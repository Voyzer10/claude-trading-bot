"""Exceptions for the US Futures (Databento / CME Globex) market data adapter."""
from __future__ import annotations


class FuturesAdapterError(RuntimeError):
    """Base error for US Futures market data operations."""


class FuturesAuthError(FuturesAdapterError):
    """Raised when Databento credentials are missing, invalid, or rejected (401/403)."""


class FuturesBlockedEndpointError(FuturesAdapterError):
    """Raised when an unapproved host, method, or billable bulk operation is blocked."""


class FuturesInputError(FuturesAdapterError):
    """Raised on invalid futures parameters, symbology, or rollover configuration."""


class FuturesRateLimitError(FuturesAdapterError):
    """Raised when HTTP 429 rate-limit retries are exhausted."""


class FuturesSubscriptionError(FuturesAdapterError):
    """Raised when a dataset or schema is blocked by subscription or entitlement."""


class FuturesLicensingError(FuturesAdapterError):
    """Raised when CME/provider licensing terms do not permit the requested use."""
