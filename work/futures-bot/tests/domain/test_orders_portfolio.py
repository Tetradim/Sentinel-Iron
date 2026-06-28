from datetime import datetime, timezone
from decimal import Decimal

import pytest

from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import OrderIntent
from futures_bot.domain.portfolio import AccountSnapshot, Position


def test_order_intent_requires_positive_quantity():
    with pytest.raises(ValueError, match="quantity must be positive"):
        OrderIntent(
            instrument_id="ES-202609-CME",
            side=OrderSide.BUY,
            quantity=0,
            order_type=OrderType.MARKET,
            client_order_id="order-1",
        )


def test_limit_order_requires_limit_price():
    with pytest.raises(ValueError, match="limit_price is required"):
        OrderIntent(
            instrument_id="ES-202609-CME",
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.LIMIT,
            client_order_id="order-1",
        )


def test_market_order_does_not_require_limit_price():
    intent = OrderIntent(
        instrument_id="ES-202609-CME",
        side=OrderSide.SELL,
        quantity=2,
        order_type=OrderType.MARKET,
        client_order_id="order-2",
    )

    assert intent.limit_price is None


def test_position_computes_signed_quantity_after_order_side():
    position = Position(
        instrument_id="ES-202609-CME",
        quantity=3,
        average_price=Decimal("5500.00"),
    )

    assert position.quantity_after(OrderSide.BUY, 2) == 5
    assert position.quantity_after(OrderSide.SELL, 4) == -1


def test_account_margin_usage_is_initial_margin_divided_by_equity():
    account = AccountSnapshot(
        account_id="DU12345",
        equity=Decimal("100000"),
        initial_margin=Decimal("25000"),
        maintenance_margin=Decimal("20000"),
        buying_power=Decimal("75000"),
        timestamp=datetime(2026, 6, 28, 14, 30, tzinfo=timezone.utc),
    )

    assert account.margin_usage == Decimal("0.25")


def test_account_snapshot_rejects_negative_buying_power():
    with pytest.raises(ValueError, match="buying_power cannot be negative"):
        AccountSnapshot(
            account_id="DU12345",
            equity=Decimal("100000"),
            initial_margin=Decimal("25000"),
            maintenance_margin=Decimal("20000"),
            buying_power=Decimal("-1"),
            timestamp=datetime(2026, 6, 28, 14, 30, tzinfo=timezone.utc),
        )
