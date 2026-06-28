from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from futures_bot.strategies.trend_following import TrendSignal


@dataclass(frozen=True)
class PositionSizingConfig:
    target_risk_fraction: Decimal
    max_contracts: int

    def __post_init__(self) -> None:
        if not Decimal("0") < self.target_risk_fraction <= Decimal("1"):
            raise ValueError("target_risk_fraction must be between 0 and 1")
        if self.max_contracts <= 0:
            raise ValueError("max_contracts must be positive")


@dataclass(frozen=True)
class PositionTarget:
    instrument_id: str
    quantity: int


def calculate_volatility_target_position(
    signal: TrendSignal,
    account_equity: Decimal,
    dollar_volatility_per_contract: Decimal,
    config: PositionSizingConfig,
) -> PositionTarget:
    if account_equity <= 0:
        raise ValueError("account_equity must be positive")
    if dollar_volatility_per_contract <= 0:
        raise ValueError("dollar_volatility_per_contract must be positive")

    signal_magnitude = abs(signal.score)
    if signal_magnitude == 0:
        return PositionTarget(instrument_id=signal.instrument_id, quantity=0)

    risk_budget = account_equity * config.target_risk_fraction * signal_magnitude
    raw_contracts = (risk_budget / dollar_volatility_per_contract).to_integral_value(
        rounding=ROUND_FLOOR
    )
    unsigned_quantity = min(int(raw_contracts), config.max_contracts)

    if signal.score < 0:
        quantity = -unsigned_quantity
    else:
        quantity = unsigned_quantity

    return PositionTarget(instrument_id=signal.instrument_id, quantity=quantity)
