from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from futures_bot.strategies.trend_following import PricePoint


@dataclass(frozen=True)
class ContractPriceSeries:
    instrument_id: str
    prices: tuple[PricePoint, ...]

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id is required")
        if not self.prices:
            raise ValueError("prices are required")

        ordered_prices = tuple(sorted(self.prices, key=lambda point: point.day))
        days = [point.day for point in ordered_prices]
        if len(set(days)) != len(days):
            raise ValueError("price days must be unique")
        object.__setattr__(self, "prices", ordered_prices)


def build_back_adjusted_continuous_series(
    segments: tuple[ContractPriceSeries, ...],
) -> tuple[PricePoint, ...]:
    if not segments:
        raise ValueError("contract price segments are required")

    first_days = tuple(segment.prices[0].day for segment in segments)
    for index in range(1, len(first_days)):
        if first_days[index] <= first_days[index - 1]:
            raise ValueError("contract segments must be chronological")

    adjustments = [Decimal("0") for _ in segments]
    for index in range(len(segments) - 2, -1, -1):
        current_segment = segments[index]
        next_segment = segments[index + 1]
        roll_day = next_segment.prices[0].day
        current_roll_price = _price_on(current_segment, roll_day)
        if current_roll_price is None:
            raise ValueError(
                "roll overlap price is required for "
                f"{current_segment.instrument_id} on {roll_day.isoformat()}"
            )
        next_roll_price = next_segment.prices[0].close + adjustments[index + 1]
        adjustments[index] = next_roll_price - current_roll_price

    adjusted_prices: list[PricePoint] = []
    for index, segment in enumerate(segments):
        next_roll_day = first_days[index + 1] if index + 1 < len(first_days) else None
        for point in segment.prices:
            if next_roll_day is not None and point.day >= next_roll_day:
                continue
            adjusted_prices.append(
                PricePoint(
                    day=point.day,
                    close=point.close + adjustments[index],
                )
            )

    return tuple(adjusted_prices)


def _price_on(segment: ContractPriceSeries, day: date) -> Decimal | None:
    for point in segment.prices:
        if point.day == day:
            return point.close
    return None
