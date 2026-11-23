#!/usr/bin/env python3
"""PERMANENT REGRESSION: the two BOS marking mistakes of 21 Nov 2026 on Easy Chart 1 and Easy Chart 2 (cases EASY01 /
EASY02 in fixtures/regression/easy_bos.json; formerly mislabelled "Medium", MED01 / MED02, renamed under audit D-4).

Mistakes being guarded against:
  A  Easy Chart 1: equal highs 105 (candles 3 and 4) were used as a swing high, giving a BOS at candle 11. WRONG.
  B  Easy Chart 2: equal lows 120 (candles 5 and 6) were used as a swing low, giving a BOS at candle 9. WRONG.
     The valid BOS (candle 13 close 116 below swing low 117, candle 10, confirmed at candle 12) must stay.

Approved profile (unchanged): L2/R2, strict comparison, equal highs / lows are not swings, BOS = candle CLOSE beyond
the latest confirmed swing (not before its confirmation), wick-only is not BOS, one BOS per reference swing id,
emitted at the close of the break candle.

The swing part runs the real scanner_v6 detector (batch and streaming). V6 has no BOS detector yet (it needs a
separate approval), so the BOS part uses `approved_bos()` below: a test-local reference evaluator that applies the
approved BOS rules literally to the detector's swings. When scanner_v6/structure/bos.py is approved, this fixture
must be run against it as well. Exact reference swing id / price and break candle are compared, not just labels.

    python tests/scanner_v6/test_regression_medium_bos.py     (or: python -m pytest tests/scanner_v6)
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import FIXTURES, run_main  # noqa: E402

from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.engine import no_lookahead_violations, replay_audit  # noqa: E402
from scanner_v6.models import EventStamp, SwingKind, SwingPoint  # noqa: E402
from scanner_v6.structure.swings import (SwingConfig, SwingStream, detect_swings, swing_id,  # noqa: E402
                                         unresolved_equal_levels)

DATA = json.load(open(os.path.join(FIXTURES, "regression", "easy_bos.json")))
CASES = {c["case_id"]: c for c in DATA["cases"]}
CFG = SwingConfig()


def series(case):
    rows = [(datetime.fromisoformat(x["t"].replace("Z", "+00:00")), x["o"], x["h"], x["l"], x["c"], 0)
            for x in case["candles"]]
    return CandleSeries.from_rows(rows, case["case_id"], "5m")


# ---- test-local reference evaluator of the APPROVED BOS rules (not a scanner_v6 module) ----------------------------
def approved_bos(s, swings_known_at):
    """swings_known_at(k) -> swings confirmed at or before candle k. At each candle k: for each kind, the reference is
    the latest swing of that kind confirmed BEFORE k (BOS-001); a CLOSE strictly beyond its price is a break
    (BOS-002); emitted at k (BOS-004); at most one break per reference id (BOS-005)."""
    used, out = set(), []
    for k in range(len(s)):
        known = swings_known_at(k - 1) if k else []
        close = s[k].close
        for kind, direction in ((SwingKind.HIGH, "bullish"), (SwingKind.LOW, "bearish")):
            refs = [e for e in known if e.kind is kind]
            if not refs:
                continue
            ref = max(refs, key=lambda e: (e.confirmed_index, e.index))
            if ref.id in used:
                continue
            beyond = close > ref.price if kind is SwingKind.HIGH else close < ref.price
            if beyond:
                used.add(ref.id)
                out.append({"direction": direction, "reference_id": ref.id, "reference_price": ref.price,
                            "reference_index": ref.index, "reference_confirmed_index": ref.confirmed_index,
                            "break_index": k, "emitted_at": k, "break_close": close})
    return out


def bos_batch(s):
    full = detect_swings(s)
    return approved_bos(s, lambda k: [e for e in full if e.confirmed_index <= k])


def bos_stream(s):
    st, seen = SwingStream(), []
    log = {}
    for c in s:
        seen += st.on_candle(c)
        log[c.index] = list(seen)
    return approved_bos(s, lambda k: log.get(k, []))


def expected_bos(case):
    out = []
    for b in case["expected_bos"]:
        kind = SwingKind.LOW if b["reference_kind"] == "low" else SwingKind.HIGH
        out.append({"direction": b["direction"], "reference_id": swing_id(kind, b["reference_candle"] - 1, CFG),
                    "reference_price": float(b["reference_price"]), "reference_index": b["reference_candle"] - 1,
                    "reference_confirmed_index": b["reference_confirmed_candle"] - 1,
                    "break_index": b["break_candle"] - 1, "emitted_at": b["emitted_at_candle"] - 1,
                    "break_close": float(b["break_close"])})
    return out


# ---- swings ---------------------------------------------------------------------------------------------------------
def check_swings(cid):
    case, s = CASES[cid], series(CASES[cid])
    got = [(e.kind.value, e.index + 1, e.confirmed_index + 1, e.price) for e in detect_swings(s)]
    want = [(k, i, c, float(p)) for k, i, c, p in case["expected_swings"]]
    assert got == want, (cid, got, want)
    ties = [(x.kind.value, x.index + 1, [t + 1 for t in x.tied_with]) for x in unresolved_equal_levels(s)]
    assert ties == [tuple(x) for x in case["expected_equal_levels"]], (cid, ties)
    exp = {(k, i - 1): c - 1 for k, i, c, _ in case["expected_swings"]}
    a = replay_audit(s, exp, lambda e: (e.kind.value, e.index), detector=detect_swings, make_stream=SwingStream)
    assert a.ok, a.findings
    assert no_lookahead_violations(detect_swings, s) == []


def test_A_med01_equal_highs_105_are_not_swings():
    check_swings("EASY01")
    s = series(CASES["EASY01"])
    assert all(e.price != 105 for e in detect_swings(s))
    assert {(x.kind.value, x.index + 1) for x in unresolved_equal_levels(s)} >= {("high", 3), ("high", 4)}


def test_B_med02_equal_lows_120_are_not_swings():
    check_swings("EASY02")
    s = series(CASES["EASY02"])
    assert all(not (e.kind is SwingKind.LOW and e.price == 120) for e in detect_swings(s))
    assert {(x.kind.value, x.index + 1) for x in unresolved_equal_levels(s)} >= {("low", 5), ("low", 6)}


# ---- BOS ------------------------------------------------------------------------------------------------------------
def test_A_med01_no_bos_at_all_and_not_at_candle_11():
    s = series(CASES["EASY01"])
    for got in (bos_batch(s), bos_stream(s)):
        assert got == expected_bos(CASES["EASY01"]) == [], got
        assert not any(b["break_index"] == 10 or b["reference_price"] == 105 for b in got)


def test_B_med02_valid_bos_candle_13_below_117_preserved_and_candle_9_rejected():
    s = series(CASES["EASY02"])
    want = expected_bos(CASES["EASY02"])
    assert want == [{"direction": "bearish", "reference_id": "swing:low:9:fixed-window-strict:L2R2",
                     "reference_price": 117.0, "reference_index": 9, "reference_confirmed_index": 11,
                     "break_index": 12, "emitted_at": 12, "break_close": 116.0}]
    b, st = bos_batch(s), bos_stream(s)
    assert b == want, b
    assert st == want, st                                       # batch == streaming
    assert not any(x["break_index"] == 8 or x["reference_price"] == 120 for x in b)


def test_bos_reference_reading_does_not_matter_here():
    """BOS-001 open reading C3 (latest vs latest-unbroken) gives the same result on both fixtures."""
    for cid in ("EASY01", "EASY02"):
        s = series(CASES[cid])
        full = detect_swings(s)
        used, out = set(), []
        for k in range(len(s)):
            for kind in (SwingKind.HIGH, SwingKind.LOW):
                refs = [e for e in full if e.kind is kind and e.confirmed_index < k and e.id not in used]
                if not refs:
                    continue
                ref = max(refs, key=lambda e: (e.confirmed_index, e.index))
                c = s[k].close
                if (c > ref.price) if kind is SwingKind.HIGH else (c < ref.price):
                    used.add(ref.id)
                    out.append((k, ref.id))
        assert out == [(x["break_index"], x["reference_id"]) for x in bos_batch(s)], (cid, out)


# ---- the mistake itself must be caught ------------------------------------------------------------------------------
def tie_promoting_detector(s):
    """The MISTAKE as code: an equal level promoted to a swing (first bar of a tie). Must be caught by this suite."""
    out = list(detect_swings(s))
    for x in unresolved_equal_levels(s):
        if all(t > x.index for t in x.tied_with) and x.index + CFG.right + max(x.tied_with) - x.index < len(s):
            conf = max(x.tied_with) + CFG.right
            if conf < len(s):
                out.append(SwingPoint(swing_id(x.kind, x.index, CFG), EventStamp.from_candles(s[x.index], s[conf]),
                                      kind=x.kind, price=x.price))
    return sorted(out, key=lambda e: (e.confirmed_index, e.index, e.id))


def test_mistake_reproduced_and_rejected():
    """With equal levels promoted, the evaluator reproduces the two wrong answers; the regression expectations reject
    them."""
    s1, s2 = series(CASES["EASY01"]), series(CASES["EASY02"])
    wrong1 = approved_bos(s1, lambda k, f=tie_promoting_detector(s1): [e for e in f if e.confirmed_index <= k])
    wrong2 = approved_bos(s2, lambda k, f=tie_promoting_detector(s2): [e for e in f if e.confirmed_index <= k])
    assert [(b["break_index"] + 1, b["reference_price"]) for b in wrong1] == [(11, 105.0)], wrong1
    assert (9, 120.0) in [(b["break_index"] + 1, b["reference_price"]) for b in wrong2], wrong2
    assert wrong1 != expected_bos(CASES["EASY01"]) and wrong2 != expected_bos(CASES["EASY02"])


if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
