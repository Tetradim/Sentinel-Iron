from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TypeVar

from futures_bot.domain.instruments import FuturesInstrument
from futures_bot.domain.orders import OrderIntent
from futures_bot.domain.portfolio import AccountSnapshot, MarketSnapshot, Position
from futures_bot.risk.engine import RiskContext


T = TypeVar("T")


@dataclass(frozen=True)
class MarginEstimate:
    initial_margin: Decimal
    maintenance_margin: Decimal

    def __post_init__(self) -> None:
        if self.initial_margin < 0:
            raise ValueError("initial_margin cannot be negative")
        if self.maintenance_margin < 0:
            raise ValueError("maintenance_margin cannot be negative")


@dataclass(frozen=True)
class RebalanceRiskContextInputs:
    now: datetime
    account: AccountSnapshot
    instruments: Mapping[str, FuturesInstrument]
    markets: Mapping[str, MarketSnapshot]
    current_positions: Mapping[str, Position]
    margin_estimates: Mapping[str, MarginEstimate]
    used_client_order_ids: frozenset[str]
    realized_pnl_today: Decimal
    recent_order_timestamps: tuple[datetime, ...]
    kill_switch_active: bool
    positions_reconciled: bool
    working_order_intents: tuple[OrderIntent, ...] = ()


def build_rebalance_risk_contexts(
    intents: tuple[OrderIntent, ...],
    inputs: RebalanceRiskContextInputs,
) -> dict[str, RiskContext]:
    seen_client_order_ids: set[str] = set()
    contexts: dict[str, RiskContext] = {}

    for intent in intents:
        if intent.client_order_id in seen_client_order_ids:
            raise ValueError("intent client order IDs must be unique")
        seen_client_order_ids.add(intent.client_order_id)

        instrument = _instrument_for_intent(intent, inputs)
        market = _market_for_intent(intent, inputs)
        current_position = _position_for_intent(intent, inputs)
        margin_estimate = _margin_estimate_for_intent(intent, inputs)

        contexts[intent.client_order_id] = RiskContext(
            now=inputs.now,
            instrument=instrument,
            account=inputs.account,
            market=market,
            current_position=current_position,
            used_client_order_ids=inputs.used_client_order_ids,
            estimated_order_initial_margin=margin_estimate.initial_margin,
            estimated_order_maintenance_margin=margin_estimate.maintenance_margin,
            realized_pnl_today=inputs.realized_pnl_today,
            recent_order_timestamps=inputs.recent_order_timestamps,
            kill_switch_active=inputs.kill_switch_active,
            positions_reconciled=inputs.positions_reconciled,
            working_order_intents=_working_order_intents_for_intent(intent, inputs),
        )

    return contexts


def _instrument_for_intent(
    intent: OrderIntent,
    inputs: RebalanceRiskContextInputs,
) -> FuturesInstrument:
    instrument = _required(
        values=inputs.instruments,
        key=intent.instrument_id,
        label="instrument",
    )
    if instrument.instrument_id != intent.instrument_id:
        raise ValueError(f"instrument input does not match {intent.instrument_id}")
    return instrument


def _market_for_intent(
    intent: OrderIntent,
    inputs: RebalanceRiskContextInputs,
) -> MarketSnapshot:
    market = _required(
        values=inputs.markets,
        key=intent.instrument_id,
        label="market snapshot",
    )
    if market.instrument_id != intent.instrument_id:
        raise ValueError(
            f"market snapshot instrument does not match {intent.instrument_id}"
        )
    return market


def _position_for_intent(
    intent: OrderIntent,
    inputs: RebalanceRiskContextInputs,
) -> Position:
    position = _required(
        values=inputs.current_positions,
        key=intent.instrument_id,
        label="position",
    )
    if position.instrument_id != intent.instrument_id:
        raise ValueError(f"position instrument does not match {intent.instrument_id}")
    return position


def _margin_estimate_for_intent(
    intent: OrderIntent,
    inputs: RebalanceRiskContextInputs,
) -> MarginEstimate:
    return _required(
        values=inputs.margin_estimates,
        key=intent.client_order_id,
        label="margin estimate",
    )


def _working_order_intents_for_intent(
    intent: OrderIntent,
    inputs: RebalanceRiskContextInputs,
) -> tuple[OrderIntent, ...]:
    return tuple(
        working_intent
        for working_intent in inputs.working_order_intents
        if working_intent.instrument_id == intent.instrument_id
        and working_intent.client_order_id != intent.client_order_id
    )


def _required(values: Mapping[str, T], key: str, label: str) -> T:
    try:
        return values[key]
    except KeyError as exc:
        raise ValueError(f"{label} is required for {key}") from exc
