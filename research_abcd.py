#!/usr/bin/env python3
"""
research_abcd.py - backtest of the owner's A-B-C-D entry (abcd.py), walk-forward 70/30, R after costs.

    python research.py crypto-abcd       # crypto, 15-minute candles
    python research.py crypto-abcd-5m    # crypto, 5-minute candles
    python research.py nse-abcd          # NSE stocks, 5-minute candles, intraday (entries 9:30-14:30, flat 15:15)
    python research.py us-abcd           # US stocks, 5-minute candles, intraday (entries 9:45-15:30 ET, flat 15:55)

Grid: side (long = the PDF, short = its mirror, both) x doji body (15%, 25%) x B reading (close below only, close
below + reclaim) x D window (2, 6, 12 candles after C) x stop (below C-low = the PDF's example, below the lowest
low from B to D) x target (2R = the PDF's example, trail, nearest swing) x trend filter (off, close above EMA200 =
the PDF's "higher-timeframe" skip) x hours (crypto). One trade per symbol at a time.
"""
import bisect
import itertools
import os
from datetime import datetime, timezone

import abcd as A

UTC = timezone.utc
STOPS = ("c_low", "sweep")
TARGETS = ("2R", "trail", "internal")
DOJI = (0.15, 0.25)
PDF = {"side": "long", "doji": 0.15, "reclaim": False, "dmax": 12, "stop": "c_low", "target": "2R", "trend": False,
       "session": "all"}
US_LIQUID = ("AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO JPM V MA UNH HD PG COST JNJ XOM CVX ABBV MRK PEP KO WMT BAC "
             "WFC CSCO ORCL CRM ADBE AMD INTC QCOM TXN AMAT MU NFLX DIS NKE MCD SBUX MAR HLT BKNG ABNB UBER LYFT "
             "CAT DE BA GE HON LMT RTX UPS FDX GS MS C AXP BLK SCHW PYPL SQ SHOP COIN PLTR SNOW CRWD PANW NOW "
             "INTU ISRG LLY PFE TMO DHR AMGN GILD CVS CI T VZ TMUS CMCSA CHTR SPGI ICE CME MMM DOW LIN F GM RIVN "
             "SPY QQQ").split()


def _exit(path, entry, stop, target, trail_atr=None):
    risk = entry - stop
    cur, armed, hi = stop, False, entry
    for b in path:
        if b[3] <= cur:
            return (cur - entry) / risk
        if trail_atr is None:
            if b[2] >= target:
                return (target - entry) / risk
        else:
            hi = max(hi, b[2])
            if not armed and hi >= entry + risk:
                armed, cur = True, max(cur, entry)
            if armed:
                cur = max(cur, hi - 2.0 * trail_atr)
    return ((path[-1][4] if path else entry) - entry) / risk


def events_abcd(data, day_of, hold, cost_fn, entry_ok=None, path_end=None):
    evs = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]) if None not in (o, h, l, c)]
        if len(rows) < 250:
            continue
        mrows = A.mirror(rows)
        for short in (False, True):
            ctx = None
            for dp in DOJI:
                ctx, sigs = A.signals(rows, day_of, doji_pct=dp, short=short, ctx=ctx)
                src = mrows if short else rows
                for s in sigs:
                    i = s["i"]
                    if entry_ok and not entry_ok(rows[i][0]):
                        continue
                    end = path_end(rows[i][0]) if path_end else None
                    path = [b for b in src[i + 1:i + 1 + hold] if end is None or b[0] < end]
                    if not path:
                        continue
                    ev = {"sym": sym, "day": rows[i][0].date().isoformat(), "i": i, "hour": rows[i][0].hour,
                          "side": s["side"], "doji": dp, "reclaimed": s["reclaimed"], "d_offset": s["d_offset"],
                          "trend": s["trend"], "out": {}}
                    sg = -1 if short else 1
                    for sm in STOPS:
                        stop = A.stop_for(s, sm)
                        risk = (s["entry"] - stop) * sg
                        if risk <= 0:
                            continue
                        for tg in TARGETS:
                            tp = A.target_for(ctx, s, tg, stop)
                            if tp is None:
                                continue
                            if tg == "internal" and abs(tp - s["entry"]) / risk < 1.0:
                                continue
                            r = _exit(path, sg * s["entry"], sg * stop, sg * tp,
                                      trail_atr=s["atr"] if tg == "trail" else None)
                            cost = cost_fn(sym, s["entry"], stop, s["entry"] if tg == "trail" else tp, s["side"])
                            if cost is None:
                                continue
                            ev["out"][(sm, tg)] = r - cost
                    if ev["out"]:
                        evs.append(ev)
    evs.sort(key=lambda e: (e["day"], e["sym"], e["i"]))
    return evs


def keep(ev, f):
    if f["side"] != "both" and ev["side"] != f["side"]:
        return False
    if ev["doji"] != f["doji"] or (f["stop"], f["target"]) not in ev["out"]:
        return False
    if f["reclaim"] and not ev["reclaimed"]:
        return False
    if ev["d_offset"] > f["dmax"]:
        return False
    if f["trend"] and not ev["trend"]:
        return False
    if f.get("session") == "active" and ev["hour"] < 6:
        return False
    return True


def score(events, f, split, stats, spacing):
    ins, oos, last, rs = {}, {}, {}, []
    k = (f["stop"], f["target"])
    for ev in events:
        if not keep(ev, f):
            continue
        if ev["sym"] in last and ev["i"] - last[ev["sym"]] < spacing:
            continue
        last[ev["sym"]] = ev["i"]
        (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["out"][k])
        rs.append(ev["out"][k])
    return {"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos), "rs": rs}


def row(r, label=""):
    f, i, o = r["filters"], r["in_sample"], r["out_of_sample"]

    def s(x):
        if not x.get("trades"):
            return "no trades"
        return "%4d tr (%.1f/day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
            x["worst_day_r"], x["max_drawdown_r"])
    parts = ["side=%s" % f["side"], "doji<=%d%%" % round(100 * f["doji"]),
             "B=%s" % ("close+reclaim" if f["reclaim"] else "close-below"), "D<=%d candles" % f["dmax"],
             "stop=%s" % f["stop"], "target=%s" % f["target"], "trend=%s" % ("EMA200" if f["trend"] else "off")]
    if "session" in f:
        parts.append("hours=%s" % f["session"])
    return "%s%s\n     in-sample   %s\n     OUT-sample  %s" % (label, " ".join(parts), s(i), s(o))


def concentration(r):
    rs = sorted(r.get("rs", []), reverse=True)
    tot = sum(rs)
    if len(rs) < 10 or tot <= 0:
        return "  concentration: not meaningful (total R not positive or under 10 trades)"
    top = sum(rs[:3])
    return "  concentration: the best 3 of %d trades = %.0f%% of the total %+.1fR%s" % (
        len(rs), 100 * top / tot, tot, "  <- a few lucky trades carry it" if top >= 0.6 * tot else "")


def main(a, syms, src, fetch_all, fetch, stats, out_dir, tz_local, market="crypto", step=15):
    import paper as P
    if market == "crypto":
        iv = "%dm" % step
        print("Fetching 60 days of %s bars for %d coins (%s)..." % (iv, len(syms), src), flush=True)
        data, _ = fetch_all(syms, "-USD", iv, a.workers)
        fee = float(P.load_config()["accounts"]["CRYPTO"]["fee_pct"]) / 100

        def cost_fn(sym, entry, stop, exit_px, side):
            return (entry + exit_px) * fee / abs(entry - stop)

        events = events_abcd(data, lambda t: t.date(), hold=12 * 60 // step, cost_fn=cost_fn)
        spacing, mode = 240 // step, "crypto-abcd" + ("" if step == 15 else "-%dm" % step)
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

        events = events_abcd(data, lambda t: t.astimezone(tz_local).date(), hold=75, cost_fn=cost_fn,
                             entry_ok=entry_ok, path_end=path_end)
        spacing, mode = 24, "nse-abcd"
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

        events = events_abcd(data, lambda t: t.astimezone(et).date(), hold=78, cost_fn=cost_fn,
                             entry_ok=entry_ok, path_end=path_end)
        spacing, mode = 24, "us-abcd"
        what = "%d US stocks/ETFs, 5m candles, intraday" % len(data)
        costs = "%.3f%% a side (paper fee + 0.02%% assumed spread/slippage)" % (fee * 100)
        grid_extra = {}

    if not events:
        print("No A-B-C-D entries found: no data came back (check the internet / Yahoo).")
        return 1
    grid = {"side": ["long", "short", "both"], "doji": list(DOJI), "reclaim": [False, True], "dmax": [2, 6, 12],
            "stop": list(STOPS), "target": list(TARGETS), "trend": [False, True], **grid_extra}
    pdf = dict(PDF) if market == "crypto" else {k: v for k, v in PDF.items() if k != "session"}
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    combos = list(itertools.product(*grid.values()))
    print("%d A-B-C-D entries; scoring %d combinations..." % (len(events), len(combos)), flush=True)
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

    longs = sum(1 for e in events if e["side"] == "long" and e["doji"] == 0.15)
    shorts = sum(1 for e in events if e["side"] == "short" and e["doji"] == 0.15)
    lines = ["research.py %s  %s" % (mode, datetime.now(tz_local).strftime("%Y-%m-%d %H:%M %Z")),
             "Owner's A-B-C-D entry (abcd.py): A bullish BOS/CHoCH -> B red candle closes below the first swing low "
             "-> C green doji -> D a later candle CLOSES above C-high. Shorts = the mirror image.",
             "%s, %d days (%s..%s). Entries found (doji 15%%): %d long, %d short. R after costs (%s). "
             "Out-of-sample = days from %s." % (what, len(days), days[0], days[-1], longs, shorts, costs, split), "",
             row(score(events, pdf, split, stats, spacing), "THE PDF AS WRITTEN (long, stop below C-low, 2R):  "),
             row(score(events, dict(pdf, reclaim=True), split, stats, spacing), "THE PDF + B RECLAIM:  "),
             row(score(events, dict(pdf, side="short"), split, stats, spacing), "THE MIRROR (short):  "), "",
             "WHICH INGREDIENT HELPS (average OUT-sample R of the combinations with it vs the alternative):",
             effect("reclaim", True, False), effect("doji", 0.25, 0.15), effect("dmax", 2, 12), effect("dmax", 6, 12),
             effect("stop", "sweep", "c_low"), effect("target", "trail", "2R"), effect("target", "internal", "2R"),
             effect("trend", True, False), effect("side", "short", "long")]
    if market == "crypto":
        lines.append(effect("session", "active", "all"))
    lines += ["", "TOP 10 BY IN-SAMPLE (the OUT-sample line is the honest one):"]
    for n, r in enumerate(ok[:10], 1):
        lines.append(row(r, "%2d. " % n))
    lines += ["", "%d of %d distinct combinations (with enough trades) were positive both in- and out-of-sample." % (
        len(stable), len(ok))]
    if stable:
        best = stable[0]
        lines += ["", "MOST CONSISTENT (best of its weaker half):", row(best, "  "), concentration(best), "",
                  "ITS NEIGHBOURS (one setting changed at a time; a robust rule has neighbours that also do well):"]
        for k, vals in grid.items():
            for v in vals:
                if v != best["filters"][k]:
                    lines.append(row(score(events, dict(best["filters"], **{k: v}), split, stats, spacing),
                                     "  %s=%s -> " % (k, v)))
    lines += ["", "Luck check: on random-walk test data some combinations look positive in both halves by chance alone",
              "(about 1% with crypto fees; about 10% with the low US costs). Trust a result only if its neighbours agree.",
              "Decision rule: put it live (paper) only if positive out-of-sample with 20+ trades and its neighbours",
              "mostly stay positive. ~60 days is short. Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report_%s.txt" % mode), "w", encoding="utf-8") as fh:
        fh.write(report)
    print("\nWrote %s" % os.path.join(out_dir, "report_%s.txt" % mode))
    return 0
