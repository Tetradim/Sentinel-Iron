from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class BrokerEnvironment(StrEnum):
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True)
class IbkrConfig:
    environment: BrokerEnvironment
    host: str
    port: int
    client_id: int


def load_ibkr_config(env: Mapping[str, str]) -> IbkrConfig:
    environment = _parse_environment(env.get("BROKER_ENV"))
    host = _parse_host(env.get("IBKR_HOST"))
    port = _parse_port(env.get("IBKR_PORT"))
    client_id = _parse_client_id(env.get("IBKR_CLIENT_ID"))
    return IbkrConfig(
        environment=environment,
        host=host,
        port=port,
        client_id=client_id,
    )


def _parse_environment(value: str | None) -> BrokerEnvironment:
    try:
        return BrokerEnvironment(value)
    except ValueError as exc:
        allowed = ", ".join(environment.value for environment in BrokerEnvironment)
        raise ValueError(f"BROKER_ENV must be one of: {allowed}") from exc


def _parse_host(value: str | None) -> str:
    if value is None or not value.strip():
        raise ValueError("IBKR_HOST is required")
    return value.strip()


def _parse_port(value: str | None) -> int:
    try:
        port = int(value or "")
    except ValueError as exc:
        raise ValueError("IBKR_PORT must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("IBKR_PORT must be an integer between 1 and 65535")
    return port


def _parse_client_id(value: str | None) -> int:
    try:
        client_id = int(value or "")
    except ValueError as exc:
        raise ValueError("IBKR_CLIENT_ID must be a positive integer") from exc
    if client_id <= 0:
        raise ValueError("IBKR_CLIENT_ID must be a positive integer")
    return client_id
