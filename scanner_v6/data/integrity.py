"""Market-data integrity for Scanner V6 (Module A): completed-candle boundary, gap detection, data state, and the
provider boundary. Neutral infrastructure: no trading rule, no candle is ever created, filled, interpolated or changed.

Spec references (research/v6/specs/V6_TRADING_SPEC_v0.2.md):
  CK-24  only completed candles may generate structure, liquidity, patterns and confirmation; no look-ahead;
         zero-based indexing; reject duplicate / out-of-order / invalid OHLC; never fabricate candles for missing
         intervals; stale or disconnected data suspends new entries; on reconnection process available completed
         candles chronologically.
  CK-9   zero-based candle indexing.
  OQ-3   `data_state` = NORMAL / DATA_INTERRUPTED / DATA_RESUMED, a separate field (not a lifecycle status), with
         interruption and recovery timestamps. Open trades keep their lifecycle status; no fabricated candles, fills
         or exits; a pending setup that misses its next-open deadline is handled downstream (EXPIRED /
         NEXT_CANDLE_UNAVAILABLE), not here.
  OQ-7   session calendar supplied explicitly (market_config.SessionCalendar); nothing hardcoded.
  O7     (structure-layer sessions / gaps) stays OPEN: gap reports here are data facts, not structure rules.

Completed-candle contract (A2): a data source states completion EXPLICITLY with CandleUpdate.is_complete. Only
CompletedCandleGate turns a completed update into a Candle, so a detector (which takes Candle objects) can never be
given a forming candle. Completion is never inferred from wall-clock time.

Research only: no orders, no broker, no live routing, no provider integration.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, List, Optional, Protocol, Tuple

from .candle_models import Candle, CandleError, CandleSeries, TimestampLike, to_utc
from .market_config import ConfigError, SessionCalendar, SessionKind, validate_timeframe


# --------------------------------------------------------------------------- A2: completed vs incomplete candles
@dataclass(frozen=True)
class CandleUpdate:
    """One OHLCV update for the candle that opened at `ts`, as delivered by a data source. `is_complete` is
    mandatory and must be a real bool: True only when the source states the candle is closed."""
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_complete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.is_complete, bool):
            raise CandleError("is_complete must be True or False, got %r" % (self.is_complete,))
        probe = Candle(0, self.ts, self.open, self.high, self.low, self.close, self.volume)   # same OHLCV checks
        for name in ("ts", "open", "high", "low", "close", "volume"):
            object.__setattr__(self, name, getattr(probe, name))


class GateError(ValueError):
    """An update that would duplicate, reorder or change an already completed candle."""


class CompletedCandleGate:
    """Turns a stream of CandleUpdates into completed Candles with indices 0, 1, 2, ...

    - An incomplete update is held as `forming` and never returned.
    - A completed update returns the new Candle (index = number of completed candles before it).
    - An update at or before the last completed candle's time raises GateError: a completed candle is never
      duplicated, reordered or modified.
    - If a newer candle starts while an older one is still forming, the older one is NOT completed: it is recorded
      in `abandoned` and never becomes a Candle (the missing candle then shows up in gap detection).
    """

    def __init__(self) -> None:
        self._done: List[Candle] = []
        self.forming: Optional[CandleUpdate] = None
        self.abandoned: List[CandleUpdate] = []

    def feed(self, u: CandleUpdate) -> Optional[Candle]:
        if not isinstance(u, CandleUpdate):
            raise TypeError("feed needs a CandleUpdate")
        if self._done and u.ts <= self._done[-1].ts:
            raise GateError("update at %s is not after the last completed candle %d (%s)"
                            % (u.ts.isoformat(), self._done[-1].index, self._done[-1].ts.isoformat()))
        if self.forming is not None:
            if u.ts < self.forming.ts:
                raise GateError("update at %s is before the forming candle at %s"
                                % (u.ts.isoformat(), self.forming.ts.isoformat()))
            if u.ts > self.forming.ts:
                self.abandoned.append(self.forming)
                self.forming = None
        if not u.is_complete:
            self.forming = u
            return None
        self.forming = None
        c = Candle(len(self._done), u.ts, u.open, u.high, u.low, u.close, u.volume)
        self._done.append(c)
        return c

    @property
    def completed(self) -> CandleSeries:
        """Every completed candle so far, as a validated series."""
        return CandleSeries(self._done)


def drive_completed(updates: Iterable[CandleUpdate], stream) -> Tuple[List, CompletedCandleGate]:
    """Feed `updates` through a CompletedCandleGate and give ONLY completed candles to `stream.on_candle`.
    Returns (events, gate)."""
    gate = CompletedCandleGate()
    events: List = []
    for u in updates:
        c = gate.feed(u)
        if c is not None:
            events.extend(stream.on_candle(c))
    return events, gate


class MarketDataProvider(Protocol):
    """Boundary for a future market-data source (A7). No implementation exists; no provider, credential or
    instrument mapping is configured. A provider yields CandleUpdates in time order and states completion
    explicitly."""

    def updates(self) -> Iterable[CandleUpdate]: ...


# --------------------------------------------------------------------------- A3: gaps
class GapKind(str, Enum):
    MISSING_CANDLES = "MISSING_CANDLES"            # expected candle slots inside the configured sessions are absent
    SESSION_CLOSURE = "SESSION_CLOSURE"            # every absent slot lies outside the configured sessions
    UNCLASSIFIED_GAP = "UNCLASSIFIED_GAP"          # absent slots, but no calendar to tell closure from missing data
    IRREGULAR_INTERVAL = "IRREGULAR_INTERVAL"      # spacing is not a whole multiple of the timeframe
    OUT_OF_SESSION_CANDLE = "OUT_OF_SESSION_CANDLE"  # a candle opens outside every configured session


class GapReportStatus(str, Enum):
    OK = "OK"             # timeframe AND calendar supplied, and every finding could be classified
    UNKNOWN = "UNKNOWN"   # timeframe or calendar missing, or an interval could not be classified; nothing is assumed


@dataclass(frozen=True)
class Gap:
    """One finding between candle `prev_index` and candle `index` (or about candle `index` alone, for
    OUT_OF_SESSION_CANDLE, where prev_index is None). `slots` = candle opens expected strictly between the two
    candles at the timeframe; `missing_count` = how many of them fall inside the configured sessions (None when
    that cannot be known)."""
    kind: GapKind
    prev_index: Optional[int]
    index: int
    prev_ts: Optional[datetime]
    ts: datetime
    slots: Optional[int] = None
    missing_count: Optional[int] = None
    first_missing_ts: Optional[datetime] = None
    last_missing_ts: Optional[datetime] = None
    crosses_session_break: Optional[bool] = None
    # Source rows between the two candles that were excluded as invalid (series.source_positions). 0 = no source
    # row was skipped there (a genuine missing candle); > 0 = that many skipped source rows, each recorded in
    # series.invalid_rows (CandleSeries refuses an unaccounted skipped row); None = provenance unknown
    # (series.source_positions is None). Not set for OUT_OF_SESSION_CANDLE. Assumption: source_positions are
    # positions in ONE source array, in source order.
    skipped_source_rows: Optional[int] = None


@dataclass(frozen=True)
class GapReport:
    status: GapReportStatus
    reason: Optional[str]
    gaps: Tuple[Gap, ...] = field(default_factory=tuple)


def _classify(prev: Candle, cur: Candle, tf: timedelta, cal: Optional[SessionCalendar]) -> List[Gap]:
    out: List[Gap] = []
    if cal is not None and cal.kind is SessionKind.EXCHANGE and not cal.contains(cur.ts):
        out.append(Gap(GapKind.OUT_OF_SESSION_CANDLE, None, cur.index, None, cur.ts))
    delta = cur.ts - prev.ts
    if delta == tf:
        return out
    if delta < tf or delta % tf != timedelta(0):
        out.append(Gap(GapKind.IRREGULAR_INTERVAL, prev.index, cur.index, prev.ts, cur.ts))
        return out
    slots = delta // tf - 1
    if cal is None:
        out.append(Gap(GapKind.UNCLASSIFIED_GAP, prev.index, cur.index, prev.ts, cur.ts, slots=slots))
        return out
    if cal.kind is SessionKind.CONTINUOUS:
        out.append(Gap(GapKind.MISSING_CANDLES, prev.index, cur.index, prev.ts, cur.ts, slots, slots,
                       prev.ts + tf, cur.ts - tf, False))
        return out
    missing = [prev.ts + tf * j for j in range(1, slots + 1) if cal.contains(prev.ts + tf * j)]
    a, b = cal.session_index(prev.ts), cal.session_index(cur.ts)
    crosses = a is None or b is None or a != b
    if missing:
        out.append(Gap(GapKind.MISSING_CANDLES, prev.index, cur.index, prev.ts, cur.ts, slots, len(missing),
                       missing[0], missing[-1], crosses))
    else:
        out.append(Gap(GapKind.SESSION_CLOSURE, prev.index, cur.index, prev.ts, cur.ts, slots, 0, None, None, crosses))
    return out


def _with_source(g: Gap, prev_pos: int, pos: int) -> Gap:
    if g.kind is GapKind.OUT_OF_SESSION_CANDLE:
        return g
    return replace(g, skipped_source_rows=pos - prev_pos - 1)


def _report(gaps: Tuple[Gap, ...], calendar: Optional[SessionCalendar]) -> GapReport:
    """Status for findings made WITH a timeframe. Priority: SESSION_CALENDAR_MISSING (no calendar: session validity was
    never checked, even when no gap was found) > IRREGULAR_INTERVAL (a spacing that is not a whole multiple of the
    timeframe cannot be classified as missing data or session closure) > OK."""
    if calendar is None:
        return GapReport(GapReportStatus.UNKNOWN, "SESSION_CALENDAR_MISSING", gaps)
    if any(g.kind is GapKind.IRREGULAR_INTERVAL for g in gaps):
        return GapReport(GapReportStatus.UNKNOWN, "IRREGULAR_INTERVAL", gaps)
    return GapReport(GapReportStatus.OK, None, gaps)


def _check_inputs(timeframe: Optional[timedelta], calendar: Optional[SessionCalendar]) -> None:
    if timeframe is not None:
        validate_timeframe(timeframe)
    if calendar is not None and not isinstance(calendar, SessionCalendar):
        raise ConfigError("calendar must be a SessionCalendar or None")


def detect_gaps(series: CandleSeries, timeframe: Optional[timedelta],
                calendar: Optional[SessionCalendar] = None) -> GapReport:
    """Every gap finding in `series` (batch form). Status, in priority order:
      - no timeframe: UNKNOWN / TIMEFRAME_MISSING, no findings (nothing can be judged);
      - no calendar: UNKNOWN / SESSION_CALENDAR_MISSING, ALWAYS (even with no gap found: session validity was not
        checked); timestamp findings are still listed (absent slots as UNCLASSIFIED_GAP). No calendar is invented;
      - a calendar, but an IRREGULAR_INTERVAL finding: UNKNOWN / IRREGULAR_INTERVAL;
      - otherwise OK (possibly with classified findings: MISSING_CANDLES, SESSION_CLOSURE, OUT_OF_SESSION_CANDLE)."""
    _check_inputs(timeframe, calendar)
    if timeframe is None:
        return GapReport(GapReportStatus.UNKNOWN, "TIMEFRAME_MISSING")
    gaps: List[Gap] = []
    if calendar is not None and calendar.kind is SessionKind.EXCHANGE and len(series) and \
            not calendar.contains(series[0].ts):
        gaps.append(Gap(GapKind.OUT_OF_SESSION_CANDLE, None, 0, None, series[0].ts))
    sp = getattr(series, "source_positions", None)
    for i in range(1, len(series)):
        found = _classify(series[i - 1], series[i], timeframe, calendar)
        if sp is not None:
            found = [_with_source(g, sp[i - 1], sp[i]) for g in found]
        gaps.extend(found)
    return _report(tuple(gaps), calendar)


class GapStream:
    """Streaming form of detect_gaps: feed completed candles in order; on_candle returns the findings known at that
    candle's close. Same findings as detect_gaps at every prefix. Needs an explicit timeframe. report() gives the
    GapReport so far, with the same status rule as detect_gaps (equal to detect_gaps on the same prefix when the
    stream gets complete provenance, or none)."""

    def __init__(self, timeframe: timedelta, calendar: Optional[SessionCalendar] = None):
        if timeframe is None:
            raise ConfigError("GapStream needs an explicit timeframe")
        _check_inputs(timeframe, calendar)
        self.tf, self.cal = timeframe, calendar
        self._prev: Optional[Candle] = None
        self._prev_pos: Optional[int] = None
        self._with_pos: Optional[bool] = None
        self._gaps: List[Gap] = []

    def on_candle(self, c: Candle, source_position: Optional[int] = None,
                  invalid_positions: Optional[Iterable[int]] = None) -> List[Gap]:
        """`source_position` (optional, all-or-nothing): the candle's original source row, as in
        CandleSeries.source_positions.
        `invalid_positions` (optional, needs source_position): the source rows recorded as INVALID since the previous
        candle (for the first candle: before it), e.g. the InvalidRow.source_position values. They must be unique,
        increasing, strictly between the previous and this candle's source row, and (after the first candle) cover
        every source row in between, as CandleSeries requires.

        skipped_source_rows on a gap: None without source positions; 0 when the two candles are adjacent source rows;
        the number of recorded invalid rows when `invalid_positions` is given; otherwise None. A position difference
        alone is never reported as an invalid-row count."""
        if not isinstance(c, Candle):
            raise TypeError("on_candle needs a Candle")
        with_pos = source_position is not None
        if self._with_pos is not None and with_pos != self._with_pos:
            raise ValueError("give source_position for every candle or for none")
        if with_pos and (isinstance(source_position, bool) or not isinstance(source_position, int) or
                         source_position < 0 or (self._prev_pos is not None and source_position <= self._prev_pos)):
            raise ValueError("source_position must be a strictly increasing non-negative int")
        inv: Optional[Tuple[int, ...]] = None
        if invalid_positions is not None:
            if not with_pos:
                raise ValueError("invalid_positions need source_position")
            inv = tuple(invalid_positions)
            lo = -1 if self._prev_pos is None else self._prev_pos
            for j, p in enumerate(inv):
                if isinstance(p, bool) or not isinstance(p, int) or not lo < p < source_position or \
                        (j and p <= inv[j - 1]):
                    raise ValueError("invalid_positions must be unique, increasing and strictly between source "
                                     "rows %d and %d (entry %d)" % (lo, source_position, j))
            if self._prev_pos is not None and len(inv) != source_position - self._prev_pos - 1:
                raise ValueError("invalid_positions %r do not account for every source row between %d and %d"
                                 % (inv, self._prev_pos, source_position))
        expected = 0 if self._prev is None else self._prev.index + 1
        if c.index != expected:
            raise CandleError("candle index %d out of order (expected %d)" % (c.index, expected))
        if self._prev is not None and c.ts <= self._prev.ts:
            raise CandleError("candle %d is not after the previous candle" % c.index)
        if self._prev is None:
            out = []
            if self.cal is not None and self.cal.kind is SessionKind.EXCHANGE and not self.cal.contains(c.ts):
                out.append(Gap(GapKind.OUT_OF_SESSION_CANDLE, None, 0, None, c.ts))
        else:
            out = _classify(self._prev, c, self.tf, self.cal)
            if with_pos:
                diff = source_position - self._prev_pos - 1
                n = 0 if diff == 0 else (len(inv) if inv is not None else None)   # unverified difference -> None
                out = [g if g.kind is GapKind.OUT_OF_SESSION_CANDLE else replace(g, skipped_source_rows=n)
                       for g in out]
        self._prev, self._prev_pos, self._with_pos = c, source_position, with_pos
        self._gaps.extend(out)
        return out

    def report(self) -> GapReport:
        """Every finding so far, with the detect_gaps status rule (SESSION_CALENDAR_MISSING without a calendar)."""
        return _report(tuple(self._gaps), self.cal)


# --------------------------------------------------------------------------- A5: data state (OQ-3)
class DataState(str, Enum):
    NORMAL = "NORMAL"
    DATA_INTERRUPTED = "DATA_INTERRUPTED"
    DATA_RESUMED = "DATA_RESUMED"


class DataStateError(ValueError):
    """A transition OQ-3 does not allow, or timestamps that go backwards."""


@dataclass(frozen=True)
class DataStateChange:
    at: datetime
    before: DataState
    after: DataState
    reason: str


@dataclass(frozen=True)
class StalenessPolicy:
    """Explicit maximum age of the newest data before the feed counts as stale. There is no default value."""
    max_age: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.max_age, timedelta) or self.max_age <= timedelta(0):
            raise ConfigError("max_age must be a positive timedelta")


class DataStateTracker:
    """The OQ-3 `data_state` field with its interruption and recovery timestamps.

    Transitions: NORMAL or DATA_RESUMED -> DATA_INTERRUPTED (mark_interrupted); DATA_INTERRUPTED -> DATA_RESUMED
    (mark_resumed). Anything else raises DataStateError. A return from DATA_RESUMED to NORMAL is not defined by the
    specification, so no such transition exists here.

    `new_entries_suspended` is True while DATA_INTERRUPTED (CK-24 / OQ-3). This tracker never creates candles,
    fills or exits and never touches any trade's lifecycle status."""

    def __init__(self) -> None:
        self.state = DataState.NORMAL
        self.history: List[DataStateChange] = []
        self.interrupted_at: Optional[datetime] = None
        self.resumed_at: Optional[datetime] = None

    @property
    def new_entries_suspended(self) -> bool:
        return self.state is DataState.DATA_INTERRUPTED

    def _check_time(self, t: datetime) -> None:
        if self.history and t < self.history[-1].at:
            raise DataStateError("time %s is before the last change at %s"
                                 % (t.isoformat(), self.history[-1].at.isoformat()))

    def mark_interrupted(self, at: TimestampLike, reason: str) -> DataStateChange:
        t = to_utc(at)
        if self.state is DataState.DATA_INTERRUPTED:
            raise DataStateError("already DATA_INTERRUPTED since %s" % self.interrupted_at.isoformat())
        self._check_time(t)
        ch = DataStateChange(t, self.state, DataState.DATA_INTERRUPTED, reason)
        self.state, self.interrupted_at = DataState.DATA_INTERRUPTED, t
        self.history.append(ch)
        return ch

    def mark_resumed(self, at: TimestampLike, reason: str) -> DataStateChange:
        t = to_utc(at)
        if self.state is not DataState.DATA_INTERRUPTED:
            raise DataStateError("can only resume from DATA_INTERRUPTED (state is %s)" % self.state.value)
        self._check_time(t)
        ch = DataStateChange(t, self.state, DataState.DATA_RESUMED, reason)
        self.state, self.resumed_at = DataState.DATA_RESUMED, t
        self.history.append(ch)
        return ch

    def observe(self, now: TimestampLike, last_data_at: Optional[TimestampLike],
                policy: StalenessPolicy) -> Optional[DataStateChange]:
        """Apply an explicit staleness policy at time `now` (supplied by the caller; never read from a clock here).
        No data yet, or data older than policy.max_age -> DATA_INTERRUPTED (once). Fresh data while interrupted ->
        DATA_RESUMED. Otherwise no change (None)."""
        if not isinstance(policy, StalenessPolicy):
            raise ConfigError("observe needs an explicit StalenessPolicy")
        t = to_utc(now)
        if last_data_at is None:
            stale, why = True, "NO_DATA"
        else:
            last = to_utc(last_data_at)
            if last > t:
                raise DataStateError("last data time %s is after now %s" % (last.isoformat(), t.isoformat()))
            stale, why = t - last > policy.max_age, "STALE"
        if stale and self.state is not DataState.DATA_INTERRUPTED:
            return self.mark_interrupted(t, why)
        if not stale and self.state is DataState.DATA_INTERRUPTED:
            return self.mark_resumed(t, "FRESH_DATA")
        return None
