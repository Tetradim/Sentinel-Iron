from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from futures_bot.cli_commands.broker import FLATTEN_CONFIRMATION
from futures_bot.cli_commands.broker import broker_connect as run_broker_connect
from futures_bot.cli_commands.broker import flatten as run_flatten
from futures_bot.cli_commands.broker import reconcile as run_reconcile
from futures_bot.cli_commands.config import config_check as run_config_check
from futures_bot.cli_commands.validation import instrument_catalog as run_instrument_catalog
from futures_bot.cli_commands.validation import kill_switch as run_kill_switch
from futures_bot.cli_commands.validation import margin_schedules as run_margin_schedules


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "config-check":
        return run_config_check(args.broker)
    if args.command == "broker-connect":
        return run_broker_connect(args.broker, args.audit_log)
    if args.command == "kill-switch":
        return run_kill_switch(
            args.kill_switch_command,
            args.state_file,
            args.audit_log,
            getattr(args, "reason", None),
        )
    if args.command == "reconcile":
        return run_reconcile(args.broker, args.internal_positions, args.audit_log)
    if args.command == "margin-schedules":
        return run_margin_schedules(args.margin_schedule_command, args.schedule_file)
    if args.command == "instrument-catalog":
        return run_instrument_catalog(
            args.instrument_catalog_command,
            args.catalog_file,
            getattr(args, "trading_day", None),
        )
    if args.command == "flatten":
        return run_flatten(
            args.confirm,
            args.broker,
            args.audit_log,
            args.live_trading_activation,
        )

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

    margin_schedules = subparsers.add_parser(
        "margin-schedules",
        help="Validate operator-supplied margin schedules.",
    )
    margin_schedules.add_argument(
        "--schedule-file",
        default=os.environ.get("MARGIN_SCHEDULE_PATH", "data/margin_schedules.json"),
        help=(
            "Margin schedule JSON path. "
            "Defaults to MARGIN_SCHEDULE_PATH or data/margin_schedules.json."
        ),
    )
    margin_schedule_subparsers = margin_schedules.add_subparsers(
        dest="margin_schedule_command"
    )
    margin_schedule_subparsers.add_parser(
        "validate",
        help="Validate schedule structure and freshness without placing orders.",
    )

    instrument_catalog = subparsers.add_parser(
        "instrument-catalog",
        help="Validate operator-supplied futures instrument catalogs.",
    )
    instrument_catalog.add_argument(
        "--catalog-file",
        default=os.environ.get("INSTRUMENT_CATALOG_PATH", "data/instruments.json"),
        help=(
            "Instrument catalog JSON path. "
            "Defaults to INSTRUMENT_CATALOG_PATH or data/instruments.json."
        ),
    )
    instrument_catalog_subparsers = instrument_catalog.add_subparsers(
        dest="instrument_catalog_command"
    )
    validate_catalog = instrument_catalog_subparsers.add_parser(
        "validate",
        help="Validate catalog structure and optional trading-day safety.",
    )
    validate_catalog.add_argument(
        "--trading-day",
        default=None,
        help="Optional YYYY-MM-DD date; fails if any catalog contract cannot trade on that day.",
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
    flatten.add_argument(
        "--live-trading-activation",
        default=None,
        help="Required exact activation token when BROKER_ENV=live.",
    )

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
