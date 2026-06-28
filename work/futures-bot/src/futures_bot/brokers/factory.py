from __future__ import annotations

from typing import Mapping

from futures_bot.brokers.tradestation import TradeStationBroker, load_tradestation_config
from futures_bot.ports.broker import BrokerPort


def create_broker(name: str, env: Mapping[str, str]) -> BrokerPort:
    broker_name = name.strip().lower()
    if broker_name == "tradestation":
        return TradeStationBroker(load_tradestation_config(env))
    if broker_name == "ibkr":
        raise ValueError("ibkr broker adapter requires a TWS client implementation")
    if broker_name in {"ninjatrader", "optimus"}:
        raise ValueError(f"{broker_name} broker adapter is not implemented yet")
    raise ValueError(f"unsupported broker: {broker_name}")
