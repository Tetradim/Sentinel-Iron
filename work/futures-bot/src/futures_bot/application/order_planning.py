from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import OrderIntent
from futures_bot.domain.portfolio import Position
from futures_bot.portfolio.position_sizing import PositionTarget


@dataclass(frozen=True)
class OrderPlanningConfig:
    client_order_prefix: str
    order_type: OrderType
    limit_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.client_order_prefix:
            raise ValueError("client_order_prefix is required")
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")


def plan_order_to_target(
    target: PositionTarget,
    current_position: Position,
    config: OrderPlanningConfig,
) -> OrderIntent | None:
    if target.instrument_id != current_position.instrument_id:
        raise ValueError("target and current_position instruments must match")

    delta = target.quantity - current_position.quantity
    if delta == 0:
        return None

    return _build_order_intent(
        instrument_id=target.instrument_id,
        side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
        quantity=abs(delta),
        config=config,
    )


def plan_orders_to_targets(
    targets: tuple[PositionTarget, ...],
    current_positions: Mapping[str, Position],
    config: OrderPlanningConfig,
) -> tuple[OrderIntent, ...]:
    return tuple(
        intent
        for phase in plan_rebalance_order_phases(
            targets=targets,
            current_positions=current_positions,
            config=config,
        )
        for intent in phase
    )


def plan_rebalance_order_phases(
    targets: tuple[PositionTarget, ...],
    current_positions: Mapping[str, Position],
    config: OrderPlanningConfig,
) -> tuple[tuple[OrderIntent, ...], ...]:
    seen_instrument_ids: set[str] = set()
    planned_orders: list[tuple[bool, int, int, OrderIntent]] = []

    for target_index, target in enumerate(targets):
        if target.instrument_id in seen_instrument_ids:
            raise ValueError("target instrument IDs must be unique")
        seen_instrument_ids.add(target.instrument_id)

        try:
            current_position = current_positions[target.instrument_id]
        except KeyError as exc:
            raise ValueError(
                f"current position is required for {target.instrument_id}"
            ) from exc

        if _is_position_reversal(
            current_quantity=current_position.quantity,
            target_quantity=target.quantity,
        ):
            planned_orders.extend(
                _plan_position_reversal(
                    target=target,
                    current_position=current_position,
                    target_index=target_index,
                    config=config,
                )
            )
            continue

        intent = plan_order_to_target(
            target=target,
            current_position=current_position,
            config=config,
        )
        if intent is None:
            continue

        planned_orders.append(
            (
                _is_risk_reducing_delta(
                    current_quantity=current_position.quantity,
                    target_quantity=target.quantity,
                ),
                target_index,
                0,
                intent,
            )
        )

    risk_reducing_orders = _order_phase(
        planned_orders=planned_orders,
        risk_reducing=True,
    )
    risk_increasing_orders = _order_phase(
        planned_orders=planned_orders,
        risk_reducing=False,
    )
    return tuple(
        phase
        for phase in (risk_reducing_orders, risk_increasing_orders)
        if phase
    )


def _order_phase(
    planned_orders: list[tuple[bool, int, int, OrderIntent]],
    risk_reducing: bool,
) -> tuple[OrderIntent, ...]:
    return tuple(
        intent
        for _, _, _, intent in sorted(
            (
                planned_order
                for planned_order in planned_orders
                if planned_order[0] is risk_reducing
            ),
            key=lambda planned_order: (planned_order[1], planned_order[2]),
        )
    )


def _build_order_intent(
    instrument_id: str,
    side: OrderSide,
    quantity: int,
    config: OrderPlanningConfig,
    client_order_suffix: str | None = None,
) -> OrderIntent:
    client_order_id = (
        f"{config.client_order_prefix}-"
        f"{instrument_id}-"
        f"{side.value}-"
        f"{quantity}"
    )
    if client_order_suffix is not None:
        client_order_id = f"{client_order_id}-{client_order_suffix}"

    return OrderIntent(
        instrument_id=instrument_id,
        side=side,
        quantity=quantity,
        order_type=config.order_type,
        limit_price=config.limit_price,
        client_order_id=client_order_id,
    )


def _plan_position_reversal(
    target: PositionTarget,
    current_position: Position,
    target_index: int,
    config: OrderPlanningConfig,
) -> tuple[
    tuple[bool, int, int, OrderIntent],
    tuple[bool, int, int, OrderIntent],
]:
    side = OrderSide.SELL if current_position.quantity > 0 else OrderSide.BUY
    flatten_intent = _build_order_intent(
        instrument_id=target.instrument_id,
        side=side,
        quantity=abs(current_position.quantity),
        config=config,
        client_order_suffix="flatten",
    )
    open_intent = _build_order_intent(
        instrument_id=target.instrument_id,
        side=side,
        quantity=abs(target.quantity),
        config=config,
        client_order_suffix="open",
    )

    return (
        (True, target_index, 0, flatten_intent),
        (False, target_index, 1, open_intent),
    )


def _is_position_reversal(current_quantity: int, target_quantity: int) -> bool:
    return (
        (current_quantity > 0 and target_quantity < 0)
        or (current_quantity < 0 and target_quantity > 0)
    )


def _is_risk_reducing_delta(current_quantity: int, target_quantity: int) -> bool:
    if current_quantity > 0:
        return 0 <= target_quantity < current_quantity
    if current_quantity < 0:
        return current_quantity < target_quantity <= 0
    return False
