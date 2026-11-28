"""Data snapshot identity, no-lookahead/provenance validation and the ChartSnapshotManifest (Chart Contract v1.0.0).

Three separate identities:
  data_snapshot_id   SHA-256 over the exact canonical input data and its provenance (what the chart shows).
  chart_snapshot_id  SHA-256 over data_snapshot_id + chart_spec_hash + renderer + theme + font fingerprint.
  image_sha256       SHA-256 of the actual PNG bytes.
No renderer and no indicator computation live here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, Inexact, InvalidOperation, localcontext
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ..instruments.identity import compute_spec_hash, normalize_decimal_str
from ..instruments.schemas import InstrumentSpecVersion
from ..storage.canonical_schema import CANONICAL_SCHEMA_VERSION, STANDARD_TIMEFRAMES_MINUTES, CanonicalCandle
from ..storage.manifests import DatasetManifest
from .exceptions import ChartContractError, ImageValidationError, LookaheadError, ProvenanceError
from .hashing import canonical_json, is_sha256_hex, require_sha256_hex, sha256_hex, sha256_of_payload
from .png import validate_chart_png
from .profiles import CHART_CONTRACT_VERSION, PRICE_AXIS_POLICY_PADDED_RANGE_V1, get_profile
from .spec import (
    AVAILABILITY_AS_KNOWN,
    AVAILABILITY_EVENT_TIME,
    AVAILABILITY_MODES,
    ChartSpec,
    RendererInfo,
    display_timezone_for_segment,
    parse_utc,
    require_iana_timezone,
    require_utc_datetime,
    utc_iso,
)
from .themes import get_theme

UTC = timezone.utc
DATA_SNAPSHOT_CONTRACT = "chart-data-snapshot/1.0.0"
MODEL_READY_QUALITY_STATUS = "VERIFIED"

STATUS_PENDING_RENDER = "PENDING_RENDER"
STATUS_INCOMPLETE = "INCOMPLETE"
STATUS_FAILED = "FAILED"
STATUS_READY = "READY"
STATUS_MODEL_READY = "MODEL_READY"
RENDER_STATUSES = (STATUS_PENDING_RENDER, STATUS_INCOMPLETE, STATUS_FAILED, STATUS_READY, STATUS_MODEL_READY)

REASON_INSUFFICIENT_VISIBLE = "INSUFFICIENT_VISIBLE_CANDLES"
REASON_INSUFFICIENT_WARMUP = "INSUFFICIENT_WARMUP_CANDLES"
REASON_VWAP_CONTEXT = "INSUFFICIENT_VWAP_SESSION_CONTEXT"
REASON_QUALITY = "QUALITY_NOT_VERIFIED"
REASON_GAPS = "INTRA_SESSION_GAPS"
REASON_PAGINATION = "DATASET_PAGINATION_INCOMPLETE"
REASON_RENDER_FAILED = "RENDER_FAILED"
INCOMPLETE_REASONS = (REASON_INSUFFICIENT_VISIBLE, REASON_INSUFFICIENT_WARMUP, REASON_VWAP_CONTEXT)
MODEL_READY_BLOCKERS = (REASON_QUALITY, REASON_GAPS, REASON_PAGINATION)

BASIS_AS_KNOWN = "AS_KNOWN_AT_DECISION"
BASIS_RETROSPECTIVE = "RETROSPECTIVE_EVENT_TIME"   # backfilled research reconstruction; not live-faithful evidence
POINT_IN_TIME_BASIS = {AVAILABILITY_AS_KNOWN: BASIS_AS_KNOWN, AVAILABILITY_EVENT_TIME: BASIS_RETROSPECTIVE}

# Sessions whose official start the v1 contract can prove from the exchange calendar (session_bounds open).
_NON_PROVABLE_SESSIONS = ("PRE_MARKET", "POST_MARKET")


# ---------------------------------------------------------------------------------------------------------------
# Immutability helpers
# ---------------------------------------------------------------------------------------------------------------

def _freeze(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(_freeze(v) for v in obj)
    return obj


def _thaw(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {k: _thaw(v) for k, v in obj.items()}
    if isinstance(obj, tuple):
        return [_thaw(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------------------------------------------
# Display-time metadata (DST-safe)
# ---------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class AxisTimestamp:
    """One x-axis instant: UTC is authoritative; the local label always carries the offset and zone abbreviation."""

    utc: str
    local_iso: str            # ISO-8601 with explicit UTC offset, e.g. 2026-11-01T01:30:00-04:00
    utc_offset_minutes: int
    tz_abbreviation: str
    label: str                # e.g. "2026-11-01 01:30 EDT": never ambiguous across DST transitions

    def to_dict(self) -> Dict[str, Any]:
        return {"utc": self.utc, "local_iso": self.local_iso, "utc_offset_minutes": self.utc_offset_minutes,
                "tz_abbreviation": self.tz_abbreviation, "label": self.label}


def axis_timestamp(utc_dt: datetime, display_timezone: str) -> AxisTimestamp:
    utc_dt = require_utc_datetime(utc_dt, "axis timestamp")
    local = utc_dt.astimezone(ZoneInfo(require_iana_timezone(display_timezone)))
    off = local.utcoffset()
    assert off is not None
    abbr = local.tzname() or "UTC"
    return AxisTimestamp(utc=utc_iso(utc_dt), local_iso=local.isoformat(),
                         utc_offset_minutes=int(off.total_seconds() // 60), tz_abbreviation=abbr,
                         label=f"{local.strftime('%Y-%m-%d %H:%M')} {abbr}")


# ---------------------------------------------------------------------------------------------------------------
# Dataset manifest identity (float-free)
# ---------------------------------------------------------------------------------------------------------------

def _canonical_metric(val: Any, path: str) -> Any:
    """Exact, float-free form of a quality_summary value.

    int / str / bool / None are kept. Decimal -> canonical decimal string. float -> its EXACT binary value as a
    canonical decimal string (Decimal(float), no rounding; e.g. 0.5 -> "0.5"). NaN / Infinity are rejected.
    Mappings and lists are normalized recursively.
    """
    if isinstance(val, bool) or val is None or isinstance(val, (int, str)):
        return val
    if isinstance(val, float):
        if val != val or val in (float("inf"), float("-inf")):
            raise ProvenanceError(f"quality_summary value at {path} is NaN/Infinity")
        return normalize_decimal_str(Decimal(val))
    if isinstance(val, Decimal):
        if not val.is_finite():
            raise ProvenanceError(f"quality_summary value at {path} is NaN/Infinity")
        return normalize_decimal_str(val)
    if isinstance(val, Mapping):
        out = {}
        for k, v in val.items():
            if not isinstance(k, str):
                raise ProvenanceError(f"quality_summary key at {path} must be a string (got {k!r})")
            out[k] = _canonical_metric(v, f"{path}.{k}")
        return out
    if isinstance(val, (list, tuple)):
        return [_canonical_metric(v, f"{path}[{i}]") for i, v in enumerate(val)]
    raise ProvenanceError(f"quality_summary value at {path} has unsupported type {type(val).__name__}")


def dataset_manifest_identity(manifest: DatasetManifest) -> Tuple[str, Tuple[str, ...]]:
    """(manifest SHA-256, sorted source partition SHA-256s).

    Covers DatasetManifest.semantic_dict() (created_at_utc excluded) via the shared float-free canonical_json.
    Partitions are identified by content SHA-256 only, so the identity does not depend on file locations.
    """
    sem = manifest.semantic_dict()
    shas = sorted(sem.pop("file_sha256s").values())
    sem.pop("file_paths")
    for s in shas:
        if not is_sha256_hex(s):
            raise ProvenanceError(f"dataset manifest has an invalid partition SHA-256: {s!r}")
    sem["partition_sha256s"] = shas
    sem["quality_summary"] = _canonical_metric(sem["quality_summary"], "quality_summary")
    for k, v in list(sem.items()):
        if isinstance(v, float):
            raise ProvenanceError(f"dataset manifest field {k} must not be a float")
    return sha256_of_payload(sem), tuple(shas)


# ---------------------------------------------------------------------------------------------------------------
# Data snapshot
# ---------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DataSnapshot:
    data_snapshot_id: str
    instrument_id: str
    market: str
    segment: str
    timeframe: str
    decision_timestamp_utc: datetime
    availability_mode: str
    point_in_time_basis: str
    visible_count: int
    warmup_count: int
    session_context_count: int
    visible_start_utc: datetime
    visible_end_utc: datetime                 # exclusive: timestamp_end_utc of the last visible candle
    warmup_start_utc: Optional[datetime]
    last_visible_event_time_utc: datetime
    last_visible_received_at_utc: datetime
    visible_low: str
    visible_high: str
    calendar_id: str
    calendar_version: str
    adjustment_mode: str
    dataset_id: str
    dataset_version: str
    dataset_manifest_sha256: str
    dataset_pagination_complete: bool
    source_snapshot_ids: Tuple[str, ...]
    source_file_sha256s: Tuple[str, ...]
    instrument_spec_version_id: int
    instrument_spec_hash: str
    instrument_spec_recorded_at_utc: datetime
    instrument_spec_known_at_decision: bool
    sessions_present: Tuple[str, ...]
    intra_session_gap_count: int
    missing_bar_count: int
    all_inputs_quality_verified: bool
    vwap_session_context_complete: bool
    vwap_session_context_issues: Tuple[str, ...]
    session_opens_utc: Tuple[Tuple[str, str], ...]   # (session_id, official open UTC) per visible session


def _check_lookahead(c: CanonicalCandle, decision: datetime, mode: str, role: str, i: int) -> None:
    where = f"{role} candle #{i} ({utc_iso(c.timestamp_start_utc)})"
    if c.timestamp_end_utc > decision:
        raise LookaheadError(f"{where} is not closed at the decision time (end {utc_iso(c.timestamp_end_utc)})")
    if c.event_time_utc > decision:
        raise LookaheadError(f"{where} event_time_utc {utc_iso(c.event_time_utc)} is after the decision time")
    if mode == AVAILABILITY_AS_KNOWN and c.received_at_utc > decision:
        raise LookaheadError(f"{where} received_at_utc {utc_iso(c.received_at_utc)} is after the decision time")


def _check_sequence(seq: Sequence[CanonicalCandle], what: str) -> None:
    for a, b in zip(seq, seq[1:]):
        if b.timestamp_start_utc <= a.timestamp_start_utc:
            raise ChartContractError(f"{what} must be strictly increasing (duplicate or out of order at {utc_iso(b.timestamp_start_utc)})")
        if b.timestamp_start_utc < a.timestamp_end_utc:
            raise ChartContractError(f"{what} overlap at {utc_iso(b.timestamp_start_utc)}")


def _official_session_open(calendar: Any, c: CanonicalCandle) -> Tuple[Optional[datetime], Optional[str]]:
    """Official start of c's trading session from the exchange calendar, or (None, why it cannot be proven)."""
    if c.trading_session in _NON_PROVABLE_SESSIONS:
        return None, f"SESSION_START_NOT_PROVABLE:{c.trading_session}:{c.session_id}"
    inner = getattr(calendar, "inner", None)
    bounds_fn = getattr(inner, "session_bounds", None)
    if bounds_fn is None:
        return None, f"CALENDAR_HAS_NO_SESSION_BOUNDS:{c.calendar_id}"
    try:
        bounds = bounds_fn(c.trading_date, require_verified=True)
    except Exception:  # noqa: BLE001 - an unverified year cannot prove the session start
        return None, f"CALENDAR_NOT_VERIFIED:{c.calendar_id}:{c.trading_date.isoformat()}"
    if bounds is None:
        return None, f"NOT_A_TRADING_DAY:{c.session_id}"
    return bounds[0].astimezone(UTC), None


def _vwap_session_context(
    *, calendar: Any, context: Sequence[CanonicalCandle], visible: Sequence[CanonicalCandle], tf: timedelta,
) -> Tuple[bool, Tuple[str, ...], Tuple[Tuple[str, str], ...]]:
    """Prove every visible session's VWAP starts at its official session open with no missing bars."""
    issues: List[str] = []
    opens: List[Tuple[str, str]] = []
    if calendar is None:
        return False, ("NO_EXCHANGE_CALENDAR",), ()
    md = getattr(calendar, "metadata", None)
    if md is None or md.calendar_id != visible[0].calendar_id or md.calendar_version != visible[0].calendar_version:
        raise ProvenanceError("the exchange calendar does not match the candles' calendar_id/calendar_version")
    sessions: Dict[str, List[CanonicalCandle]] = {}
    for c in visible:
        sessions.setdefault(c.session_id, []).append(c)
    for n, (sid, bars) in enumerate(sessions.items()):
        if calendar.trade_date_for(bars[0].timestamp_start_utc) != bars[0].trading_date:
            raise ProvenanceError(f"trading_date of session {sid} disagrees with the exchange calendar")
        seq = (list(context) + bars) if n == 0 else bars
        start, why = _official_session_open(calendar, bars[0])
        if start is None:
            issues.append(why or f"SESSION_START_UNKNOWN:{sid}")
            continue
        opens.append((sid, utc_iso(start)))
        if seq[0].timestamp_start_utc != start:
            issues.append(f"SESSION_OPEN_MISSING:{sid}")
            continue
        if any(b.timestamp_start_utc - a.timestamp_start_utc != tf for a, b in zip(seq, seq[1:])):
            issues.append(f"SESSION_BARS_MISSING:{sid}")
    return not issues, tuple(issues), tuple(opens)


def build_data_snapshot(
    *,
    instrument_id: str,
    timeframe: str,
    decision_timestamp_utc: datetime,
    availability_mode: str,
    visible_candles: Sequence[CanonicalCandle],
    warmup_candles: Sequence[CanonicalCandle],
    dataset_manifest: DatasetManifest,
    instrument_spec_version: InstrumentSpecVersion,
    session_context_candles: Sequence[CanonicalCandle] = (),
    calendar: Any = None,
) -> DataSnapshot:
    """Validate chart inputs (no lookahead, no synthetic bars, provenance) and compute data_snapshot_id.

    session_context_candles: the non-rendered bars from the official open of the first visible session up to the
    first visible candle (VWAP session context). They may repeat warm-up records, which must then be identical.
    calendar: the ExchangeCalendar matching the candles' calendar_id/version, used to prove session opens.
    """
    decision = require_utc_datetime(decision_timestamp_utc, "decision_timestamp_utc")
    if availability_mode not in AVAILABILITY_MODES:
        raise ChartContractError(f"availability_mode must be one of {AVAILABILITY_MODES}")
    if timeframe not in STANDARD_TIMEFRAMES_MINUTES:
        raise ChartContractError(f"Unsupported timeframe {timeframe!r}")
    visible, warmup, context = list(visible_candles), list(warmup_candles), list(session_context_candles)
    if not visible:
        raise ChartContractError("a chart needs at least one visible candle")
    every = warmup + visible
    allc = every + context
    for c in allc:
        if not isinstance(c, CanonicalCandle):
            raise ChartContractError("chart inputs must be CanonicalCandle records")

    # identity / single-series checks
    first = visible[0]
    for name in ("instrument_id", "timeframe", "market", "segment", "calendar_id", "calendar_version", "adjustment_mode"):
        vals = {getattr(c, name) for c in allc}
        if len(vals) != 1:
            raise ProvenanceError(f"chart inputs mix several {name} values: {sorted(vals)}")
    if first.instrument_id != instrument_id:
        raise ProvenanceError(f"candles are for {first.instrument_id}, not {instrument_id}")
    if first.timeframe != timeframe:
        raise ProvenanceError(f"candles are {first.timeframe}, not {timeframe}")

    # ordering: strictly increasing, non-overlapping; warm-up strictly before the first visible candle
    _check_sequence(every, "candles")
    _check_sequence(context, "session context candles")
    if context:
        if any(c.session_id != first.session_id for c in context):
            raise ChartContractError("session context candles must belong to the first visible session")
        if context[-1].timestamp_end_utc != first.timestamp_start_utc:
            raise ChartContractError("session context must end exactly where the visible window starts")
        warm_by_start = {c.timestamp_start_utc: c for c in warmup}
        for c in context:
            w = warm_by_start.get(c.timestamp_start_utc)
            if w is not None and w.to_dict() != c.to_dict():
                raise ProvenanceError(f"session context record at {utc_iso(c.timestamp_start_utc)} differs from warm-up")

    # no lookahead (visible, warm-up and session context: overlays may only use data known at the decision time)
    for role, seq in (("warm-up", warmup), ("session-context", context), ("visible", visible)):
        for i, c in enumerate(seq):
            _check_lookahead(c, decision, availability_mode, role, i)

    # no synthetic candles: gaps inside a session are detected and recorded, never filled
    tf = timedelta(minutes=STANDARD_TIMEFRAMES_MINUTES[timeframe])
    gaps = missing = 0
    for a, b in zip(every, every[1:]):
        if a.session_id == b.session_id:
            step = b.timestamp_start_utc - a.timestamp_start_utc
            if step > tf:
                gaps += 1
                missing += int(step // tf) - (0 if step % tf else 1)

    # provenance against the dataset manifest
    m = dataset_manifest
    if not isinstance(m, DatasetManifest):
        raise ProvenanceError("dataset_manifest must be a DatasetManifest")
    if m.schema_version != CANONICAL_SCHEMA_VERSION:
        raise ProvenanceError(f"dataset schema_version {m.schema_version!r} != canonical {CANONICAL_SCHEMA_VERSION!r}")
    if instrument_id not in m.instrument_ids:
        raise ProvenanceError(f"{instrument_id} is not in dataset {m.dataset_id}@{m.dataset_version}")
    cal_key = f"{first.calendar_id}:{first.calendar_version}"
    if cal_key not in m.calendar_versions:
        raise ProvenanceError(f"calendar {cal_key} is not recorded in the dataset manifest")
    if first.adjustment_mode not in m.adjustment_modes:
        raise ProvenanceError(f"adjustment_mode {first.adjustment_mode} is not recorded in the dataset manifest")
    if first.market not in m.markets:
        raise ProvenanceError(f"market {first.market} is not recorded in the dataset manifest")
    if not m.file_sha256s:
        raise ProvenanceError("dataset manifest has no source partitions")
    a_start = parse_utc(m.actual_start_utc, "actual_start_utc", required=False)
    a_end = parse_utc(m.actual_end_utc, "actual_end_utc", required=False)
    for c in allc:
        if c.dataset_version != m.dataset_version:
            raise ProvenanceError(f"candle dataset_version {c.dataset_version!r} != manifest {m.dataset_version!r}")
        if c.source_snapshot_id not in m.source_snapshot_ids:
            raise ProvenanceError(f"source_snapshot_id {c.source_snapshot_id!r} is not in the dataset manifest")
        if c.provider not in m.providers or c.provider_feed not in m.feeds:
            raise ProvenanceError(f"provider/feed {c.provider}/{c.provider_feed} not recorded in the dataset manifest")
        if (a_start and c.timestamp_start_utc < a_start) or (a_end and c.timestamp_end_utc > a_end):
            raise ProvenanceError(f"candle {utc_iso(c.timestamp_start_utc)} is outside the dataset's actual range")
    man_sha, part_shas = dataset_manifest_identity(m)

    # effective-dated, point-in-time instrument specification revision
    sv = instrument_spec_version
    if not isinstance(sv, InstrumentSpecVersion):
        raise ProvenanceError("instrument_spec_version must be an InstrumentSpecVersion")
    if sv.instrument_id != instrument_id:
        raise ProvenanceError("instrument specification revision is for a different instrument")
    if isinstance(sv.version_id, bool) or not isinstance(sv.version_id, int):
        raise ProvenanceError("instrument spec version_id must be an int")
    require_sha256_hex(sv.spec_hash, "instrument spec_hash")
    if not isinstance(sv.specification, Mapping):
        raise ProvenanceError("instrument specification must be a mapping")
    try:
        actual_spec_hash = compute_spec_hash(dict(sv.specification))
    except (TypeError, ValueError) as exc:
        raise ProvenanceError(f"instrument specification is not hashable canonically: {exc}") from None
    if actual_spec_hash != sv.spec_hash:
        raise ProvenanceError("instrument spec_hash does not match its specification "
                              f"(recorded {sv.spec_hash}, recomputed {actual_spec_hash})")
    eff_from = require_utc_datetime(sv.effective_from, "spec effective_from") if sv.effective_from else None
    eff_to = require_utc_datetime(sv.effective_to, "spec effective_to") if sv.effective_to else None
    if (eff_from and eff_from > decision) or (eff_to and eff_to <= decision):
        raise ProvenanceError("instrument specification revision is not effective at the decision timestamp")
    try:
        recorded = require_utc_datetime(sv.recorded_at, "spec recorded_at")
    except ChartContractError as exc:
        raise ProvenanceError(str(exc)) from None
    known_at_decision = recorded <= decision
    if availability_mode == AVAILABILITY_AS_KNOWN and not known_at_decision:
        raise LookaheadError("instrument specification revision was recorded after the decision timestamp; "
                             "it cannot be claimed as known at decision time (use EVENT_TIME for retrospective data)")

    vwap_ok, vwap_issues, opens = _vwap_session_context(calendar=calendar, context=context, visible=visible, tf=tf)

    last = visible[-1]
    payload = {
        "data_snapshot_contract": DATA_SNAPSHOT_CONTRACT,
        "instrument_id": instrument_id,
        "timeframe": timeframe,
        "adjustment_mode": first.adjustment_mode,
        "calendar_id": first.calendar_id,
        "calendar_version": first.calendar_version,
        "decision_timestamp_utc": utc_iso(decision),
        "availability_mode": availability_mode,
        "point_in_time_basis": POINT_IN_TIME_BASIS[availability_mode],
        "window": {
            "visible_start_utc": utc_iso(visible[0].timestamp_start_utc),
            "visible_end_utc": utc_iso(last.timestamp_end_utc),
            "visible_count": len(visible),
            "warmup_start_utc": utc_iso(warmup[0].timestamp_start_utc) if warmup else None,
            "warmup_count": len(warmup),
            "session_context_count": len(context),
        },
        "instrument_spec": {
            "version_id": sv.version_id, "spec_hash": sv.spec_hash,
            "effective_from": utc_iso(eff_from) if eff_from else None,
            "effective_to": utc_iso(eff_to) if eff_to else None,
            "recorded_at": utc_iso(recorded),
            "known_at_decision": known_at_decision,
        },
        "dataset": {
            "dataset_id": m.dataset_id, "dataset_version": m.dataset_version,
            "manifest_sha256": man_sha, "partition_sha256s": list(part_shas),
        },
        "session_context": {
            "official_session_opens_utc": [list(x) for x in opens],
            "vwap_session_context_complete": vwap_ok,
            "issues": list(vwap_issues),
        },
        "warmup_records": [c.to_dict() for c in warmup],
        "session_context_records": [c.to_dict() for c in context],
        "visible_records": [c.to_dict() for c in visible],
    }
    return DataSnapshot(
        data_snapshot_id=sha256_of_payload(payload),
        instrument_id=instrument_id, market=first.market, segment=first.segment, timeframe=timeframe,
        decision_timestamp_utc=decision, availability_mode=availability_mode,
        point_in_time_basis=POINT_IN_TIME_BASIS[availability_mode],
        visible_count=len(visible), warmup_count=len(warmup), session_context_count=len(context),
        visible_start_utc=visible[0].timestamp_start_utc, visible_end_utc=last.timestamp_end_utc,
        warmup_start_utc=warmup[0].timestamp_start_utc if warmup else None,
        last_visible_event_time_utc=last.event_time_utc, last_visible_received_at_utc=last.received_at_utc,
        visible_low=normalize_decimal_str(min(c.low for c in visible)),
        visible_high=normalize_decimal_str(max(c.high for c in visible)),
        calendar_id=first.calendar_id, calendar_version=first.calendar_version, adjustment_mode=first.adjustment_mode,
        dataset_id=m.dataset_id, dataset_version=m.dataset_version, dataset_manifest_sha256=man_sha,
        dataset_pagination_complete=bool(m.pagination_complete),
        source_snapshot_ids=tuple(sorted({c.source_snapshot_id for c in allc})), source_file_sha256s=part_shas,
        instrument_spec_version_id=sv.version_id, instrument_spec_hash=sv.spec_hash,
        instrument_spec_recorded_at_utc=recorded, instrument_spec_known_at_decision=known_at_decision,
        sessions_present=tuple(sorted({c.trading_session for c in allc})),
        intra_session_gap_count=gaps, missing_bar_count=missing,
        all_inputs_quality_verified=all(c.quality_status == MODEL_READY_QUALITY_STATUS for c in allc),
        vwap_session_context_complete=vwap_ok, vwap_session_context_issues=vwap_issues, session_opens_utc=opens,
    )


def require_single_availability_mode(modes: Iterable[str]) -> str:
    """A model dataset is either AS_KNOWN_AT_DECISION or EVENT_TIME (retrospective); the two are never mixed."""
    found = set(modes)
    if len(found) != 1 or not found <= set(AVAILABILITY_MODES):
        raise ChartContractError(f"A model dataset must use exactly one availability mode; found {sorted(found)}")
    return next(iter(found))


# ---------------------------------------------------------------------------------------------------------------
# Chart identity
# ---------------------------------------------------------------------------------------------------------------

def compute_chart_snapshot_id(*, data_snapshot_id: str, chart_spec_hash: str, renderer: RendererInfo,
                              theme_id: str, theme_version: str) -> str:
    require_sha256_hex(data_snapshot_id, "data_snapshot_id")
    require_sha256_hex(chart_spec_hash, "chart_spec_hash")
    theme = get_theme(theme_id, theme_version)
    return sha256_of_payload({
        "chart_contract_version": CHART_CONTRACT_VERSION,
        "data_snapshot_id": data_snapshot_id,
        "chart_spec_hash": chart_spec_hash,
        "renderer": renderer.to_dict(),                 # includes font_fingerprint
        "theme": {"theme_id": theme.theme_id, "theme_version": theme.theme_version, "theme_hash": theme.theme_hash()},
    })


# ---------------------------------------------------------------------------------------------------------------
# Price-axis bounds policy (Decimal only)
# ---------------------------------------------------------------------------------------------------------------

def price_axis_bounds(visible_low: Any, visible_high: Any, *, policy: str, padding_ratio: Any) -> Tuple[str, str]:
    """PADDED_RANGE_V1: [low - pad, high + pad]; pad = (high - low) * ratio, or (|high| or 1) * ratio if flat.

    Exact Decimal arithmetic (no float, no rounding); results are canonical decimal strings. Bounds are derived
    from the validated visible OHLC only; overlay values outside that range are clipped by the renderer.
    """
    if policy != PRICE_AXIS_POLICY_PADDED_RANGE_V1:
        raise ChartContractError(f"Unsupported price_axis_policy {policy!r}")
    vals = []
    for v, name in ((visible_low, "visible_low"), (visible_high, "visible_high"), (padding_ratio, "price_axis_padding_ratio")):
        s = _opt_dec_str(v, name)
        if s is None:
            raise ChartContractError(f"{name} is required for the price-axis policy")
        vals.append(Decimal(s))
    low, high, ratio = vals
    if high < low:
        raise ChartContractError("visible_high is below visible_low")
    if not Decimal("0") < ratio:
        raise ChartContractError("price_axis_padding_ratio must be positive")
    with localcontext() as ctx:
        ctx.prec = 80
        ctx.traps[Inexact] = True
        base = (high - low) if high > low else (abs(high) or Decimal("1"))
        pad = base * ratio
        lo, hi = low - pad, high + pad
    return normalize_decimal_str(lo), normalize_decimal_str(hi)


# ---------------------------------------------------------------------------------------------------------------
# Status derivation (shared by the builder, manifest validation and verification)
# ---------------------------------------------------------------------------------------------------------------

def _opt_dec_str(v: Any, name: str) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (float, bool)) or not isinstance(v, (str, Decimal)):
        raise ChartContractError(f"{name} must be a Decimal or decimal string (no float)")
    try:
        d = Decimal(v) if isinstance(v, str) else v
    except InvalidOperation:
        raise ChartContractError(f"{name} is not a decimal: {v!r}") from None
    if not d.is_finite():
        raise ChartContractError(f"{name} must be finite")
    return normalize_decimal_str(d)


def derive_render_status(
    *,
    actual_visible: int,
    expected_visible: int,
    warmup: int,
    required_warmup: int,
    vwap_context_complete: Optional[bool],
    all_inputs_quality_verified: bool,
    intra_session_gap_count: int,
    dataset_pagination_complete: bool,
    has_image: bool,
    render_failed: bool,
) -> Tuple[str, Tuple[str, ...]]:
    """The only correct (render_status, status_reasons) for a chart's inputs and image state."""
    incomplete: List[str] = []
    if actual_visible < expected_visible:
        incomplete.append(REASON_INSUFFICIENT_VISIBLE)
    if warmup < required_warmup:
        incomplete.append(REASON_INSUFFICIENT_WARMUP)
    if vwap_context_complete is False:
        incomplete.append(REASON_VWAP_CONTEXT)
    if render_failed:
        return STATUS_FAILED, tuple(incomplete + [REASON_RENDER_FAILED])
    if incomplete:
        return STATUS_INCOMPLETE, tuple(incomplete)
    if not has_image:
        return STATUS_PENDING_RENDER, ()
    blockers: List[str] = []
    if not all_inputs_quality_verified:
        blockers.append(REASON_QUALITY)
    if intra_session_gap_count:
        blockers.append(REASON_GAPS)
    if not dataset_pagination_complete:
        blockers.append(REASON_PAGINATION)
    return (STATUS_READY if blockers else STATUS_MODEL_READY), tuple(blockers)


# ---------------------------------------------------------------------------------------------------------------
# Snapshot manifest
# ---------------------------------------------------------------------------------------------------------------

_DT_FIELDS = ("visible_start_utc", "visible_end_utc", "decision_timestamp_utc", "last_visible_event_time_utc",
              "last_visible_received_at_utc", "instrument_spec_recorded_at_utc", "created_at_utc")
_SHA_FIELDS = ("chart_snapshot_id", "chart_spec_hash", "data_snapshot_id", "dataset_manifest_sha256",
               "instrument_spec_hash", "theme_hash", "font_fingerprint")
_TUPLE_FIELDS = ("source_snapshot_ids", "source_file_sha256s", "display_utc_offsets_minutes", "sessions_present",
                 "status_reasons")
_COUNT_FIELDS = ("actual_visible_candle_count", "warmup_candle_count", "required_warmup_candle_count",
                 "session_context_candle_count", "intra_session_gap_count", "missing_bar_count",
                 "instrument_spec_version_id")
_BOOL_FIELDS = ("dataset_pagination_complete", "all_inputs_quality_verified", "instrument_spec_known_at_decision")


@dataclass(frozen=True)
class ChartSnapshotManifest:
    chart_contract_version: str
    chart_snapshot_id: str
    chart_spec_hash: str
    data_snapshot_id: str
    image_sha256: Optional[str]
    image_path: Optional[str]
    image_size_bytes: Optional[int]
    instrument_id: str
    timeframe: str
    chart_profile_id: str
    expected_visible_candle_count: int
    actual_visible_candle_count: int
    required_warmup_candle_count: int
    warmup_candle_count: int
    session_context_candle_count: int
    visible_start_utc: datetime
    visible_end_utc: datetime
    decision_timestamp_utc: datetime
    availability_mode: str
    point_in_time_basis: str
    last_visible_event_time_utc: datetime
    last_visible_received_at_utc: datetime
    display_timezone: str
    visible_start_display: Mapping[str, Any]
    visible_end_display: Mapping[str, Any]
    display_utc_offsets_minutes: Tuple[int, ...]
    calendar_id: str
    calendar_version: str
    adjustment_mode: str
    sessions_present: Tuple[str, ...]
    dataset_id: str
    dataset_version: str
    dataset_manifest_sha256: str
    dataset_pagination_complete: bool
    source_snapshot_ids: Tuple[str, ...]
    source_file_sha256s: Tuple[str, ...]
    instrument_spec_version_id: int
    instrument_spec_hash: str
    instrument_spec_recorded_at_utc: datetime
    instrument_spec_known_at_decision: bool
    theme_id: str
    theme_version: str
    theme_hash: str
    width_px: int
    height_px: int
    image_format: str
    color_mode: str
    color_space: str
    renderer_name: str
    renderer_version: str
    renderer_build_id: str
    font_fingerprint: str
    overlay_specs: Tuple[Mapping[str, Any], ...]
    vwap_session_context_complete: Optional[bool]
    visible_low: str
    visible_high: str
    price_axis_policy: str
    price_axis_padding_ratio: str
    price_axis_min: str
    price_axis_max: str
    all_inputs_quality_verified: bool
    intra_session_gap_count: int
    missing_bar_count: int
    render_status: str
    status_reasons: Tuple[str, ...]
    created_at_utc: datetime

    def __post_init__(self) -> None:
        if self.chart_contract_version != CHART_CONTRACT_VERSION:
            raise ChartContractError(f"Unsupported chart_contract_version {self.chart_contract_version!r}")
        for name in _SHA_FIELDS:
            require_sha256_hex(getattr(self, name), name)
        for name in _DT_FIELDS:
            object.__setattr__(self, name, require_utc_datetime(getattr(self, name), name))
        for name in _TUPLE_FIELDS:
            v = getattr(self, name)
            if isinstance(v, (str, bytes)) or not isinstance(v, (list, tuple)):
                raise ChartContractError(f"{name} must be a list")
            object.__setattr__(self, name, tuple(v))
        for s in self.source_file_sha256s:
            require_sha256_hex(s, "source_file_sha256s entry")
        # nested mappings are deep-frozen: a frozen manifest cannot be mutated through nested references
        for name in ("visible_start_display", "visible_end_display"):
            if not isinstance(getattr(self, name), Mapping):
                raise ChartContractError(f"{name} must be a mapping")
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        if isinstance(self.overlay_specs, (str, bytes)) or not isinstance(self.overlay_specs, (list, tuple)):
            raise ChartContractError("overlay_specs must be a list")
        object.__setattr__(self, "overlay_specs", _freeze(list(self.overlay_specs)))
        for name in ("visible_low", "visible_high"):
            v = _opt_dec_str(getattr(self, name), name)
            if v is None:
                raise ChartContractError(f"{name} is required")
            object.__setattr__(self, name, v)
        for name in ("price_axis_min", "price_axis_max", "price_axis_padding_ratio"):
            v = _opt_dec_str(getattr(self, name), name)
            if v is None:
                raise ChartContractError(f"{name} is required")
            object.__setattr__(self, name, v)
        if (self.price_axis_min, self.price_axis_max) != price_axis_bounds(
                self.visible_low, self.visible_high, policy=self.price_axis_policy,
                padding_ratio=self.price_axis_padding_ratio):
            raise ChartContractError("price-axis bounds do not follow the recorded price_axis_policy")
        for name in _COUNT_FIELDS:
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ChartContractError(f"{name} must be a non-negative int")
        for name in _BOOL_FIELDS:
            if not isinstance(getattr(self, name), bool):
                raise ChartContractError(f"{name} must be a bool")
        prof = get_profile(self.chart_profile_id)
        for name in ("width_px", "height_px", "image_format", "color_mode", "color_space"):
            if getattr(self, name) != getattr(prof, name):
                raise ChartContractError(f"{name} does not match profile {prof.profile_id}")
        if self.expected_visible_candle_count != prof.visible_candle_count:
            raise ChartContractError("expected_visible_candle_count does not match the profile")
        theme = get_theme(self.theme_id, self.theme_version)
        if self.theme_hash != theme.theme_hash():
            raise ChartContractError("theme_hash does not match the registered theme definition")
        require_iana_timezone(self.display_timezone)
        if self.availability_mode not in AVAILABILITY_MODES:
            raise ChartContractError("invalid availability_mode")
        if self.point_in_time_basis != POINT_IN_TIME_BASIS[self.availability_mode]:
            raise ChartContractError("point_in_time_basis does not match availability_mode")
        if not self.visible_start_utc < self.visible_end_utc <= self.decision_timestamp_utc:
            raise LookaheadError("visible window must satisfy visible_start < visible_end <= decision_timestamp")
        if self.last_visible_event_time_utc > self.decision_timestamp_utc:
            raise LookaheadError("last visible event time is after the decision timestamp")
        if self.instrument_spec_known_at_decision != (self.instrument_spec_recorded_at_utc <= self.decision_timestamp_utc):
            raise ChartContractError("instrument_spec_known_at_decision does not match recorded_at vs decision")
        if self.availability_mode == AVAILABILITY_AS_KNOWN:
            if self.last_visible_received_at_utc > self.decision_timestamp_utc:
                raise LookaheadError("last visible candle was received after the decision timestamp")
            if not self.instrument_spec_known_at_decision:
                raise LookaheadError("AS_KNOWN_AT_DECISION chart uses a spec revision recorded after the decision")
        if self.actual_visible_candle_count > self.expected_visible_candle_count:
            raise ChartContractError("more visible candles than the profile allows")
        if (self.intra_session_gap_count == 0) != (self.missing_bar_count == 0):
            raise ChartContractError("intra_session_gap_count and missing_bar_count are inconsistent")
        has_vwap = any(o.get("overlay_type") == "VWAP" for o in self.overlay_specs)
        if has_vwap != (self.vwap_session_context_complete is not None):
            raise ChartContractError("vwap_session_context_complete is recorded exactly when a VWAP overlay is present")
        if self.vwap_session_context_complete is not None and not isinstance(self.vwap_session_context_complete, bool):
            raise ChartContractError("vwap_session_context_complete must be a bool or null")
        self._check_image_and_status()

    def _check_image_and_status(self) -> None:
        if self.render_status not in RENDER_STATUSES:
            raise ChartContractError(f"render_status must be one of {RENDER_STATUSES}")
        has_image = self.image_sha256 is not None
        if has_image:
            require_sha256_hex(self.image_sha256, "image_sha256")
            if not isinstance(self.image_path, str) or not self.image_path:
                raise ChartContractError("image_path is required when image_sha256 is set")
            if isinstance(self.image_size_bytes, bool) or not isinstance(self.image_size_bytes, int) or self.image_size_bytes <= 0:
                raise ChartContractError("image_size_bytes must be a positive int when an image is recorded")
        elif self.image_path is not None or self.image_size_bytes is not None:
            raise ChartContractError("image_path/image_size_bytes require image_sha256")
        lo, hi = Decimal(self.price_axis_min), Decimal(self.price_axis_max)
        if not lo < hi or lo > Decimal(self.visible_low) or hi < Decimal(self.visible_high):
            raise ChartContractError("price-axis bounds must satisfy min < max and contain every visible low/high")
        status, reasons = derive_render_status(
            actual_visible=self.actual_visible_candle_count, expected_visible=self.expected_visible_candle_count,
            warmup=self.warmup_candle_count, required_warmup=self.required_warmup_candle_count,
            vwap_context_complete=self.vwap_session_context_complete,
            all_inputs_quality_verified=self.all_inputs_quality_verified,
            intra_session_gap_count=self.intra_session_gap_count,
            dataset_pagination_complete=self.dataset_pagination_complete,
            has_image=has_image, render_failed=self.render_status == STATUS_FAILED,
        )
        if (self.render_status, self.status_reasons) != (status, reasons):
            raise ChartContractError(
                f"forged or inconsistent status: manifest says {self.render_status} {list(self.status_reasons)}, "
                f"inputs require {status} {list(reasons)}")
        if status == STATUS_FAILED and has_image:
            raise ChartContractError("a FAILED render carries no image")

    @property
    def is_model_ready(self) -> bool:
        return self.render_status == STATUS_MODEL_READY

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for name in self.__dataclass_fields__:
            v = getattr(self, name)
            out[name] = utc_iso(v) if isinstance(v, datetime) else _thaw(v)
        return out

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def semantic_dict(self) -> Dict[str, Any]:
        d = self.to_dict()
        d.pop("created_at_utc")
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChartSnapshotManifest":
        fields = set(cls.__dataclass_fields__)
        unknown, missing = set(data) - fields, fields - set(data)
        if unknown or missing:
            raise ChartContractError(f"manifest keys mismatch: unknown={sorted(unknown)} missing={sorted(missing)}")
        d = dict(data)
        for name in _DT_FIELDS:
            d[name] = parse_utc(d[name], name)
        return cls(**d)

    @classmethod
    def from_json(cls, payload: str) -> "ChartSnapshotManifest":
        return cls.from_dict(json.loads(payload))


def _display_offsets(start: datetime, end: datetime, tz: str, step: timedelta) -> Tuple[int, ...]:
    zone, offs, t = ZoneInfo(tz), set(), start
    while t < end:
        o = t.astimezone(zone).utcoffset()
        assert o is not None
        offs.add(int(o.total_seconds() // 60))
        t += step
    return tuple(sorted(offs))


def _check_spec_against_data(spec: ChartSpec, ds: DataSnapshot) -> None:
    if spec.data_snapshot_id != ds.data_snapshot_id:
        raise ProvenanceError("ChartSpec.data_snapshot_id does not match the data snapshot")
    for name in ("instrument_id", "timeframe", "decision_timestamp_utc", "availability_mode"):
        if getattr(spec, name) != getattr(ds, name):
            raise ProvenanceError(f"ChartSpec.{name} does not match the data snapshot")
    expected_tz = display_timezone_for_segment(ds.segment)
    if spec.display_timezone != expected_tz:
        raise ChartContractError(f"display_timezone for {ds.segment} must be {expected_tz} (got {spec.display_timezone})")
    bad = set(ds.sessions_present) - set(spec.allowed_sessions)
    if bad:
        raise ChartContractError(f"chart inputs contain sessions not allowed by the spec: {sorted(bad)}")
    if ds.visible_count > spec.visible_candle_count:
        raise ChartContractError(f"{ds.visible_count} visible candles supplied; the profile shows exactly {spec.visible_candle_count}")
    if ds.warmup_count > spec.warmup_candle_count:
        raise ChartContractError(f"{ds.warmup_count} warm-up candles supplied; the spec declares {spec.warmup_candle_count}")
    has_vwap = any(o.overlay_type == "VWAP" for o in spec.overlay_specs)
    if ds.session_context_count and not has_vwap:
        raise ChartContractError("session context candles are only defined for VWAP charts")


def _derive_manifest(
    *,
    spec: ChartSpec,
    ds: DataSnapshot,
    renderer: RendererInfo,
    created_at_utc: datetime,
    image_sha256: Optional[str],
    image_size_bytes: Optional[int],
    image_path: Optional[str],
    render_failed: bool,
) -> ChartSnapshotManifest:
    """Every manifest field from (spec, data snapshot, renderer, theme) plus the image state; status derived."""
    _check_spec_against_data(spec, ds)
    theme = get_theme(spec.theme_id, spec.theme_version)
    spec_hash = spec.spec_hash()
    has_vwap = any(o.overlay_type == "VWAP" for o in spec.overlay_specs)
    vwap_ctx = ds.vwap_session_context_complete if has_vwap else None
    status, reasons = derive_render_status(
        actual_visible=ds.visible_count, expected_visible=spec.visible_candle_count, warmup=ds.warmup_count,
        required_warmup=spec.warmup_candle_count, vwap_context_complete=vwap_ctx,
        all_inputs_quality_verified=ds.all_inputs_quality_verified,
        intra_session_gap_count=ds.intra_session_gap_count, dataset_pagination_complete=ds.dataset_pagination_complete,
        has_image=image_sha256 is not None, render_failed=render_failed,
    )
    tf = timedelta(minutes=STANDARD_TIMEFRAMES_MINUTES[spec.timeframe])
    axis_min, axis_max = price_axis_bounds(ds.visible_low, ds.visible_high, policy=spec.price_axis_policy,
                                           padding_ratio=spec.price_axis_padding_ratio)
    return ChartSnapshotManifest(
        chart_contract_version=CHART_CONTRACT_VERSION,
        chart_snapshot_id=compute_chart_snapshot_id(data_snapshot_id=ds.data_snapshot_id, chart_spec_hash=spec_hash,
                                                    renderer=renderer, theme_id=spec.theme_id,
                                                    theme_version=spec.theme_version),
        chart_spec_hash=spec_hash, data_snapshot_id=ds.data_snapshot_id, image_sha256=image_sha256,
        image_path=image_path, image_size_bytes=image_size_bytes, instrument_id=spec.instrument_id,
        timeframe=spec.timeframe, chart_profile_id=spec.chart_profile_id,
        expected_visible_candle_count=spec.visible_candle_count, actual_visible_candle_count=ds.visible_count,
        required_warmup_candle_count=spec.warmup_candle_count, warmup_candle_count=ds.warmup_count,
        session_context_candle_count=ds.session_context_count, visible_start_utc=ds.visible_start_utc,
        visible_end_utc=ds.visible_end_utc, decision_timestamp_utc=ds.decision_timestamp_utc,
        availability_mode=ds.availability_mode, point_in_time_basis=ds.point_in_time_basis,
        last_visible_event_time_utc=ds.last_visible_event_time_utc,
        last_visible_received_at_utc=ds.last_visible_received_at_utc, display_timezone=spec.display_timezone,
        visible_start_display=axis_timestamp(ds.visible_start_utc, spec.display_timezone).to_dict(),
        visible_end_display=axis_timestamp(ds.visible_end_utc, spec.display_timezone).to_dict(),
        display_utc_offsets_minutes=_display_offsets(ds.visible_start_utc, ds.visible_end_utc, spec.display_timezone, tf),
        calendar_id=ds.calendar_id, calendar_version=ds.calendar_version, adjustment_mode=ds.adjustment_mode,
        sessions_present=ds.sessions_present, dataset_id=ds.dataset_id, dataset_version=ds.dataset_version,
        dataset_manifest_sha256=ds.dataset_manifest_sha256, dataset_pagination_complete=ds.dataset_pagination_complete,
        source_snapshot_ids=ds.source_snapshot_ids, source_file_sha256s=ds.source_file_sha256s,
        instrument_spec_version_id=ds.instrument_spec_version_id, instrument_spec_hash=ds.instrument_spec_hash,
        instrument_spec_recorded_at_utc=ds.instrument_spec_recorded_at_utc,
        instrument_spec_known_at_decision=ds.instrument_spec_known_at_decision,
        theme_id=theme.theme_id, theme_version=theme.theme_version, theme_hash=theme.theme_hash(),
        width_px=spec.width_px, height_px=spec.height_px, image_format=spec.image_format,
        color_mode=spec.color_mode, color_space=spec.color_space, renderer_name=renderer.renderer_name,
        renderer_version=renderer.renderer_version, renderer_build_id=renderer.renderer_build_id,
        font_fingerprint=renderer.font_fingerprint, overlay_specs=tuple(o.to_dict() for o in spec.overlay_specs),
        vwap_session_context_complete=vwap_ctx, visible_low=ds.visible_low, visible_high=ds.visible_high,
        price_axis_policy=spec.price_axis_policy, price_axis_padding_ratio=spec.price_axis_padding_ratio,
        price_axis_min=axis_min, price_axis_max=axis_max,
        all_inputs_quality_verified=ds.all_inputs_quality_verified,
        intra_session_gap_count=ds.intra_session_gap_count, missing_bar_count=ds.missing_bar_count,
        render_status=status, status_reasons=reasons, created_at_utc=created_at_utc,
    )


def build_chart_snapshot_manifest(
    *,
    spec: ChartSpec,
    data_snapshot: DataSnapshot,
    renderer: RendererInfo,
    created_at_utc: datetime,
    image_bytes: Optional[bytes] = None,
    image_path: Optional[str] = None,
    price_axis_min: Any = None,
    price_axis_max: Any = None,
    render_error: Optional[str] = None,
) -> ChartSnapshotManifest:
    """Bind a ChartSpec to its validated data snapshot and (optionally) the rendered image, and derive the status."""
    img_sha = img_size = None
    if image_bytes is not None:
        if render_error is not None:
            raise ChartContractError("a failed render cannot carry an image")
        if not isinstance(image_path, str) or not image_path:
            raise ChartContractError("image_path is required with image_bytes")
        validate_chart_png(image_bytes, width_px=spec.width_px, height_px=spec.height_px)
        img_sha, img_size = sha256_hex(bytes(image_bytes)), len(image_bytes)
    elif image_path is not None:
        raise ChartContractError("image_path given without image_bytes")
    man = _derive_manifest(spec=spec, ds=data_snapshot, renderer=renderer, created_at_utc=created_at_utc,
                           image_sha256=img_sha, image_size_bytes=img_size, image_path=image_path if img_sha else None,
                           render_failed=render_error is not None)
    if (price_axis_min is None) != (price_axis_max is None):
        raise ChartContractError("renderer-reported price_axis_min and price_axis_max are given together")
    if price_axis_min is not None:
        reported = (_opt_dec_str(price_axis_min, "price_axis_min"), _opt_dec_str(price_axis_max, "price_axis_max"))
        if reported != (man.price_axis_min, man.price_axis_max):
            raise ChartContractError(f"renderer-reported price-axis bounds {reported} differ from the spec's "
                                     f"{man.price_axis_policy} bounds {(man.price_axis_min, man.price_axis_max)}")
    return man


def verify_chart_image(manifest: ChartSnapshotManifest, image_root: str = ".") -> None:
    """Re-read the image file and check it against image_sha256 and the profile's PNG format."""
    if manifest.image_sha256 is None or manifest.image_path is None:
        raise ImageValidationError("manifest records no image")
    path = manifest.image_path if os.path.isabs(manifest.image_path) else os.path.join(image_root, manifest.image_path)
    if not os.path.isfile(path):
        raise ImageValidationError(f"chart image not found: {path}")
    with open(path, "rb") as fh:
        data = fh.read()
    actual = sha256_hex(data)
    if actual != manifest.image_sha256:
        raise ImageValidationError(f"image SHA-256 mismatch: manifest {manifest.image_sha256}, file {actual}")
    if len(data) != manifest.image_size_bytes:
        raise ImageValidationError("image size does not match the manifest")
    validate_chart_png(data, width_px=manifest.width_px, height_px=manifest.height_px)


def verify_chart_snapshot(manifest: ChartSnapshotManifest, *, spec: ChartSpec, data_snapshot: DataSnapshot,
                          renderer: RendererInfo, image_root: Optional[str] = None) -> None:
    """Recompute the complete manifest from (spec, data snapshot, renderer, theme, image state) and compare every
    semantic field; the render status is re-derived, so a forged status or any tampered derived field is rejected."""
    if not isinstance(manifest, ChartSnapshotManifest):
        raise ChartContractError("manifest must be a ChartSnapshotManifest")
    expected = _derive_manifest(
        spec=spec, ds=data_snapshot, renderer=renderer, created_at_utc=manifest.created_at_utc,
        image_sha256=manifest.image_sha256, image_size_bytes=manifest.image_size_bytes, image_path=manifest.image_path,
        render_failed=manifest.render_status == STATUS_FAILED,
    )
    got, want = manifest.semantic_dict(), expected.semantic_dict()
    diff = sorted(k for k in want if got.get(k) != want[k])
    if diff:
        raise ProvenanceError(f"manifest fields do not match the recomputed values: {diff}")
    if image_root is not None:
        verify_chart_image(manifest, image_root)
