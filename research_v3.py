#!/usr/bin/env python3
"""
research_v3.py - backtest of Scanner v3's sweep reversal (sweep_reversal.py, the owner's workflow PDF), walk-forward
70/30, R after costs.

    python research.py crypto-v3       # crypto, 15-minute candles
    python research.py crypto-v3-5m    # crypto, 5-minute candles
    python research.py nse-v3          # NSE stocks, 5m, intraday (entries 9:30-14:30, flat 15:15)
    python research.py us-v3           # US stocks, 5m, intraday (entries 9:45-15:30 ET, flat 15:55)

Grid (small on purpose, so a lucky combination is less likely): side (long, short, both) x swept low (any, the BOS
move's start, a swing low after the BOS) x trigger (signal candle high, sweep candle high, either) x extended filter
(on, off) x target (1R, 2R, liquidity with R:R >= 1, liquidity with R:R >= 2) x hours (crypto). One trade per symbol
at a time. "Live" = what Scanner v3 trades: both sides, any low, either trigger, extended skipped, liquidity R:R >= 1.
"""
import itertools
import os
from datetime import datetime, timezone

import research_abcd as RA
import sweep_reversal as V

UTC = timezone.utc
TARGETS = ("1R", "2R", "liq_rr1", "liq_rr2")
LEVELS = ("any", "origin", "post")
TRIGGERS = ("signal", "sweep", "either")
LIVE = {"side": "both", "level": "any", "trigger": "either", "ext": True, "target": "liq_rr1", "session": "all"}


def events_v3(data, day_of, hold, cost_fn, entry_ok=None, path_end=None):
    evs = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]) if None not in (o, h, l, c)]
        if len(rows) < 250:
            continue
        mrows = V.mirror(rows)
        for short in (False, True):
            ctx, src, sg = None, (mrows if short else rows), (-1 if short else 1)
            for lv in LEVELS:
                for tr in TRIGGERS:
                    ctx, sigs = V.signals(rows, day_of, trigger=tr, level=lv, ext=False, short=short, ctx=ctx)
                    for s in sigs:
                        i = s["i"]
                        if entry_ok and not entry_ok(rows[i][0]):
                            continue
                        end = path_end(rows[i][0]) if path_end else None
                        path = [b for b in src[i + 1:i + 1 + hold] if end is None or b[0] < end]
                        if not path:
                            continue
                        stop = V.stop_for(s)
                        risk = (s["entry"] - stop) * sg
                        if risk <= 0:
                            continue
                        ev = {"sym": sym, "day": rows[i][0].date().isoformat(), "i": i, "hour": rows[i][0].hour,
                              "side": s["side"], "level": lv, "trigger": tr, "extended": s["extended"], "out": {}}
                        for tg in TARGETS:
                            tp = V.target_for(s, "swing" if tg.startswith("liq") else tg, stop)
                            if tp is None:
                                continue
                            if tg.startswith("liq") and V.rr(s, stop, tp) < (1.0 if tg == "liq_rr1" else 2.0):
                                continue
                            r = RA._exit(path, sg * s["entry"], sg * stop, sg * tp)
                            cost = cost_fn(sym, s["entry"], stop, tp, s["side"])
                            if cost is None:
                                continue
                            ev["out"][tg] = r - cost
                        if ev["out"]:
                            evs.append(ev)
    evs.sort(key=lambda e: (e["day"], e["sym"], e["i"]))
    return evs


def keep(ev, f):
    if f["side"] != "both" and ev["side"] != f["side"]:
        return False
    if ev["level"] != f["level"] or ev["trigger"] != f["trigger"] or f["target"] not in ev["out"]:
        return False
    if f["ext"] and ev["extended"]:
        return False
    if f.get("session") == "active" and ev["hour"] < 6:
        return False
    return True


def score(events, f, split, stats, spacing):
    ins, oos, last, rs = {}, {}, {}, []
    for ev in events:
        if not keep(ev, f):
            continue
        if ev["sym"] in last and ev["i"] - last[ev["sym"]] < spacing:
            continue
        last[ev["sym"]] = ev["i"]
        (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["out"][f["target"]])
        rs.append(ev["out"][f["target"]])
    return {"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos), "rs": rs}


def row(r, label=""):
    f, i, o = r["filters"], r["in_sample"], r["out_of_sample"]

    def s(x):
        if not x.get("trades"):
            return "no trades"
        return "%4d tr (%.1f/day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
            x["worst_day_r"], x["max_drawdown_r"])
    parts = ["side=%s" % f["side"], "low=%s" % f["level"], "trigger=%s" % f["trigger"],
             "extended=%s" % ("skip" if f["ext"] else "keep"), "target=%s" % f["target"]]
    if "session" in f:
        parts.append("hours=%s" % f["session"])
    return "%s%s\n     in-sample   %s\n     OUT-sample  %s" % (label, " ".join(parts), s(i), s(o))


def main(a, syms, src, fetch_all, fetch, stats, out_dir, tz_local, market="crypto", step=15):
    import paper as P
    if market == "crypto":
        iv = "%dm" % step
        print("Fetching 60 days of %s bars for %d coins (%s)..." % (iv, len(syms), src), flush=True)
        data, _ = fetch_all(syms, "-USD", iv, a.workers)
        fee = float(P.load_config()["accounts"]["CRYPTO"]["fee_pct"]) / 100

        def cost_fn(sym, entry, stop, exit_px, side):
            return (entry + exit_px) * fee / abs(entry - stop)

        events = events_v3(data, lambda t: t.date(), hold=12 * 60 // step, cost_fn=cost_fn)
        spacing, mode = 240 // step, "crypto-v3" + ("" if step == 15 else "-%dm" % step)
        what, costs = "%d coins, %s candles, 12h max hold" % (len(data), iv), "%.3f%% fee a side" % (fee * 100)
        grid_extra = {"session": ["all", "active"]}
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

        events = events_v3(data, lambda t: t.astimezone(tz_local).date(), hold=75, cost_fn=cost_fn,
                           entry_ok=entry_ok, path_end=path_end)
        spacing, mode = 24, "nse-v3"
        what, costs = "%d NSE stocks, 5m candles, intraday" % len(data), "paper.py India charges (STT, brokerage, ...)"
        grid_extra = {}
    else:   # US
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        print("Fetching 60 days of 5-minute bars for %d US symbols (%s)..." % (len(syms), src), flush=True)
        data, _ = fetch_all(syms, "", "5m", a.workers)
        fee = float(P.load_config()["accounts"]["US"].get("fee_pct", 0)) / 100 + 0.0002   # + 0.02% spread/slip

        def cost_fn(sym, entry, stop, exit_px, side):
            return (entry + exit_px) * fee / abs(entry - stop)

        def entry_ok(t):
            lt = t.astimezone(et)
            return (9, 45) <= (lt.hour, lt.minute) <= (15, 30)

        def path_end(t):
            return t.astimezone(et).replace(hour=15, minute=55, second=0, microsecond=0)

        events = events_v3(data, lambda t: t.astimezone(et).date(), hold=78, cost_fn=cost_fn,
                           entry_ok=entry_ok, path_end=path_end)
        spacing, mode = 24, "us-v3"
        what = "%d US stocks/ETFs, 5m candles, intraday" % len(data)
        costs = "%.3f%% a side (paper fee + 0.02%% assumed spread/slippage)" % (fee * 100)
        grid_extra = {}

    if not events:
        print("No v3 sweep-reversal entries found: no data came back (check the internet / Yahoo).")
        return 1
    grid = {"side": ["long", "short", "both"], "level": list(LEVELS), "trigger": list(TRIGGERS), "ext": [True, False],
            "target": list(TARGETS), **grid_extra}
    live = dict(LIVE) if market == "crypto" else {k: v for k, v in LIVE.items() if k != "session"}
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    combos = list(itertools.product(*grid.values()))
    print("%d entries (all variants); scoring %d combinations..." % (len(events), len(combos)), flush=True)
    res = [score(events, dict(zip(grid, c)), split, stats, spacing) for c in combos]
    ok, seen = [], set()
    for r in res:
        if r["in_sample"].get("trades", 0) < 20 or r["out_of_sample"].get("trades", 0) < 10:
            continue
        sig = (r["in_sample"]["trades"], r["in_sample"]["total_r"], r["out_of_sample"]["trades"],
               r["out_of_sample"]["total_r"])
        if sig not in seen:
            seen.add(sig)
            ok.append(r)
    ok.sort(key=lambda r: -r["in_sample"]["avg_r"])
    stable = sorted([r for r in ok if r["in_sample"]["avg_r"] > 0 and r["out_of_sample"]["avg_r"] > 0],
                    key=lambda r: -min(r["in_sample"]["avg_r"], r["out_of_sample"]["avg_r"]))

    def effect(name, on, off):
        a_ = [r["out_of_sample"]["avg_r"] for r in ok if r["filters"][name] == on]
        b_ = [r["out_of_sample"]["avg_r"] for r in ok if r["filters"][name] == off]
        if not a_ or not b_:
            return "  %-24s not enough trades to compare" % ("%s=%s" % (name, on))
        ma, mb = sum(a_) / len(a_), sum(b_) / len(b_)
        return "  %-24s %+.2fR vs %+.2fR with %s  (%s)" % ("%s=%s" % (name, on), ma, mb, off,
                                                         "helps" if ma > mb + 0.03 else "hurts" if ma < mb - 0.03
                                                         else "no clear effect")

    base = [e for e in events if e["level"] == "any" and e["trigger"] == "either" and not e["extended"]]
    longs = sum(1 for e in base if e["side"] == "long")
    shorts = len(base) - longs
    lines = ["research.py %s  %s" % (mode, datetime.now(tz_local).strftime("%Y-%m-%d %H:%M %Z")),
             "Scanner v3 sweep reversal (sweep_reversal.py, the owner's workflow PDF): BOS -> a candle CLOSES below the "
             "swept low -> doji / inverted hammer at the low -> a close above the trigger within 2 candles. Shorts = mirror.",
             "%s, %d days (%s..%s). Live-reading entries (any low, either trigger, not extended): %d long, %d short. "
             "R after costs (%s). Out-of-sample = days from %s." % (what, len(days), days[0], days[-1], longs, shorts,
                                                                    costs, split), "",
             row(score(events, live, split, stats, spacing), "LIVE (what Scanner v3 paper trades):  "),
             row(score(events, dict(live, side="long"), split, stats, spacing), "LIVE, longs only:  "),
             row(score(events, dict(live, side="short"), split, stats, spacing), "LIVE, shorts only:  "), "",
             "WHICH INGREDIENT HELPS (average OUT-sample R of the combinations with it vs the alternative):",
             effect("level", "origin", "any"), effect("level", "post", "any"), effect("trigger", "signal", "either"),
             effect("trigger", "sweep", "either"), effect("ext", True, False), effect("target", "liq_rr2", "liq_rr1"),
             effect("target", "2R", "liq_rr1"), effect("target", "1R", "liq_rr1"), effect("side", "short", "long")]
    if market == "crypto":
        lines.append(effect("session", "active", "all"))
    lines += ["", "TOP 10 BY IN-SAMPLE (the OUT-sample line is the honest one):"]
    for n, r in enumerate(ok[:10], 1):
        lines.append(row(r, "%2d. " % n))
    lines += ["", "%d of %d distinct combinations (with enough trades) were positive both in- and out-of-sample." % (
        len(stable), len(ok))]
    if stable:
        best = stable[0]
        lines += ["", "MOST CONSISTENT (best of its weaker half):", row(best, "  "), RA.concentration(best), "",
                  "ITS NEIGHBOURS (one setting changed at a time; a robust rule has neighbours that also do well):"]
        for k, vals in grid.items():
            for v in vals:
                if v != best["filters"][k]:
                    lines.append(row(score(events, dict(best["filters"], **{k: v}), split, stats, spacing),
                                     "  %s=%s -> " % (k, v)))
    lines += ["", "Luck check: on random-walk test data some combinations look positive in both halves by chance alone",
              "(about 1% with crypto fees; about 10% with the low US costs). Trust a result only if its neighbours agree.",
              "Decision rule: keep it trading (paper) only if positive out-of-sample with 20+ trades and its neighbours",
              "mostly stay positive. ~60 days is short. Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report_%s.txt" % mode), "w", encoding="utf-8") as fh:
        fh.write(report)
    print("\nWrote %s" % os.path.join(out_dir, "report_%s.txt" % mode))
    return 0
