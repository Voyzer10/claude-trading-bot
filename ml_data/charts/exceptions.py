"""Exceptions for the Phase 0 ML research chart contract."""
from __future__ import annotations


class ChartContractError(ValueError):
    """Raised when a ChartSpec, overlay, theme, snapshot manifest or chart input violates the chart contract."""


class LookaheadError(ChartContractError):
    """Raised when a chart input (visible or warm-up candle) is not available at the decision timestamp."""


class ProvenanceError(ChartContractError):
    """Raised when chart inputs do not match the dataset manifest / instrument specification provenance."""


class ImageValidationError(ChartContractError):
    """Raised when a chart image is missing, malformed, the wrong format/size, or fails its SHA-256 check."""
