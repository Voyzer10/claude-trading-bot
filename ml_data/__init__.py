"""Multi-market ML data foundation package (Phase 1A: Universal Instrument Schemas & Registry)."""
from __future__ import annotations

from .instruments.enums import (
    AssetClass,
    ContractType,
    InstrumentStatus,
    MarginType,
    Market,
    OptionRight,
    Segment,
    SettlementType,
)
from .instruments.registry import InstrumentRegistry
from .instruments.schemas import (
    SCHEMA_VERSION,
    Instrument,
    InstrumentSpecVersion,
    InstrumentValidationError,
    ProviderInstrumentMapping,
)

__all__ = [
    "AssetClass",
    "ContractType",
    "Instrument",
    "InstrumentRegistry",
    "InstrumentSpecVersion",
    "InstrumentStatus",
    "InstrumentValidationError",
    "MarginType",
    "Market",
    "OptionRight",
    "ProviderInstrumentMapping",
    "SCHEMA_VERSION",
    "Segment",
    "SettlementType",
]
