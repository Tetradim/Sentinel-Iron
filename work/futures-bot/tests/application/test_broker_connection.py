from datetime import datetime, timezone
from decimal import Decimal

from futures_bot.application.broker_connection import (
    BrokerConnectionRequest,
    BrokerConnectionService,
)
from futures_bot.domain.orders import BrokerOrder
from futures_bot.domain.portfolio import AccountSnapshot, Position
from futures_bot.ports.audit import InMemoryAuditLog
from futures_bot.ports.broker import BrokerConnectionError


NOW = datetime(2026, 6, 28, 14, 33, tzinfo=timezone.utc)


class RecordingBroker:
    def __init__(self) -> None:
        self.connected = False
        self.account = AccountSnapshot(
            account_id="acct-1",
            equity=Decimal("100000"),
            initial_margin=Decimal("10000"),
            maintenance_margin=Decimal("8000"),
            buying_power=Decimal("50000"),
            timestamp=NOW,
        )
        self.positions = (
            Position(
                instrument_id="ES-202609-CME",
                quantity=2,
                average_price=Decimal("5000.25"),
            ),
        )

    def connect(self) -> None:
        self.connected = True

    def get_account(self) -> AccountSnapshot:
        return self.account

    def get_positions(self) -> tuple[Position, ...]:
        return self.positions

    def submit_order(self, order: BrokerOrder) -> str:
        raise NotImplementedError

    def cancel_order(self, broker_order_id: str) -> None:
        raise NotImplementedError


class FailingBroker(RecordingBroker):
    def connect(self) -> None:
        raise BrokerConnectionError(
            reason="gateway socket refused connection",
            broker_error_code="CONNECTION_REFUSED",
        )


def _request(**overrides: object) -> BrokerConnectionRequest:
    values = {
        "broker_name": "ibkr",
        "environment": "paper",
        "timestamp": NOW,
    }
    values.update(overrides)
    return BrokerConnectionRequest(**values)


def test_broker_connection_connects_fetches_state_and_audits_snapshot():
    audit_log = InMemoryAuditLog()
    broker = RecordingBroker()
    service = BrokerConnectionService(broker=broker, audit_log=audit_log)

    result = service.connect(_request())

    assert broker.connected is True
    assert result.connected is True
    assert result.account == broker.account
    assert result.positions == broker.positions
    assert result.reason is None
    assert result.broker_error_code is None
    assert audit_log.events == (
        {
            "type": "broker_connected",
            "timestamp": "2026-06-28T14:33:00+00:00",
            "broker": "ibkr",
            "environment": "paper",
            "account_id": "acct-1",
            "equity": "100000",
            "initial_margin": "10000",
            "maintenance_margin": "8000",
            "buying_power": "50000",
            "position_count": 1,
        },
    )


def test_broker_connection_audits_connection_failure_without_account_state():
    audit_log = InMemoryAuditLog()
    broker = FailingBroker()
    service = BrokerConnectionService(broker=broker, audit_log=audit_log)

    result = service.connect(_request())

    assert result.connected is False
    assert result.account is None
    assert result.positions == ()
    assert result.reason == "gateway socket refused connection"
    assert result.broker_error_code == "CONNECTION_REFUSED"
    assert audit_log.events == (
        {
            "type": "broker_connection_failed",
            "timestamp": "2026-06-28T14:33:00+00:00",
            "broker": "ibkr",
            "environment": "paper",
            "reason": "broker_connection_error",
            "detail": "gateway socket refused connection",
            "broker_error_code": "CONNECTION_REFUSED",
        },
    )


def test_broker_connection_request_rejects_unknown_environment():
    try:
        _request(environment="demo")
    except ValueError as exc:
        assert str(exc) == "environment must be paper or live"
    else:
        raise AssertionError("expected unknown broker environment to be rejected")
