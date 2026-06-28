from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from futures_bot.application.order_submission import OrderSubmissionResult, OrderSubmissionService
from futures_bot.application.trading_readiness import TradingReadinessResult
from futures_bot.domain.orders import OrderIntent
from futures_bot.ports.audit import AuditLogPort
from futures_bot.risk.engine import RiskContext


@dataclass(frozen=True)
class OrderGatewayResult:
    submitted: bool
    readiness: TradingReadinessResult
    submission: OrderSubmissionResult | None
    reason: str | None
    detail: str


class OrderGatewayService:
    def __init__(self, submission: OrderSubmissionService, audit_log: AuditLogPort) -> None:
        self._submission = submission
        self._audit_log = audit_log

    def submit(
        self,
        intent: OrderIntent,
        context: RiskContext,
        readiness: TradingReadinessResult,
        timestamp: datetime,
    ) -> OrderGatewayResult:
        if not readiness.ready:
            self._audit_log.append(
                {
                    "type": "order_submission_blocked",
                    "timestamp": timestamp.isoformat(),
                    "client_order_id": intent.client_order_id,
                    "instrument_id": intent.instrument_id,
                    "reason": "trading_not_ready",
                    "detail": readiness.detail,
                    "readiness_reason": readiness.reason,
                    "side": intent.side.value,
                    "quantity": intent.quantity,
                    "order_type": intent.order_type.value,
                    "limit_price": str(intent.limit_price) if intent.limit_price is not None else None,
                }
            )
            return OrderGatewayResult(
                submitted=False,
                readiness=readiness,
                submission=None,
                reason="trading_not_ready",
                detail=readiness.detail,
            )

        submission = self._submission.submit(intent, context)
        submitted = submission.broker_order_id is not None
        return OrderGatewayResult(
            submitted=submitted,
            readiness=readiness,
            submission=submission,
            reason=None if submitted else "order_not_submitted",
            detail="submitted" if submitted else submission.lifecycle.reject_reason or submission.risk_decision.detail,
        )
