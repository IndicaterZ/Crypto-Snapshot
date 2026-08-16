"""WebSocket market-stream client, router, and connection supervisor (M5).

Verified topology (``scripts/probe_ws.py``, 2026-07-09): GLOBAL symbols stream from
``ws_base_url_global`` (``/gstream``), SITE symbols from ``ws_base_url_site``
(``/nstream``), each delivering a combined ``{"stream": ..., "data": ...}`` envelope.
Because the two symbol types live on **different hosts**, a client watching both
holds one multiplexed connection per host (:class:`_Connection`, keyed by host in
:class:`StreamClient`).

Design (ADR-0014/0015):

- The ``connect`` callable is an injectable seam (:data:`ConnectFactory`); the only
  ``websockets`` import lives in :func:`_default_connect`.
- :class:`StreamRouter` turns the symbol ``type`` into a host and builds the combined
  ``?streams=`` URL from config **data** — no hardcoded hosts, no call-site string joins.
- Each :class:`_Connection` runs one supervisor task that owns a child reader task
  (``async for`` → JSON → demux by stream name → per-subscription queue) and a proactive
  pre-24h reconnect (a planned reconnect, not an error). Keepalive is delegated to the
  ``websockets`` library via ``ws_ping_interval`` / ``ws_ping_timeout``.
- Backpressure: :class:`_Subscription` offers are non-blocking with a drop-oldest ring,
  so one slow consumer never stalls the shared reader. Subscriptions are ref-counted.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from binance_th.exceptions import BinanceThWebSocketError
from binance_th.models.enums import SymbolType
from binance_th.models.stream import (
    AggTradeEvent,
    BookTickerEvent,
    DepthUpdateEvent,
    KlineEvent,
    TickerEvent,
    TradeEvent,
)
from binance_th.orderbook import ManagedOrderBook

if TYPE_CHECKING:
    from binance_th.config import BinanceThConfig
    from binance_th.models.base import SymbolTypeInfo
    from binance_th.orderbook import DepthProvider

# Proactive reconnect margin: reconnect well before the exchange's ~24h force-close.
_DEFAULT_SESSION_TTL = 23.5 * 3600.0  # seconds (ADR-0015; ⚠ ASSUMED cap, verify)
_QUEUE_MAXSIZE = 1024

SymbolTypeProvider = Callable[..., Awaitable["list[SymbolTypeInfo]"]]

# Sentinels pushed into a subscription queue to end / fault its async iterator.
_CLOSED = object()


@dataclass(frozen=True)
class _StreamError:
    exc: BaseException


class WsConnection(Protocol):
    """Structural type for a live WebSocket connection (subset used here)."""

    async def send(self, message: str) -> None: ...
    async def close(self) -> None: ...
    def __aiter__(self) -> AsyncIterator[str | bytes]: ...


class ConnectFactory(Protocol):
    """Injectable ``connect`` seam; :func:`_default_connect` is the production impl."""

    async def __call__(
        self, url: str, *, ping_interval: float, ping_timeout: float
    ) -> WsConnection: ...


async def _default_connect(
    url: str, *, ping_interval: float, ping_timeout: float
) -> WsConnection:  # pragma: no cover - exercised only against the live server
    from websockets.asyncio.client import connect

    return await connect(url, ping_interval=ping_interval, ping_timeout=ping_timeout)


class _Backoff:
    """Deterministic capped exponential backoff (no jitter → testable)."""

    def __init__(self, base: float = 0.5, cap: float = 30.0) -> None:
        self._base = base
        self._cap = cap
        self._n = 0

    def next(self) -> float:
        delay: float = min(self._base * (2**self._n), self._cap)
        self._n += 1
        return delay

    def reset(self) -> None:
        self._n = 0


class StreamRouter:
    """Resolves a symbol to its host + stream name, and builds combined URLs (ADR-0014)."""

    def __init__(
        self, *, config: BinanceThConfig, symbol_type_provider: SymbolTypeProvider
    ) -> None:
        self._config = config
        self._symbol_type = symbol_type_provider
        self._type_cache: dict[str, SymbolType] = {}

    async def host_for(self, symbol: str) -> str:
        """Verified route: GLOBAL → ``ws_base_url_global``, SITE → ``ws_base_url_site``."""
        stype = await self._resolve_type(symbol)
        if stype is SymbolType.GLOBAL:
            return self._config.ws_base_url_global
        return self._config.ws_base_url_site

    async def _resolve_type(self, symbol: str) -> SymbolType:
        key = symbol.upper()
        cached = self._type_cache.get(key)
        if cached is not None:
            return cached
        infos = await self._symbol_type(symbol=symbol)
        match = next((i for i in infos if i.symbol.upper() == key), infos[0] if infos else None)
        # SymbolTypeInfo.symbol_type is a raw str; default to SITE on an unknown value.
        stype = SymbolType.SITE
        if match is not None:
            with contextlib.suppress(ValueError):
                stype = SymbolType(match.symbol_type)
        self._type_cache[key] = stype
        return stype

    @staticmethod
    def stream_name(symbol: str, channel: str, *, interval: str | None = None) -> str:
        suffix = channel if interval is None else f"{channel}_{interval}"
        return f"{symbol.lower()}@{suffix}"

    @staticmethod
    def combined_url(host: str, streams: Iterable[str]) -> str:
        return f"{host}?streams={'/'.join(sorted(streams))}"

    @staticmethod
    def subscribe_frame(streams: list[str], *, request_id: int, method: str) -> str:
        return json.dumps({"method": method, "params": streams, "id": request_id})


class _Subscription:
    """One consumer's view of a stream: a bounded, drop-oldest queue + async iterator."""

    def __init__(self, stream: str, *, maxsize: int = _QUEUE_MAXSIZE) -> None:
        self.stream = stream
        self.lagged = 0
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=maxsize)

    def offer(self, payload: object) -> None:
        """Non-blocking enqueue; on a full queue drop the oldest item (never stalls the reader)."""
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            self._queue.put_nowait(payload)
            self.lagged += 1

    def fault(self, exc: BaseException) -> None:
        self.offer(_StreamError(exc))

    def close(self) -> None:
        self.offer(_CLOSED)

    def __aiter__(self) -> _Subscription:
        return self

    async def __anext__(self) -> object:
        item = await self._queue.get()
        if item is _CLOSED:
            raise StopAsyncIteration
        if isinstance(item, _StreamError):
            raise item.exc
        return item


class _Connection:
    """One multiplexed WebSocket to a single host, with supervised reconnect."""

    def __init__(
        self,
        *,
        host: str,
        router: StreamRouter,
        config: BinanceThConfig,
        connect: ConnectFactory,
        sleep: Callable[[float], Awaitable[None]],
        session_ttl: float,
    ) -> None:
        self._host = host
        self._router = router
        self._config = config
        self._connect = connect
        self._sleep = sleep
        self._session_ttl = session_ttl
        self.desired: set[str] = set()
        self._subs: dict[str, list[_Subscription]] = {}
        self._ws: WsConnection | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._closing = False
        self._planned = False
        self._req_id = 0

    async def subscribe(self, stream: str) -> _Subscription:
        sub = _Subscription(stream)
        first = stream not in self._subs
        self._subs.setdefault(stream, []).append(sub)
        self.desired.add(stream)
        if self._supervisor is None:
            self._supervisor = asyncio.create_task(
                self._run_supervisor(), name=f"ws-supervisor-{self._host}"
            )
        elif first:
            await self._apply_stream(stream, method="SUBSCRIBE")
        return sub

    async def unsubscribe(self, sub: _Subscription) -> None:
        subs = self._subs.get(sub.stream)
        if subs is not None and sub in subs:
            subs.remove(sub)
        sub.close()
        if subs is not None and not subs:
            self._subs.pop(sub.stream, None)
            self.desired.discard(sub.stream)
            await self._apply_stream(sub.stream, method="UNSUBSCRIBE")

    async def _apply_stream(self, stream: str, *, method: str) -> None:
        """Push a dynamic (un)subscribe to the live socket, or reconnect to rebuild the URL."""
        ws = self._ws
        if ws is None:
            return  # not connected yet; the (re)connect URL already encodes `desired`
        if self._config.ws_supports_live_subscribe:
            self._req_id += 1
            frame = self._router.subscribe_frame([stream], request_id=self._req_id, method=method)
            with contextlib.suppress(Exception):
                await ws.send(frame)
        elif self.desired:
            self._planned = True  # force a planned reconnect that rebuilds the ?streams= URL
            with contextlib.suppress(Exception):
                await ws.close()

    def _dispatch(self, raw: str | bytes) -> None:
        try:
            frame = json.loads(raw)
        except (ValueError, TypeError):
            return  # malformed frame — skip, keep the socket healthy
        if not isinstance(frame, dict) or "stream" not in frame or "data" not in frame:
            return  # control ack or unrecognized shape
        for sub in self._subs.get(frame["stream"], ()):
            sub.offer(frame["data"])

    async def _read_loop(self, ws: WsConnection) -> None:
        # suppress connection-closed / decode errors (not CancelledError); the supervisor reconnects
        with contextlib.suppress(Exception):
            async for raw in ws:
                self._dispatch(raw)

    async def _run_supervisor(self) -> None:
        backoff = _Backoff()
        reader: asyncio.Task[None] | None = None
        try:
            while not self._closing:
                url = self._router.combined_url(self._host, self.desired)
                try:
                    ws = await self._connect(
                        url,
                        ping_interval=float(self._config.ws_ping_interval),
                        ping_timeout=float(self._config.ws_ping_timeout),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # any connect failure funnels to reconnect/fail
                    if not self._config.ws_auto_reconnect or self._closing:
                        self._fault_all(BinanceThWebSocketError(f"WebSocket connect failed: {exc}"))
                        return
                    await self._sleep(backoff.next())
                    continue

                self._ws = ws
                backoff.reset()
                reader = asyncio.create_task(self._read_loop(ws))
                _, pending = await asyncio.wait({reader}, timeout=self._session_ttl)
                timed_out = reader in pending

                if not reader.done():
                    reader.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await reader
                reader = None
                with contextlib.suppress(Exception):
                    await ws.close()
                self._ws = None

                if self._closing:
                    break
                if timed_out or self._planned:  # planned reconnect — not an error
                    self._planned = False
                    continue
                if not self._config.ws_auto_reconnect:
                    self._fault_all(BinanceThWebSocketError("WebSocket disconnected"))
                    return
                await self._sleep(backoff.next())
        finally:
            if reader is not None and not reader.done():
                reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader

    def _fault_all(self, exc: BaseException) -> None:
        for subs in self._subs.values():
            for sub in subs:
                sub.fault(exc)

    async def aclose(self) -> None:
        """Stop the supervisor, close the socket, and end every subscriber; idempotent."""
        self._closing = True
        supervisor = self._supervisor
        self._supervisor = None
        if supervisor is not None:
            supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await supervisor
        ws = self._ws
        self._ws = None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
        for subs in self._subs.values():
            for sub in subs:
                sub.close()
        self._subs.clear()
        self.desired.clear()


class StreamClient:
    """Public WebSocket market-stream client (``client.ws``).

    High-level async-iterator helpers (:meth:`watch_depth`, :meth:`watch_trades`, …) plus
    a self-syncing :meth:`order_book`. Holds one multiplexed connection per host and tears
    them all down on :meth:`aclose` (driven by ``BinanceThClient``'s context manager).
    """

    def __init__(
        self,
        *,
        config: BinanceThConfig,
        depth_provider: DepthProvider,
        symbol_type_provider: SymbolTypeProvider,
        connect: ConnectFactory = _default_connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        session_ttl: float = _DEFAULT_SESSION_TTL,
    ) -> None:
        self._config = config
        self._depth = depth_provider
        self._router = StreamRouter(config=config, symbol_type_provider=symbol_type_provider)
        self._connect = connect
        self._sleep = sleep
        self._session_ttl = session_ttl
        self._conns: dict[str, _Connection] = {}
        self._closing = False

    async def _subscribe(
        self, symbol: str, channel: str, *, interval: str | None = None
    ) -> tuple[_Connection, _Subscription]:
        host = await self._router.host_for(symbol)
        stream = self._router.stream_name(symbol, channel, interval=interval)
        conn = self._conns.get(host)
        if conn is None:
            conn = _Connection(
                host=host,
                router=self._router,
                config=self._config,
                connect=self._connect,
                sleep=self._sleep,
                session_ttl=self._session_ttl,
            )
            self._conns[host] = conn
        sub = await conn.subscribe(stream)
        return conn, sub

    async def watch_depth(self, symbol: str) -> AsyncIterator[DepthUpdateEvent]:
        """Yield raw diff-depth updates for ``symbol`` (see :meth:`order_book` for a synced book)."""
        conn, sub = await self._subscribe(symbol, "depth")
        try:
            async for payload in sub:
                yield DepthUpdateEvent.model_validate(payload)
        finally:
            await conn.unsubscribe(sub)

    async def watch_trades(self, symbol: str) -> AsyncIterator[TradeEvent]:
        conn, sub = await self._subscribe(symbol, "trade")
        try:
            async for payload in sub:
                yield TradeEvent.model_validate(payload)
        finally:
            await conn.unsubscribe(sub)

    async def watch_agg_trades(self, symbol: str) -> AsyncIterator[AggTradeEvent]:
        conn, sub = await self._subscribe(symbol, "aggTrade")
        try:
            async for payload in sub:
                yield AggTradeEvent.model_validate(payload)
        finally:
            await conn.unsubscribe(sub)

    async def watch_klines(self, symbol: str, interval: str = "1m") -> AsyncIterator[KlineEvent]:
        conn, sub = await self._subscribe(symbol, "kline", interval=interval)
        try:
            async for payload in sub:
                yield KlineEvent.model_validate(payload)
        finally:
            await conn.unsubscribe(sub)

    async def watch_book_ticker(self, symbol: str) -> AsyncIterator[BookTickerEvent]:
        conn, sub = await self._subscribe(symbol, "bookTicker")
        try:
            async for payload in sub:
                yield BookTickerEvent.model_validate(payload)
        finally:
            await conn.unsubscribe(sub)

    async def watch_ticker(self, symbol: str) -> AsyncIterator[TickerEvent]:
        conn, sub = await self._subscribe(symbol, "ticker")
        try:
            async for payload in sub:
                yield TickerEvent.model_validate(payload)
        finally:
            await conn.unsubscribe(sub)

    async def order_book(self, symbol: str, *, limit: int = 1000) -> ManagedOrderBook:
        """Return a self-syncing local order book for ``symbol`` (ADR-0007).

        The book seeds from a REST depth snapshot and stays current from the depth stream,
        re-snapshotting on any update-id gap. Call ``book.aclose()`` when done (or close the
        client), which also unsubscribes the underlying depth stream.
        """
        conn, sub = await self._subscribe(symbol, "depth")
        book = ManagedOrderBook(
            symbol,
            deltas=self._decode_depth(sub),
            depth_provider=self._depth,
            limit=limit,
            on_close=lambda: conn.unsubscribe(sub),
        )
        book.start()
        return book

    @staticmethod
    async def _decode_depth(sub: _Subscription) -> AsyncIterator[DepthUpdateEvent]:
        async for payload in sub:
            yield DepthUpdateEvent.model_validate(payload)

    async def aclose(self) -> None:
        """Tear down every connection (supervisors, sockets, subscribers); idempotent."""
        if self._closing:
            return
        self._closing = True
        await asyncio.gather(
            *(conn.aclose() for conn in self._conns.values()), return_exceptions=True
        )
        self._conns.clear()
