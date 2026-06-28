from datetime import date, datetime, timezone
from decimal import Decimal

from futures_bot.application.market_data import (
    MarketDataHistoryRequest,
    MarketDataHistoryService,
)
from futures_bot.ports.audit import InMemoryAuditLog
from futures_bot.ports.market_data import HistoricalBar, MarketDataError


NOW = datetime(2026, 6, 28, 14, 36, tzinfo=timezone.utc)


class RecordingHistoricalDataProvider:
    def __init__(self, bars: tuple[HistoricalBar, ...] | None = None) -> None:
        self.requests: list[tuple[str, date, date]] = []
        self.bars = bars or (
            _bar("ES-202609-CME", date(2026, 9, 13), "5000"),
            _bar("ES-202609-CME", date(2026, 9, 14), "5010"),
        )

    def get_daily_bars(
        self,
        instrument_id: str,
        start_day: date,
        end_day: date,
    ) -> tuple[HistoricalBar, ...]:
        self.requests.append((instrument_id, start_day, end_day))
        return self.bars


class FailingHistoricalDataProvider(RecordingHistoricalDataProvider):
    def get_daily_bars(
        self,
        instrument_id: str,
        start_day: date,
        end_day: date,
    ) -> tuple[HistoricalBar, ...]:
        self.requests.append((instrument_id, start_day, end_day))
        raise MarketDataError(
            reason="historical data permission is not active",
            provider_error_code="NO_HISTORY_PERMISSION",
        )


def _request(**overrides: object) -> MarketDataHistoryRequest:
    values = {
        "provider_name": "tradestation",
        "instrument_id": "ES-202609-CME",
        "start_day": date(2026, 9, 13),
        "end_day": date(2026, 9, 14),
        "timestamp": NOW,
    }
    values.update(overrides)
    return MarketDataHistoryRequest(**values)


def test_market_data_history_service_fetches_bars_and_audits_result():
    audit_log = InMemoryAuditLog()
    provider = RecordingHistoricalDataProvider(
        bars=(
            _bar("ES-202609-CME", date(2026, 9, 14), "5010"),
            _bar("ES-202609-CME", date(2026, 9, 13), "5000"),
        )
    )
    service = MarketDataHistoryService(provider=provider, audit_log=audit_log)

    result = service.get_daily_bars(_request())

    assert result.received is True
    assert [bar.day for bar in result.bars] == [date(2026, 9, 13), date(2026, 9, 14)]
    assert result.reason is None
    assert result.detail == "historical bars received"
    assert provider.requests == [
        ("ES-202609-CME", date(2026, 9, 13), date(2026, 9, 14))
    ]
    assert audit_log.events == (
        {
            "type": "market_data_history",
            "timestamp": "2026-06-28T14:36:00+00:00",
            "provider": "tradestation",
            "instrument_id": "ES-202609-CME",
            "start_day": "2026-09-13",
            "end_day": "2026-09-14",
            "bar_count": 2,
            "first_bar_day": "2026-09-13",
            "last_bar_day": "2026-09-14",
        },
    )


def test_market_data_history_service_audits_provider_failure():
    audit_log = InMemoryAuditLog()
    provider = FailingHistoricalDataProvider()
    service = MarketDataHistoryService(provider=provider, audit_log=audit_log)

    result = service.get_daily_bars(_request())

    assert result.received is False
    assert result.bars == ()
    assert result.reason == "market_data_error"
    assert result.detail == "historical data permission is not active"
    assert audit_log.events == (
        {
            "type": "market_data_history_failed",
            "timestamp": "2026-06-28T14:36:00+00:00",
            "provider": "tradestation",
            "instrument_id": "ES-202609-CME",
            "start_day": "2026-09-13",
            "end_day": "2026-09-14",
            "reason": "market_data_error",
            "detail": "historical data permission is not active",
            "provider_error_code": "NO_HISTORY_PERMISSION",
        },
    )


def test_market_data_history_service_rejects_instrument_mismatch():
    audit_log = InMemoryAuditLog()
    provider = RecordingHistoricalDataProvider(
        bars=(_bar("NQ-202609-CME", date(2026, 9, 13), "19000"),)
    )
    service = MarketDataHistoryService(provider=provider, audit_log=audit_log)

    result = service.get_daily_bars(_request())

    assert result.received is False
    assert result.reason == "instrument_mismatch"
    assert result.detail == "historical bar instrument does not match request"
    assert audit_log.events[-1] == {
        "type": "market_data_history_rejected",
        "timestamp": "2026-06-28T14:36:00+00:00",
        "provider": "tradestation",
        "instrument_id": "ES-202609-CME",
        "bar_instrument_id": "NQ-202609-CME",
        "bar_day": "2026-09-13",
        "reason": "instrument_mismatch",
        "detail": "historical bar instrument does not match request",
    }


def test_market_data_history_service_rejects_out_of_range_bar():
    audit_log = InMemoryAuditLog()
    provider = RecordingHistoricalDataProvider(
        bars=(_bar("ES-202609-CME", date(2026, 9, 12), "4990"),)
    )
    service = MarketDataHistoryService(provider=provider, audit_log=audit_log)

    result = service.get_daily_bars(_request())

    assert result.received is False
    assert result.reason == "history_out_of_range"
    assert result.detail == "historical bar is outside requested date range"
    assert audit_log.events[-1] == {
        "type": "market_data_history_rejected",
        "timestamp": "2026-06-28T14:36:00+00:00",
        "provider": "tradestation",
        "instrument_id": "ES-202609-CME",
        "bar_day": "2026-09-12",
        "reason": "history_out_of_range",
        "detail": "historical bar is outside requested date range",
    }


def _bar(instrument_id: str, day: date, close: str) -> HistoricalBar:
    close_value = Decimal(close)
    return HistoricalBar(
        instrument_id=instrument_id,
        day=day,
        open=close_value - Decimal("1"),
        high=close_value + Decimal("1"),
        low=close_value - Decimal("2"),
        close=close_value,
        volume=1000,
    )
