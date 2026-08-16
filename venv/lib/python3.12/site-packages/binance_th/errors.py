"""Failure mapping: HTTP status and envelope code to typed exceptions (ADR-0006).

Two failure signals coexist — the HTTP status code (non-2xx) and the envelope
``code != 0`` on an otherwise-200 signed response. Both are folded into the
Phase-1 hierarchy here: :data:`ENVELOPE_CODE_MAP` is the sibling of
:data:`binance_th.exceptions.HTTP_STATUS_MAP` for application-level codes, and
:func:`map_exception` composes the two (a non-zero envelope code wins).

Public functions take primitives (``status_code``, decoded ``body``, a headers
mapping) rather than an :class:`httpx.Response`, so this module stays
transport-agnostic and unit-testable without constructing a response object.
"""

from collections.abc import Mapping
from typing import Any, NoReturn

from binance_th.exceptions import (
    BinanceThAPIError,
    BinanceThAuthError,
    BinanceThBadRequestError,
    BinanceThIPBannedError,
    BinanceThRateLimitError,
    get_exception_for_status_code,
)

__all__ = [
    "ENVELOPE_CODE_MAP",
    "exception_for_envelope_code",
    "map_exception",
    "raise_envelope_error",
    "raise_for_http_status",
]

# Application-level error codes carried in the envelope ``code`` field.
# ⚠ ASSUMED — consistent with Binance global; refined against live signed calls (ADR-0006).
ENVELOPE_CODE_MAP: dict[int, type[BinanceThAPIError]] = {
    -1021: BinanceThAuthError,  # timestamp outside recvWindow
    -1022: BinanceThAuthError,  # invalid signature
    -2014: BinanceThAuthError,  # bad api-key format
    -2015: BinanceThAuthError,  # rejected api-key / permissions / IP
    -1000: BinanceThBadRequestError,  # generic bad request (e.g. symbol not served by endpoint)
    -1100: BinanceThBadRequestError,  # illegal chars in a parameter
    -1102: BinanceThBadRequestError,  # mandatory param missing/empty
    -1013: BinanceThBadRequestError,  # filter failure (PRICE_FILTER, LOT_SIZE, ...)
    -1121: BinanceThBadRequestError,  # invalid symbol
    -2013: BinanceThBadRequestError,  # order does not exist (used in UNKNOWN reconciliation)
}

_USED_WEIGHT_HEADER = "x-mbx-used-weight-1m"
_RETRY_AFTER_HEADER = "retry-after"
_REQUEST_ID_HEADER = "x-mbx-uuid"


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup (httpx lowercases under HTTP/2)."""
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def _int_or_none(value: str | None) -> int | None:
    """Best-effort int parse; header values are strings and may be malformed."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _extract(body: Any) -> tuple[int | None, str | None]:
    """Pull ``(code, msg)`` from a decoded JSON body when it is envelope-shaped."""
    if isinstance(body, dict):
        code = body.get("code")
        msg = body.get("msg")
        return (
            code if isinstance(code, int) else None,
            msg if isinstance(msg, str) else None,
        )
    return (None, None)


def exception_for_envelope_code(code: int) -> type[BinanceThAPIError]:
    """Map an application-level envelope code to an exception class."""
    return ENVELOPE_CODE_MAP.get(code, BinanceThAPIError)


def map_exception(status_code: int | None, code: int | None) -> type[BinanceThAPIError]:
    """Resolve the exception class from a status code and/or an envelope code.

    A non-zero envelope code wins (it is the more specific signal); otherwise the
    HTTP status decides; failing both, the base API error.
    """
    if code is not None and code != 0:
        return exception_for_envelope_code(code)
    if status_code is not None:
        return get_exception_for_status_code(status_code)
    return BinanceThAPIError


def _build(
    exc_cls: type[BinanceThAPIError],
    message: str,
    *,
    code: int | None,
    status_code: int | None,
    request_id: str | None,
    response_data: dict[str, Any] | None,
    retry_after: int | None,
    used_weight: int | None,
) -> BinanceThAPIError:
    """Construct the exception, threading rate-limit extras where the class accepts them."""
    kwargs: dict[str, Any] = {
        "code": code,
        "status_code": status_code,
        "request_id": request_id,
        "response_data": response_data,
    }
    if issubclass(exc_cls, BinanceThRateLimitError):
        kwargs["retry_after"] = retry_after
        kwargs["used_weight"] = used_weight
    elif issubclass(exc_cls, BinanceThIPBannedError):
        kwargs["retry_after"] = retry_after
    return exc_cls(message, **kwargs)


def raise_for_http_status(status_code: int, body: Any, headers: Mapping[str, str]) -> None:
    """Raise a typed exception for a non-2xx status; no-op for < 400.

    Reads ``code``/``msg`` from the body when it is JSON, and ``Retry-After`` /
    ``x-mbx-used-weight-1m`` / request-id from the headers.
    """
    if status_code < 400:
        return
    code, msg = _extract(body)
    raise _build(
        map_exception(status_code, code),
        msg or f"HTTP {status_code}",
        code=code,
        status_code=status_code,
        request_id=_header(headers, _REQUEST_ID_HEADER),
        response_data=body if isinstance(body, dict) else None,
        retry_after=_int_or_none(_header(headers, _RETRY_AFTER_HEADER)),
        used_weight=_int_or_none(_header(headers, _USED_WEIGHT_HEADER)),
    )


def raise_envelope_error(
    code: int,
    msg: str,
    *,
    status_code: int,
    response_data: dict[str, Any],
    request_id: str | None = None,
) -> NoReturn:
    """Raise a typed exception for a non-zero envelope ``code`` on a 2xx response."""
    raise _build(
        map_exception(status_code, code),
        msg or f"API error {code}",
        code=code,
        status_code=status_code,
        request_id=request_id,
        response_data=response_data,
        retry_after=None,
        used_weight=None,
    )
