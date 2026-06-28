from datetime import datetime, timezone
from decimal import Decimal

from futures_bot.application.margin_estimates import (
    MarginEstimateService,
    MarginEstimateUnavailable,
)
from futures_bot.application.rebalance_risk_context import MarginEstimate
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder, OrderIntent
from futures_bot.ports.audit import InMemoryAuditLog


NOW = datetime(2026, 6, 28, 16, 15, tzinfo=timezone.utc)


class RecordingMarginProvider:
    def __init__(
        self,
        estimate: MarginEstimate | None = None,
        error: MarginEstimateUnavailable | None = None,
    ) -> None:
        self.estimate = estimate or MarginEstimate(
            initial_margin=Decimal("12000"),
            maintenance_margin=Decimal("10000"),
        )
        self.error = error
        self.orders: list[BrokerOrder] = []

    def estimate_order_margin(self, order: BrokerOrder) -> MarginEstimate:
        self.orders.append(order)
        if self.error is not None:
            raise self.error
        return self.estimate


def _intent(client_order_id: str = "order-1") -> OrderIntent:
    return OrderIntent(
        instrument_id="ES-202609-CME",
        side=OrderSide.BUY,
        quantity=2,
        order_type=OrderType.MARKET,
        client_order_id=client_order_id,
    )


def test_margin_estimate_service_requests_provider_for_each_intent_and_audits():
    audit_log = InMemoryAuditLog()
    provider = RecordingMarginProvider()
    service = MarginEstimateService(provider=provider, audit_log=audit_log)

    estimates = service.estimate_for_intents(
        intents=(_intent("order-1"), _intent("order-2")),
        timestamp=NOW,
    )

    assert estimates == {
        "order-1": MarginEstimate(Decimal("12000"), Decimal("10000")),
        "order-2": MarginEstimate(Decimal("12000"), Decimal("10000")),
    }
    assert provider.orders == [
        BrokerOrder.from_intent(_intent("order-1")),
        BrokerOrder.from_intent(_intent("order-2")),
    ]
    assert audit_log.events == (
        {
            "type": "margin_estimate",
            "timestamp": "2026-06-28T16:15:00+00:00",
            "client_order_id": "order-1",
            "instrument_id": "ES-202609-CME",
            "initial_margin": "12000",
            "maintenance_margin": "10000",
        },
        {
            "type": "margin_estimate",
            "timestamp": "2026-06-28T16:15:00+00:00",
            "client_order_id": "order-2",
            "instrument_id": "ES-202609-CME",
            "initial_margin": "12000",
            "maintenance_margin": "10000",
        },
    )


def test_margin_estimate_service_rejects_duplicate_client_order_ids_before_provider_call():
    provider = RecordingMarginProvider()
    service = MarginEstimateService(provider=provider, audit_log=InMemoryAuditLog())

    try:
        service.estimate_for_intents(
            intents=(_intent("order-1"), _intent("order-1")),
            timestamp=NOW,
        )
    except ValueError as exc:
        assert str(exc) == "intent client order IDs must be unique"
    else:
        raise AssertionError("expected duplicate client order IDs to be rejected")

    assert provider.orders == []


def test_margin_estimate_service_audits_provider_failure_and_reraises():
    audit_log = InMemoryAuditLog()
    provider = RecordingMarginProvider(
        error=MarginEstimateUnavailable(
            reason="IBKR what-if margin request failed",
            broker_error_code="201",
        )
    )
    service = MarginEstimateService(provider=provider, audit_log=audit_log)

    try:
        service.estimate_for_intents(intents=(_intent(),), timestamp=NOW)
    except MarginEstimateUnavailable as exc:
        assert exc.reason == "IBKR what-if margin request failed"
        assert exc.broker_error_code == "201"
    else:
        raise AssertionError("expected provider failure to be reraised")

    assert audit_log.events == (
        {
            "type": "margin_estimate_failed",
            "timestamp": "2026-06-28T16:15:00+00:00",
            "client_order_id": "order-1",
            "instrument_id": "ES-202609-CME",
            "reason": "IBKR what-if margin request failed",
            "broker_error_code": "201",
        },
    )
