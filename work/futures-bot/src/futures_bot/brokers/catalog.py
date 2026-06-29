from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BrokerConnectionStatus(StrEnum):
    SUPPORTED = "supported"
    DOCUMENTED_API = "documented_api"
    ROUTE_PROVIDER = "route_provider"
    ROUTE_BROKER = "route_broker"


@dataclass(frozen=True)
class FuturesBrokerCandidate:
    broker_key: str
    display_name: str
    status: BrokerConnectionStatus
    api_surface: str
    source_url: str
    notes: str


def known_futures_brokers() -> tuple[FuturesBrokerCandidate, ...]:
    return (
        FuturesBrokerCandidate(
            broker_key="ibkr",
            display_name="Interactive Brokers",
            status=BrokerConnectionStatus.SUPPORTED,
            api_surface="TWS / IB Gateway API",
            source_url="https://interactivebrokers.github.io/tws-api/",
            notes="Native adapter is implemented through the IBKR client port.",
        ),
        FuturesBrokerCandidate(
            broker_key="tradestation",
            display_name="TradeStation",
            status=BrokerConnectionStatus.SUPPORTED,
            api_surface="TradeStation API v3",
            source_url="https://api.tradestation.com/docs/",
            notes="Native REST adapter is implemented for account, positions, orders, margin checks, and daily bars.",
        ),
        FuturesBrokerCandidate(
            broker_key="ninjatrader",
            display_name="NinjaTrader",
            status=BrokerConnectionStatus.SUPPORTED,
            api_surface="NinjaTrader REST bridge",
            source_url="https://developer.ninjatrader.com/",
            notes="Native adapter is implemented for configured REST access and fails closed for unverified optional capabilities.",
        ),
        FuturesBrokerCandidate(
            broker_key="optimus",
            display_name="Optimus Futures",
            status=BrokerConnectionStatus.SUPPORTED,
            api_surface="Configured Optimus route bridge",
            source_url="https://optimusfutures.com/Futures-Trading-Platforms.php",
            notes="Route-aware adapter is implemented for Rithmic, CQG, TT, CTS, Firetip, StoneX/Gain, OAK, and QST bridge routes.",
        ),
        FuturesBrokerCandidate(
            broker_key="tradovate",
            display_name="Tradovate",
            status=BrokerConnectionStatus.SUPPORTED,
            api_surface="Tradovate REST API",
            source_url="https://api.tradovate.com/",
            notes="Native REST adapter is implemented for account, balances, positions, order submission, and cancellation.",
        ),
        FuturesBrokerCandidate(
            broker_key="tastytrade",
            display_name="tastytrade",
            status=BrokerConnectionStatus.DOCUMENTED_API,
            api_surface="tastytrade Open API",
            source_url="https://developer.tastytrade.com/",
            notes="Public HTTP API is documented; futures-specific order and account mapping still needs adapter implementation.",
        ),
        FuturesBrokerCandidate(
            broker_key="ironbeam_xapi",
            display_name="Ironbeam",
            status=BrokerConnectionStatus.DOCUMENTED_API,
            api_surface="Ironbeam xAPI",
            source_url="https://www.ironbeam.com/xapi/",
            notes="Public xAPI surface is documented; add adapter after validating auth and futures order lifecycle payloads.",
        ),
        FuturesBrokerCandidate(
            broker_key="saxo_openapi",
            display_name="Saxo Bank",
            status=BrokerConnectionStatus.DOCUMENTED_API,
            api_surface="Saxo OpenAPI",
            source_url="https://www.developer.saxo/openapi/learn",
            notes="OpenAPI documents futures asset coverage; add regional account eligibility checks before enabling live trading.",
        ),
        FuturesBrokerCandidate(
            broker_key="webull_openapi",
            display_name="Webull",
            status=BrokerConnectionStatus.DOCUMENTED_API,
            api_surface="Webull OpenAPI",
            source_url="https://www.webull.com/open-api",
            notes="OpenAPI is documented; futures endpoint and account eligibility need adapter-level verification.",
        ),
        FuturesBrokerCandidate(
            broker_key="cqg",
            display_name="CQG",
            status=BrokerConnectionStatus.ROUTE_PROVIDER,
            api_surface="CQG APIs",
            source_url="https://partners.cqg.com/api-resources",
            notes="Common futures execution/data route used by multiple FCMs; implement as a vendor route before broker aliases.",
        ),
        FuturesBrokerCandidate(
            broker_key="rithmic",
            display_name="Rithmic",
            status=BrokerConnectionStatus.ROUTE_PROVIDER,
            api_surface="Rithmic R | API+",
            source_url="https://www.rithmic.com/apis",
            notes="Common futures execution/data route used by multiple FCMs; likely requires SDK access and certification.",
        ),
        FuturesBrokerCandidate(
            broker_key="trading_technologies",
            display_name="Trading Technologies",
            status=BrokerConnectionStatus.ROUTE_PROVIDER,
            api_surface="TT REST / FIX APIs",
            source_url="https://library.tradingtechnologies.com/tt-rest/v2/",
            notes="Institutional futures route; implement as a vendor adapter with account-scoped entitlements.",
        ),
        FuturesBrokerCandidate(
            broker_key="amp_futures",
            display_name="AMP Futures",
            status=BrokerConnectionStatus.ROUTE_BROKER,
            api_surface="Broker through CQG, Rithmic, TT, and other routes",
            source_url="https://www.ampfutures.com/trading-platforms/",
            notes="Broker connection should reuse route-provider adapters rather than a fake AMP-only API.",
        ),
        FuturesBrokerCandidate(
            broker_key="edgeclear",
            display_name="EdgeClear",
            status=BrokerConnectionStatus.ROUTE_BROKER,
            api_surface="Broker through supported futures platforms and routes",
            source_url="https://edgeclear.com/trading-platforms/",
            notes="Broker connection should be implemented as route aliases once vendor route adapters are available.",
        ),
        FuturesBrokerCandidate(
            broker_key="stage_5_trading",
            display_name="Stage 5 Trading",
            status=BrokerConnectionStatus.ROUTE_BROKER,
            api_surface="Broker through supported futures platforms and routes",
            source_url="https://stage5trading.com/platforms/",
            notes="Broker connection should be implemented as route aliases once vendor route adapters are available.",
        ),
        FuturesBrokerCandidate(
            broker_key="stonex_gain",
            display_name="StoneX / GAIN Futures",
            status=BrokerConnectionStatus.ROUTE_PROVIDER,
            api_surface="StoneX / GAIN futures routing",
            source_url="https://gainfutures.com/",
            notes="Supported as an Optimus route bridge option; direct adapter needs verified API access.",
        ),
    )


def supported_broker_keys() -> frozenset[str]:
    return frozenset(
        broker.broker_key
        for broker in known_futures_brokers()
        if broker.status == BrokerConnectionStatus.SUPPORTED
    )


def connection_backlog() -> tuple[FuturesBrokerCandidate, ...]:
    return tuple(
        broker
        for broker in known_futures_brokers()
        if broker.status != BrokerConnectionStatus.SUPPORTED
    )
