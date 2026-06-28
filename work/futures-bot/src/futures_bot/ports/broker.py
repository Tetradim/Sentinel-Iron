from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from futures_bot.domain.orders import BrokerOrder
from futures_bot.domain.portfolio import AccountSnapshot, Position


class BrokerSubmissionError(RuntimeError):
    def __init__(self, reason: str, broker_error_code: str | None = None) -> None:
        if not reason:
            raise ValueError("reason is required")
        super().__init__(reason)
        self.reason = reason
        self.broker_error_code = broker_error_code


class BrokerCancellationError(RuntimeError):
    def __init__(self, reason: str, broker_error_code: str | None = None) -> None:
        if not reason:
            raise ValueError("reason is required")
        super().__init__(reason)
        self.reason = reason
        self.broker_error_code = broker_error_code


class BrokerOrderUpdateType(StrEnum):
    WORKING = "working"
    FILL = "fill"
    CANCELED = "canceled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class BrokerOrderUpdate:
    account_id: str
    client_order_id: str
    broker_order_id: str | None
    instrument_id: str
    update_type: BrokerOrderUpdateType
    timestamp: datetime
    fill_quantity: int = 0
    reject_reason: str | None = None
    broker_error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.account_id:
            raise ValueError("account_id is required")
        if not self.client_order_id:
            raise ValueError("client_order_id is required")
        if self.broker_order_id == "":
            raise ValueError("broker_order_id cannot be empty")
        if not self.instrument_id:
            raise ValueError("instrument_id is required")
        if self.fill_quantity < 0:
            raise ValueError("fill_quantity cannot be negative")
        if self.update_type == BrokerOrderUpdateType.FILL and self.fill_quantity <= 0:
            raise ValueError("fill_quantity must be positive for fill updates")
        if self.update_type != BrokerOrderUpdateType.FILL and self.fill_quantity != 0:
            raise ValueError("fill_quantity is only valid for fill updates")
        if self.update_type == BrokerOrderUpdateType.REJECTED and not self.reject_reason:
            raise ValueError("reject_reason is required for rejected updates")


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
