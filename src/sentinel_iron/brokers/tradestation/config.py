from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping
from urllib.parse import urlparse


class BrokerEnvironment(StrEnum):
    LIVE = "live"


DEFAULT_BASE_URLS = {
    BrokerEnvironment.LIVE: "https://api.tradestation.com/v3",
}


@dataclass(frozen=True)
class TradeStationConfig:
    environment: BrokerEnvironment
    base_url: str
    access_token: str
    account_id: str


def load_tradestation_config(env: Mapping[str, str]) -> TradeStationConfig:
    environment = _parse_environment(env.get("BROKER_ENV"))
    base_url = _parse_url(
        env.get("TRADESTATION_BASE_URL") or DEFAULT_BASE_URLS[environment],
        "TRADESTATION_BASE_URL",
        {"http", "https"},
    )
    access_token = _parse_required(env.get("TRADESTATION_ACCESS_TOKEN"), "TRADESTATION_ACCESS_TOKEN")
    account_id = _parse_required(env.get("TRADESTATION_ACCOUNT_ID"), "TRADESTATION_ACCOUNT_ID")
    return TradeStationConfig(
        environment=environment,
        base_url=base_url,
        access_token=access_token,
        account_id=account_id,
    )


def _parse_environment(value: str | None) -> BrokerEnvironment:
    try:
        return BrokerEnvironment(value)
    except ValueError as exc:
        allowed = ", ".join(environment.value for environment in BrokerEnvironment)
        raise ValueError(f"BROKER_ENV must be one of: {allowed}") from exc


def _parse_required(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _parse_url(value: str, name: str, allowed_schemes: set[str]) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in allowed_schemes or not parsed.netloc:
        allowed = " or ".join(sorted(allowed_schemes))
        raise ValueError(f"{name} must be an {allowed} URL")
    return value.rstrip("/")
