from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from futures_bot.brokers.tradestation.config import TradeStationConfig
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder
from futures_bot.domain.portfolio import AccountSnapshot, Position
from futures_bot.ports.broker import (
    BrokerCancellationError,
    BrokerConnectionError,
    BrokerSubmissionError,
)


class TradeStationHttpError(RuntimeError):
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


class TradeStationTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None = None,
    ) -> Mapping[str, object] | None:
        """Send one TradeStation HTTP request."""


class UrllibTradeStationTransport:
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
            raise TradeStationHttpError(reason, exc.code, broker_error_code) from exc
        except URLError as exc:
            raise TradeStationHttpError(str(exc.reason), None, "NETWORK_ERROR") from exc

        if not response_body.strip():
            return None
        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise TradeStationHttpError("TradeStation response was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise TradeStationHttpError("TradeStation response was not a JSON object")
        return parsed


@dataclass(frozen=True)
class TradeStationBroker:
    config: TradeStationConfig
    transport: TradeStationTransport | None = None
    clock: Callable[[], datetime] | None = None

    def __post_init__(self) -> None:
        if self.transport is None:
            object.__setattr__(self, "transport", UrllibTradeStationTransport())
        if self.clock is None:
            object.__setattr__(self, "clock", lambda: datetime.now(timezone.utc))

    def connect(self) -> None:
        try:
            payload = self._request("GET", "/brokerage/accounts")
        except TradeStationHttpError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc

        accounts = payload.get("Accounts")
        if not isinstance(accounts, list):
            raise BrokerConnectionError("TradeStation accounts response was invalid")
        if not any(_optional_text(account, "AccountID") == self.config.account_id for account in accounts):
            raise BrokerConnectionError("configured TradeStation account was not returned")

    def get_account(self) -> AccountSnapshot:
        try:
            payload = self._request(
                "GET",
                f"/brokerage/accounts/{self.config.account_id}/balances",
            )
            balance = _first_record(payload, "Balances")
            account_id = _required_text(balance, "AccountID")
            if account_id != self.config.account_id:
                raise ValueError("balance account ID did not match configured account")
            return AccountSnapshot(
                account_id=account_id,
                equity=_required_decimal(balance, "Equity", "AccountBalance"),
                initial_margin=_decimal(balance, "InitialMargin", default=Decimal("0")),
                maintenance_margin=_decimal(balance, "MaintenanceMargin", default=Decimal("0")),
                buying_power=_required_decimal(balance, "BuyingPower"),
                timestamp=_timestamp(balance, self.clock),
            )
        except TradeStationHttpError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerConnectionError(str(exc)) from exc

    def get_positions(self) -> tuple[Position, ...]:
        try:
            payload = self._request(
                "GET",
                f"/brokerage/accounts/{self.config.account_id}/positions",
            )
            positions = payload.get("Positions", ())
            if not isinstance(positions, list):
                raise ValueError("positions response was invalid")
            return tuple(self._position(position) for position in positions)
        except TradeStationHttpError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerConnectionError(str(exc)) from exc

    def submit_order(self, order: BrokerOrder) -> str:
        try:
            payload = self._request("POST", "/orderexecution/orders", self._order_payload(order))
            broker_order_id = _order_id(payload)
            if broker_order_id is None:
                raise ValueError("TradeStation order response did not include an order ID")
            return broker_order_id
        except TradeStationHttpError as exc:
            raise BrokerSubmissionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerSubmissionError(str(exc)) from exc

    def cancel_order(self, broker_order_id: str) -> None:
        if not broker_order_id:
            raise ValueError("broker_order_id is required")
        try:
            self._request("DELETE", f"/orderexecution/orders/{broker_order_id}")
        except TradeStationHttpError as exc:
            raise BrokerCancellationError(exc.reason, exc.broker_error_code) from exc

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        assert self.transport is not None
        payload = self.transport.request(
            method=method,
            url=f"{self.config.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.config.access_token}",
                "Content-Type": "application/json",
            },
            body=body,
        )
        return {} if payload is None else payload

    def _order_payload(self, order: BrokerOrder) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "AccountID": self.config.account_id,
            "OrderType": _tradestation_order_type(order.order_type),
            "Quantity": str(order.quantity),
            "Symbol": order.instrument_id,
            "TimeInForce": {"Duration": "DAY"},
            "TradeAction": _tradestation_trade_action(order.side),
        }
        if order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                raise ValueError("limit price is required for TradeStation limit orders")
            payload["LimitPrice"] = str(order.limit_price)
        return payload

    def _position(self, value: object) -> Position:
        if not isinstance(value, Mapping):
            raise ValueError("position record was invalid")
        quantity = int(_required_decimal(value, "Quantity"))
        long_short = _optional_text(value, "LongShort")
        if long_short is not None and long_short.lower() == "short" and quantity > 0:
            quantity = -quantity
        return Position(
            instrument_id=_required_text(value, "Symbol"),
            quantity=quantity,
            average_price=_decimal(value, "AveragePrice", default=Decimal("0")),
        )


def _extract_error(response_body: str) -> tuple[str, str | None]:
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return response_body.strip() or "TradeStation HTTP request failed", None
    if not isinstance(parsed, Mapping):
        return "TradeStation HTTP request failed", None

    reason = (
        _optional_text(parsed, "Message")
        or _optional_text(parsed, "Error")
        or _optional_text(parsed, "Reason")
        or "TradeStation HTTP request failed"
    )
    broker_error_code = _optional_text(parsed, "ErrorCode") or _optional_text(parsed, "Code")
    return reason, broker_error_code


def _first_record(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    values = payload.get(key)
    if isinstance(values, list) and values and isinstance(values[0], Mapping):
        return values[0]
    if isinstance(payload, Mapping):
        return payload
    raise ValueError(f"{key} response was invalid")


def _required_text(value: Mapping[str, object], name: str) -> str:
    text = _optional_text(value, name)
    if text is None:
        raise ValueError(f"{name} is required")
    return text


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


def _timestamp(
    value: Mapping[str, object],
    clock: Callable[[], datetime] | None,
) -> datetime:
    timestamp_value = _optional_text(value, "Timestamp") or _optional_text(value, "TimeStamp")
    if timestamp_value is None:
        assert clock is not None
        return clock()
    return datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))


def _order_id(payload: Mapping[str, object]) -> str | None:
    direct_order_id = _optional_text(payload, "OrderID")
    if direct_order_id is not None:
        return direct_order_id
    orders = payload.get("Orders")
    if isinstance(orders, list) and orders:
        return _optional_text(orders[0], "OrderID")
    return None


def _tradestation_order_type(order_type: OrderType) -> str:
    if order_type == OrderType.MARKET:
        return "Market"
    if order_type == OrderType.LIMIT:
        return "Limit"
    raise ValueError(f"unsupported TradeStation order type: {order_type}")


def _tradestation_trade_action(side: OrderSide) -> str:
    if side == OrderSide.BUY:
        return "BUY"
    if side == OrderSide.SELL:
        return "SELL"
    raise ValueError(f"unsupported TradeStation order side: {side}")
