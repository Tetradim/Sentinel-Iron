from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping

import pytest

from futures_bot.brokers.ibkr.config import BrokerEnvironment, IbkrConfig
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder
from futures_bot.ports.broker import BrokerCancellationError, BrokerConnectionError, BrokerSubmissionError


NOW = datetime(2026, 6, 28, 17, 5, tzinfo=timezone.utc)


class RecordingIbkrClient:
    def __init__(self) -> None:
        self.connect_calls: list[tuple[str, int, int]] = []
        self.placed_orders: list[dict[str, object]] = []
        self.canceled_order_ids: list[int] = []
        self.account_rows: tuple[Mapping[str, object], ...] = (
            {"account": "DU12345", "tag": "NetLiquidation", "value": "100000.50", "currency": "USD"},
            {"account": "DU12345", "tag": "InitMarginReq", "value": "12000.25", "currency": "USD"},
            {"account": "DU12345", "tag": "MaintMarginReq", "value": "9000.75", "currency": "USD"},
            {"account": "DU12345", "tag": "BuyingPower", "value": "50000.00", "currency": "USD"},
        )
        self.position_rows: tuple[Mapping[str, object], ...] = (
            {
                "contract": {
                    "localSymbol": "ESU6",
                    "symbol": "ES",
                    "secType": "FUT",
                    "exchange": "CME",
                    "lastTradeDateOrContractMonth": "202609",
                },
                "position": "2",
                "average_cost": "5000.25",
            },
            {
                "contract": {
                    "symbol": "NQ",
                    "secType": "FUT",
                    "exchange": "CME",
                    "lastTradeDateOrContractMonth": "202609",
                },
                "position": "-1",
                "average_cost": "18000.50",
            },
        )

    def connect(self, host: str, port: int, client_id: int) -> None:
        self.connect_calls.append((host, port, client_id))

    def account_summary(self) -> tuple[Mapping[str, object], ...]:
        return self.account_rows

    def positions(self) -> tuple[Mapping[str, object], ...]:
        return self.position_rows

    def next_order_id(self) -> int:
        return 9001

    def place_order(
        self,
        order_id: int,
        contract: Mapping[str, object],
        order: Mapping[str, object],
    ) -> None:
        self.placed_orders.append(
            {
                "order_id": order_id,
                "contract": dict(contract),
                "order": dict(order),
            }
        )

    def cancel_order(self, order_id: int) -> None:
        self.canceled_order_ids.append(order_id)


def _adapter(client: RecordingIbkrClient):
    from futures_bot.brokers.ibkr.adapter import IbkrBroker

    return IbkrBroker(
        config=IbkrConfig(
            environment=BrokerEnvironment.PAPER,
            host="127.0.0.1",
            port=7497,
            client_id=101,
        ),
        client=client,
        clock=lambda: NOW,
    )


def test_ibkr_adapter_connects_to_configured_tws_gateway():
    client = RecordingIbkrClient()
    broker = _adapter(client)

    broker.connect()

    assert client.connect_calls == [("127.0.0.1", 7497, 101)]


def test_ibkr_adapter_maps_client_connection_errors():
    from futures_bot.brokers.ibkr.adapter import IbkrClientError

    class FailingConnectClient(RecordingIbkrClient):
        def connect(self, host: str, port: int, client_id: int) -> None:
            raise IbkrClientError("TWS socket refused connection", "CONNECTION_REFUSED")

    broker = _adapter(FailingConnectClient())

    with pytest.raises(BrokerConnectionError) as exc_info:
        broker.connect()

    assert exc_info.value.reason == "TWS socket refused connection"
    assert exc_info.value.broker_error_code == "CONNECTION_REFUSED"


def test_ibkr_adapter_maps_account_summary_rows():
    broker = _adapter(RecordingIbkrClient())

    account = broker.get_account()

    assert account.account_id == "DU12345"
    assert account.equity == Decimal("100000.50")
    assert account.initial_margin == Decimal("12000.25")
    assert account.maintenance_margin == Decimal("9000.75")
    assert account.buying_power == Decimal("50000.00")
    assert account.timestamp == NOW


def test_ibkr_adapter_maps_position_rows_to_domain_positions():
    broker = _adapter(RecordingIbkrClient())

    positions = broker.get_positions()

    assert positions[0].instrument_id == "ESU6"
    assert positions[0].quantity == 2
    assert positions[0].average_price == Decimal("5000.25")
    assert positions[1].instrument_id == "NQ-202609-CME"
    assert positions[1].quantity == -1
    assert positions[1].average_price == Decimal("18000.50")


def test_ibkr_adapter_places_limit_order_with_next_valid_order_id():
    client = RecordingIbkrClient()
    broker = _adapter(client)

    broker_order_id = broker.submit_order(
        BrokerOrder(
            instrument_id="ES-202609-CME",
            side=OrderSide.BUY,
            quantity=2,
            order_type=OrderType.LIMIT,
            client_order_id="client-1",
            limit_price=Decimal("5000.25"),
        )
    )

    assert broker_order_id == "9001"
    assert client.placed_orders == [
        {
            "order_id": 9001,
            "contract": {
                "currency": "USD",
                "exchange": "CME",
                "lastTradeDateOrContractMonth": "202609",
                "secType": "FUT",
                "symbol": "ES",
            },
            "order": {
                "action": "BUY",
                "lmtPrice": "5000.25",
                "orderRef": "client-1",
                "orderType": "LMT",
                "tif": "DAY",
                "totalQuantity": 2,
            },
        }
    ]


def test_ibkr_adapter_places_market_order_without_limit_price():
    client = RecordingIbkrClient()
    broker = _adapter(client)

    broker.submit_order(
        BrokerOrder(
            instrument_id="ES-202609-CME",
            side=OrderSide.SELL,
            quantity=1,
            order_type=OrderType.MARKET,
            client_order_id="client-2",
        )
    )

    assert client.placed_orders[0]["order"] == {
        "action": "SELL",
        "orderRef": "client-2",
        "orderType": "MKT",
        "tif": "DAY",
        "totalQuantity": 1,
    }


def test_ibkr_adapter_maps_order_submission_errors():
    from futures_bot.brokers.ibkr.adapter import IbkrClientError

    class FailingOrderClient(RecordingIbkrClient):
        def place_order(
            self,
            order_id: int,
            contract: Mapping[str, object],
            order: Mapping[str, object],
        ) -> None:
            raise IbkrClientError("order rejected: contract is ambiguous", "AMBIGUOUS_CONTRACT")

    broker = _adapter(FailingOrderClient())

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

    assert exc_info.value.reason == "order rejected: contract is ambiguous"
    assert exc_info.value.broker_error_code == "AMBIGUOUS_CONTRACT"


def test_ibkr_adapter_cancels_order_by_numeric_broker_order_id():
    client = RecordingIbkrClient()
    broker = _adapter(client)

    broker.cancel_order("9001")

    assert client.canceled_order_ids == [9001]


def test_ibkr_adapter_maps_cancel_errors():
    from futures_bot.brokers.ibkr.adapter import IbkrClientError

    class FailingCancelClient(RecordingIbkrClient):
        def cancel_order(self, order_id: int) -> None:
            raise IbkrClientError("API client cannot cancel this order", "CANCEL_DENIED")

    broker = _adapter(FailingCancelClient())

    with pytest.raises(BrokerCancellationError) as exc_info:
        broker.cancel_order("9001")

    assert exc_info.value.reason == "API client cannot cancel this order"
    assert exc_info.value.broker_error_code == "CANCEL_DENIED"
