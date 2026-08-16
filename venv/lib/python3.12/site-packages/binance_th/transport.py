"""Async HTTP transport for the Binance Thailand REST API (ADR-0001/0002/0015).

Owns one :class:`httpx.AsyncClient` plus the signer and the server-time offset,
and runs every request through a single pipeline: build → sign → send →
status-map → parse → (optional) unwrap. **All** Binance TH responses are bare
(verified 2026-07-09; errors are `{code,msg}` + HTTP 4xx), so the default is
bare for signed and unsigned alike; the ``unwrap`` path stays available for any
endpoint that opts into ``envelope=True``. The transport is **model-agnostic** —
it returns raw parsed JSON (or text); callers apply Pydantic models.

The rate limiter (M2, ADR-0005) and retry/backoff engine (M2, ADR-0012) plug in
via the :class:`RateLimiter` and :class:`Retryer` protocols; M1 ships no-op
defaults. The single ``-1021`` resync (ADR-0004) lives in the auth path here,
orthogonal to the retryer.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

import httpx

from binance_th.config import BinanceThConfig
from binance_th.envelope import unwrap
from binance_th.errors import raise_for_http_status
from binance_th.exceptions import (
    BinanceThAuthError,
    BinanceThIPBannedError,
    BinanceThNetworkError,
    BinanceThRateLimitError,
    BinanceThServerError,
    BinanceThTimeoutError,
)
from binance_th.models.base import RateLimit, ServerTime
from binance_th.ratelimit import DualWindowRateLimiter
from binance_th.redaction import redact_headers, redact_params
from binance_th.retry import BackoffRetryer
from binance_th.signing import Signer
from binance_th.timesync import TimeSync

__all__ = ["NullRateLimiter", "NullRetryer", "RateLimiter", "Retryer", "Transport"]

TIME_PATH = "/api/v1/time"
_TIMESTAMP_ERROR_CODE = -1021
_REQUEST_ID_HEADER = "x-mbx-uuid"


class RateLimiter(Protocol):
    """M2 seam (ADR-0005): pace requests and reconcile against server headers."""

    async def acquire(self, weight: int, *, mutating: bool) -> None: ...

    def update_from_headers(self, headers: Mapping[str, str]) -> None: ...

    def reseed(self, rate_limits: Sequence[RateLimit]) -> None: ...


class Retryer(Protocol):
    """M2 seam (ADR-0012): wrap one attempt with a retry/backoff policy."""

    async def run(
        self,
        fn: Callable[[], Awaitable[Any]],
        *,
        retryable: Callable[[BaseException], bool],
        max_retries: int,
    ) -> Any: ...


class NullRateLimiter:
    """No-op limiter used until the M2 dual-window bucket lands."""

    async def acquire(self, weight: int, *, mutating: bool) -> None:
        """Admit immediately."""

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Ignore server usage headers."""

    def reseed(self, rate_limits: Sequence[RateLimit]) -> None:
        """Ignore authoritative limits; the null limiter never paces."""


class NullRetryer:
    """Single-attempt retryer used until the M2 backoff engine lands."""

    async def run(
        self,
        fn: Callable[[], Awaitable[Any]],
        *,
        retryable: Callable[[BaseException], bool],
        max_retries: int,
    ) -> Any:
        """Run ``fn`` exactly once (the retry policy arrives in M2)."""
        del retryable, max_retries  # accepted for the protocol; the M2 retryer uses them
        return await fn()


def _resolve_limiter(limiter: RateLimiter | None, config: BinanceThConfig) -> RateLimiter:
    """Injected limiter wins; else a real limiter when rate limiting is enabled."""
    if limiter is not None:
        return limiter
    if config.enable_rate_limiting:
        return DualWindowRateLimiter.from_defaults()
    return NullRateLimiter()


def _resolve_retryer(retryer: Retryer | None, config: BinanceThConfig) -> Retryer:
    """Injected retryer wins; else a backoff retryer when retries are allowed."""
    if retryer is not None:
        return retryer
    if config.max_retries > 0:
        return BackoffRetryer()
    return NullRetryer()


class Transport:
    """Async request pipeline over a single ``httpx.AsyncClient``."""

    def __init__(
        self,
        config: BinanceThConfig,
        *,
        client: httpx.AsyncClient | None = None,
        signer: Signer | None = None,
        timesync: TimeSync | None = None,
        limiter: RateLimiter | None = None,
        retryer: Retryer | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Wire the transport; a caller may inject any collaborator (tests inject ``client``)."""
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.rest_base_url, timeout=config.timeout
        )
        self._signer = signer or (
            Signer(config.api_secret) if config.api_secret is not None else None
        )
        self._timesync = timesync or TimeSync()
        self._limiter: RateLimiter = _resolve_limiter(limiter, config)
        self._retryer: Retryer = _resolve_retryer(retryer, config)
        self._logger = logger or logging.getLogger("binance_th")
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """True once :meth:`aclose` has run."""
        return self._closed

    @property
    def can_sign(self) -> bool:
        """True if credentials for signed requests are configured."""
        return self._can_sign

    @property
    def _can_sign(self) -> bool:
        return self._signer is not None and self._config.api_key is not None

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        signed: bool = False,
        api_key_only: bool = False,
        envelope: bool | None = None,
        weight: int = 1,
        mutating: bool = False,
        parse_json: bool = True,
    ) -> Any:
        """Send a request and return raw JSON/text.

        ``envelope=None`` defaults to **bare** (Binance TH has no success envelope);
        pass ``envelope=True`` to unwrap a ``{code,msg,data}`` body. ``parse_json=False``
        returns ``response.text`` (for ``/ping``). ``weight``/``mutating`` feed the M2
        limiter seam.
        """
        resolved_envelope = bool(envelope)
        if signed and not self._can_sign:
            raise BinanceThAuthError("API credentials are required for signed endpoints")

        async def execute() -> Any:
            return await self._execute(
                method=method,
                path=path,
                params=params,
                signed=signed,
                api_key_only=api_key_only,
                envelope=resolved_envelope,
                weight=weight,
                mutating=mutating,
                parse_json=parse_json,
            )

        async def attempt() -> Any:
            try:
                return await execute()
            except BinanceThAuthError as exc:
                # One resync + retry on -1021 (ADR-0004); a second -1021 propagates.
                if signed and exc.code == _TIMESTAMP_ERROR_CODE:
                    await self.sync_time()
                    return await execute()
                raise

        return await self._retryer.run(
            attempt,
            retryable=lambda exc: self._is_retryable(exc, mutating=mutating),
            max_retries=self._config.max_retries,
        )

    async def sync_time(self) -> ServerTime:
        """Fetch ``GET /api/v1/time`` (bare) and update the offset manager."""
        data = await self._execute(
            method="GET",
            path=TIME_PATH,
            params=None,
            signed=False,
            api_key_only=False,
            envelope=False,
            weight=1,
            mutating=False,
            parse_json=True,
        )
        server_time = ServerTime(**data)
        self._timesync.update(server_time.server_time)
        return server_time

    async def aclose(self) -> None:
        """Close the underlying httpx client; idempotent."""
        if not self._closed:
            await self._client.aclose()
            self._closed = True

    def reseed_rate_limits(self, rate_limits: Sequence[RateLimit]) -> None:
        """Adopt authoritative rate limits (e.g. from exchangeInfo) into the limiter."""
        self._limiter.reseed(rate_limits)

    async def _execute(
        self,
        *,
        method: str,
        path: str,
        params: Mapping[str, Any] | None,
        signed: bool,
        api_key_only: bool,
        envelope: bool,
        weight: int,
        mutating: bool,
        parse_json: bool,
    ) -> Any:
        """One full HTTP attempt: sign, send, map errors, parse, unwrap."""
        if signed and not self._timesync.synced:
            await self.sync_time()

        if signed:
            if self._signer is None:  # pragma: no cover - guarded by _can_sign in request()
                raise BinanceThAuthError("API credentials are required for signed endpoints")
            send_params: dict[str, Any] = dict(
                self._signer.signed_params(
                    params, timestamp=self._timesync.now_ms(), recv_window=self._config.recv_window
                )
            )
        else:
            send_params = dict(params or {})

        headers: dict[str, str] = {}
        if (signed or api_key_only) and self._config.api_key is not None:
            headers["X-MBX-APIKEY"] = self._config.api_key

        self._log_request(method, path, send_params, headers)
        await self._limiter.acquire(weight, mutating=mutating)

        try:
            response = await self._client.request(method, path, params=send_params, headers=headers)
        except httpx.TimeoutException as exc:
            raise BinanceThTimeoutError(
                str(exc) or "Request timeout", timeout=self._config.timeout
            ) from exc
        except httpx.HTTPError as exc:
            raise BinanceThNetworkError(str(exc) or "Network error") from exc

        self._limiter.update_from_headers(response.headers)
        body = self._decode(response, parse_json=parse_json)
        raise_for_http_status(response.status_code, body, response.headers)
        result = (
            unwrap(
                body,
                status_code=response.status_code,
                request_id=response.headers.get(_REQUEST_ID_HEADER),
            )
            if envelope
            else body
        )
        self._log_response(result)
        return result

    def _decode(self, response: httpx.Response, *, parse_json: bool) -> Any:
        """Decode the body; always try JSON on errors so ``code``/``msg`` are readable."""
        if response.status_code >= 400:
            return self._try_json(response)
        if not parse_json:
            return response.text
        return response.json()

    @staticmethod
    def _try_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text

    def _is_retryable(self, exc: BaseException, *, mutating: bool) -> bool:
        """Retryable transient failures; never for mutating calls (ADR-0006/0012)."""
        if mutating:
            return False
        return isinstance(
            exc,
            (
                BinanceThNetworkError,
                BinanceThTimeoutError,
                BinanceThServerError,
                BinanceThRateLimitError,
                BinanceThIPBannedError,
            ),
        )

    def _log_request(
        self, method: str, path: str, params: Mapping[str, Any], headers: Mapping[str, str]
    ) -> None:
        if self._config.log_requests:
            self._logger.debug(
                "request %s %s params=%s headers=%s",
                method,
                path,
                redact_params(params),
                redact_headers(headers),
            )

    def _log_response(self, result: Any) -> None:
        if self._config.log_responses:
            safe = redact_params(result) if isinstance(result, dict) else result
            self._logger.debug("response %s", safe)
