from datetime import datetime, timezone
from decimal import Decimal

import pytest

from futures_bot.domain.enums import OrderSide
from futures_bot.domain.portfolio import Position
from futures_bot.ports.audit import InMemoryAuditLog
from futures_bot.ports.broker import BrokerOrderUpdate, BrokerOrderUpdateType


NOW = datetime(2026, 6, 28, 16, 45, tzinfo=timezone.utc)


class InMemoryPositionStore:
    def __init__(self, positions: dict[str, Position] | None = None) -> None:
        self.positions = positions or {}
        self.saved_positions: list[dict[str, Position]] = []

    def load(self):
        return dict(self.positions)

    def save(self, positions):
        self.positions = dict(positions)
        self.saved_positions.append(dict(positions))


def _fill_update(
    fill_quantity: int = 1,
    fill_price: Decimal | None = Decimal("5010.00"),
    instrument_id: str = "ES-202609-CME",
) -> BrokerOrderUpdate:
    return BrokerOrderUpdate(
        account_id="acct-1",
        client_order_id="order-1",
        broker_order_id="broker-1",
        instrument_id=instrument_id,
        update_type=BrokerOrderUpdateType.FILL,
        timestamp=NOW,
        fill_quantity=fill_quantity,
        fill_price=fill_price,
    )


def test_position_ledger_applies_buy_fill_to_existing_long_position_and_audits():
    from futures_bot.application.position_ledger import PositionLedgerService

    store = InMemoryPositionStore(
        {"ES-202609-CME": Position("ES-202609-CME", 1, Decimal("5000.00"))}
    )
    audit_log = InMemoryAuditLog()
    service = PositionLedgerService(store=store, audit_log=audit_log)

    updated = service.apply_fill(update=_fill_update(), order_side=OrderSide.BUY)

    assert updated == Position("ES-202609-CME", 2, Decimal("5005.00"))
    assert store.saved_positions == [
        {"ES-202609-CME": Position("ES-202609-CME", 2, Decimal("5005.00"))}
    ]
    assert audit_log.events == (
        {
            "type": "position_ledger_fill_applied",
            "timestamp": "2026-06-28T16:45:00+00:00",
            "account_id": "acct-1",
            "client_order_id": "order-1",
            "broker_order_id": "broker-1",
            "instrument_id": "ES-202609-CME",
            "order_side": "buy",
            "fill_quantity": 1,
            "fill_price": "5010.00",
            "previous_quantity": 1,
            "previous_average_price": "5000.00",
            "updated_quantity": 2,
            "updated_average_price": "5005.00",
        },
    )


def test_position_ledger_reduces_existing_long_without_changing_average_price():
    from futures_bot.application.position_ledger import PositionLedgerService

    store = InMemoryPositionStore(
        {"ES-202609-CME": Position("ES-202609-CME", 3, Decimal("5000.00"))}
    )
    service = PositionLedgerService(store=store, audit_log=InMemoryAuditLog())

    updated = service.apply_fill(update=_fill_update(), order_side=OrderSide.SELL)

    assert updated == Position("ES-202609-CME", 2, Decimal("5000.00"))


def test_position_ledger_sets_fill_price_as_average_when_fill_flips_position_side():
    from futures_bot.application.position_ledger import PositionLedgerService

    store = InMemoryPositionStore(
        {"ES-202609-CME": Position("ES-202609-CME", 1, Decimal("5000.00"))}
    )
    service = PositionLedgerService(store=store, audit_log=InMemoryAuditLog())

    updated = service.apply_fill(
        update=_fill_update(fill_quantity=3, fill_price=Decimal("4990.00")),
        order_side=OrderSide.SELL,
    )

    assert updated == Position("ES-202609-CME", -2, Decimal("4990.00"))


def test_position_ledger_creates_new_position_from_fill():
    from futures_bot.application.position_ledger import PositionLedgerService

    store = InMemoryPositionStore()
    service = PositionLedgerService(store=store, audit_log=InMemoryAuditLog())

    updated = service.apply_fill(update=_fill_update(fill_quantity=2), order_side=OrderSide.BUY)

    assert updated == Position("ES-202609-CME", 2, Decimal("5010.00"))


def test_position_ledger_rejects_non_fill_update():
    from futures_bot.application.position_ledger import PositionLedgerService

    store = InMemoryPositionStore()
    service = PositionLedgerService(store=store, audit_log=InMemoryAuditLog())
    update = BrokerOrderUpdate(
        account_id="acct-1",
        client_order_id="order-1",
        broker_order_id="broker-1",
        instrument_id="ES-202609-CME",
        update_type=BrokerOrderUpdateType.WORKING,
        timestamp=NOW,
    )

    with pytest.raises(ValueError, match="position ledger only applies fill updates"):
        service.apply_fill(update=update, order_side=OrderSide.BUY)


def test_position_ledger_requires_fill_price():
    from futures_bot.application.position_ledger import PositionLedgerService

    store = InMemoryPositionStore()
    service = PositionLedgerService(store=store, audit_log=InMemoryAuditLog())

    with pytest.raises(ValueError, match="fill_price is required"):
        service.apply_fill(update=_fill_update(fill_price=None), order_side=OrderSide.BUY)
