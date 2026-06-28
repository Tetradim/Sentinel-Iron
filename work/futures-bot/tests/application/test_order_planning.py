from decimal import Decimal

from futures_bot.application.order_planning import (
    OrderPlanningConfig,
    plan_order_to_target,
    plan_rebalance_order_phases,
    plan_orders_to_targets,
)
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.portfolio import Position
from futures_bot.portfolio.position_sizing import PositionTarget


def _position(quantity: int, instrument_id: str = "ES-202609-CME") -> Position:
    return Position(
        instrument_id=instrument_id,
        quantity=quantity,
        average_price=Decimal("5000"),
    )


def test_plan_order_to_target_creates_buy_intent_for_positive_delta():
    intent = plan_order_to_target(
        target=PositionTarget(instrument_id="ES-202609-CME", quantity=5),
        current_position=_position(2),
        config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
    )

    assert intent is not None
    assert intent.side == OrderSide.BUY
    assert intent.quantity == 3
    assert intent.client_order_id == "rebalance-ES-202609-CME-buy-3"


def test_plan_order_to_target_creates_sell_intent_for_negative_delta():
    intent = plan_order_to_target(
        target=PositionTarget(instrument_id="ES-202609-CME", quantity=-2),
        current_position=_position(1),
        config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
    )

    assert intent is not None
    assert intent.side == OrderSide.SELL
    assert intent.quantity == 3
    assert intent.client_order_id == "rebalance-ES-202609-CME-sell-3"


def test_plan_order_to_target_returns_none_when_already_at_target():
    intent = plan_order_to_target(
        target=PositionTarget(instrument_id="ES-202609-CME", quantity=2),
        current_position=_position(2),
        config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
    )

    assert intent is None


def test_plan_order_to_target_propagates_limit_price():
    intent = plan_order_to_target(
        target=PositionTarget(instrument_id="ES-202609-CME", quantity=3),
        current_position=_position(1),
        config=OrderPlanningConfig(
            client_order_prefix="rebalance",
            order_type=OrderType.LIMIT,
            limit_price=Decimal("5001.25"),
        ),
    )

    assert intent is not None
    assert intent.order_type == OrderType.LIMIT
    assert intent.limit_price == Decimal("5001.25")


def test_order_planning_rejects_instrument_mismatch():
    try:
        plan_order_to_target(
            target=PositionTarget(instrument_id="NQ-202609-CME", quantity=3),
            current_position=_position(1),
            config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
        )
    except ValueError as exc:
        assert str(exc) == "target and current_position instruments must match"
    else:
        raise AssertionError("expected instrument mismatch to be rejected")


def test_plan_orders_to_targets_orders_risk_reducing_deltas_before_new_exposure():
    intents = plan_orders_to_targets(
        targets=(
            PositionTarget(instrument_id="NQ-202609-CME", quantity=2),
            PositionTarget(instrument_id="ES-202609-CME", quantity=2),
            PositionTarget(instrument_id="CL-202609-NYMEX", quantity=-1),
        ),
        current_positions={
            "NQ-202609-CME": _position(0, instrument_id="NQ-202609-CME"),
            "ES-202609-CME": _position(5, instrument_id="ES-202609-CME"),
            "CL-202609-NYMEX": _position(-3, instrument_id="CL-202609-NYMEX"),
        },
        config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
    )

    assert [(intent.instrument_id, intent.side, intent.quantity) for intent in intents] == [
        ("ES-202609-CME", OrderSide.SELL, 3),
        ("CL-202609-NYMEX", OrderSide.BUY, 2),
        ("NQ-202609-CME", OrderSide.BUY, 2),
    ]


def test_plan_orders_to_targets_skips_positions_already_at_target():
    intents = plan_orders_to_targets(
        targets=(
            PositionTarget(instrument_id="ES-202609-CME", quantity=2),
            PositionTarget(instrument_id="NQ-202609-CME", quantity=1),
        ),
        current_positions={
            "ES-202609-CME": _position(2, instrument_id="ES-202609-CME"),
            "NQ-202609-CME": _position(0, instrument_id="NQ-202609-CME"),
        },
        config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
    )

    assert [(intent.instrument_id, intent.side, intent.quantity) for intent in intents] == [
        ("NQ-202609-CME", OrderSide.BUY, 1),
    ]


def test_plan_orders_to_targets_splits_long_to_short_reversal():
    intents = plan_orders_to_targets(
        targets=(PositionTarget(instrument_id="ES-202609-CME", quantity=-2),),
        current_positions={"ES-202609-CME": _position(2)},
        config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
    )

    assert [(intent.side, intent.quantity, intent.client_order_id) for intent in intents] == [
        (OrderSide.SELL, 2, "rebalance-ES-202609-CME-sell-2-flatten"),
        (OrderSide.SELL, 2, "rebalance-ES-202609-CME-sell-2-open"),
    ]


def test_plan_orders_to_targets_splits_short_to_long_reversal():
    intents = plan_orders_to_targets(
        targets=(PositionTarget(instrument_id="ES-202609-CME", quantity=1),),
        current_positions={"ES-202609-CME": _position(-3)},
        config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
    )

    assert [(intent.side, intent.quantity, intent.client_order_id) for intent in intents] == [
        (OrderSide.BUY, 3, "rebalance-ES-202609-CME-buy-3-flatten"),
        (OrderSide.BUY, 1, "rebalance-ES-202609-CME-buy-1-open"),
    ]


def test_plan_rebalance_order_phases_separates_reducing_orders_from_new_exposure():
    phases = plan_rebalance_order_phases(
        targets=(
            PositionTarget(instrument_id="NQ-202609-CME", quantity=2),
            PositionTarget(instrument_id="ES-202609-CME", quantity=-2),
            PositionTarget(instrument_id="CL-202609-NYMEX", quantity=-1),
        ),
        current_positions={
            "NQ-202609-CME": _position(0, instrument_id="NQ-202609-CME"),
            "ES-202609-CME": _position(2, instrument_id="ES-202609-CME"),
            "CL-202609-NYMEX": _position(-3, instrument_id="CL-202609-NYMEX"),
        },
        config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
    )

    assert [
        [(intent.instrument_id, intent.side, intent.quantity) for intent in phase]
        for phase in phases
    ] == [
        [
            ("ES-202609-CME", OrderSide.SELL, 2),
            ("CL-202609-NYMEX", OrderSide.BUY, 2),
        ],
        [
            ("NQ-202609-CME", OrderSide.BUY, 2),
            ("ES-202609-CME", OrderSide.SELL, 2),
        ],
    ]


def test_plan_rebalance_order_phases_omits_empty_phases():
    phases = plan_rebalance_order_phases(
        targets=(PositionTarget(instrument_id="ES-202609-CME", quantity=4),),
        current_positions={"ES-202609-CME": _position(2)},
        config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
    )

    assert [[intent.client_order_id for intent in phase] for phase in phases] == [
        ["rebalance-ES-202609-CME-buy-2"]
    ]


def test_plan_orders_to_targets_rejects_duplicate_targets():
    try:
        plan_orders_to_targets(
            targets=(
                PositionTarget(instrument_id="ES-202609-CME", quantity=2),
                PositionTarget(instrument_id="ES-202609-CME", quantity=3),
            ),
            current_positions={"ES-202609-CME": _position(1)},
            config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
        )
    except ValueError as exc:
        assert str(exc) == "target instrument IDs must be unique"
    else:
        raise AssertionError("expected duplicate targets to be rejected")


def test_plan_orders_to_targets_rejects_missing_current_position():
    try:
        plan_orders_to_targets(
            targets=(PositionTarget(instrument_id="ES-202609-CME", quantity=2),),
            current_positions={},
            config=OrderPlanningConfig(client_order_prefix="rebalance", order_type=OrderType.MARKET),
        )
    except ValueError as exc:
        assert str(exc) == "current position is required for ES-202609-CME"
    else:
        raise AssertionError("expected missing current position to be rejected")
