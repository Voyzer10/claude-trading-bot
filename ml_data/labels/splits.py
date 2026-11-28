"""Chronological purged and embargoed train/test split validation utilities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Sequence, Tuple

from .models import LabelRecord


class LeakageError(RuntimeError):
    """Raised when train/test split validation detects label overlap, embargo violation, or future leakage."""


@dataclass(frozen=True)
class PurgedEmbargoSplit:
    train: List[LabelRecord]
    test: List[LabelRecord]
    purged_count: int
    embargoed_count: int


def purged_embargo_split(
    records: Sequence[LabelRecord],
    *,
    test_start_utc: datetime,
    test_end_utc: datetime,
    embargo_delta: timedelta = timedelta(0),
) -> PurgedEmbargoSplit:
    """Create a purged & embargoed chronological split around [test_start_utc, test_end_utc]."""
    ordered = sorted(records, key=lambda x: (x.decision_ts_utc, x.instrument_id, x.horizon_bars))
    test: List[LabelRecord] = [r for r in ordered if test_start_utc <= r.decision_ts_utc <= test_end_utc]
    test_avail_max = max((r.label_available_ts_utc or r.decision_ts_utc) for r in test) if test else test_end_utc
    embargo_end = test_avail_max + embargo_delta

    train: List[LabelRecord] = []
    purged = 0
    embargoed = 0

    for r in ordered:
        if test_start_utc <= r.decision_ts_utc <= test_end_utc:
            continue
        # Purge any train record whose label interval [decision, label_available] overlaps test window
        avail = r.label_available_ts_utc or r.decision_ts_utc
        if r.decision_ts_utc < test_start_utc and avail >= test_start_utc:
            purged += 1
            continue
        # Embargo records following test_end_utc through test_avail_max + embargo_delta
        if test_end_utc < r.decision_ts_utc <= embargo_end:
            embargoed += 1
            continue
        train.append(r)

    return PurgedEmbargoSplit(train=train, test=test, purged_count=purged, embargoed_count=embargoed)


def validate_no_leakage(
    train: Sequence[LabelRecord],
    test: Sequence[LabelRecord],
    *,
    embargo_delta: timedelta = timedelta(0),
) -> None:
    """Assert zero label overlap, zero embargo violations, and strict feature_cutoff <= decision_ts."""
    for r in list(train) + list(test):
        if r.feature_cutoff_utc > r.decision_ts_utc:
            raise LeakageError(f"Feature cutoff {r.feature_cutoff_utc} exceeds decision_ts {r.decision_ts_utc}")
        if r.earliest_executable_utc is not None and r.earliest_executable_utc < r.feature_cutoff_utc:
            raise LeakageError(f"Earliest executable {r.earliest_executable_utc} precedes feature_cutoff {r.feature_cutoff_utc}")

    if not train or not test:
        return
    test_min = min(r.decision_ts_utc for r in test)
    test_max = max((r.label_available_ts_utc or r.decision_ts_utc) for r in test)
    embargo_end = test_max + embargo_delta

    for tr in train:
        tr_avail = tr.label_available_ts_utc or tr.decision_ts_utc
        if tr.decision_ts_utc < test_min and tr_avail >= test_min:
            raise LeakageError(
                f"Train label {tr.instrument_id}@{tr.decision_ts_utc.isoformat()} overlaps test window (available {tr_avail.isoformat()})"
            )
        if test_max < tr.decision_ts_utc <= embargo_end:
            raise LeakageError(
                f"Train label {tr.instrument_id}@{tr.decision_ts_utc.isoformat()} violates embargo window ending {embargo_end.isoformat()}"
            )
