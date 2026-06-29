from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from futures_bot.application.rebalance_risk_context import (
    MarginEstimate,
    RebalanceRiskContextInputs,
    build_rebalance_risk_contexts,
)
from futures_bot.domain.enums import OrderSide, OrderType, SettlementType
from futures_bot.domain.instruments import ContractSpec, FuturesInstrument, TradingCalendar
from futures_bot.domain.orders import OrderIntent
from futures_bot.domain.portfolio import AccountSnapshot, MarketSnapshot, Position


NOW = datetime(2026, 6, 28, 15, 50, tzinfo=timezone.utc)


def _instrument(instrument_id: str = "ES-202609-CME") -> FuturesInstrument:
    symbol = instrument_id.split("-", maxsplit=1)[0]
    return FuturesInstrument(
        instrument_id=instrument_id,
        spec=ContractSpec(
            symbol=symbol,
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
            last_safe_trade_date=date(2026, 9, 14),
        ),
    )


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account_id="acct-1",
        equity=Decimal("100000"),
        initial_margin=Decimal("10000"),
        maintenance_margin=Decimal("8000"),
        buying_power=Decimal("50000"),
        timestamp=NOW,
    )


def _market(instrument_id: str = "ES-202609-CME") -> MarketSnapshot:
    return MarketSnapshot(
        instrument_id=instrument_id,
        bid=Decimal("5000.00"),
        ask=Decimal("5000.25"),
        last=Decimal("5000.00"),
        timestamp=NOW,
    )


def _position(instrument_id: str = "ES-202609-CME", quantity: int = 0) -> Position:
    return Position(
        instrument_id=instrument_id,
        quantity=quantity,
        average_price=Decimal("0"),
    )


def _intent(
    client_order_id: str = "order-1",
    instrument_id: str = "ES-202609-CME",
) -> OrderIntent:
    return OrderIntent(
        instrument_id=instrument_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        client_order_id=client_order_id,
    )


def _inputs(**overrides) -> RebalanceRiskContextInputs:
    inputs = RebalanceRiskContextInputs(
        now=NOW,
        account=_account(),
        instruments={"ES-202609-CME": _instrument()},
        markets={"ES-202609-CME": _market()},
        current_positions={"ES-202609-CME": _position(quantity=2)},
        margin_estimates={
            "order-1": MarginEstimate(
                initial_margin=Decimal("12000"),
                maintenance_margin=Decimal("10000"),
            ),
        },
        used_client_order_ids=frozenset({"already-used"}),
        realized_pnl_today=Decimal("-25"),
        recent_order_timestamps=(NOW - timedelta(seconds=20),),
        kill_switch_active=False,
        positions_reconciled=True,
    )
    return replace(inputs, **overrides)


def test_build_rebalance_risk_contexts_maps_each_intent_by_client_order_id():
    contexts = build_rebalance_risk_contexts(
        intents=(_intent(),),
        inputs=_inputs(),
    )

    context = contexts["order-1"]
    assert context.now == NOW
    assert context.account == _account()
    assert context.instrument == _instrument()
    assert context.market == _market()
    assert context.current_position == _position(quantity=2)
    assert context.used_client_order_ids == frozenset({"already-used"})
    assert context.estimated_order_initial_margin == Decimal("12000")
    assert context.estimated_order_maintenance_margin == Decimal("10000")
    assert context.realized_pnl_today == Decimal("-25")
    assert context.recent_order_timestamps == (NOW - timedelta(seconds=20),)
    assert context.kill_switch_active is False
    assert context.positions_reconciled is True


def test_build_rebalance_risk_contexts_scopes_working_orders_to_intent_instrument():
    working_es = OrderIntent(
        instrument_id="ES-202609-CME",
        side=OrderSide.SELL,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("5000.00"),
        client_order_id="working-es",
    )
    working_nq = OrderIntent(
        instrument_id="NQ-202609-CME",
        side=OrderSide.SELL,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("15000.00"),
        client_order_id="working-nq",
    )

    contexts = build_rebalance_risk_contexts(
        intents=(_intent(),),
        inputs=_inputs(working_order_intents=(working_es, working_nq)),
    )

    assert contexts["order-1"].working_order_intents == (working_es,)


def test_build_rebalance_risk_contexts_supports_multiple_instruments():
    contexts = build_rebalance_risk_contexts(
        intents=(
            _intent("order-1", "ES-202609-CME"),
            _intent("order-2", "NQ-202609-CME"),
        ),
        inputs=_inputs(
            instruments={
                "ES-202609-CME": _instrument("ES-202609-CME"),
                "NQ-202609-CME": _instrument("NQ-202609-CME"),
            },
            markets={
                "ES-202609-CME": _market("ES-202609-CME"),
                "NQ-202609-CME": _market("NQ-202609-CME"),
            },
            current_positions={
                "ES-202609-CME": _position("ES-202609-CME"),
                "NQ-202609-CME": _position("NQ-202609-CME"),
            },
            margin_estimates={
                "order-1": MarginEstimate(Decimal("12000"), Decimal("10000")),
                "order-2": MarginEstimate(Decimal("15000"), Decimal("12500")),
            },
        ),
    )

    assert set(contexts) == {"order-1", "order-2"}
    assert contexts["order-2"].instrument.instrument_id == "NQ-202609-CME"
    assert contexts["order-2"].estimated_order_initial_margin == Decimal("15000")


def test_build_rebalance_risk_contexts_rejects_duplicate_client_order_ids():
    try:
        build_rebalance_risk_contexts(
            intents=(_intent("order-1"), _intent("order-1")),
            inputs=_inputs(),
        )
    except ValueError as exc:
        assert str(exc) == "intent client order IDs must be unique"
    else:
        raise AssertionError("expected duplicate client order IDs to be rejected")


def test_build_rebalance_risk_contexts_rejects_missing_market_snapshot():
    try:
        build_rebalance_risk_contexts(
            intents=(_intent(),),
            inputs=_inputs(markets={}),
        )
    except ValueError as exc:
        assert str(exc) == "market snapshot is required for ES-202609-CME"
    else:
        raise AssertionError("expected missing market snapshot to be rejected")


def test_build_rebalance_risk_contexts_rejects_missing_margin_estimate():
    try:
        build_rebalance_risk_contexts(
            intents=(_intent(),),
            inputs=_inputs(margin_estimates={}),
        )
    except ValueError as exc:
        assert str(exc) == "margin estimate is required for order-1"
    else:
        raise AssertionError("expected missing margin estimate to be rejected")


def test_build_rebalance_risk_contexts_rejects_mismatched_position():
    try:
        build_rebalance_risk_contexts(
            intents=(_intent(),),
            inputs=_inputs(
                current_positions={
                    "ES-202609-CME": _position("NQ-202609-CME"),
                }
            ),
        )
    except ValueError as exc:
        assert str(exc) == "position instrument does not match ES-202609-CME"
    else:
        raise AssertionError("expected mismatched position to be rejected")
