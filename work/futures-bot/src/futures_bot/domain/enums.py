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
    INSTRUMENT_MISMATCH = "instrument_mismatch"
    MARKET_NOT_TWO_SIDED = "market_not_two_sided"
    CROSSED_MARKET = "crossed_market"
    WIDE_BID_ASK_SPREAD = "wide_bid_ask_spread"
    ORDER_RATE_LIMIT = "order_rate_limit"
    POTENTIAL_SELF_MATCH = "potential_self_match"
    MAX_ORDER_QUANTITY = "max_order_quantity"
    MAX_ORDER_NOTIONAL = "max_order_notional"
    MAX_POSITION = "max_position"
    MAX_POSITION_NOTIONAL = "max_position_notional"
    MAX_MARGIN_USAGE = "max_margin_usage"
    MAX_MAINTENANCE_MARGIN_USAGE = "max_maintenance_margin_usage"
    INSUFFICIENT_BUYING_POWER = "insufficient_buying_power"
    MAX_DAILY_LOSS = "max_daily_loss"
    CONTRACT_NOT_TRADABLE = "contract_not_tradable"
    DUPLICATE_CLIENT_ORDER_ID = "duplicate_client_order_id"
    PRICE_COLLAR = "price_collar"
    INVALID_TICK_PRICE = "invalid_tick_price"
