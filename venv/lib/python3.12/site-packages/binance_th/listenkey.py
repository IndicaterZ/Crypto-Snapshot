"""listenKey lifecycle manager for the user-data stream (ADR-0008).

Binance TH's ``POST /api/v1/listenKey`` (API-key-only, no HMAC) returns a **list** — one
key per symbol type (GLOBAL, SITE), verified 2026-07-10 — a deviation from vanilla
Binance's single key. This manager holds all keys, keepalives each with a PUT well under
the 30-minute expiry, and DELETEs each on clean shutdown.

Keepalive and close are **best-effort per key**: the live SITE key is 64 chars, which the
server's own keepalive param regex (``^[a-zA-Z0-9]{1,60}$``) rejects — so the SITE key
cannot be extended or deleted and instead expires (~60 min), after which the SITE
connection self-heals via the drop→recreate→reconcile path. A failed keepalive/close for
one key never disturbs the others or crashes the manager.

The manager is an injectable interface (:class:`ListenKeyManager`) so a WSA-native
session-auth implementation can slot in later without changing callers.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Protocol

from binance_th.exceptions import BinanceThAuthError
from binance_th.models.account import ListenKey

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from binance_th.config import BinanceThConfig
    from binance_th.models.enums import SymbolType
    from binance_th.transport import Transport

_LISTEN_KEY_PATH = "/api/v1/listenKey"


class ListenKeyManager(Protocol):
    """Injectable listenKey lifecycle seam (ADR-0008).

    A WSA-native session-auth manager can implement the same interface; the connection
    layer depends only on this Protocol.
    """

    def key_for(self, symbol_type: SymbolType) -> str | None:
        """The current listenKey for ``symbol_type``, or None if not yet created."""
        ...

    async def create(self) -> None:
        """Obtain/refresh listenKey(s) and (re)start the keepalive loop."""
        ...

    async def keepalive(self) -> None:
        """Best-effort extend every held key."""
        ...

    async def close(self) -> None:
        """Stop keepalive and best-effort release every key."""
        ...


class RestListenKeyManager:
    """REST ``POST/PUT/DELETE /api/v1/listenKey`` implementation of :class:`ListenKeyManager`."""

    def __init__(
        self,
        transport: Transport,
        config: BinanceThConfig,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval: float | None = None,
    ) -> None:
        self._transport = transport
        self._config = config
        self._sleep = sleep
        self._interval = interval if interval is not None else config.user_stream_keepalive_interval
        self._keys: dict[SymbolType, str] = {}
        self._keepalive_task: asyncio.Task[None] | None = None
        self._inflight: asyncio.Task[None] | None = None
        self._closing = False

    def key_for(self, symbol_type: SymbolType) -> str | None:
        return self._keys.get(symbol_type)

    async def create(self) -> None:
        # Single-flight: coalesce concurrent callers (e.g. the GLOBAL + SITE connections
        # starting together) into one POST; a later reconnect issues its own fresh POST.
        inflight = self._inflight
        if inflight is not None and not inflight.done():
            await inflight
            return
        self._inflight = asyncio.ensure_future(self._do_create())
        try:
            await self._inflight
        finally:
            self._inflight = None

    async def _do_create(self) -> None:
        if self._config.api_key is None:
            raise BinanceThAuthError("API key required for the user-data stream")
        raw = await self._transport.request(
            "POST", _LISTEN_KEY_PATH, api_key_only=True, envelope=False
        )
        entries = raw if isinstance(raw, list) else [raw]
        keys: dict[SymbolType, str] = {}
        for entry in entries:
            if isinstance(entry, dict):
                listen_key = ListenKey.model_validate(entry)
                keys[listen_key.symbol_type] = listen_key.listen_key
        self._keys = keys
        if self._keepalive_task is None and not self._closing:
            self._keepalive_task = asyncio.create_task(
                self._keepalive_loop(), name="listenkey-keepalive"
            )

    async def keepalive(self) -> None:
        for key in list(self._keys.values()):
            # best-effort: the SITE key is rejected by the server's own param regex
            with contextlib.suppress(Exception):
                await self._transport.request(
                    "PUT",
                    _LISTEN_KEY_PATH,
                    params={"listenKey": key},
                    api_key_only=True,
                    envelope=False,
                )

    async def _keepalive_loop(self) -> None:
        while not self._closing:
            await self._sleep(self._interval)
            if self._closing:
                break
            await self.keepalive()

    async def close(self) -> None:
        self._closing = True
        task = self._keepalive_task
        self._keepalive_task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        keys = list(self._keys.values())
        self._keys = {}
        for key in keys:
            with contextlib.suppress(Exception):
                await self._transport.request(
                    "DELETE",
                    _LISTEN_KEY_PATH,
                    params={"listenKey": key},
                    api_key_only=True,
                    envelope=False,
                )
