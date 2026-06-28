from __future__ import annotations

from typing import Protocol

from futures_bot.domain.portfolio import MarketSnapshot


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
