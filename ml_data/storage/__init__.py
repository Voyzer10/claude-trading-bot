"""Unified cross-market canonical storage, Parquet I/O, manifests, and dataset registry."""
from __future__ import annotations

from .candle_store import CanonicalCandleStore
from .canonical_schema import (
    CANONICAL_SCHEMA_VERSION,
    STANDARD_TIMEFRAMES_MINUTES,
    CanonicalCandle,
    CanonicalQuote,
    CanonicalTrade,
    resample_candles,
)
from .checkpoints import IngestionCheckpointStore
from .dataset_registry import DatasetRegistry
from .exceptions import (
    DatasetVersionConflictError,
    ManifestError,
    PrecisionLossError,
    SchemaValidationError,
    StorageError,
)
from .manifests import DatasetManifest, compute_file_sha256, verify_manifest, write_manifest
from .parquet import read_candles_parquet, write_candles_parquet

__all__ = [
    "CANONICAL_SCHEMA_VERSION",
    "CanonicalCandle",
    "CanonicalCandleStore",
    "CanonicalQuote",
    "CanonicalTrade",
    "DatasetManifest",
    "DatasetRegistry",
    "DatasetVersionConflictError",
    "IngestionCheckpointStore",
    "ManifestError",
    "PrecisionLossError",
    "STANDARD_TIMEFRAMES_MINUTES",
    "SchemaValidationError",
    "StorageError",
    "compute_file_sha256",
    "read_candles_parquet",
    "resample_candles",
    "verify_manifest",
    "write_candles_parquet",
    "write_manifest",
]
