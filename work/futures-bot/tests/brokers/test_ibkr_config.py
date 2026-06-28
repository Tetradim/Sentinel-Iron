import pytest

from futures_bot.brokers.ibkr.config import BrokerEnvironment, IbkrConfig, load_ibkr_config


def _env(**overrides: str) -> dict[str, str]:
    env = {
        "BROKER_ENV": "paper",
        "IBKR_HOST": "127.0.0.1",
        "IBKR_PORT": "7497",
        "IBKR_CLIENT_ID": "101",
    }
    env.update(overrides)
    return env


def test_valid_paper_config_loads_from_mapping():
    config = load_ibkr_config(_env())

    assert config == IbkrConfig(
        environment=BrokerEnvironment.PAPER,
        host="127.0.0.1",
        port=7497,
        client_id=101,
    )


def test_valid_live_config_loads_from_mapping():
    config = load_ibkr_config(_env(BROKER_ENV="live", IBKR_PORT="7496"))

    assert config.environment == BrokerEnvironment.LIVE
    assert config.port == 7496


def test_unsupported_broker_environment_is_rejected():
    with pytest.raises(ValueError, match="BROKER_ENV must be one of"):
        load_ibkr_config(_env(BROKER_ENV="sandbox"))


def test_missing_host_is_rejected():
    env = _env()
    env.pop("IBKR_HOST")

    with pytest.raises(ValueError, match="IBKR_HOST is required"):
        load_ibkr_config(env)


def test_invalid_port_is_rejected():
    with pytest.raises(ValueError, match="IBKR_PORT must be an integer between 1 and 65535"):
        load_ibkr_config(_env(IBKR_PORT="not-a-port"))


def test_invalid_client_id_is_rejected():
    with pytest.raises(ValueError, match="IBKR_CLIENT_ID must be a positive integer"):
        load_ibkr_config(_env(IBKR_CLIENT_ID="0"))
