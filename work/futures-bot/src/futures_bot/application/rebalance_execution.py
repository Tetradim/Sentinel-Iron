from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from futures_bot.domain.order_lifecycle import OrderLifecycle, OrderLifecycleStatus
from futures_bot.domain.orders import OrderIntent


@dataclass(frozen=True)
class RebalanceExecutionDecision:
    phase_index: int | None
    eligible_intents: tuple[OrderIntent, ...]
    reason: str | None
    detail: str


class OrderLifecycleStorePort(Protocol):
    def load(self, client_order_id: str) -> OrderLifecycle | None:
        """Load the latest persisted lifecycle for a client order ID."""


class RebalanceExecutionCoordinator:
    def __init__(self, lifecycle_store: OrderLifecycleStorePort) -> None:
        self._lifecycle_store = lifecycle_store

    def next_intents(
        self,
        phases: tuple[tuple[OrderIntent, ...], ...],
    ) -> RebalanceExecutionDecision:
        for phase_index, phase in enumerate(phases):
            if not phase:
                continue

            phase_state = tuple(
                (intent, self._lifecycle_store.load(intent.client_order_id))
                for intent in phase
            )

            failed_intent, failed_lifecycle = self._first_failed_lifecycle(phase_state)
            if failed_intent is not None and failed_lifecycle is not None:
                return RebalanceExecutionDecision(
                    phase_index=phase_index,
                    eligible_intents=(),
                    reason="rebalance_phase_failed",
                    detail=f"{failed_intent.client_order_id} is {failed_lifecycle.status.value}",
                )

            eligible_intents = tuple(
                intent for intent, lifecycle in phase_state if lifecycle is None
            )
            if eligible_intents:
                return RebalanceExecutionDecision(
                    phase_index=phase_index,
                    eligible_intents=eligible_intents,
                    reason=None,
                    detail=f"phase {phase_index} has unsubmitted intents",
                )

            if not self._phase_is_filled(phase_state):
                return RebalanceExecutionDecision(
                    phase_index=phase_index,
                    eligible_intents=(),
                    reason="waiting_for_phase_fills",
                    detail=f"phase {phase_index} has submitted intents that are not filled",
                )

        return RebalanceExecutionDecision(
            phase_index=None,
            eligible_intents=(),
            reason="rebalance_complete",
            detail="all rebalance phases are filled",
        )

    def _first_failed_lifecycle(
        self,
        phase_state: tuple[tuple[OrderIntent, OrderLifecycle | None], ...],
    ) -> tuple[OrderIntent | None, OrderLifecycle | None]:
        for intent, lifecycle in phase_state:
            if lifecycle is not None and lifecycle.status in {
                OrderLifecycleStatus.CANCELED,
                OrderLifecycleStatus.REJECTED,
            }:
                return intent, lifecycle
        return None, None

    def _phase_is_filled(
        self,
        phase_state: tuple[tuple[OrderIntent, OrderLifecycle | None], ...],
    ) -> bool:
        return all(
            lifecycle is not None and lifecycle.status == OrderLifecycleStatus.FILLED
            for _, lifecycle in phase_state
        )
