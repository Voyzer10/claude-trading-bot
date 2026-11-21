"""Candles for Scanner V6: one validated candle, and an ordered, gap-indexed series of them.

Neutral infrastructure only: no trading rule lives here. The input shapes match what the rest of the repo already
produces (reviewed 21 Nov 2026), so V6 can read the same data without importing V4 or any scanner:
  - rows:        [(timestamp, open, high, low, close, volume), ...]   (scan_nse / scan_crypto / research loaders)
  - chart JSON:  {"t": [...epoch seconds], "o": [...], "h": [...], "l": [...], "c": [...], "v": [...]}
                 (yahoo_chart / coinbase_chart / the long research data); candles with a None price are skipped.

Timestamps are the candle's OPEN time, timezone-aware, normalised to UTC.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Iterator, Mapping, Optional, Sequence, Tuple, Union

TimestampLike = Union[datetime, int, float]


class CandleError(ValueError):
    """A candle or a candle series that breaks a basic data rule (not a trading rule)."""


def to_utc(ts: TimestampLike) -> datetime:
    """A timezone-aware UTC datetime from an aware datetime or epoch seconds. Naive datetimes are refused: their
    timezone is unknown, and guessing it would shift every event."""
    if isinstance(ts, bool):
        raise CandleError("timestamp must be a datetime or epoch seconds, not bool")
    if isinstance(ts, (int, float)):
        if not math.isfinite(ts):
            raise CandleError("timestamp is not finite: %r" % (ts,))
        return datetime.fromtimestamp(ts, timezone.utc)
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
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
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

    def __init__(self, candles: Iterable[Candle], symbol: Optional[str] = None, timeframe: Optional[str] = None):
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
        return CandleSeries(self._c[:k + 1], self.symbol, self.timeframe)

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
        """From {"t", "o", "h", "l", "c", "v"} arrays (epoch seconds). A candle with any None price is skipped, as the
        repo's existing loaders do; the remaining candles are re-indexed 0..n-1."""
        n = len(d["t"])
        for k in ("o", "h", "l", "c"):
            if len(d[k]) != n:
                raise CandleError("array %r has %d values, t has %d" % (k, len(d[k]), n))
        vols = d.get("v") or [0] * n
        rows = [(t, o, h, l, c, v) for t, o, h, l, c, v in zip(d["t"], d["o"], d["h"], d["l"], d["c"], vols)
                if None not in (o, h, l, c)]
        return cls.from_rows(rows, symbol, timeframe)
