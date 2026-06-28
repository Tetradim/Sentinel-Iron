from datetime import datetime, timezone

from futures_bot.application.order_gateway import OrderGatewayResult
from futures_bot.application.rebalance_execution import RebalanceExecutionCoordinator
from futures_bot.application.rebalance_phase_submission import (
    RebalancePhaseSubmissionService,
)
from futures_bot.application.trading_readiness import TradingReadinessResult
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.order_lifecycle import OrderLifecycle
from futures_bot.domain.orders import OrderIntent


NOW = datetime(2026, 6, 28, 15, 20, tzinfo=timezone.utc)


class RecordingLifecycleStore:
    def __init__(self, lifecycles: dict[str, OrderLifecycle] | None = None) -> None:
        self.lifecycles = lifecycles or {}

    def load(self, client_order_id: str) -> OrderLifecycle | None:
        return self.lifecycles.get(client_order_id)


class RecordingGateway:
    def __init__(self, submitted: bool = True) -> None:
        self.submitted = submitted
        self.submissions: list[
            tuple[OrderIntent, object, TradingReadinessResult, datetime]
        ] = []

    def submit(
        self,
        intent: OrderIntent,
        context: object,
        readiness: TradingReadinessResult,
        timestamp: datetime,
    ) -> OrderGatewayResult:
        self.submissions.append((intent, context, readiness, timestamp))
        return OrderGatewayResult(
            submitted=self.submitted,
            readiness=readiness,
            submission=None,
            reason=None if self.submitted else "order_not_submitted",
            detail="submitted" if self.submitted else "risk rejected order",
        )


def _intent(client_order_id: str, instrument_id: str = "ES-202609-CME") -> OrderIntent:
    return OrderIntent(
        instrument_id=instrument_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        client_order_id=client_order_id,
    )


def _service(
    lifecycle_store: RecordingLifecycleStore,
    gateway: RecordingGateway,
) -> RebalancePhaseSubmissionService:
    return RebalancePhaseSubmissionService(
        coordinator=RebalanceExecutionCoordinator(lifecycle_store=lifecycle_store),
        gateway=gateway,
    )


def _readiness() -> TradingReadinessResult:
    return TradingReadinessResult(ready=True, reason=None, detail="ready")


def test_rebalance_phase_submission_submits_eligible_phase_intents_through_gateway():
    gateway = RecordingGateway()
    service = _service(RecordingLifecycleStore(), gateway)
    reduce_context = object()
    second_reduce_context = object()

    result = service.submit_next_phase(
        phases=((_intent("reduce-1"), _intent("reduce-2", "CL-202609-NYMEX")),),
        contexts_by_client_order_id={
            "reduce-1": reduce_context,
            "reduce-2": second_reduce_context,
        },
        readiness=_readiness(),
        timestamp=NOW,
    )

    assert result.reason is None
    assert result.detail == "submitted 2 intents for phase 0"
    assert result.decision.phase_index == 0
    assert [submission[0].client_order_id for submission in gateway.submissions] == [
        "reduce-1",
        "reduce-2",
    ]
    assert [submission[1] for submission in gateway.submissions] == [
        reduce_context,
        second_reduce_context,
    ]


def test_rebalance_phase_submission_does_not_call_gateway_while_waiting_for_fills():
    lifecycle = OrderLifecycle.pending_submit("reduce-1").mark_working()
    gateway = RecordingGateway()
    service = _service(RecordingLifecycleStore({"reduce-1": lifecycle}), gateway)

    result = service.submit_next_phase(
        phases=((_intent("reduce-1"),), (_intent("open-1"),)),
        contexts_by_client_order_id={"open-1": object()},
        readiness=_readiness(),
        timestamp=NOW,
    )

    assert result.reason == "waiting_for_phase_fills"
    assert result.gateway_results == ()
    assert gateway.submissions == []


def test_rebalance_phase_submission_fails_closed_when_context_is_missing():
    gateway = RecordingGateway()
    service = _service(RecordingLifecycleStore(), gateway)

    result = service.submit_next_phase(
        phases=((_intent("reduce-1"), _intent("reduce-2")),),
        contexts_by_client_order_id={"reduce-1": object()},
        readiness=_readiness(),
        timestamp=NOW,
    )

    assert result.reason == "missing_risk_context"
    assert result.detail == "risk context is required for reduce-2"
    assert result.gateway_results == ()
    assert gateway.submissions == []


def test_rebalance_phase_submission_stops_after_gateway_rejects_intent():
    gateway = RecordingGateway(submitted=False)
    service = _service(RecordingLifecycleStore(), gateway)

    result = service.submit_next_phase(
        phases=((_intent("reduce-1"), _intent("reduce-2")),),
        contexts_by_client_order_id={"reduce-1": object(), "reduce-2": object()},
        readiness=_readiness(),
        timestamp=NOW,
    )

    assert result.reason == "phase_submission_failed"
    assert result.detail == "risk rejected order"
    assert [gateway_result.submitted for gateway_result in result.gateway_results] == [
        False
    ]
    assert [submission[0].client_order_id for submission in gateway.submissions] == [
        "reduce-1"
    ]
