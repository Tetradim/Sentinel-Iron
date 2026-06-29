from futures_bot.application.live_trading import LIVE_TRADING_ACTIVATION, LiveTradingGuard


def test_live_trading_guard_allows_paper_without_activation():
    decision = LiveTradingGuard().evaluate("paper", activation_token=None)

    assert decision.allowed is True
    assert decision.reason is None
    assert decision.detail == "paper broker environment does not require live activation"


def test_live_trading_guard_blocks_live_without_exact_activation():
    decision = LiveTradingGuard().evaluate("live", activation_token="wrong")

    assert decision.allowed is False
    assert decision.reason == "live_trading_activation_required"
    assert decision.detail == f"live trading requires activation token {LIVE_TRADING_ACTIVATION}"


def test_live_trading_guard_allows_live_with_exact_activation():
    decision = LiveTradingGuard().evaluate(
        "live",
        activation_token=LIVE_TRADING_ACTIVATION,
    )

    assert decision.allowed is True
    assert decision.reason is None
    assert decision.detail == "live trading activation accepted"


def test_live_trading_guard_blocks_unknown_environment():
    decision = LiveTradingGuard().evaluate("sandbox", activation_token=None)

    assert decision.allowed is False
    assert decision.reason == "unsupported_broker_environment"
    assert decision.detail == "broker environment must be paper or live"
