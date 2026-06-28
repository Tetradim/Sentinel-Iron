from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from futures_bot.application.risk_check import RiskCheckService
from futures_bot.domain.enums import OrderSide, OrderType, SettlementType
from futures_bot.domain.instruments import ContractSpec, FuturesInstrument, TradingCalendar
from futures_bot.domain.orders import OrderIntent
from futures_bot.domain.portfolio import AccountSnapshot, MarketSnapshot, Position
from futures_bot.ports.audit import InMemoryAuditLog
from futures_bot.risk.engine import RiskContext, RiskEngine, RiskLimits


NOW = datetime(2026, 6, 28, 14, 30, tzinfo=timezone.utc)


def _instrument() -> FuturesInstrument:
    return FuturesInstrument(
        instrument_id="ES-202609-CME",
        spec=ContractSpec(
            symbol="ES",
            exchange="CME",
            contract_month="202609",
            multiplier=Decimal("50"),
            tick_size=Decimal("0.25"),
            currency="USD",
            settlement_type=SettlementType.CASH,
        ),
        calendar=TradingCalendar(
            first_notice_date=None,
            last_trade_date=NOW.date() + timedelta(days=80),
            last_safe_trade_date=NOW.date() + timedelta(days=75),
        ),
    )


def _limits() -> RiskLimits:
    return RiskLimits(
        max_order_quantity=10,
        max_position_abs=20,
        max_margin_usage=Decimal("0.8"),
        max_maintenance_margin_usage=Decimal("0.7"),
        max_daily_loss=Decimal("3000"),
        max_order_notional=Decimal("5000000"),
        max_position_notional=Decimal("10000000"),
        max_bid_ask_spread_percent=Decimal("0.01"),
        max_orders_per_window=5,
        order_rate_window=timedelta(minutes=1),
        account_stale_after=timedelta(seconds=10),
        market_data_stale_after=timedelta(seconds=2),
        price_collar_percent=Decimal("0.03"),
    )


def _context() -> RiskContext:
    return RiskContext(
        now=NOW,
        instrument=_instrument(),
        account=AccountSnapshot(
            account_id="acct-1",
            equity=Decimal("100000"),
            initial_margin=Decimal("10000"),
            maintenance_margin=Decimal("8000"),
            buying_power=Decimal("50000"),
            timestamp=NOW,
        ),
        market=MarketSnapshot(
            instrument_id="ES-202609-CME",
            bid=Decimal("5000.00"),
            ask=Decimal("5000.25"),
            last=Decimal("5000.00"),
            timestamp=NOW,
        ),
        current_position=Position(
            instrument_id="ES-202609-CME",
            quantity=0,
            average_price=Decimal("0"),
        ),
        used_client_order_ids=frozenset(),
        estimated_order_initial_margin=Decimal("12000"),
        estimated_order_maintenance_margin=Decimal("10000"),
        realized_pnl_today=Decimal("0"),
        recent_order_timestamps=(),
        kill_switch_active=False,
        positions_reconciled=True,
    )


def test_risk_check_returns_approved_decision_and_audits_event():
    audit_log = InMemoryAuditLog()
    service = RiskCheckService(RiskEngine(_limits()), audit_log)

    decision = service.check(
        OrderIntent(
            instrument_id="ES-202609-CME",
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
            client_order_id="order-1",
        ),
        _context(),
    )

    assert decision.approved is True
    assert audit_log.events == (
        {
            "type": "risk_decision",
            "timestamp": "2026-06-28T14:30:00+00:00",
            "account_id": "acct-1",
            "client_order_id": "order-1",
            "instrument_id": "ES-202609-CME",
            "approved": True,
            "reason": None,
            "detail": "approved",
            "side": "buy",
            "quantity": 1,
            "order_type": "market",
            "limit_price": None,
        },
    )


def test_risk_check_audits_rejected_decision_reason_and_account():
    audit_log = InMemoryAuditLog()
    service = RiskCheckService(RiskEngine(_limits()), audit_log)

    decision = service.check(
        OrderIntent(
            instrument_id="ES-202609-CME",
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
            client_order_id="order-1",
        ),
        replace(_context(), used_client_order_ids=frozenset({"order-1"})),
    )

    assert decision.approved is False
    assert audit_log.events[0]["account_id"] == "acct-1"
    assert audit_log.events[0]["approved"] is False
    assert audit_log.events[0]["reason"] == "duplicate_client_order_id"
    assert audit_log.events[0]["detail"] == "client order ID was already used"
