#!/usr/bin/env python3
"""scanner_v6/structure/choch.py + protected_levels.py against the rules approved up to 22 Nov 2026 (A1-A10, D1-D5).

Expected outcomes are the hand-written `approved_rules_expected` of research/v6/specs/choch_v0_9/
choch_fixtures.draft.json (CHD01-CHD16), derived in PHASE1_2_DECISIONS.md. CHU01, CHU04 and CHU05 stay UNSCORED: for
those cases the tests only check that nothing is invented (no event, no state change beyond the approved rules).

    python tests/scanner_v6/test_choch.py     (or: python -m pytest tests/scanner_v6)
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ROOT, run_main  # noqa: E402

from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.engine import no_lookahead_violations, replay_audit  # noqa: E402
from scanner_v6.models import EventStamp, SwingKind, SwingPoint  # noqa: E402
from scanner_v6.structure.choch import (CHoCHBreak, ComplexStructureBreak, StructureStateChange,  # noqa: E402
                                        StructureStream, analyze_structure, classify_break, detect_structure)

D = json.load(open(os.path.join(ROOT, "research", "v6", "specs", "choch_v0_9", "choch_fixtures.draft.json")))
CASES = {c["case_id"]: c for c in D["decidable"]}
UNSCORED = {c["case_id"]: c for c in D["unscored"]}


def series_of(case):
    rows = [(datetime.fromisoformat(r["t"].replace("Z", "+00:00")), r["o"], r["h"], r["l"], r["c"], 0)
            for r in case["candles"]]
    return CandleSeries.from_rows(rows, case["case_id"], "5m")


def observed(rep):
    ev = []
    for e in rep.events:
        if isinstance(e, StructureStateChange) and e.cause == "ESTABLISHED":
            p = [t.protected_price for t in rep.timeline if t.index == e.index][0]
            ev.append(("ESTABLISHED", e.index + 1, e.state_after, p, ()))
        elif isinstance(e, StructureStateChange) and e.cause == "REVERSAL_CONFIRMED":
            ev.append(("REVERSAL_CONFIRMED", e.index + 1, e.state_after, None, ()))
        elif isinstance(e, CHoCHBreak):
            ev.append(("CHOCH", e.index + 1, e.state_after, e.level, tuple(e.levels_crossed)))
        elif isinstance(e, ComplexStructureBreak):
            ev.append(("COMPLEX", e.index + 1, e.state_after, e.level, ()))
    return ev


def test_all_decidable_fixtures_under_the_approved_rules():
    assert sorted(CASES) == ["CHD%02d" % i for i in range(1, 17)]
    for cid, case in CASES.items():
        want = case["approved_rules_expected"]
        rep = analyze_structure(series_of(case))
        assert [(b.direction.value, b.index + 1, b.level) for b in rep.bos] == [tuple(x) for x in want["bos"]], cid
        assert observed(rep) == [tuple(x[:4]) + (tuple(x[4]),) for x in want["events"]], (cid, observed(rep))
        last = rep.timeline[-1]
        assert (last.state, last.protected_price) == tuple(want["final"]), (cid, last)
        codes = {(d.code, d.index + 1) for d in rep.diagnostics}
        for code, cnd in want["diags"]:
            assert (code, cnd) in codes, (cid, code, cnd, codes)
        assert not any(d.code == "O4_UNRESOLVED" for d in rep.diagnostics), (cid, "fixture must not depend on O4")
        for cnd, price in want.get("protected_timeline", {}).items():
            assert rep.timeline[int(cnd) - 1].protected_price == price, (cid, cnd)


def test_d1_same_candle_bos_never_confirms_the_reversal():
    for cid in ("CHD01", "CHD02", "CHD10", "CHD11", "CHD12", "CHD14"):
        rep = analyze_structure(series_of(CASES[cid]))
        ch = [e for e in rep.events if isinstance(e, CHoCHBreak)][0]
        same = [b for b in rep.bos if b.index == ch.index and b.direction is ch.direction]
        assert same, (cid, "the CHoCH candle also has a same-direction BOS")
        assert rep.timeline[ch.index].state.startswith("TRANSITION"), cid
        conf = [e for e in rep.events if isinstance(e, StructureStateChange) and e.cause == "REVERSAL_CONFIRMED"]
        assert all(e.index > ch.index for e in conf), cid


def test_d1_separate_later_bos_confirms_both_directions():
    for cid, d, k in (("CHD10", "BEARISH", 24), ("CHD11", "BULLISH", 24)):
        rep = analyze_structure(series_of(CASES[cid]))
        conf = [e for e in rep.events if isinstance(e, StructureStateChange) and e.cause == "REVERSAL_CONFIRMED"]
        assert [(e.index + 1, e.state_after) for e in conf] == [(k, d)], cid
        bos = [b for b in rep.bos if b.index + 1 == k][0]
        assert conf[0].related == (bos.id,), cid
        states = [t.state for t in rep.timeline[17:23]]                    # c18..c23
        assert all(s.startswith("TRANSITION") for s in states), (cid, states)


def test_a8_transition_lock_no_second_choch():
    for cid in ("CHD10", "CHD11", "CHD14"):
        rep = analyze_structure(series_of(CASES[cid]))
        assert len([e for e in rep.events if isinstance(e, CHoCHBreak)]) == 1, cid


def test_d2_protected_only_after_confirmation():
    rep = analyze_structure(series_of(CASES["CHD16"]))
    # BOS c17 above 116; its origin L 106 (c16) confirms at c18 -> 101 is kept through c17
    assert [(t.index + 1, t.protected_price) for t in rep.timeline[15:19]] == [(16, 101.0), (17, 101.0), (18, 106.0),
                                                                               (19, 106.0)]
    act = [d for d in rep.diagnostics if d.code == "ACTIVATED"]
    assert [(d.index + 1, d.swing_id) for d in act] == [(12, "swing:low:9:fixed-window-strict:L2R2"),
                                                        (18, "swing:low:15:fixed-window-strict:L2R2")]


def test_d3_x1_records_extra_levels_as_evidence():
    rep = analyze_structure(series_of(CASES["CHD12"]))
    ch = [e for e in rep.events if isinstance(e, CHoCHBreak)]
    assert len(ch) == 1 and ch[0].level == 101.0 and ch[0].levels_crossed == (98.0,)
    assert not any(isinstance(e, ComplexStructureBreak) for e in rep.events)


def test_d3_complex_guard_never_forces_a_choch():
    t = datetime(2026, 1, 5, tzinfo=timezone.utc)
    a = SwingPoint("swing:low:3:x", EventStamp(3, t, 5, t + timedelta(minutes=10)), kind=SwingKind.LOW, price=100.0)
    b = SwingPoint("swing:low:7:x", EventStamp(7, t, 9, t + timedelta(minutes=10)), kind=SwingKind.LOW, price=99.0)
    assert classify_break([]) == "NONE"
    assert classify_break([a]) == "X1"
    assert classify_break([a, b]) == "COMPLEX"


def test_d5_swing_confirmed_on_k_not_used_on_k():
    rep = analyze_structure(series_of(CASES["CHD15"]))
    assert not any(isinstance(e, CHoCHBreak) for e in rep.events)       # c16 closes below 101, but state was UNKNOWN
    est = [e for e in rep.events if isinstance(e, StructureStateChange)]
    assert [(e.index + 1, e.state_after, e.cause) for e in est] == [(16, "BULLISH", "ESTABLISHED")]
    assert ("O9_UNRESOLVED", 16) in {(d.code, d.index + 1) for d in rep.diagnostics}


def test_wick_only_is_a_diagnostic_not_an_event():
    for cid in ("CHD03", "CHD04"):
        rep = analyze_structure(series_of(CASES[cid]))
        assert not any(isinstance(e, CHoCHBreak) for e in rep.events), cid
        assert [(d.code, d.index + 1) for d in rep.diagnostics if d.code == "WICK_ONLY"] == [("WICK_ONLY", 18)], cid


def test_unscored_cases_invent_nothing():
    # CHU01 (O4): the close back above 101 must NOT create a failed-CHoCH event or a state change
    rep = analyze_structure(series_of(UNSCORED["CHU01"]))
    assert [type(e).__name__ for e in rep.events] == ["StructureStateChange", "CHoCHBreak", "StructureStateChange"]
    assert rep.timeline[-1].state == "TRANSITION(bearish)"
    assert ("O4_UNRESOLVED", 19) in {(d.code, d.index + 1) for d in rep.diagnostics}
    # CHU05 (mixed HH + LL): stays UNKNOWN, no CHoCH
    rep = analyze_structure(series_of(UNSCORED["CHU05"]))
    assert rep.events == [] and rep.timeline[-1].state == "UNKNOWN"
    assert any(d.code == "MIXED_STRUCTURE" for d in rep.diagnostics)
    # CHU04 (strictness): no assertion on the outcome; only that it runs and emits no COMPLEX
    rep = analyze_structure(series_of(UNSCORED["CHU04"]))
    assert not any(isinstance(e, ComplexStructureBreak) for e in rep.events)


def test_causality_and_batch_stream_parity():
    for cid, case in list(CASES.items()) + list(UNSCORED.items()):
        s = series_of(case)
        exp = {e.id: e.index for e in detect_structure(s)}
        a = replay_audit(s, exp, lambda e: e.id, detector=detect_structure, make_stream=StructureStream)
        assert a.ok, (cid, a.findings)
        assert no_lookahead_violations(detect_structure, s) == [], cid


if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
