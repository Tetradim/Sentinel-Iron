from __future__ import annotations

from typing import Protocol

from futures_bot.domain.orders import BrokerOrder
from futures_bot.domain.portfolio import AccountSnapshot, Position


class BrokerPort(Protocol):
    def connect(self) -> None:
        """Open the broker connection."""

    def get_account(self) -> AccountSnapshot:
        """Return a fresh broker account snapshot."""

    def get_positions(self) -> tuple[Position, ...]:
        """Return current broker positions."""

    def submit_order(self, order: BrokerOrder) -> str:
        """Submit an approved broker order and return the broker order ID."""

    def cancel_order(self, broker_order_id: str) -> None:
        """Cancel an open broker order."""
