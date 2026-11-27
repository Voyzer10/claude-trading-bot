"""Alpaca US Equities, ETFs, Indices, and Options Market Data Adapter (read-only)."""
from __future__ import annotations

from .assets import AlpacaAssetsDiscovery, AssetDiscoveryReport, AssetSnapshot, diff_asset_snapshots
from .client import AlpacaDataClient, AlpacaHTTPResponse, PaginatedResult
from .config import (
    NY_TZ,
    OPTION_FEEDS,
    OPTION_HISTORY_EARLIEST,
    STOCK_ADJUSTMENTS,
    STOCK_FEEDS,
    SUPPORTED_TIMEFRAMES,
    UTC_TZ,
    AlpacaCredential,
    AlpacaRateLimiter,
    USCalendar,
    inspect_alpaca_credentials,
    resolve_alpaca_credential,
)
from .contracts import (
    CANONICAL_US_OPTIONS_EXCHANGE,
    AlpacaOptionsContractDiscovery,
    OptionContractsSnapshot,
    OptionDiscoveryReport,
)
from .coverage import AlpacaCoveragePreflight
from .exceptions import (
    AlpacaAdapterError,
    AlpacaAuthError,
    AlpacaBlockedEndpointError,
    AlpacaInputError,
    AlpacaPaginationIncompleteError,
    AlpacaRateLimitError,
    AlpacaSubscriptionError,
    USCalendarError,
)
from .historical import (
    AlpacaHistoricalOptions,
    AlpacaHistoricalStocks,
    StockBarsResult,
    USOptionBar,
    USOptionQuote,
    USOptionSnapshot,
    USOptionTrade,
    USStockBar,
)
from .indices import AlpacaIndexDiscovery, IndexDiscoveryReport, IndexOptionCapability, IndexSnapshot
from .live_bridge import AlpacaUSLiveBridge, USRealtimeEvent
from .snapshots import ImmutableSnapshotStore, StoredSnapshot

__all__ = [
    "AlpacaAdapterError",
    "AlpacaAssetsDiscovery",
    "AlpacaAuthError",
    "AlpacaBlockedEndpointError",
    "AlpacaCoveragePreflight",
    "AlpacaCredential",
    "AlpacaDataClient",
    "AlpacaHTTPResponse",
    "AlpacaHistoricalOptions",
    "AlpacaHistoricalStocks",
    "AlpacaIndexDiscovery",
    "AlpacaInputError",
    "AlpacaOptionsContractDiscovery",
    "AlpacaPaginationIncompleteError",
    "AlpacaRateLimitError",
    "AlpacaRateLimiter",
    "AlpacaSubscriptionError",
    "AlpacaUSLiveBridge",
    "AssetDiscoveryReport",
    "AssetSnapshot",
    "CANONICAL_US_OPTIONS_EXCHANGE",
    "ImmutableSnapshotStore",
    "IndexDiscoveryReport",
    "IndexOptionCapability",
    "IndexSnapshot",
    "NY_TZ",
    "OPTION_FEEDS",
    "OPTION_HISTORY_EARLIEST",
    "OptionContractsSnapshot",
    "OptionDiscoveryReport",
    "PaginatedResult",
    "STOCK_ADJUSTMENTS",
    "STOCK_FEEDS",
    "SUPPORTED_TIMEFRAMES",
    "StockBarsResult",
    "StoredSnapshot",
    "USCalendar",
    "USCalendarError",
    "USOptionBar",
    "USOptionQuote",
    "USOptionSnapshot",
    "USOptionTrade",
    "USRealtimeEvent",
    "USStockBar",
    "UTC_TZ",
    "diff_asset_snapshots",
    "inspect_alpaca_credentials",
    "resolve_alpaca_credential",
]
