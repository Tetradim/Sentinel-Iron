from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from futures_bot.application.margin_estimates import MarginEstimateUnavailable
from futures_bot.application.rebalance_risk_context import MarginEstimate
from futures_bot.brokers.tradovate.config import TradovateConfig
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder
from futures_bot.domain.portfolio import AccountSnapshot, Position
from futures_bot.ports.broker import (
    BrokerCancellationError,
    BrokerConnectionError,
    BrokerSubmissionError,
)
from futures_bot.ports.market_data import HistoricalBar, MarketDataError


class TradovateHttpError(RuntimeError):
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


class TradovateTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None = None,
    ) -> object | None:
        """Send one Tradovate HTTP request."""


class UrllibTradovateTransport:
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None = None,
    ) -> object | None:
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
            raise TradovateHttpError(reason, exc.code, broker_error_code) from exc
        except URLError as exc:
            raise TradovateHttpError(str(exc.reason), None, "NETWORK_ERROR") from exc

        if not response_body.strip():
            return None
        try:
            return json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise TradovateHttpError("Tradovate response was not valid JSON") from exc


@dataclass(frozen=True)
class TradovateBroker:
    config: TradovateConfig
    transport: TradovateTransport | None = None
    clock: Callable[[], datetime] | None = None

    def __post_init__(self) -> None:
        if self.transport is None:
            object.__setattr__(self, "transport", UrllibTradovateTransport())
        if self.clock is None:
            object.__setattr__(self, "clock", lambda: datetime.now(timezone.utc))

    def connect(self) -> None:
        try:
            accounts = _records(self._request("GET", "/account/list"), "accounts")
        except TradovateHttpError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerConnectionError(str(exc)) from exc

        if not any(self._matches_configured_account(account) for account in accounts):
            raise BrokerConnectionError("configured Tradovate account was not returned")

    def get_account(self) -> AccountSnapshot:
        try:
            balances = _records(self._request("GET", "/cashBalance/list"), "cashBalances")
            balance = self._configured_record(balances, "cash balance")
            return AccountSnapshot(
                account_id=str(self.config.account_id),
                equity=_required_decimal(
                    balance,
                    "netLiq",
                    "netLiquidation",
                    "totalCashValue",
                    "cashBalance",
                ),
                initial_margin=_decimal(
                    balance,
                    "initialMargin",
                    "initialMarginReq",
                    default=Decimal("0"),
                ),
                maintenance_margin=_decimal(
                    balance,
                    "maintenanceMargin",
                    "maintenanceMarginReq",
                    default=Decimal("0"),
                ),
                buying_power=_required_decimal(
                    balance,
                    "riskExcess",
                    "availableFunds",
                    "buyingPower",
                    "cashBalance",
                ),
                timestamp=_timestamp(balance, self.clock),
            )
        except TradovateHttpError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerConnectionError(str(exc)) from exc

    def get_positions(self) -> tuple[Position, ...]:
        try:
            records = _records(self._request("GET", "/position/list"), "positions")
            return tuple(
                _position(position)
                for position in records
                if _optional_int(position, "accountId") == self.config.account_id
            )
        except TradovateHttpError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerConnectionError(str(exc)) from exc

    def submit_order(self, order: BrokerOrder) -> str:
        try:
            payload = self._request("POST", "/order/placeorder", self._order_payload(order))
            broker_order_id = _order_id(payload)
            if broker_order_id is None:
                raise ValueError("Tradovate order response did not include an order ID")
            return broker_order_id
        except TradovateHttpError as exc:
            raise BrokerSubmissionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerSubmissionError(str(exc)) from exc

    def estimate_order_margin(self, order: BrokerOrder) -> MarginEstimate:
        raise MarginEstimateUnavailable(
            "Tradovate adapter does not expose verified order margin estimates"
        )

    def get_daily_bars(
        self,
        instrument_id: str,
        start_day: date,
        end_day: date,
    ) -> tuple[HistoricalBar, ...]:
        raise MarketDataError(
            "Tradovate adapter does not expose verified historical daily bars"
        )

    def cancel_order(self, broker_order_id: str) -> None:
        if not broker_order_id:
            raise ValueError("broker_order_id is required")
        try:
            self._request("POST", "/order/cancelorder", self._cancel_payload(broker_order_id))
        except TradovateHttpError as exc:
            raise BrokerCancellationError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerCancellationError(str(exc)) from exc

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
    ) -> object | None:
        assert self.transport is not None
        return self.transport.request(
            method=method,
            url=f"{self.config.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.config.access_token}",
                "Content-Type": "application/json",
            },
            body=body,
        )

    def _matches_configured_account(self, value: Mapping[str, object]) -> bool:
        if _optional_int(value, "id") != self.config.account_id:
            return False
        account_spec = _optional_text(value, "name") or _optional_text(value, "accountSpec")
        return account_spec is None or account_spec == self.config.account_spec

    def _configured_record(
        self,
        records: tuple[Mapping[str, object], ...],
        label: str,
    ) -> Mapping[str, object]:
        for record in records:
            if _optional_int(record, "accountId", "accountID", "id") == self.config.account_id:
                return record
        raise ValueError(f"configured Tradovate {label} was not returned")

    def _order_payload(self, order: BrokerOrder) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "accountId": self.config.account_id,
            "accountSpec": self.config.account_spec,
            "action": _action(order.side),
            "clOrdId": order.client_order_id,
            "isAutomated": True,
            "orderQty": order.quantity,
            "orderType": _order_type(order.order_type),
            "symbol": order.instrument_id,
            "timeInForce": "Day",
        }
        if order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                raise ValueError("limit price is required for Tradovate limit orders")
            payload["price"] = str(order.limit_price)
        return payload

    def _cancel_payload(self, broker_order_id: str) -> Mapping[str, object]:
        return {
            "accountId": self.config.account_id,
            "accountSpec": self.config.account_spec,
            "orderId": _parse_order_id(broker_order_id),
        }


def _extract_error(response_body: str) -> tuple[str, str | None]:
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return response_body.strip() or "Tradovate HTTP request failed", None
    if not isinstance(parsed, Mapping):
        return "Tradovate HTTP request failed", None

    reason = (
        _optional_text(parsed, "message")
        or _optional_text(parsed, "Message")
        or _optional_text(parsed, "errorText")
        or _optional_text(parsed, "error")
        or _optional_text(parsed, "Error")
        or _optional_text(parsed, "reason")
        or "Tradovate HTTP request failed"
    )
    broker_error_code = (
        _optional_text(parsed, "errorCode")
        or _optional_text(parsed, "ErrorCode")
        or _optional_text(parsed, "code")
        or _optional_text(parsed, "Code")
    )
    return reason, broker_error_code


def _records(value: object | None, wrapper_key: str) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        records = value
    elif isinstance(value, Mapping):
        wrapped = value.get(wrapper_key)
        records = wrapped if isinstance(wrapped, list) else [value]
    else:
        raise ValueError("Tradovate response was invalid")

    parsed_records: list[Mapping[str, object]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Tradovate response record was invalid")
        parsed_records.append(record)
    return tuple(parsed_records)


def _position(value: Mapping[str, object]) -> Position:
    return Position(
        instrument_id=_required_text(value, "contractName", "symbol", "instrument", "contractId"),
        quantity=int(_required_decimal(value, "netPos", "netPosition", "quantity")),
        average_price=_decimal(value, "netPrice", "averagePrice", "avgPrice", default=Decimal("0")),
    )


def _order_id(value: object | None) -> str | None:
    if isinstance(value, Mapping):
        order_id = (
            _optional_text(value, "orderId")
            or _optional_text(value, "id")
            or _optional_nested_text(value, "order", "id")
            or _optional_nested_text(value, "order", "orderId")
        )
        return order_id
    return None


def _parse_order_id(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _action(side: OrderSide) -> str:
    if side == OrderSide.BUY:
        return "Buy"
    if side == OrderSide.SELL:
        return "Sell"
    raise ValueError(f"unsupported order side: {side}")


def _order_type(order_type: OrderType) -> str:
    if order_type == OrderType.MARKET:
        return "Market"
    if order_type == OrderType.LIMIT:
        return "Limit"
    raise ValueError(f"unsupported order type: {order_type}")


def _required_text(value: Mapping[str, object], *names: str) -> str:
    text = _optional_text(value, *names)
    if text is None:
        label = " or ".join(names)
        raise ValueError(f"{label} is required")
    return text


def _optional_text(value: Mapping[str, object], *names: str) -> str | None:
    for name in names:
        raw_value = value.get(name)
        if raw_value is None:
            continue
        if isinstance(raw_value, str):
            if not raw_value:
                continue
            return raw_value
        return str(raw_value)
    return None


def _optional_nested_text(
    value: Mapping[str, object],
    parent_key: str,
    child_key: str,
) -> str | None:
    nested = value.get(parent_key)
    if not isinstance(nested, Mapping):
        return None
    return _optional_text(nested, child_key)


def _optional_int(value: Mapping[str, object], *names: str) -> int | None:
    text = _optional_text(value, *names)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError as exc:
        label = " or ".join(names)
        raise ValueError(f"{label} must be an integer") from exc


def _required_decimal(value: Mapping[str, object], *names: str) -> Decimal:
    decimal = _optional_decimal(value, *names)
    if decimal is None:
        label = " or ".join(names)
        raise ValueError(f"{label} is required")
    return decimal


def _decimal(value: Mapping[str, object], *names: str, default: Decimal) -> Decimal:
    decimal = _optional_decimal(value, *names)
    return default if decimal is None else decimal


def _optional_decimal(value: Mapping[str, object], *names: str) -> Decimal | None:
    text = _optional_text(value, *names)
    if text is None:
        return None
    try:
        return Decimal(text)
    except Exception as exc:
        label = " or ".join(names)
        raise ValueError(f"{label} must be numeric") from exc


def _timestamp(
    value: Mapping[str, object],
    clock: Callable[[], datetime] | None,
) -> datetime:
    text = _optional_text(value, "timestamp", "Timestamp", "updatedAt")
    if text is None:
        assert clock is not None
        return clock()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
