from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping
from urllib.parse import urlparse


class BrokerEnvironment(StrEnum):
    LIVE = "live"


class OptimusRoute(StrEnum):
    RITHMIC = "rithmic"
    CQG = "cqg"
    TRADING_TECHNOLOGIES = "tt"
    CTS = "cts"
    FIRETIP = "firetip"
    GAIN = "gain"
    OAK = "oak"
    QUICK_SCREEN_TRADING = "qst"


ROUTE_ALIASES = {
    "rithmic": OptimusRoute.RITHMIC,
    "cqg": OptimusRoute.CQG,
    "tt": OptimusRoute.TRADING_TECHNOLOGIES,
    "tradingtechnologies": OptimusRoute.TRADING_TECHNOLOGIES,
    "trading_technologies": OptimusRoute.TRADING_TECHNOLOGIES,
    "trading technologies": OptimusRoute.TRADING_TECHNOLOGIES,
    "cts": OptimusRoute.CTS,
    "firetip": OptimusRoute.FIRETIP,
    "gain": OptimusRoute.GAIN,
    "stonex": OptimusRoute.GAIN,
    "stonex gain": OptimusRoute.GAIN,
    "stone x": OptimusRoute.GAIN,
    "oak": OptimusRoute.OAK,
    "qst": OptimusRoute.QUICK_SCREEN_TRADING,
    "quick_screen_trading": OptimusRoute.QUICK_SCREEN_TRADING,
    "quick screen trading": OptimusRoute.QUICK_SCREEN_TRADING,
}


@dataclass(frozen=True)
class OptimusConfig:
    environment: BrokerEnvironment
    route: OptimusRoute
    username: str
    password: str
    account_id: str
    api_url: str | None
    app_name: str


def load_optimus_config(env: Mapping[str, str]) -> OptimusConfig:
    environment = _parse_environment(env.get("BROKER_ENV"))
    route = _parse_route(env.get("OPTIMUS_ROUTE"))
    username = _parse_required(env.get("OPTIMUS_USERNAME"), "OPTIMUS_USERNAME")
    password = _parse_required(env.get("OPTIMUS_PASSWORD"), "OPTIMUS_PASSWORD")
    account_id = _parse_required(env.get("OPTIMUS_ACCOUNT_ID"), "OPTIMUS_ACCOUNT_ID")
    api_url = _parse_optional_url(env.get("OPTIMUS_API_URL"), "OPTIMUS_API_URL")
    app_name = _parse_app_name(env.get("OPTIMUS_APP_NAME"))
    return OptimusConfig(
        environment=environment,
        route=route,
        username=username,
        password=password,
        account_id=account_id,
        api_url=api_url,
        app_name=app_name,
    )


def _parse_environment(value: str | None) -> BrokerEnvironment:
    try:
        return BrokerEnvironment(value)
    except ValueError as exc:
        allowed = ", ".join(environment.value for environment in BrokerEnvironment)
        raise ValueError(f"BROKER_ENV must be one of: {allowed}") from exc


def _parse_route(value: str | None) -> OptimusRoute:
    if value is None or not value.strip():
        raise ValueError("OPTIMUS_ROUTE is required")
    route = ROUTE_ALIASES.get(value.strip().lower())
    if route is None:
        allowed = ", ".join(route.value for route in OptimusRoute)
        raise ValueError(f"OPTIMUS_ROUTE must be one of: {allowed}")
    return route


def _parse_required(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _parse_optional_url(value: str | None, name: str) -> str | None:
    if value is None or not value.strip():
        return None
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an http or https URL")
    return url.rstrip("/")


def _parse_app_name(value: str | None) -> str:
    if value is None or not value.strip():
        return "sentinel-iron"
    return value.strip()
