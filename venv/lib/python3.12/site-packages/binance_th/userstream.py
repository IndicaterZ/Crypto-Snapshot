"""User-data WebSocket stream client (``client.user_stream``), M6.

Verified topology (``scripts/probe_userdata.py``, 2026-07-10): ``POST /api/v1/listenKey``
returns one key per symbol type, and each streams **bare** event frames (``{"e": ...}``,
no ``{stream, data}`` wrapper) from ``{ws_base_url}/ws/<listenKey>`` (the WSA host, uniform
for both types). So :class:`UserDataStream` holds **one connection per type** (GLOBAL, SITE),
and both feed a shared set of per-event-type subscriptions — a user's orders span both types,
so ``watch_orders()`` and the order tracker aggregate events from both.

Design (reusing M5's :mod:`binance_th.stream` leaf primitives):

- :class:`_UserDataConnection` — one socket per type with a listenKey-aware supervisor:
  ``create()`` the key, connect ``/ws/<key>``, demux **bare** frames by ``e``, and on a drop
  recreate the key and broadcast a reconcile signal. A ``listenKeyExpired`` frame forces a
  planned reconnect. Keepalive is the :class:`ListenKeyManager`'s job (an app-level REST PUT),
  distinct from the websockets-library ping.
- :class:`UserDataStream` — owns the shared subscriptions + the manager; exposes the typed
  ``watch_*`` async iterators and the self-healing :meth:`order_tracker`; DELETEs the key on close.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any

from binance_th.exceptions import BinanceThAuthError, BinanceThWebSocketError
from binance_th.listenkey import RestListenKeyManager
from binance_th.models.enums import SymbolType
from binance_th.models.userdata import (
    BalanceUpdateEvent,
    ExecutionReportEvent,
    OutboundAccountPositionEvent,
)
from binance_th.ordertracker import _RECONNECTED, OrderTracker
from binance_th.stream import (
    _DEFAULT_SESSION_TTL,
    ConnectFactory,
    WsConnection,
    _Backoff,
    _default_connect,
    _Subscription,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from binance_th.config import BinanceThConfig
    from binance_th.listenkey import ListenKeyManager
    from binance_th.models.orders import Order
    from binance_th.ordertracker import OpenOrdersProvider
    from binance_th.transport import Transport

_ORDER_EVENT = "executionReport"


class _UserDataConnection:
    """One multiplexed user-data socket for a single symbol type, with supervised reconnect."""

    def __init__(
        self,
        *,
        symbol_type: SymbolType,
        keys: ListenKeyManager,
        config: BinanceThConfig,
        connect: ConnectFactory,
        sleep: Callable[[float], Awaitable[None]],
        session_ttl: float,
        dispatch: Callable[[dict[str, Any]], None],
        on_reconnect: Callable[[], None],
        fault: Callable[[BaseException], None],
    ) -> None:
        self._symbol_type = symbol_type
        self._keys = keys
        self._config = config
        self._connect = connect
        self._sleep = sleep
        self._session_ttl = session_ttl
        self._dispatch = dispatch
        self._on_reconnect = on_reconnect
        self._fault = fault
        self._ws: WsConnection | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._closing = False
        self._planned = False

    def start(self) -> None:
        if self._supervisor is None:
            self._supervisor = asyncio.create_task(
                self._run_supervisor(), name=f"userdata-{self._symbol_type.value}"
            )

    def _handle(self, raw: str | bytes) -> bool:
        """Decode + demux one bare frame; return True to stop the reader (listenKeyExpired)."""
        try:
            frame = json.loads(raw)
        except (ValueError, TypeError):
            return False
        if not isinstance(frame, dict):
            return False
        if frame.get("e") == "listenKeyExpired":
            return True  # → planned reconnect that recreates the key
        self._dispatch(frame)
        return False

    async def _read_loop(self, ws: WsConnection) -> None:
        with contextlib.suppress(Exception):
            async for raw in ws:
                if self._handle(raw):
                    self._planned = True
                    return

    async def _run_supervisor(self) -> None:
        backoff = _Backoff()
        reader: asyncio.Task[None] | None = None
        first = True
        try:
            while not self._closing:
                try:
                    await self._keys.create()  # refresh the key (single-flight across connections)
                except asyncio.CancelledError:
                    raise
                except BinanceThAuthError as exc:
                    self._fault(BinanceThWebSocketError(f"user-data auth failed: {exc}"))
                    return
                except Exception as exc:
                    if not self._config.ws_auto_reconnect or self._closing:
                        self._fault(BinanceThWebSocketError(f"listenKey create failed: {exc}"))
                        return
                    await self._sleep(backoff.next())
                    continue

                key = self._keys.key_for(self._symbol_type)
                if key is None:
                    self._fault(
                        BinanceThWebSocketError(f"no listenKey for {self._symbol_type.value}")
                    )
                    return
                try:
                    ws = await self._connect(
                        f"{self._config.ws_base_url}/ws/{key}",
                        ping_interval=float(self._config.ws_ping_interval),
                        ping_timeout=float(self._config.ws_ping_timeout),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    if not self._config.ws_auto_reconnect or self._closing:
                        self._fault(BinanceThWebSocketError("user-data connect failed"))
                        return
                    await self._sleep(backoff.next())
                    continue

                if not first:
                    self._on_reconnect()  # broadcast reconcile to the shared order subs
                first = False
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
                    self._fault(BinanceThWebSocketError("user-data stream disconnected"))
                    return
                await self._sleep(backoff.next())
        finally:
            if reader is not None and not reader.done():
                reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader

    async def aclose(self) -> None:
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


class UserDataStream:
    """Public user-data stream (``client.user_stream``).

    Typed ``watch_orders``/``watch_account``/``watch_balances`` async iterators plus a
    self-healing :meth:`order_tracker`. Opens one connection per symbol type and tears them
    all down — DELETEing the listenKey — on :meth:`aclose`.
    """

    def __init__(
        self,
        *,
        config: BinanceThConfig,
        transport: Transport,
        open_orders_provider: OpenOrdersProvider,
        connect: ConnectFactory = _default_connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        session_ttl: float = _DEFAULT_SESSION_TTL,
        keys: ListenKeyManager | None = None,
    ) -> None:
        self._config = config
        self._open_orders = open_orders_provider
        self._connect = connect
        self._sleep = sleep
        self._session_ttl = session_ttl
        self._keys: ListenKeyManager = keys or RestListenKeyManager(transport, config, sleep=sleep)
        self._subs: dict[str, list[_Subscription]] = {}
        self._conns: list[_UserDataConnection] = []
        self._started = False
        self._closing = False

    async def _ensure_started(self) -> None:
        if self._started or self._closing:
            return
        await self._keys.create()  # POST → per-type keys (fail-fast without an api key)
        if self._started or self._closing:  # another caller won the race
            return
        self._started = True
        for symbol_type in (SymbolType.GLOBAL, SymbolType.SITE):
            if self._keys.key_for(symbol_type) is None:
                continue
            conn = _UserDataConnection(
                symbol_type=symbol_type,
                keys=self._keys,
                config=self._config,
                connect=self._connect,
                sleep=self._sleep,
                session_ttl=self._session_ttl,
                dispatch=self._dispatch,
                on_reconnect=self._broadcast_reconnect,
                fault=self._fault_all,
            )
            self._conns.append(conn)
            conn.start()

    def _dispatch(self, frame: dict[str, Any]) -> None:
        event_type = frame.get("e")
        if isinstance(event_type, str):
            for sub in self._subs.get(event_type, ()):
                sub.offer(frame)

    def _broadcast_reconnect(self) -> None:
        # a reconnect on any connection → re-seed the order tracker against REST truth
        for sub in self._subs.get(_ORDER_EVENT, ()):
            sub.offer(_RECONNECTED)

    def _fault_all(self, exc: BaseException) -> None:
        for subs in self._subs.values():
            for sub in subs:
                sub.fault(exc)

    def _subscribe(self, event_type: str) -> _Subscription:
        sub = _Subscription(event_type)
        self._subs.setdefault(event_type, []).append(sub)
        return sub

    async def _unsubscribe(self, sub: _Subscription) -> None:
        subs = self._subs.get(sub.stream)
        if subs is not None and sub in subs:
            subs.remove(sub)
        sub.close()
        if subs is not None and not subs:
            self._subs.pop(sub.stream, None)

    async def watch_orders(self) -> AsyncIterator[ExecutionReportEvent]:
        """Stream order-update events (``executionReport``) from both symbol types."""
        await self._ensure_started()
        sub = self._subscribe(_ORDER_EVENT)
        try:
            async for frame in sub:
                if frame is _RECONNECTED:
                    continue
                yield ExecutionReportEvent.model_validate(frame)
        finally:
            await self._unsubscribe(sub)

    async def watch_account(self) -> AsyncIterator[OutboundAccountPositionEvent]:
        """Stream account balance snapshots (``outboundAccountPosition``)."""
        await self._ensure_started()
        sub = self._subscribe("outboundAccountPosition")
        try:
            async for frame in sub:
                if frame is _RECONNECTED:
                    continue
                yield OutboundAccountPositionEvent.model_validate(frame)
        finally:
            await self._unsubscribe(sub)

    async def watch_balances(self) -> AsyncIterator[BalanceUpdateEvent]:
        """Stream balance deltas (``balanceUpdate``)."""
        await self._ensure_started()
        sub = self._subscribe("balanceUpdate")
        try:
            async for frame in sub:
                if frame is _RECONNECTED:
                    continue
                yield BalanceUpdateEvent.model_validate(frame)
        finally:
            await self._unsubscribe(sub)

    async def order_tracker(self) -> OrderTracker:
        """Return a self-healing local order view reconciled against REST (ADR-0008).

        The view seeds from ``openOrders``, updates from ``executionReport``s across both
        symbol types, and re-seeds on any reconnect. Call ``tracker.aclose()`` when done (or
        close the client), which also unsubscribes the underlying event stream.
        """
        await self._ensure_started()
        sub = self._subscribe(_ORDER_EVENT)
        tracker = OrderTracker(
            events=self._decode_reports(sub),
            open_orders_provider=self._open_orders,
            on_close=lambda: self._unsubscribe(sub),
        )
        tracker.start()
        return tracker

    @staticmethod
    async def _decode_reports(sub: _Subscription) -> AsyncIterator[object]:
        async for frame in sub:
            yield frame if frame is _RECONNECTED else ExecutionReportEvent.model_validate(frame)

    async def aclose(self) -> None:
        """Tear down every connection, end subscribers, and DELETE the listenKey; idempotent."""
        if self._closing:
            return
        self._closing = True
        await asyncio.gather(*(conn.aclose() for conn in self._conns), return_exceptions=True)
        self._conns = []
        for subs in self._subs.values():
            for sub in subs:
                sub.close()
        self._subs.clear()
        await self._keys.close()

    # Exposed for the tracker's terminal-fill enrichment / callers that want the raw Order list.
    async def open_orders_snapshot(self) -> list[Order]:
        return await self._open_orders()
