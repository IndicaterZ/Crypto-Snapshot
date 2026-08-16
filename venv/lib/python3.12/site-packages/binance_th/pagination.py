"""Time-window pagination for history endpoints (ADR-0016).

A generic async generator that walks half-open ``[start_time, end_time)`` windows
under a server ``limit``, de-duplicating the boundary row that a server's inclusive
``startTime`` re-returns, and stopping when a page is short or makes no forward
progress. Reused by market klines (M3a) and signed history endpoints (M3b).
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Hashable, Sequence
from typing import TypeVar

__all__ = ["iter_time_windows"]

T = TypeVar("T")


async def iter_time_windows(
    fetch: Callable[[int, int], Awaitable[Sequence[T]]],
    *,
    start_time: int,
    end_time: int,
    page_limit: int,
    window_key: Callable[[T], int],
    dedup_key: Callable[[T], Hashable] | None = None,
) -> AsyncIterator[T]:
    """Yield rows across ``[start_time, end_time)`` windows, de-duped at boundaries.

    Args:
        fetch: ``fetch(window_start, end_time)`` returns one server page, ascending by time.
        start_time: inclusive lower bound (ms).
        end_time: exclusive upper bound (ms).
        page_limit: the server page size; a short page ends iteration.
        window_key: extracts the ordering timestamp used to advance the window.
        dedup_key: identity for boundary de-duplication (defaults to ``window_key``).
    """
    identity = dedup_key or window_key
    window_start = start_time
    boundary_key: int | None = None
    boundary_ids: set[Hashable] = set()
    while window_start < end_time:
        page = await fetch(window_start, end_time)
        if not page:
            return
        for row in page:
            key = window_key(row)
            if key >= end_time:
                return
            if key == boundary_key and identity(row) in boundary_ids:
                continue  # a boundary row re-returned by the server's inclusive startTime
            yield row
        if len(page) < page_limit:
            return  # last (partial) page
        last_key = window_key(page[-1])
        if last_key <= window_start:
            return  # no forward progress; avoid an infinite loop
        boundary_key = last_key
        boundary_ids = {identity(row) for row in page if window_key(row) == last_key}
        window_start = last_key
