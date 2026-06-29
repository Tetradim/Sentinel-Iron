from __future__ import annotations

from dataclasses import dataclass


LIVE_TRADING_ACTIVATION = "ENABLE-LIVE-TRADING"


@dataclass(frozen=True)
class LiveTradingDecision:
    allowed: bool
    reason: str | None
    detail: str


class LiveTradingGuard:
    def evaluate(
        self,
        broker_environment: str,
        activation_token: str | None,
    ) -> LiveTradingDecision:
        environment = broker_environment.strip().lower()
        if environment == "paper":
            return LiveTradingDecision(
                allowed=True,
                reason=None,
                detail="paper broker environment does not require live activation",
            )
        if environment != "live":
            return LiveTradingDecision(
                allowed=False,
                reason="unsupported_broker_environment",
                detail="broker environment must be paper or live",
            )

        if activation_token != LIVE_TRADING_ACTIVATION:
            return LiveTradingDecision(
                allowed=False,
                reason="live_trading_activation_required",
                detail=f"live trading requires activation token {LIVE_TRADING_ACTIVATION}",
            )

        return LiveTradingDecision(
            allowed=True,
            reason=None,
            detail="live trading activation accepted",
        )
