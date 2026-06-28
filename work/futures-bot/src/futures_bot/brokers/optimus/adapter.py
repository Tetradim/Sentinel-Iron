from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from futures_bot.application.margin_estimates import MarginEstimateUnavailable
from futures_bot.application.rebalance_risk_context import MarginEstimate
from futures_bot.brokers.optimus.config import OptimusConfig
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder
from futures_bot.domain.portfolio import AccountSnapshot, Position
from futures_bot.ports.broker import (
    BrokerCancellationError,
    BrokerConnectionError,
    BrokerSubmissionError,
)


class OptimusBridgeError(RuntimeError):
    def __init__(
        self,
        reason: str,
        status_code: int | None = None,
        broker_error_code: str | None = None,
    ) -> None:
        if not reason:
            raise ValueError("reason is required")
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code
        self.broker_error_code = broker_error_code


class OptimusTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None = None,
    ) -> Mapping[str, object] | None:
        """Send one Optimus route bridge HTTP request."""


class UrllibOptimusTransport:
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None = None,
    ) -> Mapping[str, object] | None:
        request_body = None
        if body is not None:
            request_body = json.dumps(body, separators=(",", ":")).encode("utf-8")

        request = Request(
            url=url,
            data=request_body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            reason, broker_error_code = _extract_error(response_body)
            raise OptimusBridgeError(reason, exc.code, broker_error_code) from exc
        except URLError as exc:
            raise OptimusBridgeError(str(exc.reason), None, "NETWORK_ERROR") from exc

        if not response_body.strip():
            return None
        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise OptimusBridgeError("Optimus bridge response was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise OptimusBridgeError("Optimus bridge response was not a JSON object")
        return parsed


@dataclass(frozen=True)
class OptimusBroker:
    config: OptimusConfig
    transport: OptimusTransport | None = None
    clock: Callable[[], datetime] | None = None

    def __post_init__(self) -> None:
        if self.config.api_url is None:
            raise ValueError("OPTIMUS_API_URL is required for Optimus broker adapter")
        if self.transport is None:
            object.__setattr__(self, "transport", UrllibOptimusTransport())
        if self.clock is None:
            object.__setattr__(self, "clock", lambda: datetime.now(timezone.utc))

    def connect(self) -> None:
        try:
            payload = self._request("GET", self._account_path())
        except OptimusBridgeError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc

        account_id = _account_id(payload)
        if account_id != self.config.account_id:
            raise BrokerConnectionError("configured Optimus account was not returned")

    def get_account(self) -> AccountSnapshot:
        try:
            payload = self._request("GET", self._account_path())
            account_id = _account_id(payload)
            if account_id != self.config.account_id:
                raise ValueError("account ID did not match configured account")
            return AccountSnapshot(
                account_id=account_id,
                equity=_required_decimal(payload, "equity", "Equity", "netLiquidation"),
                initial_margin=_decimal(payload, "initialMargin", "InitialMargin", default=Decimal("0")),
                maintenance_margin=_decimal(
                    payload,
                    "maintenanceMargin",
                    "MaintenanceMargin",
                    default=Decimal("0"),
                ),
                buying_power=_required_decimal(payload, "buyingPower", "BuyingPower"),
                timestamp=_timestamp(payload, self.clock),
            )
        except OptimusBridgeError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerConnectionError(str(exc)) from exc

    def get_positions(self) -> tuple[Position, ...]:
        try:
            payload = self._request("GET", f"{self._account_path()}/positions")
            positions = payload.get("positions", payload.get("Positions", ()))
            if not isinstance(positions, list):
                raise ValueError("positions response was invalid")
            return tuple(_position(position) for position in positions)
        except OptimusBridgeError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerConnectionError(str(exc)) from exc

    def submit_order(self, order: BrokerOrder) -> str:
        try:
            payload = self._request("POST", f"{self._account_path()}/orders", self._order_payload(order))
            broker_order_id = _order_id(payload)
            if broker_order_id is None:
                raise ValueError("Optimus bridge order response did not include an order ID")
            return broker_order_id
        except OptimusBridgeError as exc:
            raise BrokerSubmissionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerSubmissionError(str(exc)) from exc

    def estimate_order_margin(self, order: BrokerOrder) -> MarginEstimate:
        raise MarginEstimateUnavailable(
            "Optimus adapter does not expose broker-provided order margin estimates"
        )

    def cancel_order(self, broker_order_id: str) -> None:
        if not broker_order_id:
            raise ValueError("broker_order_id is required")
        try:
            self._request("POST", f"{self._account_path()}/orders/{quote(broker_order_id, safe='')}/cancel", {})
        except OptimusBridgeError as exc:
            raise BrokerCancellationError(exc.reason, exc.broker_error_code) from exc

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        assert self.transport is not None
        assert self.config.api_url is not None
        payload = self.transport.request(
            method=method,
            url=f"{self.config.api_url}{path}",
            headers={
                "Authorization": self._authorization_header(),
                "Content-Type": "application/json",
                "X-Optimus-App-Name": self.config.app_name,
                "X-Optimus-Route": self.config.route.value,
            },
            body=body,
        )
        return {} if payload is None else payload

    def _account_path(self) -> str:
        return (
            f"/routes/{quote(self.config.route.value, safe='')}"
            f"/accounts/{quote(self.config.account_id, safe='')}"
        )

    def _authorization_header(self) -> str:
        token = f"{self.config.username}:{self.config.password}".encode("utf-8")
        return f"Basic {base64.b64encode(token).decode('ascii')}"

    def _order_payload(self, order: BrokerOrder) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "accountId": self.config.account_id,
            "appName": self.config.app_name,
            "clientOrderId": order.client_order_id,
            "instrument": order.instrument_id,
            "orderType": _order_type(order.order_type),
            "quantity": order.quantity,
            "route": self.config.route.value,
            "side": _side(order.side),
            "timeInForce": "DAY",
        }
        if order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                raise ValueError("limit price is required for Optimus limit orders")
            payload["limitPrice"] = str(order.limit_price)
        return payload


def _extract_error(response_body: str) -> tuple[str, str | None]:
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return response_body.strip() or "Optimus bridge HTTP request failed", None
    if not isinstance(parsed, Mapping):
        return "Optimus bridge HTTP request failed", None

    reason = (
        _optional_text(parsed, "message")
        or _optional_text(parsed, "Message")
        or _optional_text(parsed, "error")
        or _optional_text(parsed, "Error")
        or _optional_text(parsed, "reason")
        or "Optimus bridge HTTP request failed"
    )
    broker_error_code = (
        _optional_text(parsed, "errorCode")
        or _optional_text(parsed, "ErrorCode")
        or _optional_text(parsed, "code")
        or _optional_text(parsed, "Code")
    )
    return reason, broker_error_code


def _account_id(value: Mapping[str, object]) -> str:
    account_id = (
        _optional_text(value, "accountId")
        or _optional_text(value, "account")
        or _optional_text(value, "AccountID")
    )
    if account_id is None:
        raise ValueError("Optimus account response did not include an account ID")
    return account_id


def _position(value: object) -> Position:
    if not isinstance(value, Mapping):
        raise ValueError("position record was invalid")
    return Position(
        instrument_id=_required_text(value, "instrument", "Instrument", "symbol", "Symbol"),
        quantity=int(_required_decimal(value, "quantity", "Quantity")),
        average_price=_decimal(value, "averagePrice", "AveragePrice", "avgPrice", default=Decimal("0")),
    )


def _order_id(payload: Mapping[str, object]) -> str | None:
    return (
        _optional_text(payload, "orderId")
        or _optional_text(payload, "order_id")
        or _optional_text(payload, "OrderID")
    )


def _timestamp(
    value: Mapping[str, object],
    clock: Callable[[], datetime] | None,
) -> datetime:
    timestamp_value = (
        _optional_text(value, "timestamp")
        or _optional_text(value, "Timestamp")
        or _optional_text(value, "time")
    )
    if timestamp_value is None:
        assert clock is not None
        return clock()
    return datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))


def _required_text(value: Mapping[str, object], *names: str) -> str:
    for name in names:
        text = _optional_text(value, name)
        if text is not None:
            return text
    allowed = " or ".join(names)
    raise ValueError(f"{allowed} is required")


def _optional_text(value: object, name: str) -> str | None:
    if not isinstance(value, Mapping):
        return None
    raw_value = value.get(name)
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return text or None


def _required_decimal(value: Mapping[str, object], *names: str) -> Decimal:
    decimal_value = _decimal(value, *names, default=None)
    if decimal_value is None:
        allowed = " or ".join(names)
        raise ValueError(f"{allowed} is required")
    return decimal_value


def _decimal(
    value: Mapping[str, object],
    *names: str,
    default: Decimal | None,
) -> Decimal | None:
    for name in names:
        raw_value = value.get(name)
        if raw_value is not None:
            return Decimal(str(raw_value))
    return default


def _side(side: OrderSide) -> str:
    if side == OrderSide.BUY:
        return "BUY"
    if side == OrderSide.SELL:
        return "SELL"
    raise ValueError(f"unsupported Optimus order side: {side}")


def _order_type(order_type: OrderType) -> str:
    if order_type == OrderType.MARKET:
        return "MARKET"
    if order_type == OrderType.LIMIT:
        return "LIMIT"
    raise ValueError(f"unsupported Optimus order type: {order_type}")
