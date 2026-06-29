from datetime import datetime, timedelta, timezone
from decimal import Decimal

from futures_bot.application.kill_switch import KillSwitchState
from futures_bot.application.live_trading import LIVE_TRADING_ACTIVATION
from futures_bot.application.order_gateway import OrderGatewayService
from futures_bot.application.order_submission import OrderSubmissionService
from futures_bot.application.risk_check import RiskCheckService
from futures_bot.application.trading_readiness import TradingReadinessResult
from futures_bot.domain.enums import OrderSide, OrderType, SettlementType
from futures_bot.domain.instruments import ContractSpec, FuturesInstrument, TradingCalendar
from futures_bot.domain.order_lifecycle import OrderLifecycleStatus
from futures_bot.domain.orders import BrokerOrder, OrderIntent
from futures_bot.domain.portfolio import AccountSnapshot, MarketSnapshot, Position
from futures_bot.ports.audit import InMemoryAuditLog
from futures_bot.risk.engine import RiskContext, RiskEngine, RiskLimits


NOW = datetime(2026, 6, 28, 14, 35, tzinfo=timezone.utc)


class RecordingBroker:
    def __init__(self, broker_order_id: str = "broker-123") -> None:
        self.broker_order_id = broker_order_id
        self.submitted_orders: list[BrokerOrder] = []

    def connect(self) -> None:
        pass

    def get_account(self) -> AccountSnapshot:
        raise NotImplementedError

    def get_positions(self) -> tuple[Position, ...]:
        raise NotImplementedError

    def submit_order(self, order: BrokerOrder) -> str:
        self.submitted_orders.append(order)
        return self.broker_order_id

    def cancel_order(self, broker_order_id: str) -> None:
        raise NotImplementedError


class InMemoryKillSwitchStore:
    def __init__(self, state: KillSwitchState) -> None:
        self.state = state
        self.load_count = 0

    def load(self) -> KillSwitchState:
        self.load_count += 1
        return self.state

    def save(self, state: KillSwitchState) -> None:
        self.state = state


class FailingKillSwitchStore:
    def load(self) -> KillSwitchState:
        raise ValueError("invalid kill switch state")

    def save(self, state: KillSwitchState) -> None:
        raise NotImplementedError


def _instrument() -> FuturesInstrument:
    return FuturesInstrument(
        instrument_id="ES-202609-CME",
        spec=ContractSpec(
            symbol="ES",
            exchange="CME",
            contract_month="202609",
            multiplier=Decimal("50"),
            tick_size=Decimal("0.25"),
            currency="USD",
            settlement_type=SettlementType.CASH,
        ),
        calendar=TradingCalendar(
            first_notice_date=None,
            last_trade_date=NOW.date() + timedelta(days=80),
            last_safe_trade_date=NOW.date() + timedelta(days=75),
        ),
    )


def _limits() -> RiskLimits:
    return RiskLimits(
        max_order_quantity=10,
        max_position_abs=20,
        max_margin_usage=Decimal("0.8"),
        max_maintenance_margin_usage=Decimal("0.7"),
        max_daily_loss=Decimal("3000"),
        max_order_notional=Decimal("5000000"),
        max_position_notional=Decimal("10000000"),
        max_bid_ask_spread_percent=Decimal("0.01"),
        max_orders_per_window=5,
        order_rate_window=timedelta(minutes=1),
        account_stale_after=timedelta(seconds=10),
        market_data_stale_after=timedelta(seconds=2),
        price_collar_percent=Decimal("0.03"),
    )


def _context() -> RiskContext:
    return RiskContext(
        now=NOW,
        instrument=_instrument(),
        account=AccountSnapshot(
            account_id="acct-1",
            equity=Decimal("100000"),
            initial_margin=Decimal("10000"),
            maintenance_margin=Decimal("8000"),
            buying_power=Decimal("50000"),
            timestamp=NOW,
        ),
        market=MarketSnapshot(
            instrument_id="ES-202609-CME",
            bid=Decimal("5000.00"),
            ask=Decimal("5000.25"),
            last=Decimal("5000.00"),
            timestamp=NOW,
        ),
        current_position=Position(
            instrument_id="ES-202609-CME",
            quantity=0,
            average_price=Decimal("0"),
        ),
        used_client_order_ids=frozenset(),
        estimated_order_initial_margin=Decimal("12000"),
        estimated_order_maintenance_margin=Decimal("10000"),
        realized_pnl_today=Decimal("0"),
        recent_order_timestamps=(),
        kill_switch_active=False,
        positions_reconciled=True,
    )


def _intent() -> OrderIntent:
    return OrderIntent(
        instrument_id="ES-202609-CME",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("5000.25"),
        client_order_id="order-1",
    )


def _gateway(
    broker: RecordingBroker,
    audit_log: InMemoryAuditLog,
    kill_switch_store: InMemoryKillSwitchStore | FailingKillSwitchStore | None = None,
    broker_environment: str = "paper",
    live_trading_activation: str | None = None,
) -> OrderGatewayService:
    submission = OrderSubmissionService(
        risk_check=RiskCheckService(RiskEngine(_limits()), audit_log),
        broker=broker,
        audit_log=audit_log,
    )
    return OrderGatewayService(
        submission=submission,
        audit_log=audit_log,
        kill_switch_store=kill_switch_store,
        broker_environment=broker_environment,
        live_trading_activation=live_trading_activation,
    )


def test_order_gateway_blocks_not_ready_session_before_risk_or_broker_submission():
    audit_log = InMemoryAuditLog()
    broker = RecordingBroker()
    gateway = _gateway(broker, audit_log)

    result = gateway.submit(
        intent=_intent(),
        context=_context(),
        readiness=TradingReadinessResult(
            ready=False,
            reason="positions_not_reconciled",
            detail="quantity mismatch for ES-202609-CME: internal=1 broker=2",
        ),
        timestamp=NOW,
    )

    assert result.submitted is False
    assert result.submission is None
    assert result.reason == "trading_not_ready"
    assert result.detail == "quantity mismatch for ES-202609-CME: internal=1 broker=2"
    assert broker.submitted_orders == []
    assert audit_log.events == (
        {
            "type": "order_submission_blocked",
            "timestamp": "2026-06-28T14:35:00+00:00",
            "client_order_id": "order-1",
            "instrument_id": "ES-202609-CME",
            "reason": "trading_not_ready",
            "detail": "quantity mismatch for ES-202609-CME: internal=1 broker=2",
            "readiness_reason": "positions_not_reconciled",
            "side": "buy",
            "quantity": 1,
            "order_type": "limit",
            "limit_price": "5000.25",
        },
    )


def test_order_gateway_blocks_live_submission_without_activation_before_risk_or_broker():
    audit_log = InMemoryAuditLog()
    broker = RecordingBroker()
    gateway = _gateway(
        broker,
        audit_log,
        broker_environment="live",
        live_trading_activation=None,
    )

    result = gateway.submit(
        intent=_intent(),
        context=_context(),
        readiness=TradingReadinessResult(ready=True, reason=None, detail="ready"),
        timestamp=NOW,
    )

    assert result.submitted is False
    assert result.submission is None
    assert result.reason == "live_trading_activation_required"
    assert result.detail == f"live trading requires activation token {LIVE_TRADING_ACTIVATION}"
    assert broker.submitted_orders == []
    assert audit_log.events == (
        {
            "type": "order_submission_blocked",
            "timestamp": "2026-06-28T14:35:00+00:00",
            "client_order_id": "order-1",
            "instrument_id": "ES-202609-CME",
            "reason": "live_trading_activation_required",
            "detail": f"live trading requires activation token {LIVE_TRADING_ACTIVATION}",
            "readiness_reason": None,
            "side": "buy",
            "quantity": 1,
            "order_type": "limit",
            "limit_price": "5000.25",
        },
    )


def test_order_gateway_allows_live_submission_with_activation():
    audit_log = InMemoryAuditLog()
    broker = RecordingBroker()
    gateway = _gateway(
        broker,
        audit_log,
        broker_environment="live",
        live_trading_activation=LIVE_TRADING_ACTIVATION,
    )

    result = gateway.submit(
        intent=_intent(),
        context=_context(),
        readiness=TradingReadinessResult(ready=True, reason=None, detail="ready"),
        timestamp=NOW,
    )

    assert result.submitted is True
    assert broker.submitted_orders == [BrokerOrder.from_intent(_intent())]


def test_order_gateway_blocks_when_persisted_kill_switch_is_active():
    audit_log = InMemoryAuditLog()
    broker = RecordingBroker()
    kill_switch_store = InMemoryKillSwitchStore(
        KillSwitchState(
            active=True,
            reason="operator halt before news release",
            updated_at=NOW,
        )
    )
    gateway = _gateway(broker, audit_log, kill_switch_store=kill_switch_store)

    result = gateway.submit(
        intent=_intent(),
        context=_context(),
        readiness=TradingReadinessResult(ready=True, reason=None, detail="ready"),
        timestamp=NOW,
    )

    assert result.submitted is False
    assert result.submission is None
    assert result.reason == "kill_switch_active"
    assert result.detail == "operator halt before news release"
    assert broker.submitted_orders == []
    assert kill_switch_store.load_count == 1
    assert audit_log.events == (
        {
            "type": "order_submission_blocked",
            "timestamp": "2026-06-28T14:35:00+00:00",
            "client_order_id": "order-1",
            "instrument_id": "ES-202609-CME",
            "reason": "kill_switch_active",
            "detail": "operator halt before news release",
            "readiness_reason": None,
            "side": "buy",
            "quantity": 1,
            "order_type": "limit",
            "limit_price": "5000.25",
        },
    )


def test_order_gateway_fails_closed_when_persisted_kill_switch_state_is_unavailable():
    audit_log = InMemoryAuditLog()
    broker = RecordingBroker()
    gateway = _gateway(broker, audit_log, kill_switch_store=FailingKillSwitchStore())

    result = gateway.submit(
        intent=_intent(),
        context=_context(),
        readiness=TradingReadinessResult(ready=True, reason=None, detail="ready"),
        timestamp=NOW,
    )

    assert result.submitted is False
    assert result.submission is None
    assert result.reason == "kill_switch_state_unavailable"
    assert result.detail == "invalid kill switch state"
    assert broker.submitted_orders == []
    assert audit_log.events == (
        {
            "type": "order_submission_blocked",
            "timestamp": "2026-06-28T14:35:00+00:00",
            "client_order_id": "order-1",
            "instrument_id": "ES-202609-CME",
            "reason": "kill_switch_state_unavailable",
            "detail": "invalid kill switch state",
            "readiness_reason": None,
            "side": "buy",
            "quantity": 1,
            "order_type": "limit",
            "limit_price": "5000.25",
        },
    )


def test_order_gateway_submits_when_persisted_kill_switch_is_inactive():
    audit_log = InMemoryAuditLog()
    broker = RecordingBroker()
    kill_switch_store = InMemoryKillSwitchStore(KillSwitchState.inactive())
    gateway = _gateway(broker, audit_log, kill_switch_store=kill_switch_store)

    result = gateway.submit(
        intent=_intent(),
        context=_context(),
        readiness=TradingReadinessResult(ready=True, reason=None, detail="ready"),
        timestamp=NOW,
    )

    assert result.submitted is True
    assert broker.submitted_orders == [BrokerOrder.from_intent(_intent())]
    assert kill_switch_store.load_count == 1


def test_order_gateway_submits_ready_session_through_existing_submission_path():
    audit_log = InMemoryAuditLog()
    broker = RecordingBroker()
    gateway = _gateway(broker, audit_log)

    result = gateway.submit(
        intent=_intent(),
        context=_context(),
        readiness=TradingReadinessResult(ready=True, reason=None, detail="ready"),
        timestamp=NOW,
    )

    assert result.submitted is True
    assert result.reason is None
    assert result.detail == "submitted"
    assert result.submission is not None
    assert result.submission.lifecycle.status == OrderLifecycleStatus.WORKING
    assert result.submission.broker_order_id == "broker-123"
    assert broker.submitted_orders == [BrokerOrder.from_intent(_intent())]
    assert audit_log.events[-1]["type"] == "order_submitted"
