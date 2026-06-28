from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from futures_bot.application.order_gateway import OrderGatewayResult
from futures_bot.application.rebalance_execution import (
    RebalanceExecutionCoordinator,
    RebalanceExecutionDecision,
)
from futures_bot.application.trading_readiness import TradingReadinessResult
from futures_bot.domain.orders import OrderIntent
from futures_bot.risk.engine import RiskContext


class OrderGatewayPort(Protocol):
    def submit(
        self,
        intent: OrderIntent,
        context: RiskContext,
        readiness: TradingReadinessResult,
        timestamp: datetime,
    ) -> OrderGatewayResult:
        """Submit an intent through the readiness-gated order path."""


@dataclass(frozen=True)
class RebalancePhaseSubmissionResult:
    decision: RebalanceExecutionDecision
    gateway_results: tuple[OrderGatewayResult, ...]
    reason: str | None
    detail: str


class RebalancePhaseSubmissionService:
    def __init__(
        self,
        coordinator: RebalanceExecutionCoordinator,
        gateway: OrderGatewayPort,
    ) -> None:
        self._coordinator = coordinator
        self._gateway = gateway

    def submit_next_phase(
        self,
        phases: tuple[tuple[OrderIntent, ...], ...],
        contexts_by_client_order_id: Mapping[str, RiskContext],
        readiness: TradingReadinessResult,
        timestamp: datetime,
    ) -> RebalancePhaseSubmissionResult:
        decision = self._coordinator.next_intents(phases)
        if decision.reason is not None:
            return RebalancePhaseSubmissionResult(
                decision=decision,
                gateway_results=(),
                reason=decision.reason,
                detail=decision.detail,
            )

        missing_context_intent = self._first_missing_context(
            decision.eligible_intents,
            contexts_by_client_order_id,
        )
        if missing_context_intent is not None:
            return RebalancePhaseSubmissionResult(
                decision=decision,
                gateway_results=(),
                reason="missing_risk_context",
                detail=f"risk context is required for {missing_context_intent.client_order_id}",
            )

        gateway_results: list[OrderGatewayResult] = []
        for intent in decision.eligible_intents:
            gateway_result = self._gateway.submit(
                intent=intent,
                context=contexts_by_client_order_id[intent.client_order_id],
                readiness=readiness,
                timestamp=timestamp,
            )
            gateway_results.append(gateway_result)
            if not gateway_result.submitted:
                return RebalancePhaseSubmissionResult(
                    decision=decision,
                    gateway_results=tuple(gateway_results),
                    reason="phase_submission_failed",
                    detail=gateway_result.detail,
                )

        return RebalancePhaseSubmissionResult(
            decision=decision,
            gateway_results=tuple(gateway_results),
            reason=None,
            detail=(
                f"submitted {len(gateway_results)} intents "
                f"for phase {decision.phase_index}"
            ),
        )

    def _first_missing_context(
        self,
        eligible_intents: tuple[OrderIntent, ...],
        contexts_by_client_order_id: Mapping[str, RiskContext],
    ) -> OrderIntent | None:
        for intent in eligible_intents:
            if intent.client_order_id not in contexts_by_client_order_id:
                return intent
        return None
