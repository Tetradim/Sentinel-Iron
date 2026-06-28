from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from futures_bot.domain.enums import OrderSide, OrderType


@dataclass(frozen=True)
class OrderIntent:
    instrument_id: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    client_order_id: str
    limit_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id is required")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if not self.client_order_id:
            raise ValueError("client_order_id is required")
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")


@dataclass(frozen=True)
class BrokerOrder:
    instrument_id: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    client_order_id: str
    limit_price: Decimal | None = None

    @classmethod
    def from_intent(cls, intent: OrderIntent) -> BrokerOrder:
        return cls(
            instrument_id=intent.instrument_id,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            client_order_id=intent.client_order_id,
            limit_price=intent.limit_price,
        )
