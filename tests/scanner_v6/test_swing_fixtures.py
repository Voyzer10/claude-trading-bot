#!/usr/bin/env python3
"""All Volume-1 synthetic fixtures (39 draft cases + addendum SW16) against the APPROVED swing profile.

Oracle: the hand-written SP-A swing expectations in research/v6/specs/volume1/synthetic_volume1.draft.json, plus
swing_oracle_addendum.json for the cases whose draft listed breaks only. For every case:
  - the data loads (or is rejected, for the RB data-integrity cases)
  - batch output == oracle (kind, event index, confirmed index, price)
  - replay_audit: batch AND streaming vs the oracle: no premature / early / late / missing / duplicate / unexpected
    event, no repaint, batch == streaming (time and fields)
  - the old one-way no_lookahead_violations() also passes
  - equal-level diagnostics == the addendum's list (empty where none is listed)
RB03's swing expectation depends on the unresolved gap policy, so its oracle is NOT asserted; only causality and
parity are. Offline.

    python tests/scanner_v6/test_swing_fixtures.py      (or: python -m pytest tests/scanner_v6)
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ROOT, run_main  # noqa: E402

from scanner_v6.data.candle_models import CandleError, CandleSeries  # noqa: E402
from scanner_v6.engine import no_lookahead_violations, replay_audit  # noqa: E402
from scanner_v6.structure.swings import SwingStream, detect_swings, unresolved_equal_levels  # noqa: E402

SPEC = os.path.join(ROOT, "research", "v6", "specs", "volume1")
DRAFT = json.load(open(os.path.join(SPEC, "synthetic_volume1.draft.json")))
ADD = json.load(open(os.path.join(SPEC, "swing_oracle_addendum.json")))
REJECT = {"RB01", "RB02", "RB04"}
NOT_ASSERTED = {"RB03": "gap policy unresolved (D-SW-GAPS)"}
KEY = lambda e: (e.kind.value, e.index)          # noqa: E731


def load(case):
    rows = [(datetime.fromisoformat(x["t"].replace("Z", "+00:00")), x["o"], x["h"], x["l"], x["c"], 0)
            for x in case["candles"]]
    return CandleSeries.from_rows(rows, case["case_id"], "5m")


def oracle(case):
    """[(kind, index, confirmed_index, price)] for the approved profile, or None if not asserted."""
    cid = case["case_id"]
    if cid in NOT_ASSERTED:
        return None
    if cid in ADD["swing_expected"]:
        return [tuple(x) for x in ADD["swing_expected"][cid]]
    if "expected_swings" in case:
        return [tuple(x) for x in case["expected_swings"]]
    for prof, exp in case["expected"].items():
        if prof.startswith("SP-A") and isinstance(exp, list) and "tolerance" not in prof:
            sw = [e for e in exp if e["type"] == "SWING"]
            if sw or not exp:
                return [(e["kind"], e["event_index"], e["confirmed_index"], e["price"]) for e in sw]
    raise AssertionError("no approved-profile swing oracle for %s" % cid)


CASES = DRAFT["cases"] + ADD["new_cases"]
RESULTS = {}


def run_case(case):
    cid = case["case_id"]
    if cid in REJECT:
        try:
            load(case)
        except CandleError as e:
            return "rejected by loader (%s)" % str(e)[:50]
        raise AssertionError("%s should be rejected by the loader" % cid)
    s = load(case)
    got = [(e.kind.value, e.index, e.confirmed_index, e.price) for e in detect_swings(s)]
    exp = oracle(case)
    if exp is not None:
        assert sorted(got) == sorted(exp), "%s: detector %s != oracle %s" % (cid, got, exp)
    expected_times = {(k, i): c for k, i, c, _ in (exp if exp is not None else got)}
    a = replay_audit(s, expected_times if exp is not None else None, KEY if exp is not None else None,
                     detector=detect_swings, make_stream=SwingStream)
    assert a.ok, "%s: %s" % (cid, a.findings)
    assert no_lookahead_violations(detect_swings, s) == [], cid
    ties = [(x.kind.value, x.index, list(x.tied_with)) for x in unresolved_equal_levels(s)]
    want = [tuple(x) for x in ADD["equal_level_expected"].get(cid, [])]
    assert sorted(map(tuple, ties)) == sorted(want), "%s: equal-level diagnostics %s != %s" % (cid, ties, want)
    return "%d swings%s; audit ok (batch+stream)%s" % (len(got), "" if exp is not None else " (oracle NOT asserted: %s)"
                                                       % NOT_ASSERTED[cid], "; %d equal-level candidates" % len(ties)
                                                       if ties else "")


def _make(case):
    def t():
        RESULTS[case["case_id"]] = run_case(case)
    t.__name__ = "test_fixture_%s" % case["case_id"]
    return t


for _c in CASES:
    globals()["test_fixture_%s" % _c["case_id"]] = _make(_c)


def test_fixture_count():
    assert len(DRAFT["cases"]) == 39 and len(CASES) == 40


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    if "-v" in sys.argv:
        for c in CASES:
            try:
                print("%-6s %s" % (c["case_id"], run_case(c)))
            except AssertionError as e:
                print("%-6s FAIL %s" % (c["case_id"], e))
    run_main(tests)
