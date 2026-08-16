"""Local order-book synchronization engine (ADR-0007).

WebSocket-agnostic by design: the sync loop is driven by any
``AsyncIterator[DepthUpdateEvent]`` plus an injected REST depth-snapshot provider,
so it unit-tests on plain iterables with a mocked ``depth`` and no sockets.

The algorithm (ADR-0007):

1. Buffer diff-depth deltas (the caller's async iterator is already buffering).
2. Fetch the REST depth snapshot and read its ``lastUpdateId``.
3. **Drop** every buffered delta fully older than the snapshot (``u <= lastUpdateId``).
4. **Bracket-check** the first applied delta (``U <= lastUpdateId + 1 <= u``); if it
   fails, discard and re-snapshot.
5. **Apply** deltas in order (a quantity of ``0`` removes that price level).
6. On any update-id **gap** (``U > last_applied_u + 1``) discard the book and re-snapshot.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from decimal import Decimal
from typing import TYPE_CHECKING

from binance_th.models.market import OrderBook

if TYPE_CHECKING:
    from binance_th.models.market import OrderBookEntry
    from binance_th.models.stream import DepthUpdateEvent

DepthProvider = Callable[..., Awaitable[OrderBook]]
Level = tuple[Decimal, Decimal]


class LocalOrderBook:
    """Pure, synchronous in-memory order book.

    Bids/asks are held as ``dict[Decimal, Decimal]`` (O(1) upsert/remove) and sorted
    on demand for top-N reads (ADR-0007). No I/O and no ``await`` — reads never
    interleave with :meth:`apply`, so the book is race-free on a single event loop.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.last_applied_u: int = -1

    def seed(self, snapshot: OrderBook) -> None:
        """Reset the book to a REST snapshot and adopt its ``lastUpdateId`` baseline."""
        self.bids = {entry.price: entry.quantity for entry in snapshot.bids}
        self.asks = {entry.price: entry.quantity for entry in snapshot.asks}
        self.last_applied_u = snapshot.last_update_id

    def apply(self, delta: DepthUpdateEvent) -> None:
        """Apply one diff-depth delta; advance ``last_applied_u`` to its final id."""
        self._apply_side(self.bids, delta.bids)
        self._apply_side(self.asks, delta.asks)
        self.last_applied_u = delta.final_update_id

    @staticmethod
    def _apply_side(side: dict[Decimal, Decimal], levels: list[OrderBookEntry]) -> None:
        for level in levels:
            if level.quantity == 0:
                side.pop(level.price, None)
            else:
                side[level.price] = level.quantity

    def best_bid(self) -> Level | None:
        """Highest bid ``(price, quantity)``, or ``None`` if the bid side is empty."""
        if not self.bids:
            return None
        price = max(self.bids)
        return price, self.bids[price]

    def best_ask(self) -> Level | None:
        """Lowest ask ``(price, quantity)``, or ``None`` if the ask side is empty."""
        if not self.asks:
            return None
        price = min(self.asks)
        return price, self.asks[price]

    def bids_top(self, n: int) -> list[Level]:
        """Top ``n`` bids, highest price first."""
        return [(price, self.bids[price]) for price in sorted(self.bids, reverse=True)[:n]]

    def asks_top(self, n: int) -> list[Level]:
        """Top ``n`` asks, lowest price first."""
        return [(price, self.asks[price]) for price in sorted(self.asks)[:n]]


class OrderBookSynchronizer:
    """Runs the ADR-0007 seed/drop/bracket/apply/gap-resync loop over a delta stream."""

    def __init__(self, symbol: str, *, depth_provider: DepthProvider, limit: int = 1000) -> None:
        self._symbol = symbol
        self._depth = depth_provider
        self._limit = limit

    async def run(self, deltas: AsyncIterator[DepthUpdateEvent]) -> AsyncIterator[LocalOrderBook]:
        """Yield the book after every successfully applied delta.

        Loops forever re-snapshotting on gaps; returns only when ``deltas`` is
        exhausted (the stream closed). The caller owns cancellation.
        """
        while True:
            snapshot = await self._depth(self._symbol, limit=self._limit)
            book = LocalOrderBook(self._symbol)
            book.seed(snapshot)
            last_u = snapshot.last_update_id
            first = True
            gap = False
            yield book  # expose the snapshot immediately; deltas keep it current

            async for delta in deltas:
                if delta.final_update_id <= last_u:
                    continue  # (3) fully stale — drop
                if first:
                    if not (delta.first_update_id <= last_u + 1 <= delta.final_update_id):
                        gap = True  # (4) snapshot not bracketed — re-snapshot
                        break
                    first = False
                elif delta.first_update_id > last_u + 1:
                    gap = True  # (6) update-id gap — re-snapshot
                    break
                book.apply(delta)
                last_u = book.last_applied_u
                yield book

            if not gap:
                return  # delta stream ended cleanly


class ManagedOrderBook:
    """A self-syncing local order book backed by a background ``asyncio.Task``.

    Returned by ``client.ws.order_book(symbol)``. Reads (:meth:`best_bid`,
    :meth:`best_ask`, :meth:`bids`, :meth:`asks`) return the latest applied state, or
    empty/``None`` until the first snapshot lands (poll :attr:`synced` or await
    :meth:`wait_synced`).
    """

    def __init__(
        self,
        symbol: str,
        *,
        deltas: AsyncIterator[DepthUpdateEvent],
        depth_provider: DepthProvider,
        limit: int = 1000,
        on_close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.symbol = symbol
        self._deltas = deltas
        self._sync = OrderBookSynchronizer(symbol, depth_provider=depth_provider, limit=limit)
        self._book: LocalOrderBook | None = None
        self._task: asyncio.Task[None] | None = None
        self._synced = asyncio.Event()
        self._on_close = on_close

    def start(self) -> None:
        """Launch the background sync task (idempotent)."""
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"orderbook-{self.symbol}")

    async def _run(self) -> None:
        async for book in self._sync.run(self._deltas):
            self._book = book
            self._synced.set()

    @property
    def synced(self) -> bool:
        """True once the first snapshot has been applied."""
        return self._book is not None

    async def wait_synced(self) -> None:
        """Block until the first snapshot is applied.

        Bound it with ``asyncio.wait_for(book.wait_synced(), timeout=...)`` if needed.
        """
        await self._synced.wait()

    def best_bid(self) -> Level | None:
        return self._book.best_bid() if self._book is not None else None

    def best_ask(self) -> Level | None:
        return self._book.best_ask() if self._book is not None else None

    def bids(self, n: int = 10) -> list[Level]:
        return self._book.bids_top(n) if self._book is not None else []

    def asks(self, n: int = 10) -> list[Level]:
        return self._book.asks_top(n) if self._book is not None else []

    async def aclose(self) -> None:
        """Cancel the sync task, close the delta stream, and run ``on_close``; idempotent."""
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # close the delta async generator so its finally-blocks (e.g. unsubscribe) run
        aclose = getattr(self._deltas, "aclose", None)
        if callable(aclose):
            with contextlib.suppress(Exception):
                await aclose()
        on_close = self._on_close
        self._on_close = None
        if on_close is not None:
            await on_close()
