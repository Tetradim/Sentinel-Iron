from datetime import datetime, timezone
from decimal import Decimal

from futures_bot.application.market_data import (
    MarketDataSnapshotRequest,
    MarketDataSnapshotService,
)
from futures_bot.domain.portfolio import MarketSnapshot
from futures_bot.ports.audit import InMemoryAuditLog
from futures_bot.ports.market_data import MarketDataError


NOW = datetime(2026, 6, 28, 14, 36, tzinfo=timezone.utc)


class RecordingMarketDataProvider:
    def __init__(self, snapshot: MarketSnapshot | None = None) -> None:
        self.requested_instrument_ids: list[str] = []
        self.snapshot = snapshot or MarketSnapshot(
            instrument_id="ES-202609-CME",
            bid=Decimal("5000.00"),
            ask=Decimal("5000.25"),
            last=Decimal("5000.25"),
            timestamp=NOW,
        )

    def get_snapshot(self, instrument_id: str) -> MarketSnapshot:
        self.requested_instrument_ids.append(instrument_id)
        return self.snapshot


class FailingMarketDataProvider(RecordingMarketDataProvider):
    def get_snapshot(self, instrument_id: str) -> MarketSnapshot:
        self.requested_instrument_ids.append(instrument_id)
        raise MarketDataError(
            reason="market data subscription is not active",
            provider_error_code="NO_SUBSCRIPTION",
        )


def _request(**overrides: object) -> MarketDataSnapshotRequest:
    values = {
        "provider_name": "ibkr",
        "instrument_id": "ES-202609-CME",
        "timestamp": NOW,
    }
    values.update(overrides)
    return MarketDataSnapshotRequest(**values)


def test_market_data_snapshot_service_fetches_snapshot_and_audits_quote():
    audit_log = InMemoryAuditLog()
    provider = RecordingMarketDataProvider()
    service = MarketDataSnapshotService(provider=provider, audit_log=audit_log)

    result = service.get_snapshot(_request())

    assert result.received is True
    assert result.snapshot == provider.snapshot
    assert result.reason is None
    assert result.detail == "snapshot received"
    assert provider.requested_instrument_ids == ["ES-202609-CME"]
    assert audit_log.events == (
        {
            "type": "market_data_snapshot",
            "timestamp": "2026-06-28T14:36:00+00:00",
            "provider": "ibkr",
            "instrument_id": "ES-202609-CME",
            "snapshot_timestamp": "2026-06-28T14:36:00+00:00",
            "bid": "5000.00",
            "ask": "5000.25",
            "last": "5000.25",
        },
    )


def test_market_data_snapshot_service_audits_provider_failure():
    audit_log = InMemoryAuditLog()
    provider = FailingMarketDataProvider()
    service = MarketDataSnapshotService(provider=provider, audit_log=audit_log)

    result = service.get_snapshot(_request())

    assert result.received is False
    assert result.snapshot is None
    assert result.reason == "market_data_error"
    assert result.detail == "market data subscription is not active"
    assert provider.requested_instrument_ids == ["ES-202609-CME"]
    assert audit_log.events == (
        {
            "type": "market_data_snapshot_failed",
            "timestamp": "2026-06-28T14:36:00+00:00",
            "provider": "ibkr",
            "instrument_id": "ES-202609-CME",
            "reason": "market_data_error",
            "detail": "market data subscription is not active",
            "provider_error_code": "NO_SUBSCRIPTION",
        },
    )


def test_market_data_snapshot_service_rejects_instrument_mismatch():
    audit_log = InMemoryAuditLog()
    provider = RecordingMarketDataProvider(
        snapshot=MarketSnapshot(
            instrument_id="NQ-202609-CME",
            bid=Decimal("19000.00"),
            ask=Decimal("19000.25"),
            last=Decimal("19000.25"),
            timestamp=NOW,
        )
    )
    service = MarketDataSnapshotService(provider=provider, audit_log=audit_log)

    result = service.get_snapshot(_request())

    assert result.received is False
    assert result.snapshot is None
    assert result.reason == "instrument_mismatch"
    assert result.detail == "market data snapshot instrument does not match request"
    assert audit_log.events[-1] == {
        "type": "market_data_snapshot_rejected",
        "timestamp": "2026-06-28T14:36:00+00:00",
        "provider": "ibkr",
        "instrument_id": "ES-202609-CME",
        "snapshot_instrument_id": "NQ-202609-CME",
        "reason": "instrument_mismatch",
        "detail": "market data snapshot instrument does not match request",
    }
