from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from futures_bot.domain.portfolio import AccountSnapshot, Position
from futures_bot.ports.audit import AuditLogPort
from futures_bot.ports.broker import BrokerConnectionError, BrokerPort


@dataclass(frozen=True)
class BrokerConnectionRequest:
    broker_name: str
    environment: str
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.broker_name:
            raise ValueError("broker_name is required")
        if self.environment not in {"paper", "live"}:
            raise ValueError("environment must be paper or live")


@dataclass(frozen=True)
class BrokerConnectionResult:
    connected: bool
    account: AccountSnapshot | None
    positions: tuple[Position, ...]
    reason: str | None = None
    broker_error_code: str | None = None


class BrokerConnectionService:
    def __init__(self, broker: BrokerPort, audit_log: AuditLogPort) -> None:
        self._broker = broker
        self._audit_log = audit_log

    def connect(self, request: BrokerConnectionRequest) -> BrokerConnectionResult:
        try:
            self._broker.connect()
            account = self._broker.get_account()
            positions = self._broker.get_positions()
        except BrokerConnectionError as exc:
            self._audit_log.append(
                {
                    "type": "broker_connection_failed",
                    "timestamp": request.timestamp.isoformat(),
                    "broker": request.broker_name,
                    "environment": request.environment,
                    "reason": "broker_connection_error",
                    "detail": exc.reason,
                    "broker_error_code": exc.broker_error_code,
                }
            )
            return BrokerConnectionResult(
                connected=False,
                account=None,
                positions=(),
                reason=exc.reason,
                broker_error_code=exc.broker_error_code,
            )

        self._audit_log.append(
            {
                "type": "broker_connected",
                "timestamp": request.timestamp.isoformat(),
                "broker": request.broker_name,
                "environment": request.environment,
                "account_id": account.account_id,
                "equity": str(account.equity),
                "initial_margin": str(account.initial_margin),
                "maintenance_margin": str(account.maintenance_margin),
                "buying_power": str(account.buying_power),
                "position_count": len(positions),
            }
        )
        return BrokerConnectionResult(
            connected=True,
            account=account,
            positions=positions,
        )
