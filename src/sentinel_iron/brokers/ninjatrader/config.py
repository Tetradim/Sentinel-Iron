from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping
from urllib.parse import urlparse


class BrokerEnvironment(StrEnum):
    LIVE = "live"


@dataclass(frozen=True)
class NinjaTraderConfig:
    environment: BrokerEnvironment
    rest_url: str
    websocket_url: str
    access_token: str
    account_id: str


def load_ninjatrader_config(env: Mapping[str, str]) -> NinjaTraderConfig:
    environment = _parse_environment(env.get("BROKER_ENV"))
    rest_url = _parse_required_url(
        env.get("NINJATRADER_REST_URL"),
        "NINJATRADER_REST_URL",
        {"http", "https"},
    )
    websocket_url = _parse_required_url(
        env.get("NINJATRADER_WS_URL"),
        "NINJATRADER_WS_URL",
        {"ws", "wss"},
    )
    access_token = _parse_required(env.get("NINJATRADER_ACCESS_TOKEN"), "NINJATRADER_ACCESS_TOKEN")
    account_id = _parse_required(env.get("NINJATRADER_ACCOUNT_ID"), "NINJATRADER_ACCOUNT_ID")
    return NinjaTraderConfig(
        environment=environment,
        rest_url=rest_url,
        websocket_url=websocket_url,
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


def _parse_required_url(value: str | None, name: str, allowed_schemes: set[str]) -> str:
    url = _parse_required(value, name)
    parsed = urlparse(url)
    if parsed.scheme not in allowed_schemes or not parsed.netloc:
        allowed = " or ".join(sorted(allowed_schemes))
        article = "an" if allowed.startswith("http") else "a"
        raise ValueError(f"{name} must be {article} {allowed} URL")
    return url.rstrip("/")
