from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Protocol

from futures_bot.domain.enums import OrderSide
from futures_bot.domain.portfolio import Position
from futures_bot.ports.audit import AuditLogPort
from futures_bot.ports.broker import BrokerOrderUpdate, BrokerOrderUpdateType


class PositionStorePort(Protocol):
    def load(self) -> Mapping[str, Position]:
        """Load current internal positions by instrument ID."""

    def save(self, positions: Mapping[str, Position]) -> None:
        """Persist current internal positions by instrument ID."""


class ProcessedFillStorePort(Protocol):
    def contains(self, broker_execution_id: str) -> bool:
        """Return whether this broker execution ID was already applied."""

    def append(self, broker_execution_id: str) -> None:
        """Record one applied broker execution ID."""


class PositionLedgerService:
    def __init__(
        self,
        store: PositionStorePort,
        audit_log: AuditLogPort,
        processed_fill_store: ProcessedFillStorePort | None = None,
    ) -> None:
        self._store = store
        self._audit_log = audit_log
        self._processed_fill_store = processed_fill_store

    def apply_fill(self, update: BrokerOrderUpdate, order_side: OrderSide) -> Position:
        if update.update_type != BrokerOrderUpdateType.FILL:
            raise ValueError("position ledger only applies fill updates")
        if update.fill_price is None:
            raise ValueError("fill_price is required")
        if self._processed_fill_store is not None and update.broker_execution_id is None:
            raise ValueError("broker_execution_id is required when processed fill store is configured")

        positions = dict(self._store.load())
        previous_position = positions.get(
            update.instrument_id,
            Position(update.instrument_id, 0, Decimal("0")),
        )
        if (
            self._processed_fill_store is not None
            and update.broker_execution_id is not None
            and self._processed_fill_store.contains(update.broker_execution_id)
        ):
            self._audit_log.append(
                {
                    "type": "position_ledger_fill_duplicate_ignored",
                    "timestamp": update.timestamp.isoformat(),
                    "account_id": update.account_id,
                    "client_order_id": update.client_order_id,
                    "broker_order_id": update.broker_order_id,
                    "broker_execution_id": update.broker_execution_id,
                    "instrument_id": update.instrument_id,
                }
            )
            return previous_position

        updated_position = self._apply_fill_to_position(
            previous=previous_position,
            side=order_side,
            fill_quantity=update.fill_quantity,
            fill_price=update.fill_price,
        )
        positions[update.instrument_id] = updated_position
        self._store.save(positions)
        if self._processed_fill_store is not None and update.broker_execution_id is not None:
            self._processed_fill_store.append(update.broker_execution_id)

        self._audit_log.append(
            {
                "type": "position_ledger_fill_applied",
                "timestamp": update.timestamp.isoformat(),
                "account_id": update.account_id,
                "client_order_id": update.client_order_id,
                "broker_order_id": update.broker_order_id,
                "instrument_id": update.instrument_id,
                "order_side": order_side.value,
                "fill_quantity": update.fill_quantity,
                "fill_price": str(update.fill_price),
                "previous_quantity": previous_position.quantity,
                "previous_average_price": str(previous_position.average_price),
                "updated_quantity": updated_position.quantity,
                "updated_average_price": str(updated_position.average_price),
            }
        )
        return updated_position

    def _apply_fill_to_position(
        self,
        previous: Position,
        side: OrderSide,
        fill_quantity: int,
        fill_price: Decimal,
    ) -> Position:
        signed_fill_quantity = fill_quantity if side == OrderSide.BUY else -fill_quantity
        updated_quantity = previous.quantity + signed_fill_quantity

        if updated_quantity == 0:
            updated_average_price = Decimal("0")
        elif previous.quantity == 0 or self._same_side(previous.quantity, signed_fill_quantity):
            updated_average_price = self._weighted_average_price(
                previous=previous,
                fill_quantity=fill_quantity,
                fill_price=fill_price,
                updated_quantity=updated_quantity,
            )
        elif self._same_side(previous.quantity, updated_quantity):
            updated_average_price = previous.average_price
        else:
            updated_average_price = fill_price

        return Position(
            instrument_id=previous.instrument_id,
            quantity=updated_quantity,
            average_price=updated_average_price,
        )

    def _weighted_average_price(
        self,
        previous: Position,
        fill_quantity: int,
        fill_price: Decimal,
        updated_quantity: int,
    ) -> Decimal:
        previous_notional = abs(previous.quantity) * previous.average_price
        fill_notional = fill_quantity * fill_price
        return (previous_notional + fill_notional) / abs(updated_quantity)

    def _same_side(self, left_quantity: int, right_quantity: int) -> bool:
        return (left_quantity > 0 and right_quantity > 0) or (
            left_quantity < 0 and right_quantity < 0
        )
