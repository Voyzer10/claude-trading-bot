#!/usr/bin/env python3
"""
research_scanner_v5.py - backtest of Scanner v5 (scanner_v5.py, the "0.146 level" from the owner's reel, 10 Nov 2026),
walk-forward 70/30, R after costs.

    python research.py crypto-sv5       # crypto, 15-minute candles
    python research.py crypto-sv5-5m    # crypto, 5-minute candles
    python research.py us-sv5           # US stocks, 5m, intraday
    python research.py nse-sv5          # NSE stocks, 5m, intraday (India charges)
    python research.py gold-sv5         # gold futures (GC=F), 5m - the reel's own market (XAUUSD 3m)

The question this answers first: is 0.146 - or ANY "famous" constant - special? C is measured from the move's START
(the reel's way: support = low + C x range after an up-move). A Fibonacci retracement r measured from the move's end
is the same level as C = 1 - r, so both are in the list. The famous constants (owner, 10 Nov 2026: "find the other
constants like it"):
  Fibonacci      0.146 (0.236 x 0.618), 0.236, 0.382, 0.5, 0.618, 0.786 (sqrt 0.618), 0.886 (sqrt 0.786), 0.65
                 (golden pocket) and their mirrors 1 - r: 0.854, 0.764, 0.214, 0.114, 0.35
  ICT OTE        0.62, 0.705, 0.79 (and 0.5 equilibrium): mirrors 0.38, 0.295, 0.21
  Gann / Murrey  eighths 0.125, 0.25, 0.375, 0.625, 0.75, 0.875 and thirds 0.333, 0.667
  geometry       0.707 (1 / sqrt 2)
CONTROLS: 0.18, 0.27, 0.44, 0.56 - numbers no one uses. If the famous constants do not beat the controls out of sample,
their "exact" levels are hindsight. Testing ~30 constants also means the best one can win by luck: trust a constant only
if it AND its neighbours are positive out of sample, in more than one market. Then: which move (the last swing, or today's low -> high), which target (the move's other end, or 2R).
"Live" = what Scanner v5 paper trades: C 0.146, swing move, target the move's end, both sides.
"""
import itertools
import os
from datetime import datetime, timezone

import scanner_v5 as V5

UTC = timezone.utc
FAMOUS = {
    0.114: "fib 0.886 retrace", 0.125: "Gann 1/8", 0.146: "fib 0.146 (the reel)", 0.214: "fib 0.786 retrace",
    0.21: "ICT 0.79", 0.236: "fib 0.236", 0.25: "Gann 2/8", 0.295: "ICT OTE 0.705", 0.333: "1/3", 0.35: "golden pocket 0.65",
    0.375: "Gann 3/8", 0.38: "ICT 0.62", 0.382: "fib 0.382 / 0.618 retrace", 0.5: "half / equilibrium",
    0.618: "fib 0.618 / 0.382 retrace", 0.625: "Gann 5/8", 0.667: "2/3", 0.705: "ICT 0.705 mirror", 0.707: "1/sqrt 2",
    0.75: "Gann 6/8", 0.764: "fib 0.236 retrace", 0.786: "fib 0.786", 0.854: "fib 0.146 retrace", 0.875: "Gann 7/8",
    0.886: "fib 0.886"}
CONTROLS = {0.18: "control", 0.27: "control", 0.44: "control", 0.56: "control"}
NAMES = {**FAMOUS, **CONTROLS}
CONSTANTS = sorted(NAMES)
MOVES = ["swing", "day"]
TARGETS = ["leg", "2R"]
LIVE = {"side": "both", "c": 0.146, "move": "swing", "target": "leg"}


def events_v5(data, day_of, cost_fn, intraday=False, max_hold=48, entry_ok=None):
    evs = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]) if None not in (o, h, l, c)]
        if len(rows) < 250:
            continue
        ctxs = V5.contexts(rows, day_of)
        for c, mv, tg in itertools.product(CONSTANTS, MOVES, TARGETS):
            try:
                seq = V5.sequence(rows, day_of, intraday=intraday, ctxs=ctxs, c=c, move=mv, target=tg,
                                  max_hold=max_hold)
            except Exception:
                continue
            for t in seq:
                if t.get("exit") is None or (entry_ok and not entry_ok(rows[t["i"]][0])):
                    continue
                sg = 1 if t["side"] == "long" else -1
                risk = (t["entry"] - t["stop"]) * sg
                if risk <= 0:
                    continue
                cost = cost_fn(sym, t["entry"], t["stop"], t["exit"], t["side"])
                if cost is None:
                    continue
                evs.append({"sym": sym, "day": day_of(rows[t["i"]][0]).isoformat(), "i": t["i"], "side": t["side"],
                            "c": c, "move": mv, "target": tg, "r": (t["exit"] - t["entry"]) * sg / risk - cost,
                            "exit_reason": t["exit_reason"]})
    evs.sort(key=lambda e: (e["day"], e["sym"], e["i"]))
    return evs


def keep(ev, f):
    return (f["side"] == "both" or ev["side"] == f["side"]) and ev["c"] == f["c"] and ev["move"] == f["move"] \
        and ev["target"] == f["target"]


def score(events, f, split, stats):
    ins, oos = {}, {}
    for ev in events:
        if keep(ev, f):
            (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["r"])
    return {"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos)}


def _s(x):
    if not x.get("trades"):
        return "no trades"
    return "%4d tr (%.1f/day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
        x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
        x["worst_day_r"], x["max_drawdown_r"])


def row(r, label=""):
    f = r["filters"]
    return "%sC=%g move=%s target=%s side=%s\n     in-sample   %s\n     OUT-sample  %s" % (
        label, f["c"], f["move"], f["target"], f["side"], _s(r["in_sample"]), _s(r["out_of_sample"]))


def report(events, mode, what, costs, stats, tz_local):
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    live = score(events, LIVE, split, stats)
    lines = ["research.py %s  %s" % (mode, datetime.now(tz_local).strftime("%Y-%m-%d %H:%M %Z")),
             "Scanner v5 (the 0.146 level): after a move, the level C x range short of its extreme; a candle touches it "
             "and closes back on the right side -> entry; stop beyond the extreme; target the other end of the move "
             "(or 2R). Shorts = mirror.",
             "%s, %d days (%s..%s). R after costs (%s). Out-of-sample = days from %s." % (
                 what, len(days), days[0], days[-1], costs, split), "",
             row(live, "LIVE (what Scanner v5 paper trades):  "),
             row(score(events, dict(LIVE, side="long"), split, stats), "LIVE, longs only:  "),
             row(score(events, dict(LIVE, side="short"), split, stats), "LIVE, shorts only:  "), "",
             "IS ANY CONSTANT SPECIAL? Same rules, only C changes (both sides). OUT-OF-SAMPLE avg R per trade (trades);"
             " target = the move's end where reward:risk allows it (C < 0.5), else 2R:",
             "  %-7s %-26s %-18s %-18s %-18s %-18s" % ("C", "what", "swing / move end", "swing / 2R", "day / move end",
                                                         "day / 2R")]
    by_c = {}

    def cell(o):
        return "%+.2fR (%d)" % (o["avg_r"], o["trades"]) if o.get("trades") else "-"
    for c in CONSTANTS:
        cells = []
        for mv in MOVES:
            for tg in TARGETS:
                o = score(events, {"side": "both", "c": c, "move": mv, "target": tg}, split, stats)["out_of_sample"]
                by_c[(mv, tg, c)] = o
                cells.append(cell(o))
        lines.append("  %-7g %-26s %-18s %-18s %-18s %-18s" % (c, NAMES[c], *cells))

    def group_avg(group):
        rs = [by_c[(mv, tg, c)]["avg_r"] for c in group for mv in MOVES for tg in TARGETS
              if by_c[(mv, tg, c)].get("trades", 0) >= 10]
        return (sum(rs) / len(rs), len(rs)) if rs else (None, 0)
    fa, fn = group_avg(FAMOUS)
    ca, cn = group_avg(CONTROLS)
    lines.append("  famous constants: avg %s over %d settings;  controls (no one uses them): avg %s over %d settings -> %s" % (
        "%+.2fR" % fa if fa is not None else "-", fn, "%+.2fR" % ca if ca is not None else "-", cn,
        "the famous ones are NOT better than random numbers" if fa is None or ca is None or fa <= ca + 0.05
        else "the famous ones beat the controls by %.2fR (check it holds in the other markets)" % (fa - ca)))
    lines += ["", "TARGET: the move's other end vs 2R (C=0.146, swing):",
              row(score(events, dict(LIVE, target="2R"), split, stats), "  ")]
    grid = {"side": ["long", "short", "both"], "c": CONSTANTS, "move": MOVES, "target": TARGETS}
    res = [score(events, dict(zip(grid, k)), split, stats) for k in itertools.product(*grid.values())]
    res = [r for r in res if r["in_sample"].get("trades", 0) >= 20 and r["out_of_sample"].get("trades", 0) >= 10]
    res.sort(key=lambda r: -r["in_sample"]["avg_r"])
    lines += ["", "TOP 10 BY IN-SAMPLE (the OUT-sample line is the honest one):"]
    for n, r in enumerate(res[:10], 1):
        lines.append(row(r, "%2d. " % n))
    good = [r for r in res if r["in_sample"]["avg_r"] > 0 and r["out_of_sample"]["avg_r"] > 0]
    lv = live["out_of_sample"]
    oos_c = {c: by_c[("swing", "leg", c)].get("avg_r") for c in CONSTANTS
             if by_c[("swing", "leg", c)].get("trades", 0) >= 10}
    best_c = max(oos_c, key=oos_c.get) if oos_c else None
    special = best_c == 0.146 and all(oos_c[0.146] - v >= 0.05 for c, v in oos_c.items() if c != 0.146)
    pos = sorted(c for c, v in oos_c.items() if v > 0)
    lines += ["", "%d of %d combinations (with enough trades) positive both in- and out-of-sample." % (len(good), len(res)),
              "0.146 (swing, move end, out of sample): %s; best constant there: %s -> %s" % (
                  "%+.2fR" % oos_c[0.146] if 0.146 in oos_c else "too few trades",
                  "%g (%s, %+.2fR)" % (best_c, NAMES[best_c], oos_c[best_c]) if best_c is not None else "-",
                  "0.146 is clearly the best" if special else "0.146 is NOT clearly better than the others"),
              "Positive out of sample (swing, move end): %s. A real level shows as a run of neighbours, not one number." % (
                  ", ".join("%g" % c for c in pos) or "none"),
              "VERDICT: " + (("PASS: the live setting is positive out of sample (%+.2fR a trade over %d trades). Small "
                              "sample: paper trade it and keep checking." % (lv["avg_r"], lv["trades"]))
                             if lv.get("trades", 0) >= 20 and lv["avg_r"] > 0 else
                             "FAIL: no edge out of sample for the live setting (%s). Do not switch an account to v5." % (
                                 "%+.2fR a trade over %d trades" % (lv["avg_r"], lv["trades"]) if lv.get("trades")
                                 else "no trades"))]
    return "\n".join(lines)


def main(a, syms, src, fetch_all, stats, out_dir, tz_local, market="crypto", step=15):
    import paper as P
    entry_ok, intraday, max_hold = None, False, 48
    if market == "crypto":
        iv = "%dm" % step
        print("Fetching 60 days of %s bars for %d coins (%s)..." % (iv, len(syms), src), flush=True)
        data, _ = fetch_all(syms, "-USD", iv, a.workers)
        fee = float(P.load_config()["accounts"]["CRYPTO"]["fee_pct"]) / 100

        def cost_fn(sym, entry, stop, exit_px, side):
            return (entry + exit_px) * fee / abs(entry - stop)
        day_of, max_hold = (lambda t: t.date()), 12 * 60 // step
        mode = "crypto-sv5" + ("" if step == 15 else "-%dm" % step)
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
        day_of, intraday, max_hold = (lambda t: t.astimezone(tz_local).date()), True, 75
        mode, what = "nse-sv5", "%d NSE stocks, 5m candles, intraday" % len(data)
        costs = "paper.py India charges (STT, brokerage, ...)"
    else:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        gold = market == "gold"
        print("Fetching 60 days of 5-minute bars for %d %s symbols (%s)..." % (len(syms), "gold" if gold else "US", src),
              flush=True)
        data, _ = fetch_all(syms, "", "5m", a.workers)
        fee = 0.0002 if gold else float(P.load_config()["accounts"]["US"].get("fee_pct", 0)) / 100 + 0.0002

        def cost_fn(sym, entry, stop, exit_px, side):
            return (entry + exit_px) * fee / abs(entry - stop)
        if gold:
            day_of, max_hold = (lambda t: t.astimezone(et).date()), 48
            mode, what = "gold-sv5", "gold futures (GC=F), 5m candles, 4h max hold"
        else:
            def entry_ok(t):
                lt = t.astimezone(et)
                return (9, 45) <= (lt.hour, lt.minute) <= (15, 30)
            day_of, intraday, max_hold = (lambda t: t.astimezone(et).date()), True, 78
            mode, what = "us-sv5", "%d US stocks/ETFs, 5m candles, intraday" % len(data)
        costs = "%.3f%% a side (fee + assumed spread/slippage)" % (fee * 100)
    events = events_v5(data, day_of, cost_fn, intraday=intraday, max_hold=max_hold, entry_ok=entry_ok)
    if not events:
        print("No Scanner v5 trades found: no data came back (check the internet / Yahoo).")
        return 1
    text = report(events, mode, what, costs, stats, tz_local)
    print(text)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s_%s.txt" % (mode, datetime.now(tz_local).strftime("%Y%m%d_%H%M")))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\nSaved: %s" % path)
    return 0
