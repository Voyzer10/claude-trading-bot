#!/usr/bin/env python3
"""Scanner V6 no-look-ahead harness (engine.no_lookahead_violations). The harness itself is tested here with toy
detectors that have NO trading meaning: an honest one must pass, and each kind of cheat must be caught. Every real V6
detector (swings, BOS, sweep...) gets its own no-look-ahead test with this harness when it is written. Offline.

    python tests/scanner_v6/test_no_lookahead.py   (or: python -m pytest tests/scanner_v6)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import load_fixture, run_main  # noqa: E402

from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.engine import events_known_at, no_lookahead_violations, run  # noqa: E402
from scanner_v6.models import EventStamp, SwingKind, SwingPoint  # noqa: E402

S = CandleSeries.from_chart_json(load_fixture(), "SYN", "5m")
LAG = 3


def honest(series):
    """Toy: mark candle i once LAG later candles have closed (known at i + LAG). Uses only candles <= i + LAG."""
    out = []
    for i in range(0, len(series) - LAG, 10):
        c, k = series[i], series[i + LAG]
        out.append(SwingPoint("toy%d" % i, EventStamp.from_candles(c, k), kind=SwingKind.HIGH, price=c.high))
    return out


def reports_too_early(series):
    """Cheat 1: reports the event on its source candle although it is only confirmed LAG candles later."""
    out = []
    for i in range(0, len(series), 10):
        c = series[i]
        out.append(SwingPoint("toy%d" % i, EventStamp(i, c.ts, i + LAG), kind=SwingKind.HIGH, price=c.high))
    return out


def revises_history(series):
    """Cheat 2: an event's price depends on the LAST candle of whatever it is given, so the same event id changes
    as more candles arrive (repainting)."""
    last = series[len(series) - 1]
    out = []
    for i in range(0, len(series) - 1, 10):
        c = series[i]
        out.append(SwingPoint("toy%d" % i, EventStamp(i, c.ts, i), kind=SwingKind.HIGH, price=last.close))
    return out


def peeks_at_future(series):
    """Cheat 3: uses a candle beyond the series it was given, by reading the module-level full series."""
    out = []
    n = len(series)
    if n + 2 <= len(S):
        f = S[n + 1]
        out.append(SwingPoint("peek%d" % n, EventStamp(n + 1, f.ts, n + 1), kind=SwingKind.LOW, price=f.low))
    return out


def test_honest_detector_passes():
    v = no_lookahead_violations(honest, S)
    assert v == [], v[:3]


def test_early_report_is_caught():
    v = no_lookahead_violations(reports_too_early, S)
    assert v and all("before it is confirmed" in x for x in v), v[:3]


def test_repainting_is_caught():
    v = no_lookahead_violations(revises_history, S)
    assert v and any("differs from the full run" in x for x in v), v[:3]


def test_future_candle_is_caught():
    v = no_lookahead_violations(peeks_at_future, S, start=0, every=7)
    assert v and any("future candle" in x for x in v), v[:3]


def test_engine_run_has_no_detectors_yet():
    assert run(S) == []
    ev = run(S, [honest])
    assert ev == sorted(ev, key=lambda e: (e.confirmed_index, e.index, e.id))
    k = 25
    known = events_known_at(ev, k)
    assert known and all(e.confirmed_index <= k for e in known)
    assert all(e.confirmed_index > k for e in ev if e not in known)


if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
