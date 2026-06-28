from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from futures_bot.domain.enums import OrderSide


@dataclass(frozen=True)
class Position:
    instrument_id: str
    quantity: int
    average_price: Decimal

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id is required")
        if self.average_price < 0:
            raise ValueError("average_price cannot be negative")

    def quantity_after(self, side: OrderSide, order_quantity: int) -> int:
        if order_quantity <= 0:
            raise ValueError("order_quantity must be positive")
        signed_order_quantity = order_quantity if side == OrderSide.BUY else -order_quantity
        return self.quantity + signed_order_quantity


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    equity: Decimal
    initial_margin: Decimal
    maintenance_margin: Decimal
    buying_power: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.account_id:
            raise ValueError("account_id is required")
        if self.equity <= 0:
            raise ValueError("equity must be positive")
        if self.initial_margin < 0:
            raise ValueError("initial_margin cannot be negative")
        if self.maintenance_margin < 0:
            raise ValueError("maintenance_margin cannot be negative")
        if self.buying_power < 0:
            raise ValueError("buying_power cannot be negative")

    @property
    def margin_usage(self) -> Decimal:
        return self.initial_margin / self.equity


@dataclass(frozen=True)
class MarketSnapshot:
    instrument_id: str
    bid: Decimal | None
    ask: Decimal | None
    last: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id is required")
        if self.bid is not None and self.bid <= 0:
            raise ValueError("bid must be positive")
        if self.ask is not None and self.ask <= 0:
            raise ValueError("ask must be positive")
        if self.last <= 0:
            raise ValueError("last must be positive")
