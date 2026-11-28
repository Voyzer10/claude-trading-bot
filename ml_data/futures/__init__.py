"""US Futures (Databento / CME Globex) market data adapter."""
from __future__ import annotations

from .client import DatabentoHistoricalClient, DatabentoHTTPResponse
from .config import (
    CANDIDATE_INDEX_FUTURES_ROOTS,
    CME_TZ,
    DATABENTO_DATASET,
    DATABENTO_SCHEMAS,
    DATABENTO_SYMBOLOGY_TYPES,
    UTC_TZ,
    CMEGlobexCalendar,
    DatabentoCredential,
    DatabentoRateLimiter,
    inspect_databento_credentials,
    resolve_databento_credential,
)
from .continuous import (
    SUPPORTED_ADJUSTMENT_POLICIES,
    SUPPORTED_ROLL_RULES,
    ContinuousContractBuilder,
    ContinuousSeriesBar,
)
from .contract_discovery import FuturesContractDiscovery, FuturesDiscoveryReport
from .coverage import FuturesCoveragePreflight
from .exceptions import (
    FuturesAdapterError,
    FuturesAuthError,
    FuturesBlockedEndpointError,
    FuturesInputError,
    FuturesLicensingError,
    FuturesRateLimitError,
    FuturesSubscriptionError,
)
from .historical import DatabentoHistoricalFutures, FuturesHistoricalResult, FuturesOHLCVBar
from .instrument_definitions import DatabentoDefinitionRecord, parse_definition_records
from .provider_evaluation import PROVIDER_EVALUATIONS, FuturesProviderEvaluation

__all__ = [
    "CANDIDATE_INDEX_FUTURES_ROOTS",
    "CMEGlobexCalendar",
    "CME_TZ",
    "ContinuousContractBuilder",
    "ContinuousSeriesBar",
    "DATABENTO_DATASET",
    "DATABENTO_SCHEMAS",
    "DATABENTO_SYMBOLOGY_TYPES",
    "DatabentoCredential",
    "DatabentoDefinitionRecord",
    "DatabentoHistoricalClient",
    "DatabentoHistoricalFutures",
    "DatabentoHTTPResponse",
    "DatabentoRateLimiter",
    "FuturesAdapterError",
    "FuturesAuthError",
    "FuturesBlockedEndpointError",
    "FuturesContractDiscovery",
    "FuturesCoveragePreflight",
    "FuturesDiscoveryReport",
    "FuturesHistoricalResult",
    "FuturesInputError",
    "FuturesLicensingError",
    "FuturesOHLCVBar",
    "FuturesProviderEvaluation",
    "FuturesRateLimitError",
    "FuturesSubscriptionError",
    "PROVIDER_EVALUATIONS",
    "SUPPORTED_ADJUSTMENT_POLICIES",
    "SUPPORTED_ROLL_RULES",
    "UTC_TZ",
    "inspect_databento_credentials",
    "parse_definition_records",
    "resolve_databento_credential",
]
