from futures_bot.application.rebalance_execution import RebalanceExecutionCoordinator
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.order_lifecycle import OrderLifecycle, OrderLifecycleStatus
from futures_bot.domain.orders import OrderIntent


class RecordingLifecycleStore:
    def __init__(self, lifecycles: dict[str, OrderLifecycle] | None = None) -> None:
        self.lifecycles = lifecycles or {}
        self.loaded_client_order_ids: list[str] = []

    def load(self, client_order_id: str) -> OrderLifecycle | None:
        self.loaded_client_order_ids.append(client_order_id)
        return self.lifecycles.get(client_order_id)


def _intent(client_order_id: str, instrument_id: str = "ES-202609-CME") -> OrderIntent:
    return OrderIntent(
        instrument_id=instrument_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        client_order_id=client_order_id,
        limit_price=None,
    )


def test_rebalance_execution_returns_unsubmitted_first_phase_intents():
    store = RecordingLifecycleStore()
    coordinator = RebalanceExecutionCoordinator(lifecycle_store=store)

    decision = coordinator.next_intents(
        phases=(
            (_intent("reduce-1"), _intent("reduce-2", instrument_id="CL-202609-NYMEX")),
            (_intent("open-1", instrument_id="NQ-202609-CME"),),
        )
    )

    assert decision.phase_index == 0
    assert [intent.client_order_id for intent in decision.eligible_intents] == [
        "reduce-1",
        "reduce-2",
    ]
    assert decision.reason is None
    assert decision.detail == "phase 0 has unsubmitted intents"
    assert store.loaded_client_order_ids == ["reduce-1", "reduce-2"]


def test_rebalance_execution_waits_for_phase_fills_before_opening_exposure():
    store = RecordingLifecycleStore(
        {
            "reduce-1": OrderLifecycle.pending_submit("reduce-1").mark_working(),
        }
    )
    coordinator = RebalanceExecutionCoordinator(lifecycle_store=store)

    decision = coordinator.next_intents(
        phases=((_intent("reduce-1"),), (_intent("open-1"),))
    )

    assert decision.phase_index == 0
    assert decision.eligible_intents == ()
    assert decision.reason == "waiting_for_phase_fills"
    assert decision.detail == "phase 0 has submitted intents that are not filled"
    assert store.loaded_client_order_ids == ["reduce-1"]


def test_rebalance_execution_allows_next_phase_after_prior_phase_fills():
    store = RecordingLifecycleStore(
        {
            "reduce-1": OrderLifecycle(
                client_order_id="reduce-1",
                status=OrderLifecycleStatus.FILLED,
                filled_quantity=1,
            ),
        }
    )
    coordinator = RebalanceExecutionCoordinator(lifecycle_store=store)

    decision = coordinator.next_intents(
        phases=((_intent("reduce-1"),), (_intent("open-1"),))
    )

    assert decision.phase_index == 1
    assert [intent.client_order_id for intent in decision.eligible_intents] == ["open-1"]
    assert decision.reason is None
    assert decision.detail == "phase 1 has unsubmitted intents"
    assert store.loaded_client_order_ids == ["reduce-1", "open-1"]


def test_rebalance_execution_blocks_after_phase_rejection():
    store = RecordingLifecycleStore(
        {
            "reduce-1": OrderLifecycle.pending_submit("reduce-1").mark_rejected(
                "exchange rejected order"
            ),
        }
    )
    coordinator = RebalanceExecutionCoordinator(lifecycle_store=store)

    decision = coordinator.next_intents(
        phases=((_intent("reduce-1"),), (_intent("open-1"),))
    )

    assert decision.phase_index == 0
    assert decision.eligible_intents == ()
    assert decision.reason == "rebalance_phase_failed"
    assert decision.detail == "reduce-1 is rejected"
    assert store.loaded_client_order_ids == ["reduce-1"]


def test_rebalance_execution_reports_completion_after_all_phases_fill():
    store = RecordingLifecycleStore(
        {
            "reduce-1": OrderLifecycle(
                client_order_id="reduce-1",
                status=OrderLifecycleStatus.FILLED,
                filled_quantity=1,
            ),
            "open-1": OrderLifecycle(
                client_order_id="open-1",
                status=OrderLifecycleStatus.FILLED,
                filled_quantity=1,
            ),
        }
    )
    coordinator = RebalanceExecutionCoordinator(lifecycle_store=store)

    decision = coordinator.next_intents(
        phases=((_intent("reduce-1"),), (_intent("open-1"),))
    )

    assert decision.phase_index is None
    assert decision.eligible_intents == ()
    assert decision.reason == "rebalance_complete"
    assert decision.detail == "all rebalance phases are filled"
