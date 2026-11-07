#!/usr/bin/env python3
"""
research_tm.py - backtest of the Trade Manager (paper.py, 7 Nov 2026) on the Scanner v2 playbook entries
(doji / bottom star / top hammer with structure first, FVG / order-block retests: exactly what Scanner v2 trades,
stop 0.1 ATR beyond the trigger, target 2R). Walk-forward 70/30, R after costs. It doubles as the US playbook
backtest that was never run.

    python research.py us-tm          # US stocks, 5m, intraday (entries 9:45-15:30 ET, flat 15:55)
    python research.py nse-tm         # NSE stocks, 5m, intraday (entries 9:30-14:30, flat 15:15)
    python research.py crypto-tm      # crypto, 15m (12h max hold)
    python research.py crypto-tm-5m   # crypto, 5m

Exit variants, each the same entries:
  base        stop / 2R target only (what paper did before the Trade Manager)
  be          + stop to the entry at +1R
  be_lock     + once 80% of the way to the target, lock half of it
  be_lock_rev + a reversal candle near the high after +1R takes the profit (engulfing / upper-wick rejection)
  be_lock_stale + no follow-through: out after 60 min (crypto 4h) if best < 0.5R and within 0.3R of the entry
  all         every rule (= the Trade Manager as it runs live)
"""
import itertools
import os
from datetime import datetime, timezone

import research_abcd as RA
import smc_playbook as PB

UTC = timezone.utc
VARIANTS = {"base": set(), "be": {"be"}, "be_lock": {"be", "lock"}, "be_lock_rev": {"be", "lock", "rev"},
            "be_lock_stale": {"be", "lock", "stale"}, "all": {"be", "lock", "rev", "stale"}}


def manage(path, entry, stop, target, rules, stale_bars):
    """R of a long (src terms) over path (t, o, h, l, c, v) with the Trade Manager rules; stop first in a candle;
    a stop moved on a candle counts from the next one. Out at the last close if nothing hits."""
    risk = entry - stop
    if risk <= 0:
        return None
    cur, mfe, way = stop, 0.0, target - entry
    for k, b in enumerate(path):
        o, h, l, c = b[1], b[2], b[3], b[4]
        if l <= cur:
            fill = o if o < cur else cur
            return (fill - entry) / risk
        if h >= target:
            return (target - entry) / risk
        mfe = max(mfe, (h - entry) / risk)
        if "rev" in rules and mfe >= 1.0 and k >= 1:
            p = path[k - 1]
            rng = h - l
            engulf = p[4] > p[1] and c < o and o >= p[4] and c <= p[1]
            reject = rng > 0 and (h - max(o, c)) / rng >= 0.6 and (c - l) / rng <= 0.4
            if (engulf or reject) and h >= entry + (mfe - 0.25) * risk:
                return (c - entry) / risk
        if "stale" in rules and k + 1 >= stale_bars and mfe < 0.5 and abs(c - entry) < 0.3 * risk:
            return (c - entry) / risk
        if "be" in rules and mfe >= 1.0:
            cur = max(cur, entry)
        if "lock" in rules and way > 0 and (h - entry) / way >= 0.8:
            cur = max(cur, entry + 0.5 * way)
    return ((path[-1][4] if path else entry) - entry) / risk


def events_tm(data, day_of, hold, cost_fn, stale_bars, entry_ok=None, path_end=None):
    evs = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]) if None not in (o, h, l, c)]
        if len(rows) < 200:
            continue
        ctx = PB.Context(rows, day_of)
        mrows = [(r[0], -r[1], -r[3], -r[2], -r[4], r[5]) for r in rows]
        for i in range(40, len(rows) - 2):
            if entry_ok and not entry_ok(rows[i][0]):
                continue
            done = set()
            for s in PB.find_setups(ctx, i) + PB.zone_setups(ctx, i):
                if s["setup"] in done or (s["setup"] in PB.SETUPS and not s.get("struct_before")):
                    continue
                done.add(s["setup"])
                long = s["side"] == "long"
                stop = PB.stop_for(s, 0.1)
                risk = (s["entry"] - stop) if long else (stop - s["entry"])
                if risk <= 0:
                    continue
                target = s["entry"] + 2 * risk if long else s["entry"] - 2 * risk
                end = path_end(rows[i][0]) if path_end else None
                src = rows if long else mrows
                path = [b for b in src[i + 1:i + 1 + hold] if end is None or b[0] < end]
                if not path:
                    continue
                sg = 1 if long else -1
                cost = cost_fn(sym, s["entry"], stop, target, s["side"])
                if cost is None:
                    continue
                out = {}
                for name, rules in VARIANTS.items():
                    r = manage(path, sg * s["entry"], sg * stop, sg * target, rules, stale_bars)
                    if r is not None:
                        out[name] = r - cost
                evs.append({"sym": sym, "day": rows[i][0].date().isoformat(), "i": i, "side": s["side"],
                            "setup": PB.SETUP_NAMES.get("smcp_" + s["setup"], s["setup"]), "out": out})
    evs.sort(key=lambda e: (e["day"], e["sym"], e["i"]))
    return evs


def score(events, f, split, stats, spacing):
    ins, oos, last, rs = {}, {}, {}, []
    for ev in events:
        if f["side"] != "both" and ev["side"] != f["side"]:
            continue
        if f.get("setup", "all") != "all" and ev["setup"] != f["setup"]:
            continue
        if f["exits"] not in ev["out"]:
            continue
        if ev["sym"] in last and ev["i"] - last[ev["sym"]] < spacing:
            continue
        last[ev["sym"]] = ev["i"]
        (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["out"][f["exits"]])
        rs.append(ev["out"][f["exits"]])
    return {"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos), "rs": rs}


def row(r, label=""):
    f, i, o = r["filters"], r["in_sample"], r["out_of_sample"]

    def s(x):
        if not x.get("trades"):
            return "no trades"
        return "%4d tr (%.1f/day)  win %3.0f%%  avg %+.2fR  total %+7.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
            x["worst_day_r"], x["max_drawdown_r"])
    return "%s%s\n     in-sample   %s\n     OUT-sample  %s" % (
        label, " ".join("%s=%s" % (k, v) for k, v in f.items()), s(i), s(o))


def main(a, syms, src, fetch_all, fetch, stats, out_dir, tz_local, market="us", step=5):
    import paper as P
    entry_ok = path_end = None
    if market == "crypto":
        iv = "%dm" % step
        print("Fetching 60 days of %s bars for %d coins (%s)..." % (iv, len(syms), src), flush=True)
        data, _ = fetch_all(syms, "-USD", iv, a.workers)
        fee = float(P.load_config()["accounts"]["CRYPTO"]["fee_pct"]) / 100

        def cost_fn(sym, entry, stop, exit_px, side):
            return (entry + exit_px) * fee / abs(entry - stop)
        day_of, hold, stale = (lambda t: t.date()), 12 * 60 // step, 240 // step
        mode = "crypto-tm" + ("" if step == 15 else "-%dm" % step)
        what, costs = "%d coins, %s candles, 12h max hold" % (len(data), iv), "%.3f%% fee a side" % (fee * 100)
    elif market == "nse":
        print("Fetching 60 days of 5-minute bars for %d NSE symbols (%s)..." % (len(syms), src), flush=True)
        data, _ = fetch_all(syms, ".NS", "5m", a.workers)
        cfg = P.DEFAULT_CONFIG
        acc = cfg["accounts"]["INDIA"]

        def cost_fn(sym, entry, stop, exit_px, side):
            risk = abs(entry - stop)
            qty = int(min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / entry))
            if qty < 1:
                return None
            o, c = ("buy", "sell") if side == "long" else ("sell", "buy")
            return (P.charges(cfg, "NSE", sym, o, qty * entry) + P.charges(cfg, "NSE", sym, c, qty * exit_px)) / (qty * risk)

        def entry_ok(t):
            lt = t.astimezone(tz_local)
            return (9, 30) <= (lt.hour, lt.minute) <= (14, 30)

        def path_end(t):
            return t.astimezone(tz_local).replace(hour=15, minute=15, second=0, microsecond=0)
        day_of, hold, stale = (lambda t: t.astimezone(tz_local).date()), 75, 12
        mode, what = "nse-tm", "%d NSE stocks, 5m candles, intraday" % len(data)
        costs = "paper.py India charges (STT, brokerage, ...)"
    else:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        print("Fetching 60 days of 5-minute bars for %d US symbols (%s)..." % (len(syms), src), flush=True)
        data, _ = fetch_all(syms, "", "5m", a.workers)
        fee = float(P.load_config()["accounts"]["US"].get("fee_pct", 0)) / 100 + 0.0002

        def cost_fn(sym, entry, stop, exit_px, side):
            return (entry + exit_px) * fee / abs(entry - stop)

        def entry_ok(t):
            lt = t.astimezone(et)
            return (9, 45) <= (lt.hour, lt.minute) <= (15, 30)

        def path_end(t):
            return t.astimezone(et).replace(hour=15, minute=55, second=0, microsecond=0)
        day_of, hold, stale = (lambda t: t.astimezone(et).date()), 78, 12
        mode, what = "us-tm", "%d US stocks/ETFs, 5m candles, intraday" % len(data)
        costs = "%.3f%% a side (paper fee + 0.02%% assumed spread/slippage)" % (fee * 100)

    events = events_tm(data, day_of, hold, cost_fn, stale, entry_ok=entry_ok, path_end=path_end)
    if not events:
        print("No playbook entries found: no data came back (check the internet / Yahoo).")
        return 1
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    spacing = 12
    lines = ["research.py %s  %s" % (mode, datetime.now(tz_local).strftime("%Y-%m-%d %H:%M %Z")),
             "Trade Manager backtest on the Scanner v2 playbook entries (doji / star / hammer after structure, FVG / OB "
             "retests; stop 0.1 ATR beyond, target 2R).",
             "%s, %d days (%s..%s), %d entries. R after costs (%s). Out-of-sample = days from %s." % (
                 what, len(days), days[0], days[-1], len(events), costs, split), "",
             "EXITS COMPARED (the same entries; 'all' = the Trade Manager as it runs live):"]
    best = None
    for side in ("both", "long", "short"):
        for v in VARIANTS:
            r = score(events, {"side": side, "exits": v}, split, stats, spacing)
            lines.append(row(r, "  "))
            o = r["out_of_sample"]
            if side == "both" and o.get("trades") and (best is None or o["avg_r"] > best[1]):
                best = (v, o["avg_r"])
        lines.append("")
    setups = sorted({e["setup"] for e in events})
    lines += ["PER SETUP (the US playbook backtest the paper results asked for): base exits vs the Trade Manager:"]
    for st in setups:
        for v in ("base", "all"):
            lines.append(row(score(events, {"side": "both", "setup": st, "exits": v}, split, stats, spacing), "  "))
    lines += ["", "Best exit set out-of-sample (all setups, both sides): %s (avg %+.2fR)." % best if best else "",
              "Read it this way: the Trade Manager helps if 'all' beats 'base' OUT-of-sample, for longs and shorts, and",
              "most setups. It cannot turn entries with no edge into winners: it cuts losers and protects winners.",
              "~60 days is short. Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report_%s.txt" % mode), "w", encoding="utf-8") as fh:
        fh.write(report)
    print("\nWrote %s" % os.path.join(out_dir, "report_%s.txt" % mode))
    return 0
