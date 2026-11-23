"""Strategy link CHoCH -> reversal-confirming BOS -> qualifying liquidity sweep (setup CANDIDATES only).

Reads the structure stream and the liquidity stream; never changes either (LQ-22, LS-S09, G-11). Rules:
  SR-4 / CK-17  only a BOS with role REVERSAL_CONFIRMING (D1 + SR-3) opens setup eligibility; CONTINUATION and every
                other role never do.
  17.S (OWNER APPROVED 23 Nov 2026)  bullish reversal-confirming BOS -> BUY -> SSL sweep; bearish -> SELL -> BSL sweep.
                A BOS stays eligible from its candle until an opposite-direction CHoCH or an opposite-direction BOS; a
                same-direction continuation BOS does not end it. REPEAT_SWEEP and TAKEN stay ineligible while OQ-12 is OPEN.
  CK-17 r3-5    the sweep group must be on a candle strictly after the BOS candle; a same-candle sweep is recorded
                (LS-S11) but cannot qualify (diagnostic SWEEP_ON_BOS_CANDLE).
  OQ-5          r1 the first eligible sweep group after the BOS starts the candidate; r2 one pending candidate per BOS;
                r3 after EXPIRED / INVALIDATED / NO_TRADE a later group may start another while the BOS is current;
                r4 after CONFIRMED that BOS creates no other setup; r5 an opposite confirmed CHoCH or BOS ends the BOS
                eligibility; r6 one setup per sweep group (one candidate per group by construction).
  CK-18         an opposite-direction CHoCH or BOS before entry invalidates the pending candidate (INVALIDATED).
  Same-candle order (implementation, conservative): structure events at close k are applied first, so an opposite
  CHoCH / BOS at k ends the eligibility before sweep groups at k are considered. When an opposite BOS and an opposite
  CHoCH occur at the same close, the terminator (closed_by / ended_by) is chosen in canonical D5 order: the BOS
  (D5 step 1) before the CHoCH (D5 step 2); see terminating_events().
Only sweep GROUPS qualify (LQ-14 / OQ-5 speak of sweep groups). Whether REPEAT_SWEEP or TAKEN belong to a group is OPEN
(OQ-12), so they never start a candidate.
NOT here (later modules): pattern window, EXPIRED (CK-18 needs patterns), confirmation, entry, NO_TRADE. Those modules
call close_candidate(key, status, k, reason) with the exact candidate key (bos_id, group_id); this module only
implements the rules above. No setup id is created: CK-2's setup id needs a pattern id.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from scanner_v6.data.candle_models import Candle, CandleSeries
from scanner_v6.models import Direction
from scanner_v6.structure.choch import (REVERSAL_CONFIRMING, CHoCHBreak, StructureStateChange, StructureStream)

from .liquidity_pools import BSL, SSL
from .sweep import LiquidityStream, SweepGroup

BUY = "BUY"
SELL = "SELL"
PENDING = "PENDING"
INVALIDATED = "INVALIDATED"
EXPIRED = "EXPIRED"
NO_TRADE = "NO_TRADE"
CONFIRMED = "CONFIRMED"
TERMINAL = (INVALIDATED, EXPIRED, NO_TRADE, CONFIRMED)
SETUP_SIDE = {Direction.BULLISH: BUY, Direction.BEARISH: SELL}        # 17.S MB-1 / MB-2, OWNER APPROVED
REQUIRED_SWEEP_SIDE = {BUY: SSL, SELL: BSL}                           # Section 3, CK-16


def terminating_events(direction: Direction, bos_now, sev) -> list:
    """Opposite-direction events at one close that end a BOS's eligibility (17.S MB-3), in canonical D5 order
    (PHASE1_2_DECISIONS D5: (1) BOS evaluation, (2) CHoCH evaluation, (3) state update). Opposite BOS first, in the
    order the BOS stream emitted them, then opposite CHoCHBreaks in emission order. The first one is the terminator."""
    return [b for b in bos_now if b.direction is not direction] + \
           [e for e in sev if isinstance(e, CHoCHBreak) and e.direction is not direction]


@dataclass(frozen=True)
class SweepCandidate:
    bos_id: str
    bos_index: int
    group_id: str
    setup_side: str
    sweep_side: str
    index: int                      # sweep-group candle (zero-based)
    ts: datetime
    status: str = PENDING
    closed_index: Optional[int] = None
    closed_by: Optional[str] = None

    @property
    def key(self) -> Tuple[str, str]:
        return (self.bos_id, self.group_id)


@dataclass(frozen=True)
class QualifierDiagnostic:
    index: int
    code: str          # SWEEP_ON_BOS_CANDLE, CANDIDATE_ALREADY_PENDING, BOS_ALREADY_CONFIRMED, BOS_ELIGIBILITY_ENDED
    detail: str
    group_id: Optional[str] = None
    bos_id: Optional[str] = None


@dataclass
class _BOSState:
    """Eligibility of one REVERSAL_CONFIRMING BOS (OWNER APPROVED 23 Nov 2026, 17.S): eligible from its candle until an
    opposite-direction CHoCH or an opposite-direction BOS; a same-direction (continuation) BOS does not end it."""
    bos_id: str
    direction: Direction
    index: int
    eligible: bool = True
    ended_index: Optional[int] = None
    ended_by: Optional[str] = None
    confirmed_setup: bool = False


class SetupSweepStream:
    """Feed completed candles in order. Owns a StructureStream and a LiquidityStream (both unchanged by this class).
    All candidate bookkeeping is per BOS and per candidate key (bos_id, group_id); nothing is selected globally."""

    def __init__(self):
        self.structure = StructureStream()
        self.liquidity = LiquidityStream()
        self.bos_states: Dict[str, _BOSState] = {}
        self.current_bos_id: Optional[str] = None    # the eligible BOS (at most one: a new reversal needs a CHoCH first)
        self.candidates: List[SweepCandidate] = []
        self._pos: Dict[Tuple[str, str], int] = {}
        self.diagnostics: List[QualifierDiagnostic] = []
        self.snapshots: List[Tuple[SweepCandidate, ...]] = []

    @property
    def current(self) -> Optional[_BOSState]:
        return self.bos_states[self.current_bos_id] if self.current_bos_id is not None else None

    def candidate(self, key: Tuple[str, str]) -> SweepCandidate:
        return self.candidates[self._pos[key]]

    def pending_for(self, bos_id: str) -> Optional[SweepCandidate]:
        """The pending candidate of this BOS (OQ-5 r2: at most one)."""
        p = [c for c in self.candidates if c.bos_id == bos_id and c.status == PENDING]
        if len(p) > 1:
            raise AssertionError("more than one pending candidate for %s" % bos_id)
        return p[0] if p else None

    def _set_status(self, key: Tuple[str, str], status: str, k: int, by: str) -> SweepCandidate:
        i = self._pos[key]
        self.candidates[i] = replace(self.candidates[i], status=status, closed_index=k, closed_by=by)
        return self.candidates[i]

    def close_candidate(self, key: Tuple[str, str], status: str, k: int, reason: str) -> SweepCandidate:
        """For later modules (pattern / confirmation / entry): move exactly the candidate `key` = (bos_id, group_id) to a
        terminal status at candle k, the candle just processed. Only that candidate changes."""
        if status not in TERMINAL:
            raise ValueError("status must be one of %s" % (TERMINAL,))
        if key not in self._pos:
            raise KeyError("unknown candidate %r" % (key,))
        c = self.candidate(key)
        if c.status != PENDING:
            raise ValueError("candidate %r is already %s" % (key, c.status))
        if not self.snapshots or k != len(self.snapshots) - 1 or k < c.index:
            raise ValueError("k must be the candle just processed (%s) and not before the sweep candle %d"
                             % (len(self.snapshots) - 1 if self.snapshots else None, c.index))
        c = self._set_status(key, status, k, reason)
        if status == CONFIRMED:
            self.bos_states[c.bos_id].confirmed_setup = True          # OQ-5 r4, for exactly this BOS
        self.snapshots[-1] = tuple(self.candidates)                   # state after this close, as later modules saw it
        return c

    def on_candle(self, c: Candle):
        sev = self.structure.on_candle(c)
        bos_now = [b for b in self.structure.bos_events if b.index == c.index]
        cur = self.current
        if cur is not None:                                           # OQ-5 r5 / CK-18 / 17.S termination events
            opp = terminating_events(cur.direction, bos_now, sev)
            if opp:
                cur.eligible, cur.ended_index, cur.ended_by = False, c.index, opp[0].id
                p = self.pending_for(cur.bos_id)
                if p is not None:                                     # only the ended BOS's candidate
                    self._set_status(p.key, INVALIDATED, c.index, opp[0].id)
                self.diagnostics.append(QualifierDiagnostic(c.index, "BOS_ELIGIBILITY_ENDED", "%s ends the eligibility "
                                                            "of %s" % (opp[0].id, cur.bos_id), bos_id=cur.bos_id))
                self.current_bos_id, cur = None, None
        for e in sev:
            if isinstance(e, StructureStateChange) and e.cause == "REVERSAL_CONFIRMED":
                b = [x for x in bos_now if x.id in e.related][0]
                if self.structure.bos_roles.get(b.id) == REVERSAL_CONFIRMING:
                    if self.current_bos_id is not None:               # impossible: a reversal needs a CHoCH first
                        raise AssertionError("two eligible BOS at once (%s, %s)" % (self.current_bos_id, b.id))
                    self.bos_states[b.id] = _BOSState(b.id, b.direction, c.index)
                    self.current_bos_id, cur = b.id, self.bos_states[b.id]
        lev = self.liquidity.on_candle(c)
        new: List[SweepCandidate] = []
        for g in (x for x in lev if isinstance(x, SweepGroup)):       # REPEAT_SWEEP / TAKEN are not groups (OQ-12)
            if cur is None:
                continue
            side = SETUP_SIDE[cur.direction]
            if g.side != REQUIRED_SWEEP_SIDE[side]:
                continue
            pend = self.pending_for(cur.bos_id)
            if c.index <= cur.index:                                  # CK-17 r3-5 (same candle as the BOS)
                self.diagnostics.append(QualifierDiagnostic(c.index, "SWEEP_ON_BOS_CANDLE", "%s on the BOS candle of "
                                                            "%s cannot qualify" % (g.id, cur.bos_id), g.id, cur.bos_id))
            elif cur.confirmed_setup:                                 # OQ-5 r4
                self.diagnostics.append(QualifierDiagnostic(c.index, "BOS_ALREADY_CONFIRMED", "%s: %s already has a "
                                                            "CONFIRMED setup" % (g.id, cur.bos_id), g.id, cur.bos_id))
            elif pend is not None:                                    # OQ-5 r2 (per BOS)
                self.diagnostics.append(QualifierDiagnostic(c.index, "CANDIDATE_ALREADY_PENDING", "%s: candidate %s "
                                                            "still pending" % (g.id, pend.group_id), g.id, cur.bos_id))
            else:                                                     # OQ-5 r1 / r3; r6: one candidate per group
                cand = SweepCandidate(cur.bos_id, cur.index, g.id, side, g.side, c.index, c.ts)
                self._pos[cand.key] = len(self.candidates)
                self.candidates.append(cand)
                new.append(cand)
        self.snapshots.append(tuple(self.candidates))
        return sev, lev, new


@dataclass
class SetupSweepReport:
    candidates: List[SweepCandidate]
    diagnostics: List[QualifierDiagnostic]
    snapshots: List[Tuple[SweepCandidate, ...]]


def analyze_setup_sweeps(series: CandleSeries) -> SetupSweepReport:
    st = SetupSweepStream()
    for c in series:
        st.on_candle(c)
    return SetupSweepReport(list(st.candidates), list(st.diagnostics), list(st.snapshots))
