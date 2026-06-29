from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from futures_bot.application.broker_connection import (
    BrokerConnectionRequest,
    BrokerConnectionService,
)
from futures_bot.application.live_trading import LiveTradingGuard
from futures_bot.application.position_flattening import PositionFlatteningService
from futures_bot.application.reconciliation import ReconcilePositionsUseCase
from futures_bot.brokers.routes import create_broker_route
from futures_bot.storage.audit import JsonlAuditLog
from futures_bot.storage.positions import JsonPositionStore


FLATTEN_CONFIRMATION = "FLATTEN-LIVE-POSITIONS"


def broker_connect(broker: str | None, audit_log_path: str) -> int:
    selected_broker = (broker or os.environ.get("BROKER") or "tradestation").strip().lower()
    try:
        route = create_broker_route(selected_broker, os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    environment = os.environ.get("BROKER_ENV", "").strip().lower()
    service = BrokerConnectionService(
        broker=route.execution,
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


def reconcile(broker: str | None, internal_positions_path: str, audit_log_path: str) -> int:
    selected_broker = (broker or os.environ.get("BROKER") or "tradestation").strip().lower()
    try:
        internal_positions = JsonPositionStore(Path(internal_positions_path)).load()
        route = create_broker_route(selected_broker, os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        route.execution.connect()
        broker_positions = route.execution.get_positions()
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


def flatten(
    confirm: str,
    broker: str | None,
    audit_log_path: str,
    live_trading_activation: str | None = None,
) -> int:
    if confirm != FLATTEN_CONFIRMATION:
        print(f"flatten requires --confirm {FLATTEN_CONFIRMATION}", file=sys.stderr)
        return 2
    selected_broker = (broker or os.environ.get("BROKER") or "tradestation").strip().lower()
    environment = os.environ.get("BROKER_ENV", "").strip().lower()
    live_trading_decision = LiveTradingGuard().evaluate(
        environment,
        activation_token=live_trading_activation,
    )
    if not live_trading_decision.allowed:
        JsonlAuditLog(Path(audit_log_path)).append(
            {
                "type": "live_trading_blocked",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "broker": selected_broker,
                "environment": environment,
                "reason": live_trading_decision.reason,
                "detail": live_trading_decision.detail,
            }
        )
        print(f"live trading blocked: {live_trading_decision.detail}", file=sys.stderr)
        return 2

    try:
        route = create_broker_route(selected_broker, os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    service = PositionFlatteningService(
        broker=route.execution,
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
