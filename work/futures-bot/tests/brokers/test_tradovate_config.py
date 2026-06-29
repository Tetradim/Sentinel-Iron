from __future__ import annotations

from futures_bot.brokers.tradovate.config import (
    BrokerEnvironment,
    load_tradovate_config,
)


def _env(**overrides: str) -> dict[str, str]:
    env = {
        "BROKER_ENV": "paper",
        "TRADOVATE_ACCESS_TOKEN": "token-123",
        "TRADOVATE_ACCOUNT_ID": "123456",
        "TRADOVATE_ACCOUNT_SPEC": "DEMO123456",
    }
    env.update(overrides)
    return env


def test_load_tradovate_config_uses_environment_base_urls():
    config = load_tradovate_config(_env())

    assert config.environment == BrokerEnvironment.PAPER
    assert config.base_url == "https://demo.tradovateapi.com/v1"
    assert config.access_token == "token-123"
    assert config.account_id == 123456
    assert config.account_spec == "DEMO123456"


def test_load_tradovate_config_uses_live_base_url():
    config = load_tradovate_config(_env(BROKER_ENV="live"))

    assert config.environment == BrokerEnvironment.LIVE
    assert config.base_url == "https://live.tradovateapi.com/v1"


def test_load_tradovate_config_accepts_explicit_base_url():
    config = load_tradovate_config(
        _env(TRADOVATE_BASE_URL="https://tradovate-proxy.example.test/api")
    )

    assert config.base_url == "https://tradovate-proxy.example.test/api"


def test_load_tradovate_config_requires_integer_account_id():
    try:
        load_tradovate_config(_env(TRADOVATE_ACCOUNT_ID="not-an-int"))
    except ValueError as exc:
        assert str(exc) == "TRADOVATE_ACCOUNT_ID must be an integer"
    else:
        raise AssertionError("expected invalid account ID to be rejected")


def test_load_tradovate_config_requires_token():
    try:
        load_tradovate_config(_env(TRADOVATE_ACCESS_TOKEN=" "))
    except ValueError as exc:
        assert str(exc) == "TRADOVATE_ACCESS_TOKEN is required"
    else:
        raise AssertionError("expected missing token to be rejected")
