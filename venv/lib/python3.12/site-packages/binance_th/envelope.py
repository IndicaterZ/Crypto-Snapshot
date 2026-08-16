"""Response-envelope unwrapping for opt-in callers (ADR-0002).

Verified 2026-07-09: Binance TH returns **bare** bodies on every probed endpoint
(errors are ``{code,msg}`` + HTTP 4xx), so the transport default is bare and this
module is **not** on the default path. It remains available for any caller that
passes ``envelope=True`` to unwrap a ``{"code":0,"msg":...,"data":...}`` body —
asserting ``code == 0`` and returning ``data``, or routing a non-zero ``code`` to
a typed error. Signed shapes stay ⚠ ASSUMED until a credentialed soak.
"""

from typing import Any

from binance_th.errors import raise_envelope_error
from binance_th.exceptions import BinanceThValidationError

__all__ = ["is_envelope", "unwrap"]


def is_envelope(payload: Any) -> bool:
    """True if ``payload`` looks like the ``{code, msg, ...}`` response envelope."""
    return isinstance(payload, dict) and isinstance(payload.get("code"), int)


def unwrap(payload: Any, *, status_code: int, request_id: str | None = None) -> Any:
    """Return ``data`` from an envelope, raising on a non-zero ``code``.

    Raises:
        BinanceThAPIError: subclass, when the envelope ``code`` is non-zero.
        BinanceThValidationError: when an envelope was expected but the payload
            is not envelope-shaped (an endpoint mis-classified as enveloped).
    """
    if not is_envelope(payload):
        raise BinanceThValidationError(
            "Expected an enveloped response but received a bare payload",
            field="response",
            value=payload,
        )
    code = payload["code"]
    if code != 0:
        raise_envelope_error(
            code,
            str(payload.get("msg", "")),
            status_code=status_code,
            response_data=payload,
            request_id=request_id,
        )
    return payload.get("data")
