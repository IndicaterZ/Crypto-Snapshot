"""Jittered exponential backoff retryer (ADR-0012).

Implements the transport ``Retryer`` protocol. It retries only what the caller's
``retryable`` predicate approves (transport restricts that to transient, **non
mutating** failures), backing off with full-jittered exponential delays — except
on a 429/418, where it honors the server's ``Retry-After`` (read off the
exception's ``retry_after`` attribute) instead. ``sleep``/``jitter`` are
injectable so the schedule is deterministic in tests.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

__all__ = ["BackoffRetryer"]

# Jitter for retry backoff only — not security-sensitive, so the stdlib PRNG is fine.
_DEFAULT_RNG = random.Random()  # nosec B311


def _full_jitter(ceiling: float) -> float:
    """A uniformly random delay in ``[0, ceiling]`` (full jitter)."""
    return _DEFAULT_RNG.uniform(0.0, ceiling)


async def _default_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


class BackoffRetryer:
    """Retry a coroutine with jittered exponential backoff, honoring ``Retry-After``."""

    def __init__(
        self,
        *,
        base: float = 0.5,
        factor: float = 2.0,
        cap: float = 8.0,
        jitter: Callable[[float], float] = _full_jitter,
        sleep: Callable[[float], Awaitable[None]] = _default_sleep,
    ) -> None:
        """Configure the schedule; defaults are base 0.5 s, x2 growth, capped at 8 s."""
        self._base = base
        self._factor = factor
        self._cap = cap
        self._jitter = jitter
        self._sleep = sleep

    async def run(
        self,
        fn: Callable[[], Awaitable[Any]],
        *,
        retryable: Callable[[BaseException], bool],
        max_retries: int,
    ) -> Any:
        """Call ``fn``; on a retryable error, back off and retry up to ``max_retries``."""
        attempt = 0
        while True:
            try:
                return await fn()
            except Exception as exc:  # not BaseException: CancelledError must propagate
                if attempt >= max_retries or not retryable(exc):
                    raise
                await self._sleep(self._delay(exc, attempt))
                attempt += 1

    def _delay(self, exc: BaseException, attempt: int) -> float:
        """Retry-After when the error carries it (429/418); else jittered exponential."""
        retry_after = getattr(exc, "retry_after", None)
        if isinstance(retry_after, int | float):
            return float(retry_after)
        return self._jitter(min(self._cap, self._base * self._factor**attempt))
