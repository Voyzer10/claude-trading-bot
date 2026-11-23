"""Measures O3-A and O3-B SEPARATELY (and together) against the O1 research baseline on the existing NSE cache.
Counterfactual only (s1_ab.py); the official results of the Phase-3 R-1 report are untouched.

    python3 s1_ab_measure.py <raw dir with *.NS_5m.json> <out dir>
"""
import csv
import glob
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
V6_ROOT = os.environ.get("V6_ROOT", "/home/claude/v6_wt")
sys.path.insert(0, V6_ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, os.environ.get("R1_SCRIPTS", os.path.normpath(os.path.join(HERE, "..", "..", "R1_artifacts", "scripts"))))
import r1_eval as R  # noqa: E402  (loader / resampler of the Phase-3 evaluation, reused unchanged)
import s1_ab  # noqa: E402
from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.structure.choch import CHoCHBreak  # noqa: E402

OPTS = ["O1", "O3A", "O3B", "O3"]


def leg_signature(log):
    sig = defaultdict(list)
    for k, bid, d, path, old, new, base, ok, act in log:
        sig[bid].append((k, path, new, ok, act))
    return sig


def main(raw, out):
    os.makedirs(out, exist_ok=True)
    per_series, legs_rows = [], []
    for f in sorted(glob.glob(os.path.join(raw, "*.NS_5m.json"))):
        sym = os.path.basename(f).split(".NS_")[0]
        rows, meta, qc = R.load_raw(f)
        sample = "PRIMARY" if sym in R.PRIMARY else "EXTENDED"
        for tf in ("5m", "15m", "1h", "1D"):
            bars = R.as_bars(rows) if tf == "5m" else R.resample(rows, {"15m": 15, "1h": 60, "1D": "1D"}[tf])
            s = CandleSeries.from_rows([(datetime.fromtimestamp(b["t"], timezone.utc), b["o"], b["h"], b["l"], b["c"], b["v"]) for b in bars], sym, tf)
            res = {}
            for o in OPTS:
                st, ev = s1_ab.run(s, o)
                res[o] = dict(choch={(e.index, e.direction.value, e.level) for e in ev if isinstance(e, CHoCHBreak)},
                              prot=[t.protected_price for t in st.timeline],
                              structured=[t.state in ("BULLISH", "BEARISH") for t in st.timeline],
                              sig=leg_signature(st.tracker.log), log=st.tracker.log)
            base = res["O1"]
            # which legs does each switch touch?  A touches a leg when one of its LATE evaluations changes verdict;
            # B touches a leg when its FIRST evaluation changes verdict (judged on the option's own run)
            def touched(opt, path):
                t = set()
                for k, bid, d, pth, old, new, b_, ok, act in res[opt]["log"]:
                    if pth == path:
                        o1 = [x for x in base["sig"].get(bid, []) if x[1] == path and x[2] == new]
                        if not o1 or o1[0][3] != ok:
                            t.add(bid)
                return t
            A_legs, B_legs = touched("O3A", "LATE"), touched("O3B", "FIRST")
            AB_late, AB_first = touched("O3", "LATE"), touched("O3", "FIRST")
            late_paths = sum(1 for x in base["log"] if x[3] == "LATE")
            legs = len({x[1] for x in base["log"]})
            row = dict(instrument=sym, timeframe=tf, sample=sample, candles=len(bars), eligible_legs=legs,
                       late_evaluations_O1=late_paths, legs_touched_O3A=len(A_legs), legs_touched_O3B=len(B_legs),
                       legs_touched_O3_late=len(AB_late), legs_touched_O3_first=len(AB_first),
                       legs_touched_O3_both_paths=len(AB_late & AB_first))
            for o in OPTS:
                r = res[o]
                st_n = sum(r["structured"])
                un = sum(1 for p, sflag in zip(r["prot"], r["structured"]) if sflag and p is None)
                row["choch_" + o] = len(r["choch"])
                row["unprot_pct_all_structured_" + o] = round(100.0 * un / st_n, 2) if st_n else ""
                row["structured_" + o] = st_n
                row["unprotected_" + o] = un
                if o != "O1":
                    row["choch_changed_" + o] = len(r["choch"] ^ base["choch"])
                    row["prot_candles_changed_" + o] = sum(1 for a, b in zip(r["prot"], base["prot"]) if a != b)
            # additivity at candle level: is O3 explained by A alone or B alone wherever only one of them differs?
            pa, pb, p3, p1 = res["O3A"]["prot"], res["O3B"]["prot"], res["O3"]["prot"], base["prot"]
            both, unexplained = 0, 0
            for a, b, c3, c1 in zip(pa, pb, p3, p1):
                if a != c1 and b != c1:
                    both += 1
                elif (a != c1 and c3 != a) or (b != c1 and c3 != b) or (a == c1 and b == c1 and c3 != c1):
                    unexplained += 1
            row["candles_changed_by_both_A_and_B"] = both
            row["candles_O3_not_explained_by_single_switch"] = unexplained
            ch_union = (res["O3A"]["choch"] ^ base["choch"]) | (res["O3B"]["choch"] ^ base["choch"])
            row["choch_changed_O3_not_in_A_or_B"] = len((res["O3"]["choch"] ^ base["choch"]) - ch_union)
            per_series.append(row)
            print("done", sym, tf, flush=True)
    keys = list(per_series[0].keys())
    with open(os.path.join(out, "s1_ab_by_series.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, keys)
        w.writeheader()
        w.writerows(per_series)
    pooled = []
    for smp in ("PRIMARY", "EXTENDED", "ALL"):
        for tf in ("5m", "15m", "1h", "1D"):
            rs = [r for r in per_series if r["timeframe"] == tf and (smp == "ALL" or r["sample"] == smp)]
            t = lambda k: sum(int(r[k]) for r in rs)
            p = dict(sample=smp, timeframe=tf, series=len(rs), candles=t("candles"), eligible_legs=t("eligible_legs"),
                     late_evaluations=t("late_evaluations_O1"),
                     legs_touched_O3A=t("legs_touched_O3A"), legs_touched_O3A_pct=round(100.0 * t("legs_touched_O3A") / max(t("eligible_legs"), 1), 2),
                     legs_touched_O3B=t("legs_touched_O3B"), legs_touched_O3B_pct=round(100.0 * t("legs_touched_O3B") / max(t("eligible_legs"), 1), 2),
                     legs_touched_O3_both_paths=t("legs_touched_O3_both_paths"))
            for o in OPTS:
                p["choch_" + o] = t("choch_" + o)
                p["unprot_pct_all_structured_" + o] = round(100.0 * t("unprotected_" + o) / max(t("structured_" + o), 1), 2)
                if o != "O1":
                    p["choch_changed_" + o] = t("choch_changed_" + o)
                    p["prot_candles_changed_" + o] = t("prot_candles_changed_" + o)
            p["candles_changed_by_both_A_and_B"] = t("candles_changed_by_both_A_and_B")
            p["candles_O3_not_explained_by_single_switch"] = t("candles_O3_not_explained_by_single_switch")
            p["choch_changed_O3_not_in_A_or_B"] = t("choch_changed_O3_not_in_A_or_B")
            p["reliability"] = "INSUFFICIENT DATA (1D: 60 bars per series)" if tf == "1D" else ("INSUFFICIENT DATA per series; pooled indicative" if tf == "1h" else "OK")
            pooled.append(p)
    with open(os.path.join(out, "s1_ab_pooled.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, list(pooled[0].keys()))
        w.writeheader()
        w.writerows(pooled)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
