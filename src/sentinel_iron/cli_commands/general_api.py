from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from sentinel_iron.archive_general_api import (
    ArchiveGeneralApiClient,
    GeneralApiConfigStore,
    GeneralApiDefaults,
)


def _store(config_file: str) -> GeneralApiConfigStore:
    return GeneralApiConfigStore(
        Path(config_file),
        GeneralApiDefaults(
            bot_id="sentinel-iron",
            display_name="Sentinel Iron",
            roles=("trader",),
        ),
    )


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def run_general_api(command: str | None, config_file: str, args: Any) -> int:
    store = _store(config_file)
    client = ArchiveGeneralApiClient(store)
    try:
        if command == "show":
            _print({"settings": store.public(store.load()), "contract": "archive.general.v1"})
            return 0
        if command == "configure":
            patch: dict[str, Any] = {}
            for argument, key in (
                ("base_url", "base_url"),
                ("run_id", "run_id"),
                ("participant_id", "participant_id"),
                ("api_token", "api_token"),
                ("timeout_seconds", "timeout_seconds"),
                ("starting_cash", "starting_cash"),
                ("commission_per_order", "commission_per_order"),
                ("slippage_bps", "slippage_bps"),
            ):
                value = getattr(args, argument, None)
                if value is not None:
                    patch[key] = value
            if getattr(args, "enabled", None) is not None:
                patch["enabled"] = args.enabled
            if getattr(args, "symbols", None) is not None:
                patch["subscribed_symbols"] = args.symbols.split(",")
            _print({"settings": store.public(store.save(patch))})
            return 0
        if command == "test":
            _print(client.test_connection())
            return 0
        if command == "register":
            _print(client.register())
            return 0
        if command == "account":
            _print(client.account())
            return 0
    except Exception as exc:
        print(f"General API error: {exc}", file=sys.stderr)
        return 1
    print("Choose one of: show, configure, test, register, account", file=sys.stderr)
    return 2
