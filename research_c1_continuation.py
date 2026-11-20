#!/usr/bin/env python3
"""Research only (21 Nov 2026): Candidate 1 (entry_rule="c1_continuation", fresh BOS -> pullback -> continuation BOS,
with the T9 CHoCH lifecycle) vs the unchanged baseline (scanner_v4 defaults: legs BOS, close sweep) vs no entry.

Same data, same engine (scanner_v4.sequence), same fills (next open), same Trade Manager defaults, same costs:
  NSE  paper.charges on the default INDIA account sizing (research_scanner_v4's NSE cost function)
  US   fee_pct (default 0) + 0.02% a side (research_scanner_v4's US cost function)
Crypto is excluded (history provenance UNKNOWN). No parameter is searched or tuned. Splits: in-sample before
2026-08-04, out-of-sample from it (the existing research split).

    python research_c1_continuation.py LONGDIR OUTDIR

LONGDIR: the long 5m history (<SYM>_5m.json). Writes OUTDIR/c1_results.pkl, c1_report.txt, c1_symbols.csv,
c1_dataset.csv (symbol, rows, first / last candle, sha256)."""
import bisect
import csv
import hashlib
import json
import os
import pickle
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import scanner_v4 as V4  # noqa: E402
import paper as P  # noqa: E402

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
SPLIT = "2026-08-04"
C1 = {"entry_rule": "c1_continuation", "choch_invalidate": True}
CFG = P.DEFAULT_CONFIG                    # not load_config(): no runtime files written
ACC = CFG["accounts"]["INDIA"]
US_FEE = float(CFG["accounts"]["US"].get("fee_pct", 0)) / 100 + 0.0002


def et_of(t):
    y = t.year
    mar = datetime(y, 3, 8, 7, tzinfo=UTC)
    mar += timedelta(days=(6 - mar.weekday()) % 7)
    nov = datetime(y, 11, 1, 6, tzinfo=UTC)
    nov += timedelta(days=(6 - nov.weekday()) % 7)
    return t + timedelta(hours=-4 if mar <= t < nov else -5)


MARKETS = {"NSE": {"local": lambda t: t.astimezone(IST), "open": (9, 15), "close": (15, 30)},
           "US": {"local": et_of, "open": (9, 30), "close": (16, 0)}}


def market_of(fname):
    return None if "-USD_" in fname else "NSE" if ".NS_" in fname else "US"


def load(path, market):
    m = MARKETS[market]
    d = json.load(open(path))
    rows = []
    for t, o, h, l, c, v in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]):
        if None in (o, h, l, c):
            continue
        ts = datetime.fromtimestamp(t, UTC)
        lt = m["local"](ts)
        if m["open"] <= (lt.hour, lt.minute) < m["close"]:
            rows.append((ts, o, h, l, c, v or 0))
    return rows


def resample(rows, minutes, market):
    """session-anchored bars + the time of each bar's last 5m candle (when it is complete)."""
    if minutes == 5:
        return rows, [r[0] for r in rows]
    m = MARKETS[market]
    oh = m["open"]
    out, ends, key, cur = [], [], None, None
    for t, o, h, l, c, v in rows:
        lt = m["local"](t)
        k = (lt.date(), ((lt.hour * 60 + lt.minute) - (oh[0] * 60 + oh[1])) // minutes)
        if k != key:
            if cur:
                out.append(tuple(cur))
            key, cur = k, [t, o, h, l, c, v]
            ends.append(t)
        else:
            cur[2], cur[3], cur[4], cur[5] = max(cur[2], h), min(cur[3], l), c, cur[5] + v
            ends[-1] = t
    if cur:
        out.append(tuple(cur))
    return out, ends


def cost_r(market, sym, t):
    risk = abs(t["entry"] - t["stop"])
    if risk <= 0:
        return None
    if market == "NSE":
        qty = int(min(ACC["max_loss_per_trade"] / risk, ACC["capital"] * ACC["max_position_pct"] / 100 / t["entry"]))
        if qty < 1:
            return None
        o, c = ("buy", "sell") if t["side"] == "long" else ("sell", "buy")
        s = sym.replace(".NS", "")
        return (P.charges(CFG, "NSE", s, o, qty * t["entry"]) + P.charges(CFG, "NSE", s, c, qty * t["exit"])) / (qty * risk)
    return (t["entry"] + t["exit"]) * US_FEE / risk


def r_of(t):
    sg = 1 if t["side"] == "long" else -1
    risk = (t["entry"] - t["stop"]) * sg
    return (t["exit"] - t["entry"]) * sg / risk if risk > 0 else 0.0


def regime_fn(rows, market):
    """60m legs trend at the last COMPLETED 60m bar: aligned / counter / undefined."""
    bars, ends = resample(rows, 60, market)
    info = {}
    V4.legs(bars, info)
    tr, cur = [None] * len(bars), None
    ch = info["choch"]
    init = info["init"]
    for j in range(len(bars)):
        if init and j == init[0]:
            cur = init[1]
        if j in ch:
            cur = ch[j]
        tr[j] = cur

    def f(t, side):
        k = bisect.bisect_right(ends, t) - 1
        if k < 0 or tr[k] is None:
            return "undefined"
        return "aligned" if (tr[k] == "up") == (side == "long") else "counter"
    return f


def run_one(job):
    market, sym, path = job
    rows = load(path, market)
    if len(rows) < 1000:
        return []
    reg = regime_fn(rows, market)
    day_of = (lambda t: t.astimezone(IST).date()) if market == "NSE" else (lambda t: et_of(t).date())
    out = []
    for tf in (5, 15):
        bars, ends = resample(rows, tf, market)
        if len(bars) < 300:
            continue
        cx = V4.contexts(bars, day_of, False, k=int(V4.DEFAULTS["swing_k"]))
        day = cx["day"]
        res = {"market": market, "sym": sym, "tf": tf, "n": len(bars), "first": bars[0][0].isoformat(),
               "last": bars[-1][0].isoformat()}
        for arm, kw in (("baseline", {}), ("c1", C1)):
            ended, stats = [], {}
            seq = V4.sequence(bars, day_of, intraday=True, ctxs=cx, _ended=ended, _stats=stats, **kw)
            closed = [t for t in seq if t.get("exit") is not None and t.get("exit_reason") != "open"]
            trades = []
            for t in closed:
                trades.append({"kind": t["kind"], "side": t["side"], "i": t["i"], "t": bars[t["i"]][0].isoformat(),
                               "t_exit": bars[t["exit_i"]][0].isoformat(), "bos": t.get("bos", t.get("prim_bos")),
                               "r": r_of(t), "cost": cost_r(market, sym, t), "reason": t.get("exit_reason"),
                               "regime": reg(ends[t["i"]], t["side"]), "tgt_src": t.get("c1_tgt_src")})
            # the reason given ON the BOS2 candle (a BOS2 not entered can later be ended by a CHoCH: not its reason)
            rejected = {(st.get("c1_side"), st.get("bos")): w for st, _j, w in ended
                        if st.get("c1_side") and _j == st.get("bos")}
            res[arm] = {"trades": trades, "ended": Counter(w for _, _, w in ended), "stats": dict(stats),
                        "open_at_end": sum(1 for t in seq if t.get("exit_reason") == "open")}
            if arm == "c1":
                # the funnel, from the same legs pass (ctx.c1_runs), and what happened to every BOS2
                runs = cx["ctx"][0].c1_runs + cx["ctx"][1].c1_runs
                f = Counter()
                for r in runs:
                    f["runs (trend started by a CHoCH)"] += 1
                    if r["bos1"] is None:
                        f["  no BOS1: CHoCH again" if r["end"] == "choch" else "  no BOS1: data ended"] += 1
                        continue
                    f["BOS1"] += 1
                    if r["pull"] is None:
                        f["  BOS1, no pullback: CHoCH" if r["end"] == "choch" else "  BOS1, no pullback: data ended"] += 1
                        continue
                    f["valid pullback started after BOS1"] += 1
                    if r["bos2"] is None:
                        f["  pullback, no BOS2: closed beyond BOS1's protected level (CHoCH)" if r["end"] == "choch"
                          else "  pullback, no BOS2: data ended"] += 1
                        continue
                    f["BOS2"] += 1
                taken = {(t["side"], t["i"]) for t in trades}
                why = Counter()
                opens = [(t["i"], bisect.bisect_left([b[0] for b in bars], datetime.fromisoformat(t["t_exit"])), t["side"])
                         for t in trades]
                rej_ended = dict(res[arm]["ended"])
                for r in runs:
                    if r["bos2"] is None:
                        continue
                    j = r["bos2"]
                    if (r["side"], j) in taken:
                        why["entered"] += 1
                        continue
                    busy = any(a < j < b for a, b, _s in opens)
                    if j + 1 >= len(bars):
                        why["BOS2 on the last candle (pending)"] += 1
                    elif (r["side"], j) in rejected:
                        why["rejected: " + rejected[(r["side"], j)]] += 1
                    elif busy:
                        why["not entered: a trade was open on the chart (one at a time)"] += 1
                    elif day[j + 1] != day[j]:
                        why["not entered: the session ended before the next open"] += 1
                    else:
                        why["not filled: the next open was beyond the stop or the target"] += 1
                res["funnel"] = dict(f)
                res["bos2_outcome"] = dict(why)
                res["c1_reject_reasons"] = rej_ended
                res["tgt_src"] = dict(Counter(t["tgt_src"] for t in trades))
        out.append(res)
    return out


def metrics(ts, net):
    xs = []
    for t in sorted(ts, key=lambda t: t["t_exit"]):
        if net:
            if t["cost"] is None:
                continue
            xs.append(t["r"] - t["cost"])
        else:
            xs.append(t["r"])
    n = len(xs)
    if not n:
        return {"n": 0}
    pos, neg = sum(x for x in xs if x > 0), -sum(x for x in xs if x < 0)
    eq = pk = dd = 0.0
    for x in xs:
        eq += x
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    return {"n": n, "win": sum(1 for x in xs if x > 0) / n, "avg": sum(xs) / n, "total": sum(xs),
            "pf": pos / neg if neg else float("inf"), "dd": dd}


def fmt(m):
    if not m["n"]:
        return "n 0"
    return "n %d | win %.1f%% | avg %+.3fR | total %+.1fR | PF %.2f | maxDD %.1fR" % (
        m["n"], 100 * m["win"], m["avg"], m["total"], m["pf"], m["dd"])


def main():
    longdir, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    jobs, ds = [], []
    for f in sorted(os.listdir(longdir)):
        if not f.endswith("_5m.json") or market_of(f) is None:
            continue
        path = os.path.join(longdir, f)
        jobs.append((market_of(f), f.replace("_5m.json", ""), path))
        ds.append((market_of(f), f.replace("_5m.json", ""), hashlib.sha256(open(path, "rb").read()).hexdigest()))
    res = []
    with Pool(2, maxtasksperchild=4) as pool:
        for n, r in enumerate(pool.imap_unordered(run_one, jobs), 1):
            res.extend(r)
            print("progress %d/%d" % (n, len(jobs)), file=sys.stderr, flush=True)
    pickle.dump(res, open(os.path.join(outdir, "c1_results.pkl"), "wb"))
    first = {(r["market"], r["sym"]): (r["first"], r["last"], r["n"]) for r in res if r["tf"] == 5}
    with open(os.path.join(outdir, "c1_dataset.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["market", "symbol", "sha256", "5m_rows_in_session", "first", "last"])
        for m, s, h in ds:
            a = first.get((m, s), ("", "", ""))
            w.writerow([m, s, h, a[2], a[0], a[1]])
    combined = hashlib.sha256("".join(h for _, _, h in ds).encode()).hexdigest()
    rep = []
    P_ = rep.append
    P_("dataset: %d files (NSE %d, US %d), combined sha256 of the per-file hashes in name order: %s" % (
        len(ds), sum(1 for d in ds if d[0] == "NSE"), sum(1 for d in ds if d[0] == "US"), combined))
    srows = []
    for m in ("NSE", "US"):
        for tf in (5, 15):
            rs = [r for r in res if r["market"] == m and r["tf"] == tf]
            P_("\n" + "=" * 100 + "\n%s %dm: %d symbols, %d candles" % (m, tf, len(rs), sum(r["n"] for r in rs)))
            fun, out2, rej = Counter(), Counter(), Counter()
            for r in rs:
                fun.update(r["funnel"])
                out2.update(r["bos2_outcome"])
                rej.update(r["c1_reject_reasons"])
            bstats = Counter()
            for r in rs:
                bstats.update(r["baseline"]["stats"])
            P_("baseline: primary BOS setups created %d" % bstats["bos"])
            P_("baseline ended reasons: %s" % dict(sum((r["baseline"]["ended"] for r in rs), Counter())))
            P_("C1 funnel: %s" % dict(fun))
            P_("C1 BOS2 outcomes: %s" % dict(out2))
            P_("C1 engine end records (incl. later CHoCH ends of BOS2 setups not entered): %s" % dict(rej))
            P_("C1 entered trades by target source (opp_bos = the default opposite-BOS rule, near = its fallback): %s"
               % dict(sum((Counter(r["tgt_src"]) for r in rs), Counter())))
            for arm in ("baseline", "c1"):
                tr = [t for r in rs for t in r[arm]["trades"]]
                prim = [t for t in tr if t["kind"] == "primary"]
                P_("\n-- %s: closed trades %d (primary %d, secondary %d), still open at the end %d" % (
                    arm, len(tr), len(prim), len(tr) - len(prim), sum(r[arm]["open_at_end"] for r in rs)))
                for part, f in (("IS ", lambda t: t["t"][:10] < SPLIT), ("OOS", lambda t: t["t"][:10] >= SPLIT)):
                    for nm, L in (("all", tr), ("primary", prim)):
                        sub = [t for t in L if f(t)]
                        P_("  %s %-8s gross %s" % (part, nm, fmt(metrics(sub, False))))
                        P_("  %s %-8s net   %s" % (part, nm, fmt(metrics(sub, True))))
                for key, vals in (("side", ("long", "short")), ("regime", ("aligned", "counter", "undefined")),
                                  ("tgt_src", ("opp_bos", "near") if arm == "c1" else ())):
                    for v in vals:
                        sub = [t for t in tr if t[key] == v]
                        P_("  %-9s %-9s IS net %s || OOS net %s" % (key, v, fmt(metrics([t for t in sub if t["t"][:10] < SPLIT], True)),
                                                                fmt(metrics([t for t in sub if t["t"][:10] >= SPLIT], True))))
                for r in rs:
                    ts = r[arm]["trades"]
                    oos = [t for t in ts if t["t"][:10] >= SPLIT]
                    mo, mi = metrics(oos, True), metrics([t for t in ts if t["t"][:10] < SPLIT], True)
                    srows.append({"market": m, "tf": tf, "arm": arm, "symbol": r["sym"], "trades": len(ts),
                                  "is_n": mi["n"], "is_net_avg": round(mi.get("avg", 0), 4) if mi["n"] else "",
                                  "oos_n": mo["n"], "oos_net_avg": round(mo.get("avg", 0), 4) if mo["n"] else "",
                                  "oos_net_total": round(mo.get("total", 0), 3) if mo["n"] else ""})
            P_("\n-- no entry (benchmark): 0 trades, 0R in every period")
    open(os.path.join(outdir, "c1_report.txt"), "w").write("\n".join(rep) + "\n")
    with open(os.path.join(outdir, "c1_symbols.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(srows[0]))
        w.writeheader()
        w.writerows(srows)
    print("\n".join(rep))


if __name__ == "__main__":
    main()
