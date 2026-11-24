#!/usr/bin/env python3
"""Module B: liquidity pools, SWEEP / REPEAT_SWEEP / TAKEN, sweep groups, and the CHoCH -> reversal-confirming BOS ->
sweep candidate link. Rules: liquidity register (LQ-01..22, LS-S02/S09/S11, LP-12, G-1..G-11), spec CK-15..CK-18, OQ-4,
OQ-5, 17.S. Every scenario also runs mirrored (p -> 200 - p: BSL <-> SSL, BUY <-> SELL).

    python tests/scanner_v6/test_liquidity.py   (or: python -m pytest tests/scanner_v6)
"""
import inspect
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import FIXTURES, raises, run_main  # noqa: E402

from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.data.integrity import CandleUpdate, CompletedCandleGate, GapKind, detect_gaps  # noqa: E402
from scanner_v6.engine import no_lookahead_violations, replay_audit  # noqa: E402
from scanner_v6.liquidity.liquidity_pools import (ACTIVE, BSL, SSL, SWEPT, TAKEN, pool_from_swing,  # noqa: E402
                                                  pool_id)
from scanner_v6.liquidity.setup_sweep import (BUY, CONFIRMED, EXPIRED, INVALIDATED, PENDING, SELL,  # noqa: E402
                                              SetupSweepStream, analyze_setup_sweeps)
from scanner_v6.liquidity.sweep import (REPEAT_SWEEP, SWEEP, LiquidityEvent, LiquidityStream, SweepGroup,  # noqa: E402
                                        analyze_liquidity, classify, detect_liquidity, liquidity_event_id,
                                        sweep_group_id)
from scanner_v6.models import LiquidityPool, PoolSide  # noqa: E402
from scanner_v6.structure.choch import analyze_structure  # noqa: E402
from scanner_v6.structure.swings import detect_swings  # noqa: E402

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
CHD = {c["case_id"]: c for c in json.load(open(os.path.join(FIXTURES, "choch_v0_9_fixtures.draft.json")))["decidable"]}
B17 = [(x["o"], x["h"], x["l"], x["c"]) for x in CHD["CHD01"]["candles"][:17]]   # register base series (zero-based)
P98, P109, P101, P116 = ("pool:swing:%s:fixed-window-strict:L2R2" % s for s in ("low:3", "high:6", "low:9", "high:13"))


def mirror(rows):
    return [(200 - o, 200 - l, 200 - h, 200 - c) for o, h, l, c in rows]


def mpid(p):
    return p.replace(":low:", ":TMP:").replace(":high:", ":low:").replace(":TMP:", ":high:")


def series(rows, gap_after=None):
    ts = [T0 + timedelta(minutes=5 * j + (60 if gap_after is not None and j > gap_after else 0)) for j in range(len(rows))]
    return CandleSeries.from_rows([(t,) + tuple(r) for t, r in zip(ts, rows)], "SYN", "5m")


def lq(rows):
    return analyze_liquidity(series(rows))


def evs(rep, k=None):
    return [(e.index, e.name, e.pool_id, e.group_id) for e in rep.events if k is None or e.index == k]


def both(rows):
    return lq(rows), lq(mirror(rows))


def flip_side(s):
    return {BSL: SSL, SSL: BSL, "BSL_SWEEP": "SSL_SWEEP", "SSL_SWEEP": "BSL_SWEEP"}.get(s, s)


def mirrored(rep):
    """The mirror report's events translated back to the original side names / pool ids."""
    return [(k, flip_side(n), mpid(p), g and "sweep:%s:%s" % (flip_side(g.split(":")[1]), g.split(":")[2]))
            for k, n, p, g in evs(rep)]


def causal(rows):
    s = series(rows)
    assert no_lookahead_violations(detect_liquidity, s) == []
    assert not any(replay_audit(s, detector=detect_liquidity, make_stream=lambda: LiquidityStream()).findings.values())
    full = analyze_liquidity(s)
    for k in range(len(s)):
        p = analyze_liquidity(s.upto(k))
        assert p.timeline == full.timeline[:k + 1] and [e.id for e in p.events] == \
            [e.id for e in full.events if e.index <= k], k


# ---------------------------------------------------------------- pools: creation, ids, activation timing
def test_every_confirmed_swing_creates_one_pool_with_the_approved_id_price_and_side():
    s = series(B17)
    rep = analyze_liquidity(s)
    sw = detect_swings(s)
    assert [p.id for p in rep.pools] == [pool_id(x.id) for x in sw] == [P98, P109, P101, P116]
    for p, x in zip(rep.pools, sw):
        assert p.price == x.price and p.related == (x.id,) and p.stamp == x.stamp
        assert p.side is (PoolSide.ABOVE if x.kind.value == "high" else PoolSide.BELOW)
    assert [p.confirmed_index for p in rep.pools] == [5, 8, 11, 15]        # register: SSL 98 from c7 (k6), etc.
    assert raises(ValueError, pool_id, "") and raises(ValueError, pool_from_swing, "x")


def test_pool_is_evaluated_only_from_the_candle_after_its_confirmation():
    rep = lq(B17)
    for k, (pid, conf) in enumerate(((P98, 5), (P109, 8), (P101, 11), (P116, 15))):
        assert pid not in rep.states_after(conf - 1) and rep.states_after(conf)[pid] in (ACTIVE, TAKEN)
    # LS04: c17 (k16) wicks over BSL 116 (confirmed k15): the first evaluable candle, k16, already sweeps it
    rows = B17[:16] + [(107, 117, 106.5, 115)]
    for r, pid, name in ((lq(rows), P116, "BSL_SWEEP"), (lq(mirror(rows)), mpid(P116), "SSL_SWEEP")):
        assert evs(r, 16) == [(16, name, pid, "sweep:%s:16" % name[:3])]


def test_dual_pivot_candle_gives_two_pools():
    rows = [(10, 11, 9, 10), (10, 11.5, 8.5, 10), (10, 14, 6, 10), (10, 12, 8, 10), (10, 11, 9, 10)]
    rep = lq(rows)
    assert sorted(p.side.value for p in rep.pools) == ["above", "below"] and {p.index for p in rep.pools} == {2}


# ---------------------------------------------------------------- wick sweep vs TAKEN, equality, epsilon
def test_wick_sweep_vs_taken_both_sides():
    for name, rows, want in (("LS01", B17 + [(104, 105, 100, 102)], [(17, "SSL_SWEEP", P101, "sweep:SSL:17")]),
                             ("LS02", B17 + [(104, 105, 99, 100)], [(17, "TAKEN", P101, None)])):
        rep, mir = both(rows)
        assert evs(rep, 17) == want, name
        assert [e for e in mirrored(mir) if e[0] == 17] == want, name
        assert rep.final_state[P101] == (SWEPT if want[0][1] != "TAKEN" else TAKEN)
        assert rep.final_state[P98] == ACTIVE                                # untouched deeper pool


def test_equality_boundaries_follow_lq08_exactly():
    P = 101.0
    cases = [((104, 105, 100, 101.0), SWEEP),            # wick beyond, close == P -> SWEEP (LQ-08 equality sub-case)
             ((104, 105, 101.0, 101.0), None),           # low == P: no strict penetration (LQ-09 d = 0)
             ((104, 105, 101.0, 102), None),
             ((104, 105, 100, 100.999), TAKEN)]           # close strictly beyond -> TAKEN (LS-S02)
    for row, want in cases:
        rep = lq(B17 + [row])
        got = [e.event_type for e in rep.events if e.index == 17 and e.pool_id == P101]
        assert got == ([want] if want else []), row
        rm = lq(mirror(B17 + [row]))
        assert [e.event_type for e in rm.events if e.index == 17 and e.pool_id == mpid(P101)] == got
    assert classify(SSL, P, series([(104, 105, 100, 101.0)])[0]) == SWEEP


def test_no_tick_size_epsilon_is_applied_g8():
    eps = 1e-9
    assert [e.event_type for e in lq(B17 + [(104, 105, 101 - eps, 102)]).events if e.index == 17] == [SWEEP]
    assert [e.event_type for e in lq(B17 + [(104, 105, 100, 101 - eps)]).events if e.index == 17] == [TAKEN]
    assert list(inspect.signature(LiquidityStream).parameters) == ["swing_config"]   # no tick / instrument config


def test_open_price_plays_no_role_g4():
    a = lq(B17 + [(104, 105, 100, 102)])
    b = lq(B17 + [(100.5, 105, 100, 102)])
    assert evs(a) == evs(b)


# ---------------------------------------------------------------- lifecycle: repeat sweeps, TAKEN, no flip
def test_repeat_sweep_then_taken_then_inactive():
    rows = B17 + [(104, 105, 100, 102), (102, 103, 100.5, 102.5), (102.5, 103, 100.2, 101.5), (101.5, 102, 100, 100.5),
                  (100.5, 101.5, 99, 101.2)]
    rep, mir = both(rows)
    want = [(17, "SSL_SWEEP", P101, "sweep:SSL:17"), (18, "REPEAT_SWEEP", P101, None), (19, "REPEAT_SWEEP", P101, None),
            (20, "TAKEN", P101, None)]
    assert [e for e in evs(rep) if e[2] == P101] == want
    assert [e for e in mirrored(mir) if e[2] == P101] == want
    assert [(e.state_before, e.state_after) for e in rep.events if e.pool_id == P101] == \
        [(ACTIVE, SWEPT), (SWEPT, SWEPT), (SWEPT, SWEPT), (SWEPT, TAKEN)]
    assert not [e for e in rep.events if e.pool_id == P101 and e.index == 21]          # TAKEN: inactive, no flip
    assert not any(p.price == 101.0 and p.side is PoolSide.ABOVE for p in rep.pools)   # no automatic flip (LQ-16)
    causal(rows)


def test_taken_directly_from_active_and_no_later_sweep_ls11():
    rows = B17 + [(104, 105, 99, 100), (100, 101, 99.5, 100.5)]
    rep = lq(rows)
    assert [e for e in evs(rep) if e[2] == P101] == [(17, "TAKEN", P101, None)]


# ---------------------------------------------------------------- several pools on one candle, groups
def test_two_pools_same_side_share_one_group_ls05():
    rows = B17 + [(104, 105, 96, 102)]
    rep, mir = both(rows)
    assert evs(rep, 17) == [(17, "SSL_SWEEP", P98, "sweep:SSL:17"), (17, "SSL_SWEEP", P101, "sweep:SSL:17")]
    assert [(g.id, g.pool_ids) for g in rep.groups] == [("sweep:SSL:17", (P98, P101))]
    assert [(g.id, g.pool_ids) for g in mir.groups] == [("sweep:BSL:17", (mpid(P98), mpid(P101)))]
    g = rep.groups[0]
    assert g.related == tuple(liquidity_event_id(p, SWEEP, 17) for p in (P98, P101)) and g.index == 17


def test_opposite_side_sweep_and_bos_on_one_candle_ls07_ls_s11():
    rows = B17 + [(104, 117, 100, 116.5)]
    for rep, st, p101, p116, ssl in ((lq(rows), analyze_structure(series(rows)), P101, P116, "SSL"),
                                     (lq(mirror(rows)), analyze_structure(series(mirror(rows))), mpid(P101),
                                      mpid(P116), "BSL")):
        assert evs(rep, 17) == [(17, "%s_SWEEP" % ssl, p101, "sweep:%s:17" % ssl), (17, "TAKEN", p116, None)]
        assert [b.index for b in st.bos] == [11, 17]                      # BOS by the structure layer, unchanged
    causal(rows)


def test_bsl_and_ssl_sweeps_on_one_outside_candle_get_two_groups():
    rows = B17 + [(104, 117, 100, 110)]
    rep = lq(rows)
    assert evs(rep, 17) == [(17, "SSL_SWEEP", P101, "sweep:SSL:17"), (17, "BSL_SWEEP", P116, "sweep:BSL:17")]
    assert [g.id for g in rep.groups] == ["sweep:BSL:17", "sweep:SSL:17"]


def test_taken_and_repeat_sweep_carry_no_group_oq12_open():
    rows = B17 + [(104, 105, 100, 102), (102, 103, 100.5, 102.5), (102.5, 117, 102, 116.5)]
    rep = lq(rows)
    assert all(e.group_id is None for e in rep.events if e.event_type in (REPEAT_SWEEP, TAKEN))
    assert all(e.group_id == sweep_group_id(e.side, e.index) for e in rep.events if e.event_type == SWEEP)


# ---------------------------------------------------------------- ids, ordering, determinism, timestamps
def test_ids_are_deterministic_and_events_carry_actual_candle_time():
    rows = B17 + [(104, 105, 96, 102), (102, 103, 97, 102.5), (102.5, 117, 102, 116.5)]
    s = series(rows)
    a, b = analyze_liquidity(s), analyze_liquidity(s)
    assert [e.id for e in a.events] == [e.id for e in b.events] and a.events == b.events and a.groups == b.groups
    for e in a.events:
        assert e.id == liquidity_event_id(e.pool_id, e.event_type, e.index)
        assert e.index == e.confirmed_index and e.stamp.ts == s[e.index].ts and e.stamp.confirmed_ts == s[e.index].ts
        assert isinstance(e, LiquidityEvent) and e.related == (e.pool_id,)
    assert raises(ValueError, liquidity_event_id, "pool:x", "RUN", 1) and raises(ValueError, sweep_group_id, "UP", 1)


def test_stream_order_within_a_candle():
    rows = B17 + [(104, 117, 96, 110)]                     # SSL 98, SSL 101 and BSL 116 swept on one candle
    st = LiquidityStream()
    out = []
    for c in series(rows):
        out = st.on_candle(c)
    kinds = [type(x).__name__ for x in out]
    assert kinds == ["LiquidityEvent"] * 3 + ["SweepGroup"] * 2               # events in pool order, then groups
    assert [x.pool_id for x in out[:3]] == [P98, P101, P116]


# ---------------------------------------------------------------- causality and parity
def test_prefix_replay_no_lookahead_and_batch_stream_parity():
    for rows in (B17 + [(104, 105, 96, 102), (102, 103, 100.5, 102.5), (102.5, 117, 102, 116.5)],
                 B17 + [(104, 117, 100, 110), (110, 112, 99, 99.5)]):
        causal(rows)
        causal(mirror(rows))
        s = series(rows)
        st = LiquidityStream()
        streamed = [x for c in s for x in st.on_candle(c)]
        assert streamed == detect_liquidity(s)


# ---------------------------------------------------------------- data interruption, missing configuration
def test_only_completed_candles_drive_liquidity():
    rows = B17 + [(104, 105, 100, 102)]
    s = series(rows)
    gate, st, out = CompletedCandleGate(), LiquidityStream(), []
    for c in s:
        gate.feed(CandleUpdate(c.ts, c.open, c.high, 90.0, 95.0, 0.0, False))  # forming: would TAKE every SSL pool
        done = gate.feed(CandleUpdate(c.ts, c.open, c.high, c.low, c.close, c.volume, True))
        out += st.on_candle(done)
    assert out == detect_liquidity(s)                                          # forming values never leaked


def test_a_data_gap_creates_no_events_and_is_reported_by_module_a():
    rows = B17 + [(104, 105, 100, 102)]
    gapped = series(rows, gap_after=16)                                        # 60 minutes missing before k17
    rep = analyze_liquidity(gapped)
    assert evs(rep) == evs(lq(rows))                                           # events only on real candles
    assert [g.kind for g in detect_gaps(gapped, timedelta(minutes=5), None).gaps] == [GapKind.UNCLASSIFIED_GAP]


def test_missing_market_configuration_does_not_change_detection():
    rep = lq(B17 + [(104, 105, 100, 102)])                                    # no tick size, session or instrument
    assert evs(rep, 17) == [(17, "SSL_SWEEP", P101, "sweep:SSL:17")]


# ---------------------------------------------------------------- liquidity never changes structure (LQ-22)
def test_liquidity_does_not_change_structure_or_emit_bos_choch():
    for rows in (B17 + [(104, 105, 100, 102)], B17 + [(104, 117, 100, 116.5)], B17 + [(104, 105, 99, 100)]):
        s = series(rows)
        alone = analyze_structure(s)
        st = SetupSweepStream()
        for c in s:
            st.on_candle(c)
        assert [x.state for x in st.structure.timeline] == [x.state for x in alone.timeline]
        assert [e.id for e in st.structure.bos_events] == [b.id for b in alone.bos]
        assert all(type(x).__name__ in ("LiquidityEvent", "SweepGroup", "LiquidityPool") for x in detect_liquidity(s))
    rep = analyze_structure(series(B17 + [(104, 105, 100, 102)]))              # LS01: WICK_ONLY, still BULLISH 101
    assert rep.timeline[17].state == "BULLISH" and rep.timeline[17].protected_price == 101.0


# ---------------------------------------------------------------- strategy link: CHoCH -> confirming BOS -> sweep
# SR3 path (test_structure_reconciliation.py): BEARISH reversal confirmed at k21 (BOS vs a post-CHoCH swing low).
PATH_A = [(100, 101, 99, 100), (100, 102, 99.5, 101.5), (101.5, 105, 101, 104), (104, 104.5, 102, 103),
          (103, 103.5, 100, 101), (101, 102, 100.5, 101.8), (101.8, 104, 101.5, 103.8), (103.8, 106, 103.5, 104.5),
          (104.5, 105, 102.5, 103), (103, 103.5, 101.5, 102), (102, 103, 101.8, 102.8), (102.8, 104, 102.5, 103.5)]
SR3 = PATH_A + [(103.5, 104, 101.6, 103.0), (103, 103.5, 101.2, 102.0), (102, 102.8, 101.6, 102.5),
                (102.5, 103, 101.8, 102.2), (102.2, 102.4, 101.25, 101.3), (101.3, 101.5, 100.5, 100.8),
                (100.8, 101.4, 100.2, 101.0), (101, 101.6, 100.6, 101.4), (101.4, 101.8, 100.9, 101.2),
                (101.2, 101.3, 99.8, 99.9)]
AFTER = [(99.9, 100.4, 99.5, 100.0), (100, 100.6, 99.6, 100.2), (100.2, 102.0, 100.0, 101.0),   # k24: BSL sweep 101.8
         (101, 101.9, 100.5, 100.8),                                                             # k25: REPEAT_SWEEP
         (100.8, 101.5, 100.6, 101.2), (101.2, 102.5, 101.0, 101.5),                             # k27: sweep 102 group
         (101.5, 103, 101.4, 102.8)]                                                             # k28: bullish BOS


def setup_run(rows, close_at=None):
    """close_at = {k: status}: at candle k, close the pending candidate of the eligible BOS by its exact key."""
    st = SetupSweepStream()
    for c in series(rows):
        st.on_candle(c)
        if close_at and c.index in close_at:
            st.close_candidate(st.pending_for(st.current_bos_id).key, close_at[c.index], c.index, "test")
    return st


def test_reversal_confirming_bos_then_later_sweep_starts_one_candidate_both_directions():
    rows = SR3 + AFTER[:3]
    for st, setup, side in ((setup_run(rows), SELL, BSL), (setup_run(mirror(rows)), BUY, SSL)):
        assert [(c.bos_index, c.index, c.setup_side, c.sweep_side, c.status) for c in st.candidates] == \
            [(21, 24, setup, side, PENDING)]
        assert st.candidates[0].group_id == "sweep:%s:24" % side
        assert st.structure.bos_roles[st.candidates[0].bos_id] == "REVERSAL_CONFIRMING"


def test_repeat_sweep_does_not_start_a_candidate_and_one_pending_per_bos():
    st = setup_run(SR3 + AFTER[:6])
    assert [c.index for c in st.candidates] == [24]
    assert [(d.index, d.code) for d in st.diagnostics] == [(27, "CANDIDATE_ALREADY_PENDING")]   # k25 repeat: nothing


def test_after_expired_a_later_group_starts_a_new_candidate_oq5_r3():
    st = setup_run(SR3 + AFTER[:6], close_at={25: EXPIRED})
    assert [(c.index, c.status) for c in st.candidates] == [(24, EXPIRED), (27, PENDING)]


def test_after_confirmed_the_bos_creates_no_other_setup_oq5_r4():
    st = setup_run(SR3 + AFTER[:6], close_at={25: CONFIRMED})
    assert [(c.index, c.status) for c in st.candidates] == [(24, CONFIRMED)]
    assert [(d.index, d.code) for d in st.diagnostics] == [(27, "BOS_ALREADY_CONFIRMED")]


def test_opposite_bos_invalidates_and_ends_eligibility_ck18_oq5_r5():
    for rows in (SR3 + AFTER, mirror(SR3 + AFTER)):
        st = setup_run(rows)
        assert [(c.index, c.status, c.closed_index) for c in st.candidates] == [(24, INVALIDATED, 28)]
        assert ("BOS_ELIGIBILITY_ENDED", 28) in {(d.code, d.index) for d in st.diagnostics}
        assert st.current is None


def test_sweep_on_the_bos_candle_cannot_qualify_ck17():
    rows = SR3[:21] + [(101.2, 106.5, 99.8, 99.9)]          # k21: confirming bearish BOS + BSL sweeps of 105 / 106
    for st, side in ((setup_run(rows), BSL), (setup_run(mirror(rows)), SSL)):
        assert [g.id for g in st.liquidity.groups if g.index == 21] == ["sweep:%s:21" % side]
        assert st.candidates == [] and [(d.index, d.code) for d in st.diagnostics] == [(21, "SWEEP_ON_BOS_CANDLE")]
        assert st.structure.bos_roles[[b for b in st.structure.bos_events if b.index == 21][0].id] == \
            "REVERSAL_CONFIRMING"


def test_continuation_bos_never_starts_a_setup():
    fb_replace = PATH_A + [(103.5, 105.5, 103, 105), (105, 105.2, 103.2, 103.6), (103.6, 104, 102.8, 103.2),
                           (103.2, 104.5, 103, 104.3), (104.3, 106, 104, 105.9), (105.9, 106, 102.6, 103.2)]
    for rows in (fb_replace, mirror(fb_replace)):
        st = setup_run(rows)
        roles = st.structure.bos_roles
        assert "CONTINUATION" in roles.values() and "REVERSAL_CONFIRMING" not in roles.values()
        bos_k = [b.index for b in st.structure.bos_events if roles[b.id] == "CONTINUATION"][0]
        assert any(g.index > bos_k for g in st.liquidity.groups)              # a sweep group after the BOS (k17)
        assert st.candidates == []


def test_setup_link_prefix_replay_matches_snapshots():
    rows = SR3 + AFTER
    for r in (rows, mirror(rows)):
        s = series(r)
        full = analyze_setup_sweeps(s)
        for k in range(len(s)):
            assert analyze_setup_sweeps(s.upto(k)).snapshots[-1] == full.snapshots[k], k


def test_close_candidate_rejects_bad_calls():
    st = setup_run(SR3 + AFTER[:3])
    key = st.candidates[0].key
    assert raises(ValueError, st.close_candidate, key, "PENDING", 24, "x")
    assert raises(KeyError, st.close_candidate, ("bos:none", "sweep:BSL:1"), EXPIRED, 24, "x")
    assert raises(ValueError, st.close_candidate, key, EXPIRED, 23, "x")             # not the candle just processed
    st.close_candidate(key, EXPIRED, 24, "x")
    assert raises(ValueError, st.close_candidate, key, EXPIRED, 24, "x")



# ---------------------------------------------------------------- owner decisions + lifecycle corrections (23 Nov 2026)
# 17.S OWNER APPROVED: bullish reversal-confirming BOS -> BUY -> SSL sweep; bearish -> SELL -> BSL sweep; a BOS stays
# eligible until an opposite CHoCH or opposite BOS (continuation BOS does not end it); REPEAT_SWEEP / TAKEN ineligible.
CONT = SR3 + [(99.9, 100.4, 99.5, 100.0), (100, 100.6, 99.6, 100.2), (100.2, 100.5, 99.7, 99.9),
              (99.9, 100.0, 99.0, 99.2),                                  # k25: continuation BOS (same direction)
              (99.2, 102.0, 99.1, 100.0)]                                 # k26: eligible-side sweep group
CHOCH_END = SR3 + AFTER[:6] + [(101.5, 101.95, 101.4, 101.9)]             # k28: opposite CHoCH, no opposite BOS
BOS_END = SR3 + [(99.9, 100.4, 99.5, 100.0), (100, 100.6, 99.6, 100.2), (100.2, 102.0, 100.0, 101.0),
                 (101, 101.2, 100.3, 100.5), (100.5, 100.9, 100.1, 100.4), (100.4, 101.3, 100.2, 101.0),
                 (101, 101.1, 100.5, 100.7), (100.7, 100.9, 100.3, 100.6),
                 (100.6, 101.6, 100.5, 101.5)]                            # k30: opposite BOS, no CHoCH


def both_setup(rows, **kw):
    return ((setup_run(rows, **kw), SELL, BSL, "bullish"), (setup_run(mirror(rows), **kw), BUY, SSL, "bearish"))


def test_owner_decision_setup_side_mapping_both_directions():
    for st, setup, side, _ in both_setup(SR3 + AFTER[:3]):
        b = [x for x in st.structure.bos_events if x.id == st.candidates[0].bos_id][0]
        assert (b.direction.value, st.candidates[0].setup_side, st.candidates[0].sweep_side) == \
            ({SELL: "bearish", BUY: "bullish"}[setup], setup, side)


def test_dual_pivot_pool_creation_mirrored():
    rows = [(10, 11, 9, 10), (10, 11.5, 8.5, 10), (10, 14, 6, 10), (10, 12, 8, 10), (10, 11, 9, 10)]
    for r in (lq(rows), lq(mirror(rows))):
        assert [p.id for p in r.pools] == ["pool:swing:high:2:fixed-window-strict:L2R2",
                                           "pool:swing:low:2:fixed-window-strict:L2R2"]   # high before low, same candle
        assert [p.confirmed_index for p in r.pools] == [4, 4] and [p.side for p in r.pools] == \
            [PoolSide.ABOVE, PoolSide.BELOW]
    assert [p.price for p in lq(rows).pools] == [14, 6] and [p.price for p in lq(mirror(rows)).pools] == [194, 186]


def test_within_candle_event_and_group_order_mirrored():
    rows = B17 + [(104, 117, 96, 110)]
    for r, ids, groups in ((rows, [P98, P101, P116], ["sweep:BSL:17", "sweep:SSL:17"]),
                           (mirror(rows), [mpid(P98), mpid(P101), mpid(P116)], ["sweep:BSL:17", "sweep:SSL:17"])):
        st = LiquidityStream()
        for c in series(r):
            out = st.on_candle(c)
        assert [type(x).__name__ for x in out] == ["LiquidityEvent"] * 3 + ["SweepGroup"] * 2
        assert [x.pool_id for x in out[:3]] == ids and [g.id for g in out[3:]] == groups   # groups: BSL then SSL
        sides = {g.id: g.pool_ids for g in out[3:]}
        assert all(e.group_id in sides and e.pool_id in sides[e.group_id] for e in out[:3])


def test_candidate_lifecycle_pending_expired_invalidated_confirmed_mirrored():
    for st, *_ in both_setup(SR3 + AFTER[:3]):
        assert [c.status for c in st.candidates] == [PENDING]
    for st, *_ in both_setup(SR3 + AFTER[:6], close_at={25: EXPIRED}):
        assert [(c.index, c.status, c.closed_index) for c in st.candidates] == [(24, EXPIRED, 25), (27, PENDING, None)]
    for st, *_ in both_setup(SR3 + AFTER[:6], close_at={25: CONFIRMED}):
        assert [(c.index, c.status) for c in st.candidates] == [(24, CONFIRMED)]
        assert st.bos_states[st.candidates[0].bos_id].confirmed_setup
        assert [(d.index, d.code) for d in st.diagnostics] == [(27, "BOS_ALREADY_CONFIRMED")]
    for st, *_ in both_setup(SR3 + AFTER):
        assert [(c.index, c.status, c.closed_index) for c in st.candidates] == [(24, INVALIDATED, 28)]


def test_one_pending_per_bos_and_close_changes_only_that_candidate():
    for st, *_ in both_setup(SR3 + AFTER[:6], close_at={25: EXPIRED}):
        first, second = st.candidates
        assert st.pending_for(first.bos_id) == second and first.bos_id == second.bos_id
        before = first
        st.close_candidate(second.key, CONFIRMED, 27, "module C")
        assert st.candidate(first.key) == before                              # untouched (status, closed_index, by)
        assert st.candidate(second.key).status == CONFIRMED and st.pending_for(first.bos_id) is None
        assert st.snapshots[-1] == tuple(st.candidates)
    for st, *_ in both_setup(SR3 + AFTER[:6]):                                # second group blocked while pending
        assert len(st.candidates) == 1 and ("CANDIDATE_ALREADY_PENDING", 27) in {(d.code, d.index) for d in st.diagnostics}


def test_same_direction_continuation_bos_keeps_eligibility_mirrored():
    for st, setup, side, _ in both_setup(CONT):
        roles = {b.index: st.structure.bos_roles[b.id] for b in st.structure.bos_events}
        assert roles[21] == "REVERSAL_CONFIRMING" and roles[25] == "CONTINUATION"
        assert [(c.bos_index, c.index, c.setup_side, c.status) for c in st.candidates] == [(21, 26, setup, PENDING)]
        assert st.current is not None and st.current.eligible and st.current.ended_index is None
        assert not [d for d in st.diagnostics if d.code == "BOS_ELIGIBILITY_ENDED"]


def test_opposite_choch_alone_ends_eligibility_and_invalidates_mirrored():
    for st, setup, side, opp in both_setup(CHOCH_END):
        assert not [b for b in st.structure.bos_events if b.index == 28]        # no BOS at k28: the CHoCH alone ends it
        c = st.candidates[0]
        assert (c.index, c.status, c.closed_index) == (24, INVALIDATED, 28) and c.closed_by.startswith("choch:%s:" % opp)
        assert st.bos_states[c.bos_id].ended_index == 28 and st.current is None


def test_opposite_bos_alone_ends_eligibility_and_invalidates_mirrored():
    for st, setup, side, opp in both_setup(BOS_END):
        k30 = [b for b in st.structure.bos_events if b.index == 30]
        assert [b.direction.value for b in k30] == [opp] and st.structure.timeline[30].state in ("BULLISH", "BEARISH")
        c = st.candidates[0]
        assert (c.index, c.status, c.closed_index, c.closed_by) == (24, INVALIDATED, 30, k30[0].id)
        assert st.bos_states[c.bos_id].ended_by == k30[0].id and st.current is None


def _inject(st, k, make):
    real = st.liquidity.on_candle

    def wrapped(c):
        out = real(c)
        return out + make(c) if c.index == k else out
    st.liquidity.on_candle = wrapped


def test_repeat_sweep_and_taken_never_start_candidates_mirrored():
    from scanner_v6.models import EventStamp
    for rows, side in ((SR3 + AFTER[:2], BSL), (mirror(SR3 + AFTER[:2]), SSL)):
        for etype in (REPEAT_SWEEP, TAKEN):
            st = SetupSweepStream()
            s = series(rows)
            _inject(st, 23, lambda c: [LiquidityEvent(liquidity_event_id("pool:x", etype, c.index),
                                                      EventStamp.from_candles(c, c), related=("pool:x",),
                                                      pool_id="pool:x", side=side, event_type=etype, name=etype,
                                                      level=c.close, extreme=c.close, close=c.close,
                                                      state_before=SWEPT, state_after=TAKEN if etype == TAKEN else SWEPT)])
            for c in s:
                st.on_candle(c)
            assert st.current is not None and st.candidates == []              # eligible, eligible side, no group
    for st, *_ in both_setup(SR3 + AFTER[:5], close_at={24: EXPIRED}):          # real k25 REPEAT_SWEEP after EXPIRED
        assert [e.event_type for e in st.liquidity.events if e.index == 25] == [REPEAT_SWEEP]
        assert [(c.index, c.status) for c in st.candidates] == [(24, EXPIRED)]
    for st, *_ in both_setup(CHOCH_END):                                        # real k28 TAKEN: no candidate from it
        assert [e.event_type for e in st.liquidity.events if e.index == 28] == [TAKEN]
        assert [c.index for c in st.candidates] == [24]


def test_same_candle_bos_sweep_rejection_with_lifecycle_mirrored():
    rows = SR3[:21] + [(101.2, 106.5, 99.8, 99.9)] + AFTER[:3]
    for st, setup, side, _ in both_setup(rows):
        assert [(d.index, d.code) for d in st.diagnostics][:1] == [(21, "SWEEP_ON_BOS_CANDLE")]
        assert all(c.index > 21 for c in st.candidates)


# ---------------------------------------------------------------- D5 terminator order (23 Nov 2026)
# PHASE1_2 D5: at close k, (1) BOS evaluation, (2) CHoCH evaluation, (3) state update. An opposite BOS and an opposite
# CHoCH on the same candle: the BOS is the terminating event (closed_by / ended_by).
def _run_collect(rows):
    from scanner_v6.structure.choch import CHoCHBreak
    st = SetupSweepStream()
    chochs = {}
    for c in series(rows):
        sev, _, _ = st.on_candle(c)
        chochs[c.index] = [e for e in sev if isinstance(e, CHoCHBreak)]
    return st, chochs


def test_same_candle_opposite_bos_and_choch_terminator_follows_d5_mirrored():
    for rows, setup, opp in ((SR3 + AFTER, SELL, "bullish"), (mirror(SR3 + AFTER), BUY, "bearish")):
        st, chochs = _run_collect(rows)
        bos28 = [b for b in st.structure.bos_events if b.index == 28]
        assert [b.direction.value for b in bos28] == [opp] and [e.direction.value for e in chochs[28]] == [opp]
        c = st.candidates[0]
        assert (c.setup_side, c.index, c.status, c.closed_index) == (setup, 24, INVALIDATED, 28)
        assert c.closed_by == bos28[0].id and c.closed_by.startswith("bos:%s:" % opp)       # BOS (D5 step 1) first
        assert c.closed_by != chochs[28][0].id
        s = st.bos_states[c.bos_id]
        assert (s.eligible, s.ended_index, s.ended_by) == (False, 28, bos28[0].id) and st.current is None
        ended = [d for d in st.diagnostics if d.code == "BOS_ELIGIBILITY_ENDED"]
        assert [(d.index, d.bos_id) for d in ended] == [(28, c.bos_id)] and ended[0].detail.startswith(bos28[0].id)
        assert len([x for x in st.candidates if x.status == PENDING]) == 0                 # one-pending invariant kept


def test_terminating_events_order_is_d5_regardless_of_input_order():
    from scanner_v6.liquidity.setup_sweep import terminating_events
    st, chochs = _run_collect(SR3 + AFTER)
    bos28 = [b for b in st.structure.bos_events if b.index == 28]
    ch28 = chochs[28]
    bear = st.bos_states[st.candidates[0].bos_id].direction
    sev_choch_first = list(ch28) + [object()]                                        # CHoCH listed first on purpose
    assert [e.id for e in terminating_events(bear, bos28, sev_choch_first)] == [bos28[0].id, ch28[0].id]
    assert [e.id for e in terminating_events(bear, [], ch28)] == [ch28[0].id]        # CHoCH alone
    assert [e.id for e in terminating_events(bear, bos28, [])] == [bos28[0].id]      # BOS alone
    assert terminating_events(bos28[0].direction, bos28, ch28) == []                 # same direction: nothing


def test_terminator_alone_cases_and_continuation_exact_ids_mirrored():
    for rows_ch, rows_bos, rows_cont, opp in ((CHOCH_END, BOS_END, CONT, "bullish"),
                                              (mirror(CHOCH_END), mirror(BOS_END), mirror(CONT), "bearish")):
        st, chochs = _run_collect(rows_ch)                                           # opposite CHoCH alone at k28
        assert not [b for b in st.structure.bos_events if b.index == 28] and len(chochs[28]) == 1
        assert st.candidates[0].closed_by == chochs[28][0].id == st.bos_states[st.candidates[0].bos_id].ended_by
        st, chochs = _run_collect(rows_bos)                                          # opposite BOS alone at k30
        k30 = [b for b in st.structure.bos_events if b.index == 30]
        assert chochs[30] == [] and [b.direction.value for b in k30] == [opp]
        assert st.candidates[0].closed_by == k30[0].id == st.bos_states[st.candidates[0].bos_id].ended_by
        st, chochs = _run_collect(rows_cont)                                         # continuation BOS at k25
        assert [b.direction.value for b in st.structure.bos_events if b.index == 25] != [opp]
        assert st.current is not None and st.current.ended_by is None
        assert [(c.index, c.status) for c in st.candidates] == [(26, PENDING)]


def test_new_lifecycle_prefix_replay_and_stream_batch_parity():
    for rows in (CONT, CHOCH_END, BOS_END):
        for r in (rows, mirror(rows)):
            s = series(r)
            full = analyze_setup_sweeps(s)
            for k in range(len(s)):
                assert analyze_setup_sweeps(s.upto(k)).snapshots[-1] == full.snapshots[k], k
            st = SetupSweepStream()
            for c in s:
                st.on_candle(c)
            assert st.candidates == full.candidates and st.diagnostics == full.diagnostics

if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
