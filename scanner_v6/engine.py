"""Scanner V6 engine: runs detectors over a candle series. Research only.

No detector exists yet, so `run()` returns no events. What is here is the contract every future detector follows,
and the no-look-ahead check that enforces it:

  A detector is a callable  detector(series: CandleSeries) -> list[Event].
  Called on `series.upto(k)`, it may only return events whose confirmed_index <= k, and every event it reports at k
  must be reported identically by a run on the full series (an event cannot change or vanish once known).

This module never places orders, never talks to a broker and never imports V4 or any live / paper module.
"""
from __future__ import annotations

from typing import Callable, Iterable, List, Sequence

from .data.candle_models import CandleSeries
from .models import Event

Detector = Callable[[CandleSeries], List[Event]]


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
