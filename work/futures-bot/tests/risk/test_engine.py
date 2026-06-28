from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from futures_bot.domain.enums import OrderSide, OrderType, RiskReason, SettlementType
from futures_bot.domain.instruments import ContractSpec, FuturesInstrument, TradingCalendar
from futures_bot.domain.orders import OrderIntent
from futures_bot.domain.portfolio import AccountSnapshot, MarketSnapshot, Position
from futures_bot.risk.engine import RiskContext, RiskEngine, RiskLimits


NOW = datetime(2026, 6, 28, 15, 0, tzinfo=timezone.utc)


def _instrument(last_safe_trade_date: date = date(2026, 9, 18)) -> FuturesInstrument:
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
            last_trade_date=date(2026, 9, 18),
            last_safe_trade_date=last_safe_trade_date,
        ),
    )


def _intent(
    quantity: int = 1,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
    client_order_id: str = "order-1",
) -> OrderIntent:
    return OrderIntent(
        instrument_id="ES-202609-CME",
        side=OrderSide.BUY,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        client_order_id=client_order_id,
    )


def _limits() -> RiskLimits:
    return RiskLimits(
        max_order_quantity=5,
        max_position_abs=10,
        max_margin_usage=Decimal("0.50"),
        account_stale_after=timedelta(seconds=30),
        market_data_stale_after=timedelta(seconds=10),
        price_collar_percent=Decimal("0.05"),
    )


def _context(**overrides) -> RiskContext:
    context = RiskContext(
        now=NOW,
        instrument=_instrument(),
        account=AccountSnapshot(
            account_id="DU12345",
            equity=Decimal("100000"),
            initial_margin=Decimal("10000"),
            maintenance_margin=Decimal("8000"),
            buying_power=Decimal("90000"),
            timestamp=NOW - timedelta(seconds=5),
        ),
        market=MarketSnapshot(
            instrument_id="ES-202609-CME",
            bid=Decimal("4999.75"),
            ask=Decimal("5000.25"),
            last=Decimal("5000.00"),
            timestamp=NOW - timedelta(seconds=2),
        ),
        current_position=Position(
            instrument_id="ES-202609-CME",
            quantity=0,
            average_price=Decimal("0"),
        ),
        used_client_order_ids=frozenset(),
        estimated_order_initial_margin=Decimal("5000"),
        kill_switch_active=False,
        positions_reconciled=True,
    )
    return replace(context, **overrides)


def test_risk_engine_rejects_active_kill_switch():
    decision = RiskEngine(_limits()).evaluate(_intent(), _context(kill_switch_active=True))

    assert decision.approved is False
    assert decision.reason == RiskReason.KILL_SWITCH_ACTIVE


def test_risk_engine_rejects_unreconciled_positions():
    decision = RiskEngine(_limits()).evaluate(_intent(), _context(positions_reconciled=False))

    assert decision.approved is False
    assert decision.reason == RiskReason.UNRECONCILED_POSITIONS


def test_risk_engine_rejects_stale_account_snapshot():
    stale_account = replace(_context().account, timestamp=NOW - timedelta(seconds=31))

    decision = RiskEngine(_limits()).evaluate(_intent(), _context(account=stale_account))

    assert decision.approved is False
    assert decision.reason == RiskReason.STALE_ACCOUNT


def test_risk_engine_rejects_stale_market_data():
    stale_market = replace(_context().market, timestamp=NOW - timedelta(seconds=11))

    decision = RiskEngine(_limits()).evaluate(_intent(), _context(market=stale_market))

    assert decision.approved is False
    assert decision.reason == RiskReason.STALE_MARKET_DATA


def test_risk_engine_rejects_max_order_quantity_breach():
    decision = RiskEngine(_limits()).evaluate(_intent(quantity=6), _context())

    assert decision.approved is False
    assert decision.reason == RiskReason.MAX_ORDER_QUANTITY


def test_risk_engine_rejects_max_resulting_position_breach():
    position = Position(
        instrument_id="ES-202609-CME",
        quantity=9,
        average_price=Decimal("5000"),
    )

    decision = RiskEngine(_limits()).evaluate(_intent(quantity=2), _context(current_position=position))

    assert decision.approved is False
    assert decision.reason == RiskReason.MAX_POSITION


def test_risk_engine_rejects_max_margin_usage_breach():
    decision = RiskEngine(_limits()).evaluate(
        _intent(),
        _context(estimated_order_initial_margin=Decimal("45000")),
    )

    assert decision.approved is False
    assert decision.reason == RiskReason.MAX_MARGIN_USAGE


def test_risk_engine_rejects_contract_after_cutoff():
    expired = _instrument(last_safe_trade_date=date(2026, 6, 27))

    decision = RiskEngine(_limits()).evaluate(_intent(), _context(instrument=expired))

    assert decision.approved is False
    assert decision.reason == RiskReason.CONTRACT_NOT_TRADABLE


def test_risk_engine_rejects_duplicate_client_order_id():
    decision = RiskEngine(_limits()).evaluate(
        _intent(client_order_id="duplicate"),
        _context(used_client_order_ids=frozenset({"duplicate"})),
    )

    assert decision.approved is False
    assert decision.reason == RiskReason.DUPLICATE_CLIENT_ORDER_ID


def test_risk_engine_rejects_limit_price_outside_collar():
    decision = RiskEngine(_limits()).evaluate(
        _intent(order_type=OrderType.LIMIT, limit_price=Decimal("5300.25")),
        _context(),
    )

    assert decision.approved is False
    assert decision.reason == RiskReason.PRICE_COLLAR


def test_risk_engine_approves_order_when_all_checks_pass():
    decision = RiskEngine(_limits()).evaluate(_intent(), _context())

    assert decision.approved is True
    assert decision.reason is None
    assert decision.detail == "approved"
