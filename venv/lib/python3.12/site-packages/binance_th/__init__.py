"""Binance Thailand Python Library.

A production-ready Python async library for Binance Thailand API.
Supports both REST API and WebSocket connections with comprehensive
error handling, rate limiting, and retry mechanisms.

Features:
- Type-safe with Pydantic models
- Async-first architecture
- Comprehensive error handling
- Rate limiting with automatic backoff
- WebSocket support with reconnection

Example:
    >>> from binance_th import BinanceThConfig
    >>> from binance_th.models import OrderSide, OrderType
    >>>
    >>> config = BinanceThConfig(
    ...     api_key="your_api_key",
    ...     api_secret="your_api_secret",
    ... )
    >>>
    >>> # async with BinanceThClient(config) as client:
    >>> #     book = await client.ws.order_book("BTCTHB")
    >>> #     async for trade in client.ws.watch_trades("BTCTHB"):
    >>> #         ...
    >>> #     orders = await client.user_stream.order_tracker()   # self-healing local orders

Note:
    REST clients, WebSocket market streams, and the authenticated user-data stream
    (M1-M6) are available.
"""

from binance_th.client import BinanceThClient
from binance_th.config import BinanceThConfig
from binance_th.exceptions import (
    BinanceThAPIError,
    BinanceThAuthError,
    BinanceThBadRequestError,
    BinanceThError,
    BinanceThIPBannedError,
    BinanceThNetworkError,
    BinanceThOrderUnknownError,
    BinanceThRateLimitError,
    BinanceThServerError,
    BinanceThTimeoutError,
    BinanceThValidationError,
    BinanceThWAFError,
    BinanceThWebSocketError,
)
from binance_th.listenkey import ListenKeyManager, RestListenKeyManager
from binance_th.models import (
    KlineInterval,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from binance_th.orderbook import LocalOrderBook, ManagedOrderBook
from binance_th.ordertracker import LocalOrderView, OrderTracker
from binance_th.stream import StreamClient
from binance_th.userstream import UserDataStream

__version__ = "1.0.0"

__all__ = [
    "BinanceThAPIError",
    "BinanceThAuthError",
    "BinanceThBadRequestError",
    # Client
    "BinanceThClient",
    # Config
    "BinanceThConfig",
    # Exceptions
    "BinanceThError",
    "BinanceThIPBannedError",
    "BinanceThNetworkError",
    "BinanceThOrderUnknownError",
    "BinanceThRateLimitError",
    "BinanceThServerError",
    "BinanceThTimeoutError",
    "BinanceThValidationError",
    "BinanceThWAFError",
    "BinanceThWebSocketError",
    "KlineInterval",
    # User-data stream (M6)
    "ListenKeyManager",
    # WebSocket / order book (M5)
    "LocalOrderBook",
    "LocalOrderView",
    "ManagedOrderBook",
    # Common Enums (for convenience)
    "OrderSide",
    "OrderStatus",
    "OrderTracker",
    "OrderType",
    "RestListenKeyManager",
    "StreamClient",
    "TimeInForce",
    "UserDataStream",
    # Version
    "__version__",
]
