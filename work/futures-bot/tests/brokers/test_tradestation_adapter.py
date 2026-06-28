from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

import pytest

from futures_bot.brokers.tradestation.config import BrokerEnvironment, TradeStationConfig
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder
from futures_bot.ports.broker import BrokerCancellationError, BrokerConnectionError, BrokerSubmissionError


NOW = datetime(2026, 6, 28, 15, 30, tzinfo=timezone.utc)


class RecordingTransport:
    def __init__(self, responses: tuple[Mapping[str, object] | None, ...]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None = None,
    ) -> Mapping[str, object] | None:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": dict(body) if body is not None else None,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected TradeStation request")
        return self.responses.pop(0)


class FailingTransport(RecordingTransport):
    def __init__(self, reason: str, status_code: int = 400, broker_error_code: str = "BAD") -> None:
        super().__init__(())
        self.reason = reason
        self.status_code = status_code
        self.broker_error_code = broker_error_code

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None = None,
    ) -> Mapping[str, object] | None:
        from futures_bot.brokers.tradestation.adapter import TradeStationHttpError

        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": dict(body) if body is not None else None,
            }
        )
        raise TradeStationHttpError(self.reason, self.status_code, self.broker_error_code)


def _config() -> TradeStationConfig:
    return TradeStationConfig(
        environment=BrokerEnvironment.PAPER,
        base_url="https://sim-api.tradestation.com/v3",
        access_token="token-123",
        account_id="SIM12345",
    )


def _adapter(transport: RecordingTransport):
    from futures_bot.brokers.tradestation.adapter import TradeStationBroker

    return TradeStationBroker(config=_config(), transport=transport, clock=lambda: NOW)


def test_tradestation_connect_validates_configured_account_with_bearer_auth():
    transport = RecordingTransport(
        (
            {
                "Accounts": [
                    {"AccountID": "SIM12345", "AccountType": "Futures"},
                ]
            },
        )
    )
    broker = _adapter(transport)

    broker.connect()

    assert transport.requests == [
        {
            "method": "GET",
            "url": "https://sim-api.tradestation.com/v3/brokerage/accounts",
            "headers": {"Authorization": "Bearer token-123", "Content-Type": "application/json"},
            "body": None,
        }
    ]


def test_tradestation_connect_rejects_missing_configured_account():
    transport = RecordingTransport(({"Accounts": [{"AccountID": "OTHER"}]},))
    broker = _adapter(transport)

    with pytest.raises(BrokerConnectionError, match="configured TradeStation account was not returned"):
        broker.connect()


def test_tradestation_get_account_maps_balance_payload():
    transport = RecordingTransport(
        (
            {
                "Balances": [
                    {
                        "AccountID": "SIM12345",
                        "Equity": "100000.50",
                        "InitialMargin": "12000.25",
                        "MaintenanceMargin": "9000.75",
                        "BuyingPower": "50000.00",
                    }
                ]
            },
        )
    )
    broker = _adapter(transport)

    account = broker.get_account()

    assert account.account_id == "SIM12345"
    assert account.equity == Decimal("100000.50")
    assert account.initial_margin == Decimal("12000.25")
    assert account.maintenance_margin == Decimal("9000.75")
    assert account.buying_power == Decimal("50000.00")
    assert account.timestamp == NOW
    assert transport.requests[0]["url"] == (
        "https://sim-api.tradestation.com/v3/brokerage/accounts/SIM12345/balances"
    )


def test_tradestation_get_positions_maps_long_and_short_payloads():
    transport = RecordingTransport(
        (
            {
                "Positions": [
                    {
                        "AccountID": "SIM12345",
                        "Symbol": "@ESU26",
                        "Quantity": "2",
                        "AveragePrice": "5000.25",
                        "LongShort": "Long",
                    },
                    {
                        "AccountID": "SIM12345",
                        "Symbol": "@NQU26",
                        "Quantity": "1",
                        "AveragePrice": "18000.50",
                        "LongShort": "Short",
                    },
                ]
            },
        )
    )
    broker = _adapter(transport)

    positions = broker.get_positions()

    assert positions[0].instrument_id == "@ESU26"
    assert positions[0].quantity == 2
    assert positions[0].average_price == Decimal("5000.25")
    assert positions[1].instrument_id == "@NQU26"
    assert positions[1].quantity == -1
    assert positions[1].average_price == Decimal("18000.50")
    assert transport.requests[0]["url"] == (
        "https://sim-api.tradestation.com/v3/brokerage/accounts/SIM12345/positions"
    )


def test_tradestation_submit_order_posts_limit_order_and_returns_order_id():
    transport = RecordingTransport(({"Orders": [{"OrderID": "987654321"}]},))
    broker = _adapter(transport)

    broker_order_id = broker.submit_order(
        BrokerOrder(
            instrument_id="@ESU26",
            side=OrderSide.BUY,
            quantity=2,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("5000.25"),
            client_order_id="client-1",
        )
    )

    assert broker_order_id == "987654321"
    assert transport.requests == [
        {
            "method": "POST",
            "url": "https://sim-api.tradestation.com/v3/orderexecution/orders",
            "headers": {"Authorization": "Bearer token-123", "Content-Type": "application/json"},
            "body": {
                "AccountID": "SIM12345",
                "LimitPrice": "5000.25",
                "OrderType": "Limit",
                "Quantity": "2",
                "Symbol": "@ESU26",
                "TimeInForce": {"Duration": "DAY"},
                "TradeAction": "BUY",
            },
        }
    ]


def test_tradestation_submit_order_maps_http_errors_to_submission_error():
    transport = FailingTransport("order rejected: market closed", 400, "MarketClosed")
    broker = _adapter(transport)

    with pytest.raises(BrokerSubmissionError) as exc_info:
        broker.submit_order(
            BrokerOrder(
                instrument_id="@ESU26",
                side=OrderSide.SELL,
                quantity=1,
                order_type=OrderType.MARKET,
                limit_price=None,
                client_order_id="client-2",
            )
        )

    assert exc_info.value.reason == "order rejected: market closed"
    assert exc_info.value.broker_error_code == "MarketClosed"


def test_tradestation_cancel_order_uses_delete_endpoint():
    transport = RecordingTransport((None,))
    broker = _adapter(transport)

    broker.cancel_order("987654321")

    assert transport.requests == [
        {
            "method": "DELETE",
            "url": "https://sim-api.tradestation.com/v3/orderexecution/orders/987654321",
            "headers": {"Authorization": "Bearer token-123", "Content-Type": "application/json"},
            "body": None,
        }
    ]


def test_tradestation_cancel_order_maps_http_errors_to_cancellation_error():
    transport = FailingTransport("order is already filled", 409, "OrderFilled")
    broker = _adapter(transport)

    with pytest.raises(BrokerCancellationError) as exc_info:
        broker.cancel_order("987654321")

    assert exc_info.value.reason == "order is already filled"
    assert exc_info.value.broker_error_code == "OrderFilled"
