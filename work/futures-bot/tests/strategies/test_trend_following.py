from datetime import date
from decimal import Decimal

from futures_bot.strategies.trend_following import (
    PricePoint,
    TrendSignal,
    TrendSignalConfig,
    VolatilityAdjustedTrendSignalConfig,
    calculate_trend_signal,
    calculate_volatility_adjusted_trend_signal,
)


def _prices(values: list[str]) -> tuple[PricePoint, ...]:
    return tuple(
        PricePoint(day=date(2026, 1, index + 1), close=Decimal(value))
        for index, value in enumerate(values)
    )


def test_trend_signal_is_positive_when_price_is_above_all_lookbacks():
    signal = calculate_trend_signal(
        instrument_id="ES-202609-CME",
        prices=_prices(["100", "102", "104", "106", "108"]),
        config=TrendSignalConfig(lookbacks=(2, 4)),
    )

    assert signal == TrendSignal(
        instrument_id="ES-202609-CME",
        score=Decimal("1"),
        components=(Decimal("1"), Decimal("1")),
        lookbacks=(2, 4),
    )


def test_trend_signal_is_negative_when_price_is_below_all_lookbacks():
    signal = calculate_trend_signal(
        instrument_id="ES-202609-CME",
        prices=_prices(["108", "106", "104", "102", "100"]),
        config=TrendSignalConfig(lookbacks=(2, 4)),
    )

    assert signal.score == Decimal("-1")
    assert signal.components == (Decimal("-1"), Decimal("-1"))


def test_trend_signal_is_neutral_for_flat_price_history():
    signal = calculate_trend_signal(
        instrument_id="ES-202609-CME",
        prices=_prices(["100", "100", "100", "100", "100"]),
        config=TrendSignalConfig(lookbacks=(2, 4)),
    )

    assert signal.score == Decimal("0")
    assert signal.components == (Decimal("0"), Decimal("0"))


def test_trend_signal_ignores_lookbacks_without_enough_history():
    signal = calculate_trend_signal(
        instrument_id="ES-202609-CME",
        prices=_prices(["100", "101", "102"]),
        config=TrendSignalConfig(lookbacks=(2, 10)),
    )

    assert signal.score == Decimal("1")
    assert signal.components == (Decimal("1"),)
    assert signal.lookbacks == (2,)


def test_volatility_adjusted_trend_signal_scales_return_by_volatility():
    signal = calculate_volatility_adjusted_trend_signal(
        instrument_id="ES-202609-CME",
        prices=_prices(["100", "100", "101"]),
        config=VolatilityAdjustedTrendSignalConfig(
            lookbacks=(2,),
            annualized_volatility=Decimal("0.02"),
            trading_days_per_year=Decimal("2"),
        ),
    )

    assert signal == TrendSignal(
        instrument_id="ES-202609-CME",
        score=Decimal("0.5"),
        components=(Decimal("0.5"),),
        lookbacks=(2,),
    )


def test_volatility_adjusted_trend_signal_preserves_negative_direction():
    signal = calculate_volatility_adjusted_trend_signal(
        instrument_id="ES-202609-CME",
        prices=_prices(["100", "100", "99"]),
        config=VolatilityAdjustedTrendSignalConfig(
            lookbacks=(2,),
            annualized_volatility=Decimal("0.02"),
            trading_days_per_year=Decimal("2"),
        ),
    )

    assert signal.score == Decimal("-0.5")
    assert signal.components == (Decimal("-0.5"),)


def test_volatility_adjusted_trend_signal_clips_large_components():
    signal = calculate_volatility_adjusted_trend_signal(
        instrument_id="ES-202609-CME",
        prices=_prices(["100", "100", "110"]),
        config=VolatilityAdjustedTrendSignalConfig(
            lookbacks=(2,),
            annualized_volatility=Decimal("0.02"),
            trading_days_per_year=Decimal("2"),
        ),
    )

    assert signal.score == Decimal("1")
    assert signal.components == (Decimal("1"),)


def test_trend_signal_is_neutral_when_no_lookback_has_enough_history():
    signal = calculate_trend_signal(
        instrument_id="ES-202609-CME",
        prices=_prices(["100", "101"]),
        config=TrendSignalConfig(lookbacks=(5, 10)),
    )

    assert signal.score == Decimal("0")
    assert signal.components == ()
    assert signal.lookbacks == ()


def test_volatility_adjusted_config_requires_positive_volatility():
    try:
        VolatilityAdjustedTrendSignalConfig(
            lookbacks=(2,),
            annualized_volatility=Decimal("0"),
        )
    except ValueError as exc:
        assert str(exc) == "annualized_volatility must be positive"
    else:
        raise AssertionError("expected invalid volatility to be rejected")


def test_trend_config_requires_positive_lookbacks():
    try:
        TrendSignalConfig(lookbacks=(0,))
    except ValueError as exc:
        assert str(exc) == "lookbacks must be positive"
    else:
        raise AssertionError("expected invalid lookback to be rejected")
