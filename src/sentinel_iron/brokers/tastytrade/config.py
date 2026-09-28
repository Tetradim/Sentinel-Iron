from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping
from urllib.parse import urlparse


class BrokerEnvironment(StrEnum):
    LIVE = "live"


DEFAULT_BASE_URLS = {
    BrokerEnvironment.LIVE: "https://api.tastytrade.com",
}


@dataclass(frozen=True)
class TastytradeConfig:
    environment: BrokerEnvironment
    base_url: str
    session_token: str
    customer_id: str
    account_number: str


def load_tastytrade_config(env: Mapping[str, str]) -> TastytradeConfig:
    environment = _parse_environment(env.get("BROKER_ENV"))
    base_url = _parse_url(
        env.get("TASTYTRADE_BASE_URL") or DEFAULT_BASE_URLS[environment],
        "TASTYTRADE_BASE_URL",
    )
    return TastytradeConfig(
        environment=environment,
        base_url=base_url,
        session_token=_parse_required(env.get("TASTYTRADE_SESSION_TOKEN"), "TASTYTRADE_SESSION_TOKEN"),
        customer_id=_parse_required(env.get("TASTYTRADE_CUSTOMER_ID"), "TASTYTRADE_CUSTOMER_ID"),
        account_number=_parse_required(env.get("TASTYTRADE_ACCOUNT_NUMBER"), "TASTYTRADE_ACCOUNT_NUMBER"),
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


def _parse_url(value: str, name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an http or https URL")
    return value.rstrip("/")
