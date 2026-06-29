from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping
from urllib.parse import urlparse


class BrokerEnvironment(StrEnum):
    PAPER = "paper"
    LIVE = "live"


DEFAULT_BASE_URLS = {
    BrokerEnvironment.PAPER: "https://demo.tradovateapi.com/v1",
    BrokerEnvironment.LIVE: "https://live.tradovateapi.com/v1",
}


@dataclass(frozen=True)
class TradovateConfig:
    environment: BrokerEnvironment
    base_url: str
    access_token: str
    account_id: int
    account_spec: str


def load_tradovate_config(env: Mapping[str, str]) -> TradovateConfig:
    environment = _parse_environment(env.get("BROKER_ENV"))
    base_url = _parse_url(
        env.get("TRADOVATE_BASE_URL") or DEFAULT_BASE_URLS[environment],
        "TRADOVATE_BASE_URL",
    )
    access_token = _parse_required(env.get("TRADOVATE_ACCESS_TOKEN"), "TRADOVATE_ACCESS_TOKEN")
    account_id = _parse_int(env.get("TRADOVATE_ACCOUNT_ID"), "TRADOVATE_ACCOUNT_ID")
    account_spec = _parse_required(env.get("TRADOVATE_ACCOUNT_SPEC"), "TRADOVATE_ACCOUNT_SPEC")
    return TradovateConfig(
        environment=environment,
        base_url=base_url,
        access_token=access_token,
        account_id=account_id,
        account_spec=account_spec,
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


def _parse_int(value: str | None, name: str) -> int:
    raw_value = _parse_required(value, name)
    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _parse_url(value: str, name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an http or https URL")
    return value.rstrip("/")
