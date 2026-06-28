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


class RiskReason(StrEnum):
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    UNRECONCILED_POSITIONS = "unreconciled_positions"
    STALE_ACCOUNT = "stale_account"
    STALE_MARKET_DATA = "stale_market_data"
    MAX_ORDER_QUANTITY = "max_order_quantity"
    MAX_POSITION = "max_position"
    MAX_MARGIN_USAGE = "max_margin_usage"
    CONTRACT_NOT_TRADABLE = "contract_not_tradable"
    DUPLICATE_CLIENT_ORDER_ID = "duplicate_client_order_id"
    PRICE_COLLAR = "price_collar"
