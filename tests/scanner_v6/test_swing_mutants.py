#!/usr/bin/env python3
"""Mutation tests: deliberately faulty swing detectors must FAIL the Volume-1 fixtures through the oracle-based
replay audit, each in the expected category. Proves the fixtures + G12 harness can tell a wrong detector from the
approved one. Offline.

    python tests/scanner_v6/test_swing_mutants.py      (or: python -m pytest tests/scanner_v6)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import run_main  # noqa: E402

import test_swing_fixtures as F  # noqa: E402
from scanner_v6.engine import replay_audit  # noqa: E402
from scanner_v6.models import EventStamp, SwingKind, SwingPoint  # noqa: E402
from scanner_v6.structure import swings as SW  # noqa: E402

CFG = SW.SwingConfig()


def _sp(series, kind, i, conf, price=None, eid=None):
    c, k = series[i], series[conf]
    return SwingPoint(eid or SW.swing_id(kind, i, CFG), EventStamp.from_candles(c, k), kind=kind,
                      price=price if price is not None else (c.high if kind is SwingKind.HIGH else c.low))


def inclusive(series):
    """M1: >= instead of > (silently relaxed comparison)."""
    out = []
    for i in range(2, len(series) - 2):
        for kind in (SwingKind.HIGH, SwingKind.LOW):
            v = lambda j: series[j].high if kind is SwingKind.HIGH else -series[j].low      # noqa: E731
            if all(v(i) >= v(j) for j in (i - 2, i - 1, i + 1, i + 2)):
                out.append(_sp(series, kind, i, i + 2))
    return out


def premature(series):
    """M2: emits a candidate as soon as its left side and the right bars seen so far pass, before i + R closes."""
    out = []
    n = len(series)
    for i in range(2, n):
        for kind in (SwingKind.HIGH, SwingKind.LOW):
            v = lambda j: series[j].high if kind is SwingKind.HIGH else -series[j].low      # noqa: E731
            right = [j for j in (i + 1, i + 2) if j < n]
            if all(v(i) > v(j) for j in [i - 2, i - 1] + right):
                out.append(_sp(series, kind, i, i + 2) if i + 2 < n else
                           SwingPoint(SW.swing_id(kind, i, CFG), EventStamp(i, series[i].ts, i + 2), kind=kind,
                                      price=series[i].high if kind is SwingKind.HIGH else series[i].low))
    return out


def late(series):
    """M3: waits one extra candle (confirmed at i + R + 1)."""
    return [_sp(series, e.kind, e.index, e.confirmed_index + 1) for e in SW.detect_swings(series)
            if e.confirmed_index + 1 < len(series)]


def one_kind_per_candle(series):
    """M4: drops the low when the same candle is also a swing high (breaks SW-005)."""
    out, seen = [], set()
    for e in SW.detect_swings(series):
        if e.index in seen:
            continue
        seen.add(e.index)
        out.append(e)
    return out


def repainting(series):
    """M5: the swing's price follows the latest candle (changes as data arrives)."""
    last = series[len(series) - 1].close
    return [_sp(series, e.kind, e.index, e.confirmed_index, price=e.price + (last % 1) * 1e-3)
            for e in SW.detect_swings(series)]


def duplicating(series):
    """M7: every swing emitted twice under two ids."""
    out = []
    for e in SW.detect_swings(series):
        out += [e, _sp(series, e.kind, e.index, e.confirmed_index, eid=e.id + ":dup")]
    return out


class LateStream:
    """M6: streaming form that evaluates one candle too late (source = k - R - 1)."""

    def __init__(self):
        self.c = []

    def on_candle(self, candle):
        self.c.append(candle)
        i = candle.index - 3
        if i < 2:
            return []
        return [_sp(self.c, e.kind, e.index, candle.index) for e in SW._evaluate(self.c, i, CFG)]


def fails(mutant_batch=None, mutant_stream=None, want=()):
    """Run the mutant over every non-rejected, asserted fixture; return the set of finding categories seen."""
    seen = set()
    for case in F.CASES:
        if case["case_id"] in F.REJECT or case["case_id"] in F.NOT_ASSERTED:
            continue
        s = F.load(case)
        exp = {(k, i): c for k, i, c, _ in F.oracle(case)}
        a = replay_audit(s, exp, F.KEY, detector=mutant_batch or SW.detect_swings,
                         make_stream=mutant_stream or SW.SwingStream)
        seen |= set(a.categories())
    missing = [w for w in want if w not in seen]
    assert not missing, "mutant not caught as %s (seen %s)" % (missing, sorted(seen))
    return seen


def test_m1_inclusive_comparison_is_caught():
    fails(inclusive, want=("unexpected", "batch_only"))


def test_m2_premature_emission_is_caught():
    fails(premature, want=("premature", "early"))


def test_m3_late_confirmation_is_caught():
    fails(late, want=("late", "wrong_confirmed_index"))


def test_m4_dropping_a_dual_pivot_is_caught():
    fails(one_kind_per_candle, want=("missing", "stream_only"))


def test_m5_repainting_is_caught():
    fails(repainting, want=("repaint",))


def test_m6_stream_one_candle_late_is_caught():
    fails(mutant_stream=LateStream, want=("late", "parity_time"))


def test_m7_duplicates_are_caught():
    fails(duplicating, want=("duplicate", "batch_only"))


def test_the_approved_detector_passes_the_same_check():
    seen = set()
    for case in F.CASES:
        if case["case_id"] in F.REJECT or case["case_id"] in F.NOT_ASSERTED:
            continue
        s = F.load(case)
        exp = {(k, i): c for k, i, c, _ in F.oracle(case)}
        seen |= set(replay_audit(s, exp, F.KEY, detector=SW.detect_swings, make_stream=SW.SwingStream).categories())
    assert not seen, seen


if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
