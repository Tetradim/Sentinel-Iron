import pytest

from futures_bot.ports.market_data import MarketDataError


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
