from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from futures_bot.domain.enums import SettlementType


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    exchange: str
    contract_month: str
    multiplier: Decimal
    tick_size: Decimal
    currency: str
    settlement_type: SettlementType

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if not self.exchange:
            raise ValueError("exchange is required")
        if not self.contract_month:
            raise ValueError("contract_month is required")
        if self.multiplier <= 0:
            raise ValueError("multiplier must be positive")
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if not self.currency:
            raise ValueError("currency is required")

    @property
    def tick_value(self) -> Decimal:
        return self.multiplier * self.tick_size

    def round_to_tick(self, price: Decimal) -> Decimal:
        tick_count = (price / self.tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return tick_count * self.tick_size


@dataclass(frozen=True)
class TradingCalendar:
    first_notice_date: date | None
    last_trade_date: date
    last_safe_trade_date: date

    def __post_init__(self) -> None:
        if self.last_safe_trade_date > self.last_trade_date:
            raise ValueError("last_safe_trade_date cannot be after last_trade_date")

    def can_trade_on(self, trading_day: date) -> bool:
        return trading_day <= self.last_safe_trade_date


@dataclass(frozen=True)
class FuturesInstrument:
    instrument_id: str
    spec: ContractSpec
    calendar: TradingCalendar

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id is required")

    @property
    def delivery_sensitive(self) -> bool:
        return self.spec.settlement_type == SettlementType.PHYSICAL

    def can_trade_on(self, trading_day: date) -> bool:
        return self.calendar.can_trade_on(trading_day)
