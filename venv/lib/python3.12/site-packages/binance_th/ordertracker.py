"""Reconciled local order tracker for the user-data stream (ADR-0008).

WebSocket-agnostic, mirroring :mod:`binance_th.orderbook`: the sync loop is driven by any
``AsyncIterator`` of :class:`ExecutionReportEvent` (interleaved with the :data:`_RECONNECTED`
sentinel the user-data connection broadcasts) plus an injected ``open_orders`` provider, so it
unit-tests on plain iterables with no sockets.

On a stream drop the connection offers :data:`_RECONNECTED`; the tracker **re-seeds from REST
``openOrders`` and replaces the local view** (ADR-0008 drop→reconcile), rather than trusting
that no events were missed. ``executionReport`` carries absolute cumulative state (``z``/``Z``/
``X``), so updates are idempotent and a monotonic ``update_time`` guard drops a stale report.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable

from binance_th.models.enums import OrderStatus
from binance_th.models.orders import Order
from binance_th.models.userdata import ExecutionReportEvent, order_from_execution_report

# Sentinel the user-data connection offers on reconnect → the tracker re-seeds from REST.
_RECONNECTED = object()

OpenOrdersProvider = Callable[..., Awaitable[list[Order]]]

_TERMINAL = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED}
)


class LocalOrderView:
    """Pure, synchronous view of currently-open orders keyed by ``orderId``."""

    def __init__(self) -> None:
        self._orders: dict[int, Order] = {}

    def seed(self, orders: list[Order]) -> None:
        """Replace the view with the active orders from a REST snapshot."""
        self._orders = {order.order_id: order for order in orders if order.is_active}

    def apply(self, event: ExecutionReportEvent) -> None:
        """Apply one execution report: upsert while active, remove once terminal."""
        order = order_from_execution_report(event)
        prev = self._orders.get(order.order_id)
        if prev is not None and order.update_time < prev.update_time:
            return  # stale/out-of-order report — the reconciled state is newer
        if order.status in _TERMINAL:
            self._orders.pop(order.order_id, None)
        else:
            self._orders[order.order_id] = order

    def open(self) -> list[Order]:
        """All currently-open orders."""
        return list(self._orders.values())

    def get(self, order_id: int) -> Order | None:
        return self._orders.get(order_id)


class OrderTrackerSynchronizer:
    """Runs the seed → apply → reconnect-re-seed loop over an execution-report stream."""

    def __init__(self, *, open_orders_provider: OpenOrdersProvider) -> None:
        self._open_orders = open_orders_provider

    async def run(self, events: AsyncIterator[object]) -> AsyncIterator[LocalOrderView]:
        """Yield the view after the REST seed and after every applied report.

        Loops forever, re-seeding whenever ``_RECONNECTED`` arrives; returns only when the
        event stream is exhausted. The caller owns cancellation.
        """
        while True:
            view = LocalOrderView()
            view.seed(await self._open_orders())
            yield view  # expose the reconciled snapshot immediately

            reconnected = False
            async for event in events:
                if event is _RECONNECTED:
                    reconnected = True
                    break
                if isinstance(event, ExecutionReportEvent):
                    view.apply(event)
                    yield view

            if not reconnected:
                return


class OrderTracker:
    """A self-healing local order view backed by a background ``asyncio.Task``.

    Returned by ``client.user_stream.order_tracker()``. Reads (:meth:`open`, :meth:`get`)
    return the latest reconciled state, or empty/``None`` until the first REST seed lands
    (poll :attr:`synced` or await :meth:`wait_synced`).
    """

    def __init__(
        self,
        *,
        events: AsyncIterator[object],
        open_orders_provider: OpenOrdersProvider,
        on_close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._events = events
        self._sync = OrderTrackerSynchronizer(open_orders_provider=open_orders_provider)
        self._view: LocalOrderView | None = None
        self._task: asyncio.Task[None] | None = None
        self._synced = asyncio.Event()
        self._on_close = on_close

    def start(self) -> None:
        """Launch the background sync task (idempotent)."""
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="order-tracker")

    async def _run(self) -> None:
        async for view in self._sync.run(self._events):
            self._view = view
            self._synced.set()

    @property
    def synced(self) -> bool:
        """True once the first REST seed has been applied."""
        return self._view is not None

    async def wait_synced(self) -> None:
        """Block until the first REST seed is applied.

        Bound it with ``asyncio.wait_for(tracker.wait_synced(), timeout=...)`` if needed.
        """
        await self._synced.wait()

    def open(self) -> list[Order]:
        return self._view.open() if self._view is not None else []

    def get(self, order_id: int) -> Order | None:
        return self._view.get(order_id) if self._view is not None else None

    async def aclose(self) -> None:
        """Cancel the sync task, close the event stream, and run ``on_close``; idempotent."""
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        aclose = getattr(self._events, "aclose", None)
        if callable(aclose):
            with contextlib.suppress(Exception):
                await aclose()
        on_close = self._on_close
        self._on_close = None
        if on_close is not None:
            await on_close()
