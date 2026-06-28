from datetime import datetime, timezone
from decimal import Decimal

from futures_bot.application.order_updates import OrderUpdateService
from futures_bot.domain.order_lifecycle import OrderLifecycle, OrderLifecycleStatus
from futures_bot.ports.audit import InMemoryAuditLog
from futures_bot.ports.broker import BrokerOrderUpdate, BrokerOrderUpdateType


NOW = datetime(2026, 6, 28, 14, 31, tzinfo=timezone.utc)


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
