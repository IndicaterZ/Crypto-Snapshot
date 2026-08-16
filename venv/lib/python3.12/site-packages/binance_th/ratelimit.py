"""Dual-window rate limiter (ADR-0005).

Paces requests so they stay under Binance Thailand's per-IP weight limits and
per-account order limits, avoiding 429/418. Each advertised ``RateLimit`` becomes
a fixed **window** (a bucket that refills in bulk at the interval boundary — the
server's own accounting unit, so it cannot over-admit within a window). Windows
are seeded from :data:`DEFAULT_RATE_LIMITS` (the values verified live 2026-07-09)
and reconciled **upward** from the server's ``x-mbx-used-weight-*`` /
``x-mbx-order-count-*`` headers; M3 calls :meth:`DualWindowRateLimiter.reseed`
with authoritative ``exchangeInfo`` limits.

The ``clock`` (monotonic) and ``sleep`` are injectable so pacing is deterministic
in tests.
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from binance_th.models.base import RateLimit
from binance_th.models.enums import RateLimitInterval, RateLimitType

__all__ = ["DEFAULT_RATE_LIMITS", "DualWindowRateLimiter", "Window"]

WindowKey = tuple[RateLimitType, RateLimitInterval, int]

_INTERVAL_SECONDS: dict[RateLimitInterval, float] = {
    RateLimitInterval.SECOND: 1.0,
    RateLimitInterval.MINUTE: 60.0,
    RateLimitInterval.HOUR: 3600.0,
    RateLimitInterval.DAY: 86400.0,
}

_UNIT_TO_INTERVAL: dict[str, RateLimitInterval] = {
    "s": RateLimitInterval.SECOND,
    "m": RateLimitInterval.MINUTE,
    "h": RateLimitInterval.HOUR,
    "d": RateLimitInterval.DAY,
}

_WEIGHT_HEADER_RE = re.compile(r"x-mbx-used-weight-(\d+)([smhd])")
_ORDER_HEADER_RE = re.compile(r"x-mbx-order-count-(\d+)([smhd])")

# Verified live 2026-07-09 via GET /api/v1/exchangeInfo (see ADR-0005).
DEFAULT_RATE_LIMITS: list[RateLimit] = [
    RateLimit(
        rate_limit_type=RateLimitType.REQUEST_WEIGHT,
        interval=RateLimitInterval.MINUTE,
        interval_num=1,
        limit=6000,
    ),
    RateLimit(
        rate_limit_type=RateLimitType.ORDERS,
        interval=RateLimitInterval.MINUTE,
        interval_num=1,
        limit=6000,
    ),
    RateLimit(
        rate_limit_type=RateLimitType.ORDERS,
        interval=RateLimitInterval.SECOND,
        interval_num=10,
        limit=1000,
    ),
]


@dataclass
class Window:
    """A single fixed-interval rate-limit bucket."""

    rate_limit_type: RateLimitType
    interval: RateLimitInterval
    interval_num: int
    limit: int
    duration: float
    used: int = 0
    window_start: float | None = None

    @property
    def key(self) -> WindowKey:
        """Identity used to match server headers and reseeds."""
        return (self.rate_limit_type, self.interval, self.interval_num)

    def roll(self, now: float) -> None:
        """Anchor on first use; reset the counter once the interval has elapsed."""
        if self.window_start is None:
            self.window_start = now
            return
        elapsed = now - self.window_start
        if elapsed >= self.duration:
            self.window_start += self.duration * (elapsed // self.duration)
            self.used = 0

    def wait_time(self, now: float, charge: int) -> float:
        """Seconds until ``charge`` fits; 0 if it fits now (or the window is empty)."""
        if self.used == 0 or self.used + charge <= self.limit:
            return 0.0
        start = self.window_start if self.window_start is not None else now
        return max(0.0, start + self.duration - now)


def _default_now() -> float:
    return time.monotonic()


async def _default_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


class DualWindowRateLimiter:
    """Multi-window pacer implementing the transport ``RateLimiter`` protocol."""

    def __init__(
        self,
        windows: Sequence[Window],
        *,
        clock: Callable[[], float] = _default_now,
        sleep: Callable[[float], Awaitable[None]] = _default_sleep,
    ) -> None:
        """Build from ready windows; ``clock``/``sleep`` are injectable for tests."""
        self._windows: dict[WindowKey, Window] = {w.key: w for w in windows}
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()

    @classmethod
    def from_rate_limits(
        cls,
        rate_limits: Sequence[RateLimit],
        *,
        clock: Callable[[], float] = _default_now,
        sleep: Callable[[float], Awaitable[None]] = _default_sleep,
    ) -> "DualWindowRateLimiter":
        """Build windows from a list of ``RateLimit`` rules (e.g. from ``exchangeInfo``)."""
        windows = [
            Window(
                rate_limit_type=rule.rate_limit_type,
                interval=rule.interval,
                interval_num=rule.interval_num,
                limit=rule.limit,
                duration=_INTERVAL_SECONDS[rule.interval] * rule.interval_num,
            )
            for rule in rate_limits
        ]
        return cls(windows, clock=clock, sleep=sleep)

    @classmethod
    def from_defaults(
        cls,
        *,
        clock: Callable[[], float] = _default_now,
        sleep: Callable[[float], Awaitable[None]] = _default_sleep,
    ) -> "DualWindowRateLimiter":
        """Build from the verified live default limits."""
        return cls.from_rate_limits(DEFAULT_RATE_LIMITS, clock=clock, sleep=sleep)

    def _charges(self, weight: int, mutating: bool) -> list[tuple[Window, int]]:
        """Which windows this call charges, and by how much."""
        charges: list[tuple[Window, int]] = []
        for window in self._windows.values():
            if window.rate_limit_type == RateLimitType.REQUEST_WEIGHT:
                charges.append((window, weight))
            elif window.rate_limit_type == RateLimitType.RAW_REQUESTS or (
                window.rate_limit_type == RateLimitType.ORDERS and mutating
            ):
                charges.append((window, 1))
        return charges

    async def acquire(self, weight: int, *, mutating: bool) -> None:
        """Block until every applicable window admits ``weight`` (+1 order if mutating)."""
        while True:
            async with self._lock:
                now = self._clock()
                charges = self._charges(weight, mutating)
                wait = 0.0
                for window, amount in charges:
                    window.roll(now)
                    wait = max(wait, window.wait_time(now, amount))
                if wait <= 0.0:
                    for window, amount in charges:
                        window.used += amount
                    return
            await self._sleep(wait)

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Reconcile local usage up to the server's reported usage (never down)."""
        now = self._clock()
        for raw_key, raw_value in headers.items():
            match = _WEIGHT_HEADER_RE.fullmatch(raw_key.lower())
            rate_type = RateLimitType.REQUEST_WEIGHT
            if match is None:
                match = _ORDER_HEADER_RE.fullmatch(raw_key.lower())
                rate_type = RateLimitType.ORDERS
            if match is None:
                continue
            interval = _UNIT_TO_INTERVAL.get(match.group(2))
            if interval is None:
                continue
            try:
                used = int(raw_value)
            except ValueError:
                continue
            window = self._windows.get((rate_type, interval, int(match.group(1))))
            if window is None:
                continue
            window.roll(now)
            window.used = max(window.used, used)

    def reseed(self, rate_limits: Sequence[RateLimit]) -> None:
        """Adopt authoritative limits, carrying over ``used``/``window_start`` for kept keys."""
        new_windows: dict[WindowKey, Window] = {}
        for rule in rate_limits:
            key: WindowKey = (rule.rate_limit_type, rule.interval, rule.interval_num)
            duration = _INTERVAL_SECONDS[rule.interval] * rule.interval_num
            existing = self._windows.get(key)
            if existing is not None:
                existing.limit = rule.limit
                existing.duration = duration
                new_windows[key] = existing
            else:
                new_windows[key] = Window(
                    rate_limit_type=rule.rate_limit_type,
                    interval=rule.interval,
                    interval_num=rule.interval_num,
                    limit=rule.limit,
                    duration=duration,
                )
        self._windows = new_windows
