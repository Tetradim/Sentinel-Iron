from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from futures_bot.application.order_activity import OrderActivityRecord
from futures_bot.application.order_cancellation import (
    OrderCancellationRequest,
    OrderCancellationService,
)
from futures_bot.domain.order_lifecycle import OrderLifecycle, OrderLifecycleStatus
from futures_bot.ports.audit import AuditLogPort
from futures_bot.ports.broker import BrokerPort


class OrderActivityStorePort(Protocol):
    def load(self) -> tuple[OrderActivityRecord, ...]:
        """Load broker-accepted order activity."""


class OrderLifecycleStorePort(Protocol):
    def load(self, client_order_id: str) -> OrderLifecycle | None:
        """Load the latest persisted lifecycle for a client order ID."""

    def save(self, lifecycle: OrderLifecycle) -> None:
        """Persist the latest known order lifecycle."""


@dataclass(frozen=True)
class KillSwitchEnforcementResult:
    candidate_count: int
    cancel_requested_count: int
    skipped_count: int
    failed_count: int


class KillSwitchEnforcementService:
    def __init__(
        self,
        broker: BrokerPort,
        audit_log: AuditLogPort,
        activity_store: OrderActivityStorePort,
        lifecycle_store: OrderLifecycleStorePort,
    ) -> None:
        self._audit_log = audit_log
        self._activity_store = activity_store
        self._lifecycle_store = lifecycle_store
        self._cancellation = OrderCancellationService(
            broker=broker,
            audit_log=audit_log,
            lifecycle_store=lifecycle_store,
        )

    def cancel_working_orders(
        self,
        account_id: str,
        timestamp: datetime,
    ) -> KillSwitchEnforcementResult:
        if not account_id:
            raise ValueError("account_id is required")

        candidate_count = 0
        cancel_requested_count = 0
        skipped_count = 0
        failed_count = 0

        for record in self._activity_store.load():
            candidate_count += 1
            lifecycle = self._lifecycle_store.load(record.client_order_id)
            if not _is_cancel_candidate(lifecycle):
                skipped_count += 1
                continue

            result = self._cancellation.request_cancel(
                lifecycle,
                OrderCancellationRequest(
                    account_id=account_id,
                    client_order_id=record.client_order_id,
                    broker_order_id=record.broker_order_id,
                    instrument_id=record.instrument_id,
                    timestamp=timestamp,
                ),
            )
            if result.cancellation_requested:
                cancel_requested_count += 1
            else:
                failed_count += 1

        self._audit_log.append(
            {
                "type": "kill_switch_cancel_sweep_completed",
                "timestamp": timestamp.isoformat(),
                "account_id": account_id,
                "candidate_count": candidate_count,
                "cancel_requested_count": cancel_requested_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count,
            }
        )
        return KillSwitchEnforcementResult(
            candidate_count=candidate_count,
            cancel_requested_count=cancel_requested_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
        )


def _is_cancel_candidate(lifecycle: OrderLifecycle | None) -> bool:
    if lifecycle is None:
        return False
    return lifecycle.status in {
        OrderLifecycleStatus.WORKING,
        OrderLifecycleStatus.PARTIALLY_FILLED,
    }
