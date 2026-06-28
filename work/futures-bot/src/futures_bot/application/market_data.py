from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from futures_bot.domain.portfolio import MarketSnapshot
from futures_bot.ports.audit import AuditLogPort
from futures_bot.ports.market_data import MarketDataError, MarketDataPort


@dataclass(frozen=True)
class MarketDataSnapshotRequest:
    provider_name: str
    instrument_id: str
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.provider_name:
            raise ValueError("provider_name is required")
        if not self.instrument_id:
            raise ValueError("instrument_id is required")


@dataclass(frozen=True)
class MarketDataSnapshotResult:
    received: bool
    snapshot: MarketSnapshot | None
    reason: str | None
    detail: str


class MarketDataSnapshotService:
    def __init__(self, provider: MarketDataPort, audit_log: AuditLogPort) -> None:
        self._provider = provider
        self._audit_log = audit_log

    def get_snapshot(self, request: MarketDataSnapshotRequest) -> MarketDataSnapshotResult:
        try:
            snapshot = self._provider.get_snapshot(request.instrument_id)
        except MarketDataError as exc:
            self._audit_log.append(
                {
                    "type": "market_data_snapshot_failed",
                    "timestamp": request.timestamp.isoformat(),
                    "provider": request.provider_name,
                    "instrument_id": request.instrument_id,
                    "reason": "market_data_error",
                    "detail": exc.reason,
                    "provider_error_code": exc.provider_error_code,
                }
            )
            return MarketDataSnapshotResult(
                received=False,
                snapshot=None,
                reason="market_data_error",
                detail=exc.reason,
            )

        if snapshot.instrument_id != request.instrument_id:
            detail = "market data snapshot instrument does not match request"
            self._audit_log.append(
                {
                    "type": "market_data_snapshot_rejected",
                    "timestamp": request.timestamp.isoformat(),
                    "provider": request.provider_name,
                    "instrument_id": request.instrument_id,
                    "snapshot_instrument_id": snapshot.instrument_id,
                    "reason": "instrument_mismatch",
                    "detail": detail,
                }
            )
            return MarketDataSnapshotResult(
                received=False,
                snapshot=None,
                reason="instrument_mismatch",
                detail=detail,
            )

        self._audit_log.append(
            {
                "type": "market_data_snapshot",
                "timestamp": request.timestamp.isoformat(),
                "provider": request.provider_name,
                "instrument_id": request.instrument_id,
                "snapshot_timestamp": snapshot.timestamp.isoformat(),
                "bid": str(snapshot.bid) if snapshot.bid is not None else None,
                "ask": str(snapshot.ask) if snapshot.ask is not None else None,
                "last": str(snapshot.last),
            }
        )
        return MarketDataSnapshotResult(
            received=True,
            snapshot=snapshot,
            reason=None,
            detail="snapshot received",
        )
