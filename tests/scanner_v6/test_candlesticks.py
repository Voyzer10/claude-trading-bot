#!/usr/bin/env python3
"""Module C: candlestick formation detection (spec 16.A-16.E, CS-1..CS-6, CK-1..CK-5, CK-8, IR-2, IR-3, OQ-14, OQ-15).

Expected results are INDEPENDENT of scanner_v6.entry.candlesticks:
  * hand-derived fixtures below (each row states the numbers that decide it), and
  * an exact-rational oracle (_oracle, Fractions, written from the spec text) used in randomized property tests.
Fixture configuration is test-only (IR-3 / OQ-15): tick size 0.01 unless a test says otherwise.

    python tests/scanner_v6/test_candlesticks.py   (or: python -m pytest tests/scanner_v6)
"""
import hashlib
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from fractions import Fraction as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import raises, run_main  # noqa: E402

from scanner_v6.data.candle_models import CandleError, CandleSeries  # noqa: E402
from scanner_v6.data.market_config import MarketDataConfig  # noqa: E402
from scanner_v6.entry.candlesticks import (  # noqa: E402
    BEARISH_BIAS, BEARISH_ENGULFING, BULLISH_BIAS, BULLISH_ENGULFING, CLASSIC_DOJI, DETECTED, DOWNTREND, DRAGONFLY_DOJI,
    ENGULFING, EVENING_STAR, GRAVESTONE_DOJI, HAMMER, HAMMER_HANGING_MAN, HANGING_MAN, INVERTED_HAMMER,
    LONG_LEGGED_DOJI, MISSING_TICK_SIZE, MORNING_STAR, NEUTRAL, PATTERN_TYPES, SCORED, SHOOTING_STAR, SIDEWAYS,
    UNCLASSIFIED_SHAPE, UNDETERMINED, UNKNOWN, UNSCORABLE, UPTREND, ZERO_RANGE, ZERO_RANGE_IN_WINDOW,
    CandlestickConfig, CandlestickConfigError, CandlestickStream, PatternEvent, detect_candlestick_patterns,
    pattern_id)

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
INS, TF = "TEST-SYN", "5m"
CFG = MarketDataConfig.from_fixture({"instrument_id": INS, "timeframe_seconds": 300, "tick_size": 0.01})
NO_TICK = MarketDataConfig.from_fixture({"instrument_id": INS, "timeframe_seconds": 300})


def series(rows):
    return CandleSeries.from_rows([(T0 + timedelta(minutes=5 * i), o, h, l, c) for i, (o, h, l, c) in enumerate(rows)],
                                  INS, TF)


def run(rows, market=CFG, config=None):
    return detect_candlestick_patterns(series(rows), INS, TF, market, config)


def r2(x):
    return round(x + 0.0, 2)


def mirror(rows):
    return [(r2(200 - o), r2(200 - l), r2(200 - h), r2(200 - c)) for o, h, l, c in rows]


def ctx(kind):
    """10 context candles (indices 0..9) giving the CS-5 context for a pattern starting at candle 10.
    prev closes / recent closes: UP 99 -> 100 (D = +1.00), DOWN 101 -> 100 (D = -1.00), SIDE 100 -> 100 (D = 0)."""
    prev = {"UP": 99.0, "DOWN": 101.0, "SIDE": 100.0}[kind]
    return [(prev, prev + 0.1, prev - 0.1, prev)] * 5 + [(100.0, 100.1, 99.9, 100.0)] * 5


def at(rep, k):
    """(pattern_type, label, bias) of the events whose END candle is k."""
    return {(p.pattern_type, p.pattern_label, p.bias) for p in rep.patterns if p.end_candle == k}


# ---------------------------------------------------------------- hand-derived single-candle fixtures (R = 1.00)
# (name, (O, H, L, C), context, expected set at candle 10). B = body, UW / LW = wicks, all as fractions of R = 1.00.
UP_SHAPE_IH = {(INVERTED_HAMMER, INVERTED_HAMMER, BULLISH_BIAS)}
UP_SHAPE_SS = {(SHOOTING_STAR, SHOOTING_STAR, BEARISH_BIAS)}
UP_SHAPE_UNC = {(INVERTED_HAMMER, UNCLASSIFIED_SHAPE, BULLISH_BIAS), (SHOOTING_STAR, UNCLASSIFIED_SHAPE, BEARISH_BIAS)}
LO_HAMMER = {(HAMMER_HANGING_MAN, HAMMER, BULLISH_BIAS)}
LO_HANGING = {(HAMMER_HANGING_MAN, HANGING_MAN, BEARISH_BIAS)}
LO_UNC = {(HAMMER_HANGING_MAN, UNCLASSIFIED_SHAPE, UNDETERMINED)}
CL = (CLASSIC_DOJI, CLASSIC_DOJI, NEUTRAL)
LL = (LONG_LEGGED_DOJI, LONG_LEGGED_DOJI, NEUTRAL)
GR = (GRAVESTONE_DOJI, GRAVESTONE_DOJI, BEARISH_BIAS)
DF = (DRAGONFLY_DOJI, DRAGONFLY_DOJI, BULLISH_BIAS)
SINGLE = [
    # Classic Doji
    ("classic_pos", (100.80, 101, 100, 100.85), "SIDE", {CL}),                      # B .05 UW .15 LW .80
    ("classic_neg_no_lower_wick", (100.0, 101, 100, 100.05), "SIDE", {GR} | UP_SHAPE_UNC),   # LW 0 -> not classic
    ("classic_neg_no_upper_wick", (101.0, 101, 100, 100.95), "SIDE", {DF} | LO_UNC),         # UW 0 -> not classic
    ("doji_boundary_body_eq_0.10", (100.40, 101, 100, 100.50), "SIDE", {CL, LL}),    # B .10 inclusive, UW .5 LW .4
    ("doji_just_above_0.10", (100.40, 101, 100, 100.51), "SIDE", set()),             # B .11; no other shape
    # Long-legged Doji
    ("long_legged_pos", (100.50, 101, 100, 100.50), "SIDE", {CL, LL}),
    ("long_legged_boundary_uw_eq_0.25", (100.75, 101, 100, 100.75), "SIDE", {CL, LL}),   # UW .25 inclusive, LW .75
    ("long_legged_neg_uw_0.24", (100.76, 101, 100, 100.76), "SIDE", {CL}),
    # Gravestone Doji
    ("gravestone_pos", (100.05, 101, 100, 100.05), "SIDE", {CL, GR} | UP_SHAPE_UNC),   # B 0 UW .95 LW .05
    ("gravestone_boundary_lw_eq_0.10", (100.10, 101, 100, 100.10), "SIDE", {CL, GR} | UP_SHAPE_UNC),
    ("gravestone_neg_lw_0.11", (100.11, 101, 100, 100.11), "SIDE", {CL}),             # LW .11 > .10 (also shapes)
    # Dragonfly Doji (+ Hammer shape overlap, CS-2)
    ("dragonfly_pos", (100.95, 101, 100, 100.95), "SIDE", {CL, DF} | LO_UNC),
    ("dragonfly_boundary_uw_eq_0.10", (100.90, 101, 100, 100.90), "SIDE", {CL, DF} | LO_UNC),
    ("dragonfly_neg_uw_0.11", (100.89, 101, 100, 100.89), "SIDE", {CL}),
    ("dragonfly_hammer_overlap_downtrend", (100.95, 101, 100, 100.95), "DOWN", {CL, DF} | LO_HAMMER),
    # Inverted Hammer / Shooting Star shape: B .20 UW .75 LW .05
    ("upper_shape_downtrend", (100.05, 101, 100, 100.25), "DOWN", UP_SHAPE_IH),
    ("upper_shape_uptrend", (100.05, 101, 100, 100.25), "UP", UP_SHAPE_SS),
    ("upper_shape_sideways", (100.05, 101, 100, 100.25), "SIDE", UP_SHAPE_UNC),
    ("upper_shape_triple_boundary", (100.10, 101, 100, 100.40), "DOWN", UP_SHAPE_IH),   # B .30 UW .60=2B LW .10
    ("upper_shape_neg_body_0.31", (100.10, 101, 100, 100.41), "DOWN", set()),
    ("upper_shape_neg_lw_0.11", (100.11, 101, 100, 100.31), "DOWN", set()),          # B .20 UW .69 LW .11
    # Hammer / Hanging Man shape: B .20 UW .05 LW .75
    ("lower_shape_downtrend", (100.75, 101, 100, 100.95), "DOWN", LO_HAMMER),
    ("lower_shape_uptrend", (100.75, 101, 100, 100.95), "UP", LO_HANGING),
    ("lower_shape_sideways", (100.75, 101, 100, 100.95), "SIDE", LO_UNC),
    ("lower_shape_triple_boundary", (100.90, 101, 100, 100.60), "UP", LO_HANGING),    # B .30 LW .60 UW .10
    ("lower_shape_neg_uw_0.11", (100.69, 101, 100, 100.89), "DOWN", set()),          # B .20 LW .69 UW .11
    ("lower_shape_neg_dominant_wick", (100.55, 101, 100, 100.90), "DOWN", set()),    # B .35 > .30 small fails
]


def test_single_candle_fixtures():
    for name, cndl, kind, exp in SINGLE:
        rep = run(ctx(kind) + [cndl])
        assert at(rep, 10) == exp, (name, at(rep, 10), exp)


def test_single_candle_fixtures_unknown_context():
    """No history: CS-5 UNKNOWN. Context-dependent shapes get UNCLASSIFIED_SHAPE (CS-1); Dojis are unaffected."""
    swap = {(INVERTED_HAMMER, INVERTED_HAMMER, BULLISH_BIAS): UP_SHAPE_UNC, (SHOOTING_STAR, SHOOTING_STAR, BEARISH_BIAS):
            UP_SHAPE_UNC, (HAMMER_HANGING_MAN, HAMMER, BULLISH_BIAS): LO_UNC,
            (HAMMER_HANGING_MAN, HANGING_MAN, BEARISH_BIAS): LO_UNC}
    for name, cndl, kind, exp in SINGLE:
        e2 = set()
        for x in exp:
            e2 |= swap.get(x, {x})
        rep = run([cndl])
        assert at(rep, 0) == e2, (name, at(rep, 0), e2)
        assert all(p.trend.context == UNKNOWN for p in rep.patterns)


MIRROR = {CL: CL, LL: LL, GR: DF, DF: GR,
          (INVERTED_HAMMER, INVERTED_HAMMER, BULLISH_BIAS): (HAMMER_HANGING_MAN, HANGING_MAN, BEARISH_BIAS),
          (SHOOTING_STAR, SHOOTING_STAR, BEARISH_BIAS): (HAMMER_HANGING_MAN, HAMMER, BULLISH_BIAS),
          (HAMMER_HANGING_MAN, HAMMER, BULLISH_BIAS): (SHOOTING_STAR, SHOOTING_STAR, BEARISH_BIAS),
          (HAMMER_HANGING_MAN, HANGING_MAN, BEARISH_BIAS): (INVERTED_HAMMER, INVERTED_HAMMER, BULLISH_BIAS)}


def test_single_candle_fixtures_mirrored():
    """p -> 200 - p (context mirrored too): Gravestone <-> Dragonfly, upper shape <-> lower shape, labels swap."""
    for name, cndl, kind, exp in SINGLE:
        if any(x[1] == UNCLASSIFIED_SHAPE for x in exp):
            continue                       # unclassified sets differ by design (two families vs one); checked below
        rep = run(mirror(ctx(kind) + [cndl]))
        assert at(rep, 10) == {MIRROR[x] for x in exp}, (name, at(rep, 10))
    rep = run(mirror(ctx("SIDE") + [(100.05, 101, 100, 100.25)]))
    assert at(rep, 10) == LO_UNC
    rep = run(mirror(ctx("SIDE") + [(100.75, 101, 100, 100.95)]))
    assert at(rep, 10) == UP_SHAPE_UNC


# ---------------------------------------------------------------- Engulfing (16.D.7, CS-6, CS-8)
def eng(prev, cur, kind="SIDE"):
    rep = run(ctx(kind) + [prev, cur])
    return [p for p in rep.patterns if p.pattern_type == ENGULFING]


def test_engulfing_bullish_and_bearish_mirrored():
    cases = [  # (prev, cur, expected label or None, why)
        ((100.8, 101.0, 100.0, 100.2), (100.1, 101.0, 100.0, 100.9), BULLISH_ENGULFING, "body covers strictly"),
        ((100.8, 101.0, 100.0, 100.2), (100.2, 100.9, 100.1, 100.8), BULLISH_ENGULFING, "equal bodies (inclusive)"),
        ((100.8, 102.0, 99.0, 100.2), (100.1, 101.0, 100.0, 100.9), BULLISH_ENGULFING, "wicks not engulfed: allowed"),
        ((100.8, 101.0, 100.0, 100.2), (100.3, 101.0, 100.0, 100.8), None, "body low 100.3 > 100.2"),
        ((100.8, 101.0, 100.0, 100.2), (100.2, 101.0, 100.0, 100.79), None, "body high 100.79 < 100.8"),
        ((100.5, 101.0, 100.0, 100.5), (100.1, 101.0, 100.0, 100.9), None, "previous is a Doji (C == O)"),
        ((100.2, 101.0, 100.0, 100.8), (100.1, 101.0, 100.0, 100.9), None, "both bullish"),
        ((100.8, 101.0, 100.0, 100.2), (100.9, 101.0, 100.0, 100.1), None, "both bearish"),
    ]
    for kind in ("SIDE", "UP", "DOWN"):                 # no trend-context condition (CS-6)
        for prev, cur, exp, why in cases:
            got = eng(prev, cur, kind)
            assert [p.pattern_label for p in got] == ([exp] if exp else []), (why, kind)
            mg = run(mirror(ctx(kind) + [prev, cur])).patterns
            mexp = {BULLISH_ENGULFING: BEARISH_ENGULFING, None: None}[exp]
            assert [p.pattern_label for p in mg if p.pattern_type == ENGULFING] == ([mexp] if mexp else []), why
    p = eng((100.8, 102.0, 99.0, 100.2), (100.1, 101.0, 100.0, 100.9))[0]
    assert (p.start_candle, p.end_candle, p.direction, p.bias) == (10, 11, "BULLISH", BULLISH_BIAS)
    assert (p.pattern_high, p.pattern_low) == (102.0, 99.0)                    # CS-8 combined range
    assert p.id == "pattern:%s:%s:10:ENGULFING" % (INS, TF)


def test_engulfing_current_doji_is_not_engulfing():
    assert eng((100.8, 101.0, 100.0, 100.2), (100.5, 101.0, 100.0, 100.5)) == []


# ---------------------------------------------------------------- Morning / Evening Star (16.D.9 / 16.D.10)
A = (101.0, 101.1, 100.1, 100.2)            # R 1.0, B .8 (large bearish), body midpoint 100.6
M = (100.15, 100.3, 100.0, 100.2)           # R .3, B .05 (small)


def star(z, a=A, m=M, kind="SIDE"):
    return run(ctx(kind) + [a, m, z])


def test_morning_star_positive_boundary_negative_and_evening_mirror():
    cases = [
        ((100.2, 101.0, 100.1, 100.9), True, "z B .7/.9 large bullish, close 100.9 > 100.6"),
        ((100.2, 100.65, 100.15, 100.61), True, "close 100.61 just above the midpoint; z B .41/.50"),
        ((100.2, 100.65, 100.15, 100.6), False, "close == midpoint 100.6: not ABOVE (strict)"),
        ((100.2, 101.0, 100.0, 100.7), False, "z B .5/1.0 < .60: not large"),
    ]
    for z, ok, why in cases:
        rep = star(z)
        ms = [p for p in rep.patterns if p.pattern_type == MORNING_STAR]
        assert len(ms) == (1 if ok else 0), why
        rm = run(mirror(ctx("SIDE") + [A, M, z]))
        es = [p for p in rm.patterns if p.pattern_type == EVENING_STAR]
        assert len(es) == (1 if ok else 0), "mirror: " + why
        assert not [p for p in rm.patterns if p.pattern_type == MORNING_STAR]
        if ok:
            p = ms[0]
            assert (p.start_candle, p.end_candle, p.bias, p.pattern_label) == (10, 12, BULLISH_BIAS, MORNING_STAR)
            assert p.id == "pattern:%s:%s:10:MORNING_STAR" % (INS, TF)
            assert (p.pattern_high, p.pattern_low) == (max(A[1], M[1], z[1]), min(A[2], M[2], z[2]))
            assert es[0].bias == BEARISH_BIAS and es[0].start_candle == 10
    big_middle = (100.2, 100.6, 100.0, 100.5)                                # B .3/.6 = .5 > .30
    assert not [p for p in star((100.2, 101.0, 100.1, 100.9), m=big_middle).patterns if p.pattern_type == MORNING_STAR]
    small_first = (100.5, 101.1, 100.1, 100.2)                               # B .3/1.0 < .60
    assert not [p for p in star((100.2, 101.0, 100.1, 100.9), a=small_first).patterns
                if p.pattern_type == MORNING_STAR]
    no_gap_needed = (100.25, 101.0, 100.1, 100.9)                            # opens inside the middle body region
    assert [p for p in star(no_gap_needed).patterns if p.pattern_type == MORNING_STAR]


def test_incomplete_history_multi_candle():
    rep = run([A, M])                       # only 2 candles: no star can be evaluated
    assert not [p for p in rep.patterns if p.pattern_type in (MORNING_STAR, EVENING_STAR)]
    rep = run([(100.1, 101.0, 100.0, 100.9)])            # 1 candle: no Engulfing
    assert not [p for p in rep.patterns if p.pattern_type == ENGULFING]


# ---------------------------------------------------------------- trend context (CS-5, CK-1, CK-3)
def test_trend_context_labels_and_mapping():
    shape = (100.75, 101, 100, 100.95)                    # Hammer / Hanging Man shape
    for kind, ctxv, direction in (("UP", UPTREND, "BULLISH"), ("DOWN", DOWNTREND, "BEARISH"),
                                  ("SIDE", SIDEWAYS, "NEUTRAL")):
        p = [x for x in run(ctx(kind) + [shape]).patterns if x.pattern_type == HAMMER_HANGING_MAN][0]
        assert (p.trend.context, p.trend.direction) == (ctxv, direction)
        assert p.trend.candles == tuple(range(10)) and p.trend.threshold == 2 * 0.01
    p = [x for x in run(ctx("UP")[1:] + [shape]).patterns if x.pattern_type == HAMMER_HANGING_MAN][0]
    assert (p.trend.context, p.trend.direction, p.trend.reason) == (UNKNOWN, "UNKNOWN", "INSUFFICIENT_HISTORY")


def test_trend_threshold_boundary_exact_binary_tick():
    """Tick 0.25 (exact in binary): threshold 0.50. D == 0.50 -> SIDEWAYS; D = 0.75 -> UPTREND; D = -0.50 SIDEWAYS."""
    m = MarketDataConfig.from_fixture({"tick_size": 0.25})
    shape = (100.75, 101, 100, 100.95)
    for recent, exp in ((100.5, SIDEWAYS), (100.75, UPTREND), (99.5, SIDEWAYS), (99.25, DOWNTREND)):
        rows = [(100.0, 100.25, 99.75, 100.0)] * 5 + [(recent, recent + 0.25, recent - 0.25, recent)] * 5 + [shape]
        p = [x for x in run(rows, m).patterns if x.pattern_type == HAMMER_HANGING_MAN][0]
        assert p.trend.context == exp, (recent, p.trend)


def test_trend_threshold_boundary_decimal_tick():
    """Tick 0.01: D == 0.02 exactly (in decimal) -> SIDEWAYS; 0.03 -> UPTREND; -0.02 -> SIDEWAYS; -0.03 -> DOWNTREND.
    In floats mean(100.02) - 100.00 is not exactly 0.02; the CK-1 epsilon keeps the decimal answer (UQ-C3)."""
    shape = (100.75, 101, 100, 100.95)
    for recent, exp in ((100.02, SIDEWAYS), (100.03, UPTREND), (99.98, SIDEWAYS), (99.97, DOWNTREND),
                        (100.01, SIDEWAYS)):
        rows = [(100.0, 100.1, 99.9, 100.0)] * 5 + [(recent, r2(recent + 0.1), r2(recent - 0.1), recent)] * 5 + [shape]
        p = [x for x in run(rows).patterns if x.pattern_type == HAMMER_HANGING_MAN][0]
        assert p.trend.context == exp, (recent, p.trend)


def test_pattern_candles_excluded_from_context():
    """Morning Star at 10..12 with a SIDEWAYS 0..9 history: context uses 0..9 only, although candles 10..12 would make a
    window ending at 12 bearish-to-bullish different."""
    rep = star((100.2, 101.0, 100.1, 100.9), kind="SIDE")
    p = [x for x in rep.patterns if x.pattern_type == MORNING_STAR][0]
    assert p.trend.candles == tuple(range(10)) and p.trend.context == SIDEWAYS and p.trend.d == 0.0
    e = [x for x in run(ctx("UP") + [(100.8, 101.0, 100.0, 100.2), (100.1, 101.0, 100.0, 100.9)]).patterns
         if x.pattern_type == ENGULFING][0]
    assert e.trend.candles == tuple(range(10)) and e.trend.context == UPTREND


# ---------------------------------------------------------------- geometry, UNSCORABLE, invalid input
def test_geometry_values_and_zero_cases():
    rep = run([(100.2, 101.0, 100.0, 100.8), (100.5, 100.5, 100.5, 100.5), (100.5, 100.5, 100.0, 100.5),
               (100.0, 101.0, 100.0, 101.0)])
    g = rep.geometry
    assert abs(g[0].body_ratio - 0.6) < 1e-12 and abs(g[0].upper_ratio - 0.2) < 1e-12 and \
        abs(g[0].lower_ratio - 0.2) < 1e-12 and abs(g[0].close_location - 0.8) < 1e-12 and g[0].status == SCORED
    assert (g[1].status, g[1].reason, g[1].body_ratio, g[1].range) == (UNSCORABLE, ZERO_RANGE, None, 0.0)   # R = 0
    assert g[2].body == 0.0 and g[2].body_ratio == 0.0 and g[2].upper_wick == 0.0                # zero body, zero UW
    assert g[3].upper_wick == 0.0 and g[3].lower_wick == 0.0 and g[3].body_ratio == 1.0           # marubozu: no wicks
    assert not [p for p in rep.patterns if 1 in range(p.start_candle, p.end_candle + 1)]          # R = 0 never used
    ev = [e for e in rep.evaluations if 1 in e.candles]
    assert {e.reason for e in ev} == {ZERO_RANGE, ZERO_RANGE_IN_WINDOW} and all(e.status == UNSCORABLE for e in ev)
    assert {e.pattern_type for e in ev if e.end_candle == 1} == set(PATTERN_TYPES) - {MORNING_STAR, EVENING_STAR}
    assert (DRAGONFLY_DOJI, DRAGONFLY_DOJI, BULLISH_BIAS) in at(rep, 2)   # zero body + zero upper wick


def test_cs4_exact_wick_and_exact_zero_range_adversarial():
    """CS-4: a wick is present iff wick > 0 EXACTLY; 16.B: zero range iff R == 0 EXACTLY. Tick 0.01 -> epsilon 1e-8;
    W = 5e-9 is positive but smaller than the epsilon. The epsilon must neither remove such a wick nor turn such a range
    into ZERO_RANGE. Expectations below hold without any tolerance (exact ratios 0, 1 or 0.5 / 0.5)."""
    eps, W = 0.01 * 0.000001, 5e-9
    cases = [
        # (name, candle, must contain, must not contain)
        ("positive upper wick < eps", (100.5, 100.5 + W, 100.0, 100.5), {CL, DF}, set()),
        ("positive lower wick < eps", (100.5, 101.0, 100.5 - W, 100.5), {CL, GR}, set()),
        ("exact zero upper wick", (100.5, 100.5, 100.0, 100.5), {DF}, {CL}),
        ("exact zero lower wick", (100.5, 101.0, 100.5, 100.5), {GR}, {CL}),
        ("positive range < eps (upper)", (100.0, 100.0 + W, 100.0, 100.0), {GR}, {CL}),
        ("positive range < eps (lower)", (100.0, 100.0, 100.0 - W, 100.0), {DF}, {CL}),
    ]
    for name, cndl, must, must_not in cases:
        rows = [cndl]
        rep = run(rows)
        g = rep.geometry[0]
        assert g.status == SCORED and g.reason is None and g.body_ratio is not None, (name, g)
        assert not rep.evaluations, (name, rep.evaluations)                      # nothing UNSCORABLE
        got = at(rep, 0)
        assert must <= got and not (must_not & got), (name, got)
        assert [(c.open, c.high, c.low, c.close) for c in series(rows)] == [tuple(map(float, cndl))]   # OHLC intact
    g = run([(100.5, 100.5 + W, 100.0, 100.5)]).geometry[0]
    assert 0.0 < g.upper_wick < eps and 0.0 < W < eps
    g = run([(100.0, 100.0 + W, 100.0, 100.0)]).geometry[0]
    assert 0.0 < g.range < eps and g.upper_ratio == 1.0 and g.body_ratio == 0.0 and g.lower_ratio == 0.0
    rep = run([(100.0, 100.0, 100.0, 100.0)])                                    # exact zero range
    assert (rep.geometry[0].status, rep.geometry[0].reason, rep.geometry[0].range) == (UNSCORABLE, ZERO_RANGE, 0.0)
    assert rep.patterns == [] and {e.reason for e in rep.evaluations} == {ZERO_RANGE}
    # a sub-epsilon range next to normal candles: multi-candle windows are evaluated, not ZERO_RANGE_IN_WINDOW
    rep = run([(100.8, 101.0, 100.0, 100.2), (100.0, 100.0 + W, 100.0, 100.0), (100.1, 101.0, 100.0, 100.9)])
    assert not [e for e in rep.evaluations if e.reason in (ZERO_RANGE, ZERO_RANGE_IN_WINDOW)]


SINGLE_CANDLE_TYPES = {CLASSIC_DOJI, GRAVESTONE_DOJI, LONG_LEGGED_DOJI, INVERTED_HAMMER, DRAGONFLY_DOJI,
                       HAMMER_HANGING_MAN, SHOOTING_STAR}


def _exact(rep, k):
    """Exact (type, label, bias, status, context, context_qualified) tuples of the events ending at k."""
    return {(p.pattern_type, p.pattern_label, p.bias, p.status, p.trend.context, p.context_qualified)
            for p in rep.patterns if p.end_candle == k}


def _unk(s):
    """Expected tuples for a lone candle (index 0): context UNKNOWN (insufficient history), never context-qualified."""
    return {(t, lab, b, DETECTED, UNKNOWN, False) for t, lab, b in s}


def test_cs4_16b_adversarial_exact_label_sets():
    """Review items 1-6: EXACT equality of the full event set (type, label, bias, status, context), not containment.
    Lone candle -> context UNKNOWN. Tick 0.01 -> eps 1e-8; W = 5e-9 is positive but below the epsilon.
    Hand derivation (R, B, UW, LW; thresholds of 16.D compared with +-eps):
      1 (100.5, 100.5+W, 100, 100.5): R .5+W B 0 UW W LW .5  -> Classic (both wicks > 0), Dragonfly (LW >= .6R, UW <= .1R),
                                                              lower shape (LW >= 2B, UW <= .1R) -> HHM UNCLASSIFIED
      2 mirror of 1 (UW .5, LW W)                            -> Classic, Gravestone, upper shape -> IH + SS UNCLASSIFIED
      3 (100.5, 100.5, 100, 100.5): UW exactly 0              -> NOT Classic; Dragonfly, HHM UNCLASSIFIED
      4 mirror of 3: LW exactly 0                             -> NOT Classic; Gravestone, IH + SS UNCLASSIFIED
      5 (100, 100+W, 100, 100): R = W > 0 (scored), LW exactly 0 -> NOT Classic (LW absent). With R < eps every inclusive
        ratio threshold holds within the tolerance (spec 17.T 'consequence noted'): Gravestone, Long-legged, Dragonfly,
        IH + SS UNCLASSIFIED, HHM UNCLASSIFIED
      6 mirror of 5 (UW exactly 0)                            -> same set as 5 by symmetry"""
    W = 5e-9
    UPU = {(INVERTED_HAMMER, UNCLASSIFIED_SHAPE, BULLISH_BIAS), (SHOOTING_STAR, UNCLASSIFIED_SHAPE, BEARISH_BIAS)}
    LOU = {(HAMMER_HANGING_MAN, UNCLASSIFIED_SHAPE, UNDETERMINED)}
    sub_eps_range = {GR, LL, DF} | UPU | LOU
    cases = [
        ("1 positive upper wick < eps", (100.5, 100.5 + W, 100.0, 100.5), {CL, DF} | LOU),
        ("2 positive lower wick < eps", (100.5, 101.0, 100.5 - W, 100.5), {CL, GR} | UPU),
        ("3 exact zero upper wick", (100.5, 100.5, 100.0, 100.5), {DF} | LOU),
        ("4 exact zero lower wick", (100.5, 101.0, 100.5, 100.5), {GR} | UPU),
        ("6a positive range < eps (upper)", (100.0, 100.0 + W, 100.0, 100.0), sub_eps_range),
        ("6b positive range < eps (lower)", (100.0, 100.0, 100.0 - W, 100.0), sub_eps_range),
    ]
    for name, cndl, expected in cases:
        rep = run([cndl])
        g = rep.geometry[0]
        assert (g.status, g.reason) == (SCORED, None), (name, g)
        assert rep.evaluations == [], (name, rep.evaluations)
        assert _exact(rep, 0) == _unk(expected), (name, _exact(rep, 0) ^ _unk(expected))
        assert [(c.open, c.high, c.low, c.close) for c in series([cndl])] == [cndl]           # OHLC untouched
    # 5: exact zero range -> UNSCORABLE / ZERO_RANGE for every single-candle family, no pattern, no ratio
    rep = run([(100.0, 100.0, 100.0, 100.0)])
    g = rep.geometry[0]
    assert (g.status, g.reason, g.range, g.body_ratio, g.upper_ratio, g.lower_ratio) == \
        (UNSCORABLE, ZERO_RANGE, 0.0, None, None, None)
    assert rep.patterns == []
    assert sorted((e.end_candle, e.pattern_type, e.status, e.reason, e.candles) for e in rep.evaluations) == \
        sorted((0, t, UNSCORABLE, ZERO_RANGE, (0,)) for t in SINGLE_CANDLE_TYPES)
    # exact zero range inside a multi-candle window -> ZERO_RANGE_IN_WINDOW for that window only
    rep = run([(100.6, 101.0, 100.0, 100.4), (100.0, 100.0, 100.0, 100.0)])
    assert sorted((e.pattern_type, e.reason) for e in rep.evaluations) == \
        sorted([(t, ZERO_RANGE) for t in SINGLE_CANDLE_TYPES] + [(ENGULFING, ZERO_RANGE_IN_WINDOW)])


def test_normal_range_and_normal_wick_exact():
    """Review item 7: ordinary tick-grid candles (R = 1.00, wicks 0.05 .. 0.80) give the exact hand-derived sets with
    context and qualification, both directions."""
    cases = [
        ("classic", (100.80, 101, 100, 100.85), "SIDE", {(CLASSIC_DOJI, CLASSIC_DOJI, NEUTRAL, SIDEWAYS, False)}),
        ("hammer", (100.75, 101, 100, 100.95), "DOWN", {(HAMMER_HANGING_MAN, HAMMER, BULLISH_BIAS, DOWNTREND, True)}),
        ("hanging", (100.75, 101, 100, 100.95), "UP", {(HAMMER_HANGING_MAN, HANGING_MAN, BEARISH_BIAS, UPTREND, True)}),
        ("inv hammer", (100.05, 101, 100, 100.25), "DOWN", {(INVERTED_HAMMER, INVERTED_HAMMER, BULLISH_BIAS, DOWNTREND, True)}),
        ("shooting", (100.05, 101, 100, 100.25), "UP", {(SHOOTING_STAR, SHOOTING_STAR, BEARISH_BIAS, UPTREND, True)}),
        ("plain body", (100.20, 101, 100, 100.80), "SIDE", set()),            # B .60 UW .20 LW .20: no family
    ]
    for name, cndl, kind, expected in cases:
        rows = ctx(kind) + [cndl]
        rep = run(rows)
        got = {(p.pattern_type, p.pattern_label, p.bias, p.trend.context, p.context_qualified)
               for p in rep.patterns if p.end_candle == 10}
        assert got == expected, (name, got)
        assert all(p.status == DETECTED for p in rep.patterns)
        assert rep.geometry[10].status == SCORED and rep.evaluations == []


def test_ck1_ck8_epsilon_boundaries_unchanged():
    """Review item 8: the CK-1 / CK-8 epsilon (1e-8 at tick 0.01) is still applied to threshold, candle-colour,
    Engulfing body-boundary and Star-midpoint comparisons (trend threshold: test_trend_threshold_boundary_*).
    In each pair the first value lies within the tolerance (5e-9), the second beyond it (2e-8)."""
    inside, outside = 5e-9, 2e-8
    # threshold (Doji B <= 0.10 R, inclusive): B = .10 + d, UW ~.5, LW .4
    assert _exact(run([(100.40, 101.0, 100.0, 100.50 + inside)]), 0) == _unk({CL, LL})
    assert _exact(run([(100.40, 101.0, 100.0, 100.50 + outside)]), 0) == set()
    # candle colour (C < O - eps): previous candle 'bearish' by only d; current bullish candle covers it
    cur = (100.40, 101.0, 100.0, 100.60)
    ENG_BULL = (ENGULFING, BULLISH_ENGULFING, BULLISH_BIAS)
    assert _exact(run([(100.50, 101.0, 100.0, 100.50 - inside), cur]), 1) == set()          # not bearish within eps
    assert _exact(run([(100.50, 101.0, 100.0, 100.50 - outside), cur]), 1) == _unk({ENG_BULL})
    # mirror (C > O + eps): previous candle 'bullish' by only d; current bearish candle covers it
    cur_b = (100.60, 101.0, 100.0, 100.40)
    ENG_BEAR = (ENGULFING, BEARISH_ENGULFING, BEARISH_BIAS)
    assert _exact(run([(100.50, 101.0, 100.0, 100.50 + inside), cur_b]), 1) == set()        # not bullish within eps
    assert _exact(run([(100.50, 101.0, 100.0, 100.50 + outside), cur_b]), 1) == _unk({ENG_BEAR})
    # Engulfing body boundary (inclusive, CS-6): current lower body edge above the previous one by d
    prev = (100.60, 101.0, 100.0, 100.40)
    assert _exact(run([prev, (100.40 + inside, 101.0, 100.0, 100.70)]), 1) == _unk({ENG_BULL})
    assert _exact(run([prev, (100.40 + outside, 101.0, 100.0, 100.70)]), 1) == set()
    # Star midpoint (strict, close > mid + eps): mid of (100.9 -> 100.1) is 100.5
    a, m = (100.90, 101.0, 100.0, 100.10), (100.05, 100.30, 100.0, 100.10)
    MS = (MORNING_STAR, MORNING_STAR, BULLISH_BIAS)
    assert _exact(run([a, m, (99.95, 100.60, 99.90, 100.50 + inside)]), 2) == set()           # not above mid + eps
    assert _exact(run([a, m, (99.95, 100.60, 99.90, 100.50 + outside)]), 2) == _unk({MS})


def test_missing_tick_size_is_unscorable_with_no_fallback():
    rows = ctx("DOWN") + [(100.75, 101, 100, 100.95), (100.8, 101.0, 100.0, 100.2), (100.1, 101.0, 100.0, 100.9)]
    rep = run(rows, NO_TICK)
    assert rep.patterns == [] and rep.tick_size is None
    assert [(e.end_candle, e.status, e.reason) for e in rep.evaluations] == [(k, UNSCORABLE, MISSING_TICK_SIZE)
                                                                           for k in range(len(rows))]
    assert all(g.status == UNSCORABLE and g.reason == MISSING_TICK_SIZE and g.body_ratio is None for g in rep.geometry)
    st = CandlestickStream(INS, TF, NO_TICK)
    assert st.trend(10).context == UNKNOWN and st.trend(10).reason == MISSING_TICK_SIZE


def test_invalid_ohlc_and_bad_inputs_rejected():
    raises(CandleError, series, [(100.0, 99.0, 100.5, 100.0)])           # high < low
    raises(CandleError, series, [(100.0, 101.0, 100.0, 102.0)])          # close above high
    raises(CandleError, series, [(float("nan"), 101.0, 100.0, 100.5)])
    st = CandlestickStream(INS, TF, CFG)
    s = series([(100.0, 101.0, 99.0, 100.5), (100.0, 101.0, 99.0, 100.5)])
    raises(ValueError, st.on_candle, s[1])                                  # out of order
    raises(TypeError, st.on_candle, (100.0, 101.0, 99.0, 100.5))
    raises(CandlestickConfigError, CandlestickStream, "", TF, CFG)
    raises(CandlestickConfigError, CandlestickStream, "A:B", TF, CFG)
    raises(CandlestickConfigError, CandlestickStream, INS, TF, {"tick_size": 0.01})
    raises(CandlestickConfigError, CandlestickConfig, doji_body_max=-0.1)
    raises(CandlestickConfigError, CandlestickConfig, recent_window=0)
    raises(ValueError, pattern_id, INS, TF, 3, "HAMMER")                    # a label is never a pattern type
    raises(ValueError, pattern_id, INS, TF, 3, UNCLASSIFIED_SHAPE)


def test_thresholds_configurable_per_instrument():
    shape = (100.40, 101, 100, 100.51)                                       # B .11: not a Doji at the baseline
    assert at(run(ctx("SIDE") + [shape]), 10) == set()
    wide = CandlestickConfig(doji_body_max=0.12)
    assert (CLASSIC_DOJI, CLASSIC_DOJI, NEUTRAL) in at(run(ctx("SIDE") + [shape], config=wide), 10)
    assert CandlestickConfig() == CandlestickConfig(0.10, 0.30, 0.60, 2.0, 0.10, 0.60, 0.10, 0.25, 0.60, 0.10, 0.000001,
                                                    2.0, 5, 5)


# ---------------------------------------------------------------- overlap (CS-2), ids (CK-2 / OQ-14), schema
def test_overlap_no_suppression_and_ids():
    rep = run(ctx("DOWN") + [(100.95, 101, 100, 100.95)])
    ps = [p for p in rep.patterns if p.end_candle == 10]
    assert [p.pattern_type for p in ps] == [CLASSIC_DOJI, DRAGONFLY_DOJI, HAMMER_HANGING_MAN]   # 16.A order
    assert [p.id for p in ps] == ["pattern:TEST-SYN:5m:10:%s" % t for t in (CLASSIC_DOJI, DRAGONFLY_DOJI,
                                                                             HAMMER_HANGING_MAN)]
    assert len({p.id for p in rep.patterns}) == len(rep.patterns)
    h = ps[2]
    assert (h.pattern_label, h.bias, h.direction, h.context_qualified, h.status) == (HAMMER, BULLISH_BIAS, "BULLISH",
                                                                                     True, DETECTED)
    assert (h.stamp.index, h.stamp.confirmed_index, h.stamp.ts) == (10, 10, T0 + timedelta(minutes=50))
    assert (h.instrument, h.timeframe, h.start_candle, h.end_candle, h.evaluation_status) == (INS, TF, 10, 10, SCORED)
    assert h.geometry[0].index == 10 and h.reasons[0] == "16.D.6"
    raises(Exception, PatternEvent, "pattern:X:5m:1:CLASSIC_DOJI", h.stamp, instrument="X", timeframe="5m",
           pattern_type=CLASSIC_DOJI, start_candle=1, end_candle=1, status="CONFIRMED")         # DETECTED only


def test_no_buy_sell_or_confirmation_fields():
    import scanner_v6.entry.candlesticks as m
    src = open(m.__file__).read()
    for word in ("place_order", "execute_order", "\"BUY\"", "\"SELL\"", "CONFIRMED", "EXPIRED", "INVALIDATED"):
        assert word not in src, word
    rep = run(ctx("DOWN") + [(100.95, 101, 100, 100.95)])
    assert {p.status for p in rep.patterns} == {DETECTED}


# ---------------------------------------------------------------- determinism, parity, replay, no look-ahead
def rand_rows(seed, n, tick_cents=1):
    """OHLC on the tick grid (integer cents), shaped to hit every family often."""
    rnd = random.Random(seed)
    rows, c = [], 10000
    for _ in range(n):
        r = rnd.choice([0, 1, 2, 5, 10, 20, 40, 50, 100, 100, 100])
        kind = rnd.random()
        lo = c - rnd.randint(0, max(r, 1))
        hi = lo + r
        if r == 0:
            o = cl = lo
        elif kind < 0.25:                                   # doji-like
            o = rnd.randint(lo, hi); cl = min(hi, max(lo, o + rnd.choice([-1, 0, 0, 1]) * rnd.randint(0, r // 10 + 1)))
        elif kind < 0.5:                                    # hammer / shooting-star-like
            b = rnd.randint(0, r * 3 // 10 + 1)
            if rnd.random() < 0.5:
                o = hi - rnd.randint(0, r // 10 + 1); cl = o - b
            else:
                o = lo + rnd.randint(0, r // 10 + 1); cl = o + b
            o = min(hi, max(lo, o)); cl = min(hi, max(lo, cl))
        else:                                               # anything
            o, cl = rnd.randint(lo, hi), rnd.randint(lo, hi)
        if rnd.random() < 0.5:
            o, cl = cl, o
        rows.append((o * tick_cents, hi * tick_cents, lo * tick_cents, cl * tick_cents))
        c = cl
    return rows


def as_prices(rows):
    return [(o / 100, h / 100, l / 100, c / 100) for o, h, l, c in rows]


def test_determinism_stream_batch_parity_prefix_replay_no_lookahead():
    for seed in (1, 2, 3):
        rows = as_prices(rand_rows(seed, 160))
        s = series(rows)
        before = hashlib.sha256(repr([(c.open, c.high, c.low, c.close, c.ts) for c in s]).encode()).hexdigest()
        a = detect_candlestick_patterns(s, INS, TF, CFG)
        b = detect_candlestick_patterns(s, INS, TF, CFG)
        assert a.patterns == b.patterns and [p.id for p in a.patterns] == [p.id for p in b.patterns]
        st = CandlestickStream(INS, TF, CFG)
        streamed = []
        for c in s:
            streamed += st.on_candle(c)
        assert streamed == a.patterns and st.evaluations == a.evaluations
        for k in range(0, len(s), 7):                                     # prefix replay
            pk = detect_candlestick_patterns(s.upto(k), INS, TF, CFG).patterns
            assert pk == [p for p in a.patterns if p.end_candle <= k], k
        k = 80                                                             # future candles changed -> past unchanged
        alt = series(rows[:k + 1] + as_prices(rand_rows(seed + 100, 79)))
        assert [p for p in detect_candlestick_patterns(alt, INS, TF, CFG).patterns if p.end_candle <= k] == \
            [p for p in a.patterns if p.end_candle <= k]
        after = hashlib.sha256(repr([(c.open, c.high, c.low, c.close, c.ts) for c in s]).encode()).hexdigest()
        assert before == after and [(c.open, c.high, c.low, c.close) for c in s] == [tuple(map(float, r)) for r in rows]
        assert all(p.stamp.confirmed_index == p.end_candle for p in a.patterns)


# ---------------------------------------------------------------- exact-rational oracle (spec text, no implementation)
def _oracle(rows_cents, tick_cents):
    """All (start, end, type, label, bias, context) for rows in integer cents, computed with exact Fractions."""
    T = F(1, 10)
    out, n = set(), len(rows_cents)
    g = []
    for o, h, l, c in rows_cents:
        R, B = h - l, abs(c - o)
        g.append(None if R == 0 else (F(R), F(B), F(h - max(o, c)), F(min(o, c) - l)))

    def context(s):
        if s < 10:
            return UNKNOWN
        d = F(sum(r[3] for r in rows_cents[s - 5:s]) - sum(r[3] for r in rows_cents[s - 10:s - 5]), 5)
        return UPTREND if d > 2 * tick_cents else DOWNTREND if d < -2 * tick_cents else SIDEWAYS

    for k in range(n):
        if g[k] is not None:
            R, B, UW, LW = g[k]
            doji = B <= T * R
            small = B <= 3 * T * R
            cx = context(k)
            if doji and UW > 0 and LW > 0:
                out.add((k, k, CLASSIC_DOJI, CLASSIC_DOJI, NEUTRAL, cx))
            if doji and UW >= 6 * T * R and LW <= T * R:
                out.add((k, k, GRAVESTONE_DOJI, GRAVESTONE_DOJI, BEARISH_BIAS, cx))
            if doji and UW >= R / 4 and LW >= R / 4:
                out.add((k, k, LONG_LEGGED_DOJI, LONG_LEGGED_DOJI, NEUTRAL, cx))
            if doji and LW >= 6 * T * R and UW <= T * R:
                out.add((k, k, DRAGONFLY_DOJI, DRAGONFLY_DOJI, BULLISH_BIAS, cx))
            if small and UW >= 2 * B and LW <= T * R:
                if cx == DOWNTREND:
                    out.add((k, k, INVERTED_HAMMER, INVERTED_HAMMER, BULLISH_BIAS, cx))
                elif cx == UPTREND:
                    out.add((k, k, SHOOTING_STAR, SHOOTING_STAR, BEARISH_BIAS, cx))
                else:
                    out.add((k, k, INVERTED_HAMMER, UNCLASSIFIED_SHAPE, BULLISH_BIAS, cx))
                    out.add((k, k, SHOOTING_STAR, UNCLASSIFIED_SHAPE, BEARISH_BIAS, cx))
            if small and LW >= 2 * B and UW <= T * R:
                lab, bias = {DOWNTREND: (HAMMER, BULLISH_BIAS), UPTREND: (HANGING_MAN, BEARISH_BIAS)}.get(
                    cx, (UNCLASSIFIED_SHAPE, UNDETERMINED))
                out.add((k, k, HAMMER_HANGING_MAN, lab, bias, cx))
        if k >= 1 and g[k] is not None and g[k - 1] is not None:
            (po, _, _, pc), (co, _, _, cc) = rows_cents[k - 1], rows_cents[k]
            covers = min(co, cc) <= min(po, pc) and max(co, cc) >= max(po, pc)
            if covers and pc < po and cc > co:
                out.add((k - 1, k, ENGULFING, BULLISH_ENGULFING, BULLISH_BIAS, context(k - 1)))
            if covers and pc > po and cc < co:
                out.add((k - 1, k, ENGULFING, BEARISH_ENGULFING, BEARISH_BIAS, context(k - 1)))
        if k >= 2 and all(g[i] is not None for i in (k - 2, k - 1, k)):
            a, m, z = rows_cents[k - 2], rows_cents[k - 1], rows_cents[k]
            large = lambda i: g[i][1] >= 6 * T * g[i][0]
            mid = F(a[0] + a[3], 2)
            if large(k - 2) and a[3] < a[0] and g[k - 1][1] <= 3 * T * g[k - 1][0] and large(k) and z[3] > z[0] \
                    and z[3] > mid:
                out.add((k - 2, k, MORNING_STAR, MORNING_STAR, BULLISH_BIAS, context(k - 2)))
            if large(k - 2) and a[3] > a[0] and g[k - 1][1] <= 3 * T * g[k - 1][0] and large(k) and z[3] < z[0] \
                    and z[3] < mid:
                out.add((k - 2, k, EVENING_STAR, EVENING_STAR, BEARISH_BIAS, context(k - 2)))
    return out


def test_randomized_against_exact_rational_oracle():
    """Prices on the 0.01 grid: exact rational comparisons are the intended outcomes, so float + CK-1 epsilon must
    reproduce them exactly, including every boundary the generator hits (inclusive and strict)."""
    total, per_type = 0, {}
    for seed in range(40):
        rc = rand_rows(seed, 250)
        rep = run(as_prices(rc))
        got = {(p.start_candle, p.end_candle, p.pattern_type, p.pattern_label, p.bias, p.trend.context)
               for p in rep.patterns}
        exp = _oracle(rc, 1)
        assert got == exp, (seed, sorted(got - exp)[:5], sorted(exp - got)[:5])
        total += len(exp)
        for x in exp:
            per_type[x[2]] = per_type.get(x[2], 0) + 1
    assert set(per_type) == set(PATTERN_TYPES), per_type        # every family exercised
    assert total > 5000


def test_randomized_mirror_symmetry():
    swap = {CLASSIC_DOJI: CLASSIC_DOJI, LONG_LEGGED_DOJI: LONG_LEGGED_DOJI, GRAVESTONE_DOJI: DRAGONFLY_DOJI,
            DRAGONFLY_DOJI: GRAVESTONE_DOJI, MORNING_STAR: EVENING_STAR, EVENING_STAR: MORNING_STAR,
            ENGULFING: ENGULFING}
    for seed in range(10):
        rc = rand_rows(seed, 200)
        a = run(as_prices(rc)).patterns
        b = run(mirror(as_prices(rc))).patterns
        key = lambda p: (p.start_candle, p.end_candle, p.pattern_type)
        sa = {key(p) for p in a if p.pattern_type in swap}
        sb = {(s, e, swap[t]) for s, e, t in (key(p) for p in b if p.pattern_type in swap)}
        assert sa == sb, seed


if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
