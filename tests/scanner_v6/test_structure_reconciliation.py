#!/usr/bin/env python3
"""Structure reconciliation SR-1..SR-6 (delegated owner decisions, spec 17.R, 23 Nov 2026) for
scanner_v6/structure/choch.py. Hand-built candles; every case is checked in both directions (mirror p -> 200 - p), with
boundary candles, same-candle timing, prefix replay and batch / stream parity.

    python tests/scanner_v6/test_structure_reconciliation.py   (or: python -m pytest tests/scanner_v6)
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ROOT, run_main  # noqa: E402

from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.engine import no_lookahead_violations, replay_audit  # noqa: E402
from scanner_v6.models import BOSEvent, Direction, EventStamp, SwingKind  # noqa: E402
from scanner_v6.structure.bos import bos_id  # noqa: E402
from scanner_v6.structure.choch import (BOS_ROLES, CONTINUATION, COUNTER_STRUCTURE, PRE_STRUCTURE,  # noqa: E402
                                        REVERSAL_CONFIRMING, REVERSAL_INVALIDATING, SETUP_ELIGIBLE_BOS_ROLES,
                                        TRANSITION_AMBIGUOUS, TRANSITION_REF_BEFORE_CHOCH, CHoCHBreak,
                                        StructureStateChange, StructureStream, analyze_structure, detect_structure)

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
CHD = {c["case_id"]: c for c in json.load(open(os.path.join(ROOT, "research", "v6", "specs", "choch_v0_9",
                                                            "choch_fixtures.draft.json")))["decidable"]}
CHD01 = [(x["o"], x["h"], x["l"], x["c"]) for x in CHD["CHD01"]["candles"]]


def mirror(rows):
    return [(200 - o, 200 - l, 200 - h, 200 - c) for o, h, l, c in rows]


def series(rows):
    return CandleSeries.from_rows([(T0 + timedelta(minutes=5 * j),) + tuple(r) for j, r in enumerate(rows)], "SYN", "5m")


def run(rows):
    return analyze_structure(series(rows))


def both(rows):
    """(bullish-version report, bearish mirror report)."""
    return run(rows), run(mirror(rows))


def changes(rep):
    return [(e.index, e.state_before, e.state_after, e.cause) for e in rep.events if isinstance(e, StructureStateChange)]


def chochs(rep):
    return [(e.index, e.direction.value, e.level) for e in rep.events if isinstance(e, CHoCHBreak)]


def prot(rep, k):
    return rep.timeline[k].protected_price


def codes(rep):
    return {(d.code, d.index) for d in rep.diagnostics}


def roles(rep):
    return [(b.index, b.direction.value, rep.bos_roles[b.id]) for b in rep.bos]


def m(p):
    return None if p is None else 200 - p


def flip(s):
    return {"BULLISH": "BEARISH", "BEARISH": "BULLISH", "UNKNOWN": "UNKNOWN", "TRANSITION(bullish)": "TRANSITION(bearish)",
            "TRANSITION(bearish)": "TRANSITION(bullish)", "bullish": "bearish", "bearish": "bullish"}.get(s, s)


def mirrored_changes(rep):
    return [(k, flip(a), flip(b), cause) for k, a, b, cause in changes(rep)]


def causal(rows):
    s = series(rows)
    assert no_lookahead_violations(detect_structure, s) == []
    assert not any(replay_audit(s, detector=detect_structure, make_stream=lambda: StructureStream()).findings.values())
    full = analyze_structure(s)
    for k in range(len(s)):                                   # every prefix: same timeline, events and roles so far
        p = analyze_structure(s.upto(k))
        assert [(x.state, x.protected_swing_id) for x in p.timeline] == \
            [(x.state, x.protected_swing_id) for x in full.timeline[:k + 1]], k
        assert [e.id for e in p.events] == [e.id for e in full.events if e.index <= k], k
        assert p.bos_roles == {b.id: full.bos_roles[b.id] for b in full.bos if b.index <= k}, k


# ---------------------------------------------------------------- base paths (zero-based candle k)
# PATH_A: no BOS at all before establishment; HH 105 -> 106 is wick-only, lows 100 -> 101.5 (HL, k9).
# The structure is established BULLISH at close 11 (L 101.5 confirms) with NO P-B origin -> SR-2 fallback 101.5.
PATH_A = [(100, 101, 99, 100), (100, 102, 99.5, 101.5), (101.5, 105, 101, 104), (104, 104.5, 102, 103),
          (103, 103.5, 100, 101), (101, 102, 100.5, 101.8), (101.8, 104, 101.5, 103.8), (103.8, 106, 103.5, 104.5),
          (104.5, 105, 102.5, 103), (103, 103.5, 101.5, 102), (102, 103, 101.8, 102.8), (102.8, 104, 102.5, 103.5)]


def test_path_a_has_no_bos_and_is_established_at_11():
    rep, mir = both(PATH_A)
    assert rep.bos == [] and mir.bos == []
    assert changes(rep) == [(11, "UNKNOWN", "BULLISH", "ESTABLISHED")]
    assert mirrored_changes(mir) == changes(rep)


# ---------------------------------------------------------------- SR-1 sticky origin
# S-1 base variant (research/v6/audits/S1_PROTECTED_RESELECTION_ANALYSIS.md): CHD01 c1-c16 + c17-c22.
S1 = CHD01[:16] + [(107.5, 110, 107.5, 109), (109, 111, 108, 110), (110, 117, 104, 116.5), (116.5, 118, 104.5, 117),
                   (117, 119, 106, 118), (118, 118.5, 105, 105.5)]


def test_sr1_activated_origin_is_kept_when_a_later_leg_low_fails_a5():
    rep, mir = both(S1)
    for r, f in ((rep, lambda p: p), (mir, m)):
        assert [prot(r, k) for k in range(15, 21)] == [f(101.0), f(101.0), f(101.0), f(106.0), f(106.0), f(106.0)]
        assert ("ACTIVATED", 18) in codes(r) and ("NOT_QUALIFIED", 20) in codes(r)   # 104 (k18) fails A5 vs 106
        assert chochs(r) == [(21, "bearish" if r is rep else "bullish", f(106.0))]   # CHoCH against the KEPT 106
    causal(S1)


def test_sr1_a5_base_is_the_immediately_previous_swing():
    rep = run(S1)
    note = [d for d in rep.diagnostics if d.code == "NOT_QUALIFIED" and d.index == 20][0]
    assert "104" in note.detail                              # 104 compared with 106 (k15, the swing just before it)


# ---------------------------------------------------------------- SR-2 fallback at establishment
FB_CHOCH = PATH_A + [(103.5, 104, 101, 101.2)]                # k12 closes 101.2 < fallback 101.5


def test_sr2_fallback_is_the_establishing_hl_in_force_from_the_next_candle():
    rep, mir = both(PATH_A)
    for r, f in ((rep, lambda p: p), (mir, m)):
        assert prot(r, 10) is None and prot(r, 11) == f(101.5)
        assert r.timeline[11].protected_swing_id.startswith("swing:%s:9:" % ("low" if r is rep else "high"))
        assert [e.protected_swing_id for e in r.events if isinstance(e, StructureStateChange)] == \
            [r.timeline[11].protected_swing_id]


def test_sr2_fallback_is_consumed_by_a_choch_like_a_protected_swing():
    rep, mir = both(FB_CHOCH)
    assert chochs(rep) == [(12, "bearish", 101.5)] and chochs(mir) == [(12, "bullish", 98.5)]
    for r in (rep, mir):
        assert r.timeline[12].state.startswith("TRANSITION") and prot(r, 12) is None
        assert roles(r) == [(12, "bearish" if r is rep else "bullish", COUNTER_STRUCTURE)]   # same-candle BOS
    causal(FB_CHOCH)


def test_sr2_equal_close_does_not_consume_the_fallback():
    rows = PATH_A + [(103.5, 104, 101, 101.5), (101.5, 103, 101.3, 102.5)]   # close == 101.5 (CHU04 strict)
    rep, mir = both(rows)
    for r, f in ((rep, lambda p: p), (mir, m)):
        assert chochs(r) == [] and ("EXACT_LEVEL_CLOSE", 12) in codes(r) and prot(r, 13) == f(101.5)


FB_REPLACE = PATH_A + [(103.5, 105.5, 103, 105), (105, 105.2, 103.2, 103.6), (103.6, 104, 102.8, 103.2),
                       (103.2, 104.5, 103, 104.3), (104.3, 106, 104, 105.9), (105.9, 106.2, 102.5, 102.6)]


def test_sr2_first_qualifying_origin_replaces_the_fallback_for_good():
    rep, mir = both(FB_REPLACE)
    for r, f in ((rep, lambda p: p), (mir, m)):
        assert [prot(r, k) for k in range(11, 17)] == [f(101.5)] * 5 + [f(102.8)]   # origin L 102.8 (k14) from k17
        assert ("ACTIVATED", 16) in codes(r)
        assert roles(r) == [(16, "bullish" if r is rep else "bearish", CONTINUATION),
                            (17, "bearish" if r is rep else "bullish", COUNTER_STRUCTURE)]
        assert chochs(r) == [(17, "bearish" if r is rep else "bullish", f(102.8))]   # against the origin, not 101.5
    causal(FB_REPLACE)


def test_sr2_does_not_apply_when_a_qualifying_origin_exists():
    rep = run(CHD01[:17])                                     # CHD01: BOS c12 origin 101 is the protected level
    est = [e for e in rep.events if isinstance(e, StructureStateChange)]
    assert prot(rep, est[0].index) == 101.0 and rep.timeline[est[0].index].protected_swing_id.startswith("swing:low:9:")


# ---------------------------------------------------------------- SR-6 establishment rejected
O9_BASE = [(100, 101, 99, 100), (100, 102, 99.5, 101.5), (101.5, 105, 101, 104), (104, 104.5, 102, 103),
           (103, 103.5, 100, 101), (101, 102, 101, 101.8), (101.8, 103, 101.2, 102.5), (102.5, 102.8, 100.8, 101),
           (101.2, 103, 101.1, 102.8), (102.8, 106, 102.5, 104), (104, 105, 101.5, 101.6)]
O9_REJECT = O9_BASE + [(101.6, 102, 100, 100.2)]             # k11: H 106 confirms; close 100.2 < candidate HL 100.8
O9_EQUAL = O9_BASE + [(101.6, 102, 100, 100.8)]              # k11: close == 100.8 -> not beyond (CHU04)


def test_sr6_establishment_rejected_when_close_is_beyond_the_candidate():
    rep, mir = both(O9_REJECT)
    for r in (rep, mir):
        assert changes(r) == [] and chochs(r) == []
        assert ("ESTABLISHMENT_REJECTED_O9", 11) in codes(r) and not any(c == "O9_UNRESOLVED" for c, _ in codes(r))
        assert r.timeline[11].state == "UNKNOWN" and prot(r, 11) is None
        assert roles(r) == [(11, "bearish" if r is rep else "bullish", PRE_STRUCTURE)]
    causal(O9_REJECT)


def test_sr6_equal_close_is_not_beyond_and_establishes():
    rep, mir = both(O9_EQUAL)
    for r, f in ((rep, lambda p: p), (mir, m)):
        assert changes(r) == [(11, "UNKNOWN", "BULLISH" if r is rep else "BEARISH", "ESTABLISHED")]
        assert prot(r, 11) == f(100.8) and r.bos == []


def test_sr6_rejection_uses_the_p_b_origin_when_there_is_one():
    rep = run([(x["o"], x["h"], x["l"], x["c"]) for x in CHD["CHD15"]["candles"]])
    assert changes(rep) == [] and ("ESTABLISHMENT_REJECTED_O9", 15) in codes(rep)   # candidate = origin 101
    assert "P-B origin" in [d.detail for d in rep.diagnostics if d.code == "ESTABLISHMENT_REJECTED_O9"][0]


# ---------------------------------------------------------------- SR-3 confirming BOS must break a post-CHoCH swing
SR3 = PATH_A + [(103.5, 104, 101.6, 103.0), (103, 103.5, 101.2, 102.0), (102, 102.8, 101.6, 102.5),
                (102.5, 103, 101.8, 102.2), (102.2, 102.4, 101.25, 101.3), (101.3, 101.5, 100.5, 100.8),
                (100.8, 101.4, 100.2, 101.0), (101, 101.6, 100.6, 101.4), (101.4, 101.8, 100.9, 101.2),
                (101.2, 101.3, 99.8, 99.9)]


def test_sr3_bos_on_a_pre_choch_swing_does_not_confirm():
    rep, mir = both(SR3)
    for r, f in ((rep, lambda p: p), (mir, m)):
        d = "bearish" if r is rep else "bullish"
        assert chochs(r) == [(16, d, f(101.5))]               # CHoCH vs the fallback; L 101.2 (k13, conf 15) not broken
        assert ("CONFIRMATION_REF_BEFORE_CHOCH", 17) in codes(r)
        assert r.timeline[17].state == "TRANSITION(%s)" % d   # k17 breaks 101.2, confirmed at 15 < 16: no confirmation
        assert roles(r) == [(17, d, TRANSITION_REF_BEFORE_CHOCH), (21, d, REVERSAL_CONFIRMING)]
        assert changes(r)[-1] == (21, "TRANSITION(%s)" % d, d.upper(), "REVERSAL_CONFIRMED")   # L 100.2 (k18, conf 20)
    causal(SR3)


def test_sr3_swing_confirmed_on_the_choch_candle_is_eligible_from_the_next_candle():
    # CHD10: CHoCH k17; the confirming BOS (k23) breaks L 97 (k18, conf 20) -> eligible. Earliest possible = CHoCH + 1.
    rows = [(x["o"], x["h"], x["l"], x["c"]) for x in CHD["CHD10"]["candles"]]
    rep, mir = both(rows)
    for r in (rep, mir):
        conf = [b for b in r.bos if r.bos_roles[b.id] == REVERSAL_CONFIRMING]
        sw = {s.id: s for s in r.swings}
        ch = [e for e in r.events if isinstance(e, CHoCHBreak)][0]
        assert len(conf) == 1 and sw[conf[0].broken_swing_id].confirmed_index >= ch.index and conf[0].index > ch.index


def test_sr3_boundary_reference_confirmed_exactly_on_the_choch_candle():
    # PATH_A + swing low 101.3 (k12, a wick under the fallback 101.5) that confirms at k14, the CHoCH candle (close 101.4).
    # It is eligible (confirmed on the CHoCH candle) but usable only from k15 (D5): k15 breaks it -> REVERSAL_CONFIRMED
    # at CHoCH + 1, the earliest possible candle.
    rows = PATH_A + [(103.5, 104, 101.3, 102.6), (102.6, 103, 101.6, 102.0), (102.0, 102.2, 101.35, 101.4),
                     (101.4, 101.6, 101.1, 101.2)]
    rep, mir = both(rows)
    for r in (rep, mir):
        d = "bearish" if r is rep else "bullish"
        sw = {s.id: s for s in r.swings}
        assert [c[0] for c in chochs(r)] == [14] and ("WICK_ONLY", 12) in codes(r)
        assert roles(r) == [(14, d, COUNTER_STRUCTURE), (15, d, REVERSAL_CONFIRMING)]   # k14: same-candle BOS vs 101.5
        conf = [b for b in r.bos if r.bos_roles[b.id] == REVERSAL_CONFIRMING][0]
        assert sw[conf.broken_swing_id].confirmed_index == 14 and conf.index == 15
        assert changes(r)[-1] == (15, "TRANSITION(%s)" % d, d.upper(), "REVERSAL_CONFIRMED")
    causal(rows)


# ---------------------------------------------------------------- SR-5 opposite BOS during TRANSITION
SR5 = PATH_A + [(103.5, 104, 101, 101.2), (101.2, 103, 101.1, 102.8), (102.8, 105, 102.5, 104.8),
                (104.8, 106.5, 104.5, 106.3)]


def test_sr5_opposite_bos_restores_the_prior_structure():
    rep, mir = both(SR5)
    for r, f in ((rep, lambda p: p), (mir, m)):
        d, od = ("bearish", "bullish") if r is rep else ("bullish", "bearish")
        assert changes(r) == [(11, "UNKNOWN", od.upper(), "ESTABLISHED"),
                              (12, od.upper(), "TRANSITION(%s)" % d, "CHOCH"),
                              (15, "TRANSITION(%s)" % d, od.upper(), "REVERSAL_INVALIDATED")]
        inv = [e for e in r.events if isinstance(e, StructureStateChange) and e.cause == "REVERSAL_INVALIDATED"][0]
        ch = [e for e in r.events if isinstance(e, CHoCHBreak)][0]
        b = [x for x in r.bos if x.index == 15][0]
        assert inv.related == (b.id, ch.id) and r.bos_roles[b.id] == REVERSAL_INVALIDATING
        assert not any(c == "O4_UNRESOLVED" and k == 15 for c, k in codes(r))
        # protected: the CHoCH-consumed 101.5 is never restored; the restoring BOS origin (L 101, k12) is an LL vs 101.5
        # -> NOT_QUALIFIED, so no protected level is in force (no SR-2 fallback after SR-5).
        assert prot(r, 15) is None and ("NOT_QUALIFIED", 15) in codes(r)
        assert ch.broken_swing_id not in [x.protected_swing_id for x in r.timeline[12:]]
    causal(SR5)


def test_sr5_after_restoration_a_new_choch_needs_a_new_protected_level():
    rows = SR5 + [(106.3, 106.4, 100.5, 100.6)]              # deep close below everything: no protected -> no CHoCH
    rep, mir = both(rows)
    for r in (rep, mir):
        assert len(chochs(r)) == 1 and r.timeline[16].state in ("BULLISH", "BEARISH")


def test_sr5_both_directions_on_one_candle_is_ambiguous_and_changes_nothing():
    """Not constructible from plausible candles (a post-CHoCH swing low above the latest swing high); checked by
    injecting the opposite BOS into the BOS stream for one candle."""
    rows = SR3                                                # TRANSITION(bearish) from k16; k21 confirms (eligible)
    s = series(rows)
    st = StructureStream()
    for c in list(s)[:21]:
        st.on_candle(c)
    real = st.bos.on_candle
    high = max((x for x in st.bos.swings if x.kind is SwingKind.HIGH), key=lambda x: x.confirmed_index)

    def injected(c):
        out = real(c)
        return out + [BOSEvent(bos_id(Direction.BULLISH, high), EventStamp.from_candles(c, c), related=(high.id,),
                               direction=Direction.BULLISH, level=high.price, broken_swing_id=high.id)]
    st.bos.on_candle = injected
    ev = st.on_candle(s[21])
    assert not [e for e in ev if isinstance(e, StructureStateChange)] and st.state.value == "TRANSITION(bearish)"
    assert {st.bos_roles[b.id] for b in st.bos_events if b.index == 21} == {TRANSITION_AMBIGUOUS}
    assert ("TRANSITION_BOS_BOTH_DIRECTIONS", 21) in {(d.code, d.index) for d in st.diagnostics}


def test_o4_close_back_without_opposite_bos_is_still_only_a_diagnostic():
    rows = FB_CHOCH + [(101.2, 102, 101.1, 101.8)]            # back above 101.5, no BOS
    rep, mir = both(rows)
    for r in (rep, mir):
        assert ("O4_UNRESOLVED", 13) in codes(r) and r.timeline[13].state.startswith("TRANSITION")


# ---------------------------------------------------------------- SR-4 roles and setup eligibility
def test_sr4_every_bos_has_exactly_one_known_role_and_only_confirming_is_setup_eligible():
    for rows in (S1, FB_CHOCH, FB_REPLACE, O9_REJECT, SR3, SR5, CHD01, [(x["o"], x["h"], x["l"], x["c"])
                                                                         for x in CHD["CHD10"]["candles"]]):
        for r in both(rows):
            assert set(r.bos_roles) == {b.id for b in r.bos} and set(r.bos_roles.values()) <= set(BOS_ROLES)
            eligible = [b.id for b in r.bos if r.bos_roles[b.id] in SETUP_ELIGIBLE_BOS_ROLES]
            confirming = [e.related[0] for e in r.events if isinstance(e, StructureStateChange)
                          and e.cause == "REVERSAL_CONFIRMED"]
            assert eligible == confirming
    assert SETUP_ELIGIBLE_BOS_ROLES == (REVERSAL_CONFIRMING,)


def test_sr4_continuation_bos_never_starts_a_setup():
    rep = run(FB_REPLACE)
    cont = [b for b in rep.bos if rep.bos_roles[b.id] == CONTINUATION]
    assert cont and not any(rep.bos_roles[b.id] in SETUP_ELIGIBLE_BOS_ROLES for b in cont)
    assert not [e for e in rep.events if isinstance(e, StructureStateChange) and e.cause == "REVERSAL_CONFIRMED"]


def test_stream_and_batch_roles_are_identical():
    for rows in (SR3, SR5, FB_REPLACE):
        s = series(rows)
        st = StructureStream()
        for c in s:
            st.on_candle(c)
        assert st.bos_roles == analyze_structure(s).bos_roles


if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
