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
        max_daily_loss=Decimal("2500"),
        max_order_notional=Decimal("1000000"),
        max_position_notional=Decimal("2000000"),
        max_bid_ask_spread_percent=Decimal("0.001"),
        max_orders_per_window=3,
        order_rate_window=timedelta(seconds=10),
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
        realized_pnl_today=Decimal("0"),
        recent_order_timestamps=(),
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


def test_risk_engine_rejects_intent_for_different_instrument():
    decision = RiskEngine(_limits()).evaluate(
        replace(_intent(), instrument_id="NQ-202609-CME"),
        _context(),
    )

    assert decision.approved is False
    assert decision.reason == RiskReason.INSTRUMENT_MISMATCH
    assert decision.detail == "order intent instrument does not match risk context instrument"


def test_risk_engine_rejects_market_snapshot_for_different_instrument():
    market = replace(_context().market, instrument_id="NQ-202609-CME")

    decision = RiskEngine(_limits()).evaluate(_intent(), _context(market=market))

    assert decision.approved is False
    assert decision.reason == RiskReason.INSTRUMENT_MISMATCH
    assert decision.detail == "market snapshot instrument does not match risk context instrument"


def test_risk_engine_rejects_position_for_different_instrument():
    position = Position(
        instrument_id="NQ-202609-CME",
        quantity=0,
        average_price=Decimal("0"),
    )

    decision = RiskEngine(_limits()).evaluate(_intent(), _context(current_position=position))

    assert decision.approved is False
    assert decision.reason == RiskReason.INSTRUMENT_MISMATCH
    assert decision.detail == "position instrument does not match risk context instrument"


def test_risk_engine_rejects_max_order_quantity_breach():
    decision = RiskEngine(_limits()).evaluate(_intent(quantity=6), _context())

    assert decision.approved is False
    assert decision.reason == RiskReason.MAX_ORDER_QUANTITY


def test_risk_engine_rejects_max_order_notional_breach():
    decision = RiskEngine(_limits()).evaluate(_intent(quantity=5), _context())

    assert decision.approved is False
    assert decision.reason == RiskReason.MAX_ORDER_NOTIONAL
    assert decision.detail == "estimated order notional exceeds limit"


def test_risk_engine_rejects_max_resulting_position_breach():
    position = Position(
        instrument_id="ES-202609-CME",
        quantity=9,
        average_price=Decimal("5000"),
    )

    decision = RiskEngine(_limits()).evaluate(_intent(quantity=2), _context(current_position=position))

    assert decision.approved is False
    assert decision.reason == RiskReason.MAX_POSITION


def test_risk_engine_rejects_max_position_notional_breach():
    position = Position(
        instrument_id="ES-202609-CME",
        quantity=8,
        average_price=Decimal("5000"),
    )

    decision = RiskEngine(_limits()).evaluate(_intent(quantity=1), _context(current_position=position))

    assert decision.approved is False
    assert decision.reason == RiskReason.MAX_POSITION_NOTIONAL
    assert decision.detail == "estimated resulting position notional exceeds limit"


def test_risk_engine_rejects_max_margin_usage_breach():
    decision = RiskEngine(_limits()).evaluate(
        _intent(),
        _context(estimated_order_initial_margin=Decimal("45000")),
    )

    assert decision.approved is False
    assert decision.reason == RiskReason.MAX_MARGIN_USAGE


def test_risk_engine_rejects_max_daily_loss_breach():
    decision = RiskEngine(_limits()).evaluate(
        _intent(),
        _context(realized_pnl_today=Decimal("-2500")),
    )

    assert decision.approved is False
    assert decision.reason == RiskReason.MAX_DAILY_LOSS


def test_risk_engine_rejects_order_rate_limit_breach():
    decision = RiskEngine(_limits()).evaluate(
        _intent(),
        _context(
            recent_order_timestamps=(
                NOW - timedelta(seconds=1),
                NOW - timedelta(seconds=4),
                NOW - timedelta(seconds=9),
            )
        ),
    )

    assert decision.approved is False
    assert decision.reason == RiskReason.ORDER_RATE_LIMIT
    assert decision.detail == "order rate limit reached"


def test_risk_engine_ignores_recent_order_timestamps_outside_rate_window():
    decision = RiskEngine(_limits()).evaluate(
        _intent(),
        _context(
            recent_order_timestamps=(
                NOW - timedelta(seconds=2),
                NOW - timedelta(seconds=4),
                NOW - timedelta(seconds=11),
            )
        ),
    )

    assert decision.approved is True
    assert decision.reason is None


def test_risk_engine_rejects_market_without_two_sided_quote():
    one_sided_market = replace(_context().market, bid=None)

    decision = RiskEngine(_limits()).evaluate(_intent(), _context(market=one_sided_market))

    assert decision.approved is False
    assert decision.reason == RiskReason.MARKET_NOT_TWO_SIDED
    assert decision.detail == "market quote is not two-sided"


def test_risk_engine_rejects_crossed_market_quote():
    crossed_market = replace(
        _context().market,
        bid=Decimal("5000.25"),
        ask=Decimal("4999.75"),
    )

    decision = RiskEngine(_limits()).evaluate(_intent(), _context(market=crossed_market))

    assert decision.approved is False
    assert decision.reason == RiskReason.CROSSED_MARKET
    assert decision.detail == "market bid is greater than ask"


def test_risk_engine_rejects_wide_bid_ask_spread():
    wide_market = replace(
        _context().market,
        bid=Decimal("4990.00"),
        ask=Decimal("5010.00"),
    )

    decision = RiskEngine(_limits()).evaluate(_intent(), _context(market=wide_market))

    assert decision.approved is False
    assert decision.reason == RiskReason.WIDE_BID_ASK_SPREAD
    assert decision.detail == "bid/ask spread exceeds limit"


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


def test_risk_engine_rejects_limit_price_not_aligned_to_tick_size():
    decision = RiskEngine(_limits()).evaluate(
        _intent(order_type=OrderType.LIMIT, limit_price=Decimal("5000.10")),
        _context(),
    )

    assert decision.approved is False
    assert decision.reason == RiskReason.INVALID_TICK_PRICE
    assert decision.detail == "limit price is not aligned to contract tick size"


def test_risk_engine_approves_limit_price_aligned_to_tick_size():
    decision = RiskEngine(_limits()).evaluate(
        _intent(order_type=OrderType.LIMIT, limit_price=Decimal("5000.25")),
        _context(),
    )

    assert decision.approved is True
    assert decision.reason is None


def test_risk_engine_approves_order_when_all_checks_pass():
    decision = RiskEngine(_limits()).evaluate(_intent(), _context())

    assert decision.approved is True
    assert decision.reason is None
    assert decision.detail == "approved"


def test_risk_limits_rejects_non_positive_max_daily_loss():
    try:
        RiskLimits(
            max_order_quantity=5,
            max_position_abs=10,
            max_margin_usage=Decimal("0.50"),
            max_daily_loss=Decimal("0"),
            max_order_notional=Decimal("1000000"),
            max_position_notional=Decimal("2000000"),
            max_bid_ask_spread_percent=Decimal("0.001"),
            max_orders_per_window=3,
            order_rate_window=timedelta(seconds=10),
            account_stale_after=timedelta(seconds=30),
            market_data_stale_after=timedelta(seconds=10),
            price_collar_percent=Decimal("0.05"),
        )
    except ValueError as exc:
        assert str(exc) == "max_daily_loss must be positive"
    else:
        raise AssertionError("expected non-positive max_daily_loss to be rejected")


def test_risk_limits_rejects_non_positive_max_bid_ask_spread_percent():
    try:
        RiskLimits(
            max_order_quantity=5,
            max_position_abs=10,
            max_margin_usage=Decimal("0.50"),
            max_daily_loss=Decimal("2500"),
            max_order_notional=Decimal("1000000"),
            max_position_notional=Decimal("2000000"),
            max_bid_ask_spread_percent=Decimal("0"),
            max_orders_per_window=3,
            order_rate_window=timedelta(seconds=10),
            account_stale_after=timedelta(seconds=30),
            market_data_stale_after=timedelta(seconds=10),
            price_collar_percent=Decimal("0.05"),
        )
    except ValueError as exc:
        assert str(exc) == "max_bid_ask_spread_percent must be positive"
    else:
        raise AssertionError("expected non-positive max_bid_ask_spread_percent to be rejected")


def test_risk_limits_rejects_non_positive_max_order_notional():
    try:
        RiskLimits(
            max_order_quantity=5,
            max_position_abs=10,
            max_margin_usage=Decimal("0.50"),
            max_daily_loss=Decimal("2500"),
            max_order_notional=Decimal("0"),
            max_position_notional=Decimal("2000000"),
            max_bid_ask_spread_percent=Decimal("0.001"),
            max_orders_per_window=3,
            order_rate_window=timedelta(seconds=10),
            account_stale_after=timedelta(seconds=30),
            market_data_stale_after=timedelta(seconds=10),
            price_collar_percent=Decimal("0.05"),
        )
    except ValueError as exc:
        assert str(exc) == "max_order_notional must be positive"
    else:
        raise AssertionError("expected non-positive max_order_notional to be rejected")


def test_risk_limits_rejects_non_positive_max_position_notional():
    try:
        RiskLimits(
            max_order_quantity=5,
            max_position_abs=10,
            max_margin_usage=Decimal("0.50"),
            max_daily_loss=Decimal("2500"),
            max_order_notional=Decimal("1000000"),
            max_position_notional=Decimal("0"),
            max_bid_ask_spread_percent=Decimal("0.001"),
            max_orders_per_window=3,
            order_rate_window=timedelta(seconds=10),
            account_stale_after=timedelta(seconds=30),
            market_data_stale_after=timedelta(seconds=10),
            price_collar_percent=Decimal("0.05"),
        )
    except ValueError as exc:
        assert str(exc) == "max_position_notional must be positive"
    else:
        raise AssertionError("expected non-positive max_position_notional to be rejected")


def test_risk_limits_rejects_non_positive_max_orders_per_window():
    try:
        RiskLimits(
            max_order_quantity=5,
            max_position_abs=10,
            max_margin_usage=Decimal("0.50"),
            max_daily_loss=Decimal("2500"),
            max_order_notional=Decimal("1000000"),
            max_position_notional=Decimal("2000000"),
            max_bid_ask_spread_percent=Decimal("0.001"),
            max_orders_per_window=0,
            order_rate_window=timedelta(seconds=10),
            account_stale_after=timedelta(seconds=30),
            market_data_stale_after=timedelta(seconds=10),
            price_collar_percent=Decimal("0.05"),
        )
    except ValueError as exc:
        assert str(exc) == "max_orders_per_window must be positive"
    else:
        raise AssertionError("expected non-positive max_orders_per_window to be rejected")


def test_risk_limits_rejects_non_positive_order_rate_window():
    try:
        RiskLimits(
            max_order_quantity=5,
            max_position_abs=10,
            max_margin_usage=Decimal("0.50"),
            max_daily_loss=Decimal("2500"),
            max_order_notional=Decimal("1000000"),
            max_position_notional=Decimal("2000000"),
            max_bid_ask_spread_percent=Decimal("0.001"),
            max_orders_per_window=3,
            order_rate_window=timedelta(0),
            account_stale_after=timedelta(seconds=30),
            market_data_stale_after=timedelta(seconds=10),
            price_collar_percent=Decimal("0.05"),
        )
    except ValueError as exc:
        assert str(exc) == "order_rate_window must be positive"
    else:
        raise AssertionError("expected non-positive order_rate_window to be rejected")
