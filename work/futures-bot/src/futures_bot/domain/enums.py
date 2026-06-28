from enum import StrEnum


class SettlementType(StrEnum):
    CASH = "cash"
    PHYSICAL = "physical"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
