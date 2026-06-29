from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

import pytest

from futures_bot.application.margin_estimates import MarginEstimateUnavailable
from futures_bot.brokers.tradovate.config import BrokerEnvironment, TradovateConfig
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder
from futures_bot.ports.broker import (
    BrokerCancellationError,
    BrokerConnectionError,
    BrokerSubmissionError,
)
from futures_bot.ports.market_data import MarketDataError


NOW = datetime(2026, 6, 29, 1, 42, tzinfo=timezone.utc)


class RecordingTransport:
    def __init__(self, responses: tuple[object | None, ...]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None = None,
    ) -> object | None:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": dict(body) if body is not None else None,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected Tradovate request")
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
    ) -> object | None:
        from futures_bot.brokers.tradovate.adapter import TradovateHttpError

        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": dict(body) if body is not None else None,
            }
        )
        raise TradovateHttpError(self.reason, self.status_code, self.broker_error_code)


def _config() -> TradovateConfig:
    return TradovateConfig(
        environment=BrokerEnvironment.PAPER,
        base_url="https://demo.tradovateapi.com/v1",
        access_token="token-123",
        account_id=123456,
        account_spec="DEMO123456",
    )


def _adapter(transport: RecordingTransport):
    from futures_bot.brokers.tradovate.adapter import TradovateBroker

    return TradovateBroker(config=_config(), transport=transport, clock=lambda: NOW)


def test_tradovate_connect_validates_configured_account_with_bearer_auth():
    transport = RecordingTransport(
        (
            [
                {"id": 123456, "name": "DEMO123456", "active": True},
            ],
        )
    )
    broker = _adapter(transport)

    broker.connect()

    assert transport.requests == [
        {
            "method": "GET",
            "url": "https://demo.tradovateapi.com/v1/account/list",
            "headers": {"Authorization": "Bearer token-123", "Content-Type": "application/json"},
            "body": None,
        }
    ]


def test_tradovate_connect_rejects_missing_configured_account():
    transport = RecordingTransport(([{"id": 999999, "name": "OTHER"}],))
    broker = _adapter(transport)

    with pytest.raises(BrokerConnectionError, match="configured Tradovate account was not returned"):
        broker.connect()


def test_tradovate_get_account_maps_cash_balance_payload():
    transport = RecordingTransport(
        (
            [
                {
                    "accountId": 123456,
                    "netLiq": "100000.50",
                    "initialMargin": "12000.25",
                    "maintenanceMargin": "9000.75",
                    "riskExcess": "50000.00",
                    "timestamp": "2026-06-29T01:42:00Z",
                }
            ],
        )
    )
    broker = _adapter(transport)

    account = broker.get_account()

    assert account.account_id == "123456"
    assert account.equity == Decimal("100000.50")
    assert account.initial_margin == Decimal("12000.25")
    assert account.maintenance_margin == Decimal("9000.75")
    assert account.buying_power == Decimal("50000.00")
    assert account.timestamp == NOW
    assert transport.requests[0]["url"] == "https://demo.tradovateapi.com/v1/cashBalance/list"


def test_tradovate_get_positions_filters_account_and_maps_net_positions():
    transport = RecordingTransport(
        (
            [
                {
                    "accountId": 123456,
                    "contractName": "ESU6",
                    "netPos": 2,
                    "netPrice": "5000.25",
                },
                {
                    "accountId": 999999,
                    "contractName": "NQU6",
                    "netPos": 1,
                    "netPrice": "18000.50",
                },
            ],
        )
    )
    broker = _adapter(transport)

    positions = broker.get_positions()

    assert positions == (
        type(positions[0])(
            instrument_id="ESU6",
            quantity=2,
            average_price=Decimal("5000.25"),
        ),
    )
    assert transport.requests[0]["url"] == "https://demo.tradovateapi.com/v1/position/list"


def test_tradovate_submit_order_posts_limit_order_and_returns_order_id():
    transport = RecordingTransport(({"orderId": 987654321},))
    broker = _adapter(transport)

    broker_order_id = broker.submit_order(
        BrokerOrder(
            instrument_id="ESU6",
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
            "url": "https://demo.tradovateapi.com/v1/order/placeorder",
            "headers": {"Authorization": "Bearer token-123", "Content-Type": "application/json"},
            "body": {
                "accountId": 123456,
                "accountSpec": "DEMO123456",
                "action": "Buy",
                "clOrdId": "client-1",
                "isAutomated": True,
                "orderQty": 2,
                "orderType": "Limit",
                "price": "5000.25",
                "symbol": "ESU6",
                "timeInForce": "Day",
            },
        }
    ]


def test_tradovate_submit_order_maps_http_errors_to_submission_error():
    transport = FailingTransport("order rejected: market closed", 400, "MarketClosed")
    broker = _adapter(transport)

    with pytest.raises(BrokerSubmissionError) as exc_info:
        broker.submit_order(
            BrokerOrder(
                instrument_id="ESU6",
                side=OrderSide.SELL,
                quantity=1,
                order_type=OrderType.MARKET,
                client_order_id="client-2",
            )
        )

    assert exc_info.value.reason == "order rejected: market closed"
    assert exc_info.value.broker_error_code == "MarketClosed"


def test_tradovate_cancel_order_posts_cancel_request():
    transport = RecordingTransport(({"status": "ok"},))
    broker = _adapter(transport)

    broker.cancel_order("987654321")

    assert transport.requests == [
        {
            "method": "POST",
            "url": "https://demo.tradovateapi.com/v1/order/cancelorder",
            "headers": {"Authorization": "Bearer token-123", "Content-Type": "application/json"},
            "body": {
                "accountId": 123456,
                "accountSpec": "DEMO123456",
                "orderId": 987654321,
            },
        }
    ]


def test_tradovate_cancel_order_maps_http_errors_to_cancellation_error():
    transport = FailingTransport("too late to cancel", 400, "TooLateToCancel")
    broker = _adapter(transport)

    with pytest.raises(BrokerCancellationError) as exc_info:
        broker.cancel_order("987654321")

    assert exc_info.value.reason == "too late to cancel"
    assert exc_info.value.broker_error_code == "TooLateToCancel"


def test_tradovate_estimate_order_margin_fails_closed_until_verified_endpoint_exists():
    broker = _adapter(RecordingTransport(()))

    with pytest.raises(MarginEstimateUnavailable, match="does not expose verified order margin estimates"):
        broker.estimate_order_margin(
            BrokerOrder(
                instrument_id="ESU6",
                side=OrderSide.BUY,
                quantity=1,
                order_type=OrderType.MARKET,
                client_order_id="client-3",
            )
        )


def test_tradovate_historical_daily_bars_fail_closed_until_mapping_is_verified():
    broker = _adapter(RecordingTransport(()))

    with pytest.raises(MarketDataError, match="does not expose verified historical daily bars"):
        broker.get_daily_bars("ESU6", NOW.date(), NOW.date())
