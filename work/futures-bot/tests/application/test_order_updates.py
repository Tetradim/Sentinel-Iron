from datetime import datetime, timezone
from decimal import Decimal

from futures_bot.application.order_activity import OrderActivityRecord
from futures_bot.application.order_updates import OrderUpdateService
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.order_lifecycle import OrderLifecycle, OrderLifecycleStatus
from futures_bot.ports.audit import InMemoryAuditLog
from futures_bot.ports.broker import BrokerOrderUpdate, BrokerOrderUpdateType


NOW = datetime(2026, 6, 28, 14, 31, tzinfo=timezone.utc)


class RecordingPositionLedger:
    def __init__(self) -> None:
        self.applied_fills: list[tuple[BrokerOrderUpdate, OrderSide]] = []

    def apply_fill(self, update: BrokerOrderUpdate, order_side: OrderSide) -> None:
        self.applied_fills.append((update, order_side))


class StaticOrderActivityLookup:
    def __init__(self, records: tuple[OrderActivityRecord, ...]) -> None:
        self.records = {record.client_order_id: record for record in records}

    def record_for(self, client_order_id: str) -> OrderActivityRecord | None:
        return self.records.get(client_order_id)


class RecordingLifecycleStore:
    def __init__(self, loaded_lifecycle: OrderLifecycle | None = None) -> None:
        self.loaded_lifecycle = loaded_lifecycle
        self.saved_lifecycles: list[OrderLifecycle] = []
        self.loaded_client_order_ids: list[str] = []

    def load(self, client_order_id: str) -> OrderLifecycle | None:
        self.loaded_client_order_ids.append(client_order_id)
        return self.loaded_lifecycle

    def save(self, lifecycle: OrderLifecycle) -> None:
        self.saved_lifecycles.append(lifecycle)


def _activity_record(
    client_order_id: str = "order-1",
    instrument_id: str = "ES-202609-CME",
) -> OrderActivityRecord:
    return OrderActivityRecord(
        client_order_id=client_order_id,
        broker_order_id="broker-123",
        instrument_id=instrument_id,
        timestamp=NOW,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("5000.25"),
    )


def _update(update_type: BrokerOrderUpdateType, **overrides: object) -> BrokerOrderUpdate:
    values = {
        "account_id": "acct-1",
        "client_order_id": "order-1",
        "broker_order_id": "broker-123",
        "instrument_id": "ES-202609-CME",
        "update_type": update_type,
        "timestamp": NOW,
    }
    values.update(overrides)
    return BrokerOrderUpdate(**values)


def test_order_update_service_marks_pending_submit_order_working_and_audits_update():
    audit_log = InMemoryAuditLog()
    service = OrderUpdateService(audit_log)

    updated = service.apply(
        lifecycle=OrderLifecycle.pending_submit(client_order_id="order-1"),
        update=_update(BrokerOrderUpdateType.WORKING),
        order_quantity=5,
    )

    assert updated.status == OrderLifecycleStatus.WORKING
    assert audit_log.events == (
        {
            "type": "order_update_applied",
            "timestamp": "2026-06-28T14:31:00+00:00",
            "account_id": "acct-1",
            "client_order_id": "order-1",
            "broker_order_id": "broker-123",
            "instrument_id": "ES-202609-CME",
            "update_type": "working",
            "status": "working",
            "fill_quantity": 0,
            "filled_quantity": 0,
            "reject_reason": None,
            "broker_error_code": None,
        },
    )


def test_order_update_service_records_fill_and_audits_cumulative_filled_quantity():
    audit_log = InMemoryAuditLog()
    service = OrderUpdateService(audit_log)
    lifecycle = OrderLifecycle.pending_submit(client_order_id="order-1").mark_working()

    updated = service.apply(
        lifecycle=lifecycle,
        update=_update(BrokerOrderUpdateType.FILL, fill_quantity=2),
        order_quantity=5,
    )

    assert updated.status == OrderLifecycleStatus.PARTIALLY_FILLED
    assert updated.filled_quantity == 2
    assert audit_log.events[-1]["update_type"] == "fill"
    assert audit_log.events[-1]["status"] == "partially_filled"
    assert audit_log.events[-1]["fill_quantity"] == 2
    assert audit_log.events[-1]["filled_quantity"] == 2


def test_fill_update_accepts_optional_fill_price_for_position_accounting():
    update = _update(BrokerOrderUpdateType.FILL, fill_quantity=1, fill_price=Decimal("5001.25"))

    assert update.fill_price == Decimal("5001.25")


def test_fill_update_accepts_optional_execution_id_for_idempotency():
    update = _update(
        BrokerOrderUpdateType.FILL,
        fill_quantity=1,
        fill_price=Decimal("5001.25"),
        broker_execution_id="exec-1",
    )

    assert update.broker_execution_id == "exec-1"


def test_order_update_service_applies_position_ledger_when_configured_for_fill():
    audit_log = InMemoryAuditLog()
    position_ledger = RecordingPositionLedger()
    service = OrderUpdateService(audit_log, position_ledger=position_ledger)
    lifecycle = OrderLifecycle.pending_submit(client_order_id="order-1").mark_working()
    fill_update = _update(
        BrokerOrderUpdateType.FILL,
        fill_quantity=2,
        fill_price=Decimal("5001.25"),
    )

    updated = service.apply(
        lifecycle=lifecycle,
        update=fill_update,
        order_quantity=5,
        order_side=OrderSide.BUY,
    )

    assert updated.status == OrderLifecycleStatus.PARTIALLY_FILLED
    assert position_ledger.applied_fills == [(fill_update, OrderSide.BUY)]
    assert audit_log.events[-1]["update_type"] == "fill"


def test_order_update_service_recovers_order_metadata_for_restarted_fill_handler():
    audit_log = InMemoryAuditLog()
    position_ledger = RecordingPositionLedger()
    order_activity = StaticOrderActivityLookup((_activity_record(),))
    service = OrderUpdateService(
        audit_log,
        position_ledger=position_ledger,
        order_activity=order_activity,
    )
    lifecycle = OrderLifecycle.pending_submit(client_order_id="order-1").mark_working()
    fill_update = _update(
        BrokerOrderUpdateType.FILL,
        fill_quantity=2,
        fill_price=Decimal("5001.25"),
    )

    updated = service.apply(lifecycle=lifecycle, update=fill_update)

    assert updated.status == OrderLifecycleStatus.PARTIALLY_FILLED
    assert updated.filled_quantity == 2
    assert position_ledger.applied_fills == [(fill_update, OrderSide.BUY)]
    assert audit_log.events[-1]["filled_quantity"] == 2


def test_order_update_service_recovers_lifecycle_from_store_after_restart():
    audit_log = InMemoryAuditLog()
    order_activity = StaticOrderActivityLookup((_activity_record(),))
    lifecycle_store = RecordingLifecycleStore(
        OrderLifecycle.pending_submit(client_order_id="order-1").mark_working()
    )
    service = OrderUpdateService(
        audit_log,
        order_activity=order_activity,
        lifecycle_store=lifecycle_store,
    )

    updated = service.apply(
        lifecycle=None,
        update=_update(BrokerOrderUpdateType.FILL, fill_quantity=2),
    )

    assert lifecycle_store.loaded_client_order_ids == ["order-1"]
    assert updated.status == OrderLifecycleStatus.PARTIALLY_FILLED
    assert updated.filled_quantity == 2
    assert lifecycle_store.saved_lifecycles == [updated]


def test_order_update_service_rejects_missing_lifecycle_after_restart():
    audit_log = InMemoryAuditLog()
    lifecycle_store = RecordingLifecycleStore()
    service = OrderUpdateService(audit_log, lifecycle_store=lifecycle_store)

    try:
        service.apply(
            lifecycle=None,
            update=_update(BrokerOrderUpdateType.WORKING),
        )
    except ValueError as exc:
        assert str(exc) == "order lifecycle was not found"
    else:
        raise AssertionError("expected missing lifecycle to be rejected")

    assert lifecycle_store.loaded_client_order_ids == ["order-1"]
    assert lifecycle_store.saved_lifecycles == []
    assert audit_log.events == ()


def test_order_update_service_rejects_activity_instrument_mismatch():
    audit_log = InMemoryAuditLog()
    order_activity = StaticOrderActivityLookup((_activity_record(instrument_id="NQ-202609-CME"),))
    service = OrderUpdateService(audit_log, order_activity=order_activity)
    lifecycle = OrderLifecycle.pending_submit(client_order_id="order-1").mark_working()

    try:
        service.apply(
            lifecycle=lifecycle,
            update=_update(BrokerOrderUpdateType.FILL, fill_quantity=1),
        )
    except ValueError as exc:
        assert str(exc) == "broker update instrument_id does not match order activity"
    else:
        raise AssertionError("expected mismatched order activity instrument to be rejected")

    assert audit_log.events == ()


def test_order_update_service_rejects_activity_broker_order_id_mismatch():
    audit_log = InMemoryAuditLog()
    order_activity = StaticOrderActivityLookup((_activity_record(),))
    service = OrderUpdateService(audit_log, order_activity=order_activity)
    lifecycle = OrderLifecycle.pending_submit(client_order_id="order-1").mark_working()

    try:
        service.apply(
            lifecycle=lifecycle,
            update=_update(
                BrokerOrderUpdateType.FILL,
                fill_quantity=1,
                broker_order_id="broker-456",
            ),
        )
    except ValueError as exc:
        assert str(exc) == "broker update broker_order_id does not match order activity"
    else:
        raise AssertionError("expected mismatched broker order ID to be rejected")

    assert audit_log.events == ()


def test_order_update_service_allows_missing_broker_order_id_when_activity_matches_client_order():
    audit_log = InMemoryAuditLog()
    order_activity = StaticOrderActivityLookup((_activity_record(),))
    service = OrderUpdateService(audit_log, order_activity=order_activity)
    lifecycle = OrderLifecycle.pending_submit(client_order_id="order-1").mark_working()

    updated = service.apply(
        lifecycle=lifecycle,
        update=_update(
            BrokerOrderUpdateType.FILL,
            fill_quantity=1,
            broker_order_id=None,
        ),
    )

    assert updated.status == OrderLifecycleStatus.PARTIALLY_FILLED
    assert audit_log.events[-1]["broker_order_id"] is None


def test_order_update_service_requires_order_side_for_position_ledger_fills():
    audit_log = InMemoryAuditLog()
    position_ledger = RecordingPositionLedger()
    service = OrderUpdateService(audit_log, position_ledger=position_ledger)
    lifecycle = OrderLifecycle.pending_submit(client_order_id="order-1").mark_working()

    try:
        service.apply(
            lifecycle=lifecycle,
            update=_update(
                BrokerOrderUpdateType.FILL,
                fill_quantity=1,
                fill_price=Decimal("5001.25"),
            ),
            order_quantity=5,
        )
    except ValueError as exc:
        assert str(exc) == "order_side is required when position ledger is configured"
    else:
        raise AssertionError("expected missing order side to be rejected")

    assert position_ledger.applied_fills == []
    assert audit_log.events == ()


def test_order_update_service_marks_working_order_rejected_and_audits_reason():
    audit_log = InMemoryAuditLog()
    service = OrderUpdateService(audit_log)
    lifecycle = OrderLifecycle.pending_submit(client_order_id="order-1").mark_working()

    updated = service.apply(
        lifecycle=lifecycle,
        update=_update(
            BrokerOrderUpdateType.REJECTED,
            reject_reason="exchange bust or reject",
            broker_error_code="EXCHANGE_REJECT",
        ),
        order_quantity=5,
    )

    assert updated.status == OrderLifecycleStatus.REJECTED
    assert updated.reject_reason == "exchange bust or reject"
    assert audit_log.events[-1]["update_type"] == "rejected"
    assert audit_log.events[-1]["status"] == "rejected"
    assert audit_log.events[-1]["reject_reason"] == "exchange bust or reject"
    assert audit_log.events[-1]["broker_error_code"] == "EXCHANGE_REJECT"


def test_order_update_service_marks_pending_cancel_order_canceled():
    audit_log = InMemoryAuditLog()
    service = OrderUpdateService(audit_log)
    lifecycle = (
        OrderLifecycle.pending_submit(client_order_id="order-1")
        .mark_working()
        .mark_pending_cancel()
    )

    updated = service.apply(
        lifecycle=lifecycle,
        update=_update(BrokerOrderUpdateType.CANCELED),
        order_quantity=5,
    )

    assert updated.status == OrderLifecycleStatus.CANCELED
    assert audit_log.events[-1]["update_type"] == "canceled"
    assert audit_log.events[-1]["status"] == "canceled"


def test_order_update_service_rejects_mismatched_client_order_id():
    audit_log = InMemoryAuditLog()
    service = OrderUpdateService(audit_log)

    try:
        service.apply(
            lifecycle=OrderLifecycle.pending_submit(client_order_id="order-1"),
            update=_update(BrokerOrderUpdateType.WORKING, client_order_id="order-2"),
            order_quantity=5,
        )
    except ValueError as exc:
        assert str(exc) == "broker update client_order_id does not match lifecycle"
    else:
        raise AssertionError("expected mismatched update to be rejected")
