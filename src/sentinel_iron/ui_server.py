from __future__ import annotations

import argparse
import contextlib
import io
import json
import mimetypes
import os
import secrets
import sys
import threading
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

UI_VERSION = "1.0.0"
ACTION_HEADER = "X-Sentinel-Iron-Action-Token"
FLATTEN_CONFIRMATION = "FLATTEN-LIVE-POSITIONS"
CLEAR_KILL_SWITCH_CONFIRMATION = "CLEAR-KILL-SWITCH"
SUPPORTED_BROKERS = ("ibkr", "tradestation", "ninjatrader", "optimus")
DEFAULT_PATHS = {
    "audit_log": ("AUDIT_LOG_PATH", "data/audit.jsonl"),
    "kill_switch": ("KILL_SWITCH_STATE_PATH", "data/kill_switch.json"),
    "internal_positions": ("INTERNAL_POSITIONS_PATH", "data/internal_positions.json"),
    "instrument_catalog": ("INSTRUMENT_CATALOG_PATH", "data/instruments.json"),
    "margin_schedules": ("MARGIN_SCHEDULE_PATH", "data/margin_schedules.json"),
    "historical_bars": ("HISTORICAL_BARS_PATH", "data/historical_bars.json"),
    "order_activity": ("ORDER_ACTIVITY_PATH", "data/order_activity.jsonl"),
    "order_lifecycles": ("ORDER_LIFECYCLE_PATH", "data/order_lifecycles.jsonl"),
    "processed_fills": ("PROCESSED_FILLS_PATH", "data/processed_fills.jsonl"),
}
CLI_LOCK = threading.Lock()


@dataclass(frozen=True)
class ServerConfig:
    repo_root: Path
    host: str
    port: int
    action_token: str
    asset_dir: Path
    poll_hint_ms: int
    allow_remote: bool


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _read_text(path: Path, max_bytes: int = 1_000_000) -> str | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        if path.stat().st_size > max_bytes:
            # Tail-ish fallback for huge files. JSON files should not be huge; JSONL is handled separately.
            with path.open("rb") as fh:
                fh.seek(max(0, path.stat().st_size - max_bytes))
                return fh.read(max_bytes).decode("utf-8", errors="replace")
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _read_json_file(path: Path, default: Any) -> tuple[Any, dict[str, Any]]:
    meta = {"path": str(path), "exists": path.exists(), "error": None}
    text = _read_text(path)
    if text is None:
        return default, meta
    try:
        return json.loads(text), meta
    except json.JSONDecodeError as exc:
        meta["error"] = f"invalid JSON: {exc}"
        return default, meta


def _read_jsonl_tail(path: Path, limit: int = 100) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta = {"path": str(path), "exists": path.exists(), "error": None, "count_read": 0}
    if not path.exists() or not path.is_file():
        return [], meta
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            # JSONL state files are usually modest. Keep the implementation conservative and dependency-free.
            lines = [line for line in fh if line.strip()]
        for line in lines[-limit:]:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    events.append(value)
                else:
                    events.append({"type": "invalid_jsonl_record", "raw": value})
            except json.JSONDecodeError as exc:
                events.append({"type": "invalid_jsonl_line", "error": str(exc), "line": line[:400]})
        meta["count_read"] = len(events)
        meta["total_lines"] = len(lines)
        return events, meta
    except OSError as exc:
        meta["error"] = str(exc)
        return [], meta


def _path_from_env(key: str, default: str, root: Path) -> Path:
    raw = os.environ.get(key, default)
    p = Path(raw)
    if not p.is_absolute():
        p = root / p
    return p


def _resolved_paths(root: Path) -> dict[str, str]:
    return {name: str(_path_from_env(env_key, default, root)) for name, (env_key, default) in DEFAULT_PATHS.items()}


def _run_cli(argv: list[str]) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    started = _now_iso()
    with CLI_LOCK:
        try:
            from sentinel_iron.cli import main as sentinel_iron_cli_main

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = int(sentinel_iron_cli_main(argv))
        except SystemExit as exc:  # defensive: current CLI returns int, but keep this robust.
            exit_code = int(exc.code or 0) if isinstance(exc.code, int) else 1
        except Exception:
            exit_code = 1
            stderr.write(traceback.format_exc())
    return {
        "argv": argv,
        "exit_code": exit_code,
        "ok": exit_code == 0,
        "stdout": stdout.getvalue().strip(),
        "stderr": stderr.getvalue().strip(),
        "started_at": started,
        "finished_at": _now_iso(),
    }


def _config_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for broker in SUPPORTED_BROKERS:
        result = _run_cli(["config-check", "--broker", broker])
        message = result["stdout"] or result["stderr"]
        checks.append(
            {
                "broker": broker,
                "ok": bool(result["ok"]),
                "exit_code": result["exit_code"],
                "message": message,
            }
        )
    return checks


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _money(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _instrument_lookup(instruments: list[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in instruments:
        if isinstance(item, dict) and isinstance(item.get("instrument_id"), str):
            out[item["instrument_id"]] = item
    return out


def _latest_lifecycles(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for rec in records:
        cid = rec.get("client_order_id")
        if isinstance(cid, str):
            latest[cid] = rec
    return list(latest.values())


def _latest_bars_by_instrument(records: list[Any], limit: int = 160) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        instrument_id = rec.get("instrument_id")
        if not isinstance(instrument_id, str):
            continue
        grouped.setdefault(instrument_id, []).append(rec)
    out: dict[str, Any] = {}
    for instrument_id, bars in grouped.items():
        bars = sorted(bars, key=lambda b: _safe_str(b.get("day")))
        out[instrument_id] = {
            "count": len(bars),
            "latest": bars[-1] if bars else None,
            "bars": bars[-limit:],
        }
    return out


def _derive_snapshot(
    env: dict[str, Any],
    kill_switch: dict[str, Any],
    positions: list[Any],
    instruments: list[Any],
    margin_schedules: list[Any],
    audit_events: list[dict[str, Any]],
    lifecycle_records: list[dict[str, Any]],
    config_checks: list[dict[str, Any]],
    historical_bars: list[Any],
) -> dict[str, Any]:
    inst_by_id = _instrument_lookup(instruments)
    today = datetime.now(timezone.utc).date()
    gross_contracts = 0
    net_contracts = 0
    delivery_watch: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    for raw in positions:
        if not isinstance(raw, dict):
            continue
        instrument_id = str(raw.get("instrument_id", ""))
        qty = int(raw.get("quantity", 0) or 0) if str(raw.get("quantity", "")).lstrip("-").isdigit() else 0
        avg = raw.get("average_price")
        inst = inst_by_id.get(instrument_id, {})
        spec = inst.get("spec", {}) if isinstance(inst.get("spec"), dict) else {}
        cal = inst.get("calendar", {}) if isinstance(inst.get("calendar"), dict) else {}
        gross_contracts += abs(qty)
        net_contracts += qty
        last_safe = _parse_date(cal.get("last_safe_trade_date"))
        days_to_safe = (last_safe - today).days if last_safe else None
        state = "cash-settled"
        settlement = spec.get("settlement_type")
        if settlement and settlement != "cash":
            state = "delivery-sensitive"
        if days_to_safe is not None and days_to_safe <= 14:
            delivery_watch.append(
                {
                    "instrument_id": instrument_id,
                    "quantity": qty,
                    "last_safe_trade_date": cal.get("last_safe_trade_date"),
                    "days_to_last_safe": days_to_safe,
                    "settlement_type": settlement,
                }
            )
        position_rows.append(
            {
                "instrument_id": instrument_id,
                "quantity": qty,
                "average_price": avg,
                "symbol": spec.get("symbol"),
                "exchange": spec.get("exchange"),
                "contract_month": spec.get("contract_month"),
                "multiplier": spec.get("multiplier"),
                "tick_size": spec.get("tick_size"),
                "settlement_type": settlement,
                "last_safe_trade_date": cal.get("last_safe_trade_date"),
                "state": state,
            }
        )

    now = datetime.now(timezone.utc)
    stale_margin: list[dict[str, Any]] = []
    margin_total_initial = 0.0
    margin_total_maintenance = 0.0
    for raw in margin_schedules:
        if not isinstance(raw, dict):
            continue
        initial = _money(raw.get("initial_margin_per_contract")) or 0.0
        maintenance = _money(raw.get("maintenance_margin_per_contract")) or 0.0
        margin_total_initial += initial
        margin_total_maintenance += maintenance
        expires = _parse_dt(raw.get("expires_at"))
        hours = (expires - now).total_seconds() / 3600 if expires else None
        if hours is not None and hours <= 8:
            stale_margin.append({**raw, "hours_to_expiry": round(hours, 2)})

    latest_lifecycle = _latest_lifecycles(lifecycle_records)
    lifecycle_counts: dict[str, int] = {}
    for row in latest_lifecycle:
        status = _safe_str(row.get("status") or "unknown")
        lifecycle_counts[status] = lifecycle_counts.get(status, 0) + 1

    config_ok = {row["broker"]: bool(row["ok"]) for row in config_checks if "broker" in row}
    active_broker = _safe_str(env.get("broker") or "tradestation").lower()
    active_config_ok = config_ok.get(active_broker, False)
    kill_active = bool(kill_switch.get("active"))
    readiness_blocks: list[str] = []
    if kill_active:
        readiness_blocks.append("kill switch active")
    if not active_config_ok:
        readiness_blocks.append(f"{active_broker or 'broker'} config invalid or incomplete")
    if not instruments:
        readiness_blocks.append("instrument catalog missing")
    if stale_margin:
        readiness_blocks.append("one or more margin schedules expire within 8h")
    if env.get("broker_env") == "live" and not os.environ.get("SENTINEL_IRON_LIVE_TRADING_ACTIVATION"):
        readiness_blocks.append("live env: activation token not present in server env")
    if not positions:
        readiness_blocks.append("internal positions unavailable or flat")

    readiness_score = max(0, 9 - len(readiness_blocks))
    last_audit_type = audit_events[-1].get("type") if audit_events else None
    latest_bars = _latest_bars_by_instrument(historical_bars)
    return {
        "active_broker": active_broker or "tradestation",
        "config_ok": config_ok,
        "active_config_ok": active_config_ok,
        "kill_switch_active": kill_active,
        "position_count": len(position_rows),
        "gross_contracts": gross_contracts,
        "net_contracts": net_contracts,
        "positions": position_rows,
        "margin_schedule_count": len(margin_schedules),
        "margin_total_initial_per_contract": round(margin_total_initial, 2),
        "margin_total_maintenance_per_contract": round(margin_total_maintenance, 2),
        "stale_margin_count": len(stale_margin),
        "stale_margin": stale_margin,
        "delivery_watch_count": len(delivery_watch),
        "delivery_watch": delivery_watch,
        "lifecycle_counts": lifecycle_counts,
        "latest_lifecycles": latest_lifecycle,
        "audit_count_tail": len(audit_events),
        "last_audit_type": last_audit_type,
        "readiness_score": readiness_score,
        "readiness_blocks": readiness_blocks,
        "readiness_ok": len(readiness_blocks) == 0,
        "historical_instruments": list(latest_bars.keys()),
        "latest_bars_by_instrument": latest_bars,
    }


def build_snapshot(config: ServerConfig, include_config_checks: bool = True) -> dict[str, Any]:
    paths = _resolved_paths(config.repo_root)
    kill_switch_raw, kill_meta = _read_json_file(Path(paths["kill_switch"]), {"active": False, "reason": None, "updated_at": None})
    positions_raw, positions_meta = _read_json_file(Path(paths["internal_positions"]), [])
    instruments_raw, instruments_meta = _read_json_file(Path(paths["instrument_catalog"]), [])
    margins_raw, margins_meta = _read_json_file(Path(paths["margin_schedules"]), [])
    historical_raw, historical_meta = _read_json_file(Path(paths["historical_bars"]), [])
    audit_events, audit_meta = _read_jsonl_tail(Path(paths["audit_log"]), 120)
    order_activity, order_activity_meta = _read_jsonl_tail(Path(paths["order_activity"]), 120)
    order_lifecycles, lifecycle_meta = _read_jsonl_tail(Path(paths["order_lifecycles"]), 240)
    processed_fills, fills_meta = _read_jsonl_tail(Path(paths["processed_fills"]), 80)

    kill_switch = kill_switch_raw if isinstance(kill_switch_raw, dict) else {"active": False, "reason": None, "updated_at": None}
    positions = positions_raw if isinstance(positions_raw, list) else []
    instruments = instruments_raw if isinstance(instruments_raw, list) else []
    margins = margins_raw if isinstance(margins_raw, list) else []
    historical = historical_raw if isinstance(historical_raw, list) else []
    config_checks = _config_checks() if include_config_checks else []
    env = {
        "broker": (os.environ.get("BROKER") or "tradestation").strip().lower(),
        "broker_env": (os.environ.get("BROKER_ENV") or "").strip().lower(),
        "ui_host": config.host,
        "ui_port": config.port,
        "repo_root": str(config.repo_root),
        "python": sys.version.split()[0],
    }
    derived = _derive_snapshot(env, kill_switch, positions, instruments, margins, audit_events, order_lifecycles, config_checks, historical)
    return {
        "ok": True,
        "ui_version": UI_VERSION,
        "timestamp": _now_iso(),
        "poll_hint_ms": config.poll_hint_ms,
        "environment": env,
        "paths": paths,
        "path_status": {
            "kill_switch": kill_meta,
            "internal_positions": positions_meta,
            "instrument_catalog": instruments_meta,
            "margin_schedules": margins_meta,
            "historical_bars": historical_meta,
            "audit_log": audit_meta,
            "order_activity": order_activity_meta,
            "order_lifecycles": lifecycle_meta,
            "processed_fills": fills_meta,
        },
        "config_checks": config_checks,
        "kill_switch": kill_switch,
        "internal_positions": positions,
        "instrument_catalog": instruments,
        "margin_schedules": margins,
        "historical_bars": {
            "count": len(historical),
            "latest_by_instrument": derived.get("latest_bars_by_instrument", {}),
        },
        "order_activity": order_activity,
        "order_lifecycles": order_lifecycles,
        "processed_fills": processed_fills,
        "audit_events": audit_events,
        "derived": derived,
    }


class SentinelIronUiHandler(BaseHTTPRequestHandler):
    server_version = f"SentinelIronUI/{UI_VERSION}"

    @property
    def cfg(self) -> ServerConfig:
        return self.server.config  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

    def _send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:%s" % self.cfg.port)
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, {ACTION_HEADER}")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(min(length, 2_000_000)) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _check_action_token(self) -> bool:
        sent = self.headers.get(ACTION_HEADER, "")
        return bool(sent) and secrets.compare_digest(sent, self.cfg.action_token)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:%s" % self.cfg.port)
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, {ACTION_HEADER}")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            index_path = self.cfg.asset_dir / "index.html"
            html = index_path.read_text(encoding="utf-8")
            html = html.replace("__SENTINEL_IRON_UI_ACTION_TOKEN__", self.cfg.action_token)
            html = html.replace("__SENTINEL_IRON_UI_POLL_MS__", str(self.cfg.poll_hint_ms))
            self._send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/health":
            self._send_json(
                {
                    "ok": True,
                    "ui_version": UI_VERSION,
                    "timestamp": _now_iso(),
                    "repo_root": str(self.cfg.repo_root),
                    "host": self.cfg.host,
                    "port": self.cfg.port,
                }
            )
            return
        if path == "/api/snapshot":
            qs = parse_qs(parsed.query)
            include_config_checks = qs.get("config", ["1"])[0] != "0"
            self._send_json(build_snapshot(self.cfg, include_config_checks=include_config_checks))
            return
        if path.startswith("/assets/"):
            relative = path.removeprefix("/assets/")
            asset = (self.cfg.asset_dir / relative).resolve()
            if self.cfg.asset_dir.resolve() in asset.parents and asset.exists() and asset.is_file():
                ctype = mimetypes.guess_type(str(asset))[0] or "application/octet-stream"
                self._send_bytes(asset.read_bytes(), ctype)
                return
        self._send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/actions/"):
            self._send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not self._check_action_token():
            self._send_json({"ok": False, "error": f"missing or invalid {ACTION_HEADER}"}, HTTPStatus.FORBIDDEN)
            return
        try:
            body = self._read_body_json()
            result = self._dispatch_action(parsed.path, body)
            status = HTTPStatus.OK if result.get("ok", False) else HTTPStatus.BAD_REQUEST
            self._send_json(result, status)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._send_json({"ok": False, "error": traceback.format_exc()}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _dispatch_action(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        paths = _resolved_paths(self.cfg.repo_root)
        broker = _safe_str(body.get("broker") or os.environ.get("BROKER") or "tradestation").strip().lower()
        if broker not in SUPPORTED_BROKERS:
            raise ValueError(f"unsupported broker: {broker}")

        if path == "/api/actions/broker-connect":
            cli = _run_cli(["broker-connect", "--broker", broker, "--audit-log", paths["audit_log"]])
            return self._action_result("broker-connect", cli)

        if path == "/api/actions/reconcile":
            cli = _run_cli([
                "reconcile",
                "--broker",
                broker,
                "--internal-positions",
                paths["internal_positions"],
                "--audit-log",
                paths["audit_log"],
            ])
            return self._action_result("reconcile", cli)

        if path == "/api/actions/validate-catalog":
            args = ["instrument-catalog", "--catalog-file", paths["instrument_catalog"], "validate"]
            trading_day = _safe_str(body.get("trading_day") or "").strip()
            if trading_day:
                args += ["--trading-day", trading_day]
            cli = _run_cli(args)
            return self._action_result("validate-catalog", cli)

        if path == "/api/actions/validate-margin-schedules":
            cli = _run_cli(["margin-schedules", "--schedule-file", paths["margin_schedules"], "validate"])
            return self._action_result("validate-margin-schedules", cli)

        if path == "/api/actions/kill-switch/activate":
            reason = _safe_str(body.get("reason") or "").strip()
            if len(reason) < 3:
                raise ValueError("kill-switch activation requires a non-empty operator reason")
            cli = _run_cli([
                "kill-switch",
                "--state-file",
                paths["kill_switch"],
                "--audit-log",
                paths["audit_log"],
                "activate",
                "--reason",
                reason,
            ])
            return self._action_result("kill-switch/activate", cli)

        if path == "/api/actions/kill-switch/clear":
            confirm = _safe_str(body.get("confirm") or "").strip()
            if confirm != CLEAR_KILL_SWITCH_CONFIRMATION:
                raise ValueError(f"clear requires exact confirmation: {CLEAR_KILL_SWITCH_CONFIRMATION}")
            cli = _run_cli([
                "kill-switch",
                "--state-file",
                paths["kill_switch"],
                "--audit-log",
                paths["audit_log"],
                "clear",
            ])
            return self._action_result("kill-switch/clear", cli)

        if path == "/api/actions/flatten":
            confirm = _safe_str(body.get("confirm") or "").strip()
            if confirm != FLATTEN_CONFIRMATION:
                raise ValueError(f"flatten requires exact confirmation: {FLATTEN_CONFIRMATION}")
            args = ["flatten", "--broker", broker, "--audit-log", paths["audit_log"], "--confirm", FLATTEN_CONFIRMATION]
            live_activation = _safe_str(body.get("live_trading_activation") or "").strip()
            if live_activation:
                args += ["--live-trading-activation", live_activation]
            cli = _run_cli(args)
            return self._action_result("flatten", cli)

        raise ValueError(f"unsupported action route: {path}")

    def _action_result(self, action: str, cli: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": bool(cli.get("ok")),
            "action": action,
            "cli": cli,
            "snapshot": build_snapshot(self.cfg, include_config_checks=True),
        }


class SentinelIronUiServer(ThreadingHTTPServer):
    config: ServerConfig


def run_server(config: ServerConfig) -> None:
    server = SentinelIronUiServer((config.host, config.port), SentinelIronUiHandler)
    server.config = config
    url = f"http://{config.host}:{config.port}"
    print(f"Sentinel Iron UI server {UI_VERSION} listening on {url}")
    print(f"Repo root: {config.repo_root}")
    print("Open the URL above. State-changing UI calls are protected with an in-page action token.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSentinel Iron UI server stopped.")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sentinel_iron.ui_server")
    parser.add_argument("--host", default=os.environ.get("SENTINEL_IRON_UI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SENTINEL_IRON_UI_PORT", "8765")))
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("SENTINEL_IRON_REPO_ROOT", os.getcwd()),
        help="Repository root used to resolve data/*.json and data/*.jsonl paths.",
    )
    parser.add_argument(
        "--poll-ms",
        type=int,
        default=int(os.environ.get("SENTINEL_IRON_UI_POLL_MS", "2500")),
        help="UI polling hint in milliseconds.",
    )
    parser.add_argument(
        "--action-token",
        default=os.environ.get("SENTINEL_IRON_UI_ACTION_TOKEN"),
        help="Optional state-changing API token. A random token is generated when omitted.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow binding to non-loopback interfaces. Not recommended for live-capable operator actions.",
    )
    args = parser.parse_args(argv)

    host = args.host.strip()
    if host not in {"127.0.0.1", "localhost", "::1"} and not args.allow_remote:
        print("Refusing non-loopback host without --allow-remote.", file=sys.stderr)
        return 2

    asset_dir = Path(__file__).with_name("ui_assets")
    if not (asset_dir / "index.html").exists():
        print(f"UI asset not found: {asset_dir / 'index.html'}", file=sys.stderr)
        return 2

    token = args.action_token or secrets.token_urlsafe(32)
    config = ServerConfig(
        repo_root=Path(args.repo_root).resolve(),
        host=host,
        port=args.port,
        action_token=token,
        asset_dir=asset_dir,
        poll_hint_ms=max(750, int(args.poll_ms)),
        allow_remote=bool(args.allow_remote),
    )
    run_server(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
