from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from futures_bot.domain.portfolio import MarketSnapshot
from futures_bot.ports.audit import AuditLogPort
from futures_bot.ports.market_data import (
    HistoricalBar,
    HistoricalDataPort,
    MarketDataError,
    MarketDataPort,
)


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


@dataclass(frozen=True)
class MarketDataHistoryRequest:
    provider_name: str
    instrument_id: str
    start_day: date
    end_day: date
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.provider_name:
            raise ValueError("provider_name is required")
        if not self.instrument_id:
            raise ValueError("instrument_id is required")
        if self.start_day > self.end_day:
            raise ValueError("start_day cannot be after end_day")


@dataclass(frozen=True)
class MarketDataHistoryResult:
    received: bool
    bars: tuple[HistoricalBar, ...]
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


class MarketDataHistoryService:
    def __init__(self, provider: HistoricalDataPort, audit_log: AuditLogPort) -> None:
        self._provider = provider
        self._audit_log = audit_log

    def get_daily_bars(self, request: MarketDataHistoryRequest) -> MarketDataHistoryResult:
        try:
            bars = self._provider.get_daily_bars(
                request.instrument_id,
                request.start_day,
                request.end_day,
            )
        except MarketDataError as exc:
            self._audit_log.append(
                {
                    "type": "market_data_history_failed",
                    "timestamp": request.timestamp.isoformat(),
                    "provider": request.provider_name,
                    "instrument_id": request.instrument_id,
                    "start_day": request.start_day.isoformat(),
                    "end_day": request.end_day.isoformat(),
                    "reason": "market_data_error",
                    "detail": exc.reason,
                    "provider_error_code": exc.provider_error_code,
                }
            )
            return MarketDataHistoryResult(
                received=False,
                bars=(),
                reason="market_data_error",
                detail=exc.reason,
            )

        ordered_bars = tuple(sorted(bars, key=lambda bar: bar.day))
        rejected = self._reject_invalid_history(request, ordered_bars)
        if rejected is not None:
            return rejected

        self._audit_log.append(
            {
                "type": "market_data_history",
                "timestamp": request.timestamp.isoformat(),
                "provider": request.provider_name,
                "instrument_id": request.instrument_id,
                "start_day": request.start_day.isoformat(),
                "end_day": request.end_day.isoformat(),
                "bar_count": len(ordered_bars),
                "first_bar_day": ordered_bars[0].day.isoformat() if ordered_bars else None,
                "last_bar_day": ordered_bars[-1].day.isoformat() if ordered_bars else None,
            }
        )
        return MarketDataHistoryResult(
            received=True,
            bars=ordered_bars,
            reason=None,
            detail="historical bars received",
        )

    def _reject_invalid_history(
        self,
        request: MarketDataHistoryRequest,
        bars: tuple[HistoricalBar, ...],
    ) -> MarketDataHistoryResult | None:
        seen_days: set[date] = set()
        for bar in bars:
            if bar.instrument_id != request.instrument_id:
                detail = "historical bar instrument does not match request"
                self._audit_log.append(
                    {
                        "type": "market_data_history_rejected",
                        "timestamp": request.timestamp.isoformat(),
                        "provider": request.provider_name,
                        "instrument_id": request.instrument_id,
                        "bar_instrument_id": bar.instrument_id,
                        "bar_day": bar.day.isoformat(),
                        "reason": "instrument_mismatch",
                        "detail": detail,
                    }
                )
                return MarketDataHistoryResult(
                    received=False,
                    bars=(),
                    reason="instrument_mismatch",
                    detail=detail,
                )

            if bar.day < request.start_day or bar.day > request.end_day:
                detail = "historical bar is outside requested date range"
                self._audit_log.append(
                    {
                        "type": "market_data_history_rejected",
                        "timestamp": request.timestamp.isoformat(),
                        "provider": request.provider_name,
                        "instrument_id": request.instrument_id,
                        "bar_day": bar.day.isoformat(),
                        "reason": "history_out_of_range",
                        "detail": detail,
                    }
                )
                return MarketDataHistoryResult(
                    received=False,
                    bars=(),
                    reason="history_out_of_range",
                    detail=detail,
                )

            if bar.day in seen_days:
                detail = "historical bar day is duplicated"
                self._audit_log.append(
                    {
                        "type": "market_data_history_rejected",
                        "timestamp": request.timestamp.isoformat(),
                        "provider": request.provider_name,
                        "instrument_id": request.instrument_id,
                        "bar_day": bar.day.isoformat(),
                        "reason": "duplicate_bar_day",
                        "detail": detail,
                    }
                )
                return MarketDataHistoryResult(
                    received=False,
                    bars=(),
                    reason="duplicate_bar_day",
                    detail=detail,
                )
            seen_days.add(bar.day)

        return None
