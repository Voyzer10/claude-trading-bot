"""Builds the Phase-3.1 S-1 DRAFT fixtures (SX00-SX10, bullish + bearish mirror) and records what each counterfactual
option (O1 / O3A / O3B / O3) produces. The recorded outcomes are SIMULATOR OUTPUT, NOT approved expectations.

    python3 s1_fixtures_v31.py <out_dir>
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

V6_ROOT = os.environ.get("V6_ROOT", "/home/claude/v6_wt")
sys.path.insert(0, V6_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.engine import no_lookahead_violations, replay_audit  # noqa: E402
from scanner_v6.structure.choch import CHoCHBreak, StructureStateChange  # noqa: E402
import s1_ab  # noqa: E402

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
CHD = json.load(open(os.path.join(V6_ROOT, "research", "v6", "specs", "choch_v0_9", "choch_fixtures.draft.json")))
BASE = [(r["o"], r["h"], r["l"], r["c"]) for r in [c for c in CHD["decidable"] if c["case_id"] == "CHD01"][0]["candles"][:16]]
# BASE c1-c16 (CHD01): BULLISH established at c16, protected low 101 (c10); swing high 116 (c14, conf c16);
# swing low 106 (c16, conf c18 once c17/c18 lows stay above 106)
LEG_A = [(107.5, 110, 107.5, 109), (109, 111, 108, 110)]                       # c17-c18: 106 confirms at c18
F = {
    "SX00": dict(title="control: no late candidate, no in-leg swing (CHD01 as given)",
                 category="control", rows=[(r["o"], r["h"], r["l"], r["c"]) for r in [c for c in CHD["decidable"] if c["case_id"] == "CHD01"][0]["candles"]]),
    "SX01": dict(title="O3-A path, late candidate PASSES A5 vs pre-leg (late low 104 on the BOS candle k); close 105.5 between 104 and 106",
                 category="A / passes", rows=BASE + LEG_A + [(110, 117, 104, 116.5), (116.5, 118, 104.5, 117), (117, 119, 106, 118), (118, 118.5, 105, 105.5)]),
    "SX02": dict(title="O3-A path, late candidate PASSES A5 (late low 104 on k-1; BOS on c20); close 105.5",
                 category="A / passes", rows=BASE + LEG_A + [(110, 112, 104, 111), (111, 117, 105, 116.5), (116.5, 118, 105.5, 117), (117, 119, 106, 118), (118, 118.5, 105, 105.5)]),
    "SX03": dict(title="O3-A path, late candidate FAILS A5 vs pre-leg: late low 100 < 101, i.e. the late candidate's wick INVALIDATES the original protected swing 101 (close 116.5 stays above); close 102 later",
                 category="A / fails + invalidates original", rows=BASE + LEG_A + [(110, 117, 100, 116.5), (116.5, 118, 100.5, 117), (117, 119, 102, 118), (118, 118.5, 101.5, 102)]),
    "SX04": dict(title="O3-A path, late candidate PASSES; close 103.5 below the late low 104",
                 category="A / passes", rows=BASE + LEG_A + [(110, 117, 104, 116.5), (116.5, 118, 104.5, 117), (117, 119, 106, 118), (118, 118.5, 103, 103.5)]),
    "SX05": dict(title="the activated protected 106 is INVALIDATED (CHoCH, consumed) BEFORE the late candidate 104 confirms; later bearish BOS",
                 category="A / original invalidated first", rows=BASE + LEG_A + [(110, 117, 104, 116.5), (116.5, 118, 105, 105.5), (105.5, 107, 104.5, 106), (106, 106.5, 103, 103.5)]),
    "SX06": dict(title="O3-A path then a REPEATED continuation BOS (c25 over 119, origin 112); close 111 at c27",
                 category="A / repeated continuation BOS", rows=BASE + LEG_A + [(110, 117, 104, 116.5), (116.5, 118, 104.5, 117), (117, 119, 106, 118), (118, 118.5, 115, 116), (116, 117, 114, 115), (115, 116, 112, 113), (113, 121, 113, 120.5), (120.5, 121.5, 114, 115), (115, 116, 110, 111)]),
    "SX07": dict(title="O3-B path (no late candidate): two lows in one leg, 106 (c16) then 104 (c20) with no swing high between; BOS c23 over 116; origin 104 is LL vs in-leg 106 but HL vs pre-leg 101 -> PASSES under O3-B; close 103.5",
                 category="B / passes", rows=BASE + [(107.5, 110, 107.5, 109), (109, 110, 107, 108), (108, 109, 105, 106.5), (106.5, 107, 104, 106.2), (106.2, 108, 104.5, 107.5), (107.5, 112, 107, 111.5), (111.5, 117, 111, 116.5), (116.5, 117, 103, 103.5)]),
    "SX08": dict(title="O3-B path, FAILS A5 even vs pre-leg: second in-leg low 100 < 101 (its wick INVALIDATES the original protected 101; close stays above); close 103.5",
                 category="B / fails + invalidates original", rows=BASE + [(107.5, 110, 107.5, 109), (109, 110, 107, 108), (108, 109, 105, 106.5), (106.5, 107, 100, 106.2), (106.2, 108, 100.5, 107.5), (107.5, 112, 107, 111.5), (111.5, 117, 111, 116.5), (116.5, 117, 103, 103.5)]),
    "SX09": dict(title="O3-B path then a REPEATED continuation BOS (c29 over 119, origin 111); close 110.5 at c31",
                 category="B / repeated continuation BOS", rows=BASE + [(107.5, 110, 107.5, 109), (109, 110, 107, 108), (108, 109, 105, 106.5), (106.5, 107, 104, 106.2), (106.2, 108, 104.5, 107.5), (107.5, 112, 107, 111.5), (111.5, 117, 111, 116.5), (116.5, 118, 115, 117), (117, 119, 116, 118.5), (118.5, 118.8, 114, 115), (115, 116, 112, 113), (113, 114, 111, 113.5), (113.5, 121, 113, 120.5), (120.5, 122, 114, 121), (121, 121.5, 110, 110.5)]),
    "SX10": dict(title="A AND B in the SAME leg: in-leg lows 106 then 104 (B path) plus a late low 103 on the BOS candle (A path); close 103.8",
                 category="A + B interaction", rows=BASE + [(107.5, 110, 107.5, 109), (109, 110, 107, 108), (108, 109, 105, 106.5), (106.5, 107, 104, 106.2), (106.2, 108, 104.5, 107.5), (107.5, 112, 107, 111.5), (111.5, 117, 103, 116.5), (116.5, 118, 105, 117), (117, 119, 106, 118), (118, 118.5, 103.5, 103.8)]),
}


def mirror(rows, axis=200.0):
    return [(axis - o, axis - l, axis - h, axis - c) for o, h, l, c in rows]


def series(rows, name):
    return CandleSeries.from_rows([(T0 + timedelta(minutes=5 * i), o, h, l, c, 0) for i, (o, h, l, c) in enumerate(rows)], name, "5m")


def outcome(st, ev):
    ch = [(e.index + 1, e.direction.value, e.level) for e in ev if isinstance(e, CHoCHBreak)]
    rv = [(e.index + 1, e.state_after) for e in ev if isinstance(e, StructureStateChange) and e.cause == "REVERSAL_CONFIRMED"]
    prot = []
    last = object()
    for t in st.timeline:
        if t.protected_price != last:
            prot.append((t.index + 1, t.protected_price))
            last = t.protected_price
    return dict(choch=ch, reversal=rv, final_state=st.timeline[-1].state, protected_changes=prot,
                origin_log=[(k + 1, d, path, old, new, base, ok, act) for k, _, d, path, old, new, base, ok, act in st.tracker.log],
                bos=[(b.direction.value, b.index + 1, b.level) for b in st.bos_events])


def main(out):
    os.makedirs(out, exist_ok=True)
    fixtures, rows_csv = [], []
    for cid, f in F.items():
        for direction, rows in (("bullish", f["rows"]), ("bearish", mirror(f["rows"]))):
            s = series(rows, cid)
            # every fixture must be causal and stream / batch consistent under the OFFICIAL code
            from scanner_v6.structure.choch import StructureStream, detect_structure
            exp = {e.id: e.index for e in detect_structure(s)}
            a = replay_audit(s, exp, lambda e: e.id, detector=detect_structure, make_stream=StructureStream)
            assert a.ok and no_lookahead_violations(detect_structure, s) == [], (cid, direction)
            res = {}
            for opt in s1_ab.OPTIONS:
                st, ev = s1_ab.run(s, opt)
                res[opt] = outcome(st, ev)
                o = res[opt]
                rows_csv.append(dict(case_id=cid, direction=direction, category=f["category"], option=opt,
                                     choch=";".join("c%d %s@%s" % x for x in o["choch"]) or "none",
                                     reversal=";".join("c%d %s" % x for x in o["reversal"]) or "none",
                                     final_state=o["final_state"],
                                     protected_changes=" ".join("c%d:%s" % x for x in o["protected_changes"]),
                                     origin_paths=";".join("c%d %s %s->%s base=%s A5=%s act=%s" % (k, path, old, new, base, ok, act)
                                                           for k, d, path, old, new, base, ok, act in o["origin_log"] if k >= 17)))
            fixtures.append(dict(case_id=cid + ("" if direction == "bullish" else "M"), base_case=cid, direction=direction,
                                 category=f["category"], title=f["title"] + ("" if direction == "bullish" else " [MIRROR p -> 200 - p]"),
                                 status="DRAFT / UNSCORED: no option is approved; O1 is the temporary research baseline",
                                 candles=[dict(candle=i + 1, t=(T0 + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z"),
                                               o=o_, h=h, l=l, c=c) for i, (o_, h, l, c) in enumerate(rows)],
                                 counterfactual_outcomes_not_expectations=res))
    json.dump(dict(spec="V6 S-1 Phase 3.1 counterfactual fixtures", generated="2026-11-22",
                   options={k: dict(first_evaluation_base=v[0], late_candidate_base=v[1]) for k, v in s1_ab.OPTIONS.items()},
                   shared_sub_rule="a candidate failing A5 leaves the active protected swing unchanged (owner to confirm)",
                   baseline="O1 (official implementation) = temporary research baseline", fixtures=fixtures),
              open(os.path.join(out, "s1_fixtures_v31.draft.json"), "w"), indent=1)
    with open(os.path.join(out, "s1_fixtures_v31_outcomes.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, list(rows_csv[0].keys()))
        w.writeheader()
        w.writerows(rows_csv)
    return rows_csv


if __name__ == "__main__":
    for r in main(sys.argv[1]):
        if r["direction"] == "bullish":
            print(r["case_id"], r["option"], "| CHoCH:", r["choch"], "| rev:", r["reversal"], "| final:", r["final_state"], "| prot:", r["protected_changes"], "| paths:", r["origin_paths"])
