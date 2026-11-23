"""Aggregates r1_eval.py outputs into pooled tables (r1_pooled_*.csv) and charts (PNG). Research only."""
import csv, os, sys, collections, statistics as st
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
OUT = sys.argv[1]
rd = lambda n: list(csv.DictReader(open(os.path.join(OUT, n))))
S = rd("r1_summary_by_instrument_timeframe.csv"); SEG = rd("r1_segments.csv"); RUNS = rd("r1_unprotected_runs.csv")
H = rd("r1_atr_distance_hist.csv"); S1 = rd("r1_s1_reselections.csv"); C = rd("r1_synthetic_control.csv")
TFS = ("5m", "15m", "1h", "1D"); SAMPLES = ("PRIMARY", "EXTENDED")
PRIM = {"RELIANCE", "HDFCBANK", "INFY", "TCS", "SBIN", "ICICIBANK"}
def w(name, rows):
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        wr = csv.DictWriter(fh, list(rows[0].keys())); wr.writeheader(); wr.writerows(rows)
I = lambda r, k: int(r[k])
F = lambda r, k: float(r[k]) if r[k] not in ("", "nan") else float("nan")
agg = []
for smp in SAMPLES + ("ALL",):
    for tf in TFS:
        R = [r for r in S if r["timeframe"] == tf and (smp == "ALL" or r["sample"] == smp)]
        t = lambda k: sum(I(r, k) for r in R)
        Sc, U = t("S_clean"), t("unprotected_clean")
        ub = round(sum(F(r, "unprotected_pct_bullish") * I(r, "S_bullish") / 100 for r in R if I(r, "S_bullish")), 0)
        ue = round(sum(F(r, "unprotected_pct_bearish") * I(r, "S_bearish") / 100 for r in R if I(r, "S_bearish")), 0)
        sg = sum(F(r, "unprotected_pct_in_session_gap") * I(r, "structured_in_session_gap") / 100 for r in R if I(r, "structured_in_session_gap"))
        dq = sum(F(r, "unprotected_pct_in_data_quality") * I(r, "structured_in_data_quality") / 100 for r in R if I(r, "structured_in_data_quality"))
        legs = t("eligible_bos_legs")
        aff = len({(x["instrument"], x["timeframe"], x["bos_id"]) for x in S1 if x["timeframe"] == tf and (smp == "ALL" or x["sample"] == smp)})
        cls = len({(x["instrument"], x["timeframe"], x["bos_id"]) for x in S1 if x["timeframe"] == tf and (smp == "ALL" or x["sample"] == smp) and x["old_was_active"] == "True" and x["new_qualifies_a5"] == "False"})
        s1b = len({(x["instrument"], x["bos_id"]) for x in S1 if x["timeframe"] == tf and (smp == "ALL" or x["sample"] == smp) and x["direction"] == "bullish"})
        s1e = len({(x["instrument"], x["bos_id"]) for x in S1 if x["timeframe"] == tf and (smp == "ALL" or x["sample"] == smp) and x["direction"] == "bearish"})
        runs = sorted(int(x["run_len"]) for x in RUNS if x["timeframe"] == tf and (smp == "ALL" or x["sample"] == smp))
        q = lambda p: runs[min(len(runs) - 1, int(p * (len(runs) - 1) + .5))] if runs else ""
        agg.append(dict(sample=smp, timeframe=tf, instruments=len(R), candles=t("candles"),
            data_quality=t("n_data_quality"), session_gap=t("n_session_gap"), insufficient_history=t("n_insufficient_history"),
            transition=t("n_transition"), unknown_structure=t("n_unknown_structure"), S_clean=Sc, unprotected=U,
            unprotected_pct=round(100 * U / Sc, 2) if Sc else "n/a",
            S_all_structured=t("S_all_structured"),
            unprotected_pct_all_structured=round(sum(F(r, "unprotected_pct_all_structured") * I(r, "S_all_structured") / 100 for r in R if I(r, "S_all_structured")) / max(t("S_all_structured"), 1) * 100, 2),
            S_bullish=t("S_bullish"), unprotected_pct_bullish=round(100 * ub / t("S_bullish"), 2) if t("S_bullish") else "n/a",
            S_bearish=t("S_bearish"), unprotected_pct_bearish=round(100 * ue / t("S_bearish"), 2) if t("S_bearish") else "n/a",
            unprotected_pct_session_gap_candles=round(100 * sg / t("structured_in_session_gap"), 2) if t("structured_in_session_gap") else "n/a",
            unprotected_pct_data_quality_candles=round(100 * dq / t("structured_in_data_quality"), 2) if t("structured_in_data_quality") else "n/a",
            cause_no_origin_swing=t("cause_no_origin_swing"), cause_not_qualified_a5=t("cause_not_qualified_a5"),
            cause_origin_pending=t("cause_origin_pending"), cause_no_same_direction_bos=t("cause_no_same_direction_bos"),
            cause_consumed=t("cause_consumed") + t("cause_consumed_or_superseded"),
            unprot_runs=len(runs), run_len_median=q(.5), run_len_p90=q(.9), run_len_max=runs[-1] if runs else "",
            runs_spanning_session_break_pct=round(100 * sum(1 for x in RUNS if x["timeframe"] == tf and (smp == "ALL" or x["sample"] == smp) and int(x["session_breaks_spanned"])) / len(runs), 2) if runs else "n/a",
            legs_origin_on_bos_candle=t("legs_origin_on_bos_candle"), legs_origin_on_k_minus_1=t("legs_origin_on_k_minus_1"), legs_origin_earlier=t("legs_origin_earlier"),
            activation_lag0_pct=round(sum(F(r, "activation_lag_lag0_pct") * I(r, "activations") / 100 for r in R) / max(t("activations"), 1) * 100, 2),
            bos=t("bos"), activations=t("activations"), activations_per_1000_candles=round(1000 * t("activations") / t("candles"), 2),
            bos_with_activation_pct=round(100 * sum(F(r, "bos_with_activation_pct") * I(r, "bos") / 100 for r in R) / max(t("bos"), 1), 2),
            missed_breaks=t("missed_breaks_while_unprotected"), missed_per_1000_S=round(1000 * t("missed_breaks_while_unprotected") / Sc, 2) if Sc else "n/a",
            eligible_bos_legs=legs, s1_legs_affected=aff, s1_legs_affected_pct=round(100 * aff / legs, 2) if legs else "n/a",
            s1_classic_active_kept=cls, s1_bullish_legs=s1b, s1_bearish_legs=s1e,
            choch_official=t("choch_official"),
            **{"cf_%s_choch" % o: t("cf_%s_choch" % o) for o in ("O2_LA_WITHDRAW", "O3_REPLACE_VS_PRE_LEG", "O4_EXCLUDE_BOS_CANDLE")},
            **{"cf_%s_choch_changed" % o: t("cf_%s_choch_diff" % o) for o in ("O2_LA_WITHDRAW", "O3_REPLACE_VS_PRE_LEG", "O4_EXCLUDE_BOS_CANDLE")},
            **{"cf_%s_prot_candles_changed" % o: t("cf_%s_prot_candles_diff" % o) for o in ("O2_LA_WITHDRAW", "O3_REPLACE_VS_PRE_LEG", "O4_EXCLUDE_BOS_CANDLE")},
            reliable_series="%d/%d" % (sum(r["reliability"] == "OK" for r in R), len(R))))
w("r1_pooled_metrics.csv", agg)
# pooled ATR distance quantiles from histogram (bin-level)
dh = []
for smp in SAMPLES + ("ALL",):
    for tf in TFS:
        b = collections.OrderedDict()
        for x in H:
            if x["timeframe"] == tf and (smp == "ALL" or x["sample"] == smp):
                b[(x["atr_bin_lo"], x["atr_bin_hi"])] = b.get((x["atr_bin_lo"], x["atr_bin_hi"]), 0) + int(x["candles"])
        tot = sum(b.values())
        for (lo, hi), n in b.items():
            dh.append(dict(sample=smp, timeframe=tf, atr_bin="[%s, %s)" % (lo, hi), candles=n, pct=round(100 * n / tot, 2) if tot else "n/a"))
w("r1_pooled_atr_distance.csv", dh)
seg = []
for smp in SAMPLES + ("ALL",):
    for tf in TFS:
        for dim in ("session", "vol", "trend", "direction"):
            g = collections.defaultdict(lambda: [0, 0])
            for x in SEG:
                if x["timeframe"] == tf and x["dimension"] == dim and (smp == "ALL" or (x["instrument"] in PRIM) == (smp == "PRIMARY")):
                    g[x["segment"]][0] += int(x["S"]); g[x["segment"]][1] += int(x["unprotected"])
            for k, (n, u) in sorted(g.items()):
                seg.append(dict(sample=smp, timeframe=tf, dimension=dim, segment=k, S=n, unprotected=u,
                                unprotected_pct=round(100 * u / n, 2) if n else "n/a",
                                reliability="OK" if n >= 500 else "INSUFFICIENT DATA (S<500)"))
w("r1_pooled_segments.csv", seg)
# S-1 by instrument x timeframe (ranked)
rank = []
for r in S:
    if int(r["eligible_bos_legs"]):
        rank.append(dict(instrument=r["instrument"], timeframe=r["timeframe"], sample=r["sample"], legs=r["eligible_bos_legs"],
                         s1_legs_affected_pct=r["s1_legs_affected_pct"], s1_reselections=r["s1_reselections"], reliability=r["s1_reliability"]))
rank.sort(key=lambda x: -float(x["s1_legs_affected_pct"]))
w("r1_s1_by_instrument_timeframe.csv", rank)
# control pooled
ctl = []
for tf in ("5m", "15m", "1h"):
    c = [x for x in C if x["timeframe"] == tf]; n = sum(int(x["S_clean"]) for x in c)
    ctl.append(dict(timeframe=tf, label="SYNTHETIC CONTROL (not market data)", series=len(c), S_clean=n,
                    unprotected_pct=round(sum(float(x["unprotected_pct_clean"]) * int(x["S_clean"]) / 100 for x in c) / n * 100, 2),
                    s1_legs_affected_pct_mean=round(st.mean(float(x["s1_legs_affected_pct"]) for x in c), 2)))
w("r1_pooled_synthetic_control.csv", ctl)
# ---- charts
P = os.path.join(OUT, "charts"); os.makedirs(P, exist_ok=True)
A = {(r["sample"], r["timeframe"]): r for r in agg}
plt.rcParams.update({"font.size": 9})
# 1 unprotected % per instrument x TF (primary) + pooled
fig, ax = plt.subplots(figsize=(8, 3.6))
inst = ["RELIANCE", "HDFCBANK", "INFY", "TCS", "SBIN", "ICICIBANK"]
for j, tf in enumerate(("5m", "15m", "1h")):
    vals = [next(float(r["unprotected_pct_clean"]) for r in S if r["instrument"] == i and r["timeframe"] == tf) for i in inst]
    ax.bar([k + j * 0.27 for k in range(len(inst))], vals, 0.27, label=tf + (" (INSUFFICIENT per series)" if tf == "1h" else ""))
ax.set_xticks([k + 0.27 for k in range(len(inst))]); ax.set_xticklabels(inst)
ax.set_ylabel("% of clean structured candles\nwithout a protected swing"); ax.set_ylim(0, 100)
ax.set_title("R-1: unprotected share, NSE primary stocks (Yahoo 5m, 5 Aug-30 Oct 2026)")
ax.legend(frameon=False, fontsize=8); fig.tight_layout(); fig.savefig(os.path.join(P, "r1_unprotected_by_instrument.png"), dpi=150); plt.close(fig)
# 2 causes stacked per TF (ALL)
fig, ax = plt.subplots(figsize=(7, 3.4))
causes = [("cause_no_origin_swing", "NO_ORIGIN_SWING"), ("cause_not_qualified_a5", "NOT_QUALIFIED (A5)"), ("cause_origin_pending", "ORIGIN_PENDING"), ("cause_no_same_direction_bos", "NO_SAME_DIR_BOS")]
bottom = [0, 0, 0]
for k, lab in causes:
    v = [100 * int(A[("ALL", tf)][k]) / max(int(A[("ALL", tf)]["unprotected"]), 1) for tf in ("5m", "15m", "1h")]
    ax.bar(("5m", "15m", "1h"), v, bottom=bottom, label=lab); bottom = [b + x for b, x in zip(bottom, v)]
ax.set_ylabel("% of unprotected candles"); ax.set_title("Why no protected swing (all 50 NSE stocks)")
ax.legend(frameon=False, fontsize=8, loc="center left", bbox_to_anchor=(1, .5)); fig.tight_layout(); fig.savefig(os.path.join(P, "r1_unprotected_causes.png"), dpi=150); plt.close(fig)
# 3 run-length CDF
fig, ax = plt.subplots(figsize=(6.5, 3.4))
for tf in ("5m", "15m", "1h"):
    xs = sorted(int(x["run_len"]) for x in RUNS if x["timeframe"] == tf)
    if xs: ax.plot(xs, [(i + 1) / len(xs) for i in range(len(xs))], label="%s (n=%d runs)" % (tf, len(xs)))
ax.set_xscale("log"); ax.set_xlabel("consecutive unprotected candles while BULLISH / BEARISH"); ax.set_ylabel("cumulative share of runs")
ax.set_title("Unprotected-gap length distribution (all 50 NSE stocks)"); ax.legend(frameon=False, fontsize=8)
fig.tight_layout(); fig.savefig(os.path.join(P, "r1_gap_length_cdf.png"), dpi=150); plt.close(fig)
# 4 bullish vs bearish + control
fig, ax = plt.subplots(figsize=(7, 3.4))
tfs = ("5m", "15m", "1h"); x = range(len(tfs))
ax.bar([i - .27 for i in x], [float(A[("ALL", t)]["unprotected_pct_bullish"]) for t in tfs], .27, label="bullish structure")
ax.bar(list(x), [float(A[("ALL", t)]["unprotected_pct_bearish"]) for t in tfs], .27, label="bearish structure")
cp = {r["timeframe"]: float(r["unprotected_pct"]) for r in ctl}
ax.bar([i + .27 for i in x], [cp[t] for t in tfs], .27, label="synthetic control (random walk)", hatch="//", fill=False)
ax.set_xticks(list(x)); ax.set_xticklabels(tfs); ax.set_ylim(0, 100); ax.set_ylabel("% unprotected")
ax.set_title("Bullish vs bearish (all 50 NSE stocks) vs synthetic control"); ax.legend(frameon=False, fontsize=8)
fig.tight_layout(); fig.savefig(os.path.join(P, "r1_bull_bear_control.png"), dpi=150); plt.close(fig)
print("ok")
