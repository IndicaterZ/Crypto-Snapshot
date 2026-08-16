"""Client-order-id minting for idempotency (ADR-0013).

When a caller omits ``newClientOrderId``, the order client mints a collision-
resistant, URL-safe id **before** sending, so a mutating order can be reconciled by
that id after a transient failure (ADR-0006). The charset is restricted to
``[A-Za-z0-9_-]`` (<= 36 chars) so httpx never URL-encodes it and desyncs the signed
string from the sent string. ⚠ The exact TH charset/length is ASSUMED.
"""

import secrets
import string
import time
from collections.abc import Callable

__all__ = ["mint_client_order_id"]

_DEFAULT_PREFIX = "xTHPY"
_ALPHABET = string.ascii_letters + string.digits  # URL-safe
_DIGITS36 = string.digits + string.ascii_lowercase
_MAX_LEN = 36
_TOKEN_LEN = 8


def _base36(value: int) -> str:
    if value <= 0:
        return "0"
    out: list[str] = []
    while value:
        value, rem = divmod(value, 36)
        out.append(_DIGITS36[rem])
    return "".join(reversed(out))


def _default_now_ms() -> int:
    return int(time.time() * 1000)


def _default_token() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_TOKEN_LEN))


def mint_client_order_id(
    prefix: str = _DEFAULT_PREFIX,
    *,
    now_ms: Callable[[], int] = _default_now_ms,
    token: Callable[[], str] = _default_token,
) -> str:
    """Mint a URL-safe, collision-resistant client order id (<= 36 chars)."""
    return f"{prefix}-{_base36(now_ms())}-{token()}"[:_MAX_LEN]
