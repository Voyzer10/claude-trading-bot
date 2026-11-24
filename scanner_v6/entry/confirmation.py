"""Module D: sweep-to-pattern association, pattern confirmation / expiry / invalidation, and the setup lifecycle up to
CONFIRMED (PAPER ONLY; nothing here enters, sizes, exits or places an order).

Built on Module B (SetupSweepStream: structure, liquidity, setup candidates) and Module C (CandlestickStream: DETECTED
patterns and the CK-1 tolerance). No liquidity, structure or candlestick detection is repeated here.

Approved rules implemented (spec Section 16 / 17; the module docstrings of B and C list theirs):
  CS-9, CK-6     a pattern qualifies for a sweep at candle s only if start_candle > s and end_candle <= s + 5 (the
                 whole pattern inside the five completed candles after the sweep); the sweep candle never counts.
  Section 3,     SSL sweep (BUY) -> BULLISH_BIAS patterns only; BSL sweep (SELL) -> BEARISH_BIAS only; NEUTRAL /
  CS-9, CK-7,    UNDETERMINED never qualify; a context-labelled shape without its required trend (UNCLASSIFIED_SHAPE,
  CK-4           CK-4) never qualifies.
  CK-7, CK-11    every qualifying pattern is tracked (concurrently, overlap clarification); each has its own window of
                 the next 3 completed candles; the 5-candle sweep window never extends; the first pattern that confirms
                 advances the setup; after CONFIRMED no other pattern of that sweep creates a setup.
  16.F, CS-7,    bullish: close > pattern_high + eps; bearish: close < pattern_low - eps (eps = TickSize x 1e-6, the
  CS-8, CK-8     Module C comparator); pattern_high / pattern_low = full formation range (Engulfing: both candles).
  16.G, CK-12    bullish invalidation close < pattern_low - eps; bearish close > pattern_high + eps; no confirmation in
                 3 candles -> pattern EXPIRED; one terminal event per pattern (CS-10).
  CS-10, CK-2    confirmation is a separate event: confirmation:<pattern_id>:<confirmation_candle>, with pattern_id,
                 confirmation_candle, direction, timestamp; setup id setup:<sweep_group_id>:<pattern_id>.
  CK-10, CK-18   setup lifecycle statuses, separate from pattern statuses; every transition records the zero-based
                 candle index and timestamp; terminal statuses never reactivate. No qualifying pattern in the window,
                 or all eligible patterns expired -> EXPIRED; all eligible patterns invalidated -> INVALIDATED.
  OQ-2, CK-13    `reason_code` (CK-13) and `disposition_reason` (OQ-2) are separate fields; Module D sets neither
                 (both belong to the entry / risk stage).
  OQ-3, CK-24    `data_state` NORMAL / DATA_INTERRUPTED / DATA_RESUMED is a flag, not a lifecycle status; interruption
                 and recovery timestamps are recorded, each no earlier than the preceding data-state change and the
                 last processed candle; no candle, confirmation or exit is fabricated. DATA_RESUMED stays the flag
                 until the next interruption (no DATA_RESUMED -> NORMAL step is defined, so none is made).

Owner decisions MD-1..MD-4 (OWNER APPROVED 24 Nov 2026; spec 17.U):
  MD-1  several tracked patterns confirming on one candle: the setup takes the earliest end (detection) candle, then
        the earliest start candle, then the 16.A family order. Every one of them still gets its own CONFIRMED event.
  MD-2  the setup record is keyed by Module B's candidate key (bos_id, group_id) from the sweep; setup_id
        (CK-2) is assigned once, at CONFIRMED, from the confirming pattern; it stays None if the setup never confirms.
  MD-3  no confirmation and a mix of expired and invalidated patterns -> EXPIRED (INVALIDATED only when every
        eligible pattern was invalidated).
  MD-4  the record is created at the qualifying sweep (SWEEP_DETECTED) with CHOCH_DETECTED and BOS_CONFIRMED entries
        carrying their ORIGINAL candle index / timestamp; transitions only move forward (no step back from
        PATTERN_DETECTED); ENTERED, STOPPED_OUT, TARGET_HIT and NO_TRADE are reserved for the entry / execution module.

Implementation choices (ordering only; no trading rule):
  * Order at close k: (1) Module B (structure first, so an opposite CHoCH / BOS at k invalidates before anything
    else, 17.S), (2) Module C patterns ending at k, (3) tracked patterns of every setup: confirm, else invalidate,
    else expire at end + 3, in MD-1 order, (4) setup confirmation (MD-1), (5) new patterns ending at k are qualified,
    (6) a setup whose sweep window has closed and whose tracked patterns are all terminal is resolved (CK-18 / MD-3).
  * A pattern's confirmation and invalidation conditions cannot both hold on one candle (high >= low and eps > 0);
    when one pattern confirms and another invalidates on the same candle, the confirmation advances the setup.
  * Pattern confirmation is evaluated for patterns tracked by a setup. A tracked pattern is followed to its own
    terminal event even if its setup ends first. Untracked patterns keep Module C's DETECTED status.
  * Missing tick size: Module C scores nothing (CK-1); setups stay at SWEEP_DETECTED with diagnostic
    CONFIRMATION_UNSCORABLE (no expiry or confirmation is invented).
  * Windows count completed candles (zero-based indices, CK-9); an interruption adds no candles and removes none.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from scanner_v6.data.candle_models import Candle, CandleError, CandleSeries
from scanner_v6.data.market_config import MarketDataConfig
from scanner_v6.liquidity import setup_sweep as B
from scanner_v6.models import Direction, Event, EventStamp, ModelError
from scanner_v6.structure.choch import CHoCHBreak

from .candlesticks import (BEARISH_BIAS, BULLISH_BIAS, DETECTED, NEUTRAL, PATTERN_TYPES, UNCLASSIFIED_SHAPE,
                           UNDETERMINED, CandlestickConfig, CandlestickStream, PatternEvent)

# ---------------------------------------------------------------- windows (CS-7, CS-9, CK-6, CK-11)
SWEEP_WINDOW = 5
CONFIRMATION_WINDOW = 3

# ---------------------------------------------------------------- pattern statuses (16.G / CS-10), own layer
PATTERN_DETECTED_STATUS = DETECTED
PATTERN_CONFIRMED = "CONFIRMED"
PATTERN_EXPIRED = "EXPIRED"
PATTERN_INVALIDATED = "INVALIDATED"
PATTERN_TERMINAL = (PATTERN_CONFIRMED, PATTERN_EXPIRED, PATTERN_INVALIDATED)

# ---------------------------------------------------------------- setup lifecycle statuses (CK-10), own layer
CHOCH_DETECTED = "CHOCH_DETECTED"
BOS_CONFIRMED = "BOS_CONFIRMED"
SWEEP_DETECTED = "SWEEP_DETECTED"
PATTERN_DETECTED = "PATTERN_DETECTED"
CONFIRMED = "CONFIRMED"
ENTERED = "ENTERED"
STOPPED_OUT = "STOPPED_OUT"
TARGET_HIT = "TARGET_HIT"
EXPIRED = "EXPIRED"
INVALIDATED = "INVALIDATED"
NO_TRADE = "NO_TRADE"
SETUP_STATUSES = (CHOCH_DETECTED, BOS_CONFIRMED, SWEEP_DETECTED, PATTERN_DETECTED, CONFIRMED, ENTERED, STOPPED_OUT,
                  TARGET_HIT, EXPIRED, INVALIDATED, NO_TRADE)
SETUP_TERMINAL = (EXPIRED, INVALIDATED, NO_TRADE, STOPPED_OUT, TARGET_HIT)
RESERVED_FOR_ENTRY_MODULE = (ENTERED, STOPPED_OUT, TARGET_HIT, NO_TRADE)          # MD-4
# Transitions Module D may perform (MD-4: forward only). CONFIRMED -> ENTERED / NO_TRADE / EXPIRED belong to the entry
# module and are not performed here.
D_TRANSITIONS = {
    SWEEP_DETECTED: (PATTERN_DETECTED, EXPIRED, INVALIDATED),
    PATTERN_DETECTED: (CONFIRMED, EXPIRED, INVALIDATED),
}

# ---------------------------------------------------------------- data state (OQ-3), a flag, not a lifecycle status
NORMAL = "NORMAL"
DATA_INTERRUPTED = "DATA_INTERRUPTED"
DATA_RESUMED = "DATA_RESUMED"

# ---------------------------------------------------------------- detail codes (traceability only; NOT CK-13 reason
# codes and NOT OQ-2 disposition reasons, which stay None in Module D)
NO_QUALIFYING_PATTERN = "NO_QUALIFYING_PATTERN"
ALL_PATTERNS_EXPIRED = "ALL_PATTERNS_EXPIRED"
ALL_PATTERNS_INVALIDATED = "ALL_PATTERNS_INVALIDATED"
MIXED_EXPIRED_INVALIDATED = "MIXED_EXPIRED_INVALIDATED"            # MD-3 -> EXPIRED
# qualification diagnostics
SWEEP_CANDLE_IN_PATTERN = "SWEEP_CANDLE_IN_PATTERN"                # CS-9 / CK-6
BIAS_MISMATCH = "BIAS_MISMATCH"                                    # Section 3 / CK-7
NON_DIRECTIONAL_BIAS = "NON_DIRECTIONAL_BIAS"                      # NEUTRAL / UNDETERMINED (CS-9)
CONTEXT_LABEL_MISSING = "CONTEXT_LABEL_MISSING"                    # UNCLASSIFIED_SHAPE (CK-4)
SETUP_ALREADY_CONFIRMED = "SETUP_ALREADY_CONFIRMED"                # CK-7 / CK-11
SETUP_ALREADY_TERMINAL = "SETUP_ALREADY_TERMINAL"
CONFIRMATION_UNSCORABLE = "CONFIRMATION_UNSCORABLE"                # CK-1: no tick size

REQUIRED_BIAS = {B.BUY: BULLISH_BIAS, B.SELL: BEARISH_BIAS}
BIAS_DIRECTION = {BULLISH_BIAS: "BULLISH", BEARISH_BIAS: "BEARISH"}


class LifecycleError(ValueError):
    """An attempted setup transition that the lifecycle forbids (terminal reactivation, backward step, reserved)."""


def confirmation_id(pattern_id: str, k: int) -> str:
    """CK-2: confirmation:<pattern_id>:<confirmation_candle> (zero-based)."""
    if not isinstance(k, int) or isinstance(k, bool) or k < 0:
        raise ValueError("confirmation candle must be a zero-based int")
    return "confirmation:%s:%d" % (pattern_id, k)


def setup_id(sweep_group_id: str, pattern_id: str) -> str:
    """CK-2: setup:<sweep_group_id>:<pattern_id>."""
    if not sweep_group_id or not pattern_id:
        raise ValueError("setup id needs a sweep group id and a pattern id")
    return "setup:%s:%s" % (sweep_group_id, pattern_id)


def _mdl_order(p: PatternEvent) -> Tuple[int, int, int]:
    """MD-1: earliest end (detection) candle, then earliest start candle, then the 16.A family order."""
    return (p.end_candle, p.start_candle, PATTERN_TYPES.index(p.pattern_type))


@dataclass(frozen=True)
class ConfirmationEvent(Event):
    """CS-10 / CK-2. stamp.index = stamp.confirmed_index = the confirmation candle (known at its close)."""
    pattern_id: str = ""
    confirmation_candle: int = 0
    direction: str = ""
    timestamp: Optional[datetime] = None
    close: float = 0.0
    level: float = 0.0                     # pattern_high (bullish) / pattern_low (bearish)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.id != confirmation_id(self.pattern_id, self.confirmation_candle):
            raise ModelError("confirmation id does not follow CK-2")
        if self.direction not in ("BULLISH", "BEARISH"):
            raise ModelError("confirmation direction must be BULLISH or BEARISH")
        if self.stamp.index != self.confirmation_candle or self.stamp.confirmed_index != self.confirmation_candle:
            raise ModelError("a confirmation is about, and known at, its own candle")


@dataclass(frozen=True)
class PatternState:
    """Pattern-layer status of one TRACKED pattern (16.G / CS-10): DETECTED -> CONFIRMED | EXPIRED | INVALIDATED."""
    pattern_id: str
    setup_key: Tuple[str, str]
    bias: str
    start_candle: int
    end_candle: int
    pattern_high: float
    pattern_low: float
    order: Tuple[int, int, int]
    status: str = PATTERN_DETECTED_STATUS
    closed_index: Optional[int] = None
    closed_ts: Optional[datetime] = None
    confirmation_id: Optional[str] = None


@dataclass(frozen=True)
class Transition:
    """One CK-10 lifecycle entry: status reached at the close of zero-based candle `index`."""
    status: str
    index: int
    ts: datetime
    cause: Optional[str] = None           # the event id that caused it (CHoCH, BOS, group, pattern, confirmation, ...)
    detail: Optional[str] = None
    data_state: str = NORMAL


@dataclass(frozen=True)
class SetupRecord:
    """One setup per sweep group (CK-7 / CK-18). key = Module B candidate key (bos_id, group_id) (MD-2)."""
    bos_id: str
    group_id: str
    setup_side: str
    sweep_side: str
    sweep_index: int
    choch_id: Optional[str]
    status: str
    history: Tuple[Transition, ...]
    tracked: Tuple[str, ...] = ()          # pattern ids, in qualification order
    setup_id: Optional[str] = None         # MD-2: only once CONFIRMED
    confirmed_pattern_id: Optional[str] = None
    confirmation_id: Optional[str] = None
    detail: Optional[str] = None
    reason_code: Optional[str] = None      # CK-13: never set by Module D
    disposition_reason: Optional[str] = None   # OQ-2: never set by Module D
    data_state: str = NORMAL

    @property
    def key(self) -> Tuple[str, str]:
        return (self.bos_id, self.group_id)

    @property
    def window_end(self) -> int:
        return self.sweep_index + SWEEP_WINDOW

    @property
    def terminal(self) -> bool:
        return self.status in SETUP_TERMINAL


@dataclass(frozen=True)
class QualificationDiagnostic:
    index: int
    code: str
    pattern_id: str
    setup_key: Tuple[str, str]
    detail: str = ""


@dataclass(frozen=True)
class DataStateChange:
    """OQ-3: data_state flag change between candles. after_index = last processed candle (None before the first)."""
    state: str
    ts: datetime
    after_index: Optional[int]


def _advance(rec: SetupRecord, status: str, k: int, ts: datetime, cause: Optional[str], detail: Optional[str],
             data_state: str, **changes) -> SetupRecord:
    """The only way a setup changes status. Enforces CK-10 / CK-18 terminal immutability and MD-4 forward-only."""
    if rec.terminal:
        raise LifecycleError("setup %r is terminal (%s) and cannot reactivate" % (rec.key, rec.status))
    if status in RESERVED_FOR_ENTRY_MODULE:
        raise LifecycleError("%s is reserved for the entry / execution module (MD-4)" % status)
    if status not in D_TRANSITIONS.get(rec.status, ()):
        raise LifecycleError("transition %s -> %s is not permitted in Module D" % (rec.status, status))
    if rec.history and k < rec.history[-1].index:
        raise LifecycleError("transition at %d is before the previous one at %d" % (k, rec.history[-1].index))
    return replace(rec, status=status, history=rec.history + (Transition(status, k, ts, cause, detail, data_state),),
                   detail=detail if detail is not None else rec.detail, data_state=data_state, **changes)


# ---------------------------------------------------------------- input validation (F-D1 / F-E1 / F-D2, 17.U)
def check_next_candle(prev: Optional[Candle], c: object) -> None:
    """Pure check of the next stream candle against the previous processed one (None = first candle). Raises
    ValueError, without side effects, unless `c` is a Candle whose index is prev.index + 1 (0 for the first), whose
    open time is strictly after prev's open time, and whose fields pass Module A's Candle rules (finite numbers,
    consistent OHLC, volume >= 0; re-checked here so a mutated object cannot slip through)."""
    if not isinstance(c, Candle):
        raise ValueError("on_candle needs a Candle, got %r" % (type(c).__name__,))
    expected = 0 if prev is None else prev.index + 1
    if isinstance(c.index, bool) or not isinstance(c.index, int) or c.index != expected:
        raise ValueError("candles must arrive in order: got index %r, expected %d" % (c.index, expected))
    if not isinstance(c.ts, datetime):
        raise ValueError("candle %d: ts must be a datetime, got %r" % (c.index, c.ts))
    if prev is not None and c.ts <= prev.ts:
        raise ValueError("candle %d is not after the previous candle (%s <= %s)" % (c.index, c.ts.isoformat(),
                                                                                   prev.ts.isoformat()))
    try:                                                                # Module A rules, one definition
        Candle(c.index, c.ts, c.open, c.high, c.low, c.close, c.volume)
    except CandleError as e:
        raise ValueError("candle %d is invalid: %s" % (c.index, e)) from e


def _require_timeframe(timeframe: Optional[timedelta]) -> timedelta:
    if not isinstance(timeframe, timedelta) or timeframe <= timedelta(0):
        raise ValueError("data-event timestamps need the market timeframe to find a candle's close (CK-26: "
                         "MarketDataConfig.timeframe is %r)" % (timeframe,))
    return timeframe


def check_event_window(prev: Optional[Candle], nxt: Optional[Candle], ts: datetime,
                       timeframe: Optional[timedelta], what: str = "data event") -> None:
    """OQ-3 / ME-4 timestamp window of a data event applied before candle `nxt` (17.U, F-D2):

        prev.ts + timeframe  <=  ts  <=  nxt.ts          (both bounds inclusive)

    i.e. not inside the previous candle (it is complete only at its close) and not inside the next one (an event is
    applied before it). prev None = no lower bound; nxt None = upper bound checked when the candle arrives (stream).
    For contiguous candles the window is the boundary instant; across a gap, any instant in the gap."""
    if not isinstance(ts, datetime) or ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("%s: ts must be a timezone-aware datetime, got %r" % (what, ts))
    if prev is not None:
        close = prev.ts + _require_timeframe(timeframe)
        if ts < close:
            raise ValueError("%s at %s is before the close %s of candle %d (an event cannot be inside a candle)"
                             % (what, ts.isoformat(), close.isoformat(), prev.index))
    if nxt is not None and ts > nxt.ts:
        raise ValueError("%s at %s is after the open %s of candle %d, which it must precede"
                         % (what, ts.isoformat(), nxt.ts.isoformat(), nxt.index))


class ConfirmationStream:
    """Feed completed candles in order. on_candle(c) returns the records produced at c's close, in order. Uses only
    candles 0..c.index; batch (analyze_confirmations) is exactly this stream."""

    def __init__(self, instrument: str, timeframe: str, market: MarketDataConfig,
                 config: Optional[CandlestickConfig] = None):
        self.setup_stream = B.SetupSweepStream()                       # Module B (structure + liquidity inside)
        self.patterns_stream = CandlestickStream(instrument, timeframe, market, config)   # Module C
        self.cmp = self.patterns_stream.cmp                            # CK-1 / CK-8 comparator of Module C
        self.candles: List[Candle] = []
        self.setups: List[SetupRecord] = []
        self._spos: Dict[Tuple[str, str], int] = {}
        self.patterns: Dict[str, PatternEvent] = {}                    # tracked pattern events
        self.pattern_states: List[PatternState] = []
        self._ppos: Dict[str, int] = {}
        self.confirmations: List[ConfirmationEvent] = []
        self.diagnostics: List[QualificationDiagnostic] = []
        self.data_state = NORMAL
        self.data_changes: List[DataStateChange] = []
        self._last_choch: Dict[Direction, Tuple[str, int]] = {}
        self._bos_choch: Dict[str, Optional[Tuple[str, int]]] = {}      # BOS id -> (CHoCH id, index) at BOS time
        self._data_at: List[str] = []                                   # data_state at each processed candle
        self.snapshots: List[Tuple[Tuple[SetupRecord, ...], Tuple[PatternState, ...]]] = []
        self.timeframe: Optional[timedelta] = market.timeframe if market is not None else None   # F-D2 windows

    # ------------------------------------------------------------ data state (OQ-3)
    def mark_data_interrupted(self, ts: datetime) -> DataStateChange:
        if self.data_state == DATA_INTERRUPTED:
            raise ValueError("data is already interrupted")
        return self._data(DATA_INTERRUPTED, ts)

    def mark_data_resumed(self, ts: datetime) -> DataStateChange:
        if self.data_state != DATA_INTERRUPTED:
            raise ValueError("data is not interrupted")
        return self._data(DATA_RESUMED, ts)

    def _data(self, state: str, ts: datetime) -> DataStateChange:
        if not isinstance(ts, datetime):                               # checked before any state change
            raise ValueError("data-state timestamp must be a datetime, got %r" % (ts,))
        last = self.candles[-1] if self.candles else None
        check_event_window(last, None, ts, self.timeframe, state)       # F-D2: not before the last candle's close
        if self.data_changes and ts < self.data_changes[-1].ts:       # OQ-3: recorded timestamps are chronological
            raise ValueError("%s at %s is earlier than the preceding %s at %s" % (
                state, ts.isoformat(), self.data_changes[-1].state, self.data_changes[-1].ts.isoformat()))
        ch = DataStateChange(state, ts, last.index if last else None)
        self.data_state = state
        self.data_changes.append(ch)
        return ch

    # ------------------------------------------------------------ helpers
    def setup(self, key: Tuple[str, str]) -> SetupRecord:
        return self.setups[self._spos[key]]

    def pattern_state(self, pattern_id: str) -> PatternState:
        return self.pattern_states[self._ppos[pattern_id]]

    def _set_setup(self, rec: SetupRecord) -> SetupRecord:
        self.setups[self._spos[rec.key]] = rec
        return rec

    def _set_pattern(self, ps: PatternState) -> PatternState:
        self.pattern_states[self._ppos[ps.pattern_id]] = ps
        return ps

    def _close_b(self, rec: SetupRecord, status: str, k: int, reason: str) -> None:
        """Mirror the terminal / CONFIRMED status into Module B's candidate (its documented API)."""
        cand = self.setup_stream.candidate(rec.key)
        if cand.status == B.PENDING:
            self.setup_stream.close_candidate(rec.key, status, k, reason)

    # ------------------------------------------------------------ stream
    def check_candle(self, c: Candle) -> None:
        """Every check on_candle makes before it changes anything (F-D1); Module E calls it first (F-E1). Pure."""
        if self.data_state == DATA_INTERRUPTED:
            raise ValueError("no candle can be processed while data is interrupted (CK-24: nothing is fabricated)")
        check_next_candle(self.candles[-1] if self.candles else None, c)
        if self.data_changes and self.data_changes[-1].ts > c.ts:     # F-D2: the event must precede this candle
            ch = self.data_changes[-1]
            raise ValueError("candle %d opens at %s, before the recorded %s at %s" % (
                c.index, c.ts.isoformat(), ch.state, ch.ts.isoformat()))

    def on_candle(self, c: Candle) -> list:
        self.check_candle(c)                                            # F-D1: validate before any mutation
        self.candles.append(c)
        self._data_at.append(self.data_state)
        k, ts = c.index, c.ts
        out: list = []
        # (1) Module B: structure first (MB-3 invalidation), then liquidity, then new candidates at k
        sev, _lev, new_cands = self.setup_stream.on_candle(c)
        for e in sev:
            if isinstance(e, CHoCHBreak):
                self._last_choch[e.direction] = (e.id, e.index)
        cur = self.setup_stream.current_bos_id
        if cur is not None and cur not in self._bos_choch:
            d = self.setup_stream.bos_states[cur].direction
            self._bos_choch[cur] = self._last_choch.get(d)
        for rec in list(self.setups):                                   # MB-3 / CK-18: structure invalidation by B
            cand = self.setup_stream.candidate(rec.key)
            if not rec.terminal and rec.status != CONFIRMED and cand.status == B.INVALIDATED and cand.closed_index == k:
                out.append(self._set_setup(_advance(rec, INVALIDATED, k, ts, cand.closed_by, "STRUCTURE_INVALIDATION",
                                                    self.data_state)))
        for cand in new_cands:                                          # MD-4: record created at the sweep
            out.append(self._new_setup(cand, c))
        # (2) Module C patterns ending at k
        pats = self.patterns_stream.on_candle(c)
        if self.cmp is None:                                           # CK-1: no tick size -> nothing scorable
            for cand in new_cands:
                self.diagnostics.append(QualificationDiagnostic(k, CONFIRMATION_UNSCORABLE, "", cand.key,
                                                                "tick size unavailable (CK-1)"))
            self.snapshots.append((tuple(self.setups), tuple(self.pattern_states)))
            return out
        # (3) tracked patterns: confirm / invalidate / expire, in MD-1 order
        confirmed_now: Dict[Tuple[str, str], List[PatternState]] = {}
        for ps in sorted((p for p in self.pattern_states if p.status == PATTERN_DETECTED_STATUS), key=lambda p: p.order):
            if not (ps.end_candle < k <= ps.end_candle + CONFIRMATION_WINDOW):
                continue
            bull = ps.bias == BULLISH_BIAS
            if (self.cmp.gt(c.close, ps.pattern_high) if bull else self.cmp.lt(c.close, ps.pattern_low)):   # CS-7 / CK-8
                ev = ConfirmationEvent(confirmation_id(ps.pattern_id, k), EventStamp(k, ts, k, ts), (ps.pattern_id,),
                                       pattern_id=ps.pattern_id, confirmation_candle=k, direction=BIAS_DIRECTION[ps.bias],
                                       timestamp=ts, close=c.close, level=ps.pattern_high if bull else ps.pattern_low)
                self.confirmations.append(ev)
                out.append(ev)
                out.append(self._set_pattern(replace(ps, status=PATTERN_CONFIRMED, closed_index=k, closed_ts=ts,
                                                     confirmation_id=ev.id)))
                confirmed_now.setdefault(ps.setup_key, []).append(self.pattern_state(ps.pattern_id))
            elif (self.cmp.lt(c.close, ps.pattern_low) if bull else self.cmp.gt(c.close, ps.pattern_high)):  # CK-12
                out.append(self._set_pattern(replace(ps, status=PATTERN_INVALIDATED, closed_index=k, closed_ts=ts)))
            elif k == ps.end_candle + CONFIRMATION_WINDOW:                                                   # 16.G
                out.append(self._set_pattern(replace(ps, status=PATTERN_EXPIRED, closed_index=k, closed_ts=ts)))
        # (4) setup confirmation: the first confirming pattern advances the setup (CK-11; MD-1 on a tie)
        for key, lst in confirmed_now.items():
            rec = self.setup(key)
            if rec.status != PATTERN_DETECTED:
                continue                                                # already CONFIRMED or terminal: no change
            win = min(lst, key=lambda p: p.order)
            sid = setup_id(rec.group_id, win.pattern_id)
            rec = self._set_setup(_advance(rec, CONFIRMED, k, ts, win.confirmation_id, None, self.data_state,
                                           setup_id=sid, confirmed_pattern_id=win.pattern_id,
                                           confirmation_id=win.confirmation_id))
            self._close_b(rec, B.CONFIRMED, k, win.confirmation_id)
            out.append(rec)
        # (5) new patterns ending at k: qualify against every setup whose sweep window contains them
        for p in pats:
            for rec in list(self.setups):
                if not (rec.sweep_index <= p.end_candle <= rec.window_end):
                    continue                                            # outside this sweep's window (CS-9)
                code = self._qualify(rec, p)
                if code is not None:
                    self.diagnostics.append(QualificationDiagnostic(k, code, p.id, rec.key))
                    continue
                self.patterns[p.id] = p
                self._ppos[p.id] = len(self.pattern_states)
                self.pattern_states.append(PatternState(p.id, rec.key, p.bias, p.start_candle, p.end_candle,
                                                        p.pattern_high, p.pattern_low, _mdl_order(p)))
                changes = dict(tracked=rec.tracked + (p.id,))
                if rec.status == SWEEP_DETECTED:
                    rec = _advance(rec, PATTERN_DETECTED, k, ts, p.id, None, self.data_state, **changes)
                else:
                    rec = replace(rec, **changes)
                out.append(self._set_setup(rec))
        # (6) resolution after the sweep window: CK-18 / MD-3
        for rec in list(self.setups):
            if rec.terminal or rec.status == CONFIRMED or k < rec.window_end:
                continue
            states = [self.pattern_state(pid) for pid in rec.tracked]
            if any(s.status == PATTERN_DETECTED_STATUS for s in states):
                continue                                                # a tracked pattern still has its window
            if not states:
                status, detail = EXPIRED, NO_QUALIFYING_PATTERN
            elif all(s.status == PATTERN_INVALIDATED for s in states):
                status, detail = INVALIDATED, ALL_PATTERNS_INVALIDATED
            elif all(s.status == PATTERN_EXPIRED for s in states):
                status, detail = EXPIRED, ALL_PATTERNS_EXPIRED
            else:
                status, detail = EXPIRED, MIXED_EXPIRED_INVALIDATED      # MD-3
            rec = self._set_setup(_advance(rec, status, k, ts, None, detail, self.data_state))
            self._close_b(rec, B.EXPIRED if status == EXPIRED else B.INVALIDATED, k, detail)
            out.append(rec)
        self.snapshots.append((tuple(self.setups), tuple(self.pattern_states)))
        return out

    def _qualify(self, rec: SetupRecord, p: PatternEvent) -> Optional[str]:
        if p.start_candle <= rec.sweep_index:
            return SWEEP_CANDLE_IN_PATTERN                              # CS-9 / CK-6
        if rec.terminal:
            return SETUP_ALREADY_TERMINAL
        if rec.status == CONFIRMED:
            return SETUP_ALREADY_CONFIRMED                              # CK-7 / CK-11
        if p.bias in (NEUTRAL, UNDETERMINED):
            return NON_DIRECTIONAL_BIAS                                 # CS-9
        if p.bias != REQUIRED_BIAS[rec.setup_side]:
            return BIAS_MISMATCH                                        # Section 3 / CK-7
        if p.pattern_label == UNCLASSIFIED_SHAPE:
            return CONTEXT_LABEL_MISSING                                # CK-4
        return None

    def _new_setup(self, cand: B.SweepCandidate, c: Candle) -> SetupRecord:
        ch = self._bos_choch.get(cand.bos_id)
        hist: List[Transition] = []
        if ch is not None:                                              # MD-4: original index / timestamp
            hist.append(Transition(CHOCH_DETECTED, ch[1], self.candles[ch[1]].ts, ch[0], None, self._data_at[ch[1]]))
        hist.append(Transition(BOS_CONFIRMED, cand.bos_index, self.candles[cand.bos_index].ts, cand.bos_id, None,
                               self._data_at[cand.bos_index]))
        hist.append(Transition(SWEEP_DETECTED, c.index, c.ts, cand.group_id, None, self.data_state))
        rec = SetupRecord(cand.bos_id, cand.group_id, cand.setup_side, cand.sweep_side, cand.index,
                          ch[0] if ch is not None else None, SWEEP_DETECTED, tuple(hist), data_state=self.data_state)
        if rec.key in self._spos:
            raise AssertionError("duplicate setup for %r" % (rec.key,))     # one setup per sweep group (CK-7)
        self._spos[rec.key] = len(self.setups)
        self.setups.append(rec)
        return rec


@dataclass
class ConfirmationReport:
    setups: List[SetupRecord]
    pattern_states: List[PatternState]
    confirmations: List[ConfirmationEvent]
    diagnostics: List[QualificationDiagnostic]
    data_changes: List[DataStateChange]
    snapshots: List[Tuple[Tuple[SetupRecord, ...], Tuple[PatternState, ...]]]
    outputs: List[Tuple[int, list]]


def validate_data_events(series: CandleSeries, data_events: Sequence[Tuple[int, str, datetime]],
                         timeframe: Optional[timedelta]) -> List[Tuple[int, str, datetime]]:
    """Pure check of batch data events (OQ-3); returns them in application order (before_index, then given order).
    Raises ValueError, without side effects, if any event:
      * is not a (before_index, state, ts) triple;
      * has a state other than DATA_INTERRUPTED / DATA_RESUMED (no other value is ever read as one of them);
      * has a before_index that is not an int in 0 .. len(series) - 1 (an event must precede a candle of the series;
        an event after the final candle could never be applied);
      * has a ts that is not a timezone-aware datetime, is earlier than the preceding data event, or lies outside
        its window [close of candle before_index - 1, open of candle before_index], both bounds inclusive (F-D2;
        check_event_window; the close is open + `timeframe`, which must be given when before_index > 0);
      * breaks the sequence (resume without interruption, interruption while interrupted), or leaves the data
        interrupted when its candle must be processed (no candle while interrupted, CK-24)."""
    n = len(series)
    out: List[Tuple[int, int, str, datetime]] = []
    for pos, e in enumerate(data_events):
        if not isinstance(e, (tuple, list)) or len(e) != 3:
            raise ValueError("data event %d must be (before_index, state, ts): %r" % (pos, e))
        idx, state, ts = e
        if state not in (DATA_INTERRUPTED, DATA_RESUMED):
            raise ValueError("data event %d: unknown data state %r (only %s / %s)" % (pos, state, DATA_INTERRUPTED,
                                                                                     DATA_RESUMED))
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise ValueError("data event %d: before_index must be an int, got %r" % (pos, idx))
        if not 0 <= idx < n:
            raise ValueError("data event %d: before_index %d outside the series (0 .. %d)" % (pos, idx, n - 1))
        if not isinstance(ts, datetime):
            raise ValueError("data event %d: ts must be a datetime, got %r" % (pos, ts))
        check_event_window(series[idx - 1] if idx > 0 else None, series[idx], ts, timeframe,
                           "data event %d (%s before candle %d)" % (pos, state, idx))
        out.append((idx, pos, state, ts))
    out.sort(key=lambda x: (x[0], x[1]))
    state_now, last_ts = NORMAL, None
    for k, (idx, pos, state, ts) in enumerate(out):
        if state == DATA_INTERRUPTED and state_now == DATA_INTERRUPTED:
            raise ValueError("data event %d: interruption while already interrupted" % pos)
        if state == DATA_RESUMED and state_now != DATA_INTERRUPTED:
            raise ValueError("data event %d: resume without a preceding interruption" % pos)
        if last_ts is not None and ts < last_ts:
            raise ValueError("data event %d: %s at %s is earlier than the preceding data event" % (pos, state, ts))
        state_now, last_ts = state, ts
        nxt = out[k + 1][0] if k + 1 < len(out) else None
        if state_now == DATA_INTERRUPTED and nxt != idx:
            raise ValueError("data event %d: data still interrupted when candle %d must be processed" % (pos, idx))
    return [(idx, state, ts) for idx, _, state, ts in out]


def analyze_confirmations(series: CandleSeries, instrument: str, timeframe: str, market: MarketDataConfig,
                          config: Optional[CandlestickConfig] = None,
                          data_events: Sequence[Tuple[int, str, datetime]] = ()) -> ConfirmationReport:
    """Batch form: exactly the stream. data_events = (before_index, DATA_INTERRUPTED | DATA_RESUMED, ts), applied
    before candle `before_index` is processed (in the given order). Every event is validated BEFORE any candle is
    processed (validate_data_events); an invalid event raises ValueError and nothing is built or recorded."""
    ev = validate_data_events(series, data_events, market.timeframe if market is not None else None)
    st = ConfirmationStream(instrument, timeframe, market, config)
    j, outputs = 0, []
    for c in series:
        while j < len(ev) and ev[j][0] == c.index:
            _, state, ts = ev[j]
            if state == DATA_INTERRUPTED:
                st.mark_data_interrupted(ts)
            elif state == DATA_RESUMED:
                st.mark_data_resumed(ts)
            else:                                                       # unreachable after validation
                raise ValueError("unknown data state %r" % (state,))
            j += 1
        outputs.append((c.index, st.on_candle(c)))
    if j != len(ev):                                                    # never silently discard an event
        raise ValueError("%d data event(s) were not applied: %r" % (len(ev) - j, ev[j:]))
    return ConfirmationReport(list(st.setups), list(st.pattern_states), list(st.confirmations), list(st.diagnostics),
                              list(st.data_changes), list(st.snapshots), outputs)


def detect_confirmations(series: CandleSeries, instrument: str, timeframe: str, market: MarketDataConfig,
                         config: Optional[CandlestickConfig] = None) -> List[ConfirmationEvent]:
    """Confirmation events only (for engine.no_lookahead_violations)."""
    return analyze_confirmations(series, instrument, timeframe, market, config).confirmations
