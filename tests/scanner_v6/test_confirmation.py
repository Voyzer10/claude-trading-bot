#!/usr/bin/env python3
"""Module D: sweep-to-pattern association, confirmation / expiry / invalidation, setup lifecycle (spec 16.F, 16.G,
CS-7..CS-10, CK-2, CK-6, CK-7, CK-8, CK-10..CK-12, CK-17, CK-18, OQ-2, OQ-3, OQ-5, MB-3, MD-1..MD-4).

Expected results are INDEPENDENT of scanner_v6.entry.confirmation: every fixture is hand-built and every expectation is
written out below with the numbers that decide it. Each scenario runs as BUY and as the mirrored SELL (price -> 200 -
price), which maps SSL <-> BSL and bullish <-> bearish and keeps every candle index.

Fixture: BASE reproduces the controlled CHoCH -> BOS -> SSL sweep path (CHoCH@33, REVERSAL_CONFIRMING BOS@39, SSL sweep
group sweep:SSL:47 of pool swing:low:36 @ 115.40; protected low 115.40 from 39). Candles 48.. are scenario-specific and
keep every close >= 115.41 (no CHoCH, no bearish BOS) unless a test says otherwise. Tick 0.01 -> eps 1e-8.
Sweep window: candles 48..52 (CS-9 / CK-6). Each pattern's confirmation window: end+1..end+3 (CS-7).

    python tests/scanner_v6/test_confirmation.py   (or: python -m pytest tests/scanner_v6)
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import raises, run_main  # noqa: E402

from scanner_v6.data.candle_models import Candle, CandleSeries  # noqa: E402
from scanner_v6.data.market_config import MarketDataConfig  # noqa: E402
from scanner_v6.engine import no_lookahead_violations  # noqa: E402
from scanner_v6.entry.confirmation import (  # noqa: E402
    ALL_PATTERNS_EXPIRED, ALL_PATTERNS_INVALIDATED, BIAS_MISMATCH, BOS_CONFIRMED, CHOCH_DETECTED, CONFIRMATION_UNSCORABLE,
    CONFIRMED, DATA_INTERRUPTED, DATA_RESUMED, ENTERED, EXPIRED, INVALIDATED, MIXED_EXPIRED_INVALIDATED, NO_TRADE,
    NO_QUALIFYING_PATTERN, NON_DIRECTIONAL_BIAS, NORMAL, PATTERN_DETECTED, SETUP_ALREADY_CONFIRMED, STOPPED_OUT,
    SWEEP_CANDLE_IN_PATTERN, SWEEP_DETECTED, TARGET_HIT, ConfirmationStream, LifecycleError, SetupRecord, Transition,
    _advance, _mdl_order, analyze_confirmations, confirmation_id, detect_confirmations, setup_id)
from scanner_v6.liquidity import setup_sweep as B  # noqa: E402

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
TF = "5m"
EPS = 0.01 * 0.000001


def r2(x):
    return round(x + 1e-9, 2)


# ---------------------------------------------------------------- BASE path (independent copy of the controlled builder)
def _leg(rows, cur, n, target):
    start = cur
    for j in range(1, n + 1):
        o = cur
        cl = r2(start + (target - start) * j / n)
        h, l = (cl + 0.10, o - 0.03) if cl >= o else (o + 0.03, cl - 0.10)
        rows.append((r2(o), r2(h), r2(l), r2(cl)))
        cur = cl
    return cur


def _base():
    rows, c = [], 120.00
    for n, t in ((4, 121.0), (6, 116.0), (4, 118.0), (5, 114.0), (4, 116.5), (5, 112.0), (6, 117.5), (3, 115.5),
                 (4, 119.0), (2, 119.6), (4, 116.0)):
        c = _leg(rows, c, n, t)
    P = min(x[2] for x in rows[-13:-6])                     # pullback low 115.40 (swing 36)
    rows.append((r2(c), r2(c + 0.03), r2(P - 0.12), r2(P + 0.20)))  # 47: SSL sweep (low 115.28, close 115.60)
    return rows


BASE = _base()
S = 47                                                      # sweep candle

# ---------------------------------------------------------------- hand-designed post-sweep candles (BUY world)
# F  filler   O 116.00 H 116.25 L 115.95 C 116.20: R .30 B .20 (.67), UW .05 LW .05 -> no family
# E1/E2      Bullish Engulfing pair: bear (116.20 116.25 115.95 116.00) then bull (115.98 116.35 115.93 116.30)
#            bull body [115.98, 116.30] covers [116.00, 116.20]; pattern_high 116.35, pattern_low 115.93 (CS-8)
# CU  confirms E: close 116.45 > 116.35 + eps (O 116.20 H 116.50 L 116.15; R .35 B .25, no family)
# IV  invalidates E: close 115.85 < 115.93 - eps (O 116.10 H 116.15 L 115.80; R .35 B .25, no family, no engulf)
F = (116.00, 116.25, 115.95, 116.20)
E_BEAR = (116.20, 116.25, 115.95, 116.00)
E_BULL = (115.98, 116.35, 115.93, 116.30)
E_HIGH, E_LOW = 116.35, 115.93
CU = (116.20, 116.50, 116.15, 116.45)
IV = (116.10, 116.15, 115.80, 115.85)


def mirror(rows):
    return [(r2(200 - o), r2(200 - l), r2(200 - h), r2(200 - c)) for o, h, l, c in rows]


GAP = timedelta(minutes=60)                                 # a genuinely missing interval (F-D2 tests)
TFD = timedelta(minutes=5)                                  # the 5m timeframe as configured in market()


def series(rows, ins, gap_after=None):
    """gap_after: candles after this index open GAP later (a real data gap between gap_after and gap_after + 1)."""
    sh = lambda i: GAP if gap_after is not None and i > gap_after else timedelta(0)
    return CandleSeries.from_rows([(T0 + timedelta(minutes=5 * i) + sh(i), o, h, l, c)
                                   for i, (o, h, l, c) in enumerate(rows)], ins, TF)


def market(ins, tick=0.01):
    d = {"instrument_id": ins, "timeframe_seconds": 300}
    if tick is not None:
        d["tick_size"] = tick
    return MarketDataConfig.from_fixture(d)


def run(post, side="BUY", tick=0.01, data_events=(), gap_after=None):
    """Run BASE + post as BUY, or the mirror as SELL. Returns (report, ids) with ids for that side."""
    ins = "TEST-%s" % side
    rows = BASE + list(post)
    if side == "SELL":
        rows = mirror(rows)
    rep = analyze_confirmations(series(rows, ins, gap_after), ins, TF, market(ins, tick), data_events=data_events)
    sweep = "sweep:%s:%d" % ("SSL" if side == "BUY" else "BSL", S)
    return rep, dict(ins=ins, sweep=sweep, side=side, pat=lambda st, t="ENGULFING": "pattern:%s:5m:%d:%s" % (ins, st, t),
                     bull=side == "BUY")


def only_setup(rep, ids):
    assert len(rep.setups) == 1, [(s.group_id, s.status) for s in rep.setups]
    s = rep.setups[0]
    assert s.group_id == ids["sweep"] and s.sweep_index == S and s.setup_side == ids["side"]
    return s


def path(s):
    return [(t.status, t.index) for t in s.history]


def pstates(rep):
    return {p.pattern_id: (p.status, p.closed_index) for p in rep.pattern_states}


def c_patterns(post, side="BUY", lo=S, hi=None):
    """(type, label, start, end) of Module C events with end in [lo, hi] for the same rows (detection guard)."""
    from scanner_v6.entry.candlesticks import detect_candlestick_patterns
    ins = "TEST-%s" % side
    rows = BASE + list(post)
    if side == "SELL":
        rows = mirror(rows)
    hi = len(rows) - 1 if hi is None else hi
    rep = detect_candlestick_patterns(series(rows, ins), ins, TF, market(ins))
    return sorted((p.pattern_type, p.pattern_label, p.start_candle, p.end_candle) for p in rep.patterns
                  if lo <= p.end_candle <= hi)


ENG_BULL = ("ENGULFING", "BULLISH_ENGULFING")
ENG_BEAR = ("ENGULFING", "BEARISH_ENGULFING")


def both(fn):
    for side in ("BUY", "SELL"):
        fn(side)


# ---------------------------------------------------------------- base guard
def test_base_path_reaches_the_sweep_candidate():
    for side in ("BUY", "SELL"):
        rep, ids = run([F] * 6, side)
        s = only_setup(rep, ids)
        d = "bullish" if side == "BUY" else "bearish"
        k = "high" if side == "BUY" else "low"
        assert s.bos_id == "bos:%s:swing:%s:33:fixed-window-strict:L2R2" % (d, k)
        assert s.choch_id == "choch:%s:swing:%s:22:fixed-window-strict:L2R2" % (d, k)
        assert path(s)[:3] == [(CHOCH_DETECTED, 33), (BOS_CONFIRMED, 39), (SWEEP_DETECTED, 47)]   # MD-4 original indices
        assert [t.ts for t in s.history[:3]] == [T0 + timedelta(minutes=5 * i) for i in (33, 39, 47)]


# ---------------------------------------------------------------- confirmation on each of the next three candles
def test_confirmation_on_each_of_the_three_candles_mirrored():
    for side in ("BUY", "SELL"):
        for j in range(3):                                   # CU at 50, 51 or 52
            post = [E_BEAR, E_BULL] + [F] * j + [CU] + [F] * 3
            assert c_patterns(post, side, S, S + 5) == [(ENG_BULL if side == "BUY" else ENG_BEAR) + (48, 49)]
            rep, ids = run(post, side)
            s = only_setup(rep, ids)
            pid, k = ids["pat"](48), 50 + j
            assert s.status == CONFIRMED and path(s)[3:] == [(PATTERN_DETECTED, 49), (CONFIRMED, k)], path(s)
            assert s.setup_id == setup_id(ids["sweep"], pid) == "setup:%s:%s" % (ids["sweep"], pid)     # CK-2, MD-2
            assert s.confirmed_pattern_id == pid and s.confirmation_id == "confirmation:%s:%d" % (pid, k)
            assert pstates(rep) == {pid: ("CONFIRMED", k)}
            (cf,) = rep.confirmations
            assert (cf.id, cf.pattern_id, cf.confirmation_candle, cf.direction) == \
                (confirmation_id(pid, k), pid, k, "BULLISH" if side == "BUY" else "BEARISH")
            assert cf.timestamp == T0 + timedelta(minutes=5 * k) and cf.stamp.index == cf.stamp.confirmed_index == k
            assert r2(cf.level) == (E_HIGH if side == "BUY" else r2(200 - E_HIGH))   # CS-8 range; mirrored low = 200 - high
            assert (s.reason_code, s.disposition_reason) == (None, None)                  # OQ-2 / CK-13 separation
            cand = [c for c in rep_b(post, side).candidates][0]
            assert (cand.status, cand.closed_index) == (B.CONFIRMED, k)


def rep_b(post, side):
    """Module B's candidate as Module D left it."""
    ins = "TEST-%s" % side
    rows = BASE + list(post)
    if side == "SELL":
        rows = mirror(rows)
    st = ConfirmationStream(ins, TF, market(ins))
    for c in series(rows, ins):
        st.on_candle(c)
    return st.setup_stream


# ---------------------------------------------------------------- expiry
def test_pattern_and_setup_expiry_mirrored():
    def one(side):
        post = [E_BEAR, E_BULL, F, F, F, F]                  # 50..52: close 116.20 <= 116.35 and >= 115.93
        rep, ids = run(post, side)
        s, pid = only_setup(rep, ids), ids["pat"](48)
        assert pstates(rep) == {pid: ("EXPIRED", 52)}        # end 49 + 3
        assert s.status == EXPIRED and path(s)[3:] == [(PATTERN_DETECTED, 49), (EXPIRED, 52)]
        assert s.detail == ALL_PATTERNS_EXPIRED and s.setup_id is None and rep.confirmations == []     # MD-2
        assert rep_b(post, side).candidates[0].status == B.EXPIRED
    both(one)


def test_no_qualifying_pattern_expires_at_window_end_and_sweep_candle_excluded():
    """Candle 48 (O 115.58 H 116.10 L 115.55 C 116.05, bull) engulfs the sweep candle 47 (bear, body [115.60, 116.00]):
    a Bullish Engulfing 47-48 that contains the sweep candle -> never qualifies (CS-9 / CK-6)."""
    def one(side):
        post = [(115.58, 116.10, 115.55, 116.05)] + [F] * 5
        assert c_patterns(post, side, S, S + 5) == [(ENG_BULL if side == "BUY" else ENG_BEAR) + (47, 48)]
        rep, ids = run(post, side)
        s = only_setup(rep, ids)
        assert [(d.index, d.code, d.pattern_id) for d in rep.diagnostics] == [(48, SWEEP_CANDLE_IN_PATTERN, ids["pat"](47))]
        assert rep.pattern_states == [] and s.status == EXPIRED and s.detail == NO_QUALIFYING_PATTERN
        assert path(s)[3:] == [(EXPIRED, 52)]               # SWEEP_DETECTED -> EXPIRED at s + 5
    both(one)


# ---------------------------------------------------------------- invalidation
def test_invalidation_then_setup_invalidated_at_window_end_mirrored():
    def one(side):
        post = [E_BEAR, E_BULL, IV, F, F, F]
        rep, ids = run(post, side)
        s, pid = only_setup(rep, ids), ids["pat"](48)
        assert pstates(rep) == {pid: ("INVALIDATED", 50)}
        assert s.status == INVALIDATED and s.detail == ALL_PATTERNS_INVALIDATED
        assert path(s)[3:] == [(PATTERN_DETECTED, 49), (INVALIDATED, 52)]   # waits for the 5-candle window (CK-18)
    both(one)


def test_invalidation_boundary_and_epsilon_mirrored():
    """CK-12: invalidation iff close < pattern_low - eps. pattern_low 115.93: equal, 5e-9 below (inside eps) -> NOT
    invalidated (pattern later EXPIRED at 52); 2e-8 below -> INVALIDATED at 50."""
    for side in ("BUY", "SELL"):
        for d, expect in ((0.0, ("EXPIRED", 52)), (5e-9, ("EXPIRED", 52)), (2e-8, ("INVALIDATED", 50))):
            x = E_LOW - d
            cnd = (116.10, 116.15, x - 0.05, x)              # R ~.27, B ~.17 (.63): no family; bear
            post = [E_BEAR, E_BULL, cnd, F, F]
            rows = BASE + post
            if side == "SELL":
                rows = mirror(rows[:-3]) + [tuple(200 - v for v in (cnd[0], cnd[2], cnd[1], cnd[3]))] + mirror([F, F])
                ins = "TEST-SELL"
                rep = analyze_confirmations(series(rows, ins), ins, TF, market(ins))
                pid = "pattern:%s:5m:48:ENGULFING" % ins
            else:
                rep, ids = run(post, side)
                pid = ids["pat"](48)
            assert pstates(rep) == {pid: expect}, (side, d, pstates(rep))


def test_confirmation_boundary_and_epsilon_mirrored():
    """CS-7 / CK-8: confirmation iff close > pattern_high + eps (116.35): equal or 5e-9 above -> no; 2e-8 above -> yes."""
    for side in ("BUY", "SELL"):
        for d, expect in ((0.0, ("EXPIRED", 52)), (5e-9, ("EXPIRED", 52)), (2e-8, ("CONFIRMED", 50))):
            x = E_HIGH + d
            cnd = (116.20, x + 0.05, 116.15, x)              # R ~.25, B ~.15 (.6): no family; bull, no engulf
            if side == "BUY":
                rows, ins = BASE + [E_BEAR, E_BULL, cnd, F, F], "TEST-BUY"
            else:
                ins = "TEST-SELL"
                rows = mirror(BASE + [E_BEAR, E_BULL]) + [(200 - cnd[0], 200 - cnd[2], 200 - cnd[1], 200 - cnd[3])] + \
                    mirror([F, F])
            rep = analyze_confirmations(series(rows, ins), ins, TF, market(ins))
            assert pstates(rep) == {"pattern:%s:5m:48:ENGULFING" % ins: expect}, (side, d)


def test_confirmation_and_invalidation_never_both_on_one_pattern():
    """A pattern has high >= low and eps > 0, so close > high + eps and close < low - eps cannot both hold. Exhaustive
    over a grid of closes around both bounds: each candle gives at most one terminal outcome."""
    for side in ("BUY", "SELL"):
        for x in [E_LOW - 0.02, E_LOW - EPS * 2, E_LOW, (E_LOW + E_HIGH) / 2, E_HIGH, E_HIGH + EPS * 2, E_HIGH + 0.02]:
            cnd = (116.10, max(116.10, x) + 0.05, min(116.10, x) - 0.05, x)
            rows = BASE + [E_BEAR, E_BULL, cnd, F, F]
            if side == "SELL":
                rows = mirror(rows)
            ins = "TEST-%s" % side
            rep = analyze_confirmations(series(rows, ins), ins, TF, market(ins))
            st = [p for p in rep.pattern_states if p.pattern_id.endswith(":48:ENGULFING")]
            assert len(st) == 1 and st[0].status in ("CONFIRMED", "INVALIDATED", "EXPIRED")
            assert len([c for c in rep.confirmations if c.pattern_id == st[0].pattern_id]) == (st[0].status == "CONFIRMED")


# ---------------------------------------------------------------- window boundaries (first / last eligible)
# Morning Star (bull, no trend needed): a (116.40 116.45 116.02 116.05) large bear, m (116.03 116.10 115.95 116.05)
# small, z (116.05 116.50 116.02 116.45) large bull; mid(a) 116.225 < 116.45. high 116.50 low 115.95.
MS_A, MS_M, MS_Z = (116.40, 116.45, 116.02, 116.05), (116.03, 116.10, 115.95, 116.05), (116.05, 116.50, 116.02, 116.45)


def test_first_and_last_eligible_candles_and_multi_candle_window_boundary_mirrored():
    def one(side):
        star = ("MORNING_STAR", "MORNING_STAR") if side == "BUY" else ("EVENING_STAR", "EVENING_STAR")
        # (a) Morning Star 50-52: completes on the LAST eligible candle s+5 -> tracked
        post = [F, F, MS_A, MS_M, MS_Z, F, F, F]
        assert c_patterns(post, side, S + 1, S + 5) == [star + (50, 52)]
        rep, ids = run(post, side)
        s = only_setup(rep, ids)
        assert s.tracked == (ids["pat"](50, star[0]),) and path(s)[3] == (PATTERN_DETECTED, 52)
        assert pstates(rep)[ids["pat"](50, star[0])] == ("EXPIRED", 55)     # 53..55: F closes 116.20 < 116.50
        assert s.status == EXPIRED and path(s)[-1] == (EXPIRED, 55)
        # (b) Morning Star 51-53: completes at s+6 -> outside the window, never considered
        post = [F, F, F, MS_A, MS_M, MS_Z, F, F]
        assert c_patterns(post, side, S + 1, S + 6) == [star + (51, 53)]
        rep, ids = run(post, side)
        s = only_setup(rep, ids)
        assert s.tracked == () and rep.diagnostics == [] and s.status == EXPIRED and path(s)[-1] == (EXPIRED, 52)
        # (c) Engulfing 48-49: starts on the FIRST eligible candle s+1 -> tracked
        rep, ids = run([E_BEAR, E_BULL, CU], side)
        assert only_setup(rep, ids).tracked == (ids["pat"](48),)
    both(one)


# ---------------------------------------------------------------- bias filter and neutral rejection
# Bearish Engulfing in a BUY window: F (bull body [116.00, 116.20]) then (116.22 116.27 115.95 115.98) bear covering it.
# Classic Doji (116.10 116.20 116.00 116.11): B .01 R .20 -> Classic + Long-legged (both NEUTRAL), no other family.
BEAR_ENG_2ND = (116.22, 116.27, 115.95, 115.98)
DOJI = (116.10, 116.20, 116.00, 116.11)


def test_bias_filter_and_neutral_rejection_mirrored():
    def one(side):
        post = [F, BEAR_ENG_2ND, F, DOJI, F, F, F]
        neutral = [("CLASSIC_DOJI", "CLASSIC_DOJI", 51, 51), ("LONG_LEGGED_DOJI", "LONG_LEGGED_DOJI", 51, 51)]
        assert c_patterns(post, side, S + 1, S + 5) == sorted([(ENG_BEAR if side == "BUY" else ENG_BULL) + (48, 49)]
                                                              + neutral)
        rep, ids = run(post, side)
        s = only_setup(rep, ids)
        assert sorted((d.index, d.code, d.pattern_id) for d in rep.diagnostics) == sorted([
            (49, BIAS_MISMATCH, ids["pat"](48)),
            (51, NON_DIRECTIONAL_BIAS, ids["pat"](51, "CLASSIC_DOJI")),
            (51, NON_DIRECTIONAL_BIAS, ids["pat"](51, "LONG_LEGGED_DOJI"))])
        assert rep.pattern_states == [] and s.status == EXPIRED and s.detail == NO_QUALIFYING_PATTERN
    both(one)


# ---------------------------------------------------------------- multiple patterns, CK-11 retry, MD-1, MD-3
# Second Engulfing 50-51 (E_BEAR at 50, E_BULL at 51) or 51-52.
def test_ck11_retry_after_expiry_next_pattern_confirms_mirrored():
    def one(side):
        post = [E_BEAR, E_BULL, F, E_BEAR, E_BULL, CU, F]   # E1 48-49 expires at 52; E2 51-52 confirms at 53
        rep, ids = run(post, side)
        s, p1, p2 = only_setup(rep, ids), ids["pat"](48), ids["pat"](51)
        assert pstates(rep) == {p1: ("EXPIRED", 52), p2: ("CONFIRMED", 53)}
        assert s.tracked == (p1, p2) and s.setup_id == setup_id(ids["sweep"], p2)
        assert path(s)[3:] == [(PATTERN_DETECTED, 49), (CONFIRMED, 53)]      # MD-4: no step back after E1 expired
    both(one)


def test_ck11_retry_after_invalidation_mirrored():
    def one(side):
        post = [E_BEAR, E_BULL, IV, E_BEAR, E_BULL, CU, F]   # E1 invalidated at 50; E2 51-52 confirms at 53
        rep, ids = run(post, side)
        s, p1, p2 = only_setup(rep, ids), ids["pat"](48), ids["pat"](51)
        assert pstates(rep) == {p1: ("INVALIDATED", 50), p2: ("CONFIRMED", 53)}
        assert s.status == CONFIRMED and s.setup_id == setup_id(ids["sweep"], p2)
    both(one)


def test_md1_concurrent_patterns_confirm_on_the_same_candle_earliest_wins_mirrored():
    def one(side):
        post = [E_BEAR, E_BULL, E_BEAR, E_BULL, CU, F]       # E1 48-49 and E2 50-51 both pending; CU at 52 confirms both
        rep, ids = run(post, side)
        s, p1, p2 = only_setup(rep, ids), ids["pat"](48), ids["pat"](50)
        assert pstates(rep) == {p1: ("CONFIRMED", 52), p2: ("CONFIRMED", 52)}    # each pattern: its own event
        assert [c.id for c in rep.confirmations] == [confirmation_id(p1, 52), confirmation_id(p2, 52)]
        assert s.setup_id == setup_id(ids["sweep"], p1) and s.confirmed_pattern_id == p1      # MD-1: earliest end
        assert path(s)[-1] == (CONFIRMED, 52)
    both(one)


def test_md1_order_key():
    """MD-1 sort key: end candle, then start candle, then 16.A family order."""
    class P:
        def __init__(self, t, s, e):
            self.pattern_type, self.start_candle, self.end_candle = t, s, e
    ps = [P("HAMMER_HANGING_MAN", 10, 10), P("DRAGONFLY_DOJI", 10, 10), P("ENGULFING", 9, 10), P("CLASSIC_DOJI", 9, 9)]
    assert [p.pattern_type for p in sorted(ps, key=_mdl_order)] == \
        ["CLASSIC_DOJI", "ENGULFING", "DRAGONFLY_DOJI", "HAMMER_HANGING_MAN"]


def test_md3_mixed_expired_and_invalidated_gives_expired_mirrored():
    """E1 48-49 invalidated by IV at 50; E2 = Engulfing 50-51 with IV as its bear candle and (115.83 116.20 115.80
    116.15) covering [115.85, 116.10]; E2 high 116.20, low 115.80; F closes 116.20 (= high, no confirm) -> E2 EXPIRED
    at 54; setup EXPIRED (MD-3) at 54."""
    def one(side):
        e2b = (115.83, 116.20, 115.80, 116.15)
        post = [E_BEAR, E_BULL, IV, e2b, F, F, F, F]
        rep, ids = run(post, side)
        s, p1, p2 = only_setup(rep, ids), ids["pat"](48), ids["pat"](50)
        assert pstates(rep) == {p1: ("INVALIDATED", 50), p2: ("EXPIRED", 54)}
        assert s.status == EXPIRED and s.detail == MIXED_EXPIRED_INVALIDATED and path(s)[-1] == (EXPIRED, 54)
    both(one)


# ---------------------------------------------------------------- one setup per sweep; nothing after CONFIRMED
def test_no_second_setup_after_confirmation_mirrored():
    def one(side):
        post = [E_BEAR, E_BULL, CU, E_BEAR, E_BULL, F, F]    # confirmed at 50; Engulfing 51-52 inside the window
        rep, ids = run(post, side)
        s = only_setup(rep, ids)
        assert s.status == CONFIRMED and s.tracked == (ids["pat"](48),)
        assert [(d.index, d.code, d.pattern_id) for d in rep.diagnostics] == [(52, SETUP_ALREADY_CONFIRMED, ids["pat"](51))]
        assert len(rep.confirmations) == 1
    both(one)


# ---------------------------------------------------------------- structure invalidation (MB-3 / CK-18) and ordering
def test_opposite_choch_invalidates_setup_before_pattern_logic_mirrored():
    """Candle 50 closes 115.30 < protected low 115.40 -> bearish CHoCH at 50 (Module B ends the BOS eligibility first,
    17.S); the same close also invalidates E1 (pattern layer, CK-12)."""
    def one(side):
        post = [E_BEAR, E_BULL, (116.00, 116.05, 115.25, 115.30), F, F]
        rep, ids = run(post, side)
        s = only_setup(rep, ids)
        d = "bearish" if side == "BUY" else "bullish"
        assert s.status == INVALIDATED and path(s)[-1] == (INVALIDATED, 50) and s.detail == "STRUCTURE_INVALIDATION"
        k = "low" if side == "BUY" else "high"                   # CHoCH only: swing 47 (115.28) is the latest swing
        assert s.history[-1].cause == "choch:%s:swing:%s:36:fixed-window-strict:L2R2" % (d, k)   # low, not broken
        assert rep_b(post, side).candidates[0].closed_by == s.history[-1].cause
        assert pstates(rep) == {ids["pat"](48): ("INVALIDATED", 50)}
        assert rep.confirmations == []
    both(one)


# ---------------------------------------------------------------- CS-8: Engulfing range uses BOTH candles
# E_BEAR_WIDE (116.20 116.45 115.85 116.00): R .60 B .20 (.33), no family; with E_BULL the pattern range is
# high max(116.45, 116.35) = 116.45, low min(115.85, 115.93) = 115.85 (the FIRST candle sets both extremes).
E_BEAR_WIDE = (116.20, 116.45, 115.85, 116.00)


def test_engulfing_combined_range_cs8_mirrored():
    """A close of 116.40 is above the 2nd candle's high (116.35) but not above the combined high (116.45): no
    confirmation. A close of 115.88 is below the 2nd candle's low (115.93) but not below the combined low (115.85): no
    invalidation. Both patterns therefore EXPIRE at 52."""
    for side in ("BUY", "SELL"):
        for cnd in ((116.20, 116.44, 116.15, 116.40), (116.10, 116.15, 115.86, 115.88)):
            post = [E_BEAR_WIDE, E_BULL, cnd, F, F]
            assert c_patterns(post, side, S + 1, S + 5) == [(ENG_BULL if side == "BUY" else ENG_BEAR) + (48, 49)]
            rep, ids = run(post, side)
            (ps,) = rep.pattern_states
            hi, lo = (116.45, 115.85) if side == "BUY" else (r2(200 - 115.85), r2(200 - 116.45))
            assert (r2(ps.pattern_high), r2(ps.pattern_low)) == (hi, lo)
            assert (ps.status, ps.closed_index) == ("EXPIRED", 52), (side, cnd, ps.status)


def test_ck4_unclassified_shape_never_qualifies():
    """CK-4 / Section 3: a shape without its required trend (label UNCLASSIFIED_SHAPE) keeps its bias but cannot
    qualify; the same shape WITH its contextual label qualifies. Rule-level check on Module D's qualifier."""
    from scanner_v6.entry.candlesticks import PatternEvent, pattern_id
    from scanner_v6.models import EventStamp
    from scanner_v6.entry.confirmation import CONTEXT_LABEL_MISSING
    st = ConfirmationStream("TEST-BUY", TF, market("TEST-BUY"))
    for side, ptype, label, bias in (("BUY", "INVERTED_HAMMER", "INVERTED_HAMMER", "BULLISH_BIAS"),
                                     ("SELL", "SHOOTING_STAR", "SHOOTING_STAR", "BEARISH_BIAS")):
        rec = SetupRecord("bos:x", "sweep:X:5", side, "SSL" if side == "BUY" else "BSL", 5, None, SWEEP_DETECTED,
                          (Transition(SWEEP_DETECTED, 5, T0),))
        for lab, expect in ((label, None), ("UNCLASSIFIED_SHAPE", CONTEXT_LABEL_MISSING)):
            p = PatternEvent(pattern_id("TEST-BUY", TF, 7, ptype), EventStamp(7, T0, 7, T0), instrument="TEST-BUY",
                             timeframe=TF, pattern_type=ptype, pattern_label=lab, bias=bias, start_candle=7,
                             end_candle=7, pattern_high=1.0, pattern_low=0.5)
            assert st._qualify(rec, p) == expect, (side, lab)


# ---------------------------------------------------------------- review fixes 2-4: OQ-5, opposite BOS, D5 tie
# L50 (116.10 116.15 115.80 116.00): R .35 B .10; with F (low 115.95) at 48-49 and E_BEAR / E_BULL (lows 115.95 /
# 115.93) at 51-52 it is a strict L2/R2 swing low at 50 (115.80), confirmed at 52, usable from 53 (D5).
# Candle 53: OPP_BOS closes 115.70 < 115.80 (bearish BOS of swing:low:50) but >= the protected low 115.40 (no CHoCH);
# TIE closes 115.20 < 115.80 AND < 115.40 -> bearish BOS of swing:low:50 AND bearish CHoCH of swing:low:36 at 53.
# Incidental, asserted: Evening Star 49-51 (F large bull, L50 small, E_BEAR large bear closing 116.00 < 116.10) is
# bearish -> BIAS_MISMATCH; Bullish Engulfing 51-52 is tracked and pending at 53.
L50 = (116.10, 116.15, 115.80, 116.00)
OPP_BOS = (116.00, 116.05, 115.65, 115.70)
TIE = (116.00, 116.05, 115.15, 115.20)


def _opp(side):
    d, k = ("bearish", "low") if side == "BUY" else ("bullish", "high")
    return d, k


def test_opposite_bos_invalidates_setup_with_terminating_id_mirrored():
    """Review fix 3 (MB-3 b, CK-18): an opposite BOS of ANY role ends the eligibility; here a COUNTER_STRUCTURE BOS at
    53 with no CHoCH. Setup INVALIDATED at 53, cause = that BOS id; Module B candidate closed_by the same id."""
    from scanner_v6.structure.choch import CHoCHBreak, analyze_structure
    for side in ("BUY", "SELL"):
        post = [F, F, L50, E_BEAR, E_BULL, OPP_BOS, F]
        rows = BASE + post if side == "BUY" else mirror(BASE + post)
        d, k = _opp(side)
        bos_id = "bos:%s:swing:%s:50:fixed-window-strict:L2R2" % (d, k)
        st = analyze_structure(series(rows, "X"))
        assert [(b.id, b.index, st.bos_roles[b.id]) for b in st.bos if b.index >= 48] == [(bos_id, 53, "COUNTER_STRUCTURE")]
        assert [e for e in st.events if isinstance(e, CHoCHBreak) and e.index >= 48] == []          # BOS only
        rep, ids = run(post, side)
        s = only_setup(rep, ids)
        assert (s.status, path(s)[-1], s.history[-1].cause, s.detail) == (INVALIDATED, (INVALIDATED, 53), bos_id,
                                                                          "STRUCTURE_INVALIDATION")
        assert path(s)[3:] == [(PATTERN_DETECTED, 52), (INVALIDATED, 53)]
        assert pstates(rep) == {ids["pat"](51): ("INVALIDATED", 53)}                               # pattern layer too
        assert [(x.index, x.code) for x in rep.diagnostics] == [(51, BIAS_MISMATCH)]               # Evening Star
        cand = rep_b(post, side).candidates[0]
        assert (cand.status, cand.closed_index, cand.closed_by) == (B.INVALIDATED, 53, bos_id)


def test_same_candle_opposite_bos_and_choch_terminator_is_the_bos_mirrored():
    """Review fix 4 (17.S, PHASE1_2 D5: BOS evaluation before CHoCH evaluation): an opposite BOS and an opposite CHoCH
    at the same close -> the terminating event is the BOS, in Module B (closed_by) and in Module D (cause)."""
    from scanner_v6.structure.choch import CHoCHBreak, analyze_structure
    for side in ("BUY", "SELL"):
        post = [F, F, L50, E_BEAR, E_BULL, TIE, F]
        rows = BASE + post if side == "BUY" else mirror(BASE + post)
        d, k = _opp(side)
        bos_id = "bos:%s:swing:%s:50:fixed-window-strict:L2R2" % (d, k)
        choch_id = "choch:%s:swing:%s:36:fixed-window-strict:L2R2" % (d, k)
        st = analyze_structure(series(rows, "X"))
        assert [(b.id, b.index) for b in st.bos if b.index >= 48] == [(bos_id, 53)]
        assert [(e.id, e.index) for e in st.events if isinstance(e, CHoCHBreak) and e.index >= 48] == [(choch_id, 53)]
        rep, ids = run(post, side)
        s = only_setup(rep, ids)
        assert (s.status, path(s)[-1], s.history[-1].cause) == (INVALIDATED, (INVALIDATED, 53), bos_id)
        assert s.history[-1].cause != choch_id
        sb = rep_b(post, side)
        cand = sb.candidates[0]
        assert (cand.status, cand.closed_index, cand.closed_by) == (B.INVALIDATED, 53, bos_id)
        assert sb.bos_states[cand.bos_id].ended_by == bos_id


SWEEP2 = (115.60, 115.65, 115.20, 115.50)   # low 115.20 < pool swing:low:47 (115.28), close 115.50 back above it
#                                             and >= 115.40 (no CHoCH, no BOS: the latest swing low is 47 at 115.28)
IV_EQ = (116.10, 116.15, 115.85, 115.86)    # invalidates E (115.86 < 115.93); low 115.85 ...
IV_EQ_NEXT = (115.90, 116.20, 115.85, 116.15)   # ... equals this low, so neither is a strict swing low (no later BOS)


def test_oq5_new_setup_after_first_expires_or_invalidates_mirrored():
    """Review fix 2 (OQ-5 r3, MB-3, MD-2, MD-4): the first candidate of the BOS reaches EXPIRED (no qualifying pattern)
    or INVALIDATED (its only pattern invalidated); Module D closes the Module B candidate; a later SSL (BSL) sweep group
    under the SAME BOS (still eligible) starts a new candidate with its own key and lifecycle, confirmed at 57; the
    first setup stays terminal and identical in every later snapshot."""
    variants = (("EXPIRED", [F] * 6, EXPIRED, NO_QUALIFYING_PATTERN, [(EXPIRED, 52)]),
                ("INVALIDATED", [E_BEAR, E_BULL, IV_EQ, IV_EQ_NEXT, F, F], INVALIDATED, ALL_PATTERNS_INVALIDATED,
                 [(PATTERN_DETECTED, 49), (INVALIDATED, 52)]))
    for name, head, st1, det1, path1 in variants:
        for side in ("BUY", "SELL"):
            post = head + [SWEEP2, E_BEAR, E_BULL, CU, F]                 # 54 sweep, 55-56 Engulfing, 57 confirms
            rep, ids = run(post, side)
            g2 = "sweep:%s:54" % ("SSL" if side == "BUY" else "BSL")
            assert [s.group_id for s in rep.setups] == [ids["sweep"], g2], (name, side)
            s1, s2 = rep.setups
            assert s1.bos_id == s2.bos_id and s1.key != s2.key                           # same BOS, own keys
            assert (s1.status, s1.detail, path(s1)[3:]) == (st1, det1, path1)
            assert s1.setup_id is None and s1.tracked == ((ids["pat"](48),) if name == "INVALIDATED" else ())
            assert path(s2)[:3] == [(CHOCH_DETECTED, 33), (BOS_CONFIRMED, 39), (SWEEP_DETECTED, 54)]   # own lifecycle
            assert path(s2)[3:] == [(PATTERN_DETECTED, 56), (CONFIRMED, 57)]
            assert s2.setup_id == setup_id(g2, ids["pat"](55)) and s2.tracked == (ids["pat"](55),)
            # Module B: first candidate closed by Module D, second candidate created and closed CONFIRMED
            sb = rep_b(post, side)
            c1, c2 = sb.candidates
            assert (c1.key, c1.status, c1.closed_index) == (s1.key, B.EXPIRED if st1 == EXPIRED else B.INVALIDATED, 52)
            assert (c2.key, c2.index, c2.status, c2.closed_index) == (s2.key, 54, B.CONFIRMED, 57)
            assert sb.bos_states[s1.bos_id].confirmed_setup is True and sb.current_bos_id == s1.bos_id
            # first setup immutable from its terminal candle on
            for k in range(52, len(rep.snapshots)):
                assert rep.snapshots[k][0][0] == rep.snapshots[52][0][0], (name, side, k)
            # Morning / Evening Star 53-55 contains the sweep candle 54 -> excluded (CS-9)
            assert [(x.index, x.code) for x in rep.diagnostics] == [(55, SWEEP_CANDLE_IN_PATTERN)]


# ---------------------------------------------------------------- lifecycle rules
def test_terminal_immutability_and_forward_only():
    rec = SetupRecord("bos:x", "sweep:SSL:5", "BUY", "SSL", 5, None, SWEEP_DETECTED,
                      (Transition(SWEEP_DETECTED, 5, T0),))
    ok = _advance(rec, PATTERN_DETECTED, 7, T0, "p", None, NORMAL)
    assert ok.status == PATTERN_DETECTED and rec.status == SWEEP_DETECTED                 # records are immutable
    assert raises(LifecycleError, _advance, ok, SWEEP_DETECTED, 8, T0, None, None, NORMAL)      # no step back (MD-4)
    for reserved in (ENTERED, STOPPED_OUT, TARGET_HIT, NO_TRADE):                          # Module E only
        assert raises(LifecycleError, _advance, ok, reserved, 8, T0, None, None, NORMAL)
    assert raises(LifecycleError, _advance, rec, CONFIRMED, 8, T0, None, None, NORMAL)    # no skipping the pattern
    assert raises(LifecycleError, _advance, ok, CONFIRMED, 6, T0, None, None, NORMAL)     # no backdating
    for term in (EXPIRED, INVALIDATED):
        t = _advance(ok, term, 9, T0, None, None, NORMAL)
        for nxt in (SWEEP_DETECTED, PATTERN_DETECTED, CONFIRMED, EXPIRED, INVALIDATED, ENTERED):
            try:
                _advance(t, nxt, 10, T0, None, None, NORMAL)
                raise AssertionError("terminal %s reactivated to %s" % (term, nxt))
            except LifecycleError as e:                                                    # CK-10 / CK-18
                assert "cannot reactivate" in str(e), str(e)
    # in a run, a terminal setup never changes again in any later snapshot
    rep, ids = run([E_BEAR, E_BULL, F, F, F, E_BEAR, E_BULL, CU, F])
    first = [k for k, (ss, _) in enumerate(rep.snapshots) if ss and ss[0].terminal][0]
    assert all(rep.snapshots[k][0][0] == rep.snapshots[first][0][0] for k in range(first, len(rep.snapshots)))


# ---------------------------------------------------------------- data interruption (OQ-3 / CK-24)
def test_data_interruption_and_resumption():
    post = [E_BEAR, E_BULL, F, CU, F]
    base, ids = run(post, gap_after=49)                     # candle 49 closes 13:10; candle 50 opens 14:10 (a gap)
    t_int, t_res = T0 + timedelta(minutes=5 * 50, seconds=10), T0 + timedelta(minutes=5 * 50 + 30)   # inside the gap
    rep, _ = run(post, data_events=[(50, DATA_INTERRUPTED, t_int), (50, DATA_RESUMED, t_res)], gap_after=49)
    # nothing fabricated: same candles, same patterns, same confirmation; only the data_state annotations differ
    assert [c.id for c in rep.confirmations] == [c.id for c in base.confirmations]
    assert pstates(rep) == pstates(base)
    s0, s1 = base.setups[0], rep.setups[0]
    assert path(s0) == path(s1) and s1.setup_id == s0.setup_id
    assert [t.data_state for t in s1.history] == [NORMAL, NORMAL, NORMAL, NORMAL, DATA_RESUMED]
    assert [(d.state, d.ts, d.after_index) for d in rep.data_changes] == [(DATA_INTERRUPTED, t_int, 49),
                                                                          (DATA_RESUMED, t_res, 49)]
    st = ConfirmationStream(ids["ins"], TF, market(ids["ins"]))
    sr = list(series(BASE + post, ids["ins"], gap_after=49))
    for c in sr[:50]:
        st.on_candle(c)
    st.mark_data_interrupted(t_int)
    assert raises(ValueError, st.on_candle, sr[50])             # no candle while interrupted (CK-24)
    assert raises(ValueError, st.mark_data_interrupted, t_int)
    st.mark_data_resumed(t_res)
    assert raises(ValueError, st.mark_data_resumed, t_res)
    for c in sr[50:]:
        st.on_candle(c)
    assert st.setups == rep.setups
    # an interruption that ends before the sweep candle: SWEEP_DETECTED carries DATA_RESUMED, CHoCH / BOS entries keep
    # the state of their own candles (NORMAL). Contiguous candles 46 / 47: the window is the boundary instant (F-D2).
    t47 = T0 + timedelta(minutes=5 * 47)
    rep2, _ = run(post, data_events=[(47, DATA_INTERRUPTED, t47), (47, DATA_RESUMED, t47)])
    s2 = rep2.setups[0]
    assert [(t.status, t.data_state) for t in s2.history] == [(CHOCH_DETECTED, NORMAL), (BOS_CONFIRMED, NORMAL),
                                                              (SWEEP_DETECTED, DATA_RESUMED),
                                                              (PATTERN_DETECTED, DATA_RESUMED), (CONFIRMED, DATA_RESUMED)]
    assert s2.data_state == DATA_RESUMED and path(s2) == path(s0)
    # the same events stamped inside a candle (accepted before F-D2) are now rejected, in batch and in stream
    for ev in ([(47, DATA_INTERRUPTED, t47 - timedelta(seconds=1)), (47, DATA_RESUMED, t47)],      # inside 46
               [(47, DATA_INTERRUPTED, t47), (47, DATA_RESUMED, t47 + timedelta(seconds=1))]):     # inside 47
        assert raises(ValueError, run, post, data_events=ev)


def test_data_state_chronology_positive_and_negative():
    """Review fix 1 (OQ-3): each data-state timestamp is no earlier than the preceding data-state change (and the last
    processed candle). Equal timestamps are allowed; earlier ones are rejected and leave the state unchanged.
    DATA_RESUMED stays the flag until the next interruption (no DATA_RESUMED -> NORMAL step is made)."""
    ins = "TEST-BUY"
    sr = list(series(BASE + [F, F, F], ins, gap_after=49))
    t49 = sr[49].ts
    close49 = t49 + TFD                                      # data events before candle 50 live in [close49, open50]

    def fresh():
        st = ConfirmationStream(ins, TF, market(ins))
        for c in sr[:50]:
            st.on_candle(c)
        return st

    sec = lambda n: close49 + timedelta(seconds=n)
    # positive: resume after, then a later interruption after the resume, then resume again
    st = fresh()
    st.mark_data_interrupted(sec(10)); st.mark_data_resumed(sec(20)); st.mark_data_interrupted(sec(30))
    st.mark_data_resumed(sec(40))
    assert [(d.state, d.ts) for d in st.data_changes] == [(DATA_INTERRUPTED, sec(10)), (DATA_RESUMED, sec(20)),
                                                          (DATA_INTERRUPTED, sec(30)), (DATA_RESUMED, sec(40))]
    st.on_candle(sr[50])
    assert st.data_state == DATA_RESUMED                       # no invented DATA_RESUMED -> NORMAL
    # positive: equal timestamps are not "earlier"
    st = fresh()
    st.mark_data_interrupted(sec(10)); st.mark_data_resumed(sec(10)); st.mark_data_interrupted(sec(10))
    assert [d.state for d in st.data_changes] == [DATA_INTERRUPTED, DATA_RESUMED, DATA_INTERRUPTED]
    # negative: DATA_RESUMED earlier than DATA_INTERRUPTED
    st = fresh()
    st.mark_data_interrupted(sec(10))
    assert raises(ValueError, st.mark_data_resumed, sec(9))
    assert st.data_state == DATA_INTERRUPTED and len(st.data_changes) == 1          # rejected: nothing recorded
    st.mark_data_resumed(sec(10))
    # negative: a later interruption earlier than the preceding resume
    st = fresh()
    st.mark_data_interrupted(sec(10)); st.mark_data_resumed(sec(20))
    assert raises(ValueError, st.mark_data_interrupted, sec(19))
    assert st.data_state == DATA_RESUMED and len(st.data_changes) == 2
    # negative: before the last processed candle's open, and (F-D2) inside it, i.e. before its close
    st = fresh()
    assert raises(ValueError, st.mark_data_interrupted, t49 - timedelta(seconds=1))
    assert raises(ValueError, st.mark_data_interrupted, close49 - timedelta(seconds=1))
    assert st.data_changes == [] and st.data_state == NORMAL
    st.mark_data_interrupted(close49)                                                    # the close itself: allowed
    # batch path applies the same rule
    sg = series(BASE + [F, F, F], ins, gap_after=49)
    assert raises(ValueError, analyze_confirmations, sg, ins, TF, market(ins),
                  data_events=[(50, DATA_INTERRUPTED, sec(10)), (50, DATA_RESUMED, sec(5))])
    assert raises(ValueError, analyze_confirmations, sg, ins, TF, market(ins),
                  data_events=[(50, DATA_INTERRUPTED, sec(-1)), (50, DATA_RESUMED, sec(5))])


class _NoIterSeries:
    """Wraps a series; iterating it (i.e. processing any candle) fails loudly. Used to prove that a rejected
    data_events list is rejected BEFORE any candle is processed or any stream state is built."""
    def __init__(self, sr):
        self._sr = sr

    def __len__(self):
        return len(self._sr)

    def __getitem__(self, i):
        return self._sr[i]

    def __iter__(self):
        raise AssertionError("a candle was processed before data_events were validated")


def test_batch_data_events_input_validation():
    """Final review fix: analyze_confirmations validates every data event before any candle is processed. Unknown
    states, indices outside 0 .. n-1, non-datetime ts, broken sequences and events that could never be applied raise
    ValueError; nothing is interpreted, defaulted or dropped. n = 51 here (BASE 48 + 3). Candle 50 opens GAP after
    candle 49's close, so g(sec) = close of 49 + sec is a valid instant before candle 50 (F-D2 window)."""
    from scanner_v6.entry.confirmation import validate_data_events
    ins = "TEST-BUY"
    sr = series(BASE + [F, F, F], ins, gap_after=49)
    n = len(sr)
    assert n == 51
    t = lambda i, sec=0: T0 + timedelta(minutes=5 * i, seconds=sec)        # contiguous part (candles 0..49)
    g = lambda sec: sr[49].ts + TFD + timedelta(seconds=sec)              # inside the gap before candle 50
    vde = lambda s_, e: validate_data_events(s_, e, TFD)
    bad = {
        "unknown state": [(50, "DATA_RESUME", g(10))],
        "unknown state NORMAL": [(50, DATA_INTERRUPTED, g(5)), (50, NORMAL, g(10))],
        "lower-case state": [(50, "data_interrupted", g(10))],
        "None state": [(50, None, g(10))],
        "negative index": [(-1, DATA_INTERRUPTED, t(0)), (-1, DATA_RESUMED, t(0))],
        "index = n (after the final candle)": [(n, DATA_INTERRUPTED, t(n, 1))],
        "index beyond the final candle": [(n + 5, DATA_INTERRUPTED, t(n + 5))],
        "float index": [(50.0, DATA_INTERRUPTED, g(10)), (50, DATA_RESUMED, g(20))],
        "bool index": [(True, DATA_INTERRUPTED, t(1)), (1, DATA_RESUMED, t(1))],
        "string ts": [(50, DATA_INTERRUPTED, "2026-01-05T13:05:10Z"), (50, DATA_RESUMED, g(20))],
        "naive ts": [(50, DATA_INTERRUPTED, g(10).replace(tzinfo=None)), (50, DATA_RESUMED, g(20))],
        "not a triple": [(50, DATA_INTERRUPTED)],
        "resume without interruption": [(50, DATA_RESUMED, g(10))],
        "double interruption": [(50, DATA_INTERRUPTED, g(10)), (50, DATA_INTERRUPTED, g(20))],
        "left interrupted before a candle": [(50, DATA_INTERRUPTED, g(10))],
        "resume earlier than interruption": [(50, DATA_INTERRUPTED, g(20)), (50, DATA_RESUMED, g(10))],
        "ts before the previous candle": [(50, DATA_INTERRUPTED, t(48)), (50, DATA_RESUMED, g(10))],
        # F-D2: the window [close of candle k-1, open of candle k], both bounds inclusive
        "interruption inside the previous candle": [(50, DATA_INTERRUPTED, t(49, 10)), (50, DATA_RESUMED, g(10))],
        "resume inside the previous candle": [(50, DATA_INTERRUPTED, t(49, 10)), (50, DATA_RESUMED, t(49, 20))],
        "one second before the previous close": [(50, DATA_INTERRUPTED, g(-1)), (50, DATA_RESUMED, g(10))],
        "resume after the next candle's open": [(50, DATA_INTERRUPTED, g(10)),
                                                 (50, DATA_RESUMED, sr[50].ts + timedelta(seconds=1))],
        "interruption inside the next candle": [(50, DATA_INTERRUPTED, sr[50].ts + timedelta(seconds=1)),
                                                 (50, DATA_RESUMED, sr[50].ts + timedelta(seconds=2))],
        "contiguous candles, inside the next candle": [(49, DATA_INTERRUPTED, t(49)),
                                                        (49, DATA_RESUMED, t(49, 1))],
    }
    for name, events in bad.items():
        assert raises(ValueError, vde, sr, events), name
        # rejected before any candle is processed: the wrapped series must never be iterated
        try:
            analyze_confirmations(_NoIterSeries(sr), ins, TF, market(ins), data_events=events)
            raise AssertionError("accepted: %s" % name)
        except ValueError:
            pass
    # the caller's event list is not modified by validation or by a rejection
    evs = [(50, DATA_RESUMED, g(20)), (50, DATA_INTERRUPTED, g(10))]               # wrong order on purpose
    snapshot = list(evs)
    assert raises(ValueError, analyze_confirmations, sr, ins, TF, market(ins), data_events=evs)
    assert evs == snapshot
    # valid: interruption + resumption before candle 50, and two pairs, applied in index order then given order
    ok1 = [(50, DATA_INTERRUPTED, g(10)), (50, DATA_RESUMED, g(20))]
    ok2 = [(50, DATA_INTERRUPTED, g(30)), (49, DATA_INTERRUPTED, t(49)), (49, DATA_RESUMED, t(49)),
           (50, DATA_RESUMED, g(40))]          # index order first, then the given order; 48 / 49 contiguous: boundary
    ok3 = [(50, DATA_INTERRUPTED, g(0)), (50, DATA_RESUMED, sr[50].ts)]                # both inclusive bounds
    assert raises(ValueError, vde, sr, [ok2[0], ok2[2], ok2[1], ok2[3]])   # 49: resume listed first
    assert vde(sr, ok1) == ok1 and vde(sr, ok3) == ok3
    assert [e[0] for e in vde(sr, ok2)] == [49, 49, 50, 50]
    # the window needs the timeframe (a candle's close); before candle 0 there is no lower bound
    assert raises(ValueError, validate_data_events, sr, ok1, None)
    assert validate_data_events(sr, [(0, DATA_INTERRUPTED, t(-1)), (0, DATA_RESUMED, t(0))], None)
    for evs in (ok1, ok2, ok3):
        rep = analyze_confirmations(sr, ins, TF, market(ins), data_events=evs)
        assert [(d.state, d.ts) for d in rep.data_changes] == [(s_, ts_) for _, s_, ts_ in vde(sr, evs)]
        base = analyze_confirmations(sr, ins, TF, market(ins))
        assert [x.key for x in rep.setups] == [x.key for x in base.setups] and rep.confirmations == base.confirmations
    assert analyze_confirmations(sr, ins, TF, market(ins), data_events=()).data_changes == []


def test_stream_data_state_rejections_do_not_mutate():
    """Every rejected stream-level data-state call leaves data_state and data_changes exactly as they were."""
    ins = "TEST-BUY"
    sr = list(series(BASE + [F, F, F], ins, gap_after=49))
    st = ConfirmationStream(ins, TF, market(ins))
    for c in sr[:50]:
        st.on_candle(c)
    t49 = sr[49].ts + TFD                     # close of candle 49: the first valid data-event instant (F-D2)

    def frozen(call, *a):
        before = (st.data_state, list(st.data_changes), len(st.candles), list(st.setups))
        assert raises(ValueError, call, *a)
        assert (st.data_state, list(st.data_changes), len(st.candles), list(st.setups)) == before

    frozen(st.mark_data_resumed, t49 + timedelta(seconds=5))           # resume without interruption
    frozen(st.mark_data_interrupted, "2026-01-05T13:05:10Z")             # string ts
    frozen(st.mark_data_interrupted, t49 - timedelta(seconds=1))        # inside the last candle (before its close)
    frozen(st.mark_data_interrupted, sr[49].ts - timedelta(seconds=1))  # before the last candle
    st.mark_data_interrupted(t49 + timedelta(seconds=10))
    frozen(st.mark_data_interrupted, t49 + timedelta(seconds=20))       # double interruption
    frozen(st.mark_data_resumed, t49 + timedelta(seconds=5))            # earlier than the interruption
    frozen(st.mark_data_resumed, None)                                  # not a datetime
    frozen(st.on_candle, sr[50])                                        # no candle while interrupted
    st.mark_data_resumed(t49 + timedelta(seconds=10))
    frozen(st.mark_data_interrupted, t49 + timedelta(seconds=9))        # earlier than the resume
    st.on_candle(sr[50])
    assert [d.state for d in st.data_changes] == [DATA_INTERRUPTED, DATA_RESUMED] and st.data_state == DATA_RESUMED



# ---------------------------------------------------------------- stream input validation (F-D1 / F-D2, 17.U)
def _forged(c, **kw):
    """A Candle object whose fields were changed after construction (bypassing Module A's checks)."""
    import dataclasses
    x = object.__new__(Candle)
    for f in dataclasses.fields(Candle):
        object.__setattr__(x, f.name, kw.get(f.name, getattr(c, f.name)))
    return x


def _fp(st):
    import pickle
    return pickle.dumps(st)                                  # byte-for-byte fingerprint of the whole stream state


def test_stream_rejects_invalid_candles_without_mutation():
    """F-D1: every invalid candle raises ValueError BEFORE any state change (byte-identical stream state), and the
    stream stays usable: the valid candle afterwards gives exactly the outputs of an untouched stream."""
    ins = "TEST-BUY"
    post = [E_BEAR, E_BULL, F, CU, F]
    sr = list(series(BASE + post, ins))
    ref = ConfirmationStream(ins, TF, market(ins))
    ref_out = [ref.on_candle(c) for c in sr]
    st = ConfirmationStream(ins, TF, market(ins))
    out = [st.on_candle(c) for c in sr[:49]]
    c49 = sr[49]
    bad = {
        "backward timestamp": Candle(49, sr[47].ts, c49.open, c49.high, c49.low, c49.close, c49.volume),
        "equal timestamp": Candle(49, sr[48].ts, c49.open, c49.high, c49.low, c49.close, c49.volume),
        "index skip": sr[50],
        "index repeat": sr[48],
        "index 0 again": sr[0],
        "bool index": _forged(c49, index=True),
        "string timestamp": _forged(c49, ts="2026-01-05T13:05:00Z"),
        "high below low": _forged(c49, high=c49.low - 1.0),
        "close above high": _forged(c49, close=c49.high + 1.0),
        "NaN open": _forged(c49, open=float("nan")),
        "infinite low": _forged(c49, low=float("-inf")),
        "string close": _forged(c49, close="116.30"),
        "negative volume": _forged(c49, volume=-1.0),
        "not a Candle": (49, c49.ts, c49.open, c49.high, c49.low, c49.close),
    }
    for name, c in bad.items():
        before = _fp(st)
        assert raises(ValueError, st.on_candle, c), name
        assert _fp(st) == before, "state changed by a rejected candle: %s" % name
        assert raises(ValueError, st.check_candle, c), name             # the pure check says the same
        assert _fp(st) == before, name
    for c in sr[49:]:                                                   # valid candle after the rejections
        out.append(st.on_candle(c))
    assert out == ref_out
    assert st.setups == ref.setups and st.pattern_states == ref.pattern_states
    assert st.confirmations == ref.confirmations and st.snapshots == ref.snapshots
    assert st.setups[0].status == CONFIRMED
    # first candle: only index 0 is accepted on an empty stream; nothing is recorded by a rejection
    st0 = ConfirmationStream(ins, TF, market(ins))
    before = _fp(st0)
    assert raises(ValueError, st0.on_candle, sr[1]) and _fp(st0) == before
    st0.on_candle(sr[0])


def test_stream_candle_before_a_recorded_data_event_is_rejected():
    """F-D2 (stream): a data event is recorded before the next candle is known, so its upper bound (the next open) is
    checked when that candle arrives: a candle opening before the last recorded event is rejected, state unchanged."""
    ins = "TEST-BUY"
    sr = list(series(BASE + [F, F, F], ins))                            # contiguous: window before 50 = 13:10 only
    st = ConfirmationStream(ins, TF, market(ins))
    for c in sr[:50]:
        st.on_candle(c)
    t50 = sr[50].ts
    st.mark_data_interrupted(t50)                                       # = close of 49: valid
    st.mark_data_resumed(t50 + timedelta(seconds=1))                    # lower bound fine; upper bound unknown yet
    before = _fp(st)
    assert raises(ValueError, st.on_candle, sr[50]) and _fp(st) == before
    # the same events are rejected up front in batch (identical rule)
    assert raises(ValueError, analyze_confirmations, series(BASE + [F, F, F], ins), ins, TF, market(ins),
                  data_events=[(50, DATA_INTERRUPTED, t50), (50, DATA_RESUMED, t50 + timedelta(seconds=1))])
    # boundary instant for both: accepted in stream and batch, identical records
    st = ConfirmationStream(ins, TF, market(ins))
    for c in sr[:50]:
        st.on_candle(c)
    st.mark_data_interrupted(t50); st.mark_data_resumed(t50)
    for c in sr[50:]:
        st.on_candle(c)
    rep = analyze_confirmations(series(BASE + [F, F, F], ins), ins, TF, market(ins),
                                data_events=[(50, DATA_INTERRUPTED, t50), (50, DATA_RESUMED, t50)])
    assert st.data_changes == rep.data_changes and st.setups == rep.setups
    # a timeframe is required to place a candle's close: without it a data event after a candle is rejected
    mk = MarketDataConfig.from_fixture({"instrument_id": ins, "tick_size": 0.01})
    st = ConfirmationStream(ins, TF, mk)
    st.on_candle(sr[0])
    before = _fp(st)
    assert raises(ValueError, st.mark_data_interrupted, sr[1].ts) and _fp(st) == before

# ---------------------------------------------------------------- missing tick size (CK-1)
def test_missing_tick_size_is_unscorable_not_expired():
    rep, ids = run([E_BEAR, E_BULL, CU, F, F, F], tick=None)
    s = only_setup(rep, ids)
    assert s.status == SWEEP_DETECTED and rep.pattern_states == [] and rep.confirmations == []
    assert [(d.index, d.code) for d in rep.diagnostics] == [(47, CONFIRMATION_UNSCORABLE)]


# ---------------------------------------------------------------- determinism, parity, replay, no look-ahead
SCENARIOS = [[E_BEAR, E_BULL, F, CU, F], [E_BEAR, E_BULL, IV, E_BEAR, E_BULL, CU, F], [E_BEAR, E_BULL, F, F, F, F],
             [F, BEAR_ENG_2ND, F, DOJI, F, F, F], [E_BEAR, E_BULL, E_BEAR, E_BULL, CU, F]]


def test_determinism_stream_batch_parity_prefix_replay_no_lookahead():
    for post in SCENARIOS:
        for side in ("BUY", "SELL"):
            rows = BASE + post
            if side == "SELL":
                rows = mirror(rows)
            ins = "TEST-%s" % side
            sr, mk = series(rows, ins), market(ins)
            a = analyze_confirmations(sr, ins, TF, mk)
            b = analyze_confirmations(sr, ins, TF, mk)
            assert a.setups == b.setups and a.confirmations == b.confirmations and a.outputs == b.outputs   # determinism
            st = ConfirmationStream(ins, TF, mk)
            outs = [(c.index, st.on_candle(c)) for c in sr]
            assert outs == a.outputs and st.setups == a.setups and st.pattern_states == a.pattern_states
            for k in range(S - 2, len(sr)):                                                  # prefix replay
                p = analyze_confirmations(sr.upto(k), ins, TF, mk)
                assert p.snapshots[-1] == a.snapshots[k], (side, k)
                assert p.confirmations == [c for c in a.confirmations if c.confirmation_candle <= k]
            assert no_lookahead_violations(lambda s: detect_confirmations(s, ins, TF, mk), sr, start=S - 2) == []
            k = S + 2                                                                       # future perturbation
            alt = [(o, h + 1.0, l - 0.3, c) for o, h, l, c in rows[k + 1:]]
            pa = analyze_confirmations(series(rows[:k + 1] + alt, ins), ins, TF, mk)
            assert pa.snapshots[:k + 1] == a.snapshots[:k + 1]
            assert [c for c in a.confirmations if c.confirmation_candle <= k] == \
                [c for c in pa.confirmations if c.confirmation_candle <= k]


def test_ohlc_unchanged_and_ids_have_no_random_part():
    post = [E_BEAR, E_BULL, F, CU, F]
    rows = BASE + post
    sr = series(rows, "TEST-BUY")
    before = [(c.open, c.high, c.low, c.close) for c in sr]
    rep = analyze_confirmations(sr, "TEST-BUY", TF, market("TEST-BUY"))
    assert [(c.open, c.high, c.low, c.close) for c in sr] == before == [tuple(map(float, r)) for r in rows]
    s = rep.setups[0]
    assert s.setup_id == "setup:sweep:SSL:47:pattern:TEST-BUY:5m:48:ENGULFING"
    assert rep.confirmations[0].id == "confirmation:pattern:TEST-BUY:5m:48:ENGULFING:51"



# ---------------------------------------------------------------- randomized property test vs an independent oracle
def _oracle(post, side):
    """Exact-rational re-statement of the Module D rules (no import of scanner_v6.entry.confirmation logic). Inputs
    taken from the already-tested layers: Module C patterns, Module B's candidate and its MB-3 invalidation."""
    from fractions import Fraction as Q
    from scanner_v6.entry.candlesticks import detect_candlestick_patterns
    ins = "TEST-%s" % side
    rows = BASE + list(post)
    if side == "SELL":
        rows = mirror(rows)
    sr = series(rows, ins)
    cands = B.analyze_setup_sweeps(sr).candidates
    if not cands or cands[0].index != S:
        return None
    cand = cands[0]
    k_struct = cand.closed_index if cand.status == B.INVALIDATED else None
    need = "BULLISH_BIAS" if side == "BUY" else "BEARISH_BIAS"
    fam = ["CLASSIC_DOJI", "GRAVESTONE_DOJI", "LONG_LEGGED_DOJI", "INVERTED_HAMMER", "DRAGONFLY_DOJI",
           "HAMMER_HANGING_MAN", "ENGULFING", "SHOOTING_STAR", "MORNING_STAR", "EVENING_STAR"]
    pats = detect_candlestick_patterns(sr, ins, TF, market(ins)).patterns
    Qp = sorted((p for p in pats if p.start_candle > S and p.end_candle <= S + 5 and p.bias == need
                 and p.pattern_label != "UNCLASSIFIED_SHAPE"),
                key=lambda p: (p.end_candle, p.start_candle, fam.index(p.pattern_type)))
    C = [(Q(repr(c.high)), Q(repr(c.low)), Q(repr(c.close))) for c in sr]
    eps = Q(1, 100) / 1000000
    n = len(C)

    def outcome(p):
        hi = max(C[i][0] for i in range(p.start_candle, p.end_candle + 1))
        lo = min(C[i][1] for i in range(p.start_candle, p.end_candle + 1))
        bull = p.bias == "BULLISH_BIAS"
        for k in range(p.end_candle + 1, min(p.end_candle + 3, n - 1) + 1):
            cl = C[k][2]
            if (cl > hi + eps) if bull else (cl < lo - eps):
                return ("CONFIRMED", k)
            if (cl < lo - eps) if bull else (cl > hi + eps):
                return ("INVALIDATED", k)
            if k == p.end_candle + 3:
                return ("EXPIRED", k)
        return ("DETECTED", None)

    tracked, status, at, conf = [], "SWEEP_DETECTED", None, None
    for k in range(S, n):
        if k_struct == k:
            status, at = "INVALIDATED", k
            break
        hits = [p for p in tracked if outcome(p) == ("CONFIRMED", k)]
        if hits:
            status, at, conf = "CONFIRMED", k, hits[0].id          # tracked is already in MD-1 order
            break
        tracked += [p for p in Qp if p.end_candle == k]
        if tracked and status == "SWEEP_DETECTED":
            status = "PATTERN_DETECTED"
        if k >= S + 5 and all(outcome(p)[1] is not None and outcome(p)[1] <= k for p in tracked):
            outs = [outcome(p)[0] for p in tracked]
            status = "INVALIDATED" if outs and all(o == "INVALIDATED" for o in outs) else "EXPIRED"
            at = k
            break
    return dict(status=status, at=at, conf=conf, tracked=[p.id for p in tracked],
                outcomes={p.id: outcome(p) for p in tracked})


CHOCH_CANDLE = (116.00, 116.05, 115.25, 115.30)
BLOCKS = [[E_BEAR, E_BULL]] * 4 + [[E_BEAR_WIDE, E_BULL], [MS_A, MS_M, MS_Z], [CU], [CU], [IV], [IV], [F], [F], [DOJI],
                                    [F, BEAR_ENG_2ND], [IV, (115.83, 116.20, 115.80, 116.15)]]


def _random_post(rng):
    post = []
    while len(post) < rng.randint(5, 12):
        r = rng.random()
        if r < 0.75:
            post += rng.choice(BLOCKS)
        elif r < 0.97:
            o, c = r2(rng.uniform(115.6, 116.6)), r2(rng.uniform(115.6, 116.6))
            post.append((o, r2(max(o, c) + rng.choice((0.0, 0.03, 0.1, 0.3))),
                         r2(max(115.41, min(o, c) - rng.choice((0.0, 0.03, 0.1, 0.3)))), c))
        else:
            post.append(CHOCH_CANDLE)                       # opposite CHoCH: structure invalidation path
    return post


def test_randomized_against_independent_oracle():
    import random
    rng = random.Random(20261124)
    seen = set()
    for i in range(200):
        post = _random_post(rng)
        for side in ("BUY", "SELL"):
            exp = _oracle(post, side)
            if exp is None:
                continue
            rep, ids = run(post, side)
            s = rep.setups[0]
            assert s.group_id == ids["sweep"]
            got_at = s.history[-1].index if s.status in (CONFIRMED, EXPIRED, INVALIDATED) else None
            assert (s.status, got_at, s.confirmed_pattern_id) == (exp["status"], exp["at"], exp["conf"]), (i, side, post)
            assert list(s.tracked) == exp["tracked"], (i, side)
            got = {p.pattern_id: (p.status, p.closed_index) for p in rep.pattern_states if p.setup_key == s.key}
            assert got == exp["outcomes"], (i, side, got, exp["outcomes"])
            seen.add(exp["status"])
            seen.update(o for o, _ in exp["outcomes"].values())
    assert {"CONFIRMED", "EXPIRED", "INVALIDATED", "PATTERN_DETECTED"} <= seen, seen   # every branch exercised

if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
