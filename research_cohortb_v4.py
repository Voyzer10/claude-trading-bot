#!/usr/bin/env python3
"""Cohort B profitability (21 Nov 2026), research only: among the internal-sweep setups that actually produce a
CLOSED E1 trade (the scanner's own confirmation; research_entry_v4), do sweep-time features predict the trade's NET R
after the normalized costs (research_costs)? No trading behaviour changes; no filter or threshold is adopted.

  dataset   every closed E1 trade: features from research_sweep_quality_v4.features() (candles up to and including the
            sweep candle only), gross R, cost R (research_costs; NSE trades the INDIA sizing cannot size have no cost
            and are left out of net figures), net R. --csv writes it per trade.
  analysis  per market, IS / OOS separately (research_tf.SPLIT, unchanged):
            - overall gross / cost / net R, median, win rate, PF, 95% CI
            - per feature: missing values; Spearman rho with net R (95% CI, p), BH over the features (IS)
            - bins FIXED ON IS (quartiles of the IS values; binary features: 0 / 1), the same edges applied to OOS:
              n, mean net R with 95% CI, median, win rate per bin; top - bottom bin difference with CI and Cohen's d
            - feature-feature Spearman correlations (IS) so correlated features are not read as separate findings
            - one exploratory multivariate check: ridge regression on IS (standardised with IS statistics), then the
              OOS Spearman between its prediction and net R, and OOS net R by IS-fixed prediction terciles
  validity  prefix re-runs (the chart cut right after the sweep candle) must give identical features, for up to
            three trades per symbol.

    python research_scanner_v4.py cohortb nse|us [--csv trades.csv]"""
import bisect
import math
import os
import sys

import research_costs as RC
import scanner_v4 as V4

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FEATS = ["is_local", "ref_prot_atr", "close_prot_atr", "leg_atr", "bars_bos_sweep", "body_atr", "range_atr",
         "upper_wick", "lower_wick", "close_loc", "pen_atr", "is_short"]
BINARY = {"is_local", "is_short"}
KW = dict(sweep_rule="internal", sweep_max_bars=12, sweep_pen_atr=0.25, entry_max_bars=12)


def chart(args):
    import research_entry_v4 as E
    import research_features as F
    import research_sweep_quality_v4 as SQ
    market, sym, rows, tm, n_check = args
    m = F.MARKETS[market]
    day_of = (lambda t: m["local"](t).date())
    sweeps = []
    V4.sequence(rows, day_of, intraday=m["intraday"], max_hold=None, _sweeps=sweeps, **dict(tm, **KW))
    out, checks = [], []
    for sd, st, j0 in sweeps:
        short = sd.b is not rows
        t = E.setup_trades(sd, st, j0, m["intraday"])["E1 control"]["trade"]
        if not t:
            continue                                   # cohort B with a CLOSED E1 trade only
        f = SQ.features(sd, st, j0, short)
        if f is None:
            continue
        side = "short" if short else "long"
        c = RC.HARNESS[market](sym, side, abs(t["entry"]), abs(t["exit"]), abs(t["stop"]))
        cost = None if c is None else c["total_r"]
        out.append({"sym": sym, "side": side, "bos": st["bos"], "sweep": j0, "decide": t["decide"],
                    "day": day_of(rows[t["decide"]][0]).isoformat(), "sweep_time": rows[j0][0].isoformat(),
                    "gross": t["r"], "cost": cost, "net": None if cost is None else t["r"] - cost,
                    "exit_reason": t["reason"], "f": {k: f[k] for k in FEATS}})
        if len(checks) < n_check:
            # look-ahead check: the chart cut right after the sweep candle gives the same setup and features
            rows2, sw2 = rows[:j0 + 1], []
            V4.sequence(rows2, day_of, intraday=m["intraday"], max_hold=None, _sweeps=sw2, **dict(tm, **KW))
            same = False
            for sd2, st2, j2 in sw2:
                if j2 == j0 and st2["bos"] == st["bos"] and (sd2.b is not rows2) == short:
                    f2 = SQ.features(sd2, st2, j2, short)
                    same = bool(f2) and all((f[k] is None and f2[k] is None) or (
                        f[k] is not None and f2[k] is not None and abs(f[k] - f2[k]) < 1e-12) for k in f)
                    break
            checks.append(same)
    return sym, out, checks


# ----------------------------------------------------------------- statistics
def mean_ci(xs):
    n = len(xs)
    if not n:
        return None
    mu = sum(xs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1)) if n > 1 else float("nan")
    srt = sorted(xs)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    pos, neg = sum(x for x in xs if x > 0), -sum(x for x in xs if x < 0)
    return {"n": n, "mean": mu, "ci": 1.96 * sd / math.sqrt(n) if n > 1 else float("nan"), "median": med,
            "win": sum(1 for x in xs if x > 0) / n, "pf": pos / neg if neg else float("inf"), "sd": sd}


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(xs, ys):
    """rho, 95% CI (Fisher z), two-sided p (normal approximation)."""
    n = len(xs)
    if n < 4:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if not sx or not sy:
        return None
    rho = max(-0.999999, min(0.999999, sxy / (sx * sy)))
    z, se = math.atanh(rho), 1 / math.sqrt(n - 3)
    p = math.erfc(abs(z / se) / math.sqrt(2))
    return rho, math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se), p


def bh(ps):
    idx = sorted((p, i) for i, p in enumerate(ps) if p is not None)
    q, m, prev = [None] * len(ps), len(idx), 1.0
    for rank in range(m, 0, -1):
        p, i = idx[rank - 1]
        prev = min(prev, p * m / rank)
        q[i] = prev
    return q


def is_edges(vals, binary=False):
    """Bin edges fixed on the IS values: binary -> [0.5]; else the IS quartiles (25 / 50 / 75%)."""
    if binary:
        return [0.5]
    v = sorted(vals)
    if not v:
        return []
    q = [v[int((len(v) - 1) * p)] for p in (0.25, 0.5, 0.75)]
    return sorted(set(q))


def bin_of(edges, x):
    """bins (-inf, e0], (e0, e1], ..., (e_last, inf): a value equal to an edge falls in the lower bin (so a feature
    with many IS values at one number, e.g. 0, keeps them together in bin 0)."""
    return bisect.bisect_left(edges, x)


def _fmt(s):
    if not s:
        return "n 0"
    return "n %4d mean %+.3f ±%.3f med %+.3f win %4.1f%% PF %.2f" % (s["n"], s["mean"], s["ci"], s["median"],
                                                                     100 * s["win"], s["pf"])


def report(market, rows, split, n_checks, n_same):
    L = []
    P = L.append
    IS = [r for r in rows if r["day"] < split]
    OOS = [r for r in rows if r["day"] >= split]
    P("%s: %d closed E1 trades (cohort B with a trade). IS before %s: %d, OOS: %d. Costs: research_costs. "
      "Look-ahead: %d of %d prefix re-runs gave identical features." % (
          market, len(rows), split, len(IS), len(OOS), n_same, n_checks))
    nocost = sum(1 for r in rows if r["cost"] is None)
    P("Trades without a cost (NSE: not sizeable by the INDIA account; left out of net figures): %d" % nocost)
    P("\nOVERALL")
    for nm, part in (("IS", IS), ("OOS", OOS)):
        net = [r["net"] for r in part if r["net"] is not None]
        P("  %-3s gross %s" % (nm, _fmt(mean_ci([r["gross"] for r in part]))))
        P("  %-3s cost  %s" % (nm, _fmt(mean_ci([r["cost"] for r in part if r["cost"] is not None]))))
        P("  %-3s net   %s" % (nm, _fmt(mean_ci(net))))
    # per feature
    ps, res = [], {}
    for k in FEATS:
        a = [(r["f"][k], r["net"]) for r in IS if r["net"] is not None and r["f"][k] is not None]
        b = [(r["f"][k], r["net"]) for r in OOS if r["net"] is not None and r["f"][k] is not None]
        res[k] = {"is": spearman(*zip(*a)) if len(a) > 3 else None, "oos": spearman(*zip(*b)) if len(b) > 3 else None,
                  "miss_is": sum(1 for r in IS if r["f"][k] is None), "miss_oos": sum(1 for r in OOS if r["f"][k] is None)}
        ps.append(res[k]["is"][3] if res[k]["is"] else None)
    qs = bh(ps)
    P("\nPER FEATURE: Spearman rho with NET R (95%% CI, p); q = Benjamini-Hochberg over the %d features (IS). "
      "Robust = IS q < 0.05 AND OOS rho the same sign with its CI excluding 0." % len(FEATS))
    robust = []
    for k, q in zip(FEATS, qs):
        i, o = res[k]["is"], res[k]["oos"]
        ok = bool(i and o and q is not None and q < 0.05 and i[0] * o[0] > 0 and (o[1] > 0 or o[2] < 0))
        if ok:
            robust.append(k)
        P("  %-15s IS rho %s q %s | OOS rho %s | missing IS %d OOS %d -> %s" % (
            k, "%+.3f [%+.3f, %+.3f] p %.2g" % i if i else "n/a", "%.2g" % q if q is not None else "n/a",
            "%+.3f [%+.3f, %+.3f] p %.2g" % o if o else "n/a", res[k]["miss_is"], res[k]["miss_oos"],
            "ROBUST" if ok else "not robust"))
    # bins fixed on IS
    P("\nBINS FIXED ON IS (quartile edges of the IS values; binary 0 / 1), the SAME edges on OOS. Net R per bin:")
    for k in FEATS:
        vals = [r["f"][k] for r in IS if r["f"][k] is not None]
        edges = is_edges(vals, k in BINARY)
        P("  %s  edges (IS) %s" % (k, ["%.3g" % e for e in edges]))
        for nm, part in (("IS", IS), ("OOS", OOS)):
            cells = []
            groups = {}
            for r in part:
                if r["f"][k] is None or r["net"] is None:
                    continue
                groups.setdefault(bin_of(edges, r["f"][k]), []).append(r["net"])
            for kb in range(len(edges) + 1):
                cells.append("b%d %s" % (kb, _fmt(mean_ci(groups.get(kb, [])))))
            P("    %-3s %s" % (nm, " | ".join(cells)))
            lo, hi = groups.get(0, []), groups.get(len(edges), [])
            if len(lo) > 1 and len(hi) > 1:
                a, b = mean_ci(hi), mean_ci(lo)
                se = math.sqrt(a["sd"] ** 2 / a["n"] + b["sd"] ** 2 / b["n"])
                sp = math.sqrt(((a["n"] - 1) * a["sd"] ** 2 + (b["n"] - 1) * b["sd"] ** 2) / (a["n"] + b["n"] - 2))
                P("        %-3s top - bottom bin: %+.3fR ±%.3f, Cohen's d %+.2f" % (
                    nm, a["mean"] - b["mean"], 1.96 * se, (a["mean"] - b["mean"]) / sp if sp else 0))
    # correlated features
    P("\nFEATURE-FEATURE SPEARMAN (IS; |rho| >= 0.5 listed): features in one group are one finding, not several")
    for i, a in enumerate(FEATS):
        for b in FEATS[i + 1:]:
            xy = [(r["f"][a], r["f"][b]) for r in IS if r["f"][a] is not None and r["f"][b] is not None]
            s = spearman(*zip(*xy)) if len(xy) > 3 else None
            if s and abs(s[0]) >= 0.5:
                P("  %-15s ~ %-15s rho %+.2f" % (a, b, s[0]))
    # multivariate (exploratory)
    try:
        import numpy as np
        cols = FEATS
        tr = [r for r in IS if r["net"] is not None and all(r["f"][c] is not None for c in cols)]
        te = [r for r in OOS if r["net"] is not None and all(r["f"][c] is not None for c in cols)]
        X = np.array([[r["f"][c] for c in cols] for r in tr])
        mu, sdv = X.mean(0), X.std(0)
        sdv[sdv == 0] = 1
        Z = (X - mu) / sdv
        y = np.array([r["net"] for r in tr])
        lam = 1.0
        w = np.linalg.solve(Z.T @ Z + lam * len(y) * np.eye(len(cols)), Z.T @ (y - y.mean()))
        pis = Z @ w + y.mean()
        Zt = (np.array([[r["f"][c] for c in cols] for r in te]) - mu) / sdv
        pte = Zt @ w + y.mean()
        s_is = spearman(list(pis), list(y))
        s_oos = spearman(list(pte), [r["net"] for r in te])
        P("\nMULTIVARIATE (exploratory; ridge, lambda 1 x n, fit on IS only, no threshold adopted):")
        P("  prediction vs net R, Spearman: IS (fit) %+.3f [%+.3f, %+.3f] | OOS %+.3f [%+.3f, %+.3f] p %.2g" % (
            s_is[:3] + s_oos[:3] + (s_oos[3],)) if s_is and s_oos else "  n/a")
        t1, t2 = np.quantile(pis, [1 / 3, 2 / 3])
        for nm, ds, pr in (("IS", tr, pis), ("OOS", te, pte)):
            cells = []
            for kb in range(3):
                g = [r["net"] for r, v in zip(ds, pr) if bisect.bisect_right([t1, t2], v) == kb]
                cells.append("T%d %s" % (kb + 1, _fmt(mean_ci(g))))
            P("  %-3s by IS-fixed prediction tercile: %s" % (nm, " | ".join(cells)))
        P("  IS weights (standardised): " + ", ".join("%s %+.3f" % (c, wi) for c, wi in
                                                     sorted(zip(cols, w), key=lambda x: -abs(x[1]))))
    except Exception as e:      # pragma: no cover
        P("\n(multivariate check skipped: %s)" % e)
    P("\nROBUST FEATURES (IS BH q < 0.05 and the same-sign OOS rho with a CI excluding 0): %s" % (robust or "none"))
    return "\n".join(L), robust


def main(argv=None):
    import argparse
    import csv
    from multiprocessing import Pool
    import research_features as F
    import research_tf as TF
    ap = argparse.ArgumentParser(prog="research_scanner_v4.py cohortb")
    ap.add_argument("market", choices=list(F.MARKETS))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--checks", type=int, default=3, help="prefix look-ahead re-runs per symbol")
    ap.add_argument("--csv")
    a = ap.parse_args(argv)
    tm = {}
    try:
        import paper as P
        tm = V4.tm_settings(P.load_config()["accounts"].get({"nse": "INDIA", "us": "US", "crypto": "CRYPTO"}[a.market], {}))
    except Exception:
        pass
    data = F.load(a.market)
    rows, checks = [], []
    with Pool(a.workers, maxtasksperchild=4) as pool:
        for sym, out, ch in pool.imap_unordered(chart, [(a.market, s, r, tm, a.checks) for s, r in data.items()]):
            rows.extend(out)
            checks.extend(ch)
    rows.sort(key=lambda r: (r["day"], r["sym"], r["decide"]))
    text, _ = report(a.market, rows, TF.SPLIT[a.market], len(checks), sum(1 for c in checks if c))
    print(text)
    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["sym", "side", "bos", "sweep", "decide", "day", "sweep_time", "period", "gross_r", "cost_r",
                        "net_r", "exit_reason"] + FEATS)
            for r in rows:
                w.writerow([r["sym"], r["side"], r["bos"], r["sweep"], r["decide"], r["day"], r["sweep_time"],
                            "IS" if r["day"] < TF.SPLIT[a.market] else "OOS", r["gross"], r["cost"], r["net"],
                            r["exit_reason"]] + [r["f"][k] for k in FEATS])
    return 0


if __name__ == "__main__":
    sys.exit(main())
