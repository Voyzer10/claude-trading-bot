"""Candles for Scanner V6: one validated candle, and an ordered, gap-indexed series of them.

Neutral infrastructure only: no trading rule lives here. The input shapes match what the rest of the repo already
produces (reviewed 21 Nov 2026), so V6 can read the same data without importing V4 or any scanner:
  - rows:        [(timestamp, open, high, low, close, volume), ...]   (scan_nse / scan_crypto / research loaders)
  - chart JSON:  {"t": [...epoch seconds], "o": [...], "h": [...], "l": [...], "c": [...], "v": [...]}
                 (yahoo_chart / coinbase_chart / the long research data); candles with a None price are skipped.

Timestamps are the candle's OPEN time, timezone-aware, normalised to UTC.

Chart-JSON ingestion (Module A, interim "Option 2", 23 Nov 2026):
  - from_chart_json (LEGACY, unchanged result): still skips rows with a None open / high / low / close and re-indexes
    the rest 0..n-1, so existing callers keep working. It is no longer silent: every skipped row is recorded in
    `series.invalid_rows` (InvalidRow), and `series.source_positions[i]` is the original zero-based source row of
    returned candle i.
  - inspect_chart_json / load_chart_json_strict (STRICT): every row is checked and nothing is skipped silently.
    load_chart_json_strict raises InvalidRowsError if any row is invalid; inspect_chart_json returns a
    ChartJSONReport whose only series accessor is the explicitly named partial_series().
Known limitation, unchanged: a missing (None) volume becomes 0.0 in both loaders and in from_rows, so a missing
volume cannot be told apart from a zero volume.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Iterator, Mapping, Optional, Sequence, Tuple, Union

TimestampLike = Union[datetime, int, float]


class CandleError(ValueError):
    """A candle or a candle series that breaks a basic data rule (not a trading rule)."""


def _finite(x) -> bool:
    """math.isfinite for an int or float, but False (not OverflowError) for an int too large for a float (D2)."""
    try:
        return math.isfinite(x)
    except OverflowError:
        return False


def to_utc(ts: TimestampLike) -> datetime:
    """A timezone-aware UTC datetime from an aware datetime or epoch seconds. Naive datetimes are refused: their
    timezone is unknown, and guessing it would shift every event."""
    if isinstance(ts, bool):
        raise CandleError("timestamp must be a datetime or epoch seconds, not bool")
    if isinstance(ts, (int, float)):
        if not _finite(ts):
            raise CandleError("timestamp is not finite: %r" % (ts,))
        try:
            return datetime.fromtimestamp(ts, timezone.utc)
        except (OverflowError, OSError, ValueError) as e:     # D1: outside the platform's datetime range
            raise CandleError("timestamp %r is out of range: %s" % (ts, e)) from e
    if isinstance(ts, datetime):
        if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
            raise CandleError("naive datetime %s: a timezone is required" % ts.isoformat())
        return ts.astimezone(timezone.utc)
    raise CandleError("unsupported timestamp type %s" % type(ts).__name__)


@dataclass(frozen=True)
class Candle:
    """One OHLCV candle. `index` is its position in its series (0-based); `ts` its open time (UTC)."""
    index: int
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.index, int) or isinstance(self.index, bool) or self.index < 0:
            raise CandleError("index must be a non-negative int, got %r" % (self.index,))
        object.__setattr__(self, "ts", to_utc(self.ts))
        for name in ("open", "high", "low", "close", "volume"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not _finite(v):
                raise CandleError("%s must be a finite number, got %r (candle %d)" % (name, v, self.index))
            object.__setattr__(self, name, float(v))
        if self.volume < 0:
            raise CandleError("volume is negative (candle %d)" % self.index)
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close) or self.high < self.low:
            raise CandleError("inconsistent OHLC at candle %d: o %s h %s l %s c %s" % (
                self.index, self.open, self.high, self.low, self.close))

    @property
    def range(self) -> float:
        return self.high - self.low


class CandleSeries(Sequence[Candle]):
    """An immutable series of candles: indices 0..n-1 in order, timestamps strictly increasing.

    `upto(k)` returns the series as it was known at the close of candle k (candles 0..k). Detectors that only see
    `upto(k)` cannot look ahead; the no-look-ahead check in scanner_v6.engine relies on it."""

    def __init__(self, candles: Iterable[Candle], symbol: Optional[str] = None, timeframe: Optional[str] = None, *,
                 source_positions: Optional[Sequence[int]] = None, invalid_rows: Sequence["InvalidRow"] = ()):
        """`source_positions` (optional): the original zero-based source row of each candle, strictly increasing;
        None when the provenance is unknown. `invalid_rows`: source rows that were NOT turned into candles, each with
        its reason. Both are audit records only; candle indices stay 0..n-1.

        Provenance rules (checked here):
          - invalid_rows need source_positions (rows cannot be placed, or cut at a prefix, without them);
          - invalid source positions are unique and strictly increasing;
          - no invalid row shares a source position with a candle;
          - every source row strictly between the first and the last candle's source row is either a candle or an
            invalid row, so a skipped source row is always accounted for (Gap.skipped_source_rows > 0 means exactly
            that many invalid rows)."""
        self._c: Tuple[Candle, ...] = tuple(candles)
        self.symbol, self.timeframe = symbol, timeframe
        for i, c in enumerate(self._c):
            if not isinstance(c, Candle):
                raise CandleError("item %d is not a Candle" % i)
            if c.index != i:
                raise CandleError("candle at position %d has index %d (indices must be 0..n-1)" % (i, c.index))
            if i and c.ts <= self._c[i - 1].ts:
                raise CandleError("timestamps must strictly increase: candle %d (%s) is not after candle %d (%s)" % (
                    i, c.ts.isoformat(), i - 1, self._c[i - 1].ts.isoformat()))
        self.source_positions: Optional[Tuple[int, ...]] = None
        if source_positions is not None:
            sp = tuple(source_positions)
            if len(sp) != len(self._c):
                raise CandleError("source_positions has %d entries for %d candles" % (len(sp), len(self._c)))
            for j, p in enumerate(sp):
                if isinstance(p, bool) or not isinstance(p, int) or p < 0 or (j and p <= sp[j - 1]):
                    raise CandleError("source_positions must be strictly increasing non-negative ints (entry %d)" % j)
            self.source_positions = sp
        self.invalid_rows: Tuple[InvalidRow, ...] = tuple(invalid_rows)
        for j, r in enumerate(self.invalid_rows):
            if not isinstance(r, InvalidRow):
                raise CandleError("invalid_rows holds a non-InvalidRow item")
            if j and r.source_position <= self.invalid_rows[j - 1].source_position:
                raise CandleError("invalid row source positions must be unique and increasing (entry %d)" % j)
        if self.invalid_rows and self.source_positions is None:
            raise CandleError("invalid_rows need source_positions (provenance unknown)")
        if self.source_positions is not None:
            valid, bad = set(self.source_positions), {r.source_position for r in self.invalid_rows}
            both = sorted(valid & bad)
            if both:
                raise CandleError("source row %d is both a candle and an invalid row" % both[0])
            if self.source_positions:
                lo, hi = self.source_positions[0], self.source_positions[-1]
                unaccounted = [p for p in range(lo + 1, hi) if p not in valid and p not in bad]
                if unaccounted:
                    raise CandleError("source row %d lies between candles but is neither a candle nor an invalid row"
                                      % unaccounted[0])

    @property
    def provenance_known(self) -> bool:
        """True only when every candle's source row is recorded (source_positions is set)."""
        return self.source_positions is not None

    def source_position(self, i: int) -> Optional[int]:
        """The original source row of candle i, or None when the provenance is unknown."""
        if not 0 <= i < len(self._c):
            raise IndexError("candle %d outside 0..%d" % (i, len(self._c) - 1))
        return None if self.source_positions is None else self.source_positions[i]

    def __len__(self) -> int:
        return len(self._c)

    def __getitem__(self, i):  # type: ignore[override]
        if isinstance(i, slice):
            raise TypeError("slice a CandleSeries with upto(k), so indices stay 0..k")
        return self._c[i]

    def __iter__(self) -> Iterator[Candle]:
        return iter(self._c)

    def upto(self, k: int) -> "CandleSeries":
        """Candles 0..k (inclusive): what was known when candle k closed."""
        if not 0 <= k < len(self._c):
            raise IndexError("upto(%d) outside 0..%d" % (k, len(self._c) - 1))
        if self.source_positions is None:        # provenance unknown: no invalid rows can exist (see __init__)
            return CandleSeries(self._c[:k + 1], self.symbol, self.timeframe)
        last = self.source_positions[k]          # invalid rows after candle k's source row are not known yet
        return CandleSeries(self._c[:k + 1], self.symbol, self.timeframe, source_positions=self.source_positions[:k + 1],
                            invalid_rows=tuple(r for r in self.invalid_rows if r.source_position < last))

    def index_at(self, ts: TimestampLike) -> Optional[int]:
        """The index of the candle that opened at `ts`, or None."""
        t = to_utc(ts)
        for c in self._c:
            if c.ts == t:
                return c.index
        return None

    @classmethod
    def from_rows(cls, rows: Iterable[Sequence], symbol: Optional[str] = None,
                  timeframe: Optional[str] = None) -> "CandleSeries":
        """From (timestamp, open, high, low, close[, volume]) rows, oldest first."""
        out = []
        for i, r in enumerate(rows):
            if len(r) < 5:
                raise CandleError("row %d has %d fields; need ts, o, h, l, c[, v]" % (i, len(r)))
            out.append(Candle(i, r[0], r[1], r[2], r[3], r[4], (r[5] if len(r) > 5 and r[5] is not None else 0.0)))
        return cls(out, symbol, timeframe)

    @classmethod
    def from_chart_json(cls, d: Mapping[str, Sequence], symbol: Optional[str] = None,
                        timeframe: Optional[str] = None) -> "CandleSeries":
        """LEGACY loader. From {"t", "o", "h", "l", "c", "v"} arrays (epoch seconds). A candle with any None price is
        skipped, as the repo's existing loaders do; the remaining candles are re-indexed 0..n-1. Each skipped row is
        recorded in the returned series' `invalid_rows` (reason MISSING_OHLC), and `source_positions` maps every
        returned candle to its original source row. New Module A code uses load_chart_json_strict instead.

        Volume-array length (legacy behaviour kept, X03): a non-empty "v" shorter than "t" still ends the candles at
        len(v), as before, but every cut-off source row is recorded in `invalid_rows` with reason
        VOLUME_ARRAY_TRUNCATED. No volume or price is invented for it. A "v" LONGER than "t" holds extra volume
        values with no source row; they are still ignored, because no source row exists to record them against
        (known limitation; load_chart_json_strict rejects both mismatches)."""
        n = len(d["t"])                                  # input checks exactly as before (legacy behaviour kept)
        for k in ("o", "h", "l", "c"):
            if len(d[k]) != n:
                raise CandleError("array %r has %d values, t has %d" % (k, len(d[k]), n))
        vols = d.get("v") or [0] * n
        rows, positions, skipped = [], [], []
        for j, (t, o, h, l, c, v) in enumerate(zip(d["t"], d["o"], d["h"], d["l"], d["c"], vols)):
            missing = tuple(f for f, x in zip(_OHLC, (o, h, l, c)) if x is None)
            if missing:
                skipped.append(InvalidRow(j, _try_utc(t), t, "MISSING_OHLC", missing))
                continue
            rows.append((t, o, h, l, c, v))
            positions.append(j)
        if len(vols) < n:                                # X03: rows the zip above cuts off are recorded, not lost
            parsed = [_try_utc(t) for t in d["t"][:len(vols)] if t is not None]
            max_ts = max((x for x in parsed if x is not None), default=None)
            for j in range(len(vols), n):
                row, max_ts = _truncated_row(j, d["t"][j], d["o"][j], d["h"][j], d["l"][j], d["c"][j], max_ts)
                skipped.append(row)
        s = cls.from_rows(rows, symbol, timeframe)
        return cls(s, symbol, timeframe, source_positions=positions, invalid_rows=skipped)


# --------------------------------------------------------------------------- chart-JSON audit records and strict API
_OHLC = ("open", "high", "low", "close")

# Invalid-row reasons. A row gets the FIRST reason that applies, in this order; `fields` lists every field found
# missing or invalid in that row. VOLUME_ARRAY_TRUNCATED is used only by the legacy from_chart_json, for source rows
# beyond a shorter non-empty volume array (X03); it is a volume problem, so it takes the volume slot (with
# INVALID_VOLUME), after the timestamp and OHLC-value reasons. The strict loader rejects that input instead.
INVALID_ROW_REASONS = ("MISSING_TIMESTAMP", "INVALID_TIMESTAMP", "MISSING_OHLC", "INVALID_OHLC_VALUE",
                       "INVALID_VOLUME", "VOLUME_ARRAY_TRUNCATED", "INCONSISTENT_OHLC", "NON_INCREASING_TIMESTAMP")


@dataclass(frozen=True)
class InvalidRow:
    """A source row that did not become a candle. `source_position` is its zero-based position in the source
    arrays (never a candle index); `ts` is its UTC timestamp when the raw value was valid, else None; `raw_ts` is the
    value as given; `reason` is one of INVALID_ROW_REASONS; `fields` names the missing / invalid fields."""
    source_position: int
    ts: Optional[datetime]
    raw_ts: object
    reason: str
    fields: Tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.source_position, bool) or not isinstance(self.source_position, int) or \
                self.source_position < 0:
            raise CandleError("source_position must be a non-negative int")
        if self.reason not in INVALID_ROW_REASONS:
            raise CandleError("unknown invalid-row reason %r" % (self.reason,))


class InvalidRowsError(CandleError):
    """Raised by load_chart_json_strict: the input has invalid rows, so no complete series exists."""

    def __init__(self, invalid_rows: Tuple[InvalidRow, ...], total_rows: int):
        self.invalid_rows, self.total_rows = tuple(invalid_rows), total_rows
        shown = "; ".join("row %d (%s, ts %s): %s" % (r.source_position, r.reason,
                                                      r.ts.isoformat() if r.ts else r.raw_ts, ",".join(r.fields))
                          for r in self.invalid_rows[:10])
        more = "" if len(self.invalid_rows) <= 10 else "; ... %d more" % (len(self.invalid_rows) - 10)
        super().__init__("%d of %d source rows are invalid: %s%s" % (len(self.invalid_rows), total_rows, shown, more))


@dataclass(frozen=True)
class ChartJSONReport:
    """Result of inspect_chart_json: every source row is either a valid candle (`valid_positions`) or an
    InvalidRow. There is deliberately no `.series`: a caller must choose complete_series() (raises unless every
    row is valid) or partial_series() (the valid rows only, with the invalid rows attached)."""
    total_rows: int
    valid_positions: Tuple[int, ...]
    invalid_rows: Tuple[InvalidRow, ...]
    _rows: Tuple[tuple, ...] = field(repr=False)

    @property
    def is_complete(self) -> bool:
        return not self.invalid_rows

    def complete_series(self, symbol: Optional[str] = None, timeframe: Optional[str] = None) -> "CandleSeries":
        if self.invalid_rows:
            raise InvalidRowsError(self.invalid_rows, self.total_rows)
        return self.partial_series(symbol, timeframe)

    def partial_series(self, symbol: Optional[str] = None, timeframe: Optional[str] = None) -> "CandleSeries":
        """The valid rows only, as candles 0..m-1, with `source_positions` and `invalid_rows` attached so the
        exclusion stays visible. No candle is created for an invalid row."""
        s = CandleSeries.from_rows(self._rows, symbol, timeframe)
        return CandleSeries(s, symbol, timeframe, source_positions=self.valid_positions,
                            invalid_rows=self.invalid_rows)


def _chart_arrays(d: Mapping[str, Sequence]):
    if not isinstance(d, Mapping):
        raise CandleError("chart JSON must be a mapping")
    for k in ("t", "o", "h", "l", "c", "v"):
        if k in ("t", "o", "h", "l", "c") and (k not in d or d[k] is None):
            raise CandleError("chart JSON has no %r array" % k)
        if d.get(k) is not None and (not isinstance(d[k], Sequence) or isinstance(d[k], (str, bytes, bytearray))):
            raise CandleError("chart JSON %r must be a list or tuple, got %s" % (k, type(d[k]).__name__))   # D3
    n = len(d["t"])
    for k in ("o", "h", "l", "c"):
        if len(d[k]) != n:
            raise CandleError("array %r has %d values, t has %d" % (k, len(d[k]), n))
    if d.get("v") is None:                  # no volume array supplied: documented default policy (all 0)
        return n, [0] * n
    vols = d["v"]                           # an explicit array must match, including an explicit empty one
    if len(vols) != n:
        raise CandleError("array 'v' has %d values, t has %d" % (len(vols), n))
    return n, vols


def _try_utc(t) -> Optional[datetime]:
    try:
        return to_utc(t)
    except CandleError:
        return None


def _bad_number(x) -> bool:
    return isinstance(x, bool) or not isinstance(x, (int, float)) or not _finite(x)


def _truncated_row(j: int, t, o, h, l, c, max_ts: Optional[datetime]):
    """InvalidRow for a legacy source row with no volume value (X03), using the same checks and reason priority as
    inspect_chart_json: MISSING_TIMESTAMP > INVALID_TIMESTAMP > MISSING_OHLC > INVALID_OHLC_VALUE >
    VOLUME_ARRAY_TRUNCATED. Fields list every problem found: timestamp (missing, invalid, or not after the highest
    earlier parseable source timestamp), missing / invalid OHLC, "volume", and all four OHLC fields when the prices
    are inconsistent. Nothing is filled in. Returns (row, updated highest timestamp)."""
    ts = _try_utc(t) if t is not None else None
    out_of_order = ts is not None and max_ts is not None and ts <= max_ts
    if ts is not None and not out_of_order:
        max_ts = ts
    missing = tuple(f for f, x in zip(_OHLC, (o, h, l, c)) if x is None)
    invalid = tuple(f for f, x in zip(_OHLC, (o, h, l, c)) if x is not None and _bad_number(x))
    inconsistent = not missing and not invalid and (h < max(o, c) or l > min(o, c) or h < l)
    fields = (("timestamp",) if ts is None or out_of_order else ()) + missing + invalid + ("volume",) + \
        (_OHLC if inconsistent else ())
    if t is None:
        reason = "MISSING_TIMESTAMP"
    elif ts is None:
        reason = "INVALID_TIMESTAMP"
    elif missing:
        reason = "MISSING_OHLC"
    elif invalid:
        reason = "INVALID_OHLC_VALUE"
    else:
        reason = "VOLUME_ARRAY_TRUNCATED"
    return InvalidRow(j, ts, t, reason, fields), max_ts


def inspect_chart_json(d: Mapping[str, Sequence]) -> ChartJSONReport:
    """STRICT inspection of chart JSON: every row is checked; nothing is skipped silently and no value is changed or
    filled. Structural problems (missing arrays, length mismatch) raise CandleError. A missing (None) volume is read
    as 0.0, the existing convention (known limitation).

    Timestamp order is checked against the SOURCE rows, not only the valid ones: every row with a parseable
    timestamp (even one rejected for its OHLC) takes part. A row whose timestamp is not after the highest parseable
    source timestamp seen so far is out of order. (The highest, not merely the previous one, so the valid rows always
    stay strictly increasing; for an ordered source the two are the same.) An out-of-order row with an OHLC problem
    keeps the higher-priority reason and lists "timestamp" in its fields."""
    n, vols = _chart_arrays(d)
    valid_rows, valid_pos, bad = [], [], []
    max_src_ts: Optional[datetime] = None
    for j, (t, o, h, l, c, v) in enumerate(zip(d["t"], d["o"], d["h"], d["l"], d["c"], vols)):
        ts = _try_utc(t) if t is not None else None
        out_of_order = ts is not None and max_src_ts is not None and ts <= max_src_ts
        if ts is not None and not out_of_order:
            max_src_ts = ts
        missing = tuple(f for f, x in zip(_OHLC, (o, h, l, c)) if x is None)
        invalid = tuple(f for f, x in zip(_OHLC, (o, h, l, c)) if x is not None and _bad_number(x))
        vol = 0.0 if v is None else v
        bad_vol = _bad_number(vol) or (not _bad_number(vol) and vol < 0)
        fields = (("timestamp",) if ts is None or out_of_order else ()) + missing + invalid + \
            (("volume",) if bad_vol else ())
        if t is None:
            reason = "MISSING_TIMESTAMP"
        elif ts is None:
            reason = "INVALID_TIMESTAMP"
        elif missing:
            reason = "MISSING_OHLC"
        elif invalid:
            reason = "INVALID_OHLC_VALUE"
        elif bad_vol:
            reason = "INVALID_VOLUME"
        elif h < max(o, c) or l > min(o, c) or h < l:
            reason, fields = "INCONSISTENT_OHLC", (("timestamp",) if out_of_order else ()) + _OHLC
        elif out_of_order:
            reason, fields = "NON_INCREASING_TIMESTAMP", ("timestamp",)
        else:
            valid_rows.append((t, o, h, l, c, vol))
            valid_pos.append(j)
            continue
        bad.append(InvalidRow(j, ts, t, reason, fields))
    return ChartJSONReport(n, tuple(valid_pos), tuple(bad), tuple(valid_rows))


def load_chart_json_strict(d: Mapping[str, Sequence], symbol: Optional[str] = None,
                           timeframe: Optional[str] = None) -> CandleSeries:
    """STRICT loader: the complete series, or InvalidRowsError listing every invalid row (source position,
    timestamp, reason, fields). It never returns a series with rows left out."""
    return inspect_chart_json(d).complete_series(symbol, timeframe)
