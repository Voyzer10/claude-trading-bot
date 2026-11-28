"""Exceptions for the unified cross-market canonical storage subsystem."""
from __future__ import annotations


class StorageError(RuntimeError):
    """Base error for canonical market data storage."""


class PrecisionLossError(StorageError):
    """Raised when a Decimal value cannot be represented without rounding or precision loss."""


class ManifestError(StorageError):
    """Raised when a dataset manifest is invalid or fails SHA-256 checksum verification."""


class DatasetVersionConflictError(ManifestError):
    """Raised when an immutable dataset version or duplicate key has conflicting content."""


class SchemaValidationError(StorageError):
    """Raised when a canonical candle, quote, or trade violates schema invariants."""
