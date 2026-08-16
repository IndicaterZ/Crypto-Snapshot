"""Server-time offset tracking for signed-request timestamps (ADR-0004).

Pure state, no I/O — the transport owns the network call to ``GET /api/v1/time``
and feeds the result to :meth:`TimeSync.update`. :meth:`TimeSync.now_ms` then
returns local time adjusted by the offset, so every signed ``timestamp`` lands
inside the server's ``recvWindow`` even when the local clock drifts.

The ``clock`` callable is injectable so tests can simulate skew deterministically.
"""

import time
from collections.abc import Callable

__all__ = ["TimeSync", "default_now_ms"]


def default_now_ms() -> int:
    """Current UTC time in milliseconds since the epoch."""
    return time.time_ns() // 1_000_000


class TimeSync:
    """Tracks the local-to-server clock offset."""

    def __init__(self, *, clock: Callable[[], int] = default_now_ms) -> None:
        """Initialize with a zero offset; ``clock`` supplies local epoch-ms."""
        self._clock = clock
        self._offset_ms = 0
        self._synced = False

    @property
    def offset_ms(self) -> int:
        """The current server-minus-local offset in milliseconds."""
        return self._offset_ms

    @property
    def synced(self) -> bool:
        """True once :meth:`update` has run at least once."""
        return self._synced

    def now_ms(self) -> int:
        """Local clock adjusted by the current server offset."""
        return self._clock() + self._offset_ms

    def update(self, server_time_ms: int) -> int:
        """Recompute the offset from a fresh server time; return the new offset."""
        self._offset_ms = server_time_ms - self._clock()
        self._synced = True
        return self._offset_ms
