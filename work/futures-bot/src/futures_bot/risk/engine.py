from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from futures_bot.domain.enums import OrderType, RiskReason
from futures_bot.domain.instruments import FuturesInstrument
from futures_bot.domain.orders import OrderIntent
from futures_bot.domain.portfolio import AccountSnapshot, MarketSnapshot, Position


@dataclass(frozen=True)
class RiskLimits:
    max_order_quantity: int
    max_position_abs: int
    max_margin_usage: Decimal
    account_stale_after: timedelta
    market_data_stale_after: timedelta
    price_collar_percent: Decimal

    def __post_init__(self) -> None:
        if self.max_order_quantity <= 0:
            raise ValueError("max_order_quantity must be positive")
        if self.max_position_abs <= 0:
            raise ValueError("max_position_abs must be positive")
        if not Decimal("0") < self.max_margin_usage <= Decimal("1"):
            raise ValueError("max_margin_usage must be between 0 and 1")
        if self.account_stale_after <= timedelta(0):
            raise ValueError("account_stale_after must be positive")
        if self.market_data_stale_after <= timedelta(0):
            raise ValueError("market_data_stale_after must be positive")
        if self.price_collar_percent <= 0:
            raise ValueError("price_collar_percent must be positive")


@dataclass(frozen=True)
class RiskContext:
    now: datetime
    instrument: FuturesInstrument
    account: AccountSnapshot
    market: MarketSnapshot
    current_position: Position
    used_client_order_ids: frozenset[str]
    estimated_order_initial_margin: Decimal
    kill_switch_active: bool
    positions_reconciled: bool

    def __post_init__(self) -> None:
        if self.estimated_order_initial_margin < 0:
            raise ValueError("estimated_order_initial_margin cannot be negative")


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: RiskReason | None
    detail: str

    @classmethod
    def approve(cls) -> RiskDecision:
        return cls(approved=True, reason=None, detail="approved")

    @classmethod
    def reject(cls, reason: RiskReason, detail: str) -> RiskDecision:
        return cls(approved=False, reason=reason, detail=detail)


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self._limits = limits

    def evaluate(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        if context.kill_switch_active:
            return RiskDecision.reject(RiskReason.KILL_SWITCH_ACTIVE, "kill switch is active")

        if not context.positions_reconciled:
            return RiskDecision.reject(
                RiskReason.UNRECONCILED_POSITIONS,
                "internal positions do not reconcile with broker positions",
            )

        if context.now - context.account.timestamp > self._limits.account_stale_after:
            return RiskDecision.reject(RiskReason.STALE_ACCOUNT, "account snapshot is stale")

        if context.now - context.market.timestamp > self._limits.market_data_stale_after:
            return RiskDecision.reject(RiskReason.STALE_MARKET_DATA, "market data is stale")

        if intent.quantity > self._limits.max_order_quantity:
            return RiskDecision.reject(RiskReason.MAX_ORDER_QUANTITY, "order quantity exceeds limit")

        resulting_quantity = context.current_position.quantity_after(intent.side, intent.quantity)
        if abs(resulting_quantity) > self._limits.max_position_abs:
            return RiskDecision.reject(RiskReason.MAX_POSITION, "resulting position exceeds limit")

        margin_usage = (
            context.account.initial_margin + context.estimated_order_initial_margin
        ) / context.account.equity
        if margin_usage > self._limits.max_margin_usage:
            return RiskDecision.reject(RiskReason.MAX_MARGIN_USAGE, "estimated margin usage exceeds limit")

        if not context.instrument.can_trade_on(context.now.date()):
            return RiskDecision.reject(RiskReason.CONTRACT_NOT_TRADABLE, "contract is past last safe trade date")

        if intent.client_order_id in context.used_client_order_ids:
            return RiskDecision.reject(RiskReason.DUPLICATE_CLIENT_ORDER_ID, "client order ID was already used")

        if intent.order_type == OrderType.LIMIT and intent.limit_price is not None:
            distance = abs(intent.limit_price - context.market.last) / context.market.last
            if distance > self._limits.price_collar_percent:
                return RiskDecision.reject(RiskReason.PRICE_COLLAR, "limit price is outside price collar")

        return RiskDecision.approve()
