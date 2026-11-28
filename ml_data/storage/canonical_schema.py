"""Versioned CanonicalCandle, CanonicalQuote, CanonicalTrade schemas and deterministic resampling."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ..instruments.identity import normalize_decimal_str
from .exceptions import SchemaValidationError

CANONICAL_SCHEMA_VERSION = "1.0.0"
UTC_TZ = timezone.utc

STANDARD_TIMEFRAMES_MINUTES: Dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
}


def _require_utc(dt: datetime, name: str) -> datetime:
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise SchemaValidationError(f"{name} must be a timezone-aware datetime")
    return dt.astimezone(UTC_TZ)


def _require_dec(val: Optional[Decimal], name: str, *, required: bool = True) -> Optional[Decimal]:
    if val is None:
        if required:
            raise SchemaValidationError(f"{name} is required and must be Decimal")
        return None
    if isinstance(val, (float, bool)) or not isinstance(val, Decimal) or not val.is_finite():
        raise SchemaValidationError(f"{name} must be a finite Decimal (got {type(val).__name__})")
    return val


def _require_non_empty_str(val: Any, name: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise SchemaValidationError(f"{name} must be a non-empty string")
    return val


def _check_opt_str(val: Any, name: str) -> None:
    if val is not None and not isinstance(val, str):
        raise SchemaValidationError(f"{name} must be a str or None (got {type(val).__name__})")


def _normalize_str_tuple(val: Any, name: str) -> Tuple[str, ...]:
    if not isinstance(val, (tuple, list)):
        raise SchemaValidationError(f"{name} must be a tuple or list of strings (got {type(val).__name__})")
    for item in val:
        if not isinstance(item, str):
            raise SchemaValidationError(f"{name} elements must be strings (got {type(item).__name__})")
    return tuple(val)


def _parse_json_dec(val: Any, name: str, *, required: bool = True) -> Optional[Decimal]:
    if val is None:
        if required:
            raise SchemaValidationError(f"{name} is required and must be a Decimal string")
        return None
    if isinstance(val, (float, bool)):
        raise SchemaValidationError(f"{name} must not be float or bool (got {type(val).__name__})")
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError) as exc:
        raise SchemaValidationError(f"Invalid Decimal for {name}: {val!r}") from exc


def _parse_json_dt(val: Any, name: str, *, required: bool = True) -> Optional[datetime]:
    if val is None:
        if required:
            raise SchemaValidationError(f"{name} is required")
        return None
    if isinstance(val, datetime):
        return _require_utc(val, name)
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchemaValidationError(f"Invalid ISO-8601 datetime for {name}: {val!r}") from exc
    return _require_utc(dt, name)


@dataclass(frozen=True)
class CanonicalCandle:
    """Universal cross-market canonical OHLCV(+derivatives) candle contract."""

    # Identity
    instrument_id: str
    market: str
    asset_class: str
    segment: str
    exchange: str
    provider: str
    provider_symbol: str
    provider_instrument_id: str

    # Time
    timestamp_start_utc: datetime
    timestamp_end_utc: datetime
    event_time_utc: datetime
    received_at_utc: datetime
    timeframe: str
    trading_date: date
    trading_session: str
    session_id: str
    calendar_id: str
    calendar_version: str

    # Prices & Volume (Decimal only)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    # Provenance
    provider_feed: str
    source_snapshot_id: str
    source_record_id: str
    dataset_version: str
    adjustment_mode: str
    retrieval_run_id: str
    quality_status: str

    schema_version: str = CANONICAL_SCHEMA_VERSION
    quote_volume: Optional[Decimal] = None
    trade_count: Optional[int] = None

    # Optional derivatives fields (null + provenance when unavailable; never fabricated)
    open_interest: Optional[Decimal] = None
    mark_price: Optional[Decimal] = None
    index_price: Optional[Decimal] = None
    funding_rate: Optional[Decimal] = None
    funding_timestamp_utc: Optional[datetime] = None

    quality_flags: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != CANONICAL_SCHEMA_VERSION:
            raise SchemaValidationError(
                f"Unsupported schema_version {self.schema_version!r} (expected {CANONICAL_SCHEMA_VERSION!r})"
            )
        for sf in (
            "instrument_id", "market", "asset_class", "segment", "exchange",
            "provider", "provider_symbol", "provider_instrument_id",
            "timeframe", "trading_session", "session_id", "calendar_id",
            "calendar_version", "provider_feed", "source_snapshot_id",
            "source_record_id", "dataset_version", "adjustment_mode",
            "retrieval_run_id", "quality_status",
        ):
            _require_non_empty_str(getattr(self, sf), sf)
        if self.timeframe not in STANDARD_TIMEFRAMES_MINUTES:
            raise SchemaValidationError(
                f"Unsupported timeframe {self.timeframe!r} (expected one of {tuple(STANDARD_TIMEFRAMES_MINUTES)})"
            )
        if isinstance(self.trading_date, datetime) or not isinstance(self.trading_date, date):
            raise SchemaValidationError(
                f"trading_date must be a datetime.date (got {type(self.trading_date).__name__})"
            )
        object.__setattr__(self, "quality_flags", _normalize_str_tuple(self.quality_flags, "quality_flags"))
        t0 = _require_utc(self.timestamp_start_utc, "timestamp_start_utc")
        t1 = _require_utc(self.timestamp_end_utc, "timestamp_end_utc")
        object.__setattr__(self, "timestamp_start_utc", t0)
        object.__setattr__(self, "timestamp_end_utc", t1)
        object.__setattr__(self, "event_time_utc", _require_utc(self.event_time_utc, "event_time_utc"))
        object.__setattr__(self, "received_at_utc", _require_utc(self.received_at_utc, "received_at_utc"))
        if self.funding_timestamp_utc is not None:
            object.__setattr__(self, "funding_timestamp_utc", _require_utc(self.funding_timestamp_utc, "funding_timestamp_utc"))
        if t1 <= t0:
            raise SchemaValidationError("timestamp_end_utc must be strictly after timestamp_start_utc")
        max_dur = timedelta(minutes=STANDARD_TIMEFRAMES_MINUTES[self.timeframe])
        if (t1 - t0) > max_dur:
            raise SchemaValidationError(
                f"Candle interval {(t1 - t0)} exceeds timeframe {self.timeframe} ({max_dur})"
            )
        if self.trade_count is not None:
            if isinstance(self.trade_count, bool) or not isinstance(self.trade_count, int) or self.trade_count < 0:
                raise SchemaValidationError(f"trade_count must be a non-negative int (got {self.trade_count!r})")
        o = _require_dec(self.open, "open")
        h = _require_dec(self.high, "high")
        l = _require_dec(self.low, "low")
        c = _require_dec(self.close, "close")
        v = _require_dec(self.volume, "volume")
        assert o is not None and h is not None and l is not None and c is not None and v is not None
        if h < max(o, c, l) or l > min(o, c, h) or v < 0:
            raise SchemaValidationError(f"Invalid OHLCV invariants on {self.instrument_id} at {self.timestamp_start_utc.isoformat()}")
        _require_dec(self.quote_volume, "quote_volume", required=False)
        _require_dec(self.open_interest, "open_interest", required=False)
        _require_dec(self.mark_price, "mark_price", required=False)
        _require_dec(self.index_price, "index_price", required=False)
        _require_dec(self.funding_rate, "funding_rate", required=False)

    def to_dict(self) -> Dict[str, Any]:
        def _d(v: Optional[Decimal]) -> Optional[str]:
            return normalize_decimal_str(v) if v is not None else None

        return {
            "schema_version": self.schema_version,
            "instrument_id": self.instrument_id,
            "market": self.market,
            "asset_class": self.asset_class,
            "segment": self.segment,
            "exchange": self.exchange,
            "provider": self.provider,
            "provider_symbol": self.provider_symbol,
            "provider_instrument_id": self.provider_instrument_id,
            "timestamp_start_utc": self.timestamp_start_utc.astimezone(UTC_TZ).isoformat(),
            "timestamp_end_utc": self.timestamp_end_utc.astimezone(UTC_TZ).isoformat(),
            "event_time_utc": self.event_time_utc.astimezone(UTC_TZ).isoformat(),
            "received_at_utc": self.received_at_utc.astimezone(UTC_TZ).isoformat(),
            "timeframe": self.timeframe,
            "trading_date": self.trading_date.isoformat(),
            "trading_session": self.trading_session,
            "session_id": self.session_id,
            "calendar_id": self.calendar_id,
            "calendar_version": self.calendar_version,
            "open": _d(self.open),
            "high": _d(self.high),
            "low": _d(self.low),
            "close": _d(self.close),
            "volume": _d(self.volume),
            "quote_volume": _d(self.quote_volume),
            "trade_count": self.trade_count,
            "open_interest": _d(self.open_interest),
            "mark_price": _d(self.mark_price),
            "index_price": _d(self.index_price),
            "funding_rate": _d(self.funding_rate),
            "funding_timestamp_utc": self.funding_timestamp_utc.astimezone(UTC_TZ).isoformat() if self.funding_timestamp_utc else None,
            "provider_feed": self.provider_feed,
            "source_snapshot_id": self.source_snapshot_id,
            "source_record_id": self.source_record_id,
            "dataset_version": self.dataset_version,
            "adjustment_mode": self.adjustment_mode,
            "retrieval_run_id": self.retrieval_run_id,
            "quality_status": self.quality_status,
            "quality_flags": list(self.quality_flags),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CanonicalCandle":
        d = dict(data)
        for ts_f in ("timestamp_start_utc", "timestamp_end_utc", "event_time_utc", "received_at_utc"):
            d[ts_f] = _parse_json_dt(d.get(ts_f), ts_f, required=True)
        d["funding_timestamp_utc"] = _parse_json_dt(d.get("funding_timestamp_utc"), "funding_timestamp_utc", required=False)
        td = d.get("trading_date")
        if isinstance(td, datetime) or not td:
            raise SchemaValidationError(f"Invalid trading_date: {td!r}")
        d["trading_date"] = td if isinstance(td, date) else date.fromisoformat(str(td))
        for dec_f in ("open", "high", "low", "close", "volume"):
            d[dec_f] = _parse_json_dec(d.get(dec_f), dec_f, required=True)
        for dec_f in ("quote_volume", "open_interest", "mark_price", "index_price", "funding_rate"):
            d[dec_f] = _parse_json_dec(d.get(dec_f), dec_f, required=False)
        d["quality_flags"] = tuple(d.get("quality_flags") or ())
        return cls(**d)

    @classmethod
    def from_json(cls, payload: str) -> "CanonicalCandle":
        return cls.from_dict(json.loads(payload))


@dataclass(frozen=True)
class CanonicalQuote:
    """Canonical top-of-book (or depth-annotated) quote record."""

    instrument_id: str
    event_time_utc: datetime
    received_at_utc: datetime
    bid_price: Decimal
    ask_price: Decimal
    bid_size: Decimal
    ask_size: Decimal
    exchange: str
    provider: str
    feed: str
    sequence_id: Optional[str] = None
    depth_json: Optional[str] = None
    quality_flags: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for sf in ("instrument_id", "exchange", "provider", "feed"):
            _require_non_empty_str(getattr(self, sf), sf)
        _check_opt_str(self.sequence_id, "sequence_id")
        _check_opt_str(self.depth_json, "depth_json")
        object.__setattr__(self, "quality_flags", _normalize_str_tuple(self.quality_flags, "quality_flags"))
        object.__setattr__(self, "event_time_utc", _require_utc(self.event_time_utc, "event_time_utc"))
        object.__setattr__(self, "received_at_utc", _require_utc(self.received_at_utc, "received_at_utc"))
        bp = _require_dec(self.bid_price, "bid_price")
        ap = _require_dec(self.ask_price, "ask_price")
        bs = _require_dec(self.bid_size, "bid_size")
        as_ = _require_dec(self.ask_size, "ask_size")
        assert bs is not None and as_ is not None and bp is not None and ap is not None
        if bs < 0 or as_ < 0:
            raise SchemaValidationError("Quote sizes must be non-negative")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "event_time_utc": self.event_time_utc.astimezone(UTC_TZ).isoformat(),
            "received_at_utc": self.received_at_utc.astimezone(UTC_TZ).isoformat(),
            "bid_price": normalize_decimal_str(self.bid_price),
            "ask_price": normalize_decimal_str(self.ask_price),
            "bid_size": normalize_decimal_str(self.bid_size),
            "ask_size": normalize_decimal_str(self.ask_size),
            "exchange": self.exchange,
            "provider": self.provider,
            "feed": self.feed,
            "sequence_id": self.sequence_id,
            "depth_json": self.depth_json,
            "quality_flags": list(self.quality_flags),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CanonicalQuote":
        d = dict(data)
        d["event_time_utc"] = _parse_json_dt(d.get("event_time_utc"), "event_time_utc", required=True)
        d["received_at_utc"] = _parse_json_dt(d.get("received_at_utc"), "received_at_utc", required=True)
        for dec_f in ("bid_price", "ask_price", "bid_size", "ask_size"):
            d[dec_f] = _parse_json_dec(d.get(dec_f), dec_f, required=True)
        d["quality_flags"] = tuple(d.get("quality_flags") or ())
        return cls(**d)

    @classmethod
    def from_json(cls, payload: str) -> "CanonicalQuote":
        return cls.from_dict(json.loads(payload))


@dataclass(frozen=True)
class CanonicalTrade:
    """Canonical trade tick record."""

    instrument_id: str
    trade_id: str
    event_time_utc: datetime
    received_at_utc: datetime
    price: Decimal
    quantity: Decimal
    exchange: str
    provider: str
    feed: str
    source_id: str
    quote_quantity: Optional[Decimal] = None
    aggressor_side: Optional[str] = None   # None when not reliably supplied by provider
    conditions: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for sf in ("instrument_id", "trade_id", "exchange", "provider", "feed", "source_id"):
            _require_non_empty_str(getattr(self, sf), sf)
        _check_opt_str(self.aggressor_side, "aggressor_side")
        object.__setattr__(self, "conditions", _normalize_str_tuple(self.conditions, "conditions"))
        object.__setattr__(self, "event_time_utc", _require_utc(self.event_time_utc, "event_time_utc"))
        object.__setattr__(self, "received_at_utc", _require_utc(self.received_at_utc, "received_at_utc"))
        _require_dec(self.price, "price")
        q = _require_dec(self.quantity, "quantity")
        assert q is not None
        if q < 0:
            raise SchemaValidationError("Trade quantity must be non-negative")
        _require_dec(self.quote_quantity, "quote_quantity", required=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "trade_id": self.trade_id,
            "event_time_utc": self.event_time_utc.astimezone(UTC_TZ).isoformat(),
            "received_at_utc": self.received_at_utc.astimezone(UTC_TZ).isoformat(),
            "price": normalize_decimal_str(self.price),
            "quantity": normalize_decimal_str(self.quantity),
            "exchange": self.exchange,
            "provider": self.provider,
            "feed": self.feed,
            "source_id": self.source_id,
            "quote_quantity": normalize_decimal_str(self.quote_quantity) if self.quote_quantity is not None else None,
            "aggressor_side": self.aggressor_side,
            "conditions": list(self.conditions),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CanonicalTrade":
        d = dict(data)
        d["event_time_utc"] = _parse_json_dt(d.get("event_time_utc"), "event_time_utc", required=True)
        d["received_at_utc"] = _parse_json_dt(d.get("received_at_utc"), "received_at_utc", required=True)
        d["price"] = _parse_json_dec(d.get("price"), "price", required=True)
        d["quantity"] = _parse_json_dec(d.get("quantity"), "quantity", required=True)
        d["quote_quantity"] = _parse_json_dec(d.get("quote_quantity"), "quote_quantity", required=False)
        d["conditions"] = tuple(d.get("conditions") or ())
        return cls(**d)

    @classmethod
    def from_json(cls, payload: str) -> "CanonicalTrade":
        return cls.from_dict(json.loads(payload))


def _derive_session_anchor_utc(
    ref: CanonicalCandle,
    t_date: date,
    calendar: Optional[Any] = None,
) -> Tuple[Optional[datetime], bool]:
    """Derive canonical session start in UTC for (market, exchange, trading_date, trading_session).

    Returns (anchor_utc, is_session_aligned).
    """
    sess = ref.trading_session.strip().upper()
    inner = getattr(calendar, "inner", calendar) if calendar is not None else None

    if ref.market == "US" and ref.exchange.upper() in ("NASDAQ", "NYSE", "ARCA", "BATS", "IEX", "XNYS", "XNAS"):
        ny = ZoneInfo("America/New_York")
        if sess == "PRE_MARKET":
            t_open = getattr(inner, "premarket_open", dt_time(4, 0)) if inner is not None else dt_time(4, 0)
            return datetime.combine(t_date, t_open, tzinfo=ny).astimezone(UTC_TZ), True
        if sess in ("REGULAR", "EARLY_CLOSE"):
            t_open = getattr(inner, "regular_open", dt_time(9, 30)) if inner is not None else dt_time(9, 30)
            return datetime.combine(t_date, t_open, tzinfo=ny).astimezone(UTC_TZ), True
        if sess == "POST_MARKET":
            if inner is not None and hasattr(inner, "early_closes") and t_date in inner.early_closes:
                t_open = inner.early_closes[t_date]
            else:
                t_open = getattr(inner, "regular_close", dt_time(16, 0)) if inner is not None else dt_time(16, 0)
            return datetime.combine(t_date, t_open, tzinfo=ny).astimezone(UTC_TZ), True
        return None, False

    if ref.market == "IN" and ref.exchange.upper() in ("NSE", "NFO", "XNSE"):
        ist = ZoneInfo("Asia/Kolkata")
        if sess in ("REGULAR", "MUHURAT", "WEEKEND_SPECIAL", "SPECIAL_SESSION", "EARLY_CLOSE"):
            if inner is not None and hasattr(inner, "session_bounds"):
                bounds = inner.session_bounds(t_date, require_verified=False)
                if bounds is not None:
                    return bounds[0].astimezone(UTC_TZ), True
            if sess == "REGULAR":
                return datetime.combine(t_date, dt_time(9, 15), tzinfo=ist).astimezone(UTC_TZ), True
            return None, False
        if sess == "PRE_OPEN":
            return datetime.combine(t_date, dt_time(9, 0), tzinfo=ist).astimezone(UTC_TZ), True
        return None, False

    if ref.market == "CRYPTO":
        if sess in ("CONTINUOUS", "CONTINUOUS_24_7", "REGULAR"):
            return datetime.combine(t_date, dt_time(0, 0), tzinfo=UTC_TZ), True
        return None, False

    if ref.market == "US" and inner is not None and hasattr(inner, "trade_date_for"):
        if sess in ("ETH", "RTH", "GLOBEX"):
            # Globex ETH opens 17:00 CT on prior calendar day; RTH opens 08:30 CT on t_date
            ct = ZoneInfo("America/Chicago")
            if sess == "RTH":
                return datetime.combine(t_date, dt_time(8, 30), tzinfo=ct).astimezone(UTC_TZ), True
            prev_day = t_date - timedelta(days=3 if t_date.weekday() == 0 else 1)
            return datetime.combine(prev_day, dt_time(17, 0), tzinfo=ct).astimezone(UTC_TZ), True

    return None, False


def resample_candles(
    candles: Sequence[CanonicalCandle],
    target_timeframe: str,
    *,
    partial_policy: str = "MARK",
    anchor_time_utc: Optional[datetime] = None,
    calendar: Optional[Any] = None,
) -> List[CanonicalCandle]:
    """Deterministically resample finer-grained candles into 5m/15m/1h within identical (instrument_id, trading_date, session_id).

    Derives session-aligned anchors from the exchange calendar (e.g. 09:30 ET / 09:15 IST) so missing opening bars
    never shift subsequent buckets, validates source timeframe/provenance consistency, detects missing bars, and
    preserves all source quality flags.
    """
    if target_timeframe not in STANDARD_TIMEFRAMES_MINUTES:
        raise SchemaValidationError(f"Unsupported target_timeframe: {target_timeframe!r}")
    if partial_policy not in ("MARK", "REJECT"):
        raise SchemaValidationError(f"Unsupported partial_policy: {partial_policy!r}")
    step_min = STANDARD_TIMEFRAMES_MINUTES[target_timeframe]
    step = timedelta(minutes=step_min)

    by_session: Dict[Tuple[str, date, str], List[CanonicalCandle]] = {}
    for c in sorted(candles, key=lambda x: (x.instrument_id, x.timestamp_start_utc)):
        if c.trading_session == "CLOSED":
            continue
        if c.timeframe not in STANDARD_TIMEFRAMES_MINUTES:
            raise SchemaValidationError(f"Unsupported source timeframe: {c.timeframe!r}")
        if STANDARD_TIMEFRAMES_MINUTES[c.timeframe] >= step_min:
            raise SchemaValidationError(f"Cannot resample {c.timeframe} into {target_timeframe}")
        by_session.setdefault((c.instrument_id, c.trading_date, c.session_id), []).append(c)

    out: List[CanonicalCandle] = []
    for (iid, t_date, sess_id), sess_bars in sorted(by_session.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        ref = sess_bars[0]
        src_min = STANDARD_TIMEFRAMES_MINUTES[ref.timeframe]
        src_step = timedelta(minutes=src_min)
        expected_per_bucket = step_min // src_min

        if anchor_time_utc is not None:
            sess_anchor = anchor_time_utc.astimezone(UTC_TZ)
            is_aligned = True
        else:
            derived_anchor, is_aligned = _derive_session_anchor_utc(ref, t_date, calendar=calendar)
            sess_anchor = derived_anchor if derived_anchor is not None else ref.timestamp_start_utc

        for b in sess_bars:
            if (
                b.timeframe != ref.timeframe
                or b.provider != ref.provider
                or b.provider_feed != ref.provider_feed
                or b.adjustment_mode != ref.adjustment_mode
                or b.calendar_id != ref.calendar_id
                or b.calendar_version != ref.calendar_version
                or b.dataset_version != ref.dataset_version
                or b.retrieval_run_id != ref.retrieval_run_id
            ):
                raise SchemaValidationError(
                    f"Incompatible source provenance/timeframe in resample group for {iid}@{t_date.isoformat()}"
                )
            offset_sec = int((b.timestamp_start_utc - sess_anchor).total_seconds())
            if offset_sec % (src_min * 60) != 0:
                raise SchemaValidationError(
                    f"Source bar {b.timestamp_start_utc.isoformat()} does not align to {ref.timeframe} grid from {sess_anchor.isoformat()}"
                )

        buckets: Dict[datetime, List[CanonicalCandle]] = {}
        for c in sess_bars:
            offset_sec = int((c.timestamp_start_utc - sess_anchor).total_seconds())
            bucket_idx = offset_sec // (step_min * 60)
            b_start = sess_anchor + timedelta(minutes=bucket_idx * step_min)
            buckets.setdefault(b_start, []).append(c)

        for b_start, grp in sorted(buckets.items()):
            first, last = grp[0], grp[-1]
            has_gap = any(
                (grp[k].timestamp_start_utc - grp[k - 1].timestamp_start_utc) != src_step
                for k in range(1, len(grp))
            )
            is_partial = (len(grp) < expected_per_bucket) or (first.timestamp_start_utc != b_start) or has_gap
            if partial_policy == "REJECT" and is_partial:
                raise SchemaValidationError(
                    f"Incomplete/non-contiguous resample bucket for {iid} at {b_start.isoformat()} "
                    f"(got {len(grp)}/{expected_per_bucket}, gap={has_gap})"
                )

            hi = max(x.high for x in grp)
            lo = min(x.low for x in grp)
            vol = sum((x.volume for x in grp), Decimal("0"))
            qv_vals = [x.quote_volume for x in grp if x.quote_volume is not None]
            qv = sum(qv_vals, Decimal("0")) if len(qv_vals) == len(grp) else None
            tc_vals = [x.trade_count for x in grp if x.trade_count is not None]
            tc = sum(tc_vals) if len(tc_vals) == len(grp) else None

            merged_flags: List[str] = []
            for x in grp:
                for fl in x.quality_flags:
                    if fl not in merged_flags:
                        merged_flags.append(fl)
            merged_flags.append(f"resampled_from:{ref.timeframe}")
            if not is_aligned:
                merged_flags.append("unaligned_anchor")
            if is_partial:
                merged_flags.append("partial_bucket")
            if has_gap:
                merged_flags.append("missing_constituent_bars")
            flags = tuple(dict.fromkeys(merged_flags))

            snaps = sorted({x.source_snapshot_id for x in grp})
            snap_str = snaps[0] if len(snaps) == 1 else "|".join(snaps)
            b_end = min(b_start + step, last.timestamp_end_utc) if last.timestamp_end_utc > b_start else b_start + step

            out.append(
                CanonicalCandle(
                    instrument_id=iid,
                    market=first.market,
                    asset_class=first.asset_class,
                    segment=first.segment,
                    exchange=first.exchange,
                    provider=first.provider,
                    provider_symbol=first.provider_symbol,
                    provider_instrument_id=first.provider_instrument_id,
                    timestamp_start_utc=b_start,
                    timestamp_end_utc=b_end,
                    event_time_utc=last.event_time_utc,
                    received_at_utc=max(x.received_at_utc for x in grp),
                    timeframe=target_timeframe,
                    trading_date=t_date,
                    trading_session=first.trading_session,
                    session_id=sess_id,
                    calendar_id=first.calendar_id,
                    calendar_version=first.calendar_version,
                    open=first.open,
                    high=hi,
                    low=lo,
                    close=last.close,
                    volume=vol,
                    quote_volume=qv,
                    trade_count=tc,
                    open_interest=last.open_interest,
                    mark_price=last.mark_price,
                    index_price=last.index_price,
                    funding_rate=last.funding_rate,
                    funding_timestamp_utc=last.funding_timestamp_utc,
                    provider_feed=first.provider_feed,
                    source_snapshot_id=snap_str,
                    source_record_id=f"{first.source_record_id}..{last.source_record_id}",
                    dataset_version=first.dataset_version,
                    adjustment_mode=first.adjustment_mode,
                    retrieval_run_id=first.retrieval_run_id,
                    quality_status="PARTIAL_DATA" if is_partial else first.quality_status,
                    quality_flags=flags,
                )
            )
    return out
