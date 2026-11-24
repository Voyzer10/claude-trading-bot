"""Market-structure state and change of character (CHoCH): only the rules APPROVED up to 22 Nov 2026.

Approved rules implemented:
  A1     external structure only. "External" has no executable definition yet, so every L2/R2 swing counts as
         external. This is a stated limitation, not a rule.
  A2-A4  a structure is established when the latest two confirmed swing highs AND the latest two confirmed swing
         lows are HH + HL (BULLISH) or LH + LL (BEARISH). With fewer than 2 + 2, or any other combination, the state
         stays UNKNOWN (A3). Once established, the state changes only through the events below.
  A5/D2  protected swing = the active P-B origin (structure/protected_levels.py). It is used only after its L2/R2
         confirmation; until then the previous valid protected swing is kept.
  A6     CHoCH = a candle CLOSE beyond the protected swing, against the structure direction. Wick-only is NO_CHOCH;
         it is recorded as a WICK_ONLY diagnostic, not as an event. The comparison is STRICT, which is the CURRENT
         DEFAULT (the same as BOS), not an approved CHoCH decision: see CHU04 below.
  A7/A8  after a CHoCH the state is TRANSITION(direction). While in TRANSITION no CHoCH is emitted.
  D1     a separate, LATER BOS (structure/bos.py) in the CHoCH direction confirms the reversal. A BOS on the CHoCH
         candle never confirms it, because confirmation needs the pre-candle state to be TRANSITION already. After
         confirmation the protected swing is the origin of the confirming BOS, or of a later BOS (D2).
  D3     X1: exactly one protected level is crossed by the close -> one CHoCH against it. Other swing levels of the
         same kind crossed on the same candle are recorded as `levels_crossed` evidence. If more than one competing
         protected level would be responsible -> COMPLEX_STRUCTURE_BREAK, never a forced CHoCH.
  D5     at the close of candle k: (1) BOS from swings confirmed at or before k-1; (2) CHoCH from the pre-candle
         state and protected swing; (3) state update; (4) swings confirmed at k: P-B activation, then structure
         establishment. Changes made in (4) apply from candle k+1.

Structure reconciliation, delegated owner decisions SR-1..SR-6 (23 Nov 2026, spec 17.R):
  SR-1   sticky origin: an activated P-B origin stays protected when a later same-leg candidate fails A5 (A5 base = the
         immediately previous confirmed swing of that kind). protected_levels.py already behaves so; no change.
  SR-2   establishment with no qualifying P-B origin: the establishing HL (BULLISH) / LH (BEARISH) is the protected level
         from k + 1, until the first qualifying P-B origin for that direction activates (then permanently replaced).
  SR-3   a reversal-confirming BOS must break a swing confirmed at or after the CHoCH candle (usable from CHoCH + 1, D5).
  SR-4   every BOS gets one role (BOS_ROLES); only REVERSAL_CONFIRMING may start a reversal setup (CK-17).
  SR-5   an opposite-direction BOS during TRANSITION invalidates the reversal and restores the prior structure; the
         consumed protected swing is not restored; the protected level is the P-B origin of that BOS or a later one.
  SR-6   establishment is rejected (state stays UNKNOWN) when the establishing close is already beyond the candidate
         protected level (ESTABLISHMENT_REJECTED_O9).

UNRESOLVED, so NOT implemented as rules (diagnostics only):
  O4     failed CHoCH: a close back across the consumed level WITHOUT an opposite BOS: no event (O4_UNRESOLVED). (The
         opposite-BOS part is decided by SR-5.)
  O5     the state AFTER a COMPLEX_STRUCTURE_BREAK is unspecified. The guard cannot trigger with one protected level
         per direction. If it ever does, the state becomes UNKNOWN with reason O5_STATE_AFTER_COMPLEX_UNRESOLVED.
  O7     session gaps; O8 invalidation.
  CHU04  strictness of the CHoCH close is UNRESOLVED. The code keeps the strict comparison as its current default (no
         CHoCH when the close EQUALS the protected level). Such a candle is recorded with the neutral diagnostic
         EXACT_LEVEL_CLOSE, never as WICK_ONLY, so the open question stays visible.
  O9     decided by SR-6 (establishment rejected when the close is already beyond the candidate protected level).
  CHU05  mixed HH + LL stays UNKNOWN (the A3 default), with a MIXED_STRUCTURE diagnostic. LH + HL also stays
         UNKNOWN with MIXED_STRUCTURE, but CHU05 is not claimed for it. An EQUAL swing price (equal highs or equal
         lows between swings; FIXTURE_REVIEW C6, open) stays UNKNOWN with the neutral EQUAL_SWING_PRICE diagnostic.

Research only: no orders, no broker, no live routing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from ..data.candle_models import Candle, CandleSeries
from ..models import (BOSEvent, CHoCHEvent, Direction, Event, EventStamp, StructureEvent, SwingKind, SwingPoint)
from .bos import BOSStream
from .protected_levels import ProtectedTracker
from .swings import SwingConfig


class State(str, Enum):
    UNKNOWN = "UNKNOWN"
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    TRANSITION_BULLISH = "TRANSITION(bullish)"     # after a bullish CHoCH, awaiting a later bullish BOS
    TRANSITION_BEARISH = "TRANSITION(bearish)"


# SR-4: BOS roles (one per BOS, decided at its own close)
REVERSAL_CONFIRMING = "REVERSAL_CONFIRMING"
REVERSAL_INVALIDATING = "REVERSAL_INVALIDATING"
CONTINUATION = "CONTINUATION"
COUNTER_STRUCTURE = "COUNTER_STRUCTURE"
TRANSITION_REF_BEFORE_CHOCH = "TRANSITION_REF_BEFORE_CHOCH"
TRANSITION_AMBIGUOUS = "TRANSITION_AMBIGUOUS"
PRE_STRUCTURE = "PRE_STRUCTURE"
BOS_ROLES = (REVERSAL_CONFIRMING, REVERSAL_INVALIDATING, CONTINUATION, COUNTER_STRUCTURE, TRANSITION_REF_BEFORE_CHOCH,
             TRANSITION_AMBIGUOUS, PRE_STRUCTURE)
SETUP_ELIGIBLE_BOS_ROLES = (REVERSAL_CONFIRMING,)     # CK-17 + SR-4: only these may start a reversal setup


def _transition(d: Direction) -> State:
    return State.TRANSITION_BULLISH if d is Direction.BULLISH else State.TRANSITION_BEARISH


def _structure(d: Direction) -> State:
    return State.BULLISH if d is Direction.BULLISH else State.BEARISH


@dataclass(frozen=True)
class CHoCHBreak(CHoCHEvent):
    """A CHoCH (A6, D3 X1). `level` / `broken_swing_id` = the protected swing; `levels_crossed` = other swing levels
    of the same kind crossed by this close (evidence only)."""
    state_before: str = ""
    state_after: str = ""
    levels_crossed: Tuple[float, ...] = field(default_factory=tuple)
    confirmation_basis: str = "CLOSE_BEYOND"


@dataclass(frozen=True)
class ComplexStructureBreak(StructureEvent):
    """D3: more than one competing protected level crossed by one close. Never turned into a CHoCH."""
    state_before: str = ""
    state_after: str = ""
    competing_ids: Tuple[str, ...] = field(default_factory=tuple)
    unresolved_reason: str = "O5_STATE_AFTER_COMPLEX_UNRESOLVED"


@dataclass(frozen=True)
class StructureStateChange(Event):
    """The structure state changed at the close of `index`. cause: ESTABLISHED, CHOCH, REVERSAL_CONFIRMED,
    REVERSAL_INVALIDATED (SR-5) or COMPLEX. `related` = the triggering event id(s) (CHoCH / BOS / complex); for
    REVERSAL_INVALIDATED (opposite BOS id, CHoCH id)."""
    state_before: str = ""
    state_after: str = ""
    cause: str = ""
    protected_swing_id: Optional[str] = None


@dataclass(frozen=True)
class Diagnostic:
    """Not an event. WICK_ONLY (a rejected NO_CHOCH candidate: wick beyond, close not at or beyond),
    EXACT_LEVEL_CLOSE (close equal to the protected level; CHU04 unresolved), O4_UNRESOLVED, ESTABLISHMENT_REJECTED_O9
    (SR-6), CONFIRMATION_REF_BEFORE_CHOCH (SR-3), TRANSITION_BOS_BOTH_DIRECTIONS (SR-5), MIXED_STRUCTURE,
    EQUAL_SWING_PRICE, or a P-B origin note (ACTIVATED / NOT_QUALIFIED / NO_ORIGIN_SWING)."""
    index: int
    code: str
    detail: str
    swing_id: Optional[str] = None


@dataclass(frozen=True)
class CandleState:
    """Per-candle record after the close of `index`. The protected swing shown is the one in force for the next candle."""
    index: int
    state: str
    protected_swing_id: Optional[str]
    protected_price: Optional[float]


def classify_break(protected_crossed: List[SwingPoint]) -> str:
    """D3. "X1" when exactly one protected level is responsible; "COMPLEX" when several compete; "NONE" otherwise."""
    if not protected_crossed:
        return "NONE"
    return "X1" if len(protected_crossed) == 1 else "COMPLEX"


class StructureStream:
    """Streaming structure / CHoCH detector. on_candle(c) returns the CHoCH, COMPLEX and state-change events at c's
    close. `bos_events`, `diagnostics` and `timeline` accumulate as candles arrive."""

    def __init__(self, config: Optional[SwingConfig] = None):
        cfg = config or SwingConfig()
        self.bos = BOSStream(cfg)
        self.tracker = ProtectedTracker(cfg.right)
        self.state = State.UNKNOWN
        self.min_bos_index: Dict[Direction, int] = {Direction.BULLISH: -1, Direction.BEARISH: -1}
        self.consumed: Set[str] = set()
        self.choch_level: Optional[Tuple[Direction, SwingPoint, int]] = None
        self.choch_id: Optional[str] = None
        self.fallback: Optional[Tuple[Direction, SwingPoint]] = None   # SR-2: establishing HL / LH
        self.bos_roles: Dict[str, str] = {}                            # SR-4
        self.bos_events: List[BOSEvent] = []
        self.diagnostics: List[Diagnostic] = []
        self.timeline: List[CandleState] = []
        self._prev_close: Optional[float] = None
        self._notes_seen = 0

    # -- helpers ------------------------------------------------------------------------------------------------
    def protected_in_force(self) -> Optional[SwingPoint]:
        if self.state in (State.BULLISH, State.BEARISH):
            d = Direction.BULLISH if self.state is State.BULLISH else Direction.BEARISH
            p = self.tracker.protected(d, self.min_bos_index[d], self.consumed)
            if p is None and self.fallback is not None and self.fallback[0] is d and \
                    self.fallback[1].id not in self.consumed:
                return self.fallback[1]                      # SR-2
            return p
        return None

    def _stamp(self, c: Candle) -> EventStamp:
        return EventStamp.from_candles(c, c)

    def _change(self, c: Candle, before: State, after: State, cause: str, related: Tuple[str, ...] = (),
                protected: Optional[SwingPoint] = None) -> StructureStateChange:
        return StructureStateChange("state:%d:%s->%s" % (c.index, before.value, after.value), self._stamp(c),
                                    related=related, state_before=before.value, state_after=after.value, cause=cause,
                                    protected_swing_id=protected.id if protected else None)

    # -- one candle ---------------------------------------------------------------------------------------------
    def on_candle(self, c: Candle) -> List[Event]:
        out: List[Event] = []
        pre_state = self.state
        prot = self.protected_in_force()                     # pre-candle protected swing (D5 step 2)
        known_before = list(self.bos.swings)                 # swings confirmed at or before k-1
        # (1) BOS (also runs the swing stream; the swings confirmed at k are kept apart until step 4)
        bos_now = self.bos.on_candle(c)
        self.bos_events.extend(bos_now)
        # (2) CHoCH against the pre-candle state
        choch: Optional[Event] = None
        if pre_state in (State.BULLISH, State.BEARISH) and prot is not None:
            bearish = pre_state is State.BULLISH                 # a bullish structure breaks down
            beyond = c.close < prot.price if bearish else c.close > prot.price     # strict: current default (CHU04)
            at_level = c.close == prot.price
            wick = c.low < prot.price if bearish else c.high > prot.price
            if beyond:
                d = Direction.BEARISH if bearish else Direction.BULLISH
                kind = SwingKind.LOW if bearish else SwingKind.HIGH
                prev = self._prev_close
                crossed = [s for s in known_before if s.kind is kind and s.id != prot.id and
                           (c.close < s.price if bearish else c.close > s.price) and
                           (prev is None or (prev >= s.price if bearish else prev <= s.price))]
                competing = [prot]                           # D2: one protected level per direction
                verdict = classify_break(competing)
                if verdict == "X1":
                    after = _transition(d)
                    choch = CHoCHBreak("choch:%s:%s" % (d.value, prot.id), self._stamp(c), related=(prot.id,),
                                       direction=d, level=prot.price, broken_swing_id=prot.id,
                                       state_before=pre_state.value, state_after=after.value,
                                       levels_crossed=tuple(sorted((s.price for s in crossed), reverse=bearish)))
                else:                                        # unreachable while D2 keeps one protected level
                    after = State.UNKNOWN
                    choch = ComplexStructureBreak("complex:%d" % c.index, self._stamp(c),
                                                  related=tuple(s.id for s in competing), direction=d,
                                                  level=prot.price, broken_swing_id=None,
                                                  state_before=pre_state.value, state_after=after.value,
                                                  competing_ids=tuple(s.id for s in competing))
            elif at_level:
                self.diagnostics.append(Diagnostic(c.index, "EXACT_LEVEL_CLOSE", "close %s equals protected %s (%s %s): "
                                                   "no CHoCH under the current strict-close default; CHU04 unresolved"
                                                   % (c.close, prot.price, "low" if bearish else "high",
                                                      c.low if bearish else c.high), prot.id))
            elif wick:
                self.diagnostics.append(Diagnostic(c.index, "WICK_ONLY", "NO_CHOCH: %s %s beyond protected %s, close %s"
                                                   % ("low" if bearish else "high", c.low if bearish else c.high,
                                                      prot.price, c.close), prot.id))
        # (3) state update
        if choch is not None:
            out.append(choch)
            if isinstance(choch, CHoCHBreak):
                self.consumed.add(prot.id)
                self.choch_level = (choch.direction, prot, c.index)
                self.choch_id = choch.id
                self.fallback = None                         # SR-2 rule 5: any CHoCH ends the fallback
                self.state = _transition(choch.direction)
                out.append(self._change(c, pre_state, self.state, "CHOCH", (choch.id,)))
            else:
                self.consumed.add(prot.id)
                self.state = State.UNKNOWN
                out.append(self._change(c, pre_state, self.state, "COMPLEX", (choch.id,)))
        elif pre_state in (State.TRANSITION_BULLISH, State.TRANSITION_BEARISH):
            d = Direction.BULLISH if pre_state is State.TRANSITION_BULLISH else Direction.BEARISH
            choch_k = self.choch_level[2] if self.choch_level is not None else None
            ref_by_id = {s.id: s for s in self.bos.swings}
            same = [b for b in bos_now if b.direction is d]
            opp = [b for b in bos_now if b.direction is not d]
            confirm = [b for b in same if choch_k is not None and ref_by_id[b.broken_swing_id].confirmed_index >= choch_k]
            for b in same:                                   # SR-3: reference confirmed before the CHoCH candle
                if b not in confirm:
                    self.bos_roles[b.id] = TRANSITION_REF_BEFORE_CHOCH
                    self.diagnostics.append(Diagnostic(c.index, "CONFIRMATION_REF_BEFORE_CHOCH", "%s breaks a swing "
                                                       "confirmed at %d, before the CHoCH candle %d: no confirmation"
                                                       % (b.id, ref_by_id[b.broken_swing_id].confirmed_index, choch_k),
                                                       b.broken_swing_id))
            if confirm and opp:                              # SR-5 rule 5: ambiguous, no state change
                for b in confirm + opp:
                    self.bos_roles[b.id] = TRANSITION_AMBIGUOUS
                self.diagnostics.append(Diagnostic(c.index, "TRANSITION_BOS_BOTH_DIRECTIONS", "%s and %s on one "
                                                   "candle during %s: no state change"
                                                   % (confirm[0].id, opp[0].id, pre_state.value)))
            elif confirm:                                    # D1 + SR-3
                b = confirm[0]
                self.bos_roles[b.id] = REVERSAL_CONFIRMING
                self.state = _structure(d)
                self.min_bos_index[d] = c.index              # protected = origin of this BOS or a later one (D1/D2)
                self.choch_level, self.choch_id = None, None
                out.append(self._change(c, pre_state, self.state, "REVERSAL_CONFIRMED", (b.id,)))
            elif opp:                                        # SR-5: invalidate, restore the prior structure
                b = opp[0]
                od = b.direction
                self.bos_roles[b.id] = REVERSAL_INVALIDATING
                self.state = _structure(od)
                self.min_bos_index[od] = c.index             # protected = origin of this BOS or a later one; the
                related = (b.id,) + ((self.choch_id,) if self.choch_id else ())   # consumed swing stays consumed
                self.choch_level, self.choch_id = None, None
                out.append(self._change(c, pre_state, self.state, "REVERSAL_INVALIDATED", related))
            if self.choch_level is not None and self.state is pre_state:
                cd, lvl, _ = self.choch_level
                back = c.close > lvl.price if cd is Direction.BEARISH else c.close < lvl.price
                if back:
                    self.diagnostics.append(Diagnostic(c.index, "O4_UNRESOLVED", "close %s back across the consumed "
                                                       "protected %s during %s: failed-CHoCH rule not approved"
                                                       % (c.close, lvl.price, pre_state.value), lvl.id))
        for b in bos_now:                                    # SR-4 roles not set above
            if b.id not in self.bos_roles:
                if pre_state is State.UNKNOWN:
                    self.bos_roles[b.id] = PRE_STRUCTURE
                elif pre_state is _structure(b.direction):
                    self.bos_roles[b.id] = CONTINUATION
                else:
                    self.bos_roles[b.id] = COUNTER_STRUCTURE
        # every BOS registers its P-B origin search
        swing_by_id = {s.id: s for s in self.bos.swings}
        for b in bos_now:
            self.tracker.on_bos(b, swing_by_id[b.broken_swing_id])
        # (4) swings confirmed at k: P-B activation, then establishment (in force from k+1)
        self.tracker.on_close(c.index, self.bos.swings)
        for n in self.tracker.notes[self._notes_seen:]:
            self.diagnostics.append(Diagnostic(n.index, n.code, "%s (%s)" % (n.detail, n.bos_id), n.swing_id))
        self._notes_seen = len(self.tracker.notes)
        if self.fallback is not None and self.tracker.active[self.fallback[0]] is not None:
            self.fallback = None                             # SR-2 rule 4: a qualifying P-B origin replaces it for good
        if self.state is State.UNKNOWN and self.bos.new_swings:
            est = self._establish(c)
            if est is not None:
                out.append(est)
        p = self.protected_in_force()
        self.timeline.append(CandleState(c.index, self.state.value, p.id if p else None, p.price if p else None))
        self._prev_close = c.close
        return out

    def _establish(self, c: Candle) -> Optional[StructureStateChange]:
        highs = sorted((s for s in self.bos.swings if s.kind is SwingKind.HIGH), key=lambda s: (s.confirmed_index, s.index))
        lows = sorted((s for s in self.bos.swings if s.kind is SwingKind.LOW), key=lambda s: (s.confirmed_index, s.index))
        if len(highs) < 2 or len(lows) < 2:
            return None
        h1, h2, l1, l2 = highs[-2].price, highs[-1].price, lows[-2].price, lows[-1].price
        if h2 > h1 and l2 > l1:
            d = Direction.BULLISH
        elif h2 < h1 and l2 < l1:
            d = Direction.BEARISH
        else:
            if h2 == h1 or l2 == l1:
                code, why = "EQUAL_SWING_PRICE", ("an equal swing price; classifying equal swings as HH / LH / HL / LL "
                                                  "is not approved (FIXTURE_REVIEW C6, open)")
            elif h2 > h1:
                code, why = "MIXED_STRUCTURE", "HH + LL (CHU05 unresolved)"
            else:
                code, why = "MIXED_STRUCTURE", "LH + HL: no approved classification"
            self.diagnostics.append(Diagnostic(c.index, code, "highs %s->%s, lows %s->%s: %s; stays UNKNOWN (A3)"
                                               % (h1, h2, l1, l2, why)))
            return None
        origin = self.tracker.protected(d, -1, self.consumed)   # initial: the most recent BOS origin (P-B)
        fb = None
        if origin is None and self.tracker.active[d] is None:     # SR-2: the establishing HL / LH
            fb = lows[-1] if d is Direction.BULLISH else highs[-1]
        p = origin or fb
        if p is not None and (c.close < p.price if d is Direction.BULLISH else c.close > p.price):
            self.diagnostics.append(Diagnostic(c.index, "ESTABLISHMENT_REJECTED_O9", "structure %s not established: "
                                               "close %s is already beyond the candidate protected %s (%s); stays "
                                               "UNKNOWN (SR-6)" % (d.value, c.close, p.price,
                                                                   "fallback" if fb is not None else "P-B origin"), p.id))
            return None
        before = self.state
        self.state = _structure(d)
        self.min_bos_index[d] = -1
        self.fallback = (d, fb) if fb is not None else None
        return self._change(c, before, self.state, "ESTABLISHED", (), p)


@dataclass
class StructureReport:
    events: List[Event]
    bos: List[BOSEvent]
    swings: List[SwingPoint]
    diagnostics: List[Diagnostic]
    timeline: List[CandleState]
    bos_roles: Dict[str, str] = field(default_factory=dict)      # SR-4: bos id -> role


def analyze_structure(series: CandleSeries, config: Optional[SwingConfig] = None) -> StructureReport:
    st = StructureStream(config)
    ev: List[Event] = []
    for c in series:
        ev.extend(st.on_candle(c))
    return StructureReport(ev, st.bos_events, list(st.bos.swings), st.diagnostics, st.timeline, dict(st.bos_roles))


def detect_structure(series: CandleSeries, config: Optional[SwingConfig] = None) -> List[Event]:
    """Batch form: the CHoCH / COMPLEX / state-change events within `series`; identical to StructureStream."""
    return analyze_structure(series, config).events
