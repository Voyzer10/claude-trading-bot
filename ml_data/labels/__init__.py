"""Phase 2B — Leakage-Safe Label Engine."""
from __future__ import annotations

from .config import LabelConfig
from .engine import LabelEngine
from .models import LabelRecord
from .splits import LeakageError, PurgedEmbargoSplit, purged_embargo_split, validate_no_leakage
from .storage import LABEL_ARROW_SCHEMA, read_labels_parquet, write_labels_parquet

__all__ = [
    "LABEL_ARROW_SCHEMA",
    "LabelConfig",
    "LabelEngine",
    "LabelRecord",
    "LeakageError",
    "PurgedEmbargoSplit",
    "purged_embargo_split",
    "read_labels_parquet",
    "validate_no_leakage",
    "write_labels_parquet",
]
