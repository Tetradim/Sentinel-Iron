from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Mapping

from futures_bot.application.margin_estimates import MarginEstimateProviderPort
from futures_bot.brokers.ibkr import IbkrBroker, IbkrClientPort, IbapiTwsClient, load_ibkr_config
from futures_bot.brokers.ninjatrader import NinjaTraderBroker, load_ninjatrader_config
from futures_bot.brokers.optimus import OptimusBroker, load_optimus_config
from futures_bot.brokers.tradestation import TradeStationBroker, load_tradestation_config
from futures_bot.brokers.tradovate import TradovateBroker, load_tradovate_config
from futures_bot.ports.broker import BrokerPort
from futures_bot.ports.market_data import HistoricalDataPort


@dataclass(frozen=True)
class BrokerRoute:
    name: str
    execution: BrokerPort
    margin_estimator: MarginEstimateProviderPort
    historical_data: HistoricalDataPort


def create_broker_route(
    name: str,
    env: Mapping[str, str],
    ibkr_client_factory: Callable[[], IbkrClientPort] | None = None,
) -> BrokerRoute:
    broker_name = name.strip().lower()
    if broker_name == "tradestation":
        broker = TradeStationBroker(load_tradestation_config(env))
        return BrokerRoute(
            name=broker_name,
            execution=broker,
            margin_estimator=broker,
            historical_data=broker,
        )
    if broker_name == "ibkr":
        client = ibkr_client_factory() if ibkr_client_factory is not None else IbapiTwsClient()
        broker = IbkrBroker(load_ibkr_config(env), client)
        return BrokerRoute(
            name=broker_name,
            execution=broker,
            margin_estimator=broker,
            historical_data=broker,
        )
    if broker_name == "ninjatrader":
        broker = NinjaTraderBroker(load_ninjatrader_config(env))
        return BrokerRoute(
            name=broker_name,
            execution=broker,
            margin_estimator=broker,
            historical_data=broker,
        )
    if broker_name == "optimus":
        broker = OptimusBroker(load_optimus_config(env))
        return BrokerRoute(
            name=broker_name,
            execution=broker,
            margin_estimator=broker,
            historical_data=broker,
        )
    if broker_name == "tradovate":
        broker = TradovateBroker(load_tradovate_config(env))
        return BrokerRoute(
            name=broker_name,
            execution=broker,
            margin_estimator=broker,
            historical_data=broker,
        )
    raise ValueError(f"unsupported broker: {broker_name}")
