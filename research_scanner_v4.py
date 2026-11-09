#!/usr/bin/env python3
"""
research_scanner_v4.py - backtest of Scanner v4 (scanner_v4.py, the owner's 7 Nov final workflow), walk-forward 70/30,
R after costs. The engine's own sequence is replayed on every chart: a primary trade, and only after it closed an
OB / FVG secondary, then reset - exactly what the live scanner does.

    python research.py crypto-sv4       # crypto, 15-minute candles (12h max hold)
    python research.py crypto-sv4-5m    # crypto, 5-minute candles
    python research.py us-sv4           # US stocks, 5m, intraday (closed at the day's last candle)
    python research.py nse-sv4          # NSE stocks, 5m, intraday

Grid (small on purpose): side (long, short, both) x trades (primary only, primary + secondary, secondary only) x
min R:R (1, 2) x the PDF's skip rules (all on = live, all off, or one of them off: higher-timeframe trend, chop,
BOS body + volume, nearby opposing zone) [x hours for crypto]. "Live" = what Scanner v4 paper trades: both sides,
primary + secondary, R:R >= 1, every skip rule on.
"""
import itertools
import os
from datetime import datetime, timezone

import research_abcd as RA
import scanner_v4 as V4

UTC = timezone.utc
FILTERS = {"all": {}, "none": {"htf": False, "chop_er": 0, "bos_body_atr": 0, "bos_vol_x": 0, "opp_zone": False},
           "no_htf": {"htf": False}, "no_chop": {"chop_er": 0}, "no_bos_quality": {"bos_body_atr": 0, "bos_vol_x": 0},
           "no_opp_zone": {"opp_zone": False}}
VARIANTS = [(rr, f) for rr in (1.0, 2.0) for f in FILTERS]
LIVE = {"side": "both", "trades": "both", "min_rr": 1.0, "filters": "all", "session": "all"}


def events_v4(data, day_of, cost_fn, intraday=False, max_hold=48, entry_ok=None):
    evs = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]) if None not in (o, h, l, c)]
        if len(rows) < 250:
            continue
        for rr, fname in VARIANTS:
            try:
                seq = V4.sequence(rows, day_of, intraday=intraday, min_rr=rr, max_hold=max_hold, **FILTERS[fname])
            except Exception:
                continue
            for t in seq:
                if t.get("exit") is None:
                    continue
                if entry_ok and not entry_ok(rows[t["i"]][0]):
                    continue
                sg = 1 if t["side"] == "long" else -1
                risk = (t["entry"] - t["stop"]) * sg
                if risk <= 0:
                    continue
                cost = cost_fn(sym, t["entry"], t["stop"], t["exit"], t["side"])
                if cost is None:
                    continue
                evs.append({"sym": sym, "day": rows[t["i"]][0].date().isoformat(), "i": t["i"],
                            "hour": rows[t["i"]][0].hour, "side": t["side"], "kind": t["kind"], "min_rr": rr,
                            "filters": fname, "r": (t["exit"] - t["entry"]) * sg / risk - cost,
                            "exit_reason": t["exit_reason"]})
    evs.sort(key=lambda e: (e["day"], e["sym"], e["i"]))
    return evs


def keep(ev, f):
    if f["side"] != "both" and ev["side"] != f["side"]:
        return False
    if f["trades"] != "both" and ev["kind"] != f["trades"]:
        return False
    if ev["min_rr"] != f["min_rr"] or ev["filters"] != f["filters"]:
        return False
    if f.get("session") == "active" and ev["hour"] < 6:
        return False
    return True


def score(events, f, split, stats):
    ins, oos, rs = {}, {}, []
    for ev in events:
        if keep(ev, f):
            (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["r"])
            rs.append(ev["r"])
    return {"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos), "rs": rs}


def row(r, label=""):
    f, i, o = r["filters"], r["in_sample"], r["out_of_sample"]

    def s(x):
        if not x.get("trades"):
            return "no trades"
        return "%4d tr (%.1f/day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
            x["worst_day_r"], x["max_drawdown_r"])
    parts = ["side=%s" % f["side"], "trades=%s" % f["trades"], "min_rr=%g" % f["min_rr"], "skip_rules=%s" % f["filters"]]
    if "session" in f:
        parts.append("hours=%s" % f["session"])
    return "%s%s\n     in-sample   %s\n     OUT-sample  %s" % (label, " ".join(parts), s(i), s(o))


def main(a, syms, src, fetch_all, fetch, stats, out_dir, tz_local, market="crypto", step=15):
    import paper as P
    entry_ok = None
    if market == "crypto":
        iv = "%dm" % step
        print("Fetching 60 days of %s bars for %d coins (%s)..." % (iv, len(syms), src), flush=True)
        data, _ = fetch_all(syms, "-USD", iv, a.workers)
        fee = float(P.load_config()["accounts"]["CRYPTO"]["fee_pct"]) / 100

        def cost_fn(sym, entry, stop, exit_px, side):
            return (entry + exit_px) * fee / abs(entry - stop)
        events = events_v4(data, lambda t: t.date(), cost_fn, max_hold=None)   # PDF: TP / SL only, no time stop
        mode = "crypto-sv4" + ("" if step == 15 else "-%dm" % step)
        what, costs = "%d coins, %s candles, exits at TP / SL only (the PDF)" % (len(data), iv), \
            "%.3f%% fee a side" % (fee * 100)
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
        events = events_v4(data, lambda t: t.astimezone(tz_local).date(), cost_fn, intraday=True, max_hold=75,
                           entry_ok=entry_ok)
        mode, what = "nse-sv4", "%d NSE stocks, 5m candles, intraday" % len(data)
        costs, grid_extra = "paper.py India charges (STT, brokerage, ...)", {}
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
        events = events_v4(data, lambda t: t.astimezone(et).date(), cost_fn, intraday=True, max_hold=78,
                           entry_ok=entry_ok)
        mode, what = "us-sv4", "%d US stocks/ETFs, 5m candles, intraday" % len(data)
        costs = "%.3f%% a side (paper fee + 0.02%% assumed spread/slippage)" % (fee * 100)
        grid_extra = {}

    if not events:
        print("No Scanner v4 trades found: no data came back (check the internet / Yahoo).")
        return 1
    grid = {"side": ["long", "short", "both"], "trades": ["primary", "secondary", "both"], "min_rr": [1.0, 2.0],
            "filters": list(FILTERS), **grid_extra}
    live = dict(LIVE) if market == "crypto" else {k: v for k, v in LIVE.items() if k != "session"}
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    res = [score(events, dict(zip(grid, c)), split, stats) for c in itertools.product(*grid.values())]
    ok, seen = [], set()
    for r in res:
        if r["in_sample"].get("trades", 0) < 20 or r["out_of_sample"].get("trades", 0) < 10:
            continue
        sig = (r["in_sample"]["trades"], r["in_sample"]["total_r"], r["out_of_sample"]["trades"], r["out_of_sample"]["total_r"])
        if sig not in seen:
            seen.add(sig)
            ok.append(r)
    ok.sort(key=lambda r: -r["in_sample"]["avg_r"])
    stable = sorted([r for r in ok if r["in_sample"]["avg_r"] > 0 and r["out_of_sample"]["avg_r"] > 0],
                    key=lambda r: -min(r["in_sample"]["avg_r"], r["out_of_sample"]["avg_r"]))
    base = [e for e in events if e["min_rr"] == 1.0 and e["filters"] == "all"]
    n_p = sum(1 for e in base if e["kind"] == "primary")
    exits = {}
    for e in base:
        exits[e["exit_reason"]] = exits.get(e["exit_reason"], 0) + 1
    lines = ["research.py %s  %s" % (mode, datetime.now(tz_local).strftime("%Y-%m-%d %H:%M %Z")),
             "Scanner v4 (scanner_v4.py, the owner's 7 Nov final workflow): PRIMARY = BOS -> sweep of an old low/high that "
             "is reclaimed -> doji / hammer / inverted hammer -> break-and-close; SECONDARY = only after the primary "
             "closed: OB / FVG of that move tapped, then break-and-close. One sequence per chart. Shorts = mirror.",
             "%s, %d days (%s..%s). Live-reading trades: %d primary, %d secondary; exits %s. R after costs (%s). "
             "Out-of-sample = days from %s." % (what, len(days), days[0], days[-1], n_p, len(base) - n_p, exits, costs,
                                                split), "",
             row(score(events, live, split, stats), "LIVE (what Scanner v4 paper trades):  "),
             row(score(events, dict(live, trades="primary"), split, stats), "LIVE, primary trades only:  "),
             row(score(events, dict(live, trades="secondary"), split, stats), "LIVE, secondary (OB/FVG) only:  "),
             row(score(events, dict(live, side="long"), split, stats), "LIVE, longs only:  "),
             row(score(events, dict(live, side="short"), split, stats), "LIVE, shorts only:  "), "",
             "THE PDF'S SKIP RULES (live setting, one rule switched off at a time; trades/day shows how much each cuts):"]
    for fname in FILTERS:
        if fname != "all":
            lines.append(row(score(events, dict(live, filters=fname), split, stats), "  skip_rules=%s -> " % fname))
    lines += ["",
             "TOP 10 BY IN-SAMPLE (the OUT-sample line is the honest one):"]
    for n, r in enumerate(ok[:10], 1):
        lines.append(row(r, "%2d. " % n))
    lines += ["", "%d of %d distinct combinations (with enough trades) were positive both in- and out-of-sample." % (
        len(stable), len(ok))]
    if stable:
        best = stable[0]
        lines += ["", "MOST CONSISTENT:", row(best, "  "), RA.concentration(best), "", "ITS NEIGHBOURS:"]
        for k, vals in grid.items():
            for v in vals:
                if v != best["filters"][k]:
                    lines.append(row(score(events, dict(best["filters"], **{k: v}), split, stats), "  %s=%s -> " % (k, v)))
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
