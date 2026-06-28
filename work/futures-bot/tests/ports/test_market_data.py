from datetime import date
from decimal import Decimal

import pytest

from futures_bot.ports.market_data import HistoricalBar, MarketDataError


def test_market_data_error_exposes_reason_and_provider_error_code():
    error = MarketDataError(
        reason="market data subscription is not active",
        provider_error_code="NO_SUBSCRIPTION",
    )

    assert str(error) == "market data subscription is not active"
    assert error.reason == "market data subscription is not active"
    assert error.provider_error_code == "NO_SUBSCRIPTION"


def test_market_data_error_requires_reason():
    with pytest.raises(ValueError, match="reason is required"):
        MarketDataError(reason="")


def test_historical_bar_rejects_invalid_ohlc_range():
    with pytest.raises(ValueError, match="high must be greater than or equal to all prices"):
        HistoricalBar(
            instrument_id="ES-202609-CME",
            day=date(2026, 9, 14),
            open=Decimal("5000"),
            high=Decimal("4999"),
            low=Decimal("4995"),
            close=Decimal("4998"),
            volume=1000,
        )


def test_historical_bar_rejects_negative_volume():
    with pytest.raises(ValueError, match="volume cannot be negative"):
        HistoricalBar(
            instrument_id="ES-202609-CME",
            day=date(2026, 9, 14),
            open=Decimal("5000"),
            high=Decimal("5005"),
            low=Decimal("4995"),
            close=Decimal("4998"),
            volume=-1,
        )
