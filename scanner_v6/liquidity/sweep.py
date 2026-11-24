"""Liquidity sweeps: SWEEP, REPEAT_SWEEP and TAKEN events on pools, and same-candle sweep groups.

Implemented from OWNER APPROVED rules only (liquidity register; spec 11, CK-15, OQ-4):
  LQ-08 / LS-S02 / LQ-09  per pool at price P, on a completed candle (open plays no role, G-4):
      BSL: close > P            -> TAKEN            SSL: close < P            -> TAKEN
           high > P, close <= P -> sweep               low < P, close >= P   -> sweep
      (close == P after a strict wick beyond P is a sweep; d = 0, strict penetration; raw floats, G-8)
  LQ-06 / LQ-15 / G-5 / LQ-16
      ACTIVE + sweep -> SWEEP event (BSL_SWEEP / SSL_SWEEP, LQ-17), state SWEPT
      SWEPT  + sweep -> REPEAT_SWEEP diagnostic event (at most one per pool per candle), state stays SWEPT
      ACTIVE / SWEPT + close beyond -> TAKEN event (distinct event, OQ-4), state TAKEN; a TAKEN pool is inactive
  G-1     candle k evaluates only pools whose swing was confirmed at or before k - 1; swings confirmed at k create pools
          that are evaluated from k + 1
  LQ-14 / G-2 / OQ-4  one event per pool; SWEEP events of the same side on the same candle share the group id
          sweep:<side>:<k> (side BSL / SSL, k zero-based). Opposite sides get different groups.
  OQ-4 / G-6  event id liquidity:<pool_id>:<event_type>:<k>, event_type SWEEP / REPEAT_SWEEP / TAKEN; deterministic
  LQ-21   every event is emitted at its own detection candle (index = confirmed index = k); never backdated
  LQ-22 / LS-S09 / G-11  this module never reads or changes the structure state and never emits BOS / CHoCH
  LP-12   a pool TAKEN and a BOS reference consumption are separate (the pool rule here, BOS-005 in structure/bos.py)
OPEN, so NOT implemented:
  OQ-12   whether TAKEN events and REPEAT_SWEEP diagnostics belong to a sweep group: they carry group_id None
  LQ-10   GRAB / RUN taxonomy (TAKEN is not also named RUN)
  LQ-07   expiry other than "no expiry by elapsed time"
  LQ-12   R1 reclaim after a close beyond (reclaim.py stays NOT IMPLEMENTED)
  BOS-006 / C1  tick-size epsilon: none applied (G-8)
Implementation ordering (not a trading rule): within one candle, pools are evaluated in creation order (swing
confirmation index, then swing index, then high before low, as the swing detector emits them); each sweep group record
follows its SWEEP events; new pools confirmed at k come last.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from scanner_v6.data.candle_models import Candle, CandleSeries
from scanner_v6.models import Event, EventStamp, LiquidityPool, ModelError
from scanner_v6.structure.swings import SwingConfig, SwingStream

from .liquidity_pools import ACTIVE, BSL, SSL, SWEPT, TAKEN, pool_from_swing, pool_side

SWEEP = "SWEEP"
REPEAT_SWEEP = "REPEAT_SWEEP"
EVENT_TYPES = (SWEEP, REPEAT_SWEEP, TAKEN)


def liquidity_event_id(pool_id: str, event_type: str, k: int) -> str:
    """OQ-4: liquidity:<pool_id>:<event_type>:<k>."""
    if event_type not in EVENT_TYPES:
        raise ValueError("unknown liquidity event type %r" % (event_type,))
    return "liquidity:%s:%s:%d" % (pool_id, event_type, k)


def sweep_group_id(side: str, k: int) -> str:
    """OQ-4 / G-2: sweep:<side>:<k>."""
    if side not in (BSL, SSL):
        raise ValueError("side must be BSL or SSL")
    return "sweep:%s:%d" % (side, k)


@dataclass(frozen=True)
class LiquidityEvent(Event):
    """One pool event on candle k. name: BSL_SWEEP / SSL_SWEEP for SWEEP (LQ-17); REPEAT_SWEEP; TAKEN.
    level = pool price; extreme = the candle high (BSL) or low (SSL); close = the candle close."""
    pool_id: str = ""
    side: str = BSL
    event_type: str = SWEEP
    name: str = ""
    level: float = 0.0
    extreme: float = 0.0
    close: float = 0.0
    group_id: Optional[str] = None
    state_before: str = ACTIVE
    state_after: str = SWEPT

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.side not in (BSL, SSL) or self.event_type not in EVENT_TYPES:
            raise ModelError("bad side / event type")
        if not self.pool_id or self.pool_id == self.id:
            raise ModelError("pool_id must be a non-empty string, not the event id")


@dataclass(frozen=True)
class SweepGroup(Event):
    """All SWEEP events of one side on one candle (LQ-14). id = sweep:<side>:<k>; related = their event ids."""
    side: str = BSL
    pool_ids: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.side not in (BSL, SSL) or not self.pool_ids:
            raise ModelError("a sweep group needs a side and at least one pool")


def classify(side: str, price: float, c: Candle) -> Optional[str]:
    """TAKEN, SWEEP (a qualifying wick) or None for one pool on one completed candle (LQ-08, LS-S02, G-4, G-8)."""
    if side == BSL:
        if c.close > price:
            return TAKEN
        return SWEEP if c.high > price else None
    if c.close < price:
        return TAKEN
    return SWEEP if c.low < price else None


class LiquidityStream:
    """Feed completed candles in order; on_candle(c) returns the liquidity events known at c's close: pool events
    (SWEEP / REPEAT_SWEEP / TAKEN), sweep groups, then the pools created at c. Same output as detect_liquidity at
    every prefix."""

    def __init__(self, swing_config: Optional[SwingConfig] = None):
        self.swings = SwingStream(swing_config)
        self.pools: List[LiquidityPool] = []            # creation order
        self.state: Dict[str, str] = {}
        self.events: List[LiquidityEvent] = []
        self.groups: List[SweepGroup] = []
        self.timeline: List[Tuple[Tuple[str, str], ...]] = []   # after each close: (pool id, state) of evaluable pools

    def on_candle(self, c: Candle) -> List[Event]:
        new_swings = self.swings.on_candle(c)           # validates order / type; swings confirmed at c's close
        out: List[Event] = []
        sweeps: Dict[str, List[LiquidityEvent]] = {BSL: [], SSL: []}
        for p in self.pools:                            # only pools created at or before c.index - 1 (G-1)
            st = self.state[p.id]
            if st == TAKEN:
                continue
            side = pool_side(p)
            kind = classify(side, p.price, c)
            if kind is None:
                continue
            extreme = c.high if side == BSL else c.low
            stamp = EventStamp.from_candles(c, c)
            if kind == TAKEN:
                ev = LiquidityEvent(liquidity_event_id(p.id, TAKEN, c.index), stamp, related=(p.id,), pool_id=p.id,
                                    side=side, event_type=TAKEN, name=TAKEN, level=p.price, extreme=extreme,
                                    close=c.close, group_id=None, state_before=st, state_after=TAKEN)
                self.state[p.id] = TAKEN
                out.append(ev)
            elif st == ACTIVE:
                ev = LiquidityEvent(liquidity_event_id(p.id, SWEEP, c.index), stamp, related=(p.id,), pool_id=p.id,
                                    side=side, event_type=SWEEP, name="%s_SWEEP" % side, level=p.price,
                                    extreme=extreme, close=c.close, group_id=sweep_group_id(side, c.index),
                                    state_before=ACTIVE, state_after=SWEPT)
                self.state[p.id] = SWEPT
                sweeps[side].append(ev)
                out.append(ev)
            else:                                       # SWEPT: one REPEAT_SWEEP per pool per candle (G-5)
                ev = LiquidityEvent(liquidity_event_id(p.id, REPEAT_SWEEP, c.index), stamp, related=(p.id,),
                                    pool_id=p.id, side=side, event_type=REPEAT_SWEEP, name=REPEAT_SWEEP,
                                    level=p.price, extreme=extreme, close=c.close, group_id=None,
                                    state_before=SWEPT, state_after=SWEPT)
                out.append(ev)
        self.events += [e for e in out if isinstance(e, LiquidityEvent)]
        for side in (BSL, SSL):
            if sweeps[side]:
                g = SweepGroup(sweep_group_id(side, c.index), EventStamp.from_candles(c, c),
                               related=tuple(e.id for e in sweeps[side]), side=side,
                               pool_ids=tuple(e.pool_id for e in sweeps[side]))
                self.groups.append(g)
                out.append(g)
        for s in new_swings:                            # usable from c.index + 1
            p = pool_from_swing(s)
            self.pools.append(p)
            self.state[p.id] = ACTIVE
            out.append(p)
        self.timeline.append(tuple((p.id, self.state[p.id]) for p in self.pools))
        return out


@dataclass
class LiquidityReport:
    pools: List[LiquidityPool]
    events: List[LiquidityEvent]
    groups: List[SweepGroup]
    final_state: Dict[str, str]
    timeline: List[Tuple[Tuple[str, str], ...]]

    def states_after(self, k: int) -> Dict[str, str]:
        """Pool states after the close of candle k (pools created at or before k)."""
        return dict(self.timeline[k])


def analyze_liquidity(series: CandleSeries, swing_config: Optional[SwingConfig] = None) -> LiquidityReport:
    st = LiquidityStream(swing_config)
    for c in series:
        st.on_candle(c)
    return LiquidityReport(list(st.pools), list(st.events), list(st.groups), dict(st.state), list(st.timeline))


def detect_liquidity(series: CandleSeries) -> List[Event]:
    """Batch detector for the engine harness: every pool, liquidity event and sweep group, in emission order."""
    st = LiquidityStream()
    out: List[Event] = []
    for c in series:
        out += st.on_candle(c)
    return out
