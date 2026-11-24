"""Scanner V6 engine: runs detectors over a candle series. Research only.

No detector exists yet, so `run()` returns no events. What is here is the contract every future detector follows,
and the no-look-ahead check that enforces it:

  A detector is a callable  detector(series: CandleSeries) -> list[Event].
  Called on `series.upto(k)`, it may only return events whose confirmed_index <= k, and every event it reports at k
  must be reported identically by a run on the full series (an event cannot change or vanish once known).

This module never places orders, never talks to a broker and never imports V4 or any live / paper module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Hashable, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

from .data.candle_models import Candle, CandleSeries
from .models import Event

Detector = Callable[[CandleSeries], List[Event]]


class StreamingDetector(Protocol):
    """Streaming form of a detector: fed one closed candle at a time (in order), it returns the events that became
    known at THAT candle's close. It never sees a later candle."""

    def on_candle(self, candle: Candle) -> List[Event]: ...


def run(series: CandleSeries, detectors: Sequence[Detector] = ()) -> List[Event]:
    """Run each detector on the whole series and return their events, ordered by (confirmed_index, index, id)."""
    out: List[Event] = []
    for d in detectors:
        out.extend(d(series))
    return sorted(out, key=lambda e: (e.confirmed_index if e.confirmed_index is not None else -1, e.index, e.id))


def no_lookahead_violations(detector: Detector, series: CandleSeries, start: int = 0,
                            every: int = 1) -> List[str]:
    """Replay `detector` candle by candle (prefixes 0..k) and compare with one run on the full series.

    Reported violations:
      - an event returned at k that is not confirmed by k (confirmed_index None or > k)
      - an event that refers to a candle after k (index > k)
      - an event returned at k that the full run does not contain, or contains with different fields
    Returns a list of human-readable violations; empty means the detector passed."""
    full = {e.id: e for e in detector(series)}
    bad: List[str] = []
    for k in range(start, len(series), max(1, every)):
        for e in detector(series.upto(k)):
            if e.confirmed_index is None or e.confirmed_index > k:
                bad.append("k=%d: %s %s reported before it is confirmed (confirmed_index %s)" % (
                    k, type(e).__name__, e.id, e.confirmed_index))
            if e.index > k:
                bad.append("k=%d: %s %s refers to future candle %d" % (k, type(e).__name__, e.id, e.index))
            f = full.get(e.id)
            if f is None:
                bad.append("k=%d: %s %s is missing from the full run (it was later revised)" % (
                    k, type(e).__name__, e.id))
            elif f != e:
                bad.append("k=%d: %s %s differs from the full run's version" % (k, type(e).__name__, e.id))
    return bad


def events_known_at(events: Iterable[Event], k: int) -> List[Event]:
    """The events confirmed at or before the close of candle k."""
    return [e for e in events if e.stamp.known_at(k)]


# --------------------------------------------------------------------------------------------------------------
# G12: oracle-based replay audit (added 21 Nov 2026). no_lookahead_violations() above is unchanged; it only checks
# one direction (nothing early, nothing revised). replay_audit() also catches events that are LATE, MISSING,
# DUPLICATED, or that differ between batch and streaming mode, by comparing each mode's emission time with an
# expected-event oracle (the approved fixtures).
# --------------------------------------------------------------------------------------------------------------

KeyFn = Callable[[Event], Hashable]


@dataclass
class Emissions:
    """What one mode emitted: event id -> (candle index at whose close it first appeared, the event)."""
    mode: str
    first_seen: Dict[str, Tuple[int, Event]] = field(default_factory=dict)
    problems: Dict[str, List[str]] = field(default_factory=dict)

    def add_problem(self, category: str, msg: str) -> None:
        self.problems.setdefault(category, []).append("%s: %s" % (self.mode, msg))


def batch_emissions(detector: Detector, series: CandleSeries) -> Emissions:
    """Replay a batch detector on every prefix 0..k. An event 'is emitted at k' when it first appears in the prefix-k
    output. Flags: an id twice in one output (duplicate), an event whose stated confirmed_index is not k when it first
    appears (premature if > k, self-late if < k), and any emitted event that later changes or disappears (repaint)."""
    em = Emissions("batch")
    prev: Dict[str, Event] = {}
    for k in range(len(series)):
        out = detector(series.upto(k))
        cur: Dict[str, Event] = {}
        for e in out:
            if e.id in cur:
                em.add_problem("duplicate", "id %s emitted twice in the prefix-%d output" % (e.id, k))
            cur[e.id] = e
        for eid, old in prev.items():
            if eid not in cur:
                em.add_problem("repaint", "%s disappeared at k=%d (emitted at %d)" % (eid, k, em.first_seen[eid][0]))
            elif cur[eid] != old:
                em.add_problem("repaint", "%s changed at k=%d (emitted at %d)" % (eid, k, em.first_seen[eid][0]))
        for eid, e in cur.items():
            if eid in em.first_seen:
                continue
            em.first_seen[eid] = (k, e)
            if e.confirmed_index is None or e.confirmed_index > k:
                em.add_problem("premature", "%s shown at k=%d but confirmed_index is %s" % (eid, k, e.confirmed_index))
            elif e.confirmed_index < k:
                em.add_problem("late", "%s first shown at k=%d but its confirmed_index is %d" % (eid, k,
                                                                                                e.confirmed_index))
        prev = cur      # an event that vanished was already flagged; a later return is not a fresh emission
    return em


def stream_emissions(make_stream: Callable[[], StreamingDetector], series: CandleSeries) -> Emissions:
    """Feed a fresh streaming detector the candles one by one. Flags: an id emitted twice (duplicate) and an event
    whose confirmed_index is not the candle it was emitted on (premature if > k, late if < k)."""
    em = Emissions("stream")
    s = make_stream()
    for c in series:
        k = c.index
        for e in s.on_candle(c):
            if e.id in em.first_seen:
                em.add_problem("duplicate", "id %s emitted again at k=%d (first at %d)" % (e.id, k,
                                                                                         em.first_seen[e.id][0]))
                continue
            em.first_seen[e.id] = (k, e)
            if e.confirmed_index is None or e.confirmed_index > k:
                em.add_problem("premature", "%s emitted at k=%d but confirmed_index is %s" % (e.id, k,
                                                                                            e.confirmed_index))
            elif e.confirmed_index < k:
                em.add_problem("late", "%s emitted at k=%d but its confirmed_index is %d" % (e.id, k,
                                                                                           e.confirmed_index))
    return em


@dataclass
class ReplayAudit:
    """Result of replay_audit(). Each category is a list of human-readable findings; ok == no finding at all."""
    findings: Dict[str, List[str]] = field(default_factory=dict)

    def add(self, category: str, msg: str) -> None:
        self.findings.setdefault(category, []).append(msg)

    @property
    def ok(self) -> bool:
        return not any(self.findings.values())

    def categories(self) -> List[str]:
        return sorted(k for k, v in self.findings.items() if v)


def _oracle_compare(em: Emissions, expected: Mapping[Hashable, int], key: KeyFn, audit: ReplayAudit) -> None:
    by_key: Dict[Hashable, List[Tuple[int, Event]]] = {}
    for eid, (k, e) in em.first_seen.items():
        by_key.setdefault(key(e), []).append((k, e))
    for kk, got in by_key.items():
        if len(got) > 1:
            audit.add("duplicate", "%s: %d events for one expected event %r (ids %s)" % (
                em.mode, len(got), kk, sorted(e.id for _, e in got)))
    for kk, exp_k in expected.items():
        got = by_key.get(kk)
        if not got:
            audit.add("missing", "%s: expected %r at k=%d was never emitted" % (em.mode, kk, exp_k))
            continue
        k, e = min(got, key=lambda x: x[0])
        if k < exp_k:
            audit.add("early", "%s: %r emitted at k=%d, expected at k=%d" % (em.mode, kk, k, exp_k))
        elif k > exp_k:
            audit.add("late", "%s: %r emitted at k=%d, expected at k=%d" % (em.mode, kk, k, exp_k))
        if e.confirmed_index != exp_k:
            audit.add("wrong_confirmed_index", "%s: %r has confirmed_index %s, expected %d" % (
                em.mode, kk, e.confirmed_index, exp_k))
    for kk, got in by_key.items():
        if kk not in expected:
            audit.add("unexpected", "%s: %r emitted at k=%d but is not in the oracle" % (em.mode, kk, got[0][0]))


def replay_audit(series: CandleSeries, expected: Optional[Mapping[Hashable, int]] = None, key: Optional[KeyFn] = None,
                 detector: Optional[Detector] = None,
                 make_stream: Optional[Callable[[], StreamingDetector]] = None) -> ReplayAudit:
    """Full causal audit of a detector against an expected-event oracle.

    expected: {event key: expected confirmation index}, the approved fixture's events (keys built by `key`).
    detector / make_stream: the batch form, the streaming form, or both.
    Categories reported: premature, early, late, missing, unexpected, duplicate, repaint, wrong_confirmed_index,
    batch_only, stream_only, parity_time, parity_fields. ok == True only if none fires."""
    if detector is None and make_stream is None:
        raise ValueError("give a batch detector, a streaming detector, or both")
    if expected is not None and key is None:
        raise ValueError("an oracle needs a key function")
    audit = ReplayAudit()
    modes: List[Emissions] = []
    if detector is not None:
        modes.append(batch_emissions(detector, series))
    if make_stream is not None:
        modes.append(stream_emissions(make_stream, series))
    for em in modes:
        for cat, msgs in em.problems.items():
            for m in msgs:
                audit.add(cat, m)
        if expected is not None:
            _oracle_compare(em, expected, key, audit)   # type: ignore[arg-type]
    if len(modes) == 2:
        b, s = modes
        for eid in sorted(set(b.first_seen) - set(s.first_seen)):
            audit.add("batch_only", "%s emitted in batch at k=%d but never in streaming" % (eid, b.first_seen[eid][0]))
        for eid in sorted(set(s.first_seen) - set(b.first_seen)):
            audit.add("stream_only", "%s emitted in streaming at k=%d but never in batch" % (eid, s.first_seen[eid][0]))
        for eid in sorted(set(b.first_seen) & set(s.first_seen)):
            (kb, eb), (ks, es) = b.first_seen[eid], s.first_seen[eid]
            if kb != ks:
                audit.add("parity_time", "%s: batch k=%d, streaming k=%d" % (eid, kb, ks))
            if eb != es:
                audit.add("parity_fields", "%s: batch and streaming events differ" % eid)
    return audit
