from datetime import datetime, timezone
from decimal import Decimal

from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder
from futures_bot.domain.portfolio import AccountSnapshot, Position
from futures_bot.ports.audit import InMemoryAuditLog
from futures_bot.ports.broker import BrokerSubmissionError


NOW = datetime(2026, 6, 28, 16, 20, tzinfo=timezone.utc)


class RecordingBroker:
    def __init__(self, positions: tuple[Position, ...]) -> None:
        self.connected = False
        self.positions = positions
        self.submitted_orders: list[BrokerOrder] = []

    def connect(self) -> None:
        self.connected = True

    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="acct-1",
            equity=Decimal("100000"),
            initial_margin=Decimal("10000"),
            maintenance_margin=Decimal("8000"),
            buying_power=Decimal("50000"),
            timestamp=NOW,
        )

    def get_positions(self) -> tuple[Position, ...]:
        return self.positions

    def submit_order(self, order: BrokerOrder) -> str:
        self.submitted_orders.append(order)
        return f"broker-{len(self.submitted_orders)}"

    def cancel_order(self, broker_order_id: str) -> None:
        raise NotImplementedError


class PartiallyRejectingBroker(RecordingBroker):
    def submit_order(self, order: BrokerOrder) -> str:
        self.submitted_orders.append(order)
        if order.instrument_id == "NQ-202609-CME":
            raise BrokerSubmissionError("exchange rejected flatten order", "REJECTED")
        return f"broker-{len(self.submitted_orders)}"


def test_position_flattening_submits_opposite_market_orders_and_audits():
    from futures_bot.application.position_flattening import PositionFlatteningService

    broker = RecordingBroker(
        (
            Position("ES-202609-CME", 2, Decimal("5000")),
            Position("NQ-202609-CME", -1, Decimal("18000")),
            Position("CL-202608-NYMEX", 0, Decimal("75")),
        )
    )
    audit_log = InMemoryAuditLog()
    service = PositionFlatteningService(broker=broker, audit_log=audit_log)

    result = service.flatten(timestamp=NOW, client_order_id_prefix="flatten-live")

    assert result.account_id == "acct-1"
    assert result.submitted_count == 2
    assert result.failed_count == 0
    assert result.skipped_count == 1
    assert broker.connected is True
    assert broker.submitted_orders == [
        BrokerOrder(
            instrument_id="ES-202609-CME",
            side=OrderSide.SELL,
            quantity=2,
            order_type=OrderType.MARKET,
            client_order_id="flatten-live-20260628T162000Z-1",
        ),
        BrokerOrder(
            instrument_id="NQ-202609-CME",
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
            client_order_id="flatten-live-20260628T162000Z-2",
        ),
    ]
    assert audit_log.events[0]["type"] == "position_flatten_started"
    assert audit_log.events[1]["type"] == "position_flatten_order_submitted"
    assert audit_log.events[2]["type"] == "position_flatten_order_submitted"
    assert audit_log.events[3] == {
        "type": "position_flatten_completed",
        "timestamp": "2026-06-28T16:20:00+00:00",
        "account_id": "acct-1",
        "submitted_count": 2,
        "failed_count": 0,
        "skipped_count": 1,
    }


def test_position_flattening_records_failures_and_continues_remaining_positions():
    from futures_bot.application.position_flattening import PositionFlatteningService

    broker = PartiallyRejectingBroker(
        (
            Position("ES-202609-CME", 1, Decimal("5000")),
            Position("NQ-202609-CME", -2, Decimal("18000")),
            Position("RTY-202609-CME", 3, Decimal("2100")),
        )
    )
    audit_log = InMemoryAuditLog()
    service = PositionFlatteningService(broker=broker, audit_log=audit_log)

    result = service.flatten(timestamp=NOW, client_order_id_prefix="flatten-live")

    assert result.submitted_count == 2
    assert result.failed_count == 1
    assert broker.submitted_orders[-1].instrument_id == "RTY-202609-CME"
    assert audit_log.events[2] == {
        "type": "position_flatten_order_failed",
        "timestamp": "2026-06-28T16:20:00+00:00",
        "account_id": "acct-1",
        "client_order_id": "flatten-live-20260628T162000Z-2",
        "instrument_id": "NQ-202609-CME",
        "side": "buy",
        "quantity": 2,
        "reason": "exchange rejected flatten order",
        "broker_error_code": "REJECTED",
    }
