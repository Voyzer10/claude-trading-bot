#!/usr/bin/env python3
"""Swing detector, APPROVED baseline profile (fixed window L2/R2, strict, equal levels unresolved, dual pivots
allowed): unit, boundary, negative, mirror, determinism, immutability and causality tests on hand-built candles.
Offline.

    python tests/scanner_v6/test_swings.py      (or: python -m pytest tests/scanner_v6)
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import raises, run_main  # noqa: E402

from scanner_v6.data.candle_models import Candle, CandleSeries  # noqa: E402
from scanner_v6.engine import no_lookahead_violations, replay_audit  # noqa: E402
from scanner_v6.models import SwingKind  # noqa: E402
from scanner_v6.structure.swings import (SwingConfig, SwingStream, detect_swings, swing_id,  # noqa: E402
                                         unresolved_equal_levels)

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)


def series(rows):
    return CandleSeries([Candle(i, T0 + timedelta(minutes=5 * i), *r) for i, r in enumerate(rows)], "T", "5m")


def keys(evs):
    return [(e.kind.value, e.index, e.confirmed_index, e.price) for e in evs]


PDF = [(10, 11, 9, 10.5), (10.5, 12, 10, 11.5), (11.5, 15, 11, 13), (13, 14, 12, 12.5), (12.5, 13, 10, 10.5),
       (10.5, 11, 8, 9), (9, 10, 7, 8), (8, 9, 6, 7)]


def mirror(rows, axis=20.0):
    return [(axis - o, axis - l, axis - h, axis - c) for o, h, l, c in rows]


def test_pdf_example_swing_high_confirmed_at_i_plus_r():
    out = detect_swings(series(PDF))
    assert keys(out) == [("high", 2, 4, 15.0)], keys(out)
    assert out[0].stamp.ts == series(PDF)[2].ts and out[0].stamp.confirmed_ts == series(PDF)[4].ts


def test_final_low_stays_unconfirmed_then_confirms_with_two_more_bars():
    assert all(e.kind is SwingKind.HIGH for e in detect_swings(series(PDF)))
    longer = PDF + [(7, 8.5, 6.5, 8), (8, 9.5, 7, 9)]
    assert ("low", 7, 9, 6.0) in keys(detect_swings(series(longer)))


def test_strict_comparison_rejects_ties_left_and_right():
    tie_right = [(10, 11, 9, 10.5), (10.5, 12, 10, 11.5), (11.5, 14, 11, 13), (13, 14, 12, 12.5), (12.5, 13, 10, 10.5),
                 (10.5, 12, 9.5, 10), (10, 11, 9, 9.5)]
    assert detect_swings(series(tie_right)) == []            # 14 / 14: neither bar is a unique strict pivot
    eq = unresolved_equal_levels(series(tie_right))
    assert [(x.kind.value, x.index, x.tied_with) for x in eq] == [("high", 2, (3,)), ("high", 3, (2,))]


def test_one_tick_difference_is_a_unique_pivot():
    rows = [(10, 11, 9, 10.5), (10.5, 12, 10, 11.5), (11.5, 14, 11, 13), (13, 13.99, 12, 12.5), (12.5, 13, 10, 10.5),
            (10.5, 12, 9.5, 10), (10, 11, 9, 9.5)]
    assert keys(detect_swings(series(rows))) == [("high", 2, 4, 14.0)]
    assert unresolved_equal_levels(series(rows)) == []


def test_window_boundaries_and_configurable_windows():
    rows = [(10, 10.5, 9.5, 10), (10, 11, 9.8, 10.8), (10.8, 12, 10.5, 11.5), (11.5, 15, 11, 14), (14, 13, 12, 12.5)]
    rows[4] = (14, 14.5, 12, 12.5)
    rows += [(12.5, 13, 11.5, 12), (12, 12.5, 11, 11.5), (11.5, 12, 10.5, 11)]
    s = series(rows)
    assert keys(detect_swings(s)) == [("high", 3, 5, 15.0)]
    assert keys(detect_swings(s, SwingConfig(2, 3))) == [("high", 3, 6, 15.0)]
    assert keys(detect_swings(s, SwingConfig(2, 1))) == [("high", 3, 4, 15.0)]
    assert detect_swings(s, SwingConfig(4, 2)) == []                     # only 3 bars left of candle 3
    assert raises(ValueError, SwingConfig, 0, 2) and raises(ValueError, SwingConfig, 2, 0)
    assert raises(ValueError, SwingConfig, 2.0, 2) and raises(ValueError, SwingConfig, True, 2)


def test_equal_level_clusters_are_not_implemented():
    assert raises(NotImplementedError, SwingConfig, 2, 2, "cluster")
    assert raises(NotImplementedError, SwingConfig, 2, 2, "first")


def test_insufficient_left_history_needs_full_window():
    rows = [(14, 14, 12.5, 13), (13, 13, 11, 11.5), (11.5, 11.5, 10, 10.5), (10.5, 10.5, 9.6, 10), (10, 10, 9, 9.5)]
    assert detect_swings(series(rows)) == []                              # bar 0 is highest but has no left window


def test_dual_pivot_and_independent_kinds():
    outside = [(10, 11, 9, 10.5), (10.5, 11.5, 9.5, 11), (11, 13, 8, 9), (9, 12, 8.5, 11.5), (11.5, 12.5, 9, 10)]
    out = detect_swings(series(outside))
    assert keys(out) == [("high", 2, 4, 13.0), ("low", 2, 4, 8.0)], keys(out)
    only_high = [(10, 11, 9, 10.5), (10.5, 11.5, 9.5, 11), (11, 13, 8, 9), (9, 12, 7.5, 11.5), (11.5, 12.5, 9, 10),
                 (10, 11, 9.5, 10.5)]
    assert keys(detect_swings(series(only_high))) == [("high", 2, 4, 13.0), ("low", 3, 5, 7.5)]


def test_high_low_mirror_symmetry():
    a = detect_swings(series(PDF + [(7, 8.5, 6.5, 8), (8, 9.5, 7, 9)]))
    b = detect_swings(series(mirror(PDF + [(7, 8.5, 6.5, 8), (8, 9.5, 7, 9)])))
    flip = {"high": "low", "low": "high"}
    assert sorted((flip[k], i, c) for k, i, c, _ in keys(a)) == sorted((k, i, c) for k, i, c, _ in keys(b))


def test_ids_stable_and_output_deterministic():
    s = series(PDF + [(7, 8.5, 6.5, 8), (8, 9.5, 7, 9)])
    a, b = detect_swings(s), detect_swings(s)
    assert a == b and [e.id for e in a] == ["swing:high:2:fixed-window-strict:L2R2", "swing:low:7:fixed-window-strict:L2R2"]
    assert swing_id(SwingKind.LOW, 7, SwingConfig()) == a[1].id
    assert raises(Exception, setattr, a[0], "price", 1.0)                 # frozen


def test_no_lookahead_and_parity_on_hand_cases():
    for rows in (PDF + [(7, 8.5, 6.5, 8), (8, 9.5, 7, 9)],
                 [(10, 11, 9, 10.5), (10.5, 11.5, 9.5, 11), (11, 13, 8, 9), (9, 12, 8.5, 11.5), (11.5, 12.5, 9, 10)]):
        s = series(rows)
        assert no_lookahead_violations(detect_swings, s) == []
        exp = {(e.kind.value, e.index): e.confirmed_index for e in detect_swings(s)}
        a = replay_audit(s, exp, lambda e: (e.kind.value, e.index), detector=detect_swings, make_stream=SwingStream)
        assert a.ok, a.findings


def test_stream_rejects_out_of_order_candles():
    s = series(PDF)
    st = SwingStream()
    st.on_candle(s[0])
    assert raises(ValueError, st.on_candle, s[2])
    assert raises(TypeError, st.on_candle, (1, 2, 3))


if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
