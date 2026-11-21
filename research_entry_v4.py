#!/usr/bin/env python3
"""Entry-quality research on the internal-sweep setups (21 Nov 2026). Research only; scanner_v4 decides BOS and sweeps
(sweep_rule "internal", unchanged) and publishes every valid sweep (the _sweeps hook); this module only decides
ENTRIES on those same setups, three ways, with one simulator:

  E1 control  the scanner's own confirmation: a signal candle after the sweep (signal_kind, conf_max, latest_signal),
              then a candle closing above its high, within entry_max_bars of the sweep. Fill: the next open.
  E2 strong   the first candle after the sweep that closes in the setup's direction (close > open) AND above the
              sweep candle's high (the reclaim candle's high), within entry_max_bars. Fill: the next open.
              No body / range / extension threshold: those are only measured (distributions, in-sample).
  E3 retest   after E1's break, a buy limit at the broken signal-candle high, for entry_max_bars candles. Fills when
              a candle trades back to it (at the open if it opens through it). Stop and target fixed when placed.

Common to all three (fair comparison):
  - the same published setups, symbols, periods and direction
  - pending entries end on: a close beyond the protected swing, a CHoCH against the setup, a newer same-side BOS
    (the scanner's own "superseded"), the session's end (NSE / US), entry_max_bars without a decision
  - stop = the lowest low from the sweep candle to the signal / decision candle - buffer_atr x ATR(14) of the
    decision candle (E1 / E3: the scanner's _trade stop; E2: up to its decision candle). Never widened.
  - target = the scanner's target methodology (_trade: target_rule opp_bos_cap, big_k, the near fallback),
    computed at the decision candle for the order's entry price; min_rr as configured
  - exits: the scanner's _exit_step (stop first, target, the Trade Manager, the session's end); a retest fill
    candle is only checked against the stop (intrabar order unknown: conservative)
  - results in R: every trade risks the same money (size = risk budget / entry-to-stop distance)
  - costs: research_tf.COST_PCT (round trip, % of the entry price), converted to R per trade
Each setup is simulated on its own (no one-trade-per-chart interaction), for all three models alike."""
import bisect
import math
import os
import sys

import scanner_v4 as V4

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MODELS = ("E1 control", "E2 strong", "E3 retest")


def _target(sd, st, k, c):
    """scanner_v4._Side._trade's target for an entry price c decided on candle k (the same rules)."""
    b, ctx, p = sd.b, sd.ctx, sd.p
    liq = V4._targets(ctx, b, k, c)
    move_hi = sd.highs.q(st["bos"], st["sweep"])
    tgt = min([x for x in (liq, move_hi if move_hi > c else None) if x is not None], default=None)
    rule = p.get("target_rule", "near")
    if rule != "near":
        ot = sd._opp_target(k, c)
        if ot is not None:
            if rule == "opp_bos_cap":
                cap = sd._big_swing(k, c, int(p.get("big_k") or 6))
                if cap is not None:
                    ot = min(ot, cap)
            tgt = ot
    return tgt


class Pending:
    """The cancel rules every model shares, checked on a candle's close."""

    def __init__(self, sd, st, j0, intraday):
        self.sd, self.st, self.j0 = sd, st, j0
        self.ag = sd.ctx.choch_against
        self.bos = sorted(sd.ctx.legs)
        self.intraday = intraday

    def cancel(self, k):
        b, day = self.sd.b, self.sd.day
        if self.intraday and day is not None and day[k] != day[self.j0]:
            return "session ended"
        if b[k][4] < self.st["origin"]:
            return "closed beyond the protected swing"
        q = bisect.bisect_right(self.ag, self.j0)
        if q < len(self.ag) and self.ag[q] <= k:
            return "CHoCH"
        q = bisect.bisect_right(self.bos, self.j0)
        if q < len(self.bos) and self.bos[q] <= k:
            return "superseded by a newer BOS"
        return None


def _exit(sd, tr, start, intraday, fill_candle_stop_only=False):
    """(exit candle, exit price, reason) via scanner_v4._exit_step, from candle `start`; None = still open."""
    b, p, day = sd.b, sd.p, sd.day
    k = start
    if fill_candle_stop_only:
        if b[k][3] <= tr["cur_stop"]:
            return k, tr["cur_stop"], "stop"
        if intraday and k + 1 < len(b) and day[k + 1] != day[k]:
            return k, b[k][4], "day end"
        k += 1
    while k < len(b):
        got = V4._exit_step(b, k, tr, p, day, intraday)
        if got:
            return k, got[0], got[1]
        k += 1
    return None


def _next_open_fill(sd, k, stop, tgt, intraday):
    b, day = sd.b, sd.day
    if k + 1 >= len(b):
        return None, "decision on the last candle"
    if intraday and day[k + 1] != day[k]:
        return None, "session ended before the next open"
    o = b[k + 1][1]
    if o <= stop or o >= tgt:
        return None, "opened past the stop / target"
    return o, None


def setup_trades(sd, st, j0, intraday):
    """The three models on one published swept setup. {model: {"opp": bool, "trade": dict | None, "why": str}}."""
    b, ctx, p = sd.b, sd.ctx, sd.p
    nmax = int(p.get("entry_max_bars") or 12)
    pend = Pending(sd, st, j0, intraday)
    out = {}
    last = min(len(b) - 1, j0 + nmax)

    def finish(name, k, s_lo_end, entry_px, decide_close, fill_k, stop_only):
        a = ctx.atr[k]
        stop = sd.lows.q(j0, s_lo_end) - p["buffer_atr"] * a
        if stop >= decide_close:
            out[name] = {"opp": True, "trade": None, "why": "stop at or beyond the entry"}
            return
        tgt = _target(sd, st, k, decide_close)
        if tgt is None or tgt <= decide_close or (tgt - decide_close) < p["min_rr"] * (decide_close - stop):
            out[name] = {"opp": True, "trade": None, "why": "no target beyond the entry"}
            return
        if entry_px is None:
            o, why = _next_open_fill(sd, k, stop, tgt, intraday)
            if o is None:
                out[name] = {"opp": True, "trade": None, "why": why}
                return
            entry_px, fill_k = o, k + 1
        tr = {"i": k, "entry": entry_px, "stop": stop, "cur_stop": stop, "target": tgt}
        ex = _exit(sd, tr, fill_k, intraday, fill_candle_stop_only=stop_only)
        if ex is None:
            out[name] = {"opp": True, "trade": None, "why": "still open at the end of the data"}
            return
        risk = entry_px - stop
        out[name] = {"opp": True, "why": "traded", "trade": {
            "decide": k, "fill": fill_k, "exit_i": ex[0], "entry": entry_px, "stop": stop, "target": tgt,
            "exit": ex[1], "reason": ex[2], "r": (ex[1] - entry_px) / risk, "risk": risk, "atr": a,
            "stop_atr": risk / a, "body_atr": abs(b[k][4] - b[k][1]) / a, "range_atr": (b[k][2] - b[k][3]) / a,
            "ext_atr": (b[k][4] - st["lvl"]) / a}}

    # E1 control (and the break E3 builds on)
    e1 = None
    for k in range(j0 + 1, last + 1):
        why = pend.cancel(k)
        if why:
            out["E1 control"] = {"opp": False, "trade": None, "why": why}
            break
        c = b[k][4]
        s = next((x for x in range(k - 1, max(k - p["conf_max"], 0) - 1, -1) if sd.pat(x)), None)
        if s is None or s <= j0 or c <= b[s][2] or not ctx.atr[k]:
            continue
        e1 = (k, s)
        finish("E1 control", k, s, None, c, None, False)
        break
    else:
        out["E1 control"] = {"opp": False, "trade": None, "why": "no confirmation within %d candles" % nmax}
    # E2 strong
    for k in range(j0 + 1, last + 1):
        why = pend.cancel(k)
        if why:
            out["E2 strong"] = {"opp": False, "trade": None, "why": why}
            break
        o, c = b[k][1], b[k][4]
        if c > o and c > b[j0][2] and ctx.atr[k]:
            finish("E2 strong", k, k, None, c, None, False)
            break
    else:
        out["E2 strong"] = {"opp": False, "trade": None, "why": "no confirmation within %d candles" % nmax}
    # E3 retest of E1's broken level
    if e1 is None:
        out["E3 retest"] = {"opp": False, "trade": None, "why": "no confirmation break (E1)"}
        return out
    k1, s = e1
    lvl = b[s][2]
    a1 = ctx.atr[k1]
    stop = sd.lows.q(j0, s) - p["buffer_atr"] * a1
    tgt = _target(sd, st, k1, lvl)
    if tgt is None or tgt <= lvl:
        out["E3 retest"] = {"opp": True, "trade": None, "why": "no target beyond the entry"}
        return out
    for k in range(k1 + 1, min(len(b) - 1, k1 + nmax) + 1):
        if intraday and sd.day[k] != sd.day[j0]:
            out["E3 retest"] = {"opp": True, "trade": None, "why": "session ended before a retest"}
            return out
        if b[k][3] <= lvl:
            px = min(b[k][1], lvl)
            if px <= stop:
                out["E3 retest"] = {"opp": True, "trade": None, "why": "gapped through the stop before a fill"}
                return out
            tr = {"i": k1, "entry": px, "stop": stop, "cur_stop": stop, "target": tgt}
            ex = _exit(sd, tr, k, intraday, fill_candle_stop_only=True)
            if ex is None:
                out["E3 retest"] = {"opp": True, "trade": None, "why": "still open at the end of the data"}
                return out
            risk = px - stop
            out["E3 retest"] = {"opp": True, "why": "traded", "trade": {
                "decide": k1, "fill": k, "exit_i": ex[0], "entry": px, "stop": stop, "target": tgt, "exit": ex[1],
                "reason": ex[2], "r": (ex[1] - px) / risk, "risk": risk, "atr": a1, "stop_atr": risk / a1,
                "body_atr": None, "range_atr": None, "ext_atr": (px - st["lvl"]) / a1}}
            return out
        why = pend.cancel(k)
        if why:
            out["E3 retest"] = {"opp": True, "trade": None, "why": why + " before a retest"}
            return out
    out["E3 retest"] = {"opp": True, "trade": None, "why": "no retest within %d candles" % nmax}
    return out


def chart(args):
    """One symbol: the scanner (internal sweep) once, then the three entry models on each published sweep."""
    import research_features as F
    market, sym, rows, tm, cost_pct = args
    m = F.MARKETS[market]
    day_of = (lambda t: m["local"](t).date())
    sweeps = []
    seq = V4.sequence(rows, day_of, intraday=m["intraday"], max_hold=None, _sweeps=sweeps,
                      **dict(tm, sweep_rule="internal", sweep_max_bars=12, sweep_pen_atr=0.25, entry_max_bars=12))
    engine = {(t["side"], t["bos"]): t["i"] for t in seq if t["kind"] == "primary"}
    res = []
    for sd, st, j0 in sweeps:
        side = "long" if sd.b is rows else "short"
        r = setup_trades(sd, st, j0, m["intraday"])
        row = {"sym": sym, "side": side, "bos": st["bos"], "sweep": j0, "day": day_of(rows[j0][0]).isoformat(),
               "engine_i": engine.get((side, st["bos"]))}
        for name in MODELS:
            x = r[name]
            t = x["trade"]
            if t:
                t = dict(t, cost_r=cost_pct / 100 * abs(t["entry"]) / t["risk"],
                         day=day_of(rows[t["decide"]][0]).isoformat())
            row[name] = {"opp": x["opp"], "why": x["why"], "trade": t}
        res.append(row)
    return sym, res


def stats(trs, net):
    xs = [t["r"] - (t["cost_r"] if net else 0) for t in sorted(trs, key=lambda t: (t["day"], t["decide"]))]
    n = len(xs)
    if not n:
        return None
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    pos, neg = sum(x for x in xs if x > 0), -sum(x for x in xs if x < 0)
    eq = pk = dd = 0.0
    for x in xs:
        eq += x
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    return {"n": n, "mean": mean, "se": sd / math.sqrt(n) if n > 1 else float("nan"),
            "win": sum(1 for x in xs if x > 0) / n, "pf": pos / neg if neg else float("inf"), "dd": dd}


def fmt(s):
    if not s:
        return "n 0"
    return "n %5d  avg %+.3fR  95%% CI [%+.3f, %+.3f]  win %4.1f%%  PF %.2f  maxDD %6.1fR" % (
        s["n"], s["mean"], s["mean"] - 1.96 * s["se"], s["mean"] + 1.96 * s["se"], 100 * s["win"], s["pf"], s["dd"])


BINS = {"body_atr": [0.5, 1.0, 1.5], "range_atr": [1.0, 1.5, 2.0], "ext_atr": [0.25, 0.5, 1.0]}   # fixed in advance


def report(market, rows, split, cost_pct):
    L = []
    P = L.append
    n_set = len(rows)
    P("%s: %d published internal-sweep setups (sweeps); costs %.3f%% round trip of the entry price; out-of-sample "
      "from %s" % (market, n_set, cost_pct, split))
    eng = [r for r in rows if r["engine_i"] is not None]
    agree = sum(1 for r in eng if r["E1 control"]["trade"] and r["E1 control"]["trade"]["decide"] == r["engine_i"])
    P("E1 vs the scanner's own trades on these setups: the engine traded %d of them; E1 decides on the same candle "
      "for %d (%.1f%%). (The engine also applies one trade per chart, flips and the latest-BOS rule.)" % (
          len(eng), agree, 100 * agree / max(1, len(eng))))
    for name in MODELS:
        opp = sum(1 for r in rows if r[name]["opp"])
        tr = [r[name]["trade"] for r in rows if r[name]["trade"]]
        why = {}
        for r in rows:
            if not r[name]["trade"]:
                why[r[name]["why"]] = why.get(r[name]["why"], 0) + 1
        P("\n== %s: eligible setups %d | entry opportunities %d | executed (closed) trades %d" % (
            name, n_set, opp, len(tr)))
        P("   not executed: %s" % ", ".join("%s %d" % kv for kv in sorted(why.items(), key=lambda x: -x[1])))
        if tr:
            P("   avg initial stop %.2f ATR | avg cost %.3fR | exits %s" % (
                sum(t["stop_atr"] for t in tr) / len(tr), sum(t["cost_r"] for t in tr) / len(tr),
                ", ".join("%s %d" % kv for kv in sorted(_count(t["reason"] for t in tr).items(), key=lambda x: -x[1]))))
        for part, f in (("IS ", lambda t: t["day"] < split), ("OOS", lambda t: t["day"] >= split)):
            sub = [t for t in tr if f(t)]
            g, nt = stats(sub, False), stats(sub, True)
            P("   %s gross %s" % (part, fmt(g)))
            P("   %s net   %s" % (part, fmt(nt)))
            if g and nt:
                P("   %s costs consumed %.3fR per trade (%s of the gross mean)" % (
                    part, g["mean"] - nt["mean"], ("%.0f%%" % (100 * (g["mean"] - nt["mean"]) / g["mean"]))
                    if g["mean"] > 0 else "gross mean <= 0"))
        for side in ("long", "short"):
            sub = [r[name]["trade"] for r in rows if r[name]["trade"] and r["side"] == side]
            P("   %-5s all-period net %s" % (side, fmt(stats(sub, True))))
    # E2 distributions, IN-SAMPLE only (no threshold chosen here)
    P("\nE2 decision-candle distributions, IN-SAMPLE trades only (bins fixed in advance; reported, not applied):")
    tr = [r["E2 strong"]["trade"] for r in rows if r["E2 strong"]["trade"] and r["E2 strong"]["trade"]["day"] < split]
    for key, edges in BINS.items():
        cells = []
        for kb in range(len(edges) + 1):
            sub = [t for t in tr if t[key] is not None and bisect.bisect_right(edges, t[key]) == kb]
            lo = "<%g" % edges[0] if kb == 0 else (">=%g" % edges[-1] if kb == len(edges) else "%g-%g" % (edges[kb - 1], edges[kb]))
            s = stats(sub, True)
            cells.append("%s: %s" % (lo, "n 0" if not s else "n %d net %+.3f±%.3f" % (s["n"], s["mean"], 1.96 * s["se"])))
        P("   %-9s %s" % (key, " | ".join(cells)))
    return "\n".join(L)


def _count(it):
    d = {}
    for x in it:
        d[x] = d.get(x, 0) + 1
    return d


def main(argv=None):
    import argparse
    import json
    from multiprocessing import Pool
    import research_features as F
    import research_tf as TF
    ap = argparse.ArgumentParser(prog="research_scanner_v4.py entry")
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
    cost = TF.COST_PCT[a.market]
    jobs = [(a.market, s, rows, tm, cost) for s, rows in data.items()]
    with Pool(a.workers, maxtasksperchild=4) as pool:
        res = dict(pool.imap_unordered(chart, jobs))
    rows = [r for v in res.values() for r in v]
    print(report(a.market, rows, TF.SPLIT[a.market], cost))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rows, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
