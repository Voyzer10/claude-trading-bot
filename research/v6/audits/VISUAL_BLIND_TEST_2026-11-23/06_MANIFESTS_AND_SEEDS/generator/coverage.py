"""Feature coverage of the generated set, measured with the V6 code (cwd = repo). usage: coverage.py <build_dir>"""
import csv, glob, json, os, sys
from collections import Counter
from datetime import datetime
sys.path.insert(0, os.getcwd())
from scanner_v6.data.candle_models import CandleSeries
from scanner_v6.liquidity.setup_sweep import analyze_setup_sweeps, SetupSweepStream
from scanner_v6.liquidity.sweep import analyze_liquidity
from scanner_v6.structure.choch import analyze_structure, CHoCHBreak, StructureStateChange
from scanner_v6.structure.swings import detect_swings


def load(p):
    rows = list(csv.DictReader(open(p)))
    return CandleSeries.from_rows([(datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")), float(r["open"]), float(r["high"]),
                                    float(r["low"]), float(r["close"])) for r in rows], os.path.basename(p)[:-4], "5m")


def features(cs):
    f = Counter()
    st = analyze_structure(cs)
    lq = analyze_liquidity(cs)
    su = SetupSweepStream()
    for c in cs:
        su.on_candle(c)
    f["candles"] = len(cs)
    f["swings_H"] = sum(s.kind.value == "high" for s in st.swings)
    f["swings_L"] = sum(s.kind.value == "low" for s in st.swings)
    f["dual_pivot"] = len({s.index for s in st.swings if s.kind.value == "high"} & {s.index for s in st.swings if s.kind.value == "low"})
    f["BOS"] = len(st.bos)
    f["BOS_bull"] = sum(b.direction.value == "bullish" for b in st.bos)
    f["BOS_bear"] = sum(b.direction.value == "bearish" for b in st.bos)
    ch = [e for e in st.events if isinstance(e, CHoCHBreak)]
    f["CHoCH"] = len(ch)
    f["CHoCH_bull"] = sum(e.direction.value == "bullish" for e in ch)
    f["CHoCH_bear"] = sum(e.direction.value == "bearish" for e in ch)
    causes = Counter(e.cause for e in st.events if isinstance(e, StructureStateChange))
    f["ESTABLISHED"] = causes["ESTABLISHED"]
    f["REVERSAL_CONFIRMED"] = causes["REVERSAL_CONFIRMED"]
    f["COMPLEX"] = sum(type(e).__name__ == "ComplexStructureBreak" for e in st.events)
    f["protected_changes"] = len({x.protected_swing_id for x in st.timeline if x.protected_swing_id})
    bk = {b.index for b in st.bos}
    f["BOS_CHoCH_same_candle"] = sum(e.index in bk for e in ch)
    roles = Counter(st.bos_roles.values()) if hasattr(st, "bos_roles") else Counter(su.structure.bos_roles.values())
    for r, n in roles.items():
        f["role_" + r] = n
    diag = Counter(d.code for d in st.diagnostics)
    for d, n in diag.items():
        f["diag_" + d] = n
    f["pools_BSL"] = sum(p.side.value == "above" for p in lq.pools)
    f["pools_SSL"] = sum(p.side.value == "below" for p in lq.pools)
    et = Counter((e.event_type, e.side) for e in lq.events)
    for (t, s), n in et.items():
        f["%s_%s" % (t, s)] = n
    swept_then_taken = 0
    hist = {}
    for e in lq.events:
        hist.setdefault(e.pool_id, []).append(e.event_type)
    f["ACTIVE_SWEPT_TAKEN"] = sum(h[0] == "SWEEP" and h[-1] == "TAKEN" for h in hist.values())
    f["taken_direct"] = sum(h[0] == "TAKEN" for h in hist.values())
    f["multi_pool_group"] = sum(len(g.pool_ids) > 1 for g in lq.groups)
    gk = Counter(g.index for g in lq.groups)
    f["BSL_SSL_same_candle"] = sum(n == 2 for n in gk.values())
    f["outside_candle"] = sum(cs[i].high > cs[i - 1].high and cs[i].low < cs[i - 1].low for i in range(1, len(cs)))
    f["sweep_on_BOS_candle"] = len({g.index for g in lq.groups} & bk)
    eq = 0
    for i in range(1, len(cs)):
        for j in range(max(0, i - 4), i):
            if cs[i].high == cs[j].high or cs[i].low == cs[j].low:
                eq += 1
    f["equal_extremes_within_4"] = eq
    f["setup_candidates"] = len(su.candidates)
    for c in su.candidates:
        f["cand_" + c.status] += 1
    for d in su.diagnostics:
        f["setup_" + d.code] += 1
    return f


def main():
    tot = Counter()
    per = {}
    for p in sorted(glob.glob(sys.argv[1] + "/ohlc/*.csv")):
        f = features(load(p))
        per[os.path.basename(p)[:-4]] = f
        tot.update(f)
    keys = sorted(tot)
    print("chart  " + " ".join(k for k in ["candles", "BOS", "CHoCH", "REVERSAL_CONFIRMED", "SWEEP_BSL", "SWEEP_SSL",
                                            "TAKEN_BSL", "TAKEN_SSL", "REPEAT_SWEEP_BSL", "REPEAT_SWEEP_SSL",
                                            "multi_pool_group", "setup_candidates"]))
    for cid, f in per.items():
        print(cid, [f[k] for k in ["candles", "BOS", "CHoCH", "REVERSAL_CONFIRMED", "SWEEP_BSL", "SWEEP_SSL", "TAKEN_BSL",
                                   "TAKEN_SSL", "REPEAT_SWEEP_BSL", "REPEAT_SWEEP_SSL", "multi_pool_group", "setup_candidates"]])
    print("TOTAL", dict((k, tot[k]) for k in keys))
    if len(sys.argv) > 2:
        json.dump({"per_chart": per, "total": tot}, open(sys.argv[2], "w"), indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
