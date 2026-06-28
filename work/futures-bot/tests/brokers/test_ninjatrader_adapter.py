from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

import pytest

from futures_bot.brokers.ninjatrader.config import BrokerEnvironment, NinjaTraderConfig
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder
from futures_bot.ports.broker import BrokerCancellationError, BrokerConnectionError, BrokerSubmissionError


NOW = datetime(2026, 6, 28, 18, 15, tzinfo=timezone.utc)


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
            raise AssertionError("unexpected NinjaTrader request")
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
        from futures_bot.brokers.ninjatrader.adapter import NinjaTraderHttpError

        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": dict(body) if body is not None else None,
            }
        )
        raise NinjaTraderHttpError(self.reason, self.status_code, self.broker_error_code)


def _config() -> NinjaTraderConfig:
    return NinjaTraderConfig(
        environment=BrokerEnvironment.PAPER,
        rest_url="https://nt-api.example.test/v1/api",
        websocket_url="wss://nt-stream.example.test/v1/ws",
        access_token="token-123",
        account_id="Sim101",
    )


def _adapter(transport: RecordingTransport):
    from futures_bot.brokers.ninjatrader.adapter import NinjaTraderBroker

    return NinjaTraderBroker(config=_config(), transport=transport, clock=lambda: NOW)


def test_ninjatrader_connect_validates_configured_account_with_bearer_auth():
    transport = RecordingTransport(({"account": "Sim101", "connected": True},))
    broker = _adapter(transport)

    broker.connect()

    assert transport.requests == [
        {
            "method": "GET",
            "url": "https://nt-api.example.test/v1/api/accounts/Sim101",
            "headers": {"Authorization": "Bearer token-123", "Content-Type": "application/json"},
            "body": None,
        }
    ]


def test_ninjatrader_connect_rejects_missing_configured_account():
    transport = RecordingTransport(({"account": "OtherAccount", "connected": True},))
    broker = _adapter(transport)

    with pytest.raises(BrokerConnectionError, match="configured NinjaTrader account was not returned"):
        broker.connect()


def test_ninjatrader_get_account_maps_account_snapshot_payload():
    transport = RecordingTransport(
        (
            {
                "account": "Sim101",
                "equity": "100000.50",
                "initialMargin": "12000.25",
                "maintenanceMargin": "9000.75",
                "buyingPower": "50000.00",
            },
        )
    )
    broker = _adapter(transport)

    account = broker.get_account()

    assert account.account_id == "Sim101"
    assert account.equity == Decimal("100000.50")
    assert account.initial_margin == Decimal("12000.25")
    assert account.maintenance_margin == Decimal("9000.75")
    assert account.buying_power == Decimal("50000.00")
    assert account.timestamp == NOW
    assert transport.requests[0]["url"] == "https://nt-api.example.test/v1/api/accounts/Sim101"


def test_ninjatrader_get_positions_maps_position_payload():
    transport = RecordingTransport(
        (
            {
                "positions": [
                    {"instrument": "ES 09-26", "quantity": "2", "averagePrice": "5000.25"},
                    {"instrument": "NQ 09-26", "quantity": "-1", "averagePrice": "18000.50"},
                ]
            },
        )
    )
    broker = _adapter(transport)

    positions = broker.get_positions()

    assert positions[0].instrument_id == "ES 09-26"
    assert positions[0].quantity == 2
    assert positions[0].average_price == Decimal("5000.25")
    assert positions[1].instrument_id == "NQ 09-26"
    assert positions[1].quantity == -1
    assert positions[1].average_price == Decimal("18000.50")
    assert transport.requests[0]["url"] == "https://nt-api.example.test/v1/api/accounts/Sim101/positions"


def test_ninjatrader_submit_order_posts_limit_order_and_returns_order_id():
    transport = RecordingTransport(({"success": True, "orderId": "nt-order-123"},))
    broker = _adapter(transport)

    broker_order_id = broker.submit_order(
        BrokerOrder(
            instrument_id="ES 09-26",
            side=OrderSide.BUY,
            quantity=2,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("5000.25"),
            client_order_id="client-1",
        )
    )

    assert broker_order_id == "nt-order-123"
    assert transport.requests == [
        {
            "method": "POST",
            "url": "https://nt-api.example.test/v1/api/accounts/Sim101/orders/place",
            "headers": {"Authorization": "Bearer token-123", "Content-Type": "application/json"},
            "body": {
                "action": "BUY",
                "instrument": "ES 09-26",
                "limitPrice": "5000.25",
                "orderId": "client-1",
                "orderType": "LIMIT",
                "quantity": 2,
                "timeInForce": "DAY",
            },
        }
    ]


def test_ninjatrader_submit_order_posts_market_order_without_limit_price():
    transport = RecordingTransport(({"success": True, "orderId": "nt-order-456"},))
    broker = _adapter(transport)

    broker.submit_order(
        BrokerOrder(
            instrument_id="ES 09-26",
            side=OrderSide.SELL,
            quantity=1,
            order_type=OrderType.MARKET,
            limit_price=None,
            client_order_id="client-2",
        )
    )

    assert transport.requests[0]["body"] == {
        "action": "SELL",
        "instrument": "ES 09-26",
        "orderId": "client-2",
        "orderType": "MARKET",
        "quantity": 1,
        "timeInForce": "DAY",
    }


def test_ninjatrader_submit_order_maps_http_errors_to_submission_error():
    transport = FailingTransport("order rejected: account locked", 400, "ACCOUNT_LOCKED")
    broker = _adapter(transport)

    with pytest.raises(BrokerSubmissionError) as exc_info:
        broker.submit_order(
            BrokerOrder(
                instrument_id="ES 09-26",
                side=OrderSide.BUY,
                quantity=1,
                order_type=OrderType.MARKET,
                client_order_id="client-3",
            )
        )

    assert exc_info.value.reason == "order rejected: account locked"
    assert exc_info.value.broker_error_code == "ACCOUNT_LOCKED"


def test_ninjatrader_cancel_order_uses_cancel_endpoint():
    transport = RecordingTransport(({"success": True, "orderId": "nt-order-123"},))
    broker = _adapter(transport)

    broker.cancel_order("nt-order-123")

    assert transport.requests == [
        {
            "method": "POST",
            "url": "https://nt-api.example.test/v1/api/accounts/Sim101/orders/nt-order-123/cancel",
            "headers": {"Authorization": "Bearer token-123", "Content-Type": "application/json"},
            "body": {},
        }
    ]


def test_ninjatrader_cancel_order_maps_http_errors_to_cancellation_error():
    transport = FailingTransport("order not found or already terminal", 400, "ORDER_TERMINAL")
    broker = _adapter(transport)

    with pytest.raises(BrokerCancellationError) as exc_info:
        broker.cancel_order("nt-order-123")

    assert exc_info.value.reason == "order not found or already terminal"
    assert exc_info.value.broker_error_code == "ORDER_TERMINAL"
