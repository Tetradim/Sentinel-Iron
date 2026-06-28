from __future__ import annotations

from dataclasses import dataclass

from futures_bot.application.risk_check import RiskCheckService
from futures_bot.domain.order_lifecycle import OrderLifecycle
from futures_bot.domain.orders import BrokerOrder, OrderIntent
from futures_bot.ports.audit import AuditLogPort
from futures_bot.ports.broker import BrokerPort
from futures_bot.risk.engine import RiskContext, RiskDecision


@dataclass(frozen=True)
class OrderSubmissionResult:
    risk_decision: RiskDecision
    lifecycle: OrderLifecycle
    broker_order_id: str | None


class OrderSubmissionService:
    def __init__(
        self,
        risk_check: RiskCheckService,
        broker: BrokerPort,
        audit_log: AuditLogPort,
    ) -> None:
        self._risk_check = risk_check
        self._broker = broker
        self._audit_log = audit_log

    def submit(self, intent: OrderIntent, context: RiskContext) -> OrderSubmissionResult:
        risk_decision = self._risk_check.check(intent, context)
        lifecycle = OrderLifecycle.pending_submit(client_order_id=intent.client_order_id)

        if not risk_decision.approved:
            rejected = lifecycle.mark_rejected(risk_decision.detail)
            self._audit_log.append(
                {
                    "type": "order_submission_blocked",
                    "timestamp": context.now.isoformat(),
                    "account_id": context.account.account_id,
                    "client_order_id": intent.client_order_id,
                    "instrument_id": intent.instrument_id,
                    "status": rejected.status.value,
                    "reason": risk_decision.reason.value if risk_decision.reason is not None else None,
                    "detail": risk_decision.detail,
                }
            )
            return OrderSubmissionResult(
                risk_decision=risk_decision,
                lifecycle=rejected,
                broker_order_id=None,
            )

        broker_order = BrokerOrder.from_intent(intent)
        broker_order_id = self._broker.submit_order(broker_order)
        working = lifecycle.mark_working()
        self._audit_log.append(
            {
                "type": "order_submitted",
                "timestamp": context.now.isoformat(),
                "account_id": context.account.account_id,
                "client_order_id": intent.client_order_id,
                "broker_order_id": broker_order_id,
                "instrument_id": intent.instrument_id,
                "status": working.status.value,
            }
        )
        return OrderSubmissionResult(
            risk_decision=risk_decision,
            lifecycle=working,
            broker_order_id=broker_order_id,
        )
