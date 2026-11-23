#!/usr/bin/env python3
"""Regression tests for the Phase-2 defect fixes D-1..D-4 of research/v6/audits/V6_BOS_CHOCH_CODE_AUDIT.md.

These tests pin DIAGNOSTIC labels only. They do not decide any open item:
- CHU04 (strictness of the CHoCH close) stays unresolved; the strict close is the CURRENT DEFAULT, not an approved rule.
- CHU05 (mixed HH + LL) and C6 (equal-swing classification) stay unresolved; such structure stays UNKNOWN.

    python tests/scanner_v6/test_defect_fixes.py     (or: python -m pytest tests/scanner_v6)
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import FIXTURES, ROOT, run_main  # noqa: E402

import scanner_v6.structure.choch as choch_mod  # noqa: E402
from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.engine import no_lookahead_violations, replay_audit  # noqa: E402
from scanner_v6.structure.choch import CHoCHBreak, StructureStream, analyze_structure, detect_structure  # noqa: E402
from test_regression_medium_bos import expected_bos  # noqa: E402

D = json.load(open(os.path.join(ROOT, "research", "v6", "specs", "choch_v0_9", "choch_fixtures.draft.json")))
CASES = {c["case_id"]: c for c in D["decidable"]}
UNSCORED = {c["case_id"]: c for c in D["unscored"]}
T0 = datetime(2026, 1, 5, tzinfo=timezone.utc)
STRUCTURE_DIAGS = ("MIXED_STRUCTURE", "EQUAL_SWING_PRICE")
ORIGINAL_DATA_SHA256 = "58be27349481fd20dceea5fcb8c5f197d902609b972cf462f1aebef321dc6ec8"


def series_rows(rows, name="x"):
    return CandleSeries.from_rows([(T0 + timedelta(minutes=5 * i), o, h, l, c, 0) for i, (o, h, l, c) in enumerate(rows)],
                                  name, "5m")


def case_rows(case):
    return [(r["o"], r["h"], r["l"], r["c"]) for r in case["candles"]]


def mirror(rows, axis=200.0):
    # price p -> axis - p: highs become lows, bullish becomes bearish; integer prices stay exact
    return [(axis - o, axis - l, axis - h, axis - c) for o, h, l, c in rows]


def bars(mids, pivot_highs, pivot_lows):
    # simple synthetic path: body from the previous mid to this mid, a 0.5 wick on the chosen pivot candles (1-based)
    rows, prev = [], mids[0]
    for i, m in enumerate(mids, 1):
        o, c = prev, m
        rows.append((o, max(o, c) + (0.5 if i in pivot_highs else 0), min(o, c) - (0.5 if i in pivot_lows else 0), c))
        prev = m
    return rows


# two swing highs (c6, c12) and two swing lows (c3, c9); only the second high / low differ between the cases
EQUAL_HIGHS = bars([20, 18, 16, 18, 20, 22, 20, 18, 17, 19, 21, 22, 20, 18], {6, 12}, {3, 9})   # 22.5 = 22.5, HL
HH_LL = bars([20, 18, 16, 18, 20, 22, 20, 18, 15, 19, 21, 24, 20, 18], {6, 12}, {3, 9})         # HH + LL (CHU05 shape)
LH_HL = bars([20, 18, 16, 18, 20, 22, 20, 18, 17, 19, 20, 21, 20, 18], {6, 12}, {3, 9})         # LH + HL (contracting)


def structure_diags(rep):
    return [(d.index + 1, d.code, d.detail) for d in rep.diagnostics if d.code in STRUCTURE_DIAGS]


def assert_unknown_and_silent(rep, tag):
    assert rep.events == [], (tag, rep.events)
    assert {t.state for t in rep.timeline} == {"UNKNOWN"}, tag


# ---------------------------------------------------------------- D-1: equal-price vs mixed structure diagnostics

def test_d1_equal_swing_price_is_not_labelled_chu05():
    for tag, rows in (("bull", EQUAL_HIGHS), ("mirror", mirror(EQUAL_HIGHS, 100.0))):
        rep = analyze_structure(series_rows(rows))
        got = structure_diags(rep)
        assert [(i, code) for i, code, _ in got] == [(14, "EQUAL_SWING_PRICE")], (tag, got)
        assert "CHU05" not in got[0][2] and "C6" in got[0][2], (tag, got)
        assert not any(d.code == "MIXED_STRUCTURE" for d in rep.diagnostics), tag
        assert_unknown_and_silent(rep, tag)


def test_d1_hh_plus_ll_keeps_the_chu05_mixed_label():
    for tag, rows in (("bull", HH_LL), ("mirror", mirror(HH_LL, 100.0))):
        rep = analyze_structure(series_rows(rows))
        got = structure_diags(rep)
        assert [(i, code) for i, code, _ in got] == [(14, "MIXED_STRUCTURE")], (tag, got)
        assert "HH + LL (CHU05 unresolved)" in got[0][2], (tag, got)
        assert_unknown_and_silent(rep, tag)


def test_d1_lh_plus_hl_is_mixed_but_not_chu05():
    for tag, rows in (("bull", LH_HL), ("mirror", mirror(LH_HL, 100.0))):
        rep = analyze_structure(series_rows(rows))
        got = structure_diags(rep)
        assert [(i, code) for i, code, _ in got] == [(14, "MIXED_STRUCTURE")], (tag, got)
        assert "CHU05" not in got[0][2] and "LH + HL" in got[0][2], (tag, got)
        assert_unknown_and_silent(rep, tag)


def test_d1_chu05_fixture_still_mixed_and_unknown():
    rep = analyze_structure(series_rows(case_rows(UNSCORED["CHU05"])))
    assert rep.events == [] and rep.timeline[-1].state == "UNKNOWN"
    mixed = [d for d in rep.diagnostics if d.code == "MIXED_STRUCTURE"]
    assert mixed and all("CHU05" in d.detail for d in mixed), [d.detail for d in mixed]


# ---------------------------------------------------------------- D-2: wick-only / close beyond / close exactly at

def test_d2_wick_only_rejection_both_directions():
    for cid in ("CHD03", "CHD04"):
        rep = analyze_structure(series_rows(case_rows(CASES[cid])))
        assert [(d.index + 1, d.code) for d in rep.diagnostics if d.code in ("WICK_ONLY", "EXACT_LEVEL_CLOSE")] \
            == [(18, "WICK_ONLY")], cid
        assert not any(isinstance(e, CHoCHBreak) for e in rep.events), cid


def test_d2_close_strictly_beyond_is_a_choch_both_directions():
    for cid in ("CHD01", "CHD02"):
        rep = analyze_structure(series_rows(case_rows(CASES[cid])))
        assert [e.index + 1 for e in rep.events if isinstance(e, CHoCHBreak)] == [18], cid
        assert not any(d.code in ("WICK_ONLY", "EXACT_LEVEL_CLOSE") for d in rep.diagnostics), cid


def test_d2_exact_level_close_is_not_wick_only_and_chu04_stays_open():
    # CHU04: c18 closes exactly at the protected HL 101. Under the CURRENT DEFAULT (strict close, CHU04 unresolved) no
    # CHoCH is emitted; the fix only changes the diagnostic label from WICK_ONLY to EXACT_LEVEL_CLOSE.
    case = UNSCORED["CHU04"]
    for tag, rows in (("bull", case_rows(case)), ("mirror", mirror(case_rows(case)))):
        rep = analyze_structure(series_rows(rows))
        labels = [(d.index + 1, d.code) for d in rep.diagnostics if d.code in ("WICK_ONLY", "EXACT_LEVEL_CLOSE")]
        assert labels == [(18, "EXACT_LEVEL_CLOSE")], (tag, labels)
        exact = [d for d in rep.diagnostics if d.code == "EXACT_LEVEL_CLOSE"][0]
        assert "CHU04 unresolved" in exact.detail and "current strict-close default" in exact.detail, exact.detail
        # emission and transitions are unchanged from before the fix (no CHoCH, no state change after c16)
        assert [(type(e).__name__, e.index + 1) for e in rep.events] == [("StructureStateChange", 16)], (tag, rep.events)


def test_d2_mirror_states_are_symmetric():
    for cid in ("CHD01", "CHD03", "CHD05", "CHD10"):
        a = analyze_structure(series_rows(case_rows(CASES[cid])))
        b = analyze_structure(series_rows(mirror(case_rows(CASES[cid]))))
        flip = {"BULLISH": "BEARISH", "BEARISH": "BULLISH", "UNKNOWN": "UNKNOWN",
                "TRANSITION(bearish)": "TRANSITION(bullish)", "TRANSITION(bullish)": "TRANSITION(bearish)"}
        assert [flip.get(t.state, t.state) for t in a.timeline] == [t.state for t in b.timeline], cid
        assert sorted((d.index, d.code) for d in a.diagnostics) == sorted((d.index, d.code) for d in b.diagnostics), cid


# ---------------------------------------------------------------- D-3: dead helper removed

def test_d3_opposite_helper_removed():
    assert not hasattr(choch_mod, "_opposite")
    src = open(choch_mod.__file__).read()
    assert "_opposite" not in src


# ---------------------------------------------------------------- D-4: fixture identity

def test_d4_easy_fixture_identity_and_legacy_ids():
    path = os.path.join(FIXTURES, "regression", "easy_bos.json")
    data = json.load(open(path))
    assert data["dataset"] == "v6_regression_easy_bos"
    assert [(c["case_id"], c["legacy_case_id"]) for c in data["cases"]] == [("EASY01", "MED01"), ("EASY02", "MED02")]
    for c in data["cases"]:
        assert "Easy" in c["source"], c["source"]
    # candles and every expectation are byte-for-byte the data of the former medium_bos.json (sha256 recorded before
    # the rename, over the canonical JSON of these keys)
    keys = ["candles", "expected_swings", "expected_equal_levels", "expected_bos", "rejected_mistake"]
    blob = json.dumps([{k: c[k] for k in keys} for c in data["cases"]], sort_keys=True).encode()
    assert hashlib.sha256(blob).hexdigest() == ORIGINAL_DATA_SHA256
    assert len(data["cases"][0]["candles"]) and len(data["cases"][1]["candles"])
    assert [len(expected_bos(c)) for c in data["cases"]] == [len(c["expected_bos"]) for c in data["cases"]]
    assert not os.path.exists(os.path.join(FIXTURES, "regression", "medium_bos.json"))


def test_d4_no_code_reference_to_the_old_fixture_name():
    hits = []
    for top in ("scanner_v6", "tests", os.path.join("research", "v6", "experiments"),
                os.path.join("research", "v6", "specs", "choch_v0_9")):
        for dp, _, fs in os.walk(os.path.join(ROOT, top)):
            for f in fs:
                if f.endswith(".py"):
                    p = os.path.join(dp, f)
                    if os.path.abspath(p) == os.path.abspath(__file__):
                        continue
                    if re.search(r"medium_bos\.json", open(p, encoding="utf-8").read()):
                        hits.append(os.path.relpath(p, ROOT))
    assert hits == [], hits


# ---------------------------------------------------------------- causality on the new synthetic inputs

def test_new_inputs_batch_stream_parity_and_no_lookahead():
    inputs = {"EQ": EQUAL_HIGHS, "HHLL": HH_LL, "LHHL": LH_HL, "CHU04": case_rows(UNSCORED["CHU04"])}
    for k in list(inputs):
        inputs[k + "_m"] = mirror(inputs[k], 100.0 if k != "CHU04" else 200.0)
    for k, rows in inputs.items():
        s = series_rows(rows, k)
        exp = {e.id: e.index for e in detect_structure(s)}
        a = replay_audit(s, exp, lambda e: e.id, detector=detect_structure, make_stream=StructureStream)
        assert a.ok, (k, a.findings)
        assert no_lookahead_violations(detect_structure, s) == [], k


if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
