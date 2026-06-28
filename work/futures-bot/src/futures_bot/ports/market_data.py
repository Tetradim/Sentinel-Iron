from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from futures_bot.domain.portfolio import MarketSnapshot


@dataclass(frozen=True)
class HistoricalBar:
    instrument_id: str
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id is required")
        if self.open <= 0:
            raise ValueError("open must be positive")
        if self.high <= 0:
            raise ValueError("high must be positive")
        if self.low <= 0:
            raise ValueError("low must be positive")
        if self.close <= 0:
            raise ValueError("close must be positive")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high must be greater than or equal to all prices")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low must be less than or equal to all prices")
        if self.volume is not None and self.volume < 0:
            raise ValueError("volume cannot be negative")


class MarketDataError(RuntimeError):
    def __init__(self, reason: str, provider_error_code: str | None = None) -> None:
        if not reason:
            raise ValueError("reason is required")
        super().__init__(reason)
        self.reason = reason
        self.provider_error_code = provider_error_code


class MarketDataPort(Protocol):
    def get_snapshot(self, instrument_id: str) -> MarketSnapshot:
        """Return the latest market snapshot for an instrument."""


class HistoricalDataPort(Protocol):
    def get_daily_bars(
        self,
        instrument_id: str,
        start_day: date,
        end_day: date,
    ) -> tuple[HistoricalBar, ...]:
        """Return normalized daily bars for an instrument and inclusive date range."""
