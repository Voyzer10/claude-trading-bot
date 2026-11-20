#!/usr/bin/env python3
"""Sweep v1 comparative backtest (owner's task, 20 Nov 2026). Research only.

Runs the live Scanner v4 (legs BOS, everything else as on the research branch) with the old "close" sweep and with
sweep v1 at four settings, on the long broker history (research_data.py), per market:

  baseline  sweep_rule "close"
  A         v1, sweep_max_bars 6,  sweep_pen_atr 0.10
  B         v1, sweep_max_bars 6,  sweep_pen_atr 0.25
  C         v1, sweep_max_bars 12, sweep_pen_atr 0.10
  D         v1, sweep_max_bars 12, sweep_pen_atr 0.25      (entry_max_bars 12 throughout)

and prints the funnel (BOS, sweeps, expired, invalidated, too deep, confirmations, trades), the results (wins,
losses, breakeven, win rate, gross profit / loss R, net R, profit factor, max drawdown R, avg R) BEFORE costs, in- and
out-of-sample, an approximate R after costs, and the filter quality against the baseline (what the rejected baseline
trades did: target / stop / other; the new trades the baseline did not take).

    python research_sweep_v1.py nse|us|crypto [--workers 2]
"""
import argparse
import json
import sys
from multiprocessing import Pool

import research_features as F
import research_tf as TF
import scanner_v4 as V4

CONFIGS = [("baseline", {"sweep_rule": "close"}),
           ("A 6/0.10", {"sweep_rule": "v1", "sweep_max_bars": 6, "sweep_pen_atr": 0.10}),
           ("B 6/0.25", {"sweep_rule": "v1", "sweep_max_bars": 6, "sweep_pen_atr": 0.25}),
           ("C 12/0.10", {"sweep_rule": "v1", "sweep_max_bars": 12, "sweep_pen_atr": 0.10}),
           ("D 12/0.25", {"sweep_rule": "v1", "sweep_max_bars": 12, "sweep_pen_atr": 0.25})]
BE = 0.05            # |R| under this = breakeven


def one(args):
    market, sym, rows, tm = args
    m = F.MARKETS[market]
    day_of = (lambda t: m["local"](t).date())
    out = {}
    for name, kw in CONFIGS:
        ended, stats = [], {}
        seq = V4.sequence(rows, day_of, intraday=m["intraday"], max_hold=None, _ended=ended, _stats=stats,
                          **dict(tm, entry_max_bars=12, **kw))
        trades = []
        for t in seq:
            if t["kind"] != "primary" or t.get("exit") is None or t.get("exit_reason") == "open":
                continue
            sg = 1 if t["side"] == "long" else -1
            risk = (t["entry"] - t["stop"]) * sg
            if risk <= 0:
                continue
            r = (t["exit"] - t["entry"]) * sg / risk
            trades.append({"sym": sym, "bos": t["bos"], "side": t["side"], "i": t["i"], "t": rows[t["i"]][0].timestamp(),
                           "day": day_of(rows[t["i"]][0]).isoformat(), "r": r, "exit": t["exit_reason"],
                           "cost": TF.COST_PCT[market] / 100 * t["entry"] / risk})
        why = {}
        for st, j, w in ended:
            k = ("invalidated" if "protected swing" in w else "too deep" if w.startswith("wick too deep") else
                 "expired: no sweep" if w.startswith("no sweep") else "expired: no entry" if w.startswith("no entry")
                 else "overnight" if w == "overnight" else w)
            why[k] = why.get(k, 0) + 1
        out[name] = {"trades": trades, "stats": stats, "why": why}
    return sym, out


def summary(trades):
    n = len(trades)
    if not n:
        return None
    w = [t for t in trades if t["r"] >= BE]
    l_ = [t for t in trades if t["r"] <= -BE]
    gp = sum(t["r"] for t in w)
    gl = -sum(t["r"] for t in l_)
    net = sum(t["r"] for t in trades)
    eq = peak = dd = 0.0
    for t in sorted(trades, key=lambda x: x["t"]):
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"n": n, "w": len(w), "l": len(l_), "be": n - len(w) - len(l_), "wr": 100.0 * len(w) / n, "gp": gp, "gl": gl,
            "net": net, "pf": gp / gl if gl else float("inf"), "dd": dd, "avg": net / n,
            "net_c": sum(t["r"] - t["cost"] for t in trades) / n,
            "tp": 100.0 * sum(1 for t in trades if t["exit"] == "target") / n}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("market", choices=list(F.MARKETS))
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--json")
    a = p.parse_args(argv)
    tm = {}
    try:
        import paper as P
        tm = V4.tm_settings(P.load_config()["accounts"].get({"nse": "INDIA", "us": "US", "crypto": "CRYPTO"}[a.market], {}))
    except Exception:
        pass
    data = F.load(a.market)
    jobs = [(a.market, s, rows, tm) for s, rows in data.items()]
    with Pool(a.workers) as pool:
        res = dict(pool.imap_unordered(one, jobs))
    split = TF.SPLIT[a.market]
    print("%s: %d symbols; out-of-sample from %s; R BEFORE costs unless marked" % (a.market, len(res), split))
    agg = {}
    for name, _kw in CONFIGS:
        trades = [t for r in res.values() for t in r[name]["trades"]]
        stats, why = {}, {}
        for r in res.values():
            for k, v in r[name]["stats"].items():
                stats[k] = stats.get(k, 0) + v
            for k, v in r[name]["why"].items():
                why[k] = why.get(k, 0) + v
        agg[name] = {"trades": trades, "stats": stats, "why": why}

    print("\nFUNNEL (whole period)")
    print("  %-10s %7s %7s %8s %8s %8s %8s %8s %8s %7s" % ("config", "BOS", "sweeps", "exp:sw", "exp:ent", "invalid",
                                                            "too deep", "overnt", "confirm", "trades"))
    for name, _ in CONFIGS:
        s, w = agg[name]["stats"], agg[name]["why"]
        print("  %-10s %7d %7s %8d %8d %8d %8d %8d %8d %7d" % (
            name, s.get("bos", 0), s.get("sweeps", "-") if name != "baseline" else "-", w.get("expired: no sweep", 0),
            w.get("expired: no entry", 0), w.get("invalidated", 0), w.get("too deep", 0), w.get("overnight", 0),
            s.get("confirmations", 0), len(agg[name]["trades"])))
    for part, f in (("OUT-OF-SAMPLE", lambda t: t["day"] >= split), ("IN-SAMPLE", lambda t: t["day"] < split)):
        print("\n%s results (R before costs)" % part)
        print("  %-10s %6s %5s %5s %5s %6s %6s %8s %8s %8s %6s %7s %8s %8s" % (
            "config", "trades", "win", "loss", "BE", "win%", "TP%", "gross+", "gross-", "net R", "PF", "maxDD", "avg R",
            "after c."))
        for name, _ in CONFIGS:
            s = summary([t for t in agg[name]["trades"] if f(t)])
            if not s:
                print("  %-10s no trades" % name)
                continue
            print("  %-10s %6d %5d %5d %5d %5.1f%% %5.1f%% %+8.1f %8.1f %+8.1f %6.2f %7.1f %+7.3fR %+7.3fR" % (
                name, s["n"], s["w"], s["l"], s["be"], s["wr"], s["tp"], s["gp"], s["gl"], s["net"], s["pf"], s["dd"],
                s["avg"], s["net_c"]))
    print("\nFILTER QUALITY vs baseline (out-of-sample, same symbol + BOS candle + side)")
    base = {(t["sym"], t["bos"], t["side"]): t for t in agg["baseline"]["trades"] if t["day"] >= split}
    for name, _ in CONFIGS[1:]:
        keys = {(t["sym"], t["bos"], t["side"]) for t in agg[name]["trades"] if t["day"] >= split}
        rej = [t for k, t in base.items() if k not in keys]
        new = [t for t in agg[name]["trades"] if t["day"] >= split and (t["sym"], t["bos"], t["side"]) not in base]
        kept = [t for k, t in base.items() if k in keys]
        print("  %-10s baseline trades rejected %d of %d: target %d, stop %d, other %d, their avg %+.3fR | kept avg "
              "%+.3fR | new trades not in baseline %d, avg %+.3fR" % (
                  name, len(rej), len(base), sum(1 for t in rej if t["exit"] == "target"),
                  sum(1 for t in rej if t["exit"] in ("stop", "stop (gapped past it)")),
                  sum(1 for t in rej if t["exit"] not in ("target", "stop", "stop (gapped past it)")),
                  sum(t["r"] for t in rej) / max(1, len(rej)), sum(t["r"] for t in kept) / max(1, len(kept)), len(new),
                  sum(t["r"] for t in new) / max(1, len(new))))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({k: {"stats": v["stats"], "why": v["why"]} for k, v in agg.items()}, fh)


if __name__ == "__main__":
    sys.exit(main())
