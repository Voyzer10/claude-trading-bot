"""Historical OHLCV datasets for V6 backtests: loading, validation and integrity metadata.

Accepted files (one symbol per file):
  * CSV with the header `ts,open,high,low,close,volume`; `ts` is the bar OPEN time, ISO-8601 with an explicit UTC
    offset (`2026-11-23T14:30:00Z`, `...+00:00`) or integer epoch seconds (UTC). A naive timestamp is refused.
  * JSON `{"bars": [{"t", "o", "h", "l", "c", "v"}, ...]}` (the Alpaca bars shape).
Optional sidecar `<file>.meta.json` with at least {"source": "..."}; a `--source` given on the command line wins.

Validation never repairs data. Rows are never re-ordered, de-duplicated or filled in:
  ERRORS (the run refuses to start): unparsable rows, invalid OHLCV (high < max(open, close), low > min(open, close),
  negative volume, non-finite values), timestamps out of order, duplicate timestamps, bars outside a trading session
  or ending after the session close, bars off the timeframe grid, and no bars in the requested range.
  GAPS (reported, and handled by the run's `gap_policy`): expected bars missing inside a session, and whole sessions
  with no bars. With `gap_policy="interrupt"` each gap becomes a DATA_INTERRUPTED / DATA_RESUMED pair (Module E's
  OQ-3 data-interruption handling); with `gap_policy="fail"` any gap is an error.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from scanner_v6.data.candle_models import Candle
from scanner_v6.data.market_config import SessionCalendar, SessionKind

CSV_HEADER = ["ts", "open", "high", "low", "close", "volume"]
MAX_LISTED = 20


class DatasetError(ValueError):
    """The dataset cannot be used. `problems` lists every reason found (not just the first)."""

    def __init__(self, message: str, problems: Optional[List[str]] = None):
        super().__init__(message if not problems else "%s:\n  - %s" % (message, "\n  - ".join(problems[:MAX_LISTED])))
        self.problems = list(problems or [])


@dataclass(frozen=True)
class Row:
    line: int
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Dataset:
    symbol: str
    path: str
    sha256: str
    source: str
    rows: List[Row]
    timeframe: timedelta
    integrity: Dict[str, Any] = field(default_factory=dict)
    gaps: List[Tuple[datetime, datetime]] = field(default_factory=list)   # (expected start, next actual bar start)

    def candles(self) -> List[Candle]:
        return [Candle(i, r.ts, r.open, r.high, r.low, r.close, r.volume) for i, r in enumerate(self.rows)]


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_ts(v: Any) -> datetime:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return datetime.fromtimestamp(int(v), tz=timezone.utc)
    s = str(v).strip()
    if s.lstrip("-").isdigit():
        return datetime.fromtimestamp(int(s), tz=timezone.utc)
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("timestamp %r has no UTC offset" % s)
    return t.astimezone(timezone.utc)


def _num(v: Any, name: str) -> float:
    if isinstance(v, bool):
        raise ValueError("%s is not a number" % name)
    x = float(v)
    if not math.isfinite(x):
        raise ValueError("%s is not finite" % name)
    return x


def _raw_rows(path: str) -> List[Tuple[int, Dict[str, Any]]]:
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        bars = d.get("bars") if isinstance(d, dict) else None
        if not isinstance(bars, list):
            raise DatasetError("%s: JSON datasets need a 'bars' list" % path)
        return [(i + 1, {"ts": b.get("t"), "open": b.get("o"), "high": b.get("h"), "low": b.get("l"),
                         "close": b.get("c"), "volume": b.get("v")} if isinstance(b, dict) else {})
                for i, b in enumerate(bars)]
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        if rd.fieldnames is None or [f.strip() for f in rd.fieldnames] != CSV_HEADER:
            raise DatasetError("%s: CSV header must be exactly %s, got %s" % (path, ",".join(CSV_HEADER), rd.fieldnames))
        return [(i + 2, row) for i, row in enumerate(rd)]


def _source(path: str, source: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    meta: Dict[str, Any] = {}
    side = path + ".meta.json"
    if os.path.exists(side):
        with open(side, encoding="utf-8") as fh:
            meta = json.load(fh)
    src = source or meta.get("source")
    if not isinstance(src, str) or not src.strip():
        raise DatasetError("%s: the dataset source is not declared (give --source or a .meta.json sidecar)" % path)
    return src.strip(), meta


def _session_of(session: SessionCalendar, t: datetime) -> Optional[Tuple[datetime, datetime]]:
    if session.kind is SessionKind.CONTINUOUS:
        return (datetime.min.replace(tzinfo=timezone.utc), datetime.max.replace(tzinfo=timezone.utc))
    for o, c in session.sessions:
        if o <= t < c:
            return o, c
    return None


def _expected_grid(session: SessionCalendar, tf: timedelta, first: datetime, last: datetime) -> List[datetime]:
    """Every bar start the calendar expects in [first, last] (sessions intersecting the data span)."""
    out: List[datetime] = []
    if session.kind is SessionKind.CONTINUOUS:
        t = first
        while t <= last:
            out.append(t)
            t += tf
        return out
    for o, c in session.sessions:
        if c <= first or o > last:
            continue
        t = o
        while t + tf <= c:
            if first <= t <= last:
                out.append(t)
            t += tf
    return out


def load_dataset(path: str, symbol: str, timeframe: timedelta, session: SessionCalendar, start: Optional[date] = None,
                 end: Optional[date] = None, source: Optional[str] = None, gap_policy: str = "interrupt") -> Dataset:
    if gap_policy not in ("interrupt", "fail"):
        raise DatasetError("gap_policy must be 'interrupt' or 'fail', got %r" % (gap_policy,))
    if not os.path.isfile(path):
        raise DatasetError("dataset file %s does not exist" % path)
    if start and end and end < start:
        raise DatasetError("end date %s is before start date %s" % (end, start))
    src, meta = _source(path, source)
    if meta.get("symbol") not in (None, symbol):
        raise DatasetError("%s is declared for symbol %s, not %s" % (path, meta.get("symbol"), symbol))
    tz = ZoneInfo(session.timezone)
    lo = datetime.combine(start, datetime.min.time(), tz).astimezone(timezone.utc) if start else None
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), tz).astimezone(timezone.utc) if end else None

    errors: List[str] = []
    rows: List[Row] = []
    total = 0
    for line, raw in _raw_rows(path):
        total += 1
        try:
            ts = _parse_ts(raw.get("ts"))
            o, h, l, c, v = (_num(raw.get(k), k) for k in ("open", "high", "low", "close", "volume"))
        except (TypeError, ValueError) as e:
            errors.append("line %d: unparsable row (%s)" % (line, e))
            continue
        if (lo and ts < lo) or (hi and ts >= hi):
            continue
        if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c) or h < l or v < 0:
            errors.append("line %d (%s): invalid OHLCV o=%r h=%r l=%r c=%r v=%r" % (line, ts.isoformat(), o, h, l, c, v))
            continue
        rows.append(Row(line, ts, o, h, l, c, v))

    for a, b in zip(rows, rows[1:]):
        if b.ts == a.ts:
            errors.append("line %d: duplicate timestamp %s (also line %d)" % (b.line, b.ts.isoformat(), a.line))
        elif b.ts < a.ts:
            errors.append("line %d: timestamp %s is out of order (after %s)" % (b.line, b.ts.isoformat(), a.ts.isoformat()))
    for r in rows:
        sess = _session_of(session, r.ts)
        if sess is None:
            errors.append("line %d: %s is outside every trading session" % (r.line, r.ts.isoformat()))
        elif r.ts + timeframe > sess[1]:
            errors.append("line %d: bar %s ends after the session close %s" % (r.line, r.ts.isoformat(), sess[1].isoformat()))
        else:
            anchor = sess[0] if session.kind is SessionKind.EXCHANGE else datetime(1970, 1, 1, tzinfo=timezone.utc)
            if (r.ts - anchor) % timeframe != timedelta(0):
                errors.append("line %d: bar %s is not on the %s grid" % (r.line, r.ts.isoformat(), timeframe))
    if not rows and not errors:
        errors.append("no bars in the requested range %s .. %s" % (start, end))
    if errors:
        raise DatasetError("dataset %s (%s) is not usable (%d problem(s))" % (path, symbol, len(errors)), errors)

    have = {r.ts for r in rows}
    expected = _expected_grid(session, timeframe, rows[0].ts, rows[-1].ts)
    missing = [t for t in expected if t not in have]
    gaps: List[Tuple[datetime, datetime]] = []
    miss_set = set(missing)
    max_run = 0
    for a, b in zip(rows, rows[1:]):
        t = a.ts + timeframe
        if t < b.ts:
            run = sum(1 for x in _expected_grid(session, timeframe, t, b.ts - timeframe) if x in miss_set)
            if run:
                gaps.append((t, b.ts))
                max_run = max(max_run, run)
    if gaps and gap_policy == "fail":
        raise DatasetError("dataset %s (%s) has %d gap(s) and gap_policy is 'fail'" % (path, symbol, len(gaps)),
                           ["missing bars from %s up to %s" % (a.isoformat(), b.isoformat()) for a, b in gaps])
    integrity = {
        "symbol": symbol, "path": os.path.abspath(path), "sha256": file_sha256(path), "source": src,
        "source_metadata": meta, "rows_in_file": total, "rows_used": len(rows),
        "first_bar": rows[0].ts.isoformat(), "last_bar": rows[-1].ts.isoformat(),
        "range": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
                  "timezone": session.timezone},
        "timeframe_seconds": int(timeframe.total_seconds()), "duplicates": 0, "out_of_order": 0,
        "expected_bars": len(expected), "missing_bars": len(missing), "gaps": len(gaps),
        "max_consecutive_missing": max_run,
        "gap_list": [[a.isoformat(), b.isoformat()] for a, b in gaps[:MAX_LISTED]], "gap_policy": gap_policy,
    }
    return Dataset(symbol, os.path.abspath(path), integrity["sha256"], src, rows, timeframe, integrity, gaps)


def write_csv(path: str, rows: List[Tuple[datetime, float, float, float, float, float]], meta: Dict[str, Any]) -> str:
    """Write a dataset file plus its .meta.json sidecar (used by `fetch` and by fixture generation)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(CSV_HEADER)
        for ts, o, h, l, c, v in rows:
            w.writerow([ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), repr(o), repr(h), repr(l),
                        repr(c), repr(v)])
    with open(path + ".meta.json", "w", encoding="utf-8") as fh:
        json.dump(dict(meta, sha256=file_sha256(path), rows=len(rows)), fh, indent=1, sort_keys=True)
    return path
