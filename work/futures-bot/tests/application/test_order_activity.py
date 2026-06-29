from datetime import datetime, timedelta, timezone
from decimal import Decimal

from futures_bot.application.order_activity import (
    OrderActivityRecord,
    OrderActivityTracker,
    working_order_intents_from_activity,
)
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.order_lifecycle import OrderLifecycle, OrderLifecycleStatus
from futures_bot.domain.orders import OrderIntent
from futures_bot.ports.audit import InMemoryAuditLog


NOW = datetime(2026, 6, 28, 14, 37, tzinfo=timezone.utc)


def _intent(client_order_id: str = "order-1") -> OrderIntent:
    return OrderIntent(
        instrument_id="ES-202609-CME",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("5000.25"),
        client_order_id=client_order_id,
    )


def _record(
    client_order_id: str = "order-1",
    broker_order_id: str = "broker-123",
    quantity: int = 1,
) -> OrderActivityRecord:
    return OrderActivityRecord(
        client_order_id=client_order_id,
        broker_order_id=broker_order_id,
        instrument_id="ES-202609-CME",
        timestamp=NOW,
        side=OrderSide.BUY,
        quantity=quantity,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("5000.25"),
    )


class RecordingLifecycleStore:
    def __init__(self, lifecycles: dict[str, OrderLifecycle]) -> None:
        self.lifecycles = lifecycles
        self.loaded_client_order_ids: list[str] = []

    def load(self, client_order_id: str) -> OrderLifecycle | None:
        self.loaded_client_order_ids.append(client_order_id)
        return self.lifecycles.get(client_order_id)


def test_order_activity_records_submission_and_builds_risk_inputs():
    audit_log = InMemoryAuditLog()
    tracker = OrderActivityTracker(audit_log)

    tracker.record_submission(
        intent=_intent(),
        timestamp=NOW,
        broker_order_id="broker-123",
    )
    snapshot = tracker.snapshot(now=NOW, recent_order_window=timedelta(minutes=1))

    assert snapshot.used_client_order_ids == frozenset({"order-1"})
    assert snapshot.recent_order_timestamps == (NOW,)
    record = tracker.record_for("order-1")
    assert record is not None
    assert record.side == OrderSide.BUY
    assert record.quantity == 1
    assert record.order_type == OrderType.LIMIT
    assert record.limit_price == Decimal("5000.25")
    assert audit_log.events == (
        {
            "type": "order_activity_recorded",
            "timestamp": "2026-06-28T14:37:00+00:00",
            "client_order_id": "order-1",
            "broker_order_id": "broker-123",
            "instrument_id": "ES-202609-CME",
            "side": "buy",
            "quantity": 1,
            "order_type": "limit",
            "limit_price": "5000.25",
        },
    )


def test_order_activity_snapshot_excludes_orders_outside_recent_window():
    tracker = OrderActivityTracker(InMemoryAuditLog())

    tracker.record_submission(
        intent=_intent("old-order"),
        timestamp=NOW - timedelta(minutes=5),
        broker_order_id="broker-old",
    )
    tracker.record_submission(
        intent=_intent("new-order"),
        timestamp=NOW - timedelta(seconds=20),
        broker_order_id="broker-new",
    )
    snapshot = tracker.snapshot(now=NOW, recent_order_window=timedelta(minutes=1))

    assert snapshot.used_client_order_ids == frozenset({"old-order", "new-order"})
    assert snapshot.recent_order_timestamps == (NOW - timedelta(seconds=20),)


def test_order_activity_rejects_duplicate_client_order_id():
    tracker = OrderActivityTracker(InMemoryAuditLog())
    tracker.record_submission(
        intent=_intent(),
        timestamp=NOW,
        broker_order_id="broker-123",
    )

    try:
        tracker.record_submission(
            intent=_intent(),
            timestamp=NOW + timedelta(seconds=1),
            broker_order_id="broker-456",
        )
    except ValueError as exc:
        assert str(exc) == "client order ID was already recorded"
    else:
        raise AssertionError("expected duplicate client order ID to be rejected")


class InMemoryOrderActivityStore:
    def __init__(self):
        self.records = []

    def load(self):
        return tuple(self.records)

    def append(self, record):
        self.records.append(record)


def test_order_activity_rehydrates_order_metadata_from_store():
    audit_log = InMemoryAuditLog()
    store = InMemoryOrderActivityStore()
    tracker = OrderActivityTracker(audit_log, store=store)
    tracker.record_submission(
        intent=_intent(),
        timestamp=NOW,
        broker_order_id="broker-123",
    )

    rehydrated = OrderActivityTracker(InMemoryAuditLog(), store=store)
    record = rehydrated.record_for("order-1")

    assert record is not None
    assert record.side == OrderSide.BUY
    assert record.quantity == 1
    assert record.order_type == OrderType.LIMIT
    assert record.limit_price == Decimal("5000.25")


def test_order_activity_snapshot_requires_positive_recent_window():
    tracker = OrderActivityTracker(InMemoryAuditLog())

    try:
        tracker.snapshot(now=NOW, recent_order_window=timedelta(0))
    except ValueError as exc:
        assert str(exc) == "recent_order_window must be positive"
    else:
        raise AssertionError("expected invalid recent window to be rejected")


def test_working_order_intents_from_activity_uses_working_lifecycle_state():
    lifecycle_store = RecordingLifecycleStore(
        {
            "working-1": OrderLifecycle.pending_submit("working-1").mark_working(),
            "partial-1": OrderLifecycle.pending_submit("partial-1")
            .mark_working()
            .record_fill(fill_quantity=1, order_quantity=3),
            "filled-1": OrderLifecycle(
                client_order_id="filled-1",
                status=OrderLifecycleStatus.FILLED,
                filled_quantity=1,
            ),
        }
    )

    intents = working_order_intents_from_activity(
        (
            _record("working-1", "broker-working-1", quantity=2),
            _record("partial-1", "broker-partial-1", quantity=3),
            _record("filled-1", "broker-filled-1", quantity=1),
        ),
        lifecycle_store,
    )

    assert lifecycle_store.loaded_client_order_ids == [
        "working-1",
        "partial-1",
        "filled-1",
    ]
    assert intents == (
        OrderIntent(
            instrument_id="ES-202609-CME",
            side=OrderSide.BUY,
            quantity=2,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("5000.25"),
            client_order_id="working-1",
        ),
        OrderIntent(
            instrument_id="ES-202609-CME",
            side=OrderSide.BUY,
            quantity=2,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("5000.25"),
            client_order_id="partial-1",
        ),
    )
