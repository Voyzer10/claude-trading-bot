#!/usr/bin/env python3
"""E1 trade lifecycle and execution economics (21 Nov 2026), research only, observational: why is the E1 internal-sweep
entry net-negative? No trading behaviour changes; no parameter is chosen.

Data: the closed E1 trades (research_entry_v4 on the published internal sweeps), NSE / US, costs from research_costs,
the existing IS / OOS split (research_tf.SPLIT). Per trade, from the recorded trade (decide / fill / exit candle, entry,
initial stop and target, exit price and reason) and the ACTUAL candles from the fill to the exit candle:

  - the exit is re-simulated with scanner_v4._exit_step (the Trade Manager) from the fill candle: it must give the same
    exit candle, price and reason as the record, and the stop path (breakeven / trailing moves) is read from it
  - MFE / MAE in R from those candles. The exit candle counts only as far as its order is known (the engine checks the
    stop first, then the target): a STOP-type exit adds its exit price as the adverse extreme and no favourable
    extreme; a TARGET exit adds the target as the favourable extreme and no adverse extreme; a close-based exit (day
    end) adds the whole candle. The TM's own running MFE (tr["mfe"]) is checked against the same candles.
  - stop distance (ATR, %), planned reward:risk, bars held, minutes held, approach flags at fixed, descriptive levels
    (+0.5 / +1 / +1.5R, -0.5 / -1R; "approached the target" = MFE >= half the planned R; "approached the stop" =
    MAE >= 0.75R). These levels describe outcomes; none is a trading parameter.
  - gross R, cost R (research_costs), net R; each reconciled: gross = (exit - entry) / risk, net = gross - cost.

    python research_scanner_v4.py lifecycle nse|us [--csv trades.csv]"""
import bisect
import math
import os
import sys

import research_costs as RC
import scanner_v4 as V4

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

KW = dict(sweep_rule="internal", sweep_max_bars=12, sweep_pen_atr=0.25, entry_max_bars=12)
STOP_TYPES = ("stop", "breakeven stop", "trailing stop", "profit lock stop", "stop (gapped past it)")
LEVELS_UP = (0.5, 1.0, 1.5)
LEVELS_DN = (0.5, 1.0)


def excursions(bars, fill, exit_i, entry, risk, reason, exit_px, target):
    """(MFE R, MAE R) of one trade in src terms (long; shorts are mirrored bars), from the fill candle to the exit
    candle, the exit candle counted only as far as its intrabar order is known (see the module docstring). MAE is
    returned as a positive number of R against the trade."""
    hi, lo = [], []
    for k in range(fill, exit_i):
        hi.append(bars[k][2])
        lo.append(bars[k][3])
    if reason in STOP_TYPES:
        lo.append(exit_px)
    elif reason == "target":
        hi.append(target)
    else:                                   # close-based exits: the whole candle happened while open
        hi.append(bars[exit_i][2])
        lo.append(bars[exit_i][3])
    mfe = (max(hi) - entry) / risk if hi else 0.0
    mae = (entry - min(lo)) / risk if lo else 0.0
    return mfe, mae


def chart(args):
    import research_entry_v4 as E
    import research_features as F
    market, sym, rows, tm = args
    m = F.MARKETS[market]
    day_of = (lambda t: m["local"](t).date())
    sweeps = []
    V4.sequence(rows, day_of, intraday=m["intraday"], max_hold=None, _sweeps=sweeps, **dict(tm, **KW))
    out = []
    for sd, st, j0 in sweeps:
        t = E.setup_trades(sd, st, j0, m["intraday"])["E1 control"]["trade"]
        if not t:
            continue
        b, short = sd.b, sd.b is not rows
        sg = -1 if short else 1
        # the Trade Manager re-run from the fill candle: same exit, and the stop path
        tr = {"i": t["decide"], "entry": t["entry"], "stop": t["stop"], "cur_stop": t["stop"], "target": t["target"]}
        k, got, moves = t["fill"], None, []
        while k < len(b):
            before = tr["cur_stop"]
            got = V4._exit_step(b, k, tr, sd.p, sd.day, m["intraday"])
            if got:
                break
            if tr["cur_stop"] != before:
                moves.append((k, tr.get("stop_kind")))
            k += 1
        tm_ok = bool(got) and k == t["exit_i"] and abs(got[0] - t["exit"]) < 1e-9 and got[1] == t["reason"]
        risk = t["entry"] - t["stop"]
        mfe, mae = excursions(b, t["fill"], t["exit_i"], t["entry"], risk, t["reason"], t["exit"], t["target"])
        # the TM's running MFE uses the candles where neither the stop nor the target fired (floored at 0)
        tm_cands = [b[x][2] for x in range(t["fill"], t["exit_i"])] + (
            [b[t["exit_i"]][2]] if t["reason"] not in STOP_TYPES and t["reason"] != "target" else [])
        tm_mfe_mine = max(0.0, (max(tm_cands) - t["entry"]) / risk) if tm_cands else 0.0
        c = RC.HARNESS[market](sym, "short" if short else "long", abs(t["entry"]), abs(t["exit"]), abs(t["stop"]))
        cost = None if c is None else c["total_r"]
        gross = (t["exit"] - t["entry"]) / risk
        planned = (t["target"] - t["entry"]) / risk
        out.append({
            "sym": sym, "side": "short" if short else "long", "bos": st["bos"], "sweep": j0,
            "sweep_time": rows[j0][0].isoformat(), "entry_time": rows[t["fill"]][0].isoformat(),
            "exit_time": rows[t["exit_i"]][0].isoformat(), "day": day_of(rows[t["decide"]][0]).isoformat(),
            "entry": sg * t["entry"], "stop": sg * t["stop"], "target": sg * t["target"], "exit": sg * t["exit"],
            "stop_dist": risk, "stop_atr": risk / t["atr"], "stop_pct": 100 * risk / abs(t["entry"]),
            "target_dist": t["target"] - t["entry"], "planned_rr": planned, "exit_reason": t["reason"],
            "gross": gross, "gross_rec": t["r"], "cost": cost, "net": None if cost is None else gross - cost,
            "mfe": mfe, "mae": mae, "tm_mfe": tr.get("mfe", 0.0), "tm_mfe_mine": tm_mfe_mine,
            "bars": t["exit_i"] - t["fill"] + 1,
            "minutes": (rows[t["exit_i"]][0] - rows[t["fill"]][0]).total_seconds() / 60,
            "stop_moves": len(moves), "tm_ok": tm_ok,
            "approached_target": mfe >= 0.5 * planned, "approached_stop": mae >= 0.75})
    return sym, out


# ----------------------------------------------------------------- statistics
def stat(xs):
    n = len(xs)
    if not n:
        return None
    mu = sum(xs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1)) if n > 1 else float("nan")
    s = sorted(xs)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    return {"n": n, "mean": mu, "ci": 1.96 * sd / math.sqrt(n) if n > 1 else float("nan"), "median": med,
            "q1": s[int((n - 1) * .25)], "q3": s[int((n - 1) * .75)], "sum": sum(xs)}


def f(s, sums=False):
    if not s:
        return "n 0"
    return "n %4d mean %+.3f ±%.3f med %+.3f [Q1 %+.3f Q3 %+.3f]%s" % (
        s["n"], s["mean"], s["ci"], s["median"], s["q1"], s["q3"], " sum %+.1f" % s["sum"] if sums else "")


def spearman(xs, ys):
    from research_cohortb_v4 import spearman as sp
    return sp(xs, ys)


def report(market, rows, split):
    L = []
    P = L.append
    nc = [r for r in rows if r["net"] is not None]
    P("%s: %d closed E1 trades; IS before %s %d, OOS %d. Costs: research_costs. Trades with no cost (NSE, not "
      "sizeable): %d." % (market, len(rows), split, sum(1 for r in rows if r["day"] < split),
                          sum(1 for r in rows if r["day"] >= split), len(rows) - len(nc)))
    P("VALIDATION: Trade Manager re-run matches the recorded exit (candle, price, reason) for %d of %d; gross R "
      "recomputed = recorded for %d; TM running MFE = the candle-based MFE for %d; net = gross - cost for %d of %d." % (
          sum(1 for r in rows if r["tm_ok"]), len(rows), sum(1 for r in rows if abs(r["gross"] - r["gross_rec"]) < 1e-9),
          sum(1 for r in rows if abs(r["tm_mfe"] - r["tm_mfe_mine"]) < 1e-9),
          sum(1 for r in nc if abs(r["net"] - (r["gross"] - r["cost"])) < 1e-12), len(nc)))
    for part, sel in (("IS", lambda r: r["day"] < split), ("OOS", lambda r: r["day"] >= split)):
        rs = [r for r in rows if sel(r)]
        rn = [r for r in rs if r["net"] is not None]
        if not rs:
            continue
        P("\n" + "=" * 30 + " %s %s (n %d)" % (market.upper(), part, len(rs)))
        P("gross %s" % f(stat([r["gross"] for r in rs])))
        P("cost  %s" % f(stat([r["cost"] for r in rn])))
        P("net   %s" % f(stat([r["net"] for r in rn]), True))
        # A. exit attribution
        P("\nA. EXIT ATTRIBUTION (net R; share of trades; contribution to the total; share of all losing net R)")
        tot_loss = -sum(r["net"] for r in rn if r["net"] < 0)
        cats = {}
        for r in rn:
            cats.setdefault(r["exit_reason"], []).append(r)
        for cat, xs in sorted(cats.items(), key=lambda kv: sum(r["net"] for r in kv[1])):
            s = stat([r["net"] for r in xs])
            loss = -sum(r["net"] for r in xs if r["net"] < 0)
            P("  %-18s %5.1f%% of trades | net %s | gross mean %+.3f | cost mean %.3f | %.1f%% of all losing R" % (
                cat, 100 * len(xs) / len(rn), f(s, True), sum(r["gross"] for r in xs) / len(xs),
                sum(r["cost"] for r in xs) / len(xs), 100 * loss / tot_loss if tot_loss else 0))
        # B. MFE / MAE
        P("\nB. MFE / MAE (R, from the trade's own candles)")
        P("  MFE %s" % f(stat([r["mfe"] for r in rs])))
        P("  MAE %s" % f(stat([r["mae"] for r in rs])))
        up = "  reached before the exit: " + ", ".join(
            "+%.1fR %.1f%%" % (lv, 100 * sum(1 for r in rs if r["mfe"] >= lv) / len(rs)) for lv in LEVELS_UP)
        dn = ", ".join("-%.1fR %.1f%%" % (lv, 100 * sum(1 for r in rs if r["mae"] >= lv) / len(rs)) for lv in LEVELS_DN)
        P(up + " | " + dn)
        gb = [r["mfe"] - r["gross"] for r in rs if r["mfe"] > 0]
        P("  giveback (MFE - gross R, trades with MFE > 0): %s" % f(stat(gb)))
        for lv in (1.0,):
            sub = [r for r in rn if r["mfe"] >= lv]
            P("  trades that reached +%.1fR (n %d): exits %s; net %s" % (
                lv, len(sub), ", ".join("%s %d" % kv for kv in sorted(_count(r["exit_reason"] for r in sub).items(),
                                                                      key=lambda x: -x[1])), f(stat([r["net"] for r in sub]))))
        P("  approached the target (MFE >= half the planned R): %.1f%% | approached the stop (MAE >= 0.75R): %.1f%%" % (
            100 * sum(1 for r in rs if r["approached_target"]) / len(rs),
            100 * sum(1 for r in rs if r["approached_stop"]) / len(rs)))
        # C. stop / target economics
        P("\nC. STOP AND TARGET ECONOMICS")
        P("  initial stop distance: ATR %s" % f(stat([r["stop_atr"] for r in rs])))
        P("                         %%   %s" % f(stat([r["stop_pct"] for r in rs])))
        P("  planned reward:risk (R)    %s" % f(stat([r["planned_rr"] for r in rs])))
        tg = [r for r in rs if r["exit_reason"] == "target"]
        P("  realised gross R on target exits %s vs planned %s" % (
            f(stat([r["gross"] for r in tg])), f(stat([r["planned_rr"] for r in tg]))))
        P("  all trades: realised gross R / planned R, median %.3f" % stat(
            [r["gross"] / r["planned_rr"] for r in rs if r["planned_rr"] > 0])["median"])
        P("  cost vs stop distance (stop % quartiles fixed on IS):")
        P(_bins(rows, rn, split, "stop_pct"))
        # D. holding time
        P("\nD. HOLDING TIME (exploratory; bars-held quartiles fixed on IS; no timeout chosen)")
        P(_bins(rows, rn, split, "bars"))
        s = spearman([r["bars"] for r in rn], [r["net"] for r in rn])
        P("  Spearman bars held vs net R: %s" % ("%+.3f [%+.3f, %+.3f] p %.2g" % s if s else "n/a"))
    return "\n".join(L)


def _bins(rows, rn, split, key):
    is_vals = sorted(r[key] for r in rows if r["day"] < split)
    edges = sorted(set(is_vals[int((len(is_vals) - 1) * p)] for p in (.25, .5, .75))) if is_vals else []
    out = []
    groups = {}
    for r in rn:
        groups.setdefault(bisect.bisect_left(edges, r[key]), []).append(r)
    for kb in range(len(edges) + 1):
        g = groups.get(kb, [])
        lo = "<=%.3g" % edges[0] if kb == 0 else (">%.3g" % edges[-1] if kb == len(edges) else "%.3g-%.3g" % (
            edges[kb - 1], edges[kb]))
        out.append("    %-12s n %4d | cost %s | net %s" % (
            lo, len(g), "%.3f" % (sum(r["cost"] for r in g) / len(g)) if g else "-",
            f(stat([r["net"] for r in g]))))
    return "\n".join(out)


def _count(it):
    d = {}
    for x in it:
        d[x] = d.get(x, 0) + 1
    return d


CSV_COLS = ["sym", "side", "bos", "sweep", "sweep_time", "entry_time", "exit_time", "day", "period", "entry", "stop",
            "target", "exit", "stop_dist", "stop_atr", "stop_pct", "target_dist", "planned_rr", "exit_reason", "gross",
            "cost", "net", "mfe", "mae", "tm_mfe", "bars", "minutes", "stop_moves", "approached_target",
            "approached_stop", "tm_ok"]


def main(argv=None):
    import argparse
    import csv
    from multiprocessing import Pool
    import research_features as F
    import research_tf as TF
    ap = argparse.ArgumentParser(prog="research_scanner_v4.py lifecycle")
    ap.add_argument("market", choices=list(F.MARKETS))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--csv")
    a = ap.parse_args(argv)
    tm = {}
    try:
        import paper as P
        tm = V4.tm_settings(P.load_config()["accounts"].get({"nse": "INDIA", "us": "US", "crypto": "CRYPTO"}[a.market], {}))
    except Exception:
        pass
    data = F.load(a.market)
    rows = []
    with Pool(a.workers, maxtasksperchild=4) as pool:
        for sym, out in pool.imap_unordered(chart, [(a.market, s, r, tm) for s, r in data.items()]):
            rows.extend(out)
    rows.sort(key=lambda r: (r["entry_time"], r["sym"]))
    split = TF.SPLIT[a.market]
    print(report(a.market, rows, split))
    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(CSV_COLS)
            for r in rows:
                w.writerow([("IS" if r["day"] < split else "OOS") if c == "period" else r[c] for c in CSV_COLS])
    return 0


if __name__ == "__main__":
    sys.exit(main())
