"""
JA Hedge — Kalshi API Exceptions.

Typed exceptions for every Kalshi API error category.
"""

from __future__ import annotations


class KalshiError(Exception):
    """Base exception for all Kalshi API errors."""

    def __init__(self, message: str, status_code: int | None = None, body: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.body = body or {}
        super().__init__(self.message)


class KalshiAuthError(KalshiError):
    """Authentication failure — bad key, bad signature, expired timestamp."""
    pass


class KalshiRateLimitError(KalshiError):
    """Rate limit exceeded (HTTP 429). Retry after backoff."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: float | None = None, **kwargs):  # type: ignore[override]
        super().__init__(message, status_code=429, **kwargs)
        self.retry_after = retry_after


class KalshiOrderError(KalshiError):
    """Order-related errors — insufficient funds, invalid params, market closed."""
    pass


class KalshiNotFoundError(KalshiError):
    """Resource not found (HTTP 404)."""
    pass


class KalshiValidationError(KalshiError):
    """Request validation error (HTTP 400)."""
    pass


class KalshiServerError(KalshiError):
    """Kalshi server error (HTTP 5xx). Should retry."""
    pass


class KalshiConnectionError(KalshiError):
    """Network-level connection failure."""
    pass


# Map HTTP status codes to exception classes
STATUS_CODE_MAP: dict[int, type[KalshiError]] = {
    400: KalshiValidationError,
    401: KalshiAuthError,
    403: KalshiAuthError,
    404: KalshiNotFoundError,
    429: KalshiRateLimitError,
}
