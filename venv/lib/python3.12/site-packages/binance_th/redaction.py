"""Secret redaction for request/response logging (ADR-0017).

The library must never write ``api_secret``, ``signature``, or ``listenKey`` to a
log record. These helpers mask credential-bearing fields (in dicts, header maps,
and raw query strings) before anything reaches a logger, so the ``log_requests``
and ``log_responses`` debug flags on :class:`~binance_th.config.BinanceThConfig`
are safe to enable.
"""

import re
from collections.abc import Mapping
from typing import Any

__all__ = [
    "REDACTED",
    "SENSITIVE_KEYS",
    "redact_headers",
    "redact_params",
    "redact_query",
]

REDACTED = "***REDACTED***"

# Compared case-insensitively against parameter/header keys.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "signature",
        "api_secret",
        "apisecret",
        "secret",
        "api_key",
        "apikey",
        "x-mbx-apikey",
        "listenkey",
        "token",
    }
)


def _is_sensitive(key: str) -> bool:
    """Return True if a parameter/header key holds a credential."""
    return key.lower() in SENSITIVE_KEYS


def _redact_value(value: Any) -> Any:
    """Recurse into nested mappings/sequences, masking sensitive keys at any depth."""
    if isinstance(value, Mapping):
        return {k: (REDACTED if _is_sensitive(k) else _redact_value(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def redact_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep copy of ``params`` with sensitive values masked at any nesting depth.

    Recurses into nested dicts/lists so a credential buried in a response body (not just a
    top-level key) is masked before it can reach a logger.
    """
    return {k: (REDACTED if _is_sensitive(k) else _redact_value(v)) for k, v in params.items()}


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return a shallow copy of ``headers`` with sensitive values masked."""
    return {k: (REDACTED if _is_sensitive(k) else v) for k, v in headers.items()}


_QUERY_SENSITIVE_RE = re.compile(
    r"(?i)(?<![\w-])(" + "|".join(re.escape(k) for k in SENSITIVE_KEYS) + r")=[^&]*"
)


def redact_query(query: str) -> str:
    """Mask sensitive values inside a raw ``k=v&k2=v2`` query string."""
    return _QUERY_SENSITIVE_RE.sub(lambda m: f"{m.group(1)}={REDACTED}", query)
