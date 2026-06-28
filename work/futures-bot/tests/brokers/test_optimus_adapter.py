from __future__ import annotations

import base64
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

import pytest

from futures_bot.application.margin_estimates import MarginEstimateUnavailable
from futures_bot.brokers.optimus.config import BrokerEnvironment, OptimusConfig, OptimusRoute
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder
from futures_bot.ports.broker import BrokerCancellationError, BrokerConnectionError, BrokerSubmissionError


NOW = datetime(2026, 6, 28, 19, 0, tzinfo=timezone.utc)
AUTH_HEADER = f"Basic {base64.b64encode(b'user-123:secret-password').decode('ascii')}"


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
            raise AssertionError("unexpected Optimus request")
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
        from futures_bot.brokers.optimus.adapter import OptimusBridgeError

        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": dict(body) if body is not None else None,
            }
        )
        raise OptimusBridgeError(self.reason, self.status_code, self.broker_error_code)


def _config(api_url: str | None = "https://optimus-bridge.example.test/api") -> OptimusConfig:
    return OptimusConfig(
        environment=BrokerEnvironment.PAPER,
        route=OptimusRoute.RITHMIC,
        username="user-123",
        password="secret-password",
        account_id="SIM12345",
        api_url=api_url,
        app_name="futures-bot-test",
    )


def _adapter(transport: RecordingTransport, api_url: str | None = "https://optimus-bridge.example.test/api"):
    from futures_bot.brokers.optimus.adapter import OptimusBroker

    return OptimusBroker(config=_config(api_url), transport=transport, clock=lambda: NOW)


def _headers() -> dict[str, str]:
    return {
        "Authorization": AUTH_HEADER,
        "Content-Type": "application/json",
        "X-Optimus-App-Name": "futures-bot-test",
        "X-Optimus-Route": "rithmic",
    }


def test_optimus_adapter_requires_configured_bridge_url():
    with pytest.raises(ValueError, match="OPTIMUS_API_URL is required for Optimus broker adapter"):
        _adapter(RecordingTransport(()), api_url=None)


def test_optimus_connect_validates_configured_account_through_route_bridge():
    transport = RecordingTransport(({"accountId": "SIM12345", "connected": True},))
    broker = _adapter(transport)

    broker.connect()

    assert transport.requests == [
        {
            "method": "GET",
            "url": "https://optimus-bridge.example.test/api/routes/rithmic/accounts/SIM12345",
            "headers": _headers(),
            "body": None,
        }
    ]


def test_optimus_connect_rejects_mismatched_account():
    transport = RecordingTransport(({"accountId": "OTHER", "connected": True},))
    broker = _adapter(transport)

    with pytest.raises(BrokerConnectionError, match="configured Optimus account was not returned"):
        broker.connect()


def test_optimus_get_account_maps_account_payload():
    transport = RecordingTransport(
        (
            {
                "accountId": "SIM12345",
                "equity": "100000.50",
                "initialMargin": "12000.25",
                "maintenanceMargin": "9000.75",
                "buyingPower": "50000.00",
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


def test_optimus_get_positions_maps_position_payload():
    transport = RecordingTransport(
        (
            {
                "positions": [
                    {"instrument": "ES-202609-CME", "quantity": "2", "averagePrice": "5000.25"},
                    {"instrument": "NQ-202609-CME", "quantity": "-1", "averagePrice": "18000.50"},
                ]
            },
        )
    )
    broker = _adapter(transport)

    positions = broker.get_positions()

    assert positions[0].instrument_id == "ES-202609-CME"
    assert positions[0].quantity == 2
    assert positions[0].average_price == Decimal("5000.25")
    assert positions[1].instrument_id == "NQ-202609-CME"
    assert positions[1].quantity == -1
    assert positions[1].average_price == Decimal("18000.50")
    assert transport.requests[0]["url"] == (
        "https://optimus-bridge.example.test/api/routes/rithmic/accounts/SIM12345/positions"
    )


def test_optimus_submit_order_posts_limit_order_and_returns_order_id():
    transport = RecordingTransport(({"accepted": True, "orderId": "opt-order-123"},))
    broker = _adapter(transport)

    broker_order_id = broker.submit_order(
        BrokerOrder(
            instrument_id="ES-202609-CME",
            side=OrderSide.BUY,
            quantity=2,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("5000.25"),
            client_order_id="client-1",
        )
    )

    assert broker_order_id == "opt-order-123"
    assert transport.requests == [
        {
            "method": "POST",
            "url": "https://optimus-bridge.example.test/api/routes/rithmic/accounts/SIM12345/orders",
            "headers": _headers(),
            "body": {
                "accountId": "SIM12345",
                "appName": "futures-bot-test",
                "clientOrderId": "client-1",
                "instrument": "ES-202609-CME",
                "limitPrice": "5000.25",
                "orderType": "LIMIT",
                "quantity": 2,
                "route": "rithmic",
                "side": "BUY",
                "timeInForce": "DAY",
            },
        }
    ]


def test_optimus_submit_order_posts_market_order_without_limit_price():
    transport = RecordingTransport(({"accepted": True, "orderId": "opt-order-456"},))
    broker = _adapter(transport)

    broker.submit_order(
        BrokerOrder(
            instrument_id="ES-202609-CME",
            side=OrderSide.SELL,
            quantity=1,
            order_type=OrderType.MARKET,
            client_order_id="client-2",
        )
    )

    assert transport.requests[0]["body"] == {
        "accountId": "SIM12345",
        "appName": "futures-bot-test",
        "clientOrderId": "client-2",
        "instrument": "ES-202609-CME",
        "orderType": "MARKET",
        "quantity": 1,
        "route": "rithmic",
        "side": "SELL",
        "timeInForce": "DAY",
    }


def test_optimus_submit_order_maps_bridge_errors_to_submission_error():
    transport = FailingTransport("route rejected order: market closed", 400, "MARKET_CLOSED")
    broker = _adapter(transport)

    with pytest.raises(BrokerSubmissionError) as exc_info:
        broker.submit_order(
            BrokerOrder(
                instrument_id="ES-202609-CME",
                side=OrderSide.BUY,
                quantity=1,
                order_type=OrderType.MARKET,
                client_order_id="client-3",
            )
        )

    assert exc_info.value.reason == "route rejected order: market closed"
    assert exc_info.value.broker_error_code == "MARKET_CLOSED"


def test_optimus_adapter_fails_closed_for_order_margin_estimates():
    transport = RecordingTransport(())
    broker = _adapter(transport)

    with pytest.raises(MarginEstimateUnavailable) as exc_info:
        broker.estimate_order_margin(
            BrokerOrder(
                instrument_id="ES-202609-CME",
                side=OrderSide.BUY,
                quantity=1,
                order_type=OrderType.MARKET,
                client_order_id="client-4",
            )
        )

    assert exc_info.value.reason == (
        "Optimus adapter does not expose broker-provided order margin estimates"
    )
    assert transport.requests == []


def test_optimus_cancel_order_uses_cancel_endpoint():
    transport = RecordingTransport(({"accepted": True, "orderId": "opt-order-123"},))
    broker = _adapter(transport)

    broker.cancel_order("opt-order-123")

    assert transport.requests == [
        {
            "method": "POST",
            "url": "https://optimus-bridge.example.test/api/routes/rithmic/accounts/SIM12345/orders/opt-order-123/cancel",
            "headers": _headers(),
            "body": {},
        }
    ]


def test_optimus_cancel_order_maps_bridge_errors_to_cancellation_error():
    transport = FailingTransport("order is already filled", 409, "ORDER_FILLED")
    broker = _adapter(transport)

    with pytest.raises(BrokerCancellationError) as exc_info:
        broker.cancel_order("opt-order-123")

    assert exc_info.value.reason == "order is already filled"
    assert exc_info.value.broker_error_code == "ORDER_FILLED"
