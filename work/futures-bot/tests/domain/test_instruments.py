from datetime import date
from decimal import Decimal

from futures_bot.domain.enums import SettlementType
from futures_bot.domain.instruments import ContractSpec, FuturesInstrument, TradingCalendar


def test_contract_spec_calculates_tick_value():
    spec = ContractSpec(
        symbol="ES",
        exchange="CME",
        contract_month="202609",
        multiplier=Decimal("50"),
        tick_size=Decimal("0.25"),
        currency="USD",
        settlement_type=SettlementType.CASH,
    )

    assert spec.tick_value == Decimal("12.50")


def test_contract_spec_rounds_prices_to_nearest_tick():
    spec = ContractSpec(
        symbol="CL",
        exchange="NYMEX",
        contract_month="202609",
        multiplier=Decimal("1000"),
        tick_size=Decimal("0.01"),
        currency="USD",
        settlement_type=SettlementType.PHYSICAL,
    )

    assert spec.round_to_tick(Decimal("82.134")) == Decimal("82.13")
    assert spec.round_to_tick(Decimal("82.135")) == Decimal("82.14")


def test_instrument_blocks_trading_after_last_safe_trade_date():
    instrument = FuturesInstrument(
        instrument_id="CL-202609-NYMEX",
        spec=ContractSpec(
            symbol="CL",
            exchange="NYMEX",
            contract_month="202609",
            multiplier=Decimal("1000"),
            tick_size=Decimal("0.01"),
            currency="USD",
            settlement_type=SettlementType.PHYSICAL,
        ),
        calendar=TradingCalendar(
            first_notice_date=date(2026, 8, 31),
            last_trade_date=date(2026, 9, 21),
            last_safe_trade_date=date(2026, 8, 28),
        ),
    )

    assert instrument.can_trade_on(date(2026, 8, 28)) is True
    assert instrument.can_trade_on(date(2026, 8, 29)) is False


def test_physical_settlement_marks_instrument_delivery_sensitive():
    physical = FuturesInstrument(
        instrument_id="ZC-202612-CBOT",
        spec=ContractSpec(
            symbol="ZC",
            exchange="CBOT",
            contract_month="202612",
            multiplier=Decimal("5000"),
            tick_size=Decimal("0.25"),
            currency="USD",
            settlement_type=SettlementType.PHYSICAL,
        ),
        calendar=TradingCalendar(
            first_notice_date=date(2026, 11, 30),
            last_trade_date=date(2026, 12, 14),
            last_safe_trade_date=date(2026, 11, 27),
        ),
    )

    cash = FuturesInstrument(
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
            last_safe_trade_date=date(2026, 9, 18),
        ),
    )

    assert physical.delivery_sensitive is True
    assert cash.delivery_sensitive is False
