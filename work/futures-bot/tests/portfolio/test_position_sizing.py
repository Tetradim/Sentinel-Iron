from decimal import Decimal

import pytest

from futures_bot.portfolio.position_sizing import (
    PortfolioRiskCapConfig,
    PositionSizingConfig,
    PositionTarget,
    cap_position_targets_by_gross_risk,
    calculate_volatility_target_position,
)
from futures_bot.strategies.trend_following import TrendSignal


def _signal(score: str) -> TrendSignal:
    return TrendSignal(
        instrument_id="ES-202609-CME",
        score=Decimal(score),
        components=(Decimal(score),),
        lookbacks=(63,),
    )


def test_positive_signal_sizes_long_by_dollar_volatility_budget():
    target = calculate_volatility_target_position(
        signal=_signal("1"),
        account_equity=Decimal("100000"),
        dollar_volatility_per_contract=Decimal("2500"),
        config=PositionSizingConfig(target_risk_fraction=Decimal("0.10"), max_contracts=10),
    )

    assert target == PositionTarget(instrument_id="ES-202609-CME", quantity=4)


def test_negative_signal_sizes_short_by_dollar_volatility_budget():
    target = calculate_volatility_target_position(
        signal=_signal("-0.5"),
        account_equity=Decimal("100000"),
        dollar_volatility_per_contract=Decimal("2500"),
        config=PositionSizingConfig(target_risk_fraction=Decimal("0.10"), max_contracts=10),
    )

    assert target.quantity == -2


def test_zero_signal_returns_flat_target():
    target = calculate_volatility_target_position(
        signal=_signal("0"),
        account_equity=Decimal("100000"),
        dollar_volatility_per_contract=Decimal("2500"),
        config=PositionSizingConfig(target_risk_fraction=Decimal("0.10"), max_contracts=10),
    )

    assert target.quantity == 0


def test_position_size_is_capped_by_max_contracts():
    target = calculate_volatility_target_position(
        signal=_signal("1"),
        account_equity=Decimal("1000000"),
        dollar_volatility_per_contract=Decimal("500"),
        config=PositionSizingConfig(target_risk_fraction=Decimal("0.20"), max_contracts=7),
    )

    assert target.quantity == 7


def test_portfolio_risk_cap_leaves_targets_under_budget_unchanged():
    targets = cap_position_targets_by_gross_risk(
        targets=(
            PositionTarget("ES-202609-CME", 2),
            PositionTarget("NQ-202609-CME", -1),
        ),
        dollar_volatility_by_instrument={
            "ES-202609-CME": Decimal("2500"),
            "NQ-202609-CME": Decimal("5000"),
        },
        account_equity=Decimal("100000"),
        config=PortfolioRiskCapConfig(max_gross_risk_fraction=Decimal("0.10")),
    )

    assert targets == (
        PositionTarget("ES-202609-CME", 2),
        PositionTarget("NQ-202609-CME", -1),
    )


def test_portfolio_risk_cap_scales_targets_over_budget_proportionally():
    targets = cap_position_targets_by_gross_risk(
        targets=(
            PositionTarget("ES-202609-CME", 4),
            PositionTarget("NQ-202609-CME", -2),
        ),
        dollar_volatility_by_instrument={
            "ES-202609-CME": Decimal("2500"),
            "NQ-202609-CME": Decimal("5000"),
        },
        account_equity=Decimal("100000"),
        config=PortfolioRiskCapConfig(max_gross_risk_fraction=Decimal("0.10")),
    )

    assert targets == (
        PositionTarget("ES-202609-CME", 2),
        PositionTarget("NQ-202609-CME", -1),
    )


def test_portfolio_risk_cap_rejects_missing_dollar_volatility():
    with pytest.raises(ValueError, match="dollar volatility is required for ES-202609-CME"):
        cap_position_targets_by_gross_risk(
            targets=(PositionTarget("ES-202609-CME", 1),),
            dollar_volatility_by_instrument={},
            account_equity=Decimal("100000"),
            config=PortfolioRiskCapConfig(max_gross_risk_fraction=Decimal("0.10")),
        )


def test_portfolio_risk_cap_rejects_non_positive_dollar_volatility():
    with pytest.raises(ValueError, match="dollar volatility must be positive for ES-202609-CME"):
        cap_position_targets_by_gross_risk(
            targets=(PositionTarget("ES-202609-CME", 1),),
            dollar_volatility_by_instrument={"ES-202609-CME": Decimal("0")},
            account_equity=Decimal("100000"),
            config=PortfolioRiskCapConfig(max_gross_risk_fraction=Decimal("0.10")),
        )


def test_position_sizing_rejects_non_positive_dollar_volatility():
    with pytest.raises(ValueError, match="dollar_volatility_per_contract must be positive"):
        calculate_volatility_target_position(
            signal=_signal("1"),
            account_equity=Decimal("100000"),
            dollar_volatility_per_contract=Decimal("0"),
            config=PositionSizingConfig(target_risk_fraction=Decimal("0.10"), max_contracts=10),
        )


def test_position_sizing_config_rejects_invalid_risk_fraction():
    with pytest.raises(ValueError, match="target_risk_fraction must be between 0 and 1"):
        PositionSizingConfig(target_risk_fraction=Decimal("1.5"), max_contracts=10)
