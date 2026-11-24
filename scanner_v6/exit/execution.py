"""Module E: confirmed-setup intake, PAPER entry, risk sizing, fixed SL / TP exits, daily-loss and position limits,
and the execution part of the setup lifecycle. PAPER ONLY: a simulated ledger in memory; nothing here places, routes or
prepares a real order, and nothing imports a broker, network or V4 module.

Built on Module D (ConfirmationStream: Modules A-D, unchanged). Module E owns a ConfirmationStream and reads its setups,
candles and the liquidity pool states; it never mutates a Module D record (it keeps its own TradeRecord).

Approved rules implemented (research/v6/specs/V6_TRADING_SPEC_v0.2.md):
  CK-10, MD-4      Module E performs CONFIRMED -> ENTERED / NO_TRADE / EXPIRED and ENTERED -> STOPPED_OUT /
                   TARGET_HIT; every transition records the zero-based candle index, timestamp and data_state; terminal
                   statuses never reactivate (LifecycleError). INVALIDATED stays with Module D: with NEXT_OPEN entry no
                   candle closes between confirmation and entry, so no structure event can invalidate a CONFIRMED setup.
  CK-25            end of data: an open position is reported OPEN_UNRESOLVED (finalize_end_of_data), never force-closed,
                   excluded from closed-trade results; the last available close is reported separately.
  Section 4, CK-19 entry at the open of C+1 (NEXT_OPEN); BUY fill = open + entry_ticks x T, SELL fill = open -
                   entry_ticks x T; no chasing, no delayed entry; actual entry fill used for sizing and R:R.
  OQ-1             max_adverse_gap = min(max_gap_ticks x T, 0.25 x planned_risk_distance); adverse gap from the
                   confirmation close (BUY open - close, SELL close - open); exceeded = strictly greater.
  Section 5, CK-20 / Section 6, CK-16, CK-21 / Section 9, 10, CK-22: see stop_loss.py, targets.py,
                   trade_management.py. Section 7, CK-14, CK-23: see sizing.py.
  CK-13            one final reason_code per rejected setup, from the six approved codes in their approved priority.
  OQ-2             operational dispositions in `disposition_reason` (never in reason_code): NO_ELIGIBLE_OPPOSING_POOL,
                   POSITION_LIMIT_REACHED, DAILY_LOSS_LIMIT_REACHED -> NO_TRADE; NEXT_CANDLE_UNAVAILABLE,
                   SESSION_CLOSED -> EXPIRED.
  OQ-3, CK-24      data_state is a flag (NORMAL / DATA_INTERRUPTED / DATA_RESUMED), never a status; no candle, fill or
                   exit is fabricated; a pending setup that misses its next-open deadline -> EXPIRED
                   NEXT_CANDLE_UNAVAILABLE; an open position keeps its status, its data gaps are recorded, and exits
                   are only taken from observed candles after the resumption.
  OQ-6, CK-23      one open position; 1% risk of current MTM equity; daily loss = start-of-day equity - current MTM
                   equity; at >= 2% new setups are rejected for the rest of that trading day; open positions keep their
                   fixed SL / TP; no forced close. Costs already in cash or fills are never deducted twice.
  OQ-7             confirmation candle and entry candle in the same continuous session; a confirmation on a session's
                   final candle expires (SESSION_CLOSED); a CONTINUOUS calendar must be configured explicitly.

Owner decisions ME-1...ME-4 (24 Nov 2026, conversation level; spec 17.V):
  ME-1  outcome precedence (fills OQ-10 for Module E): the first applicable of EXECUTION_CONFIG_INCOMPLETE,
        POSITION_LIMIT_REACHED, DAILY_LOSS_LIMIT_REACHED, SESSION_CLOSED, NEXT_CANDLE_UNAVAILABLE,
        NO_ELIGIBLE_OPPOSING_POOL, then CK-13 #2...#6 in their approved order.
  ME-2  CONTINUOUS calendars: explicit `trading_day_start` (missing -> EXECUTION_CONFIG_INCOMPLETE).
  ME-3  margin = entry_fill x q x M x initial_margin_rate against current paper equity.
  ME-4  any data interruption between C's close and C+1's open -> EXPIRED NEXT_CANDLE_UNAVAILABLE.

OQ-13 (OWNER APPROVED 24 Nov 2026) mark-to-market convention:
  mark            = the latest COMPLETED candle close (never a forming or future candle); at a trading-day start, the
                    latest completed close immediately before the boundary (a candle ending at or before it).
  estimated exit  = LONG mark - mtm_exit_slippage_ticks x T, SHORT mark + mtm_exit_slippage_ticks x T (slippage is in
                    the estimated fill and is not deducted again).
  estimated fee   = the configured fee schedule on the estimated exit fill notional, deducted exactly once; entry costs
                    already in cash / the entry fill are not counted again.
  unrealized      = LONG (est_exit - entry_fill) x q x M, SHORT (entry_fill - est_exit) x q x M.
  MTM equity      = cash + unrealized - estimated exit fee  (flat: cash).
  Missing mark, tick size, slippage or fee configuration -> MTM UNSCORABLE; a daily-loss check that needs it is
  UNSCORABLE and new entries are suspended (result UNSCORABLE, blocked_by OQ-13: no entry, no lifecycle step, never
  entered later). Open positions keep their lifecycle and fixed SL / TP. Nothing is fabricated.
Daily loss is measured at every completed candle close (the only times a mark exists) and at each entry decision; a
measure >= 2% of start-of-day equity latches the rest of that trading day. If the day boundary falls inside a candle
in which the position was exited, its state at the boundary is intrabar-ambiguous -> start-of-day UNSCORABLE.

Implementation choices (ordering / representation only; listed in 17.V): staged evaluation (phase 1 at the close of
C: configuration, position limit, daily loss, session; phase 2 at the open of C+1: position limit again for a second
setup pending on the same candle, next candle, target pool, CK-13 #2...#6); order at each candle: (A) entries of
pending setups at the open, (B) exit of the open position on this candle (STOP_FIRST, entry candle included),
(C) Module D processes the candle, (M) MTM / daily-loss measurement at this close, (D) new CONFIRMED setups
(phase 1); trading day: CONTINUOUS from
trading_day_start, EXCHANGE from the first configured session opening on that local date; the snapshot is taken at
the day start before any fill at that instant. TradeRecords are keyed by the CK-2 setup_id; no new id format.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ..data.candle_models import Candle, CandleSeries
from ..data.market_config import MarketDataConfig, SessionKind
from ..entry import confirmation as D
from ..entry.candlesticks import CandlestickConfig
from ..models import Event, EventStamp
from .execution_config import ExecutionConfig, dec
from .sizing import RISK_FRACTION, Costs, largest_quantity, margin_quantity, required_margin
from .stop_loss import BUY, SELL, stop_fill, structural_sl, to_grid
from .targets import PoolView, select_target_pool, target_price, tie_info
from .trade_management import evaluate_exit

# ---------------------------------------------------------------- statuses (CK-10, CK-25)
CONFIRMED, ENTERED, STOPPED_OUT, TARGET_HIT = D.CONFIRMED, D.ENTERED, D.STOPPED_OUT, D.TARGET_HIT
NO_TRADE, EXPIRED, INVALIDATED = D.NO_TRADE, D.EXPIRED, D.INVALIDATED
OPEN_UNRESOLVED = "OPEN_UNRESOLVED"
E_TRANSITIONS = {CONFIRMED: (ENTERED, NO_TRADE, EXPIRED), ENTERED: (STOPPED_OUT, TARGET_HIT)}
E_TERMINAL = (NO_TRADE, EXPIRED, STOPPED_OUT, TARGET_HIT)
UNSCORABLE = "UNSCORABLE"                                 # Section 13 item result: pending rule

# ---------------------------------------------------------------- CK-13 reason codes, approved priority
EXECUTION_CONFIG_INCOMPLETE = "EXECUTION_CONFIG_INCOMPLETE"
ENTRY_AT_OR_BEYOND_SL = "ENTRY_AT_OR_BEYOND_SL"
ENTRY_GAP_EXCEEDED = "ENTRY_GAP_EXCEEDED"
NET_RR_BELOW_MINIMUM = "NET_RR_BELOW_MINIMUM"
MIN_QTY_EXCEEDS_RISK_BUDGET = "MIN_QTY_EXCEEDS_RISK_BUDGET"
INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
CK13_PRIORITY = (EXECUTION_CONFIG_INCOMPLETE, ENTRY_AT_OR_BEYOND_SL, ENTRY_GAP_EXCEEDED, NET_RR_BELOW_MINIMUM,
                 MIN_QTY_EXCEEDS_RISK_BUDGET, INSUFFICIENT_MARGIN)

# ---------------------------------------------------------------- OQ-2 dispositions -> lifecycle status
NO_ELIGIBLE_OPPOSING_POOL = "NO_ELIGIBLE_OPPOSING_POOL"
POSITION_LIMIT_REACHED = "POSITION_LIMIT_REACHED"
DAILY_LOSS_LIMIT_REACHED = "DAILY_LOSS_LIMIT_REACHED"
NEXT_CANDLE_UNAVAILABLE = "NEXT_CANDLE_UNAVAILABLE"
SESSION_CLOSED = "SESSION_CLOSED"
DISPOSITION_STATUS = {NO_ELIGIBLE_OPPOSING_POOL: NO_TRADE, POSITION_LIMIT_REACHED: NO_TRADE,
                      DAILY_LOSS_LIMIT_REACHED: NO_TRADE, NEXT_CANDLE_UNAVAILABLE: EXPIRED, SESSION_CLOSED: EXPIRED}

# ME-1 (owner decision 24 Nov 2026): the full precedence; CK-13's own relative order is unchanged inside it
ME1_ORDER = (EXECUTION_CONFIG_INCOMPLETE, POSITION_LIMIT_REACHED, DAILY_LOSS_LIMIT_REACHED, SESSION_CLOSED,
             NEXT_CANDLE_UNAVAILABLE, NO_ELIGIBLE_OPPOSING_POOL, ENTRY_AT_OR_BEYOND_SL, ENTRY_GAP_EXCEEDED,
             NET_RR_BELOW_MINIMUM, MIN_QTY_EXCEEDS_RISK_BUDGET, INSUFFICIENT_MARGIN)

# ---------------------------------------------------------------- approved operating values (not configuration)
GAP_RISK_FRACTION = Decimal("0.25")       # CK-19 / OQ-1
DAILY_LOSS_FRACTION = Decimal("0.02")     # CK-23 / OQ-6
MAX_OPEN_POSITIONS = 1                    # CK-23

# ---------------------------------------------------------------- intake diagnostics
INTAKE_NOT_CONFIRMED = "INTAKE_NOT_CONFIRMED"
INTAKE_MISSING_SETUP_ID = "INTAKE_MISSING_SETUP_ID"
INTAKE_DUPLICATE_SETUP = "INTAKE_DUPLICATE_SETUP"
INTAKE_CONFIRMATION_NOT_CURRENT = "INTAKE_CONFIRMATION_NOT_CURRENT"

OQ13 = "OQ-13"
UTC = timezone.utc


class LifecycleError(D.LifecycleError):
    pass


@dataclass(frozen=True)
class TradeRecord:
    """Module E view of one CONFIRMED setup. `history` = Module D's history (CHOCH_DETECTED ... CONFIRMED, original
    indices and timestamps) followed by Module E transitions. Prices / money are exact Decimals."""
    setup_id: str
    setup_key: Tuple[str, str]
    side: str
    group_id: str
    pattern_id: str
    confirmation_id: str
    sweep_index: int
    confirmation_index: int
    status: str
    history: Tuple[D.Transition, ...]
    reason_code: Optional[str] = None             # CK-13 only
    disposition_reason: Optional[str] = None      # OQ-2 only
    result: Optional[str] = None                  # ENTERED / NO_TRADE / EXPIRED / UNSCORABLE / STOPPED_OUT / TARGET_HIT
    blocked_by: Tuple[str, ...] = ()
    detail: Optional[str] = None
    data_state: str = D.NORMAL
    data_gaps: Tuple[Tuple[str, datetime], ...] = ()
    # plan (known at the close of C)
    sl: Optional[Decimal] = None
    confirmation_close: Optional[Decimal] = None
    planned_risk_distance: Optional[Decimal] = None
    max_adverse_gap: Optional[Decimal] = None
    expected_entry_ts: Optional[datetime] = None
    # entry decision (open of C+1)
    entry_index: Optional[int] = None
    entry_open: Optional[Decimal] = None
    adverse_gap: Optional[Decimal] = None
    entry_fill: Optional[Decimal] = None
    planned_stop_fill: Optional[Decimal] = None
    tp_pool_id: Optional[str] = None
    tp_pool_price: Optional[Decimal] = None
    tp_tied_pools: Tuple[str, ...] = ()
    tp: Optional[Decimal] = None
    equity_at_decision: Optional[Decimal] = None
    risk_budget: Optional[Decimal] = None
    risk_quantity: Optional[Decimal] = None
    quantity: Optional[Decimal] = None
    loss_estimate: Optional[Decimal] = None
    net_rr: Optional[Decimal] = None
    required_margin: Optional[Decimal] = None
    entry_fee: Optional[Decimal] = None
    # exit
    exit_index: Optional[int] = None
    exit_fill: Optional[Decimal] = None
    exit_gap: Optional[bool] = None
    exit_fee: Optional[Decimal] = None
    gross_pnl: Optional[Decimal] = None
    realized_pnl: Optional[Decimal] = None
    diagnostics: Tuple[str, ...] = ()

    @property
    def terminal(self) -> bool:
        return self.status in E_TERMINAL


@dataclass(frozen=True)
class IntakeDiagnostic:
    index: int
    code: str
    setup_key: Tuple[str, str]
    setup_id: Optional[str]


@dataclass(frozen=True)
class EndOfData:
    """CK-25: open positions are OPEN_UNRESOLVED (copies; the stream is not changed), the last available close is
    reported separately, and closed-trade figures exclude them."""
    last_index: Optional[int]
    last_ts: Optional[datetime]
    last_close: Optional[Decimal]
    open_unresolved: Tuple[TradeRecord, ...]
    awaiting_next_candle: Tuple[str, ...]
    closed_trades: int
    target_hits: int
    stopped_out: int
    realized_pnl: Decimal
    cash: Decimal


def _advance(rec: TradeRecord, status: str, k: int, ts: datetime, cause: Optional[str], detail: Optional[str],
             data_state: str, **changes) -> TradeRecord:
    if rec.terminal:
        raise LifecycleError("setup %s is terminal (%s) and cannot reactivate" % (rec.setup_id, rec.status))
    if status not in E_TRANSITIONS.get(rec.status, ()):
        raise LifecycleError("transition %s -> %s is not permitted in Module E" % (rec.status, status))
    if k < rec.history[-1].index:
        raise LifecycleError("transition at %d is before the previous one at %d" % (k, rec.history[-1].index))
    return replace(rec, status=status, history=rec.history + (D.Transition(status, k, ts, cause, detail, data_state),),
                   detail=detail if detail is not None else rec.detail, data_state=data_state, **changes)


@dataclass
class _Account:
    cash: Decimal
    position: Optional[str] = None
    cash_events: List[Tuple[datetime, bool, Decimal]] = field(default_factory=list)   # (time, is_entry, delta)
    intervals: List[list] = field(default_factory=list)                              # [entry ts, end ts or None, setup id]
    latched_days: Dict[str, int] = field(default_factory=dict)                       # day key -> index latched
    unscorable_days: Dict[str, Tuple[int, str]] = field(default_factory=dict)        # day key -> (index, reason)
    sod: Dict[str, Tuple[str, Optional[Decimal], Optional[str]]] = field(default_factory=dict)   # day -> snapshot


class ExecutionStream:
    """Feed completed candles in order (and data-state changes between them). on_candle(c) returns the TradeRecords
    that changed at c, in order. Uses only candles 0..c.index; analyze_execution is exactly this stream."""

    def __init__(self, instrument: str, timeframe: str, market: MarketDataConfig, config: ExecutionConfig,
                 candlestick_config: Optional[CandlestickConfig] = None):
        if not isinstance(config, ExecutionConfig):
            raise TypeError("config must be an ExecutionConfig")
        self.market, self.cfg = market, config
        self.d = D.ConfirmationStream(instrument, timeframe, market, candlestick_config)
        self.candles: List[Candle] = []
        self.records: List[TradeRecord] = []
        self._pos: Dict[str, int] = {}
        self.pending: List[str] = []                       # setup ids awaiting the open of C+1
        self.intake_diagnostics: List[IntakeDiagnostic] = []
        self.missing = config.missing(market)
        self.account = _Account(cash=config.starting_equity if config.starting_equity is not None else Decimal(0))
        self.snapshots: List[tuple] = []
        self.mtm_log: List[Tuple[int, str, Optional[Decimal], Optional[str], Optional[Decimal], Optional[str]]] = []

    # ------------------------------------------------------------ helpers
    @property
    def tick(self) -> Decimal:
        return dec(self.market.tick_size, "tick_size")

    def record(self, setup_id: str) -> TradeRecord:
        return self.records[self._pos[setup_id]]

    def _set(self, rec: TradeRecord) -> TradeRecord:
        self.records[self._pos[rec.setup_id]] = rec
        return rec

    # ------------------------------------------------------------ OQ-13 mark-to-market
    def estimate_exit(self, rec: TradeRecord, mark: Optional[Decimal]) -> Tuple[str, Optional[tuple], Optional[str]]:
        """(OK, (mark, est_exit_fill, unrealized, est_exit_fee), None) or (UNSCORABLE, None, reason) for an open
        position at `mark` (OQ-13). Nothing is defaulted."""
        cfg = self.cfg
        miss = [n for n, v in (("mark", mark), ("tick_size", self.market.tick_size),
                               ("mtm_exit_slippage_ticks", cfg.mtm_exit_slippage_ticks),
                               ("fee_schedule", cfg.fee_schedule), ("price_rounding_mode", cfg.price_rounding_mode),
                               ("contract_multiplier", cfg.contract_multiplier)) if v is None]
        if miss:
            return UNSCORABLE, None, "MTM needs " + ",".join(miss)
        T, slip = self.tick, cfg.mtm_exit_slippage_ticks
        est = to_grid(mark - slip * T if rec.side == BUY else mark + slip * T, T, cfg.price_rounding_mode)
        M, q = cfg.contract_multiplier, rec.quantity
        unreal = (est - rec.entry_fill if rec.side == BUY else rec.entry_fill - est) * q * M
        return "OK", (mark, est, unreal, cfg.fee_schedule.fee(est, q, M)), None

    def _equity(self, cash: Decimal, open_ids: Sequence[str], mark: Optional[Decimal]) -> Tuple[str, Optional[Decimal], Optional[str]]:
        eq = cash
        for sid in open_ids:
            st, est, why = self.estimate_exit(self.record(sid), mark)
            if st != "OK":
                return UNSCORABLE, None, why
            eq += est[2] - est[3]
        return "OK", eq, None

    def mtm_equity(self) -> Tuple[str, Optional[Decimal]]:
        """OQ-6 / OQ-13 MTM equity now: cash while flat; with an open position, marked at the latest completed close."""
        mark = dec(self.candles[-1].close) if self.candles else None
        st, eq, _ = self._equity(self.account.cash, [self.account.position] if self.account.position else [], mark)
        return st, eq

    # ------------------------------------------------------------ data state (OQ-3, ME-4)
    def mark_data_interrupted(self, ts: datetime) -> list:
        ch = self.d.mark_data_interrupted(ts)            # Module D validates the chronology first
        out = []
        k = self.candles[-1].index if self.candles else 0
        for sid in list(self.pending):                   # ME-4: the next-open deadline is missed
            rec = self.record(sid)
            out.append(self._set(_advance(rec, EXPIRED, k, ch.ts, None, NEXT_CANDLE_UNAVAILABLE, D.DATA_INTERRUPTED,
                                          disposition_reason=NEXT_CANDLE_UNAVAILABLE, result=EXPIRED)))
            self.pending.remove(sid)
        if self.account.position is not None:            # open trade keeps its status; the gap is recorded
            rec = self.record(self.account.position)
            out.append(self._set(replace(rec, data_state=D.DATA_INTERRUPTED,
                                         data_gaps=rec.data_gaps + ((D.DATA_INTERRUPTED, ch.ts),))))
        return out

    def mark_data_resumed(self, ts: datetime) -> list:
        ch = self.d.mark_data_resumed(ts)
        out = []
        if self.account.position is not None:
            rec = self.record(self.account.position)
            out.append(self._set(replace(rec, data_state=D.DATA_RESUMED,
                                         data_gaps=rec.data_gaps + ((D.DATA_RESUMED, ch.ts),))))
        return out

    # ------------------------------------------------------------ sessions and trading days (OQ-6, OQ-7, ME-2)
    def _day(self, t: datetime) -> Optional[Tuple[str, datetime]]:
        cal = self.market.session
        tz = ZoneInfo(cal.timezone)
        if cal.kind is SessionKind.CONTINUOUS:
            loc = t.astimezone(tz)
            start = datetime.combine(loc.date(), self.cfg.trading_day_start, tzinfo=tz)
            if loc < start:
                start = datetime.combine(loc.date() - timedelta(days=1), self.cfg.trading_day_start, tzinfo=tz)
            return start.date().isoformat(), start.astimezone(UTC)
        opens = [o for o, _ in cal.sessions]
        j = bisect.bisect_right(opens, t) - 1
        if j < 0:
            return None
        day = opens[j].astimezone(tz).date()
        while j > 0 and opens[j - 1].astimezone(tz).date() == day:
            j -= 1
        return day.isoformat(), opens[j]

    def _session_ok(self, t_conf: datetime, t_next: datetime, tf: timedelta) -> bool:
        cal = self.market.session
        if cal.kind is SessionKind.CONTINUOUS:
            return True
        j = cal.session_index(t_conf)
        return j is not None and cal.session_index(t_next) == j and t_next + tf <= cal.sessions[j][1]

    def _cash_at(self, t: datetime) -> Decimal:
        c = self.cfg.starting_equity
        for when, is_entry, delta in self.account.cash_events:
            if (when < t) if is_entry else (when <= t):
                c += delta
        return c

    def _sod(self, key: str, start: datetime) -> Tuple[str, Optional[Decimal], Optional[str]]:
        """Start-of-day equity at `start` (OQ-6 / OQ-13), cached per trading day. Positions open at the boundary are
        marked at the latest completed close at or before it."""
        if key in self.account.sod:
            return self.account.sod[key]
        tf = self.market.timeframe
        open_ids, res = [], None
        for e, end, sid in self.account.intervals:
            if e < start and (end is None or end > start):
                if end is not None and end - tf < start:            # exited inside the candle spanning the boundary
                    res = (UNSCORABLE, None, "day boundary %s inside the exit candle of %s (intrabar)" % (start.isoformat(), sid))
                    break
                open_ids.append(sid)
        if res is None:
            mark = None
            if open_ids:
                done = [c for c in self.candles if c.ts + tf <= start]
                mark = dec(done[-1].close) if done else None
            res = self._equity(self._cash_at(start), open_ids, mark)
        self.account.sod[key] = res
        return res

    def _measure(self, key: str, start: datetime, k: int, eq_status: str, eq: Optional[Decimal],
                 why: Optional[str]) -> Tuple[str, Optional[str]]:
        """One daily-loss measurement; latches at >= 2% of start-of-day equity."""
        if key in self.account.latched_days:
            return "REACHED", "latched at %d" % self.account.latched_days[key]
        s_st, sod, s_why = self._sod(key, start)
        if s_st != "OK":
            self.account.unscorable_days.setdefault(key, (k, s_why))
            return UNSCORABLE, s_why
        if eq_status != "OK":
            self.account.unscorable_days.setdefault(key, (k, why))
            return UNSCORABLE, why
        loss = sod - eq
        if loss >= DAILY_LOSS_FRACTION * sod:
            self.account.latched_days[key] = k
            return "REACHED", "daily loss %s >= 2%% of start-of-day equity %s" % (loss, sod)
        if key in self.account.unscorable_days:
            return UNSCORABLE, "an earlier measurement on %s was UNSCORABLE: %s" % (key, self.account.unscorable_days[key][1])
        return "OK", None

    def _measure_close(self, c: Candle) -> None:
        """(M) MTM and daily loss at this completed close (OQ-6 / OQ-13)."""
        if self.missing:                    # no entry is possible (EXECUTION_CONFIG_INCOMPLETE); nothing to measure
            return
        tf = self.market.timeframe
        day = self._day(c.ts + tf)
        if day is None:
            return
        pos = self.account.position
        st, eq, why = self._equity(self.account.cash, [pos] if pos else [], dec(c.close))
        res, _ = self._measure(day[0], day[1], c.index, st, eq, why)
        self.mtm_log.append((c.index, st, eq, day[0], None if self.account.sod[day[0]][1] is None or eq is None
                             else self.account.sod[day[0]][1] - eq, res))

    def _daily_loss(self, t_entry: datetime, k: int) -> Tuple[str, Optional[str]]:
        """('OK'|'REACHED'|UNSCORABLE, detail) for the trading day of t_entry; the account is flat here (the position
        limit is checked first, ME-1), so current MTM equity = cash."""
        key, start = self._day(t_entry)
        return self._measure(key, start, k, "OK", self.account.cash, None)

    # ------------------------------------------------------------ intake (A)
    def intake(self, rec: D.SetupRecord, k: int) -> Optional[TradeRecord]:
        code = None
        if rec.status != CONFIRMED:
            code = INTAKE_NOT_CONFIRMED
        elif not rec.setup_id or not rec.confirmed_pattern_id or not rec.confirmation_id:
            code = INTAKE_MISSING_SETUP_ID
        elif rec.setup_id in self._pos:
            code = INTAKE_DUPLICATE_SETUP
        elif rec.history[-1].status != CONFIRMED or rec.history[-1].index != k:
            code = INTAKE_CONFIRMATION_NOT_CURRENT
        if code is not None:
            self.intake_diagnostics.append(IntakeDiagnostic(k, code, rec.key, rec.setup_id))
            return None
        tr = TradeRecord(rec.setup_id, rec.key, rec.setup_side, rec.group_id, rec.confirmed_pattern_id,
                         rec.confirmation_id, rec.sweep_index, k, CONFIRMED, rec.history, data_state=rec.data_state)
        self._pos[tr.setup_id] = len(self.records)
        self.records.append(tr)
        return tr

    # ------------------------------------------------------------ phase 1 at the close of C (D)
    def _reject(self, rec: TradeRecord, outcome: str, k: int, ts: datetime, detail: Optional[str] = None,
                **changes) -> TradeRecord:
        if outcome in CK13_PRIORITY:
            st, kw = NO_TRADE, dict(reason_code=outcome)
        else:
            st, kw = DISPOSITION_STATUS[outcome], dict(disposition_reason=outcome)
        kw.update(changes)
        return self._set(_advance(rec, st, k, ts, None, detail or outcome, self.d.data_state, result=st, **kw))

    def _phase1(self, rec: TradeRecord, c: Candle) -> TradeRecord:
        k, ts = c.index, c.ts
        if self.missing:                                                            # CK-13 #1 / CK-26
            return self._reject(rec, EXECUTION_CONFIG_INCOMPLETE, k, ts, "missing: " + ",".join(self.missing))
        tf = self.market.timeframe
        t_next = ts + tf
        if self._day(t_next) is None:                                               # calendar does not cover t_next
            return self._reject(rec, EXECUTION_CONFIG_INCOMPLETE, k, ts, "missing: session_calendar_coverage")
        if self.account.position is not None:                                       # CK-23 / OQ-2 (ME-1 #2)
            return self._reject(rec, POSITION_LIMIT_REACHED, k, ts, "open position %s" % self.account.position)
        dl, why = self._daily_loss(t_next, k)                                       # OQ-6 (ME-1 #3)
        if dl == "REACHED":
            return self._reject(rec, DAILY_LOSS_LIMIT_REACHED, k, ts, why)
        if dl == UNSCORABLE:
            return self._set(replace(rec, result=UNSCORABLE, blocked_by=(OQ13,), detail=why))   # entries suspended
        if not self._session_ok(ts, t_next, tf):                                    # OQ-7 (ME-1 #4)
            return self._reject(rec, SESSION_CLOSED, k, ts)
        T, cfg = self.tick, self.cfg
        sw = self.candles[rec.sweep_index]
        sl = structural_sl(rec.side, dec(sw.low), dec(sw.high), cfg.sl_buffer_ticks, T, cfg.price_rounding_mode)
        cc = dec(c.close)
        prd = abs(cc - sl)
        rec = self._set(replace(rec, sl=sl, confirmation_close=cc, planned_risk_distance=prd,
                                max_adverse_gap=min(cfg.max_gap_ticks * T, GAP_RISK_FRACTION * prd),
                                expected_entry_ts=t_next))
        self.pending.append(rec.setup_id)
        return rec

    # ------------------------------------------------------------ phase 2 at the open of C+1 (A)
    def _pools(self) -> List[PoolView]:
        lq = self.d.setup_stream.liquidity
        return [PoolView(p.id, "BSL" if p.side.value == "above" else "SSL", dec(p.price), p.stamp.confirmed_index,
                         lq.state[p.id]) for p in lq.pools]

    def _phase2(self, sid: str, c: Candle) -> TradeRecord:
        rec = self.record(sid)
        k, ts, cfg, T, mode = c.index, c.ts, self.cfg, self.tick, self.cfg.price_rounding_mode
        if self.account.position is not None:                                       # second setup on the same open
            return self._reject(rec, POSITION_LIMIT_REACHED, k, ts, "open position %s" % self.account.position)
        if c.index != rec.confirmation_index + 1 or c.ts != rec.expected_entry_ts:   # CK-19 / OQ-2
            return self._reject(rec, NEXT_CANDLE_UNAVAILABLE, k, ts,
                                "expected %s, got %s" % (rec.expected_entry_ts.isoformat(), ts.isoformat()))
        side, o = rec.side, dec(c.open)
        fill = to_grid(o + cfg.entry_ticks * T if side == BUY else o - cfg.entry_ticks * T, T, mode)
        pools = self._pools()
        pool = select_target_pool(side, fill, pools)
        sfill = stop_fill(side, rec.sl, cfg.stop_exit_ticks, T, mode)
        gap = o - rec.confirmation_close if side == BUY else rec.confirmation_close - o
        base = dict(entry_index=k, entry_open=o, entry_fill=fill, adverse_gap=gap, planned_stop_fill=sfill)
        if pool is None:                                                            # CK-16 / OQ-2 (ME-1 #6)
            return self._reject(rec, NO_ELIGIBLE_OPPOSING_POOL, k, ts, **base)
        tp = target_price(side, pool.price, cfg.tp_offset_ticks, T, mode)
        base.update(tp_pool_id=pool.pool_id, tp_pool_price=pool.price, tp=tp, tp_tied_pools=tie_info(side, fill, pools))
        if (o <= rec.sl) if side == BUY else (o >= rec.sl):                         # CK-13 #2
            return self._reject(rec, ENTRY_AT_OR_BEYOND_SL, k, ts, **base)
        if gap > rec.max_adverse_gap:                                               # CK-13 #3 (OQ-1)
            return self._reject(rec, ENTRY_GAP_EXCEEDED, k, ts, **base)
        costs = Costs(side, fill, sfill, tp, cfg.contract_multiplier, cfg.fee_schedule)
        equity = self.account.cash                                                  # flat: MTM = cash (OQ-6)
        budget = RISK_FRACTION * equity
        q_risk = largest_quantity(costs, budget, cfg.quantity_step, cfg.min_quantity)
        q_rr = q_risk if q_risk is not None else cfg.min_quantity
        base.update(equity_at_decision=equity, risk_budget=budget, risk_quantity=q_risk, net_rr=costs.net_rr(q_rr))
        if not costs.rr_ok(q_rr):                                                   # CK-13 #4
            return self._reject(rec, NET_RR_BELOW_MINIMUM, k, ts, **base)
        if q_risk is None:                                                          # CK-13 #5
            return self._reject(rec, MIN_QTY_EXCEEDS_RISK_BUDGET, k, ts, loss_estimate=costs.loss(cfg.min_quantity), **base)
        diags: Tuple[str, ...] = ()
        q = q_risk
        if required_margin(fill, q, cfg.contract_multiplier, cfg.initial_margin_rate) > equity:   # CK-14 (ME-3)
            q = margin_quantity(costs, q_risk, cfg.quantity_step, cfg.min_quantity, cfg.initial_margin_rate, equity)
            if q is None:                                                           # CK-13 #6
                return self._reject(rec, INSUFFICIENT_MARGIN, k, ts, **base)
            diags = ("QUANTITY_REDUCED_FOR_MARGIN",)
        if fill < dec(c.low) or fill > dec(c.high):
            diags += ("FILL_OUTSIDE_CANDLE_RANGE",)
        fee = cfg.fee_schedule.fee(fill, q, cfg.contract_multiplier)
        base.update(quantity=q, loss_estimate=costs.loss(q), net_rr=costs.net_rr(q), entry_fee=fee,
                    required_margin=required_margin(fill, q, cfg.contract_multiplier, cfg.initial_margin_rate),
                    diagnostics=rec.diagnostics + diags)
        self.account.cash -= fee                                                    # entry cost enters cash once
        self.account.cash_events.append((ts, True, -fee))
        self.account.intervals.append([ts, None, sid])
        self.account.position = sid
        return self._set(_advance(rec, ENTERED, k, ts, rec.confirmation_id, None, self.d.data_state, result=ENTERED,
                                  **base))

    # ------------------------------------------------------------ exits (B)
    def _exit(self, c: Candle) -> Optional[TradeRecord]:
        sid = self.account.position
        rec = self.record(sid)
        cfg = self.cfg
        ex = evaluate_exit(rec.side, dec(c.open), dec(c.high), dec(c.low), rec.sl, rec.tp, cfg.stop_exit_ticks, self.tick,
                           cfg.price_rounding_mode, entry_candle=(c.index == rec.entry_index))
        if ex is None:
            return None
        M, q = cfg.contract_multiplier, rec.quantity
        fee = cfg.fee_schedule.fee(ex.fill, q, M)
        gross = (ex.fill - rec.entry_fill if rec.side == BUY else rec.entry_fill - ex.fill) * q * M
        self.account.cash += gross - fee                                            # exit cost enters cash once
        end = c.ts + self.market.timeframe
        self.account.cash_events.append((end, False, gross - fee))
        self.account.intervals[-1][1] = end
        self.account.position = None
        return self._set(_advance(rec, ex.status, c.index, c.ts, None, None, self.d.data_state, result=ex.status,
                                  exit_index=c.index, exit_fill=ex.fill, exit_gap=ex.gap, exit_fee=fee, gross_pnl=gross,
                                  realized_pnl=gross - rec.entry_fee - fee, diagnostics=rec.diagnostics + ex.diagnostics))

    # ------------------------------------------------------------ main loop
    def on_candle(self, c: Candle) -> list:
        self.d.check_candle(c)              # F-E1: the whole candle is validated (Module D's rules) before (A)-(D)
        out: list = []
        for sid in list(self.pending):                                              # (A) entries at the open
            self.pending.remove(sid)
            out.append(self._phase2(sid, c))
        if self.account.position is not None:                                       # (B) exit on this candle
            r = self._exit(c)
            if r is not None:
                out.append(r)
        self.d.on_candle(c)                                                         # (C) Modules A-D
        self.candles.append(c)
        self._measure_close(c)                                                      # (M) OQ-6 / OQ-13
        for rec in self.d.setups:                                                   # (D) phase 1 for new CONFIRMED
            if rec.status == CONFIRMED and rec.history[-1].index == c.index and rec.setup_id not in self._pos:
                tr = self.intake(rec, c.index)
                if tr is not None:
                    out.append(self._phase1(tr, c))
        self.snapshots.append((tuple(self.records), self.account.cash, self.account.position, tuple(self.pending),
                               tuple(sorted(self.account.latched_days.items())),
                               tuple(sorted(self.account.unscorable_days.items())),
                               self.mtm_log[-1] if self.mtm_log else None))
        return out

    def finalize_end_of_data(self) -> EndOfData:
        last = self.candles[-1] if self.candles else None
        unresolved = []
        if self.account.position is not None and last is not None:
            rec = self.record(self.account.position)
            unresolved.append(replace(rec, status=OPEN_UNRESOLVED, result=OPEN_UNRESOLVED,
                                      history=rec.history + (D.Transition(OPEN_UNRESOLVED, last.index, last.ts, None,
                                                                          "END_OF_DATA", self.d.data_state),)))
        closed = [r for r in self.records if r.status in (STOPPED_OUT, TARGET_HIT)]
        return EndOfData(last.index if last else None, last.ts if last else None, dec(last.close) if last else None,
                         tuple(unresolved), tuple(self.pending), len(closed),
                         sum(r.status == TARGET_HIT for r in closed), sum(r.status == STOPPED_OUT for r in closed),
                         sum((r.realized_pnl for r in closed), Decimal(0)), self.account.cash)


@dataclass(frozen=True)
class ExecutionEvent(Event):
    """Audit-only event per Module E transition (for engine.no_lookahead_violations); its id is a traceability key,
    not a CK-2 identifier."""
    status: str = ""


@dataclass
class ExecutionReport:
    records: List[TradeRecord]
    intake_diagnostics: List[IntakeDiagnostic]
    snapshots: List[tuple]
    outputs: List[Tuple[int, list]]
    end_of_data: EndOfData
    setups: List[D.SetupRecord]


def analyze_execution(series: CandleSeries, instrument: str, timeframe: str, market: MarketDataConfig,
                      config: ExecutionConfig, data_events: Sequence[Tuple[int, str, datetime]] = (),
                      candlestick_config: Optional[CandlestickConfig] = None) -> ExecutionReport:
    """Batch form: exactly the stream. data_events as in Module D (validated by D.validate_data_events before any
    candle is processed)."""
    ev = D.validate_data_events(series, data_events, market.timeframe if market is not None else None)
    st = ExecutionStream(instrument, timeframe, market, config, candlestick_config)
    j, outputs = 0, []
    for c in series:
        out: list = []
        while j < len(ev) and ev[j][0] == c.index:
            _, state, ts = ev[j]
            out += st.mark_data_interrupted(ts) if state == D.DATA_INTERRUPTED else st.mark_data_resumed(ts)
            j += 1
        out += st.on_candle(c)
        outputs.append((c.index, out))
    if j != len(ev):
        raise ValueError("%d data event(s) were not applied" % (len(ev) - j))
    return ExecutionReport(list(st.records), list(st.intake_diagnostics), list(st.snapshots), outputs,
                           st.finalize_end_of_data(), list(st.d.setups))


def detect_execution(series: CandleSeries, instrument: str, timeframe: str, market: MarketDataConfig,
                     config: ExecutionConfig) -> List[ExecutionEvent]:
    """Module E transitions as audit events (for engine.no_lookahead_violations); end-of-data marks excluded."""
    rep = analyze_execution(series, instrument, timeframe, market, config)
    out = []
    for r in rep.records:
        for t in r.history:
            if t.status in (ENTERED, NO_TRADE, EXPIRED, STOPPED_OUT, TARGET_HIT):
                out.append(ExecutionEvent("exec:%s:%s" % (t.status, r.setup_id),
                                          EventStamp(t.index, series[t.index].ts, t.index, series[t.index].ts),
                                          related=(r.setup_id,), status=t.status))
    return out
