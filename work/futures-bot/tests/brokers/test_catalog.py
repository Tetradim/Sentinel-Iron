from __future__ import annotations

from futures_bot.brokers.catalog import (
    BrokerConnectionStatus,
    connection_backlog,
    known_futures_brokers,
    supported_broker_keys,
)


def test_catalog_includes_supported_live_capable_broker_routes():
    assert supported_broker_keys() == frozenset(
        {
            "ibkr",
            "ninjatrader",
            "optimus",
            "tradestation",
            "tradovate",
        }
    )


def test_catalog_tracks_documented_api_backlog():
    documented_backlog = {
        broker.broker_key
        for broker in connection_backlog()
        if broker.status == BrokerConnectionStatus.DOCUMENTED_API
    }

    assert documented_backlog >= {
        "ironbeam_xapi",
        "saxo_openapi",
        "tastytrade",
        "webull_openapi",
    }


def test_catalog_entries_have_unique_keys_and_source_urls():
    brokers = known_futures_brokers()
    keys = {broker.broker_key for broker in brokers}

    assert len(keys) == len(brokers)
    assert all(broker.source_url.startswith("https://") for broker in brokers)
    assert all(broker.display_name for broker in brokers)
    assert all(broker.api_surface for broker in brokers)
