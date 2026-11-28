"""Exceptions for Crypto Spot (Coinbase) and Crypto Derivatives (Binance/Deribit) adapters."""
from __future__ import annotations


class CryptoAdapterError(RuntimeError):
    """Base error for crypto market data operations."""


class CryptoBlockedEndpointError(CryptoAdapterError):
    """Raised when an unapproved host, non-GET method, or private trading endpoint is attempted."""


class CryptoInputError(CryptoAdapterError):
    """Raised on invalid symbol, contract, timeframe, or parameter inputs."""


class CryptoRateLimitError(CryptoAdapterError):
    """Raised when exchange HTTP 429/418 rate-limit retries are exhausted."""


class CryptoGeoBlockedError(CryptoAdapterError):
    """Raised when an exchange returns HTTP 451 or geographic restriction."""
