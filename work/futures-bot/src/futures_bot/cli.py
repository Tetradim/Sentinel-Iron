from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from futures_bot.application.broker_connection import (
    BrokerConnectionRequest,
    BrokerConnectionService,
)
from futures_bot.application.kill_switch import KillSwitchService
from futures_bot.application.position_flattening import PositionFlatteningService
from futures_bot.application.reconciliation import ReconcilePositionsUseCase
from futures_bot.brokers.factory import create_broker
from futures_bot.brokers.ibkr.config import load_ibkr_config
from futures_bot.brokers.ninjatrader.config import load_ninjatrader_config
from futures_bot.brokers.optimus.config import load_optimus_config
from futures_bot.brokers.tradestation.config import load_tradestation_config
from futures_bot.storage.audit import JsonlAuditLog
from futures_bot.storage.kill_switch import JsonKillSwitchStore
from futures_bot.storage.positions import JsonPositionStore

FLATTEN_CONFIRMATION = "FLATTEN-LIVE-POSITIONS"


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "config-check":
        return _config_check(args.broker)
    if args.command == "broker-connect":
        return _broker_connect(args.broker, args.audit_log)
    if args.command == "kill-switch":
        return _kill_switch(
            args.kill_switch_command,
            args.state_file,
            args.audit_log,
            getattr(args, "reason", None),
        )
    if args.command == "reconcile":
        return _reconcile(args.broker, args.internal_positions, args.audit_log)
    if args.command == "flatten":
        return _flatten(args.confirm, args.broker, args.audit_log)

    parser.print_help(sys.stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="futures-bot")
    subparsers = parser.add_subparsers(dest="command")

    config_check = subparsers.add_parser("config-check", help="Validate broker configuration.")
    config_check.add_argument(
        "--broker",
        default=None,
        help=(
            "Broker to validate: ibkr, tradestation, ninjatrader, or optimus. "
            "Defaults to BROKER or ibkr."
        ),
    )
    reconcile = subparsers.add_parser("reconcile", help="Reconcile internal and broker positions.")
    reconcile.add_argument(
        "--broker",
        default=None,
        help="Broker to reconcile against. Defaults to BROKER or tradestation.",
    )
    reconcile.add_argument(
        "--internal-positions",
        default=os.environ.get("INTERNAL_POSITIONS_PATH", "data/internal_positions.json"),
        help=(
            "Internal position snapshot JSON path. "
            "Defaults to INTERNAL_POSITIONS_PATH or data/internal_positions.json."
        ),
    )
    reconcile.add_argument(
        "--audit-log",
        default=os.environ.get("AUDIT_LOG_PATH", "data/audit.jsonl"),
        help="JSONL audit log path. Defaults to AUDIT_LOG_PATH or data/audit.jsonl.",
    )

    broker_connect = subparsers.add_parser(
        "broker-connect",
        help="Connect to a configured broker and fetch account state without placing orders.",
    )
    broker_connect.add_argument(
        "--broker",
        default=None,
        help=(
            "Broker to connect: tradestation. Defaults to BROKER or tradestation. "
            "IBKR, NinjaTrader, and Optimus require their real adapters first."
        ),
    )
    broker_connect.add_argument(
        "--audit-log",
        default=os.environ.get("AUDIT_LOG_PATH", "data/audit.jsonl"),
        help="JSONL audit log path. Defaults to AUDIT_LOG_PATH or data/audit.jsonl.",
    )

    kill_switch = subparsers.add_parser(
        "kill-switch",
        help="Inspect or change the persisted operator kill switch.",
    )
    kill_switch.add_argument(
        "--state-file",
        default=os.environ.get("KILL_SWITCH_STATE_PATH", "data/kill_switch.json"),
        help="Kill-switch state path. Defaults to KILL_SWITCH_STATE_PATH or data/kill_switch.json.",
    )
    kill_switch.add_argument(
        "--audit-log",
        default=os.environ.get("AUDIT_LOG_PATH", "data/audit.jsonl"),
        help="JSONL audit log path. Defaults to AUDIT_LOG_PATH or data/audit.jsonl.",
    )
    kill_switch_subparsers = kill_switch.add_subparsers(dest="kill_switch_command")
    kill_switch_subparsers.add_parser("status", help="Show current kill-switch state.")
    activate = kill_switch_subparsers.add_parser("activate", help="Block new trading until cleared.")
    activate.add_argument("--reason", required=True, help="Operator reason for activating the kill switch.")
    kill_switch_subparsers.add_parser("clear", help="Clear the kill switch.")

    flatten = subparsers.add_parser("flatten", help="Flatten live broker positions.")
    flatten.add_argument(
        "--broker",
        default=None,
        help="Broker to flatten through. Defaults to BROKER or tradestation.",
    )
    flatten.add_argument(
        "--audit-log",
        default=os.environ.get("AUDIT_LOG_PATH", "data/audit.jsonl"),
        help="JSONL audit log path. Defaults to AUDIT_LOG_PATH or data/audit.jsonl.",
    )
    flatten.add_argument("--confirm", default="", help=f"Must equal {FLATTEN_CONFIRMATION}.")

    return parser


def _config_check(broker: str | None) -> int:
    selected_broker = (broker or os.environ.get("BROKER") or "ibkr").strip().lower()
    try:
        message = _load_config_message(selected_broker)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(message)
    return 0


def _load_config_message(broker: str) -> str:
    if broker == "ibkr":
        config = load_ibkr_config(os.environ)
        return (
            "IBKR config ok: "
            f"environment={config.environment.value} "
            f"host={config.host} "
            f"port={config.port} "
            f"client_id={config.client_id}"
        )
    if broker == "tradestation":
        config = load_tradestation_config(os.environ)
        return (
            "TradeStation config ok: "
            f"environment={config.environment.value} "
            f"base_url={config.base_url} "
            f"account_id={config.account_id}"
        )
    if broker == "ninjatrader":
        config = load_ninjatrader_config(os.environ)
        return (
            "NinjaTrader config ok: "
            f"environment={config.environment.value} "
            f"rest_url={config.rest_url} "
            f"websocket_url={config.websocket_url} "
            f"account_id={config.account_id}"
        )
    if broker == "optimus":
        config = load_optimus_config(os.environ)
        return (
            "Optimus config ok: "
            f"environment={config.environment.value} "
            f"route={config.route.value} "
            f"account_id={config.account_id} "
            f"api_url={config.api_url or 'not-set'}"
        )
    raise ValueError(f"unsupported broker: {broker}")


def _broker_connect(broker: str | None, audit_log_path: str) -> int:
    selected_broker = (broker or os.environ.get("BROKER") or "tradestation").strip().lower()
    try:
        configured_broker = create_broker(selected_broker, os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    environment = os.environ.get("BROKER_ENV", "").strip().lower()
    service = BrokerConnectionService(
        broker=configured_broker,
        audit_log=JsonlAuditLog(Path(audit_log_path)),
    )
    result = service.connect(
        BrokerConnectionRequest(
            broker_name=selected_broker,
            environment=environment,
            timestamp=datetime.now(timezone.utc),
        )
    )
    if not result.connected or result.account is None:
        print(f"broker connect failed: {result.reason}", file=sys.stderr)
        return 1

    print(
        "broker connected: "
        f"broker={selected_broker} "
        f"account_id={result.account.account_id} "
        f"positions={len(result.positions)}"
    )
    return 0


def _kill_switch(
    command: str | None,
    state_file_path: str,
    audit_log_path: str,
    reason: str | None,
) -> int:
    if command is None:
        print("kill-switch requires a subcommand: status, activate, or clear", file=sys.stderr)
        return 2

    service = KillSwitchService(
        store=JsonKillSwitchStore(Path(state_file_path)),
        audit_log=JsonlAuditLog(Path(audit_log_path)),
    )
    try:
        if command == "status":
            state = service.status()
        elif command == "activate":
            state = service.activate(reason=reason or "", timestamp=datetime.now(timezone.utc))
        elif command == "clear":
            state = service.clear(timestamp=datetime.now(timezone.utc))
        else:
            print(f"unsupported kill-switch command: {command}", file=sys.stderr)
            return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if state.active:
        print(f"kill switch active: reason={state.reason}")
    else:
        print("kill switch inactive")
    return 0


def _reconcile(broker: str | None, internal_positions_path: str, audit_log_path: str) -> int:
    selected_broker = (broker or os.environ.get("BROKER") or "tradestation").strip().lower()
    try:
        internal_positions = JsonPositionStore(Path(internal_positions_path)).load()
        configured_broker = create_broker(selected_broker, os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        configured_broker.connect()
        broker_positions = configured_broker.get_positions()
    except Exception as exc:
        print(f"reconcile failed: {exc}", file=sys.stderr)
        return 1

    result = ReconcilePositionsUseCase(
        audit_log=JsonlAuditLog(Path(audit_log_path)),
    ).execute(
        internal_positions=internal_positions,
        broker_positions=broker_positions,
    )
    if not result.positions_reconciled:
        print(f"positions not reconciled: {'; '.join(result.mismatches)}", file=sys.stderr)
        return 1

    print(
        "positions reconciled: "
        f"broker={selected_broker} "
        f"broker_positions={len(broker_positions)}"
    )
    return 0


def _flatten(confirm: str, broker: str | None, audit_log_path: str) -> int:
    if confirm != FLATTEN_CONFIRMATION:
        print(f"flatten requires --confirm {FLATTEN_CONFIRMATION}", file=sys.stderr)
        return 2
    selected_broker = (broker or os.environ.get("BROKER") or "tradestation").strip().lower()
    try:
        configured_broker = create_broker(selected_broker, os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    service = PositionFlatteningService(
        broker=configured_broker,
        audit_log=JsonlAuditLog(Path(audit_log_path)),
    )
    try:
        result = service.flatten(timestamp=datetime.now(timezone.utc))
    except Exception as exc:
        print(f"flatten failed: {exc}", file=sys.stderr)
        return 1

    print(
        "flatten submitted: "
        f"broker={selected_broker} "
        f"submitted={result.submitted_count} "
        f"failed={result.failed_count} "
        f"skipped={result.skipped_count}"
    )
    return 0 if result.failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
