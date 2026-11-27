"""Exceptions for the Alpaca US equities, ETFs, indices, and options market data adapter."""
from __future__ import annotations


class AlpacaAdapterError(RuntimeError):
    """Base error for Alpaca US market data operations."""


class AlpacaAuthError(AlpacaAdapterError):
    """Raised when Alpaca credentials are missing, invalid, or rejected (HTTP 401/403)."""


class AlpacaSubscriptionError(AlpacaAdapterError):
    """Raised when an operation or feed (e.g., SIP/OPRA) is blocked by account subscription entitlement."""


class AlpacaRateLimitError(AlpacaAdapterError):
    """Raised when Alpaca HTTP 429 rate-limit retries are exhausted."""


class AlpacaPaginationIncompleteError(AlpacaAdapterError):
    """Raised when pagination stops before next_page_token is exhausted or a token repeats."""


class AlpacaInputError(AlpacaAdapterError):
    """Raised on invalid request parameters or out-of-scope inputs."""


class AlpacaBlockedEndpointError(AlpacaInputError):
    """Raised when a non-GET method or non-read-only/trading endpoint is attempted."""


class USCalendarError(AlpacaAdapterError):
    """Raised when US exchange calendar data is unverified or invalid."""
