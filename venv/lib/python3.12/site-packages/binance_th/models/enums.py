"""Enum definitions for Binance Thailand API.

This module defines all enumerations used throughout the library,
including order types, sides, statuses, and intervals.
"""

from enum import Enum, StrEnum


class OrderSide(StrEnum):
    """Order side - buy or sell."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Order types supported by the API.

    - LIMIT: Limit order with specified price
    - MARKET: Market order at best available price
    - STOP_LOSS: Stop loss market order
    - STOP_LOSS_LIMIT: Stop loss limit order
    - TAKE_PROFIT: Take profit market order
    - TAKE_PROFIT_LIMIT: Take profit limit order
    - LIMIT_MAKER: Limit order that will be rejected if it would match immediately
    """

    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"
    LIMIT_MAKER = "LIMIT_MAKER"


class OrderStatus(StrEnum):
    """Order status values.

    - NEW: Order has been accepted
    - PARTIALLY_FILLED: Order partially filled
    - FILLED: Order completely filled
    - CANCELED: Order canceled by user
    - REJECTED: Order rejected (not enough balance, etc.)
    - EXPIRED: Order expired (e.g., FOK not filled)
    """

    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class TimeInForce(StrEnum):
    """Time in force options for orders.

    - GTC: Good Til Canceled - remains until filled or canceled
    - IOC: Immediate Or Cancel - fill immediately or cancel unfilled portion
    - FOK: Fill or Kill - fill completely immediately or cancel entirely
    """

    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class KlineInterval(StrEnum):
    """Kline/candlestick intervals.

    Supported intervals from 1 minute to 1 month.
    """

    MINUTE_1 = "1m"
    MINUTE_3 = "3m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    HOUR_2 = "2h"
    HOUR_4 = "4h"
    HOUR_6 = "6h"
    HOUR_8 = "8h"
    HOUR_12 = "12h"
    DAY_1 = "1d"
    DAY_3 = "3d"
    WEEK_1 = "1w"
    MONTH_1 = "1M"


class SymbolType(StrEnum):
    """Symbol types for Binance Thailand.

    - GLOBAL: Standard symbols available across the platform
    - SITE: Symbols specific to Binance Thailand regional instance
    """

    GLOBAL = "GLOBAL"
    SITE = "SITE"


class SymbolStatus(StrEnum):
    """Trading status for a symbol."""

    TRADING = "TRADING"
    HALT = "HALT"
    BREAK = "BREAK"


class RateLimitType(StrEnum):
    """Rate limit types from exchange info.

    - REQUEST_WEIGHT: Weight-based limit for API requests
    - ORDERS: Limit on number of orders per interval
    - RAW_REQUESTS: Raw request count limit
    """

    REQUEST_WEIGHT = "REQUEST_WEIGHT"
    ORDERS = "ORDERS"
    RAW_REQUESTS = "RAW_REQUESTS"


class RateLimitInterval(StrEnum):
    """Rate limit interval units.

    Intervals used in rate limit configuration.
    """

    SECOND = "SECOND"
    MINUTE = "MINUTE"
    HOUR = "HOUR"
    DAY = "DAY"


class FilterType(StrEnum):
    """Symbol filter types from exchange info.

    Filters define trading rules and constraints for symbols.
    """

    PRICE_FILTER = "PRICE_FILTER"
    PERCENT_PRICE = "PERCENT_PRICE"
    LOT_SIZE = "LOT_SIZE"
    MIN_NOTIONAL = "MIN_NOTIONAL"
    ICEBERG_PARTS = "ICEBERG_PARTS"
    MARKET_LOT_SIZE = "MARKET_LOT_SIZE"
    MAX_NUM_ORDERS = "MAX_NUM_ORDERS"
    MAX_NUM_ALGO_ORDERS = "MAX_NUM_ALGO_ORDERS"
    MAX_NUM_ICEBERG_ORDERS = "MAX_NUM_ICEBERG_ORDERS"
    EXCHANGE_MAX_NUM_ORDERS = "EXCHANGE_MAX_NUM_ORDERS"
    EXCHANGE_MAX_NUM_ALGO_ORDERS = "EXCHANGE_MAX_NUM_ALGO_ORDERS"


class DepositStatus(int, Enum):
    """Deposit status codes.

    Status codes for deposit history records.
    """

    PENDING = 0
    SUCCESS = 1
    CREDITED = 6


class WithdrawStatus(int, Enum):
    """Withdraw status codes.

    Status codes for withdrawal history records.
    """

    EMAIL_SENT = 0
    CANCELLED = 1
    AWAITING_APPROVAL = 2
    REJECTED = 3
    PROCESSING = 4
    FAILURE = 5
    COMPLETED = 6
