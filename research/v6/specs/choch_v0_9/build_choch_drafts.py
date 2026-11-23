#!/usr/bin/env python3
"""Builds + checks the CHoCH v0.9 CONCEPTUAL fixture drafts (research only, PAPER ONLY, no orders).

This is NOT a CHoCH detector. Every expected CHoCH outcome below is written by hand from the approved decisions
A1-A10 of the V6 CHoCH Training Spec v0.9 plus the owner's 21 Nov 2026 decisions. The script only:
  * writes the candles (1-based candle numbers) and the hand-written expectations to choch_fixtures.draft.json,
  * checks the FACTS each expectation rests on with the approved scanner_v6 swing detector (L2/R2 strict):
    the confirmed swings, the swing counts known before the candidate candle, the HH/HL (LH/LL) comparisons, and
    the candidate candle's close / wick against the protected price,
  * records, for information only, the BOS events under the existing approved BOS rules (Option A: BOS is
    independent of structure direction),
  * hashes each case's OHLC.
Unscored cases get no CHoCH expectation at all (spec Section 7: "Do not score unresolved scenarios").

    python research/v6/specs/choch_v0_9/build_choch_drafts.py
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "scanner_v6"))
from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.models import SwingKind  # noqa: E402
from scanner_v6.structure.swings import SwingConfig, detect_swings, swing_id, unresolved_equal_levels  # noqa: E402
from test_regression_medium_bos import approved_bos  # noqa: E402  (test-local evaluator of the approved BOS rules)

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
CFG = SwingConfig()

# ---- base bullish sequence: L1 98 (c4) -> H1 109 (c7) -> L2 101 (c10, HL) -> bullish BOS c12 -> H2 116 (c14, HH) ----
BASE = [(104, 105, 102, 103), (103, 104, 101, 102), (102, 103, 100, 101), (101, 102, 98, 99), (99, 103, 99, 102),
        (102, 106, 101, 105), (105, 109, 104, 108), (108, 108, 104, 105), (105, 106, 102, 103), (103, 104, 101, 102),
        (102, 107, 102, 106), (106, 111, 105, 110), (110, 114, 109, 113), (113, 116, 112, 115), (115, 115, 110, 111),
        (111, 112, 106, 107), (107, 108, 103, 104)]                                   # candles 1..17
BASE_SWINGS = [("low", 4, 6, 98), ("high", 7, 9, 109), ("low", 10, 12, 101), ("high", 14, 16, 116)]


def mirror(rows):
    return [(200 - o, 200 - l, 200 - h, 200 - c) for o, h, l, c in rows]


def mirror_swings(sw):
    return [("high" if k == "low" else "low", i, c, 200 - p) for k, i, c, p in sw]


EASY = {c["case_id"]: c for c in json.load(open(os.path.join(ROOT, "tests", "scanner_v6", "fixtures", "regression",
                                                             "easy_bos.json")))["cases"]}


def easy_rows(cid):
    return [(x["o"], x["h"], x["l"], x["c"]) for x in EASY[cid]["candles"]]


def sid(kind, candle):
    return swing_id(SwingKind.HIGH if kind == "high" else SwingKind.LOW, candle - 1, CFG)


def choch(state_before, event, prot, candle, basis, state_after, reason):
    """prot = (kind, candle, price) or None. Spec Section 5/6 output fields + a plain-language reason."""
    return {"state_before": state_before, "event": event,
            "protected_swing_id": sid(prot[0], prot[1]) if prot else None,
            "protected_swing_type": prot[0].upper() if prot else None,
            "protected_swing_price": prot[2] if prot else None,
            "candidate_candle": candle,
            "break_candle_index": (candle - 1) if event in ("BULLISH_CHOCH", "BEARISH_CHOCH") else None,
            "confirmation_basis": basis, "state_after": state_after, "unresolved_reason": None, "reason": reason}


# ---- decidable cases -----------------------------------------------------------------------------------------------
D = []
D.append(dict(case_id="CHD01", title="Bullish structure -> close below protected HL -> BEARISH_CHOCH -> TRANSITION",
              rows=BASE + [(104, 105, 99, 100)], swings=BASE_SWINGS,
              structure=("BULLISH", ("high", 7, 109), ("high", 14, 116), ("low", 4, 98), ("low", 10, 101)),
              check=("close_below", 101), expected=choch("BULLISH", "BEARISH_CHOCH", ("low", 10, 101), 18,
              "CLOSE_BEYOND", "TRANSITION", "HH 116>109 + HL 101>98 = BULLISH (A2, A4). The only HL is 101 (A5). "
              "Candle 18 closes 100 < 101 (A6) -> BEARISH_CHOCH, enter TRANSITION, no reversal declared (A7).")))
D.append(dict(case_id="CHD02", title="Mirror of CHD01: bearish structure -> close above protected LH -> BULLISH_CHOCH",
              rows=mirror(D[0]["rows"]), swings=mirror_swings(BASE_SWINGS),
              structure=("BEARISH", ("low", 7, 91), ("low", 14, 84), ("high", 4, 102), ("high", 10, 99)),
              check=("close_above", 99), expected=choch("BEARISH", "BULLISH_CHOCH", ("high", 10, 99), 18,
              "CLOSE_BEYOND", "TRANSITION", "LL 84<91 + LH 99<102 = BEARISH. The only LH is 99. Candle 18 closes "
              "100 > 99 -> BULLISH_CHOCH, TRANSITION.")))
D.append(dict(case_id="CHD03", title="Bullish structure, wick-only pierce of protected HL -> NO_CHOCH (WICK_ONLY)",
              rows=BASE + [(104, 105, 100, 102)], swings=BASE_SWINGS, structure=D[0]["structure"],
              check=("wick_only_below", 101), expected=choch("BULLISH", "NO_CHOCH", ("low", 10, 101), 18, "WICK_ONLY",
              "BULLISH", "Low 100 < 101 but close 102 > 101: wick-only is not CHoCH (A6); WICK_ONLY is evidence of a "
              "rejected candidate (owner decision 3). Structure unchanged.")))
D.append(dict(case_id="CHD04", title="Mirror of CHD03: wick-only pierce of protected LH -> NO_CHOCH (WICK_ONLY)",
              rows=mirror(D[2]["rows"]), swings=mirror_swings(BASE_SWINGS), structure=D[1]["structure"],
              check=("wick_only_above", 99), expected=choch("BEARISH", "NO_CHOCH", ("high", 10, 99), 18, "WICK_ONLY",
              "BEARISH", "High 100 > 99 but close 98 < 99: wick-only, NO_CHOCH. Structure unchanged.")))
CONT = BASE[:16] + [(107, 113, 107, 112), (112, 118, 111, 117)]
D.append(dict(case_id="CHD05", title="Bullish structure, with-trend close above H2 -> bullish BOS, NO_CHOCH",
              rows=CONT, swings=BASE_SWINGS + [("low", 16, 18, 106)], structure=D[0]["structure"],
              check=("close_above", 116), expected=choch("BULLISH", "NO_CHOCH", None, 18, None, "BULLISH",
              "Close 117 > H2 116 is a with-direction break: a BOS under the approved BOS rules, not a "
              "counter-direction break, so not CHoCH. (Swing low 106 at c16 confirms only at c18's close.)")))
D.append(dict(case_id="CHD06", title="Mirror of CHD05: bearish structure, close below L2 -> bearish BOS, NO_CHOCH",
              rows=mirror(CONT), swings=mirror_swings(BASE_SWINGS + [("low", 16, 18, 106)]),
              structure=D[1]["structure"], check=("close_below", 84), expected=choch("BEARISH", "NO_CHOCH", None, 18,
              None, "BEARISH", "Close 83 < L2 84 is a with-direction break: BOS, not CHoCH.")))
D.append(dict(case_id="CHD07", title="UNKNOWN (2 highs, 1 low): close below the only swing low -> NO_CHOCH",
              rows=D[0]["rows"][4:], swings=[("high", 3, 5, 109), ("low", 6, 8, 101), ("high", 10, 12, 116)],
              structure=("UNKNOWN",), check=("close_below", 101), expected=choch("UNKNOWN", "NO_CHOCH", None, 14, None,
              "UNKNOWN", "Only one confirmed swing low: A4 minimum (2 highs + 2 lows) not met -> UNKNOWN (A3). No "
              "protected swing may be invented (spec 5/8). The close below 101 is still a bearish BOS under the "
              "approved BOS rules (Option A).")))
D.append(dict(case_id="CHD08", title="UNKNOWN from equal levels only (Easy Chart 1 OHLC): NO_CHOCH throughout",
              rows=easy_rows("EASY01"), swings=[], structure=("UNKNOWN",), check=None,
              expected=choch("UNKNOWN", "NO_CHOCH", None, None, None, "UNKNOWN", "Equal highs 105 and equal lows 99 "
              "are not swings: no confirmed swing at all -> UNKNOWN, no CHoCH on any candle.")))
D.append(dict(case_id="CHD09", title="UNKNOWN (1 confirmed low) (Easy Chart 2 OHLC): BOS at c13 but NO_CHOCH",
              rows=easy_rows("EASY02"), swings=[("high", 4, 6, 127), ("high", 8, 10, 126), ("low", 10, 12, 117),
                                               ("high", 12, 14, 123)],
              structure=("UNKNOWN",), check=("close_below", 117), expected=choch("UNKNOWN", "NO_CHOCH", None, 13, None,
              "UNKNOWN", "Only one confirmed swing low (equal lows 120 are not swings) -> UNKNOWN. Candle 13 stays "
              "the approved bearish BOS below 117 (existing fixture unchanged, Option A), but it is not a CHoCH.")))

# ---- owner's list of unresolved decisions (21 Nov 2026), verbatim ------------------------------------------------
O_LIST = {"O1": "protected-swing lifecycle", "O2": "continuation BOS association", "O3": "transition completion",
          "O4": "failed CHoCH sequencing", "O5": "complex-break detection and state",
          "O6": "same-candle event ordering", "O7": "history/session gaps",
          "O8": "duplicate, invalidation and stable event IDs", "O9": "initial structure chronology"}

# ---- audit of 21 Nov 2026 (AUDIT_CHD01-09.md): which open items each decidable expectation touches ---------------
AUDIT = {
    "CHD01": ("SUPPORTED (D2 P-B + D5, approved 22 Nov 2026)", [], "Event rests on the single HL (101) qualifying as protected (O1); it is "
              "confirmed on the same candle (c12) as the bullish BOS above 109 (O6). state_after TRANSITION rests on "
              "A7 even though c18 is also a bearish BOS (O3/O6)."),
    "CHD02": ("SUPPORTED (D2 P-B + D5, approved 22 Nov 2026)", [], "Mirror of CHD01."),
    "CHD03": ("SUPPORTED (D2 P-B, approved 22 Nov 2026)", [], "NO_CHOCH is independent of O1 (no close beyond any low). "
              "Only the protected_swing_id field (101) depends on O1."),
    "CHD04": ("SUPPORTED (D2 P-B, approved 22 Nov 2026)", [], "Mirror of CHD03."),
    "CHD05": ("SUPPORTED", [], "With-direction close: never a CHoCH (A2/A6 + spec terminology)."),
    "CHD06": ("SUPPORTED", [], "Mirror of CHD05."),
    "CHD07": ("SUPPORTED", [], "One confirmed low: A4 minimum not met under any chronology -> UNKNOWN (A3)."),
    "CHD08": ("SUPPORTED", [], "No confirmed swing at all -> UNKNOWN."),
    "CHD09": ("SUPPORTED", [], "One confirmed low before c13 -> UNKNOWN; c13 BOS unchanged (Option A)."),
}
UNSCORED_O = {"CHU01": ["O4"], "CHU02": ["O5", "O6"], "CHU03": ["O1", "O2"], "CHU04": [],
              "CHU05": ["O9"], "CHU06": ["O3", "O8"]}

# ---- unscored cases (rule not finalised): OHLC + the question only, NO expected CHoCH outcome ----------------------
U = [
    dict(case_id="CHU01", open_items=["failed-CHoCH sequencing (A9)"], rows=D[0]["rows"] + [(100, 103, 100, 102)],
         question="After the c18 BEARISH_CHOCH, c19 closes 102 back above protected 101 before any new-direction BOS. "
                  "FAILED_CHOCH at c19? Is BULLISH restored immediately, and what 'remains valid' means."),
    dict(case_id="CHU02", open_items=["complex-break state semantics (A10)", "same-candle ordering"],
         rows=BASE + [(104, 105, 96, 97)],
         question="One candle closes 97 below both the protected HL 101 and the older low 98. CHoCH, or "
                  "COMPLEX_STRUCTURE_BREAK? What is state_after?"),
    dict(case_id="CHU03", open_items=["protected-swing lifecycle (A5)"],
         rows=CONT + [(117, 117, 110, 111), (111, 112, 104, 105)],
         question="Rising lows 98, 101, 106 (106 confirmed at c18, after the BOS above 116). c20 closes 105: below "
                  "106, above 101. Which HL is protected: 106 (latest) or 101? CHoCH at c20 or not?"),
    dict(case_id="CHU04", open_items=["strictness of 'close beyond' for CHoCH: NOT in O1-O9, needs an owner decision"],
         rows=BASE + [(104, 105, 100, 101)],
         question="c18 closes exactly 101 = protected HL. BOS uses a strict close (approved); does CHoCH too?"),
    dict(case_id="CHU05", open_items=["initial-structure chronology (O9)", "mixed HH + LL classification: not named in O1-O9"],
         rows=BASE[:9] + [(103, 104, 96, 102)] + BASE[10:16] + [(107, 108, 100, 101), (101, 102, 94, 95)],
         question="Highs 109 -> 116 (HH) but lows 98 -> 96 (LL). Is that UNKNOWN (A3), and is c18's close 95 < 96 "
                  "a CHoCH, a BOS only, or nothing?"),
    dict(case_id="CHU06", open_items=["transition-confirmation BOS eligibility", "event identity / invalidation",
                                      "BOS-001 reading C3 (latest vs latest unbroken): BOS question, not in O1-O9"],
         rows=D[0]["rows"] + [(100, 101, 96, 97)],
         question="In TRANSITION after the c18 CHoCH, c19 closes 97 below the older low 98. A8 forbids a second "
                  "CHoCH. Is c19 a bearish BOS that confirms BEARISH (only under the 'latest unbroken' reading is 98 "
                  "a BOS reference), or does the state stay TRANSITION?"),
]


# ---- 22 Nov 2026: owner-approved D1-D5. Full hand-written expectations under the approved rules ---------------------
# Each entry: bos [(dir, candle, ref price)], events [(cause/type, candle, state_after, protected or CHoCH level,
# levels_crossed)], final (state, protected in force after the last candle), diags (codes that must appear).
EXT10 = [(104, 105, 99, 100), (100, 101, 97, 98), (98, 100.5, 97.5, 100), (100, 103, 99.5, 100.5),
         (100.5, 102.5, 99, 99.5), (99.5, 100, 98, 98.5), (98.5, 99, 95, 96)]
NEW_CASES = [
    dict(case_id="CHD10", title="D1 bearish reversal: CHoCH c18 -> TRANSITION -> separate bearish BOS c24 confirms",
         rows=BASE + EXT10, decided_by=["D1", "D2", "D4", "D5"]),
    dict(case_id="CHD11", title="D1 bullish reversal (mirror of CHD10)", rows=mirror(BASE + EXT10),
         decided_by=["D1", "D2", "D4", "D5"]),
    dict(case_id="CHD12", title="D3 X1: close below protected 101 and non-protected 98 (formerly CHU02)",
         rows=BASE + [(104, 105, 96, 97)], decided_by=["D3", "D5"], supersedes="CHU02"),
    dict(case_id="CHD13", title="D2: protected moves 101 -> 106 (origin of BOS c18); CHoCH c20 (formerly CHU03)",
         rows=CONT + [(117, 117, 110, 111), (111, 112, 104, 105)], decided_by=["D2", "D5"], supersedes="CHU03"),
    dict(case_id="CHD14", title="D1 + D4: TRANSITION kept, c19 close below older low 98 is not a BOS (formerly CHU06)",
         rows=BASE + [(104, 105, 99, 100), (100, 101, 96, 97)], decided_by=["D1", "D4"], supersedes="CHU06"),
    dict(case_id="CHD15", title="D5: H 116 confirms at c16 while c16 closes below 101 -> no CHoCH on c16",
         rows=BASE[:14] + [(115, 115, 110, 111), (111, 112, 99, 100)], decided_by=["D5"]),
    dict(case_id="CHD16", title="D2 activation: BOS c17 origin 106 confirms at c18; 101 kept until then; CHoCH c20",
         rows=BASE[:14] + [(115, 115, 110, 111), (111, 112, 106, 107), (107, 117, 107, 116.5), (116.5, 118, 112, 117),
                           (117, 117.5, 110, 111), (111, 112, 104, 105)], decided_by=["D2", "D5"]),
]
B_UP, B_DN = ("bullish", 12, 109.0), ("bearish", 12, 91.0)
EST_UP, EST_DN = ("ESTABLISHED", 16, "BULLISH", 101.0, ()), ("ESTABLISHED", 16, "BEARISH", 99.0, ())
APPROVED_EXPECTED = {
    "CHD01": dict(bos=[B_UP, ("bearish", 18, 101.0)], events=[EST_UP, ("CHOCH", 18, "TRANSITION(bearish)", 101.0, ())],
                  final=("TRANSITION(bearish)", None), diags=[]),
    "CHD02": dict(bos=[B_DN, ("bullish", 18, 99.0)], events=[EST_DN, ("CHOCH", 18, "TRANSITION(bullish)", 99.0, ())],
                  final=("TRANSITION(bullish)", None), diags=[]),
    "CHD03": dict(bos=[B_UP], events=[EST_UP], final=("BULLISH", 101.0), diags=[("WICK_ONLY", 18)]),
    "CHD04": dict(bos=[B_DN], events=[EST_DN], final=("BEARISH", 99.0), diags=[("WICK_ONLY", 18)]),
    "CHD05": dict(bos=[B_UP, ("bullish", 18, 116.0)], events=[EST_UP], final=("BULLISH", 106.0), diags=[]),
    "CHD06": dict(bos=[B_DN, ("bearish", 18, 84.0)], events=[EST_DN], final=("BEARISH", 94.0), diags=[]),
    "CHD07": dict(bos=[("bullish", 8, 109.0), ("bearish", 14, 101.0)], events=[], final=("UNKNOWN", None), diags=[]),
    "CHD08": dict(bos=[], events=[], final=("UNKNOWN", None), diags=[]),
    "CHD09": dict(bos=[("bearish", 13, 117.0)], events=[], final=("UNKNOWN", None), diags=[]),
    "CHD10": dict(bos=[B_UP, ("bearish", 18, 101.0), ("bearish", 24, 97.0)],
                  events=[EST_UP, ("CHOCH", 18, "TRANSITION(bearish)", 101.0, ()), ("REVERSAL_CONFIRMED", 24, "BEARISH", None, ())],
                  final=("BEARISH", 103.0), diags=[]),
    "CHD11": dict(bos=[B_DN, ("bullish", 18, 99.0), ("bullish", 24, 103.0)],
                  events=[EST_DN, ("CHOCH", 18, "TRANSITION(bullish)", 99.0, ()), ("REVERSAL_CONFIRMED", 24, "BULLISH", None, ())],
                  final=("BULLISH", 97.0), diags=[]),
    "CHD12": dict(bos=[B_UP, ("bearish", 18, 101.0)], events=[EST_UP, ("CHOCH", 18, "TRANSITION(bearish)", 101.0, (98.0,))],
                  final=("TRANSITION(bearish)", None), diags=[]),
    "CHD13": dict(bos=[B_UP, ("bullish", 18, 116.0), ("bearish", 20, 106.0)],
                  events=[EST_UP, ("CHOCH", 20, "TRANSITION(bearish)", 106.0, ())], final=("TRANSITION(bearish)", None), diags=[]),
    "CHD14": dict(bos=[B_UP, ("bearish", 18, 101.0)], events=[EST_UP, ("CHOCH", 18, "TRANSITION(bearish)", 101.0, ())],
                  final=("TRANSITION(bearish)", None), diags=[]),
    "CHD15": dict(bos=[B_UP, ("bearish", 16, 101.0)], events=[EST_UP], final=("BULLISH", 101.0), diags=[("O9_UNRESOLVED", 16)],
                  scored_through_candle=16),
    "CHD16": dict(bos=[B_UP, ("bullish", 17, 116.0), ("bearish", 20, 106.0)],
                  events=[EST_UP, ("CHOCH", 20, "TRANSITION(bearish)", 106.0, ())], final=("TRANSITION(bearish)", None),
                  diags=[], protected_timeline={16: 101.0, 17: 101.0, 18: 106.0, 19: 106.0}),
}
SUPERSEDED = {"CHU02": "CHD12", "CHU03": "CHD13", "CHU06": "CHD14"}


def series(rows, name):
    return CandleSeries.from_rows([(T0 + timedelta(minutes=5 * i), *r, 0) for i, r in enumerate(rows)], name, "5m")


def ohlc_hash(rows):
    return hashlib.sha256(json.dumps([list(map(float, r)) for r in rows]).encode()).hexdigest()


def candles_json(rows):
    return [{"candle": i + 1, "t": (T0 + timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "o": o, "h": h, "l": l, "c": c} for i, (o, h, l, c) in enumerate(rows)]


def got_swings(s):
    return [(e.kind.value, e.index + 1, e.confirmed_index + 1, e.price) for e in detect_swings(s)]


def bos_info(s):
    sw = detect_swings(s)
    return [{"direction": b["direction"], "break_candle": b["break_index"] + 1, "reference_id": b["reference_id"],
             "reference_price": b["reference_price"]}
            for b in approved_bos(s, lambda k, f=sw: [e for e in f if e.confirmed_index <= k])]


def verify(case):
    s, exp = series(case["rows"], case["case_id"]), case["expected"]
    got = got_swings(s)
    assert got == [(k, i, c, float(p)) for k, i, c, p in case["swings"]], (case["case_id"], got)
    k = exp["candidate_candle"]
    known = [x for x in got if k is None or x[2] < k]               # confirmed before the candidate candle
    nh, nl = sum(x[0] == "high" for x in known), sum(x[0] == "low" for x in known)
    st = case["structure"]
    if st[0] == "UNKNOWN":
        assert nh < 2 or nl < 2, (case["case_id"], nh, nl)          # A4 minimum not met
    else:
        (_, ih1, h1), (_, ih2, h2), (_, il1, l1), (_, il2, l2) = st[1:]   # BULLISH: highs, highs, lows, lows; BEARISH: lows, lows, highs, highs
        assert nh == 2 and nl == 2, (case["case_id"], known)        # exactly 2 + 2: no chronology choice involved
        assert {(x[1], x[3]) for x in known} == {(ih1, h1), (ih2, h2), (il1, l1), (il2, l2)}
        assert (h2 > h1 and l2 > l1) if st[0] == "BULLISH" else (h2 < h1 and l2 < l1), case["case_id"]
        if exp["protected_swing_price"] is not None:                # the single HL (bullish) / LH (bearish)
            want = ("low", l2) if st[0] == "BULLISH" else ("high", l2)   # bearish tuples: 4th/5th entries are highs
            assert (exp["protected_swing_type"].lower(), exp["protected_swing_price"]) == want, case["case_id"]
    if case["check"]:
        how, p = case["check"]
        c = s[k - 1]
        ok = {"close_below": c.close < p, "close_above": c.close > p,
              "wick_only_below": c.low < p <= c.close, "wick_only_above": c.high > p >= c.close}[how]
        assert ok, (case["case_id"], how, p, c)
    if exp["event"] in ("BULLISH_CHOCH", "BEARISH_CHOCH"):          # nothing counter-direction before the break
        prot = exp["protected_swing_price"]
        conf = [x[2] for x in got if x[3] == prot][0]
        for j in range(conf, k - 1):
            assert (s[j].close >= prot) if exp["event"] == "BEARISH_CHOCH" else (s[j].close <= prot), (case, j)
    return s


def main():
    out = {"spec": "V6 CHoCH Training Specification v0.9 (21 Nov 2026)", "status": "DRAFT, conceptual only. Not a "
           "CHoCH detector contract. Not approved for implementation (spec Section 9).",
           "profile": {"swings": "fixed window L2/R2, strict; equal highs/lows are not swings",
                       "bos": "existing approved BOS rules, independent of structure direction (owner decision 2)",
                       "choch_approved": "A1-A10 only", "candles": "1-based candle numbers; *_index fields 0-based"},
           "external_structure_note": "A1: external structure only. 'External' has no executable definition yet. "
           "Every decidable case is a clean zig-zag in which each confirmed swing is a leg extreme, so no swing can "
           "be internal under any reading.",
           "unresolved_decisions": O_LIST,
           "builder_is_not_proof": "Passing build_choch_drafts.py only shows the inputs (swings, counts, closes) are as "
           "described. The CHoCH expectations are hand-written; see AUDIT_CHD01-09.md for their support.",
           "owner_decisions_22_nov_2026": "D1, D2 (P-B, protected only after L2/R2 confirmation), D4, D5 approved; D3 "
           "approved with modification (X1 / COMPLEX guard). See PHASE1_2_DECISIONS.md. O4, O7, O8, O9, CHU04, CHU05 "
           "remain unresolved. Not all CHoCH rules are final.",
           "decidable": [], "unscored": []}
    for case in D:
        s = verify(case)
        ties = sorted({(x.kind.value, x.price) for x in unresolved_equal_levels(s)})
        out["decidable"].append({
            "case_id": case["case_id"], "title": case["title"], "candles": candles_json(case["rows"]),
            "candle_count": len(case["rows"]), "ohlc_sha256": ohlc_hash(case["rows"]),
            "expected_swings": [{"id": sid(k, i), "kind": k, "candle": i, "confirmed_candle": c, "price": p}
                                for k, i, c, p in case["swings"]],
            "equal_levels_not_swings": [list(x) for x in ties],
            "expected_choch": case["expected"],
            "expected_choch_on_other_candles": "none",
            "audit": {"verdict": AUDIT[case["case_id"]][0], "depends_on": AUDIT[case["case_id"]][1],
                      "note": AUDIT[case["case_id"]][2]},
            "info_bos_under_approved_rules": bos_info(s),
            "approved_rules_expected": APPROVED_EXPECTED[case["case_id"]]})
    for case in NEW_CASES:
        out["decidable"].append({
            "case_id": case["case_id"], "title": case["title"], "candles": candles_json(case["rows"]),
            "candle_count": len(case["rows"]), "ohlc_sha256": ohlc_hash(case["rows"]), "decided_by": case["decided_by"],
            "supersedes": case.get("supersedes"),
            "approved_rules_expected": APPROVED_EXPECTED[case["case_id"]]})
    for case in U:
        s = series(case["rows"], case["case_id"])
        out["unscored"].append({
            "case_id": case["case_id"], "open_decisions": UNSCORED_O[case["case_id"]],
            "open_items": case["open_items"], "question": case["question"],
            "candles": candles_json(case["rows"]), "candle_count": len(case["rows"]),
            "ohlc_sha256": ohlc_hash(case["rows"]),
            "detector_swings": [{"kind": k, "candle": i, "confirmed_candle": c, "price": p} for k, i, c, p in got_swings(s)],
            "info_bos_under_approved_rules": bos_info(s),
            "expected_choch": ("SUPERSEDED by %s (decided by the 22 Nov 2026 approvals)" % SUPERSEDED[case["case_id"]])
            if case["case_id"] in SUPERSEDED else "UNSCORED: rule not finalised (spec Section 7)"})
    path = os.path.join(HERE, "choch_fixtures.draft.json")
    json.dump(out, open(path, "w"), indent=1)
    for c in out["decidable"]:
        if "expected_choch" not in c:
            print("%-6s %2d candles  sha %s  %s" % (c["case_id"], c["candle_count"], c["ohlc_sha256"][:12], c["title"]))
            continue
        e = c["expected_choch"]
        print("%-6s %2d candles  sha %s  %-8s -> %-13s %-11s prot=%-6s cand=c%-4s %s" % (
            c["case_id"], c["candle_count"], c["ohlc_sha256"][:12], e["state_before"], e["event"], e["state_after"],
            e["protected_swing_price"], e["candidate_candle"], [(b["direction"][:4], b["break_candle"], b["reference_price"]) for b in c["info_bos_under_approved_rules"]]))
    for c in out["unscored"]:
        print("%-6s %2d candles  sha %s  UNSCORED  swings=%s" % (c["case_id"], c["candle_count"], c["ohlc_sha256"][:12],
              [(d["kind"][0], d["candle"], d["price"]) for d in c["detector_swings"]]))
    print("wrote", os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
