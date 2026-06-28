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

    side = OrderSide.BUY if delta > 0 else OrderSide.SELL
    quantity = abs(delta)
    client_order_id = (
        f"{config.client_order_prefix}-"
        f"{target.instrument_id}-"
        f"{side.value}-"
        f"{quantity}"
    )

    return OrderIntent(
        instrument_id=target.instrument_id,
        side=side,
        quantity=quantity,
        order_type=config.order_type,
        limit_price=config.limit_price,
        client_order_id=client_order_id,
    )


def plan_orders_to_targets(
    targets: tuple[PositionTarget, ...],
    current_positions: Mapping[str, Position],
    config: OrderPlanningConfig,
) -> tuple[OrderIntent, ...]:
    seen_instrument_ids: set[str] = set()
    planned_orders: list[tuple[bool, int, OrderIntent]] = []

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
                intent,
            )
        )

    return tuple(
        intent
        for _, _, intent in sorted(
            planned_orders,
            key=lambda planned_order: (not planned_order[0], planned_order[1]),
        )
    )


def _is_risk_reducing_delta(current_quantity: int, target_quantity: int) -> bool:
    if current_quantity > 0:
        return 0 <= target_quantity < current_quantity
    if current_quantity < 0:
        return current_quantity < target_quantity <= 0
    return False
