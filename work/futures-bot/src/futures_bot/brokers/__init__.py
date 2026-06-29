"""Broker infrastructure adapters."""

from futures_bot.brokers.catalog import (
    BrokerConnectionStatus,
    FuturesBrokerCandidate,
    connection_backlog,
    known_futures_brokers,
    supported_broker_keys,
)
from futures_bot.brokers.factory import create_broker
from futures_bot.brokers.routes import BrokerRoute, create_broker_route

__all__ = [
    "BrokerConnectionStatus",
    "BrokerRoute",
    "FuturesBrokerCandidate",
    "connection_backlog",
    "create_broker",
    "create_broker_route",
    "known_futures_brokers",
    "supported_broker_keys",
]
