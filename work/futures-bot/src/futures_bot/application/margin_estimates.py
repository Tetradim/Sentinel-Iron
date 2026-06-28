from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from futures_bot.application.rebalance_risk_context import MarginEstimate
from futures_bot.domain.orders import BrokerOrder, OrderIntent
from futures_bot.ports.audit import AuditLogPort


class MarginEstimateUnavailable(RuntimeError):
    def __init__(self, reason: str, broker_error_code: str | None = None) -> None:
        if not reason:
            raise ValueError("reason is required")
        super().__init__(reason)
        self.reason = reason
        self.broker_error_code = broker_error_code


class MarginEstimateProviderPort(Protocol):
    def estimate_order_margin(self, order: BrokerOrder) -> MarginEstimate:
        """Estimate margin impact for an order without submitting it."""


@dataclass(frozen=True)
class MarginEstimateService:
    provider: MarginEstimateProviderPort
    audit_log: AuditLogPort

    def estimate_for_intents(
        self,
        intents: tuple[OrderIntent, ...],
        timestamp: datetime,
    ) -> dict[str, MarginEstimate]:
        self._validate_unique_client_order_ids(intents)

        estimates: dict[str, MarginEstimate] = {}
        for intent in intents:
            try:
                estimate = self.provider.estimate_order_margin(
                    BrokerOrder.from_intent(intent)
                )
            except MarginEstimateUnavailable as exc:
                self.audit_log.append(
                    {
                        "type": "margin_estimate_failed",
                        "timestamp": timestamp.isoformat(),
                        "client_order_id": intent.client_order_id,
                        "instrument_id": intent.instrument_id,
                        "reason": exc.reason,
                        "broker_error_code": exc.broker_error_code,
                    }
                )
                raise

            estimates[intent.client_order_id] = estimate
            self.audit_log.append(
                {
                    "type": "margin_estimate",
                    "timestamp": timestamp.isoformat(),
                    "client_order_id": intent.client_order_id,
                    "instrument_id": intent.instrument_id,
                    "initial_margin": str(estimate.initial_margin),
                    "maintenance_margin": str(estimate.maintenance_margin),
                }
            )

        return estimates

    def _validate_unique_client_order_ids(self, intents: tuple[OrderIntent, ...]) -> None:
        seen_client_order_ids: set[str] = set()
        for intent in intents:
            if intent.client_order_id in seen_client_order_ids:
                raise ValueError("intent client order IDs must be unique")
            seen_client_order_ids.add(intent.client_order_id)
