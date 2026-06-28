from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from futures_bot.brokers.ibkr.config import IbkrConfig
from futures_bot.domain.enums import OrderSide, OrderType
from futures_bot.domain.orders import BrokerOrder
from futures_bot.domain.portfolio import AccountSnapshot, Position
from futures_bot.ports.broker import (
    BrokerCancellationError,
    BrokerConnectionError,
    BrokerSubmissionError,
)


class IbkrClientError(RuntimeError):
    def __init__(self, reason: str, broker_error_code: str | None = None) -> None:
        if not reason:
            raise ValueError("reason is required")
        super().__init__(reason)
        self.reason = reason
        self.broker_error_code = broker_error_code


class IbkrClientPort(Protocol):
    def connect(self, host: str, port: int, client_id: int) -> None:
        """Connect to TWS or IB Gateway."""

    def account_summary(self) -> tuple[Mapping[str, object], ...]:
        """Return rows from an IBKR account summary request."""

    def positions(self) -> tuple[Mapping[str, object], ...]:
        """Return rows from an IBKR positions request."""

    def next_order_id(self) -> int:
        """Return the next valid IBKR API order ID."""

    def place_order(
        self,
        order_id: int,
        contract: Mapping[str, object],
        order: Mapping[str, object],
    ) -> None:
        """Place an order through TWS or IB Gateway."""

    def cancel_order(self, order_id: int) -> None:
        """Cancel an order through TWS or IB Gateway."""


@dataclass(frozen=True)
class IbkrBroker:
    config: IbkrConfig
    client: IbkrClientPort
    clock: Callable[[], datetime] | None = None

    def __post_init__(self) -> None:
        if self.clock is None:
            object.__setattr__(self, "clock", lambda: datetime.now(timezone.utc))

    def connect(self) -> None:
        try:
            self.client.connect(self.config.host, self.config.port, self.config.client_id)
        except IbkrClientError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc

    def get_account(self) -> AccountSnapshot:
        try:
            rows = self.client.account_summary()
            account_id = _account_id(rows)
            assert self.clock is not None
            return AccountSnapshot(
                account_id=account_id,
                equity=_summary_value(rows, "NetLiquidation"),
                initial_margin=_summary_value(rows, "InitMarginReq"),
                maintenance_margin=_summary_value(rows, "MaintMarginReq"),
                buying_power=_summary_value(rows, "BuyingPower"),
                timestamp=self.clock(),
            )
        except IbkrClientError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerConnectionError(str(exc)) from exc

    def get_positions(self) -> tuple[Position, ...]:
        try:
            return tuple(_position(row) for row in self.client.positions())
        except IbkrClientError as exc:
            raise BrokerConnectionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerConnectionError(str(exc)) from exc

    def submit_order(self, order: BrokerOrder) -> str:
        try:
            order_id = self.client.next_order_id()
            self.client.place_order(
                order_id=order_id,
                contract=_contract(order.instrument_id),
                order=_order(order),
            )
            return str(order_id)
        except IbkrClientError as exc:
            raise BrokerSubmissionError(exc.reason, exc.broker_error_code) from exc
        except ValueError as exc:
            raise BrokerSubmissionError(str(exc)) from exc

    def cancel_order(self, broker_order_id: str) -> None:
        try:
            order_id = int(broker_order_id)
        except ValueError as exc:
            raise ValueError("broker_order_id must be a numeric IBKR order ID") from exc

        try:
            self.client.cancel_order(order_id)
        except IbkrClientError as exc:
            raise BrokerCancellationError(exc.reason, exc.broker_error_code) from exc


def _account_id(rows: tuple[Mapping[str, object], ...]) -> str:
    for row in rows:
        account = _optional_text(row, "account") or _optional_text(row, "Account")
        if account is not None:
            return account
    raise ValueError("IBKR account summary did not include an account ID")


def _summary_value(rows: tuple[Mapping[str, object], ...], tag: str) -> Decimal:
    for row in rows:
        if _optional_text(row, "tag") == tag or _optional_text(row, "Tag") == tag:
            value = _optional_text(row, "value") or _optional_text(row, "Value")
            if value is None:
                raise ValueError(f"IBKR account summary tag {tag} did not include a value")
            return Decimal(value)
    raise ValueError(f"IBKR account summary did not include {tag}")


def _position(row: Mapping[str, object]) -> Position:
    contract = row.get("contract") or row.get("Contract")
    if not isinstance(contract, Mapping):
        raise ValueError("IBKR position row did not include a contract")
    return Position(
        instrument_id=_instrument_id(contract),
        quantity=int(Decimal(_required_text(row, "position", "Position"))),
        average_price=Decimal(_required_text(row, "average_cost", "AverageCost", "avgCost")),
    )


def _instrument_id(contract: Mapping[str, object]) -> str:
    local_symbol = _optional_text(contract, "localSymbol") or _optional_text(contract, "LocalSymbol")
    if local_symbol is not None:
        return local_symbol

    symbol = _required_text(contract, "symbol", "Symbol")
    contract_month = _required_text(
        contract,
        "lastTradeDateOrContractMonth",
        "LastTradeDateOrContractMonth",
    )
    exchange = _required_text(contract, "exchange", "Exchange")
    return f"{symbol}-{contract_month}-{exchange}"


def _contract(instrument_id: str) -> Mapping[str, object]:
    parts = instrument_id.split("-")
    if len(parts) != 3 or not all(parts):
        raise ValueError("IBKR futures instrument ID must use SYMBOL-YYYYMM-EXCHANGE")
    symbol, contract_month, exchange = parts
    return {
        "currency": "USD",
        "exchange": exchange,
        "lastTradeDateOrContractMonth": contract_month,
        "secType": "FUT",
        "symbol": symbol,
    }


def _order(order: BrokerOrder) -> Mapping[str, object]:
    payload: dict[str, object] = {
        "action": _action(order.side),
        "orderRef": order.client_order_id,
        "orderType": _order_type(order.order_type),
        "tif": "DAY",
        "totalQuantity": order.quantity,
    }
    if order.order_type == OrderType.LIMIT:
        if order.limit_price is None:
            raise ValueError("limit price is required for IBKR limit orders")
        payload["lmtPrice"] = str(order.limit_price)
    return payload


def _action(side: OrderSide) -> str:
    if side == OrderSide.BUY:
        return "BUY"
    if side == OrderSide.SELL:
        return "SELL"
    raise ValueError(f"unsupported IBKR order side: {side}")


def _order_type(order_type: OrderType) -> str:
    if order_type == OrderType.MARKET:
        return "MKT"
    if order_type == OrderType.LIMIT:
        return "LMT"
    raise ValueError(f"unsupported IBKR order type: {order_type}")


def _required_text(value: Mapping[str, object], *names: str) -> str:
    for name in names:
        text = _optional_text(value, name)
        if text is not None:
            return text
    allowed = " or ".join(names)
    raise ValueError(f"{allowed} is required")


def _optional_text(value: Mapping[str, object], name: str) -> str | None:
    raw_value = value.get(name)
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return text or None
