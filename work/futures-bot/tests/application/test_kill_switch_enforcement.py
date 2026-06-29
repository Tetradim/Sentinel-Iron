from datetime import datetime, timezone
from decimal import Decimal

from futures_bot.application.order_activity import OrderActivityRecord
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.order_lifecycle import OrderLifecycle, OrderLifecycleStatus
from futures_bot.domain.orders import BrokerOrder
from futures_bot.domain.portfolio import AccountSnapshot, Position
from futures_bot.ports.audit import InMemoryAuditLog
from futures_bot.ports.broker import BrokerCancellationError


NOW = datetime(2026, 6, 28, 21, 15, tzinfo=timezone.utc)


class RecordingActivityStore:
    def __init__(self, records: tuple[OrderActivityRecord, ...]) -> None:
        self.records = records

    def load(self) -> tuple[OrderActivityRecord, ...]:
        return self.records


class RecordingLifecycleStore:
    def __init__(self, lifecycles: dict[str, OrderLifecycle]) -> None:
        self.lifecycles = lifecycles
        self.loaded_client_order_ids: list[str] = []
        self.saved_lifecycles: list[OrderLifecycle] = []

    def load(self, client_order_id: str) -> OrderLifecycle | None:
        self.loaded_client_order_ids.append(client_order_id)
        return self.lifecycles.get(client_order_id)

    def save(self, lifecycle: OrderLifecycle) -> None:
        self.saved_lifecycles.append(lifecycle)
        self.lifecycles[lifecycle.client_order_id] = lifecycle


class RecordingBroker:
    def __init__(self, rejecting_order_ids: set[str] | None = None) -> None:
        self.rejecting_order_ids = rejecting_order_ids or set()
        self.canceled_order_ids: list[str] = []

    def connect(self) -> None:
        pass

    def get_account(self) -> AccountSnapshot:
        raise NotImplementedError

    def get_positions(self) -> tuple[Position, ...]:
        raise NotImplementedError

    def submit_order(self, order: BrokerOrder) -> str:
        raise NotImplementedError

    def cancel_order(self, broker_order_id: str) -> None:
        self.canceled_order_ids.append(broker_order_id)
        if broker_order_id in self.rejecting_order_ids:
            raise BrokerCancellationError(
                "broker rejected cancel: too late to cancel",
                "TOO_LATE_TO_CANCEL",
            )


def test_kill_switch_enforcement_cancels_working_orders_and_skips_terminal_orders():
    from futures_bot.application.kill_switch_enforcement import KillSwitchEnforcementService

    audit_log = InMemoryAuditLog()
    broker = RecordingBroker()
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
    service = KillSwitchEnforcementService(
        broker=broker,
        audit_log=audit_log,
        activity_store=RecordingActivityStore(
            (
                _record("working-1", "broker-working-1"),
                _record("partial-1", "broker-partial-1"),
                _record("filled-1", "broker-filled-1"),
            )
        ),
        lifecycle_store=lifecycle_store,
    )

    result = service.cancel_working_orders(account_id="acct-1", timestamp=NOW)

    assert result.cancel_requested_count == 2
    assert result.skipped_count == 1
    assert result.failed_count == 0
    assert broker.canceled_order_ids == ["broker-working-1", "broker-partial-1"]
    assert [item.status for item in lifecycle_store.saved_lifecycles] == [
        OrderLifecycleStatus.PENDING_CANCEL,
        OrderLifecycleStatus.PENDING_CANCEL,
    ]
    assert audit_log.events[-1] == {
        "type": "kill_switch_cancel_sweep_completed",
        "timestamp": "2026-06-28T21:15:00+00:00",
        "account_id": "acct-1",
        "candidate_count": 3,
        "cancel_requested_count": 2,
        "skipped_count": 1,
        "failed_count": 0,
    }


def test_kill_switch_enforcement_records_cancel_failures_and_continues():
    from futures_bot.application.kill_switch_enforcement import KillSwitchEnforcementService

    audit_log = InMemoryAuditLog()
    broker = RecordingBroker(rejecting_order_ids={"broker-working-1"})
    lifecycle_store = RecordingLifecycleStore(
        {
            "working-1": OrderLifecycle.pending_submit("working-1").mark_working(),
            "working-2": OrderLifecycle.pending_submit("working-2").mark_working(),
        }
    )
    service = KillSwitchEnforcementService(
        broker=broker,
        audit_log=audit_log,
        activity_store=RecordingActivityStore(
            (
                _record("working-1", "broker-working-1"),
                _record("working-2", "broker-working-2"),
            )
        ),
        lifecycle_store=lifecycle_store,
    )

    result = service.cancel_working_orders(account_id="acct-1", timestamp=NOW)

    assert result.cancel_requested_count == 1
    assert result.skipped_count == 0
    assert result.failed_count == 1
    assert broker.canceled_order_ids == ["broker-working-1", "broker-working-2"]
    assert [item.client_order_id for item in lifecycle_store.saved_lifecycles] == ["working-2"]
    assert audit_log.events[-1]["type"] == "kill_switch_cancel_sweep_completed"
    assert audit_log.events[-1]["failed_count"] == 1


def _record(client_order_id: str, broker_order_id: str) -> OrderActivityRecord:
    return OrderActivityRecord(
        client_order_id=client_order_id,
        broker_order_id=broker_order_id,
        instrument_id="ES-202609-CME",
        timestamp=NOW,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("5000.25"),
    )
