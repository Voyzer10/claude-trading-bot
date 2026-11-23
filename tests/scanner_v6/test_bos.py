#!/usr/bin/env python3
"""scanner_v6/structure/bos.py against the APPROVED BOS rules (BOS-001..005, Option A, D4 latest-confirmed reference,
D5 ordering).

    python tests/scanner_v6/test_bos.py     (or: python -m pytest tests/scanner_v6)
"""
import json
import math
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import FIXTURES, ROOT, run_main  # noqa: E402

from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.engine import no_lookahead_violations, replay_audit  # noqa: E402
from scanner_v6.structure.bos import BOSStream, detect_bos  # noqa: E402
from scanner_v6.structure.swings import detect_swings  # noqa: E402
from test_regression_medium_bos import approved_bos, expected_bos  # noqa: E402

VOL1 = json.load(open(os.path.join(ROOT, "research", "v6", "specs", "volume1", "synthetic_volume1.draft.json")))
CHOCH = json.load(open(os.path.join(ROOT, "research", "v6", "specs", "choch_v0_9", "choch_fixtures.draft.json")))
MED = json.load(open(os.path.join(FIXTURES, "regression", "medium_bos.json")))
# the approved-profile expectation key of each Volume-1 BOS draft case (close strictly beyond, RL, one per level)
APPROVED_KEY = {"BOS01": "SP-A + BOS-P1/P2/P3/P4 (RL)", "BOS02": "SP-A + BOS-P1 (RL)", "BOS03": "BOS-P1/P2/P4 (close)",
                "BOS04": "BOS-P1/P2/P4", "BOS05": "BOS-P1 (close >)", "BOS06": "BOS-P1/P2/P3",
                "BOS07": "BOS-P1..P4 (gap counts)", "BOS08": "BOS-P1 + one event per level", "BOS09": "SP-A + BOS-P1",
                "BOS10": "BOS-P1 + RL (latest confirmed low)", "BOS11": "SP-A + BOS-P1 (RL)", "BOS12": "BOS-P1 + RL",
                "BOS13": "BOS-P1", "BOS14": "BOS-P1", "BOS15": "raw float, any profile"}


def series_of(rows_json, name="x"):
    rows = [(datetime.fromisoformat(r["t"].replace("Z", "+00:00")), r["o"], r["h"], r["l"], r["c"], r.get("v", 0))
            for r in rows_json]
    return CandleSeries.from_rows(rows, name, "5m")


def all_series():
    out = [(c["case_id"], series_of(c["candles"], c["case_id"])) for c in VOL1["cases"] if c["case_id"].startswith("BOS")]
    out += [(c["case_id"], series_of(c["candles"], c["case_id"])) for c in MED["cases"]]
    out += [(c["case_id"], series_of(c["candles"], c["case_id"])) for c in CHOCH["decidable"] + CHOCH["unscored"]]
    return out


def as_tuple(b):
    return (b.direction.value, b.index, b.broken_swing_id, b.level)


def test_volume1_bos_drafts_match_the_approved_profile():
    for case in VOL1["cases"]:
        cid = case["case_id"]
        if not cid.startswith("BOS"):
            continue
        want = [e for e in case["expected"][APPROVED_KEY[cid]] if e.get("type") == "BREAK"]
        got = detect_bos(series_of(case["candles"], cid))
        assert len(got) == len(want), (cid, [as_tuple(b) for b in got], want)
        for b, w in zip(got, want):
            ref_i = int(b.broken_swing_id.split(":")[2])
            assert (b.direction.value, b.index, b.confirmed_index) == (w["direction"], w["event_index"], w["confirmed_index"]), (cid, b, w)
            assert w["reference_swing"] == "S%s%d" % ("H" if b.direction.value == "bullish" else "L", ref_i), (cid, b, w)
            assert math.isclose(b.level, w["reference_level"], abs_tol=1e-9), (cid, b.level, w["reference_level"])


def test_medium_regression_bos_from_the_module():
    for case in MED["cases"]:
        got = [{"direction": b.direction.value, "reference_id": b.broken_swing_id, "break_index": b.index}
               for b in detect_bos(series_of(case["candles"], case["case_id"]))]
        want = [{k: e[k] for k in ("direction", "reference_id", "break_index")} for e in expected_bos(case)]
        assert got == want, (case["case_id"], got, want)


def test_module_equals_the_test_local_reference_evaluator_everywhere():
    for cid, s in all_series():
        sw = detect_swings(s)
        ref = [(b["direction"], b["break_index"], b["reference_id"], b["reference_price"])
               for b in approved_bos(s, lambda k, f=sw: [e for e in f if e.confirmed_index <= k])]
        assert [as_tuple(b) for b in detect_bos(s)] == ref, cid


def test_d4_no_fallback_to_older_unbroken_swing():
    # CHD14: c18 breaks L 101 (latest); c19 closes 97 below the OLDER low 98 -> no BOS under D4
    s = series_of([c for c in CHOCH["decidable"] if c["case_id"] == "CHD14"][0]["candles"])
    got = [(b.direction.value, b.index + 1, b.level) for b in detect_bos(s)]
    assert got == [("bullish", 12, 109.0), ("bearish", 18, 101.0)], got


def test_one_bos_per_reference_and_close_strictly_beyond():
    for cid, s in all_series():
        bos = detect_bos(s)
        assert len({b.broken_swing_id for b in bos}) == len(bos), cid
        for b in bos:
            c = s[b.index].close
            assert (c > b.level) if b.direction.value == "bullish" else (c < b.level), (cid, b)


def test_d5_reference_confirmed_before_the_break_candle():
    for cid, s in all_series():
        sw = {e.id: e for e in detect_swings(s)}
        for b in detect_bos(s):
            assert sw[b.broken_swing_id].confirmed_index < b.index, (cid, b)


def test_causality_and_batch_stream_parity():
    for cid, s in all_series():
        exp = {b.id: b.index for b in detect_bos(s)}
        a = replay_audit(s, exp, lambda e: e.id, detector=detect_bos, make_stream=BOSStream)
        assert a.ok, (cid, a.findings)
        assert no_lookahead_violations(detect_bos, s) == [], cid


if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
