from __future__ import annotations

from futures_bot.domain.orders import OrderIntent
from futures_bot.ports.audit import AuditLogPort
from futures_bot.risk.engine import RiskContext, RiskDecision, RiskEngine


class RiskCheckService:
    def __init__(self, risk_engine: RiskEngine, audit_log: AuditLogPort) -> None:
        self._risk_engine = risk_engine
        self._audit_log = audit_log

    def check(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        decision = self._risk_engine.evaluate(intent, context)
        self._audit_log.append(
            {
                "type": "risk_decision",
                "timestamp": context.now.isoformat(),
                "account_id": context.account.account_id,
                "client_order_id": intent.client_order_id,
                "instrument_id": intent.instrument_id,
                "approved": decision.approved,
                "reason": decision.reason.value if decision.reason is not None else None,
                "detail": decision.detail,
                "side": intent.side.value,
                "quantity": intent.quantity,
                "order_type": intent.order_type.value,
                "limit_price": str(intent.limit_price) if intent.limit_price is not None else None,
            }
        )
        return decision
