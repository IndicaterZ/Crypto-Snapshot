"""Public async client entry point (ADR-0015).

:class:`BinanceThClient` owns the :class:`~binance_th.transport.Transport`
lifecycle behind an async context manager, so
``async with BinanceThClient(cfg) as client:`` opens and deterministically
closes the HTTP connection and all WebSocket streams. Alongside the general
endpoints (:meth:`ping`, :meth:`server_time`, :meth:`exchange_info`,
:meth:`symbol_types`), it composes the resource sub-clients ``market``,
``account``, ``wallet``, ``orders`` (REST), ``ws`` (WebSocket market streams and
local order books, M5) and ``user_stream`` (authenticated user-data stream with a
self-healing order tracker, M6).
"""

import asyncio
from types import TracebackType
from typing import Self

from binance_th.account import AccountClient
from binance_th.config import BinanceThConfig
from binance_th.market import MarketClient
from binance_th.models.base import ExchangeInfo, ServerTime, SymbolTypeInfo
from binance_th.orders import OrdersClient
from binance_th.stream import StreamClient
from binance_th.transport import Transport
from binance_th.userstream import UserDataStream
from binance_th.wallet import WalletClient

__all__ = ["BinanceThClient"]

PING_PATH = "/api/v1/ping"
EXCHANGE_INFO_PATH = "/api/v1/exchangeInfo"
SYMBOL_TYPE_PATH = "/api/v1/symbolType"
EXCHANGE_INFO_WEIGHT = 10


class BinanceThClient:
    """Async client for the Binance Thailand API."""

    def __init__(
        self,
        config: BinanceThConfig | None = None,
        *,
        transport: Transport | None = None,
    ) -> None:
        """Build from ``config`` (or env/``.env`` defaults); ``transport`` is injectable for tests."""
        self._config = config or BinanceThConfig()
        self._transport = transport or Transport(self._config)
        self.market = MarketClient(self._transport)
        self.account = AccountClient(self._transport)
        self.wallet = WalletClient(self._transport)
        self.orders = OrdersClient(
            self._transport,
            exchange_info=self.exchange_info,
            execution_rules=self.market.execution_rules,
        )
        self.ws = StreamClient(
            config=self._config,
            depth_provider=self.market.depth,
            symbol_type_provider=self.symbol_types,
        )
        self.user_stream = UserDataStream(
            config=self._config,
            transport=self._transport,
            open_orders_provider=self.orders.open_orders,
        )
        self._exchange_info: ExchangeInfo | None = None
        self._exchange_info_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    @property
    def is_closed(self) -> bool:
        """True once the client has been closed."""
        return self._transport.is_closed

    async def aclose(self) -> None:
        """Close market streams, then the user-data stream, then the transport; idempotent.

        Both stream layers run tasks that call REST on the transport (order-book snapshots;
        the user-data listenKey DELETE + reconciliation), so they are torn down first while
        the transport is still alive (ADR-0015 / ADR-0008).
        """
        await self.ws.aclose()
        await self.user_stream.aclose()
        await self._transport.aclose()

    async def ping(self) -> bool:
        """``GET /api/v1/ping`` — True if the API is reachable.

        The endpoint returns the non-JSON literal ``pong`` (verified 2026-07-09),
        so the body is read as text and never JSON-decoded.
        """
        text = await self._transport.request(
            "GET", PING_PATH, envelope=False, parse_json=False, weight=1
        )
        return isinstance(text, str) and text.strip() == "pong"

    async def server_time(self) -> ServerTime:
        """``GET /api/v1/time`` — server time; also refreshes the signing offset."""
        return await self._transport.sync_time()

    async def exchange_info(self, *, force: bool = False) -> ExchangeInfo:
        """``GET /api/v1/exchangeInfo`` — cached; reseeds the rate limiter on fetch.

        The first call (or ``force=True``) fetches and caches the exchange info and
        adopts its authoritative rate limits into the limiter; later calls return the
        cached instance without a request.
        """
        if self._exchange_info is not None and not force:
            return self._exchange_info
        async with self._exchange_info_lock:
            if self._exchange_info is not None and not force:
                return self._exchange_info
            raw = await self._transport.request(
                "GET", EXCHANGE_INFO_PATH, envelope=False, weight=EXCHANGE_INFO_WEIGHT
            )
            info = ExchangeInfo(**raw)
            self._exchange_info = info
            self._transport.reseed_rate_limits(info.rate_limits)
            return info

    async def symbol_types(self, *, symbol: str | None = None) -> list[SymbolTypeInfo]:
        """``GET /api/v1/symbolType`` — GLOBAL/SITE type per symbol (always an array)."""
        params = {"symbol": symbol} if symbol is not None else {}
        raw = await self._transport.request(
            "GET", SYMBOL_TYPE_PATH, params=params, envelope=False, weight=1
        )
        return [SymbolTypeInfo(**item) for item in raw]
