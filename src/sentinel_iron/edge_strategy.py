"""Sentinel Edge communication and execution orchestration for Sentinel Iron."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sentinel_iron.application.order_gateway import OrderGatewayResult, OrderGatewayService
from sentinel_iron.application.trading_readiness import TradingReadinessResult
from sentinel_iron.domain.enums import OrderSide, OrderType
from sentinel_iron.domain.orders import OrderIntent
from sentinel_iron.ports.audit import AuditLogPort
from sentinel_iron.risk.engine import RiskContext


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _positive_decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


@dataclass(frozen=True)
class EdgeExecutionResult:
    authorization: dict[str, Any]
    intent: OrderIntent | None
    gateway: OrderGatewayResult | None
    submitted: bool
    reason: str | None
    detail: str


class EdgeStrategyClient:
    """Small authenticated HTTP client for Edge's portfolio authority."""

    def __init__(self, base_url: str | None = None, secret: str | None = None, timeout_seconds: float | None = None) -> None:
        self.base_url = (base_url or os.getenv("EDGE_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
        self.secret = secret if secret is not None else os.getenv("EDGE_OPERATOR_ACTION_SECRET", "")
        self.timeout_seconds = timeout_seconds or max(0.5, float(os.getenv("IRON_EDGE_TIMEOUT_SECONDS", "5") or 5))

    def authorize(self, proposal: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "contract_version": "edge.strategy.proposal.v1",
            "source_bot": "sentinel-iron",
            "target_bot": "sentinel-iron",
            **proposal,
        }
        response = self._request("POST", "/bus/profitability/opportunities", payload)
        authorization = response.get("authorization") if isinstance(response.get("authorization"), dict) else None
        if authorization is None:
            raise RuntimeError("Edge response did not contain an authorization")
        return authorization

    def feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/bus/profitability/feedback",
            {"contract_version": "edge.strategy.feedback.v1", "source_bot": "sentinel-iron", **payload},
        )

    def trade_cards(self, *, include_terminal: bool = False) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            f"/bus/profitability/trade-cards?{urlencode({'include_terminal': str(include_terminal).lower()})}",
            None,
        )
        cards = response.get("trade_cards")
        return [item for item in cards if isinstance(item, dict)] if isinstance(cards, list) else []

    def _request(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        if not self.secret:
            raise RuntimeError("EDGE_OPERATOR_ACTION_SECRET is required")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Accept": "application/json", "X-Edge-Operator-Secret": self.secret, **({"Content-Type": "application/json"} if data else {})},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Edge returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Edge is unavailable: {exc.reason}") from exc


class EdgeAuthorizedOrderService:
    """Turns an Edge-authorized futures proposal into Iron's real order path."""

    def __init__(
        self,
        gateway: OrderGatewayService,
        audit_log: AuditLogPort,
        client: EdgeStrategyClient | None = None,
    ) -> None:
        self.gateway = gateway
        self.audit_log = audit_log
        self.client = client or EdgeStrategyClient()

    def execute(
        self,
        proposal: dict[str, Any],
        context: RiskContext,
        readiness: TradingReadinessResult,
        timestamp: datetime,
    ) -> EdgeExecutionResult:
        normalized = self._normalize_proposal(proposal)
        try:
            authorization = self.client.authorize(normalized)
        except Exception as exc:
            self._audit("edge_authorization_unavailable", timestamp, normalized, detail=str(exc))
            return EdgeExecutionResult({}, None, None, False, "edge_authorization_unavailable", str(exc))

        reasons = self.validate_authorization(authorization, normalized, timestamp)
        if reasons:
            detail = ",".join(reasons)
            self._audit("edge_authorization_rejected", timestamp, normalized, authorization=authorization, detail=detail)
            return EdgeExecutionResult(authorization, None, None, False, reasons[0], detail)

        intent = self.build_order_intent(authorization, normalized)
        gateway_result = self.gateway.submit(intent, context, readiness, timestamp)
        card = authorization.get("trade_card") if isinstance(authorization.get("trade_card"), dict) else {}
        feedback = {
            "feedback_id": f"sentinel-iron:{intent.client_order_id}:{'submitted' if gateway_result.submitted else 'rejected'}",
            "card_id": card.get("card_id"),
            "position_id": card.get("position_id"),
            "symbol": normalized["symbol"],
            "action": "entry" if gateway_result.submitted else "rejected",
            "feedback": {
                "accepted": gateway_result.submitted,
                "status": "submitted" if gateway_result.submitted else "rejected",
                "reason": gateway_result.reason,
                "detail": gateway_result.detail,
                "client_order_id": intent.client_order_id,
                "instrument_id": intent.instrument_id,
                "side": intent.side.value,
                "quantity": intent.quantity,
                "order_type": intent.order_type.value,
                "limit_price": str(intent.limit_price) if intent.limit_price is not None else None,
                "broker_order_id": (
                    gateway_result.submission.broker_order_id
                    if gateway_result.submission is not None
                    else None
                ),
            },
            "metadata": {"proposal_id": normalized["proposal_id"]},
        }
        try:
            self.client.feedback(feedback)
        except Exception as exc:
            self._audit("edge_feedback_delivery_failed", timestamp, normalized, authorization=authorization, detail=str(exc))
        self._audit(
            "edge_authorized_order_submitted" if gateway_result.submitted else "edge_authorized_order_blocked",
            timestamp,
            normalized,
            authorization=authorization,
            detail=gateway_result.detail,
        )
        return EdgeExecutionResult(
            authorization,
            intent,
            gateway_result,
            gateway_result.submitted,
            gateway_result.reason,
            gateway_result.detail,
        )

    def reconcile_position(
        self,
        authorization: dict[str, Any],
        *,
        quantity: int,
        average_price: Decimal | None,
        current_price: Decimal | None,
        realized_pnl: Decimal | None = None,
    ) -> dict[str, Any]:
        card = authorization.get("trade_card") if isinstance(authorization.get("trade_card"), dict) else {}
        if not card.get("card_id") or str(card.get("target_bot") or authorization.get("target_bot") or "") != "sentinel-iron":
            raise ValueError("position feedback requires an Iron trade card")
        payload = {
            "feedback_id": f"sentinel-iron:{card['position_id']}:{quantity}:{current_price}",
            "card_id": card["card_id"],
            "position_id": card["position_id"],
            "symbol": card["symbol"],
            "action": "position_update" if quantity else "exit",
            "position": {
                "quantity": quantity,
                "average_price": str(average_price) if average_price is not None else None,
                "current_price": str(current_price) if current_price is not None else None,
                "realized_pnl": str(realized_pnl) if realized_pnl is not None else None,
            },
            "current_price": float(current_price) if current_price is not None else 0.0,
        }
        return self.client.feedback(payload)

    @staticmethod
    def validate_authorization(authorization: dict[str, Any], proposal: dict[str, Any], timestamp: datetime) -> list[str]:
        reasons: list[str] = []
        if authorization.get("contract_version") != "edge.strategy.authorization.v1":
            reasons.append("edge_authorization_contract_invalid")
        if not bool(authorization.get("authorized")):
            reasons.append("edge_authorization_rejected")
        if str(authorization.get("target_bot") or "") != "sentinel-iron":
            reasons.append("edge_authorization_wrong_bot")
        card = authorization.get("trade_card") if isinstance(authorization.get("trade_card"), dict) else {}
        if str(card.get("symbol") or authorization.get("symbol") or "").upper() != proposal["symbol"]:
            reasons.append("edge_authorization_symbol_mismatch")
        if str(card.get("state") or "").lower() not in {"armed", "entering", "active"}:
            reasons.append("edge_trade_card_not_entry_eligible")
        expiry = _parse_time(card.get("expires_at"))
        if expiry is not None and expiry <= timestamp.astimezone(timezone.utc):
            reasons.append("edge_trade_card_expired")
        direction = str(card.get("direction") or "long").lower()
        expected_direction = "long" if proposal["side"] == "buy" else "short"
        if direction != expected_direction:
            reasons.append("edge_authorization_direction_mismatch")
        requested_notional = _positive_decimal(proposal.get("estimated_notional"))
        target_notional = _positive_decimal(card.get("target_notional") or authorization.get("target_notional"))
        if requested_notional is not None and target_notional is not None:
            tolerance = Decimal(str(os.getenv("IRON_EDGE_NOTIONAL_TOLERANCE_PCT", "2"))) / Decimal("100")
            if requested_notional > target_notional * (Decimal("1") + max(Decimal("0"), tolerance)):
                reasons.append("edge_target_notional_exceeded")
        stop_owner = (card.get("metadata") or {}).get("stop_owner") if isinstance(card.get("metadata"), dict) else None
        if isinstance(stop_owner, dict) and stop_owner.get("position_id") != card.get("position_id"):
            reasons.append("edge_stop_owner_mismatch")
        return reasons

    @staticmethod
    def build_order_intent(authorization: dict[str, Any], proposal: dict[str, Any]) -> OrderIntent:
        card = authorization.get("trade_card") if isinstance(authorization.get("trade_card"), dict) else {}
        side = OrderSide.BUY if proposal["side"] == "buy" else OrderSide.SELL
        order_type = OrderType.LIMIT if proposal["order_type"] == "limit" else OrderType.MARKET
        limit_price = _positive_decimal(proposal.get("limit_price")) if order_type == OrderType.LIMIT else None
        return OrderIntent(
            instrument_id=proposal["instrument_id"],
            side=side,
            quantity=proposal["quantity"],
            order_type=order_type,
            client_order_id=f"edge-{str(card.get('position_id') or proposal['proposal_id']).replace(':', '-')[:56]}",
            limit_price=limit_price,
        )

    @staticmethod
    def _normalize_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
        instrument_id = str(proposal.get("instrument_id") or proposal.get("symbol") or "").strip().upper()
        if not instrument_id:
            raise ValueError("instrument_id is required")
        side = str(proposal.get("side") or proposal.get("direction") or "").strip().lower()
        if side in {"long", "buy"}:
            side = "buy"
        elif side in {"short", "sell"}:
            side = "sell"
        else:
            raise ValueError("side must be buy/long or sell/short")
        quantity = _positive_int(proposal.get("quantity"))
        if quantity is None:
            raise ValueError("quantity must be a positive integer")
        order_type = str(proposal.get("order_type") or "market").strip().lower()
        if order_type not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        if order_type == "limit" and _positive_decimal(proposal.get("limit_price")) is None:
            raise ValueError("limit_price is required for limit orders")
        proposal_id = str(proposal.get("proposal_id") or "").strip()
        if not proposal_id:
            proposal_id = f"sentinel-iron:{instrument_id}:{side}:{quantity}:{datetime.now(timezone.utc).timestamp()}"
        normalized = {
            **proposal,
            "contract_version": "edge.strategy.proposal.v1",
            "proposal_id": proposal_id,
            "source_bot": "sentinel-iron",
            "target_bot": "sentinel-iron",
            "symbol": instrument_id,
            "instrument_id": instrument_id,
            "side": side,
            "direction": "long" if side == "buy" else "short",
            "quantity": quantity,
            "order_type": order_type,
            "confidence": float(proposal.get("confidence", 0.8)),
            "strategy": str(proposal.get("strategy") or "futures_strategy"),
            "regime": str(proposal.get("regime") or "unknown"),
        }
        return normalized

    def _audit(
        self,
        event_type: str,
        timestamp: datetime,
        proposal: dict[str, Any],
        *,
        authorization: dict[str, Any] | None = None,
        detail: str = "",
    ) -> None:
        card = authorization.get("trade_card") if isinstance(authorization, dict) and isinstance(authorization.get("trade_card"), dict) else {}
        self.audit_log.append(
            {
                "type": event_type,
                "timestamp": timestamp.isoformat(),
                "proposal_id": proposal.get("proposal_id"),
                "instrument_id": proposal.get("instrument_id"),
                "side": proposal.get("side"),
                "quantity": proposal.get("quantity"),
                "card_id": card.get("card_id"),
                "strategy_id": card.get("strategy_id"),
                "thesis_id": card.get("thesis_id"),
                "position_id": card.get("position_id"),
                "detail": detail,
            }
        )


def load_proposal(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("proposal file must contain one JSON object")
    return payload
