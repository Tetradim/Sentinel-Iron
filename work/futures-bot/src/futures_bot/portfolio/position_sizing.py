from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Mapping

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
class PortfolioRiskCapConfig:
    max_gross_risk_fraction: Decimal

    def __post_init__(self) -> None:
        if not Decimal("0") < self.max_gross_risk_fraction <= Decimal("1"):
            raise ValueError("max_gross_risk_fraction must be between 0 and 1")


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


def cap_position_targets_by_gross_risk(
    targets: tuple[PositionTarget, ...],
    dollar_volatility_by_instrument: Mapping[str, Decimal],
    account_equity: Decimal,
    config: PortfolioRiskCapConfig,
) -> tuple[PositionTarget, ...]:
    if account_equity <= 0:
        raise ValueError("account_equity must be positive")

    gross_risk = sum(
        _target_gross_risk(target, dollar_volatility_by_instrument)
        for target in targets
    )
    max_gross_risk = account_equity * config.max_gross_risk_fraction
    if gross_risk <= max_gross_risk:
        return targets

    scale = max_gross_risk / gross_risk
    capped_targets: list[PositionTarget] = []
    for target in targets:
        unsigned_quantity = Decimal(abs(target.quantity))
        capped_quantity = int((unsigned_quantity * scale).to_integral_value(rounding=ROUND_FLOOR))
        if target.quantity < 0:
            capped_quantity = -capped_quantity
        capped_targets.append(
            PositionTarget(
                instrument_id=target.instrument_id,
                quantity=capped_quantity,
            )
        )
    return tuple(capped_targets)


def _target_gross_risk(
    target: PositionTarget,
    dollar_volatility_by_instrument: Mapping[str, Decimal],
) -> Decimal:
    try:
        dollar_volatility = dollar_volatility_by_instrument[target.instrument_id]
    except KeyError as exc:
        raise ValueError(f"dollar volatility is required for {target.instrument_id}") from exc
    if dollar_volatility <= 0:
        raise ValueError(f"dollar volatility must be positive for {target.instrument_id}")
    return Decimal(abs(target.quantity)) * dollar_volatility
