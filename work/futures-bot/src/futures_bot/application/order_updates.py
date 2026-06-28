from __future__ import annotations

from typing import Protocol

from futures_bot.application.order_activity import OrderActivityRecord
from futures_bot.domain.enums import OrderSide
from futures_bot.domain.order_lifecycle import OrderLifecycle
from futures_bot.ports.audit import AuditLogPort
from futures_bot.ports.broker import BrokerOrderUpdate, BrokerOrderUpdateType


class PositionLedgerPort(Protocol):
    def apply_fill(self, update: BrokerOrderUpdate, order_side: OrderSide) -> object:
        """Apply one broker fill to the internal position ledger."""


class OrderActivityLookupPort(Protocol):
    def record_for(self, client_order_id: str) -> OrderActivityRecord | None:
        """Return persisted broker-accepted order activity by client order ID."""


class OrderLifecycleStorePort(Protocol):
    def load(self, client_order_id: str) -> OrderLifecycle | None:
        """Load the latest persisted order lifecycle by client order ID."""

    def save(self, lifecycle: OrderLifecycle) -> None:
        """Persist the latest known order lifecycle."""


class OrderUpdateService:
    def __init__(
        self,
        audit_log: AuditLogPort,
        position_ledger: PositionLedgerPort | None = None,
        order_activity: OrderActivityLookupPort | None = None,
        lifecycle_store: OrderLifecycleStorePort | None = None,
    ) -> None:
        self._audit_log = audit_log
        self._position_ledger = position_ledger
        self._order_activity = order_activity
        self._lifecycle_store = lifecycle_store

    def apply(
        self,
        lifecycle: OrderLifecycle | None,
        update: BrokerOrderUpdate,
        order_quantity: int | None = None,
        order_side: OrderSide | None = None,
    ) -> OrderLifecycle:
        if lifecycle is None:
            if self._lifecycle_store is None:
                raise ValueError("order lifecycle is required when lifecycle store is not configured")
            lifecycle = self._lifecycle_store.load(update.client_order_id)
            if lifecycle is None:
                raise ValueError("order lifecycle was not found")
        if update.client_order_id != lifecycle.client_order_id:
            raise ValueError("broker update client_order_id does not match lifecycle")

        resolved_order_quantity = order_quantity
        resolved_order_side = order_side
        if self._order_activity is not None:
            activity_record = self._order_activity.record_for(update.client_order_id)
            if activity_record is not None:
                if activity_record.instrument_id != update.instrument_id:
                    raise ValueError("broker update instrument_id does not match order activity")
                if (
                    update.broker_order_id is not None
                    and activity_record.broker_order_id != update.broker_order_id
                ):
                    raise ValueError("broker update broker_order_id does not match order activity")
                if resolved_order_quantity is None:
                    resolved_order_quantity = activity_record.quantity
                if resolved_order_side is None:
                    resolved_order_side = activity_record.side

        if resolved_order_quantity is not None and resolved_order_quantity <= 0:
            raise ValueError("order_quantity must be positive")
        if update.update_type == BrokerOrderUpdateType.FILL and resolved_order_quantity is None:
            raise ValueError("order_quantity is required for fill updates")
        if (
            self._position_ledger is not None
            and update.update_type == BrokerOrderUpdateType.FILL
            and resolved_order_side is None
        ):
            raise ValueError("order_side is required when position ledger is configured")

        if update.update_type == BrokerOrderUpdateType.WORKING:
            updated = lifecycle.mark_working()
        elif update.update_type == BrokerOrderUpdateType.FILL:
            assert resolved_order_quantity is not None
            updated = lifecycle.record_fill(update.fill_quantity, resolved_order_quantity)
        elif update.update_type == BrokerOrderUpdateType.CANCELED:
            updated = lifecycle.mark_canceled()
        elif update.update_type == BrokerOrderUpdateType.REJECTED:
            updated = lifecycle.mark_rejected(update.reject_reason or "")
        else:
            raise ValueError(f"unsupported broker update type: {update.update_type}")

        self._audit_log.append(
            {
                "type": "order_update_applied",
                "timestamp": update.timestamp.isoformat(),
                "account_id": update.account_id,
                "client_order_id": update.client_order_id,
                "broker_order_id": update.broker_order_id,
                "instrument_id": update.instrument_id,
                "update_type": update.update_type.value,
                "status": updated.status.value,
                "fill_quantity": update.fill_quantity,
                "filled_quantity": updated.filled_quantity,
                "reject_reason": updated.reject_reason,
                "broker_error_code": update.broker_error_code,
            }
        )
        if self._lifecycle_store is not None:
            self._lifecycle_store.save(updated)
        if self._position_ledger is not None and update.update_type == BrokerOrderUpdateType.FILL:
            assert resolved_order_side is not None
            self._position_ledger.apply_fill(update, resolved_order_side)
        return updated
