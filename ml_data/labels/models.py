"""Leakage-safe label record model with explicit decision, cutoff, executable, and availability timestamps."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple


@dataclass(frozen=True)
class LabelRecord:
    instrument_id: str
    market: str
    exchange: str
    asset_class: str
    timeframe: str
    horizon_bars: int
    label_method: str
    config_version: str

    # Explicit anti-leakage timestamps (all UTC)
    decision_ts_utc: datetime
    feature_cutoff_utc: datetime
    earliest_executable_utc: Optional[datetime]
    label_start_ts_utc: Optional[datetime]
    label_end_ts_utc: Optional[datetime]
    label_available_ts_utc: Optional[datetime]

    # Targets (None when incomplete)
    gross_return: Optional[Decimal]
    net_return: Optional[Decimal]
    direction: Optional[int]          # +1, 0, -1
    mfe: Optional[Decimal]            # Maximum Favourable Excursion (return)
    mae: Optional[Decimal]            # Maximum Adverse Excursion (return, <= 0 for adverse)
    bars_to_exit: Optional[int]
    completion_status: str            # COMPLETE | INCOMPLETE_HORIZON | INCOMPLETE_SESSION_BOUNDARY | MISSING_BAR_GAP | AMBIGUOUS_BARRIER

    # Provenance
    dataset_id: Optional[str] = None
    dataset_version: Optional[str] = None
    manifest_sha256: Optional[str] = None
    spec_version_id: Optional[int] = None
    quality_flags: Tuple[str, ...] = ()
