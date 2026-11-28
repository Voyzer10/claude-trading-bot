"""Crypto Spot (Coinbase & CoinDCX) and Perpetual Futures (CoinDCX) Market Data Adapters."""
from __future__ import annotations

from .coindcx import (
    COINDCX_FUTURES_RESOLUTIONS,
    COINDCX_LICENSE_NOTE,
    COINDCX_MAX_CANDLES,
    COINDCX_SPOT_INTERVALS,
    CoinDCXDiscovery,
    CoinDCXDiscoveryReport,
    CoinDCXHistoricalClient,
    CoinDCXLiveBridge,
    inspect_coindcx_credentials,
)
from .config import (
    APPROVED_CRYPTO_HOSTS,
    COINBASE_REST_BASE,
    COINDCX_API_BASE,
    COINDCX_PUBLIC_BASE,
    COINDCX_WS_URL,
    CRYPTO_DERIVATIVES_EVALUATIONS,
    DEFAULT_CRYPTO_UNIVERSE,
    UTC_TZ,
    CryptoCalendar,
    CryptoHTTPResponse,
    CryptoProviderEvaluation,
    CryptoRateLimiter,
    PublicCryptoHTTPClient,
)
from .coverage import CryptoCoveragePreflight
from .discovery import CryptoDiscoveryReport, CryptoSpotDiscovery
from .exceptions import (
    CryptoAdapterError,
    CryptoBlockedEndpointError,
    CryptoGeoBlockedError,
    CryptoInputError,
    CryptoRateLimitError,
)
from .historical import (
    CryptoCandle,
    CryptoFundingRecord,
    CryptoHistoricalClient,
    CryptoLiveBridge,
    CryptoOpenInterestRecord,
)

__all__ = [
    "APPROVED_CRYPTO_HOSTS",
    "COINBASE_REST_BASE",
    "COINDCX_API_BASE",
    "COINDCX_FUTURES_RESOLUTIONS",
    "COINDCX_LICENSE_NOTE",
    "COINDCX_MAX_CANDLES",
    "COINDCX_PUBLIC_BASE",
    "COINDCX_SPOT_INTERVALS",
    "COINDCX_WS_URL",
    "CRYPTO_DERIVATIVES_EVALUATIONS",
    "CoinDCXDiscovery",
    "CoinDCXDiscoveryReport",
    "CoinDCXHistoricalClient",
    "CoinDCXLiveBridge",
    "CryptoAdapterError",
    "CryptoBlockedEndpointError",
    "CryptoCalendar",
    "CryptoCandle",
    "CryptoCoveragePreflight",
    "CryptoDiscoveryReport",
    "CryptoFundingRecord",
    "CryptoGeoBlockedError",
    "CryptoHTTPResponse",
    "CryptoHistoricalClient",
    "CryptoInputError",
    "CryptoLiveBridge",
    "CryptoOpenInterestRecord",
    "CryptoProviderEvaluation",
    "CryptoRateLimitError",
    "CryptoRateLimiter",
    "CryptoSpotDiscovery",
    "DEFAULT_CRYPTO_UNIVERSE",
    "PublicCryptoHTTPClient",
    "UTC_TZ",
    "inspect_coindcx_credentials",
]
