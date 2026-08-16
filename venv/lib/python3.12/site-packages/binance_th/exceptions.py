"""Exception hierarchy for Binance Thailand API.

This module defines all custom exceptions used by the Binance-TH library.
Each exception is typed and specific to enable precise error handling.

Exception Hierarchy:
    BinanceThError (base)
    ├── BinanceThAPIError
    │   ├── BinanceThRateLimitError (429)
    │   ├── BinanceThIPBannedError (418)
    │   ├── BinanceThWAFError (403)
    │   ├── BinanceThAuthError (401)
    │   ├── BinanceThBadRequestError (400)
    │   └── BinanceThServerError (5xx)
    ├── BinanceThNetworkError
    ├── BinanceThTimeoutError
    ├── BinanceThValidationError
    └── BinanceThWebSocketError

HTTP Status Code Handling (per Binance Thailand API docs):
- 4XX: Malformed requests (client-side issues)
- 403: WAF (Web Application Firewall) limit violation
- 429: Rate limit exceeded
- 418: IP auto-banned for continued requests after 429s
- 5XX: Server errors (treat as unknown execution status, not failure)

Response Structure:
- code: 0 = success, other values = failure
- msg: Error message details
- timestamp: Server timestamp in milliseconds
- data: Response payload (when successful)
"""

from typing import Any


class BinanceThError(Exception):
    """Base exception for all Binance Thailand errors.

    All exceptions in the library inherit from this class,
    allowing for catch-all error handling when needed.

    Attributes:
        message: Human-readable error message
        code: Optional error code from the API response
        details: Additional error context as a dictionary
    """

    def __init__(
        self,
        message: str,
        code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize exception.

        Args:
            message: Error message
            code: Error code from API response (0 = success, other = failure)
            details: Additional error details
        """
        super().__init__(message)
        self.message: str = message
        self.code: int | None = code
        self.details: dict[str, Any] = details or {}

    def __str__(self) -> str:
        """Return string representation."""
        if self.code:
            return f"[{self.code}] {self.message}"
        return self.message


class BinanceThAPIError(BinanceThError):
    """API error from Binance Thailand.

    Raised when the API returns an error response.
    Includes HTTP status code and request ID for debugging.

    Attributes:
        status_code: HTTP status code
        request_id: Request ID from X-MBX-REQUEST-ID header
        response_data: Raw response data from API
    """

    def __init__(
        self,
        message: str,
        code: int | None = None,
        status_code: int | None = None,
        request_id: str | None = None,
        response_data: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize API error.

        Args:
            message: Error message (typically from 'msg' field in response)
            code: Error code from API response
            status_code: HTTP status code
            request_id: Request ID from response headers
            response_data: Raw API response data
            details: Additional error details
        """
        super().__init__(message=message, code=code, details=details)
        self.status_code: int | None = status_code
        self.request_id: str | None = request_id
        self.response_data: dict[str, Any] = response_data or {}


class BinanceThRateLimitError(BinanceThAPIError):
    """Rate limit exceeded (HTTP 429).

    Raised when request rate limit is exceeded. The client should
    back off and retry after the specified duration.

    Attributes:
        retry_after: Seconds to wait before retrying (from Retry-After header)
        used_weight: Current used weight from X-MBX-USED-WEIGHT headers
        limit_weight: Maximum allowed weight (if known)

    Note:
        Rate limits are tracked per IP using X-MBX-USED-WEIGHT-(intervalNum)(intervalLetter)
        headers. Order rate limits use X-MBX-ORDER-COUNT-(intervalNum)(intervalLetter).
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: int | None = None,
        used_weight: int | None = None,
        limit_weight: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize rate limit error.

        Args:
            message: Error message
            retry_after: Seconds to wait before retry (from Retry-After header)
            used_weight: Current used weight (from X-MBX-USED-WEIGHT header)
            limit_weight: Maximum allowed weight
            **kwargs: Additional arguments passed to BinanceThAPIError
        """
        if "status_code" not in kwargs:
            kwargs["status_code"] = 429
        super().__init__(message=message, **kwargs)
        self.retry_after: int | None = retry_after
        self.used_weight: int | None = used_weight
        self.limit_weight: int | None = limit_weight


class BinanceThIPBannedError(BinanceThAPIError):
    """IP auto-banned error (HTTP 418).

    Raised when the IP is automatically banned for repeatedly
    violating rate limits after receiving 429 responses.

    Ban durations scale from 2 minutes to 3 days for repeat offenders.

    Attributes:
        retry_after: Seconds until ban expires (from Retry-After header)
    """

    def __init__(
        self,
        message: str = "IP auto-banned for rate limit violations",
        retry_after: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize IP banned error.

        Args:
            message: Error message
            retry_after: Seconds until ban expires (from Retry-After header)
            **kwargs: Additional arguments passed to BinanceThAPIError
        """
        if "status_code" not in kwargs:
            kwargs["status_code"] = 418
        super().__init__(message=message, **kwargs)
        self.retry_after: int | None = retry_after


class BinanceThWAFError(BinanceThAPIError):
    """Web Application Firewall limit violation (HTTP 403).

    Raised when the request is blocked by Binance's WAF.
    This is different from authentication errors.

    Suspend requests immediately and review security protocols.
    """

    def __init__(
        self,
        message: str = "WAF limit violation",
        **kwargs: Any,
    ) -> None:
        """Initialize WAF error.

        Args:
            message: Error message
            **kwargs: Additional arguments passed to BinanceThAPIError
        """
        if "status_code" not in kwargs:
            kwargs["status_code"] = 403
        super().__init__(message=message, **kwargs)


class BinanceThAuthError(BinanceThAPIError):
    """Authentication error (HTTP 401).

    Raised when:
    - API key is invalid or missing
    - Signature is incorrect
    - Timestamp is outside recvWindow
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        **kwargs: Any,
    ) -> None:
        """Initialize auth error.

        Args:
            message: Error message
            **kwargs: Additional arguments passed to BinanceThAPIError
        """
        if "status_code" not in kwargs:
            kwargs["status_code"] = 401
        super().__init__(message=message, **kwargs)


class BinanceThBadRequestError(BinanceThAPIError):
    """Bad request error (HTTP 400).

    Raised when request parameters are invalid or malformed.
    This is a client-side issue - review request parameters before resubmitting.
    """

    def __init__(
        self,
        message: str = "Bad request",
        **kwargs: Any,
    ) -> None:
        """Initialize bad request error.

        Args:
            message: Error message
            **kwargs: Additional arguments passed to BinanceThAPIError
        """
        if "status_code" not in kwargs:
            kwargs["status_code"] = 400
        super().__init__(message=message, **kwargs)


class BinanceThServerError(BinanceThAPIError):
    """Server error (HTTP 5xx).

    Raised when Binance servers encounter an error.

    IMPORTANT: Per Binance Thailand API documentation, 5XX errors
    should NOT be treated as operation failure. The execution status
    is unknown and the operation may have succeeded.

    Consider:
    - Checking order status before retrying order operations
    - Using idempotent request patterns where possible
    """

    def __init__(
        self,
        message: str = "Server error - execution status unknown",
        **kwargs: Any,
    ) -> None:
        """Initialize server error.

        Args:
            message: Error message
            **kwargs: Additional arguments passed to BinanceThAPIError
        """
        super().__init__(message=message, **kwargs)


class BinanceThNetworkError(BinanceThError):
    """Network connection error.

    Raised when unable to connect to the API due to:
    - DNS resolution failure
    - Connection refused
    - SSL/TLS errors
    - Other network-level issues

    These errors are typically transient and can be retried.
    """

    def __init__(
        self,
        message: str = "Network error",
        **kwargs: Any,
    ) -> None:
        """Initialize network error.

        Args:
            message: Error message
            **kwargs: Additional arguments passed to BinanceThError
        """
        super().__init__(message=message, **kwargs)


class BinanceThTimeoutError(BinanceThError):
    """Request timeout error.

    Raised when a request exceeds the configured timeout.
    Can be retried, but consider increasing timeout for heavy operations.

    Attributes:
        timeout: The timeout value that was exceeded (seconds)
    """

    def __init__(
        self,
        message: str = "Request timeout",
        timeout: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize timeout error.

        Args:
            message: Error message
            timeout: The timeout value that was exceeded (seconds)
            **kwargs: Additional arguments passed to BinanceThError
        """
        super().__init__(message=message, **kwargs)
        self.timeout: float | None = timeout


class BinanceThValidationError(BinanceThError):
    """Data validation error.

    Raised when data validation fails:
    - Invalid request parameters before sending
    - Response data doesn't match expected schema
    - Type conversion errors

    This is a client-side error, not an API error.

    Attributes:
        field: Name of the field that failed validation
        value: The invalid value
    """

    def __init__(
        self,
        message: str = "Validation error",
        field: str | None = None,
        value: Any = None,
        **kwargs: Any,
    ) -> None:
        """Initialize validation error.

        Args:
            message: Error message
            field: Name of the field that failed validation
            value: The invalid value
            **kwargs: Additional arguments passed to BinanceThError
        """
        super().__init__(message=message, **kwargs)
        self.field: str | None = field
        self.value: Any = value


class BinanceThWebSocketError(BinanceThError):
    """WebSocket error.

    Raised for WebSocket-specific errors:
    - Connection failures
    - Message parsing errors
    - Subscription errors
    - Unexpected disconnections

    Note: Planned reconnections (e.g., proactive 24h reconnect)
    are NOT errors and should not raise this exception.
    """

    def __init__(
        self,
        message: str = "WebSocket error",
        **kwargs: Any,
    ) -> None:
        """Initialize WebSocket error.

        Args:
            message: Error message
            **kwargs: Additional arguments passed to BinanceThError
        """
        super().__init__(message=message, **kwargs)


class BinanceThOrderUnknownError(BinanceThError):
    """Order execution status is UNKNOWN after a transient failure (ADR-0006).

    Raised when a mutating order create hit a 5xx/timeout/network error and the
    reconciliation query (by client order id) could not confirm the order. The
    execution status is genuinely unknown — do not blindly resubmit.

    Attributes:
        client_order_id: The client order id used to reconcile.
        symbol: The order's symbol.
        resubmittable: True only when the reconciliation query positively confirmed
            the order was NOT placed (safe to resubmit); False if still unknown.
    """

    def __init__(
        self,
        message: str = "Order execution status unknown",
        *,
        client_order_id: str | None = None,
        symbol: str | None = None,
        resubmittable: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize the UNKNOWN-order error."""
        super().__init__(message=message, **kwargs)
        self.client_order_id: str | None = client_order_id
        self.symbol: str | None = symbol
        self.resubmittable: bool = resubmittable


# HTTP status code to exception mapping
HTTP_STATUS_MAP: dict[int, type[BinanceThAPIError]] = {
    400: BinanceThBadRequestError,
    401: BinanceThAuthError,
    403: BinanceThWAFError,
    418: BinanceThIPBannedError,
    429: BinanceThRateLimitError,
    500: BinanceThServerError,
    502: BinanceThServerError,
    503: BinanceThServerError,
    504: BinanceThServerError,
}


def get_exception_for_status_code(status_code: int) -> type[BinanceThAPIError]:
    """Get exception class for HTTP status code.

    Args:
        status_code: HTTP status code

    Returns:
        Exception class to raise
    """
    if status_code >= 500:
        return BinanceThServerError
    return HTTP_STATUS_MAP.get(status_code, BinanceThAPIError)
