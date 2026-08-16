"""Public market-data resource client (M3a).

Every Binance TH market/system endpoint returns a BARE body (verified 2026-07-09),
so all calls pass ``envelope=False``. Exposed as ``BinanceThClient.market``. Weights
are best-effort (⚠ ASSUMED, ADR-0005) and self-correct via header reconciliation.
"""

from collections.abc import AsyncIterator
from typing import Any

from binance_th.models.enums import KlineInterval
from binance_th.models.market import (
    AggregateTrade,
    BookTicker,
    ExecutionRules,
    Kline,
    OrderBook,
    PriceTicker,
    ReferencePrice,
    Ticker24hr,
    Trade,
)
from binance_th.pagination import iter_time_windows
from binance_th.transport import Transport

__all__ = ["MarketClient"]

_DEPTH_PATH = "/api/v1/depth"
_TRADES_PATH = "/api/v1/trades"
_AGG_TRADES_PATH = "/api/v1/aggTrades"
_KLINES_PATH = "/api/v1/klines"
_TICKER_24HR_PATH = "/api/v1/ticker/24hr"
_TICKER_PRICE_PATH = "/api/v1/ticker/price"
_BOOK_TICKER_PATH = "/api/v1/ticker/bookTicker"
_REFERENCE_PRICE_PATH = "/api/v1/referencePrice"
_EXECUTION_RULES_PATH = "/api/v1/executionRules"


def _depth_weight(limit: int | None) -> int:
    """Best-effort depth weight by limit (ASSUMED; header-reconciled)."""
    if limit is None or limit <= 100:
        return 1
    if limit <= 500:
        return 5
    if limit <= 1000:
        return 10
    return 50


class MarketClient:
    """Public market-data endpoints (bare responses)."""

    def __init__(self, transport: Transport) -> None:
        """Hold the shared transport owned by :class:`BinanceThClient`."""
        self._transport = transport

    async def depth(self, symbol: str, *, limit: int | None = None) -> OrderBook:
        """``GET /api/v1/depth`` — the order book for a symbol."""
        params: dict[str, Any] = {"symbol": symbol}
        if limit is not None:
            params["limit"] = limit
        raw = await self._transport.request(
            "GET", _DEPTH_PATH, params=params, envelope=False, weight=_depth_weight(limit)
        )
        return OrderBook.from_api(raw)

    async def trades(self, symbol: str, *, limit: int | None = None) -> list[Trade]:
        """``GET /api/v1/trades`` — recent trades."""
        params: dict[str, Any] = {"symbol": symbol}
        if limit is not None:
            params["limit"] = limit
        raw = await self._transport.request(
            "GET", _TRADES_PATH, params=params, envelope=False, weight=1
        )
        return [Trade(**item) for item in raw]

    async def agg_trades(self, symbol: str, *, limit: int | None = None) -> list[AggregateTrade]:
        """``GET /api/v1/aggTrades`` — compressed aggregate trades."""
        params: dict[str, Any] = {"symbol": symbol}
        if limit is not None:
            params["limit"] = limit
        raw = await self._transport.request(
            "GET", _AGG_TRADES_PATH, params=params, envelope=False, weight=1
        )
        return [AggregateTrade(**item) for item in raw]

    async def klines(
        self,
        symbol: str,
        interval: KlineInterval | str,
        *,
        limit: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[Kline]:
        """``GET /api/v1/klines`` — candlesticks (supports ``startTime``/``endTime``)."""
        params: dict[str, Any] = {"symbol": symbol, "interval": str(interval)}
        if limit is not None:
            params["limit"] = limit
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        raw = await self._transport.request(
            "GET", _KLINES_PATH, params=params, envelope=False, weight=1
        )
        return [Kline.from_list(item) for item in raw]

    async def ticker_24hr(self, symbol: str) -> Ticker24hr:
        """``GET /api/v1/ticker/24hr`` — 24-hour rolling statistics."""
        raw = await self._transport.request(
            "GET", _TICKER_24HR_PATH, params={"symbol": symbol}, envelope=False, weight=1
        )
        return Ticker24hr(**raw)

    async def ticker_price(self, symbol: str) -> PriceTicker:
        """``GET /api/v1/ticker/price`` — latest price."""
        raw = await self._transport.request(
            "GET", _TICKER_PRICE_PATH, params={"symbol": symbol}, envelope=False, weight=1
        )
        return PriceTicker(**raw)

    async def book_ticker(self, symbol: str) -> BookTicker:
        """``GET /api/v1/ticker/bookTicker`` — best bid/ask."""
        raw = await self._transport.request(
            "GET", _BOOK_TICKER_PATH, params={"symbol": symbol}, envelope=False, weight=1
        )
        return BookTicker(**raw)

    async def reference_price(self, symbol: str) -> ReferencePrice:
        """``GET /api/v1/referencePrice`` — TH reference price (GLOBAL symbols only).

        SITE/THB symbols return HTTP 400, surfaced as ``BinanceThBadRequestError``.
        """
        raw = await self._transport.request(
            "GET", _REFERENCE_PRICE_PATH, params={"symbol": symbol}, envelope=False, weight=1
        )
        return ReferencePrice(**raw)

    async def execution_rules(self) -> ExecutionRules:
        """``GET /api/v1/executionRules`` — TH PRICE_RANGE rules (GLOBAL symbols only)."""
        raw = await self._transport.request("GET", _EXECUTION_RULES_PATH, envelope=False, weight=2)
        return ExecutionRules(**raw)

    async def iter_klines(
        self,
        symbol: str,
        interval: KlineInterval | str,
        *,
        start_time: int,
        end_time: int,
        limit: int = 1000,
    ) -> AsyncIterator[Kline]:
        """Iterate candlesticks across ``[start_time, end_time)``, paginating + de-duping."""

        async def fetch(window_start: int, window_end: int) -> list[Kline]:
            return await self.klines(
                symbol, interval, start_time=window_start, end_time=window_end, limit=limit
            )

        async for kline in iter_time_windows(
            fetch,
            start_time=start_time,
            end_time=end_time,
            page_limit=limit,
            window_key=lambda kline: kline.open_time,
        ):
            yield kline
