"""HMAC-SHA256 request signing for SIGNED endpoints (ADR-0003).

Parameters are signed in the order they are sent (insertion order) over their
**raw** (un-URL-encoded) values; the ``signature`` is appended **last** and is
never itself part of the signed string. ``timestamp`` (and an optional
``recvWindow``) are injected here, immediately before hashing, so the signed
string is byte-identical to what the client sends.

The golden-vector test locks this algorithm. Verification against the *server's*
re-derivation requires live credentials and is done in a later live soak
(``⚠ ASSUMED`` in ADR-0003 until then).
"""

import hashlib
import hmac
from collections.abc import Mapping
from typing import Any

from pydantic import SecretStr

__all__ = ["Signer", "build_query", "sign_payload"]


def build_query(params: Mapping[str, Any]) -> str:
    """Build an insertion-ordered ``k=v&k2=v2`` string over raw ``str(value)``.

    A ``signature`` key, if present, is excluded — it is never self-signed.
    """
    return "&".join(f"{key}={value}" for key, value in params.items() if key != "signature")


def sign_payload(secret: str, payload: str) -> str:
    """Return the lowercase hex HMAC-SHA256 digest of ``payload`` keyed by ``secret``."""
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


class Signer:
    """Signs request parameters with the API secret."""

    def __init__(self, api_secret: SecretStr) -> None:
        """Store the secret; it is read only inside :meth:`signed_params`."""
        self._api_secret = api_secret

    def signed_params(
        self,
        params: Mapping[str, Any] | None,
        *,
        timestamp: int,
        recv_window: int | None = None,
    ) -> dict[str, str]:
        """Return an ordered param dict ending with ``timestamp`` then ``signature``.

        ``recvWindow`` is injected only if the caller did not already supply it.
        Every value is stringified; the signature covers all preceding params in
        insertion order.
        """
        ordered: dict[str, str] = {key: str(value) for key, value in (params or {}).items()}
        if recv_window is not None and "recvWindow" not in ordered:
            ordered["recvWindow"] = str(recv_window)
        ordered["timestamp"] = str(timestamp)
        ordered["signature"] = sign_payload(
            self._api_secret.get_secret_value(), build_query(ordered)
        )
        return ordered
