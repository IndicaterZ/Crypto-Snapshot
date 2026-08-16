"""Pydantic models for Binance Thailand API.

This module exports all model classes used for API requests and responses.

Model Categories:
- Enums: Order types, sides, statuses, intervals
- Base: Common response/request models, exchange info
- Market: Order book, trades, klines, tickers
- Account: Balances, deposits, withdrawals, user data
- Orders: Order creation, querying, cancellation

Example:
    >>> from binance_th.models import OrderSide, OrderType, Order
    >>> from binance_th.models import Ticker24hr, OrderBook
"""

from binance_th.models.account import (
    AccountInfo,
    Balance,
    DepositAddress,
    DepositRecord,
    ListenKey,
    SubAccountTransfer,
    TradeFee,
    UserTrade,
    WithdrawRecord,
    WithdrawResult,
)
from binance_th.models.base import (
    ExchangeInfo,
    RateLimit,
    RequestModel,
    ResponseModel,
    ServerTime,
    SymbolFilter,
    SymbolInfo,
    SymbolTypeInfo,
)
from binance_th.models.enums import (
    DepositStatus,
    FilterType,
    KlineInterval,
    OrderSide,
    OrderStatus,
    OrderType,
    RateLimitInterval,
    RateLimitType,
    SymbolStatus,
    SymbolType,
    TimeInForce,
    WithdrawStatus,
)
from binance_th.models.market import (
    AggregateTrade,
    BookTicker,
    ExecutionRule,
    ExecutionRules,
    Kline,
    OrderBook,
    OrderBookEntry,
    PriceTicker,
    ReferencePrice,
    SymbolExecutionRules,
    Ticker24hr,
    Trade,
)
from binance_th.models.orders import (
    CancelOrderRequest,
    Order,
    OrderRequest,
    QueryOrderRequest,
)
from binance_th.models.stream import (
    AggTradeEvent,
    BookTickerEvent,
    DepthUpdateEvent,
    KlineData,
    KlineEvent,
    StreamMessage,
    TickerEvent,
    TradeEvent,
)
from binance_th.models.userdata import (
    AccountBalanceDelta,
    BalanceUpdateEvent,
    ExecutionReportEvent,
    ListenKeyExpiredEvent,
    OutboundAccountPositionEvent,
    order_from_execution_report,
)

__all__ = [
    "AccountBalanceDelta",
    "AccountInfo",
    "AggTradeEvent",
    "AggregateTrade",
    # Account models
    "Balance",
    "BalanceUpdateEvent",
    "BookTicker",
    "BookTickerEvent",
    "CancelOrderRequest",
    "DepositAddress",
    "DepositRecord",
    "DepositStatus",
    "DepthUpdateEvent",
    "ExchangeInfo",
    "ExecutionReportEvent",
    "ExecutionRule",
    "ExecutionRules",
    "FilterType",
    "Kline",
    "KlineData",
    "KlineEvent",
    "KlineInterval",
    "ListenKey",
    "ListenKeyExpiredEvent",
    # Order models
    "Order",
    "OrderBook",
    # Market models
    "OrderBookEntry",
    "OrderRequest",
    # Enums
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "OutboundAccountPositionEvent",
    "PriceTicker",
    "QueryOrderRequest",
    "RateLimit",
    "RateLimitInterval",
    "RateLimitType",
    "ReferencePrice",
    "RequestModel",
    # Base models
    "ResponseModel",
    "ServerTime",
    "StreamMessage",
    "SubAccountTransfer",
    "SymbolExecutionRules",
    "SymbolFilter",
    "SymbolInfo",
    "SymbolStatus",
    "SymbolType",
    "SymbolTypeInfo",
    "Ticker24hr",
    "TickerEvent",
    "TimeInForce",
    "Trade",
    "TradeEvent",
    "TradeFee",
    "UserTrade",
    "WithdrawRecord",
    "WithdrawResult",
    "WithdrawStatus",
    "order_from_execution_report",
]
