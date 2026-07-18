from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sentinel_iron.application.order_gateway import OrderGatewayResult
from sentinel_iron.edge_strategy import EdgeAuthorizedOrderService
from sentinel_iron.ports.audit import InMemoryAuditLog


def _authorization(*, target_bot: str = "sentinel-iron"):
    now = datetime.now(timezone.utc)
    return {
        "contract_version": "edge.strategy.authorization.v1",
        "authorized": True,
        "symbol": "ES-202609-CME",
        "target_bot": target_bot,
        "target_notional": 100000.0,
        "trade_card": {
            "card_id": "edge-card:iron",
            "strategy_id": "edge-strategy:iron",
            "thesis_id": "edge-thesis:iron",
            "position_id": "edge-position:iron",
            "symbol": "ES-202609-CME",
            "target_bot": target_bot,
            "direction": "long",
            "state": "armed",
            "target_notional": 100000.0,
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
            "metadata": {"stop_owner": {"position_id": "edge-position:iron", "inherit_on_reentry": False}},
        },
    }


def _proposal():
    return {
        "proposal_id": "iron-proposal-1",
        "instrument_id": "ES-202609-CME",
        "side": "buy",
        "quantity": 1,
        "order_type": "market",
        "confidence": 0.85,
        "strategy": "trend_following",
        "regime": "trending_up",
        "expected_reward_pct": 3.0,
        "expected_risk_pct": 1.0,
        "estimated_cost_pct": 0.05,
        "estimated_notional": 5000,
    }


class FakeClient:
    def __init__(self, authorization):
        self.authorization = authorization
        self.feedback_payloads = []

    def authorize(self, proposal):
        self.proposal = proposal
        return self.authorization

    def feedback(self, payload):
        self.feedback_payloads.append(payload)
        return {"status": "recorded"}


class FakeGateway:
    def __init__(self, submitted=True):
        self.submitted = submitted
        self.intents = []

    def submit(self, intent, context, readiness, timestamp):
        self.intents.append(intent)
        submission = SimpleNamespace(broker_order_id="broker-1") if self.submitted else None
        return OrderGatewayResult(
            submitted=self.submitted,
            readiness=readiness,
            submission=submission,
            reason=None if self.submitted else "risk_rejected",
            detail="submitted" if self.submitted else "risk rejected",
        )


def test_authorized_proposal_flows_through_real_order_intent_and_gateway():
    client = FakeClient(_authorization())
    gateway = FakeGateway()
    audit = InMemoryAuditLog()
    service = EdgeAuthorizedOrderService(gateway, audit, client)
    readiness = SimpleNamespace(ready=True, reason=None, detail="ready")

    result = service.execute(_proposal(), SimpleNamespace(), readiness, datetime.now(timezone.utc))

    assert result.submitted is True
    assert result.intent.instrument_id == "ES-202609-CME"
    assert result.intent.quantity == 1
    assert result.intent.client_order_id.startswith("edge-edge-position-iron")
    assert gateway.intents == [result.intent]
    assert client.feedback_payloads[0]["card_id"] == "edge-card:iron"
    assert audit.events[-1]["type"] == "edge_authorized_order_submitted"


def test_wrong_bot_authorization_never_reaches_gateway():
    client = FakeClient(_authorization(target_bot="sentinel-chain"))
    gateway = FakeGateway()
    service = EdgeAuthorizedOrderService(gateway, InMemoryAuditLog(), client)
    readiness = SimpleNamespace(ready=True, reason=None, detail="ready")

    result = service.execute(_proposal(), SimpleNamespace(), readiness, datetime.now(timezone.utc))

    assert result.submitted is False
    assert result.reason == "edge_authorization_wrong_bot"
    assert gateway.intents == []


def test_position_reconciliation_returns_card_and_position_identity():
    client = FakeClient(_authorization())
    service = EdgeAuthorizedOrderService(FakeGateway(), InMemoryAuditLog(), client)

    response = service.reconcile_position(
        _authorization(),
        quantity=1,
        average_price=None,
        current_price=None,
    )

    assert response["status"] == "recorded"
    assert client.feedback_payloads[-1]["position_id"] == "edge-position:iron"
