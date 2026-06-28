from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder
from futures_bot.domain.portfolio import Position
from futures_bot.ports.audit import AuditLogPort
from futures_bot.ports.broker import BrokerPort, BrokerSubmissionError


@dataclass(frozen=True)
class FlattenSubmittedOrder:
    instrument_id: str
    original_quantity: int
    side: OrderSide
    quantity: int
    client_order_id: str
    broker_order_id: str


@dataclass(frozen=True)
class FlattenFailedOrder:
    instrument_id: str
    original_quantity: int
    side: OrderSide
    quantity: int
    client_order_id: str
    reason: str
    broker_error_code: str | None


@dataclass(frozen=True)
class PositionFlatteningResult:
    account_id: str
    submitted_orders: tuple[FlattenSubmittedOrder, ...]
    failed_orders: tuple[FlattenFailedOrder, ...]
    skipped_count: int

    @property
    def submitted_count(self) -> int:
        return len(self.submitted_orders)

    @property
    def failed_count(self) -> int:
        return len(self.failed_orders)


class PositionFlatteningService:
    def __init__(self, broker: BrokerPort, audit_log: AuditLogPort) -> None:
        self._broker = broker
        self._audit_log = audit_log

    def flatten(
        self,
        timestamp: datetime,
        client_order_id_prefix: str = "flatten-live",
    ) -> PositionFlatteningResult:
        if timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        prefix = client_order_id_prefix.strip()
        if not prefix:
            raise ValueError("client_order_id_prefix is required")

        self._broker.connect()
        account = self._broker.get_account()
        positions = self._broker.get_positions()
        actionable_positions = tuple(position for position in positions if position.quantity != 0)
        skipped_count = len(positions) - len(actionable_positions)

        self._audit_log.append(
            {
                "type": "position_flatten_started",
                "timestamp": timestamp.isoformat(),
                "account_id": account.account_id,
                "position_count": len(positions),
                "actionable_position_count": len(actionable_positions),
                "skipped_count": skipped_count,
            }
        )

        submitted_orders: list[FlattenSubmittedOrder] = []
        failed_orders: list[FlattenFailedOrder] = []
        for sequence, position in enumerate(actionable_positions, start=1):
            order = self._flatten_order(
                position=position,
                client_order_id=self._client_order_id(prefix, timestamp, sequence),
            )
            try:
                broker_order_id = self._broker.submit_order(order)
            except BrokerSubmissionError as exc:
                failure = FlattenFailedOrder(
                    instrument_id=position.instrument_id,
                    original_quantity=position.quantity,
                    side=order.side,
                    quantity=order.quantity,
                    client_order_id=order.client_order_id,
                    reason=exc.reason,
                    broker_error_code=exc.broker_error_code,
                )
                failed_orders.append(failure)
                self._audit_log.append(
                    {
                        "type": "position_flatten_order_failed",
                        "timestamp": timestamp.isoformat(),
                        "account_id": account.account_id,
                        "client_order_id": failure.client_order_id,
                        "instrument_id": failure.instrument_id,
                        "side": failure.side.value,
                        "quantity": failure.quantity,
                        "reason": failure.reason,
                        "broker_error_code": failure.broker_error_code,
                    }
                )
                continue

            submitted = FlattenSubmittedOrder(
                instrument_id=position.instrument_id,
                original_quantity=position.quantity,
                side=order.side,
                quantity=order.quantity,
                client_order_id=order.client_order_id,
                broker_order_id=broker_order_id,
            )
            submitted_orders.append(submitted)
            self._audit_log.append(
                {
                    "type": "position_flatten_order_submitted",
                    "timestamp": timestamp.isoformat(),
                    "account_id": account.account_id,
                    "client_order_id": submitted.client_order_id,
                    "broker_order_id": submitted.broker_order_id,
                    "instrument_id": submitted.instrument_id,
                    "side": submitted.side.value,
                    "quantity": submitted.quantity,
                    "original_quantity": submitted.original_quantity,
                }
            )

        result = PositionFlatteningResult(
            account_id=account.account_id,
            submitted_orders=tuple(submitted_orders),
            failed_orders=tuple(failed_orders),
            skipped_count=skipped_count,
        )
        self._audit_log.append(
            {
                "type": "position_flatten_completed",
                "timestamp": timestamp.isoformat(),
                "account_id": result.account_id,
                "submitted_count": result.submitted_count,
                "failed_count": result.failed_count,
                "skipped_count": result.skipped_count,
            }
        )
        return result

    def _flatten_order(self, position: Position, client_order_id: str) -> BrokerOrder:
        side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
        return BrokerOrder(
            instrument_id=position.instrument_id,
            side=side,
            quantity=abs(position.quantity),
            order_type=OrderType.MARKET,
            client_order_id=client_order_id,
        )

    def _client_order_id(self, prefix: str, timestamp: datetime, sequence: int) -> str:
        utc_timestamp = timestamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{prefix}-{utc_timestamp}-{sequence}"
