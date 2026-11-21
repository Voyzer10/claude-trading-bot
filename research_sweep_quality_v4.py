#!/usr/bin/env python3
"""Sweep quality research (21 Nov 2026), research only: why do ~half of the valid internal sweeps lose their protected
swing before the entry confirmation? No trading behaviour changes; no filter is chosen here.

Cohorts (the same published internal-sweep setups as research_entry_v4; E1 = the scanner's own confirmation):
  A  the protected swing closed through (or a CHoCH) after the sweep, before E1's confirmation
  B  E1's confirmation came first (protected structure intact until then)
  (other ends - no confirmation in 12 candles, a newer BOS, the session's end - are counted, not compared)

Features: ONLY candles up to and including the sweep candle j0 (decided at its close). Mirrored setups (shorts) are
in src terms, so every feature reads the same way for both sides. A prefix re-run (the chart cut right after j0)
checks for look-ahead: the setup must be published again with identical features.

    python research_scanner_v4.py sweepq nse|us|crypto [--json out.json]
    python research_sweep_quality_v4.py costaudit <entry_nse.json> <entry_us.json> [<entry_crypto.json>]"""
import bisect
import math
import os
import sys

import scanner_v4 as V4

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FEATURES = [  # name, what (all at the sweep candle's close)
    ("pen_atr", "sweep penetration beyond the swept level / ATR"),
    ("ref_prot_atr", "swept level - protected swing / ATR (0 = the protected swing itself)"),
    ("body_atr", "sweep candle body / ATR"),
    ("range_atr", "sweep candle range / ATR"),
    ("upper_wick", "upper wick / range (src terms: the wick away from the sweep)"),
    ("lower_wick", "lower wick / range (src terms: the sweep wick)"),
    ("close_loc", "close location in the range (0 = low, 1 = high; src terms)"),
    ("reclaim_atr", "close - swept level / ATR"),
    ("close_prot_atr", "close - protected swing / ATR"),
    ("leg_atr", "BOS leg: broken level - protected swing / ATR"),
    ("bars_bos_sweep", "candles from the BOS to the sweep"),
    ("atr_pct", "ATR(14) / close, %"),
    ("atr_rel", "ATR(14) / median ATR of the 100 candles before"),
    ("is_local", "swept level is an internal swing (1) or the protected-swing fallback (0)"),
    ("is_short", "setup direction: short (1) or long (0)"),
]


def features(sd, st, j0, short):
    b, ctx = sd.b, sd.ctx
    o, h, l, c = b[j0][1], b[j0][2], b[j0][3], b[j0][4]
    a = ctx.atr[j0]
    rng = h - l
    if not a:
        return None
    prior = [x for x in ctx.atr[max(0, j0 - 100):j0] if x]
    med = sorted(prior)[len(prior) // 2] if prior else None
    return {
        "pen_atr": st["sweep_pen"] / a,
        "ref_prot_atr": (st["lvl"] - st["origin"]) / a,
        "body_atr": abs(c - o) / a,
        "range_atr": rng / a,
        "upper_wick": (h - max(o, c)) / rng if rng > 0 else None,
        "lower_wick": (min(o, c) - l) / rng if rng > 0 else None,
        "close_loc": (c - l) / rng if rng > 0 else None,
        "reclaim_atr": (c - st["lvl"]) / a,
        "close_prot_atr": (c - st["origin"]) / a,
        "leg_atr": (st["level"] - st["origin"]) / a,
        "bars_bos_sweep": j0 - st["bos"],
        "atr_pct": 100.0 * a / abs(c),
        "atr_rel": a / med if med else None,
        "is_local": 1.0 if st["lvl_name"] == "local_swing" else 0.0,
        "is_short": 1.0 if short else 0.0,
    }


def chart(args):
    import research_features as F
    import research_entry_v4 as E
    market, sym, rows, tm = args
    m = F.MARKETS[market]
    day_of = (lambda t: m["local"](t).date())
    kw = dict(tm, sweep_rule="internal", sweep_max_bars=12, sweep_pen_atr=0.25, entry_max_bars=12)
    sweeps = []
    V4.sequence(rows, day_of, intraday=m["intraday"], max_hold=None, _sweeps=sweeps, **kw)
    out, leak = [], None
    for n, (sd, st, j0) in enumerate(sweeps):
        short = sd.b is not rows
        f = features(sd, st, j0, short)
        e1 = E.setup_trades(sd, st, j0, m["intraday"])["E1 control"]
        why = e1["why"]
        cohort = ("B" if e1["opp"] else "A" if why in ("closed beyond the protected swing", "CHoCH") else "other")
        out.append({"sym": sym, "side": "long" if sd.b is rows else "short", "bos": st["bos"], "sweep": j0,
                    "day": day_of(rows[j0][0]).isoformat(), "cohort": cohort, "end": why, "f": f})
        if leak is None and f is not None:
            # look-ahead check: the chart cut right after the sweep candle publishes the same setup, same features
            sw2, rows2 = [], rows[:j0 + 1]
            V4.sequence(rows2, day_of, intraday=m["intraday"], max_hold=None, _sweeps=sw2, **kw)
            same = False
            for sd2, st2, j2 in sw2:
                short2 = sd2.b is not rows2
                if j2 == j0 and st2["bos"] == st["bos"] and short2 == short:
                    f2 = features(sd2, st2, j2, short2)
                    same = bool(f2) and all((f[k] is None and f2[k] is None) or (
                        f[k] is not None and f2[k] is not None and abs(f[k] - f2[k]) < 1e-12) for k in f)
                    break
            leak = {"sym": sym, "bos": st["bos"], "sweep": j0, "identical": bool(same)}
    return sym, out, leak


# ----------------------------------------------------------------- statistics (no thresholds chosen)
def _q(xs, p):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    f = math.floor(k)
    return xs[f] + (xs[min(f + 1, len(xs) - 1)] - xs[f]) * (k - f)


def _auc(a, b):
    """P(feature of A > feature of B) + 0.5 P(tie) (Mann-Whitney), its normal-approximation p-value and Hanley-McNeil
    standard error. 0.5 = no separation."""
    na, nb = len(a), len(b)
    if not na or not nb:
        return None
    allv = sorted([(x, 0) for x in a] + [(x, 1) for x in b])
    ranks, i = [0.0] * len(allv), 0
    tie_term = 0.0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = r
        t = j - i + 1
        tie_term += t ** 3 - t
        i = j + 1
    ra = sum(r for r, (_, g) in zip(ranks, allv) if g == 0)
    u = ra - na * (na + 1) / 2
    auc = u / (na * nb)
    n = na + nb
    var = na * nb / 12 * ((n + 1) - tie_term / (n * (n - 1))) if n > 1 else 0
    z = (u - na * nb / 2) / math.sqrt(var) if var > 0 else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    q1, q2 = auc / (2 - auc), 2 * auc * auc / (1 + auc)
    se = math.sqrt(max(0.0, (auc * (1 - auc) + (na - 1) * (q1 - auc * auc) + (nb - 1) * (q2 - auc * auc)) / (na * nb)))
    return auc, p, se


def _desc(xs):
    if not xs:
        return "n 0"
    mean = sum(xs) / len(xs)
    return "n %5d mean %7.3f med %7.3f Q1 %7.3f Q3 %7.3f" % (len(xs), mean, _q(xs, .5), _q(xs, .25), _q(xs, .75))


def _cmp(a, b):
    """mean(A) - mean(B) with a Welch 95% CI, Cohen's d (pooled)."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    se = math.sqrt(va / na + vb / nb)
    sp = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return ma - mb, 1.96 * se, (ma - mb) / sp if sp > 0 else 0.0


def _bh(ps):
    """Benjamini-Hochberg q-values for a list of p-values (None kept)."""
    idx = sorted((p, i) for i, p in enumerate(ps) if p is not None)
    q = [None] * len(ps)
    m = len(idx)
    prev = 1.0
    for rank in range(m, 0, -1):
        p, i = idx[rank - 1]
        prev = min(prev, p * m / rank)
        q[i] = prev
    return q


def _logit_fit(X, y, iters=3000, lr=0.1, l2=1e-3):
    import numpy as np
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    w = np.zeros(X.shape[1])
    b0 = 0.0
    for _ in range(iters):
        z = X @ w + b0
        pr = 1 / (1 + np.exp(-z))
        g = pr - y
        w -= lr * (X.T @ g / len(y) + l2 * w)
        b0 -= lr * g.mean()
    return w, b0


def report(market, rows, split):
    L = []
    P = L.append
    names = [n for n, _ in FEATURES]
    coh = {}
    for r in rows:
        coh[r["cohort"]] = coh.get(r["cohort"], 0) + 1
    P("%s: %d published internal-sweep setups. Cohort A (protected broken before confirmation) %d, cohort B "
      "(confirmation first) %d, other ends %d. In-sample before %s." % (
          market, len(rows), coh.get("A", 0), coh.get("B", 0), coh.get("other", 0), split))
    for part, f in (("IS", lambda r: r["day"] < split), ("OOS", lambda r: r["day"] >= split)):
        sub = [r for r in rows if f(r) and r["cohort"] in "AB"]
        na = sum(1 for r in sub if r["cohort"] == "A")
        P("  %s: A %d, B %d -> A share %.1f%% of A+B" % (part, na, len(sub) - na, 100 * na / max(1, len(sub))))
    res = {}
    for part, f in (("IS", lambda r: r["day"] < split), ("OOS", lambda r: r["day"] >= split)):
        sub = [r for r in rows if f(r) and r["cohort"] in "AB" and r["f"]]
        res[part] = {}
        for n in names:
            a = [r["f"][n] for r in sub if r["cohort"] == "A" and r["f"][n] is not None]
            b = [r["f"][n] for r in sub if r["cohort"] == "B" and r["f"][n] is not None]
            miss = sum(1 for r in sub if r["f"][n] is None)
            res[part][n] = {"a": a, "b": b, "miss": miss, "auc": _auc(a, b), "cmp": _cmp(a, b)}
        qs = _bh([res[part][n]["auc"][1] if res[part][n]["auc"] else None for n in names])
        for n, q in zip(names, qs):
            res[part][n]["q"] = q
    P("\nPER FEATURE (A = invalidated first, B = confirmed first). AUC = P(A's value > B's); 0.5 = no separation. "
      "q = Benjamini-Hochberg over the %d features of that period. d = Cohen's d (A - B)." % len(names))
    for n, what in FEATURES:
        P("\n  %s: %s" % (n, what))
        for part in ("IS", "OOS"):
            x = res[part][n]
            P("    %-3s A %s" % (part, _desc(x["a"])))
            P("    %-3s B %s   missing %d" % (part, _desc(x["b"]), x["miss"]))
            if x["auc"] and x["cmp"]:
                auc, p, se = x["auc"]
                dm, ci, d = x["cmp"]
                P("    %-3s mean A-B %+.3f ±%.3f | d %+.2f | AUC %.3f [%.3f, %.3f] p %.2g q %.2g" % (
                    part, dm, ci, d, auc, auc - 1.96 * se, auc + 1.96 * se, p, x["q"]))
    P("\nSTABILITY (same direction in IS and OOS, IS q < 0.05 after BH, OOS AUC 95% CI excluding 0.5):")
    for n, _ in FEATURES:
        i, o = res["IS"][n], res["OOS"][n]
        if not (i["auc"] and o["auc"]):
            continue
        same = (i["auc"][0] - 0.5) * (o["auc"][0] - 0.5) > 0
        sig_is = i["q"] is not None and i["q"] < 0.05
        oos_ci = abs(o["auc"][0] - 0.5) > 1.96 * o["auc"][2]
        P("  %-15s IS AUC %.3f (q %.2g) | OOS AUC %.3f ±%.3f | same direction %s | IS significant %s | OOS CI "
          "excludes 0.5 %s -> %s" % (n, i["auc"][0], i["q"], o["auc"][0], 1.96 * o["auc"][2], same, sig_is, oos_ci,
                                     "STABLE" if same and sig_is and oos_ci else "not stable"))
    # multivariate check: logistic regression fit on IS only (standardised with IS statistics), scored on OOS
    try:
        import numpy as np
        cols = names
        tr = [r for r in rows if r["day"] < split and r["cohort"] in "AB" and r["f"]
              and all(r["f"][c] is not None for c in cols)]
        te = [r for r in rows if r["day"] >= split and r["cohort"] in "AB" and r["f"]
              and all(r["f"][c] is not None for c in cols)]
        Xtr = np.array([[r["f"][c] for c in cols] for r in tr])
        mu, sdv = Xtr.mean(0), Xtr.std(0)
        sdv[sdv == 0] = 1
        w, b0 = _logit_fit((Xtr - mu) / sdv, [1 if r["cohort"] == "A" else 0 for r in tr])
        for nm, ds in (("IS (fit)", tr), ("OOS", te)):
            X = (np.array([[r["f"][c] for c in cols] for r in ds]) - mu) / sdv
            s = X @ w + b0
            a = [float(v) for v, r in zip(s, ds) if r["cohort"] == "A"]
            b = [float(v) for v, r in zip(s, ds) if r["cohort"] == "B"]
            auc, p, se = _auc(a, b)
            P("\nALL FEATURES TOGETHER (logistic regression, fit on IS only, no threshold): %s AUC %.3f [%.3f, %.3f], "
              "n %d" % (nm, auc, auc - 1.96 * se, auc + 1.96 * se, len(ds)))
        P("  IS weights (standardised; + = more likely A): " + ", ".join(
            "%s %+.2f" % (c, wi) for c, wi in sorted(zip(cols, w), key=lambda x: -abs(x[1]))))
    except Exception as e:      # pragma: no cover
        P("\n(multivariate check skipped: %s)" % e)
    return "\n".join(L)


def main(argv=None):
    import argparse
    import json
    from multiprocessing import Pool
    import research_features as F
    import research_tf as TF
    ap = argparse.ArgumentParser(prog="research_scanner_v4.py sweepq")
    ap.add_argument("market", choices=list(F.MARKETS))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    tm = {}
    try:
        import paper as P
        tm = V4.tm_settings(P.load_config()["accounts"].get({"nse": "INDIA", "us": "US", "crypto": "CRYPTO"}[a.market], {}))
    except Exception:
        pass
    data = F.load(a.market)
    jobs = [(a.market, s, rows, tm) for s, rows in data.items()]
    rows, leaks = [], []
    with Pool(a.workers, maxtasksperchild=4) as pool:
        for sym, out, leak in pool.imap_unordered(chart, jobs):
            rows.extend(out)
            if leak:
                leaks.append(leak)
    print(report(a.market, rows, TF.SPLIT[a.market]))
    ok = sum(1 for x in leaks if x["identical"])
    print("\nLOOK-AHEAD CHECK: %d of %d prefix re-runs (one setup per symbol, the chart cut right after the sweep "
          "candle) published the same setup with identical features.%s" % (
              ok, len(leaks), "" if ok == len(leaks) else " MISMATCHES: %s" % [x for x in leaks if not x["identical"]]))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rows, fh)
    return 0


# ----------------------------------------------------------------- cost audit (reads research_entry_v4 --json output)
def cost_audit(paths):
    import json
    import paper as P
    import research_tf as TF
    cfg = P.DEFAULT_CONFIG
    acc = cfg["accounts"]["INDIA"]
    ch = cfg["india_charges"]["equity_intraday"]
    out = ["COST MODEL AUDIT (no assumption changed)", "",
           "Sources in the code:",
           "  research_tf.COST_PCT = %s (round trip, %% of the entry price), used by `research_scanner_v4.py sweep` "
           "and `entry`; cost in R = COST_PCT/100 x |entry fill| / (entry fill - stop)" % TF.COST_PCT,
           "  research_scanner_v4.py nse-sv4 (main backtest) uses paper.charges on the INDIA account sizing; us-sv4 "
           "uses (entry + exit) x (US fee_pct %s%% + 0.02%%) per side; crypto (entry + exit) x fee_pct %s%%" % (
               cfg["accounts"]["US"].get("fee_pct", 0), cfg["accounts"]["CRYPTO"]["fee_pct"]),
           "  paper.charges (NSE equity intraday, per order): brokerage min(Rs %s, %s%% of value); STT %s%% on sells; "
           "exchange %s%%; SEBI 0.0001%%; stamp %s%% on buys; GST %s%% on (brokerage + exchange + SEBI)" % (
               ch["brokerage_flat"], ch["brokerage_pct"], ch["stt_sell_pct"], ch["exchange_pct"], ch["stamp_buy_pct"],
               ch["gst_pct"]),
           "  paper fills: slippage_pct per account (default 0 everywhere); no separate spread model (US F&O only, "
           "inside its fee_pct)", ""]
    out.append("NSE round trip from paper.charges (buy + sell at the same price), as % of the order value:")
    for v in (10000, 25000, 50000, 100000, 250000):
        rt = P.charges(cfg, "NSE", "X", "buy", v) + P.charges(cfg, "NSE", "X", "sell", v)
        out.append("  Rs %8d: Rs %7.2f = %.4f%%" % (v, rt, 100 * rt / v))
    for path in paths:
        rows = json.load(open(path))
        market = os.path.basename(path).replace("entry_", "").replace(".json", "")
        out.append("")
        out.append("%s (%s): per entry model, the cost in R as the backtest computed it, recomputed, and the "
                   "alternatives" % (market.upper(), path))
        for name in ("E1 control", "E2 strong", "E3 retest"):
            tr = [(r["sym"], r[name]["trade"]) for r in rows if r[name]["trade"]]
            if not tr:
                continue
            got = [t["cost_r"] for _, t in tr]
            rec = [TF.COST_PCT[market] / 100 * abs(t["entry"]) / t["risk"] for _, t in tr]
            mism = sum(1 for g, r_ in zip(got, rec) if abs(g - r_) > 1e-12)
            risk_pct = [100 * t["risk"] / abs(t["entry"]) for _, t in tr]
            line = ("  %-10s n %5d | avg cost %.3fR (median %.3fR) | recomputed mismatches %d | stop distance: mean "
                    "%.3f%% median %.3f%% of the entry" % (name, len(tr), sum(got) / len(got), _q(got, .5), mism,
                                                           sum(risk_pct) / len(risk_pct), _q(risk_pct, .5)))
            out.append(line)
            if market == "nse":
                alt = []
                for sym, t in tr:
                    e, x, risk = abs(t["entry"]), abs(t["exit"]), t["risk"]
                    qty = int(min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / e))
                    if qty < 1:
                        continue
                    sd_ = ("buy", "sell") if t["entry"] > 0 else ("sell", "buy")
                    c = P.charges(cfg, "NSE", sym, sd_[0], qty * e) + P.charges(cfg, "NSE", sym, sd_[1], qty * x)
                    alt.append(c / (qty * risk))
                out.append("             paper.charges on the INDIA sizing (max loss Rs %d, position <= %d%% of Rs %d): "
                           "avg %.3fR median %.3fR (n %d)" % (acc["max_loss_per_trade"], acc["max_position_pct"],
                                                              acc["capital"], sum(alt) / max(1, len(alt)), _q(alt, .5),
                                                              len(alt)))
            if market == "us":
                fee = float(cfg["accounts"]["US"].get("fee_pct", 0)) / 100 + 0.0002
                alt = [(abs(t["entry"]) + abs(t["exit"])) * fee / t["risk"] for _, t in tr]
                out.append("             us-sv4 formula ((entry + exit) x 0.02%% per side): avg %.3fR median %.3fR" % (
                    sum(alt) / len(alt), _q(alt, .5)))
    return "\n".join(out)


if __name__ == "__main__":
    if sys.argv[1:2] == ["costaudit"]:
        print(cost_audit(sys.argv[2:]))
        sys.exit(0)
    sys.exit(main())
