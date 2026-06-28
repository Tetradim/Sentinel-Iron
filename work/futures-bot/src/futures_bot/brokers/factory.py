from __future__ import annotations

from collections.abc import Callable
from typing import Mapping

from futures_bot.brokers.ibkr import IbkrBroker, IbkrClientPort, IbapiTwsClient, load_ibkr_config
from futures_bot.brokers.ninjatrader import NinjaTraderBroker, load_ninjatrader_config
from futures_bot.brokers.tradestation import TradeStationBroker, load_tradestation_config
from futures_bot.ports.broker import BrokerPort


def create_broker(
    name: str,
    env: Mapping[str, str],
    ibkr_client_factory: Callable[[], IbkrClientPort] | None = None,
) -> BrokerPort:
    broker_name = name.strip().lower()
    if broker_name == "tradestation":
        return TradeStationBroker(load_tradestation_config(env))
    if broker_name == "ibkr":
        client = ibkr_client_factory() if ibkr_client_factory is not None else IbapiTwsClient()
        return IbkrBroker(load_ibkr_config(env), client)
    if broker_name == "ninjatrader":
        return NinjaTraderBroker(load_ninjatrader_config(env))
    if broker_name in {"optimus"}:
        raise ValueError(f"{broker_name} broker adapter is not implemented yet")
    raise ValueError(f"unsupported broker: {broker_name}")
