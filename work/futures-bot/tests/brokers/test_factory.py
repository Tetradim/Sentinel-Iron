from __future__ import annotations

import pytest

from futures_bot.brokers.tradestation import TradeStationBroker


def _tradestation_env() -> dict[str, str]:
    return {
        "BROKER_ENV": "paper",
        "TRADESTATION_ACCESS_TOKEN": "secret-token",
        "TRADESTATION_ACCOUNT_ID": "SIM12345",
    }


def test_create_broker_returns_tradestation_adapter_from_environment():
    from futures_bot.brokers.factory import create_broker

    broker = create_broker("tradestation", _tradestation_env())

    assert isinstance(broker, TradeStationBroker)
    assert broker.config.base_url == "https://sim-api.tradestation.com/v3"
    assert broker.config.account_id == "SIM12345"


def test_create_broker_rejects_ibkr_until_tws_client_factory_is_wired():
    from futures_bot.brokers.factory import create_broker

    with pytest.raises(ValueError, match="ibkr broker adapter requires a TWS client implementation"):
        create_broker(
            "ibkr",
            {
                "BROKER_ENV": "paper",
                "IBKR_HOST": "127.0.0.1",
                "IBKR_PORT": "7497",
                "IBKR_CLIENT_ID": "101",
            },
        )


def test_create_broker_rejects_unknown_broker():
    from futures_bot.brokers.factory import create_broker

    with pytest.raises(ValueError, match="unsupported broker: unknown"):
        create_broker("unknown", _tradestation_env())
