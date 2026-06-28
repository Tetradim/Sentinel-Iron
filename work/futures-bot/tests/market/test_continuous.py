from datetime import date
from decimal import Decimal

import pytest

from futures_bot.strategies.trend_following import PricePoint


def _continuous_module():
    try:
        from futures_bot.market.continuous import (
            ContractPriceSeries,
            build_back_adjusted_continuous_series,
        )
    except ModuleNotFoundError:
        pytest.fail("expected continuous futures module to exist")

    return ContractPriceSeries, build_back_adjusted_continuous_series


def test_builds_back_adjusted_continuous_series_across_single_roll():
    series_class, build = _continuous_module()

    continuous = build(
        (
            series_class(
                instrument_id="ES-202609-CME",
                prices=_prices(("2026-09-01", "100"), ("2026-09-02", "102"), ("2026-09-03", "104")),
            ),
            series_class(
                instrument_id="ES-202612-CME",
                prices=_prices(("2026-09-03", "110"), ("2026-09-04", "111")),
            ),
        )
    )

    assert continuous == _prices(
        ("2026-09-01", "106"),
        ("2026-09-02", "108"),
        ("2026-09-03", "110"),
        ("2026-09-04", "111"),
    )


def test_back_adjustment_is_cumulative_across_multiple_rolls():
    series_class, build = _continuous_module()

    continuous = build(
        (
            series_class(
                instrument_id="CL-202608-NYMEX",
                prices=_prices(("2026-08-24", "100"), ("2026-08-25", "102"), ("2026-08-26", "104")),
            ),
            series_class(
                instrument_id="CL-202609-NYMEX",
                prices=_prices(("2026-08-26", "110"), ("2026-08-27", "112"), ("2026-08-28", "114")),
            ),
            series_class(
                instrument_id="CL-202610-NYMEX",
                prices=_prices(("2026-08-28", "120"), ("2026-08-31", "121")),
            ),
        )
    )

    assert continuous == _prices(
        ("2026-08-24", "112"),
        ("2026-08-25", "114"),
        ("2026-08-26", "116"),
        ("2026-08-27", "118"),
        ("2026-08-28", "120"),
        ("2026-08-31", "121"),
    )


def test_back_adjusted_series_rejects_missing_roll_overlap_price():
    series_class, build = _continuous_module()

    with pytest.raises(
        ValueError,
        match="roll overlap price is required for ES-202609-CME on 2026-09-03",
    ):
        build(
            (
                series_class(
                    instrument_id="ES-202609-CME",
                    prices=_prices(("2026-09-01", "100"), ("2026-09-02", "102")),
                ),
                series_class(
                    instrument_id="ES-202612-CME",
                    prices=_prices(("2026-09-03", "110"), ("2026-09-04", "111")),
                ),
            )
        )


def test_back_adjusted_series_rejects_non_chronological_segments():
    series_class, build = _continuous_module()

    with pytest.raises(ValueError, match="contract segments must be chronological"):
        build(
            (
                series_class(
                    instrument_id="ES-202612-CME",
                    prices=_prices(("2026-09-03", "110"), ("2026-09-04", "111")),
                ),
                series_class(
                    instrument_id="ES-202609-CME",
                    prices=_prices(("2026-09-01", "100"), ("2026-09-03", "104")),
                ),
            )
        )


def test_contract_price_series_rejects_duplicate_days():
    series_class, _ = _continuous_module()

    with pytest.raises(ValueError, match="price days must be unique"):
        series_class(
            instrument_id="ES-202609-CME",
            prices=_prices(("2026-09-01", "100"), ("2026-09-01", "101")),
        )


def _prices(*values: tuple[str, str]) -> tuple[PricePoint, ...]:
    return tuple(
        PricePoint(day=date.fromisoformat(day), close=Decimal(close))
        for day, close in values
    )
