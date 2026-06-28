from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from futures_bot.brokers.ibkr.config import load_ibkr_config

FLATTEN_CONFIRMATION = "FLATTEN-LIVE-POSITIONS"


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "config-check":
        return _config_check()
    if args.command == "reconcile":
        return _reconcile()
    if args.command == "flatten":
        return _flatten(args.confirm)

    parser.print_help(sys.stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="futures-bot")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("config-check", help="Validate broker configuration.")
    subparsers.add_parser("reconcile", help="Reconcile internal and broker positions.")

    flatten = subparsers.add_parser("flatten", help="Flatten live broker positions.")
    flatten.add_argument("--confirm", default="", help=f"Must equal {FLATTEN_CONFIRMATION}.")

    return parser


def _config_check() -> int:
    try:
        config = load_ibkr_config(os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(
        "IBKR config ok: "
        f"environment={config.environment.value} "
        f"host={config.host} "
        f"port={config.port} "
        f"client_id={config.client_id}"
    )
    return 0


def _reconcile() -> int:
    print("No live broker adapter is wired for reconciliation yet.", file=sys.stderr)
    return 1


def _flatten(confirm: str) -> int:
    if confirm != FLATTEN_CONFIRMATION:
        print(f"flatten requires --confirm {FLATTEN_CONFIRMATION}", file=sys.stderr)
        return 2
    print("No live broker adapter is wired for flatten yet.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
