"""Exceptions for the Indian Kite market data adapter."""
from __future__ import annotations


class KiteAdapterError(RuntimeError):
    """Base error for Indian Kite market data operations."""


class KiteAuthError(KiteAdapterError):
    """Raised on missing, invalid, or expired Kite access token (403 TokenException)."""


class KiteInputError(KiteAdapterError):
    """Raised on invalid request parameters (400 InputException)."""


class KiteRateLimitError(KiteAdapterError):
    """Raised when Kite HTTP 429 rate-limit retries are exhausted."""


class InstrumentMasterError(KiteAdapterError):
    """Raised when instrument master download, CSV parsing, or snapshot validation fails."""


class ContractDiscoveryError(KiteAdapterError):
    """Raised when contract filtering or canonical mapping fails."""


class CalendarError(KiteAdapterError):
    """Raised when NSE calendar data is missing or invalid."""
