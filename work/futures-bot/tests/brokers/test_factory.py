from __future__ import annotations

import pytest

from futures_bot.brokers.ibkr import IbkrBroker
from futures_bot.brokers.tradestation import TradeStationBroker


def _tradestation_env() -> dict[str, str]:
    return {
        "BROKER_ENV": "paper",
        "TRADESTATION_ACCESS_TOKEN": "secret-token",
        "TRADESTATION_ACCOUNT_ID": "SIM12345",
    }


def _ninjatrader_env() -> dict[str, str]:
    return {
        "BROKER_ENV": "paper",
        "NINJATRADER_REST_URL": "https://nt-api.example.test/v1/api",
        "NINJATRADER_WS_URL": "wss://nt-stream.example.test/v1/ws",
        "NINJATRADER_ACCESS_TOKEN": "secret-token",
        "NINJATRADER_ACCOUNT_ID": "Sim101",
    }


def test_create_broker_returns_tradestation_adapter_from_environment():
    from futures_bot.brokers.factory import create_broker

    broker = create_broker("tradestation", _tradestation_env())

    assert isinstance(broker, TradeStationBroker)
    assert broker.config.base_url == "https://sim-api.tradestation.com/v3"
    assert broker.config.account_id == "SIM12345"


def test_create_broker_returns_ibkr_adapter_from_environment_with_injected_client():
    from futures_bot.brokers.factory import create_broker

    class Client:
        def connect(self, host: str, port: int, client_id: int) -> None:
            pass

        def account_summary(self) -> tuple[dict[str, object], ...]:
            return ()

        def positions(self) -> tuple[dict[str, object], ...]:
            return ()

        def next_order_id(self) -> int:
            return 1

        def place_order(
            self,
            order_id: int,
            contract: dict[str, object],
            order: dict[str, object],
        ) -> None:
            pass

        def cancel_order(self, order_id: int) -> None:
            pass

    client = Client()
    broker = create_broker(
        "ibkr",
        {
            "BROKER_ENV": "paper",
            "IBKR_HOST": "127.0.0.1",
            "IBKR_PORT": "7497",
            "IBKR_CLIENT_ID": "101",
        },
        ibkr_client_factory=lambda: client,
    )

    assert isinstance(broker, IbkrBroker)
    assert broker.config.host == "127.0.0.1"
    assert broker.config.port == 7497
    assert broker.config.client_id == 101
    assert broker.client is client


def test_create_broker_returns_ninjatrader_adapter_from_environment():
    from futures_bot.brokers.factory import create_broker
    from futures_bot.brokers.ninjatrader import NinjaTraderBroker

    broker = create_broker("ninjatrader", _ninjatrader_env())

    assert isinstance(broker, NinjaTraderBroker)
    assert broker.config.rest_url == "https://nt-api.example.test/v1/api"
    assert broker.config.websocket_url == "wss://nt-stream.example.test/v1/ws"
    assert broker.config.account_id == "Sim101"


def test_create_broker_rejects_unknown_broker():
    from futures_bot.brokers.factory import create_broker

    with pytest.raises(ValueError, match="unsupported broker: unknown"):
        create_broker("unknown", _tradestation_env())
