#!/usr/bin/env python3
"""
research.py - backtest the breakout rules on ~60 days of real 5/15-minute bars, try every filter
combination, and check the winners on days they were NOT chosen on (walk-forward).

    python research.py nse                # Nifty 500 (trader/universe_nse.txt), 60 days of 5m bars
    python research.py nse --limit 100    # faster: the first 100 symbols
    python research.py crypto             # trader/universe_crypto.txt, 60 days of 15m bars
    python research.py crypto-5m          # the same rule on 5-minute bars (4h and 1h ranges)
    python research.py crypto-live        # the live rule with live entry timing: close vs +1 min vs +5 min
    python research.py nse-v2             # NSE opening range v2: wider stops (range low, ATR), trailing exit,
                                          # charges cap in R, 15/30-minute ranges (research_nse2.py)
    python research.py crypto-smc         # Smart Money "liquidity sweep and reclaim" vs the live breakout rule
    python research.py crypto-v4-5m       # the same v4 report on 5-minute candles (compare with crypto-v4)
    python research.py crypto-v4-short    # the same v4 grid for SHORTS (4h breakdowns), incl. trailing exits
    python research.py crypto-v4          # "pro" breakout setup: trend, squeeze, session, ATR stop, partial/trailing exits

Bars are cached in trader/research/cache/ (delete it to refetch). Reports:
trader/research/report_<mode>.txt and .json.

How it scores a trade (same rules as the live pipeline):
  NSE     15-minute opening range from 9:15; the first 5-minute close above it is the entry (one per
          stock per day); stop at the range midpoint; target N x risk; optional breakeven at +1R;
          flat by 15:15. Charges: paper.py's india_charges, size as the live INDIA account would.
  crypto  a fresh 15-minute close above the prior 4-hour high; stop at the 4-hour range midpoint;
          target N x risk; optional breakeven; time stop after 6 hours; 0.1% fee each side.
  Inside one bar that touches both the stop and the target, the stop counts (cautious).

Walk-forward: the first 70% of the days choose the best combinations ("in-sample"); the last 30%
("out-of-sample") show how they did on days they never saw. Trust out-of-sample, not in-sample:
with ~1,000 combinations, the in-sample best is always flattered by luck.
A backtest is history, not a promise. Not financial advice.
"""
import argparse
import bisect
import itertools
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import paper as P
import scan_nse as S

OUT = os.path.join("trader", "research")
CACHE = os.path.join(OUT, "cache")
IST = S.IST
UTC = timezone.utc


# ------------------------------------------------------------------ data

def fetch(sym, suffix, interval, workers_note=""):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "%s%s_%s.json" % (sym.replace("^", "_"), suffix, interval))
    if os.path.exists(path) and (datetime.now().timestamp() - os.path.getmtime(path)) < 12 * 3600:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    d = S.yahoo_chart(sym, "60d", interval, suffix)
    if d:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
    return d


def fetch_all(syms, suffix, interval, workers):
    data, failed = {}, []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch, s, suffix, interval): s for s in syms}
        for i, f in enumerate(as_completed(futs), 1):
            s = futs[f]
            try:
                d = f.result()
                if d and d["t"]:
                    data[s] = d
                else:
                    failed.append(s)
            except Exception:
                failed.append(s)
            if i % 50 == 0:
                print("  fetched %d of %d" % (i, len(syms)), flush=True)
    return data, failed


def bars_by_day(d, tz, step):
    days = {}
    for t, o, h, l, c, v in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]):
        st = datetime.fromtimestamp(t, tz)
        if st.minute % step or st.second:
            continue
        days.setdefault(st.date(), []).append((st, o, h, l, c, v))
    return {k: sorted(v) for k, v in days.items()}


# ------------------------------------------------------------------ outcome

def outcome(path, entry, stop, target_r, breakeven, cost_r, end_close=None):
    """R of a long trade over `path` bars (st,o,h,l,c,v); exits at the last close if nothing hits."""
    risk = entry - stop
    target = entry + target_r * risk
    cur_stop, be_on = stop, False
    for b in path:
        if b[3] <= cur_stop:
            r = (cur_stop - entry) / risk
            return r - cost_r, ("breakeven" if be_on else "stop")
        if b[2] >= target:
            return target_r - cost_r, "target"
        if breakeven and not be_on and b[2] >= entry + risk:
            cur_stop, be_on = entry, True  # applies from the next bar
    last = path[-1][4] if path else entry
    return (last - entry) / risk - cost_r, "time"


# ------------------------------------------------------------------ NSE events

def nse_events(data, nifty):
    cfg = P.DEFAULT_CONFIG
    acc = cfg["accounts"]["INDIA"]
    nday = bars_by_day(nifty, IST, 5) if nifty else {}
    events = []
    for sym, d in data.items():
        days = bars_by_day(d, IST, 5)
        prev_close = None
        for day in sorted(days):
            bars = days[day]
            o_start = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST)
            rng = [b for b in bars if o_start <= b[0] < o_start + timedelta(minutes=15)]
            if len(rng) < 3:
                prev_close = bars[-1][4]
                continue
            hi, lo = max(b[2] for b in rng), min(b[3] for b in rng)
            mid = (hi + lo) / 2
            after = [b for b in bars if b[0] >= o_start + timedelta(minutes=15)]
            flat = o_start.replace(hour=15, minute=15)
            for i, b in enumerate(after):
                if b[0] + timedelta(minutes=5) > o_start.replace(hour=14, minute=30):
                    break
                if b[4] <= hi:
                    continue
                entry, end = b[4], b[0] + timedelta(minutes=5)
                risk = entry - mid
                if risk <= 0:
                    break
                prior = (rng + after[:i])[-6:]
                base = sum(x[5] for x in prior) / len(prior)
                vol_x = b[5] / base if base else 0.0
                gap = (bars[0][1] / prev_close - 1) * 100 if prev_close else 0.0
                regime = None
                nb = nday.get(day)
                if nb:
                    nr = [x for x in nb if o_start <= x[0] < o_start + timedelta(minutes=15)]
                    upto = [x for x in nb if x[0] + timedelta(minutes=5) <= end]
                    if nr and upto:
                        nmid = (max(x[2] for x in nr) + min(x[3] for x in nr)) / 2
                        regime = upto[-1][4] > nmid and upto[-1][4] > nb[0][1]
                qty = max(1, int(min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / entry)))
                path = [x for x in after[i + 1:] if x[0] < flat]
                ev = {"sym": sym, "day": day.isoformat(), "time": end.strftime("%H:%M"), "vol_x": vol_x,
                      "gap": gap, "regime": regime, "stop_pct": risk / entry * 100, "out": {}}
                for tr in (1.0, 1.5, 2.0):
                    cost = (P.charges(cfg, "NSE", sym, "buy", qty * entry) +
                            P.charges(cfg, "NSE", sym, "sell", qty * (entry + tr * risk))) / (qty * risk)
                    for be in (False, True):
                        ev["out"][(tr, be)] = outcome(path, entry, mid, tr, be, cost)[0]
                events.append(ev)
                break  # one trade per stock per day
            prev_close = bars[-1][4]
    add_history(events)
    return events


# ------------------------------------------------------------------ crypto events

def crypto_events(data, btc, short=False, step=15, rb=16, hold=24, tag=None):
    """Fresh breakouts of the prior `rb` bars (long) or, with short=True, fresh breakdowns traded short: the
    bars are mirrored (price -> -price) so the same long-only rule and outcome() score the short.
    Defaults = the live rule: 15-minute bars, 4h range (16 bars), 6h hold (24 bars). step/rb/hold let the
    same rule run on 5-minute bars (crypto-5m)."""
    day_bars = 1440 // step
    btc_close = {}
    if btc:
        for t, c in zip(btc["t"], btc["c"]):
            btc_close[t] = c
    bt = sorted(btc_close)
    events = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"])
                if not datetime.fromtimestamp(t, UTC).minute % step]
        if short:
            rows = [mirror(r) for r in rows]
        i = rb + 1
        while i < len(rows) - hold:
            hi = max(r[2] for r in rows[i - rb:i])
            lo = min(r[3] for r in rows[i - rb:i])
            prev_hi = max(r[2] for r in rows[i - rb - 1:i - 1])
            if not (rows[i][4] > hi and rows[i - 1][4] <= prev_hi):
                i += 1
                continue
            entry, mid = rows[i][4], (hi + lo) / 2
            risk = entry - mid
            if risk <= 0:
                i += 1
                continue
            avg_v = sum(r[5] for r in rows[i - rb:i]) / rb
            ts = int(rows[i][0].timestamp())
            regime = btc_trend = None
            if bt:
                j = bisect.bisect_right(bt, ts)
                k = bt[max(0, j - rb - 1):j]
                if len(k) > rb:
                    w = [btc_close[x] for x in k]
                    up = w[-1] > (max(w[:-1]) + min(w[:-1])) / 2
                    regime = (not up) if short else up   # "with the trade": BTC weak for a short
                k = bt[max(0, j - day_bars):j]
                if len(k) == day_bars:  # BTC vs its own 24-hour average: the bigger trend
                    w = [btc_close[x] for x in k]
                    above = w[-1] > sum(w) / day_bars
                    btc_trend = (not above) if short else above
            coin_trend = None
            if i >= day_bars:  # the coin vs its own 24-hour average (rows are mirrored for shorts: "with the trade")
                coin_trend = rows[i][4] > sum(r[4] for r in rows[i - day_bars:i]) / day_bars
            ev = {"sym": sym, "day": rows[i][0].date().isoformat(), "time": rows[i][0].strftime("%H:%M"),
                  "vol_x": rows[i][5] / avg_v if avg_v else 0.0, "gap": 0.0, "regime": regime,
                  "stop_pct": risk / abs(entry) * 100, "hour": rows[i][0].hour, "out": {},
                  "btc_trend": btc_trend, "coin_trend": coin_trend, "range": tag,
                  "_end": ts + step * 60, "_hi": hi, "_mid": mid, "_entry": entry}
            path = rows[i + 1:i + 1 + hold]
            fill_outcomes(ev, path, entry, mid)
            events.append(ev)
            i += hold  # one trade at a time per coin
    events.sort(key=lambda e: (e["day"], e["time"]))
    add_history(events)
    return events


STOP_FLOOR = 1.0  # % : "widen" mode moves a tighter stop out to this distance instead of skipping the trade


def fill_outcomes(ev, path, entry, stop, targets=(1.0, 1.5, 2.0, 3.0), fee=0.001):
    """R for every target / breakeven combination, with the rule's own stop (out) and with the stop
    widened to STOP_FLOOR % when it was tighter (out_w). Fee is per side, as a fraction."""
    risk = entry - stop
    wrisk = max(risk, abs(entry) * STOP_FLOOR / 100)
    ev["out"], ev["out_w"] = {}, {}
    for tr in targets:
        for be in (False, True):
            ev["out"][(tr, be)] = outcome(path, entry, stop, tr, be,
                                          (2 * abs(entry) + tr * risk) * fee / risk)[0]
            ev["out_w"][(tr, be)] = outcome(path, entry, entry - wrisk, tr, be,
                                            (2 * abs(entry) + tr * wrisk) * fee / wrisk)[0]


def mr_events(data, btc):
    """Oversold bounce for sideways markets: 15-minute RSI(14) was under 30 on the previous candle and
    this candle closes up. Long at the close; stop under the lowest low of the last 4 candles; target
    N x risk; time stop after 6 hours. One trade at a time per coin."""
    rb, hold = 16, 24
    btc_close = {t: c for t, c in zip(btc["t"], btc["c"])} if btc else {}
    bt = sorted(btc_close)
    events = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"])
                if not datetime.fromtimestamp(t, UTC).minute % 15]
        closes = [r[4] for r in rows]
        i = 60
        while i < len(rows) - hold:
            _, rsi_prev = S.rsi14(closes[i - 50:i])
            if rsi_prev is None or rsi_prev >= 30 or not closes[i] > closes[i - 1]:
                i += 1
                continue
            entry = closes[i]
            stop = min(r[3] for r in rows[i - 3:i + 1])
            if entry - stop <= 0:
                i += 1
                continue
            avg_v = sum(r[5] for r in rows[i - rb:i]) / rb
            ts = int(rows[i][0].timestamp())
            regime = btc_trend = None
            if bt:
                j = bisect.bisect_right(bt, ts)
                k = bt[max(0, j - rb - 1):j]
                if len(k) > rb:
                    w = [btc_close[x] for x in k]
                    regime = w[-1] > (max(w[:-1]) + min(w[:-1])) / 2
                k = bt[max(0, j - 96):j]
                if len(k) == 96:
                    w = [btc_close[x] for x in k]
                    btc_trend = w[-1] > sum(w) / 96
            ev = {"sym": sym, "day": rows[i][0].date().isoformat(), "time": rows[i][0].strftime("%H:%M"),
                  "vol_x": rows[i][5] / avg_v if avg_v else 0.0, "gap": 0.0, "regime": regime,
                  "stop_pct": (entry - stop) / entry * 100, "hour": rows[i][0].hour,
                  "btc_trend": btc_trend, "coin_trend": None, "rsi_prev": rsi_prev}
            fill_outcomes(ev, rows[i + 1:i + 1 + hold], entry, stop)
            events.append(ev)
            i += hold
    events.sort(key=lambda e: (e["day"], e["time"]))
    add_history(events)
    return events


def add_history(events):
    """Each event's stock-own track record of the same rule BEFORE that day (the live time machine's view)."""
    events.sort(key=lambda e: (e["day"], e["time"]))
    past = {}
    for ev in events:
        for name in ("out", "out_w"):
            if name not in ev:
                continue
            hk = "hist" if name == "out" else "hist_w"
            ev[hk] = {}
            for k in ev[name]:
                p = past.get((ev["sym"], name, k), [])
                prior = [r for d, r in p if d < ev["day"]]
                ev[hk][k] = (len(prior), sum(prior) / len(prior) if prior else None)
        for name in ("out", "out_w"):
            for k, r in ev.get(name, {}).items():
                past.setdefault((ev["sym"], name, k), []).append((ev["day"], r))


# ------------------------------------------------------------------ grid

def stats(rs_by_day):
    rs = [r for day in sorted(rs_by_day) for r in rs_by_day[day]]
    if not rs:
        return {"trades": 0}
    eq, peak, dd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    daily = [sum(v) for v in rs_by_day.values()]
    return {"trades": len(rs), "days_traded": len(rs_by_day), "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 3),
            "avg_r": round(sum(rs) / len(rs), 3), "total_r": round(sum(rs), 2), "worst_day_r": round(min(daily), 2),
            "losing_days": sum(1 for x in daily if x < 0), "max_drawdown_r": round(dd, 2)}


def run_grid(events, grid, split_day, max_per_day):
    results = []
    keys = list(grid)
    for combo in itertools.product(*[grid[k] for k in keys]):
        f = dict(zip(keys, combo))
        k = (f["target_r"], f["breakeven"])
        ins, oos = {}, {}
        count = {}
        widen = f.get("stop_mode") == "widen"
        outk, histk = ("out_w", "hist_w") if widen else ("out", "hist")
        for ev in events:
            if ev["time"] > f["entry_end"] or ev["vol_x"] < f["min_vol_x"]:
                continue
            if "range" in f and ev.get("range") != f["range"]:
                continue
            if not widen and ev["stop_pct"] < f["min_stop_pct"]:
                continue
            if abs(ev["gap"]) > f["max_gap"]:
                continue
            if f["regime"] and ev["regime"] is not True:
                continue
            tr_ = f.get("trend", "off")
            if tr_ in ("btc", "both") and ev.get("btc_trend") is not True:
                continue
            if tr_ in ("coin", "both") and ev.get("coin_trend") is not True:
                continue
            if f["min_hist_r"] is not None:
                n, avg = ev[histk][k]
                if n >= 10 and avg < f["min_hist_r"]:
                    continue
            if count.get(ev["day"], 0) >= max_per_day:
                continue
            count[ev["day"]] = count.get(ev["day"], 0) + 1
            (ins if ev["day"] < split_day else oos).setdefault(ev["day"], []).append(ev[outk][k])
        results.append({"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos)})
    return results


def fmt_row(r, label=""):
    i, o = r["in_sample"], r["out_of_sample"]
    f = r["filters"]
    fs = "until %s vol>=%.1f stop>=%.1f%% gap<=%s regime=%s hist>=%s tgt=%gR BE=%s%s" % (
        f["entry_end"], f["min_vol_x"], f["min_stop_pct"], f["max_gap"], "on" if f["regime"] else "off",
        f["min_hist_r"], f["target_r"], "on" if f["breakeven"] else "off",
        ((" trend=%s" % f["trend"]) if "trend" in f else "") + ((" stops=%s" % f["stop_mode"]) if "stop_mode" in f else "")
        + ((" range=%s" % f["range"]) if "range" in f else ""))
    def s(x):
        if not x.get("trades"):
            return "no trades".ljust(56)
        return "%4d tr  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], 100 * x["win_rate"], x["avg_r"], x["total_r"], x["worst_day_r"], x["max_drawdown_r"])
    return "%s%s\n     in-sample   %s\n     OUT-sample  %s" % (label, fs, s(i), s(o))


# ------------------------------------------------------------------ index F&O

def mirror(b):
    """A bar seen upside down, so a short (or a bought put) can be scored with the long-only outcome()."""
    return (b[0], -b[1], -b[3], -b[2], -b[4], b[5])


def fno_events(idx_data):
    events = []
    for name, d in idx_data.items():
        for day, bars in sorted(bars_by_day(d, IST, 5).items()):
            o_start = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST)
            rng = [b for b in bars if o_start <= b[0] < o_start + timedelta(minutes=15)]
            if len(rng) < 3:
                continue
            hi, lo = max(b[2] for b in rng), min(b[3] for b in rng)
            mid = (hi + lo) / 2
            after = [b for b in bars if b[0] >= o_start + timedelta(minutes=15)]
            flat = o_start.replace(hour=15, minute=15)
            for i, b in enumerate(after):
                end = b[0] + timedelta(minutes=5)
                if end > o_start.replace(hour=13, minute=0):
                    break
                up, down = b[4] > hi, b[4] < lo
                if not (up or down):
                    continue
                path = [x for x in after[i + 1:] if x[0] < flat]
                if up:
                    entry, stop = b[4], mid
                else:
                    entry, stop, path = -b[4], -mid, [mirror(x) for x in path]
                if entry - stop <= 0:
                    break
                ev = {"index": name, "day": day.isoformat(), "time": end.strftime("%H:%M"),
                      "dir": "up" if up else "down", "out": {}}
                for tr in (1.0, 1.5, 2.0):
                    for be in (False, True):
                        ev["out"][(tr, be)] = outcome(path, entry, stop, tr, be, 0.0)[0]
                events.append(ev)
                break  # the first break of the day only, as in the live pipeline
    return events


def fno_main(a):
    print("Fetching 60 days of 5-minute bars for Nifty 50 and Bank Nifty...", flush=True)
    data = {}
    for name, sym in (("NIFTY", "^NSEI"), ("BANKNIFTY", "^NSEBANK")):
        d = fetch(sym, "", "5m")
        if d and d["t"]:
            data[name] = d
    events = fno_events(data)
    if not events:
        print("No events: no index data came back.")
        return 1
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    grid = {"index": ["NIFTY", "BANKNIFTY", "both"], "dir": ["up", "down", "both"],
            "entry_end": ["10:30", "11:30", "13:00"], "target_r": [1.0, 1.5, 2.0], "breakeven": [False, True],
            "cost_r": [0.15, 0.25]}
    res = []
    for combo in itertools.product(*grid.values()):
        f = dict(zip(grid, combo))
        ins, oos = {}, {}
        for ev in events:
            if f["index"] != "both" and ev["index"] != f["index"]:
                continue
            if f["dir"] != "both" and ev["dir"] != f["dir"]:
                continue
            if ev["time"] > f["entry_end"]:
                continue
            r = ev["out"][(f["target_r"], f["breakeven"])] - f["cost_r"]
            (ins if ev["day"] < split else oos).setdefault(ev["day"] + ev["index"], []).append(r)
        res.append({"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos)})

    def row(r, label=""):
        f, i, o = r["filters"], r["in_sample"], r["out_of_sample"]
        def s(x):
            if not x.get("trades"):
                return "no trades"
            return "%3d tr  win %3.0f%%  avg %+.2fR  total %+5.1fR  dd %+.1fR" % (
                x["trades"], 100 * x["win_rate"], x["avg_r"], x["total_r"], x["max_drawdown_r"])
        return "%s%s %s until %s tgt=%gR BE=%s cost=%.2fR\n     in-sample   %s\n     OUT-sample  %s" % (
            label, f["index"], f["dir"], f["entry_end"], f["target_r"], "on" if f["breakeven"] else "off",
            f["cost_r"], s(i), s(o))

    live = next(r for r in res if r["filters"] == {"index": "both", "dir": "both", "entry_end": "13:00",
                                                    "target_r": 2.0, "breakeven": True, "cost_r": 0.15})
    ok = [r for r in res if r["in_sample"].get("trades", 0) >= 15 and r["out_of_sample"].get("trades", 0) >= 6]
    ok.sort(key=lambda r: -r["in_sample"]["avg_r"])
    stable = [r for r in ok if r["in_sample"]["avg_r"] > 0 and r["out_of_sample"]["avg_r"] > 0]
    lines = ["research.py fno  %s" % datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
             "%d index-days with a first break (%s..%s). Scored in INDEX R: an option buyer's R is roughly this "
             "minus time decay, so every result has cost_r (theta + charges) subtracted. No historical option "
             "prices are used: treat this as the index edge, not option P&L." % (len(events), days[0], days[-1]), "",
             row(live, "CURRENT LIVE RULES: "), "", "TOP 10 BY IN-SAMPLE:"]
    for n, r in enumerate(ok[:10], 1):
        lines.append(row(r, "%2d. " % n))
    lines += ["", "%d of %d combinations (with enough trades) were positive both in- and out-of-sample." % (len(stable), len(ok)),
              "Small sample: two indices x ~60 days is about 100 trades at most. Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    with open(os.path.join(OUT, "report_fno.txt"), "w", encoding="utf-8") as fh:
        fh.write(report)
    with open(os.path.join(OUT, "report_fno.json"), "w", encoding="utf-8") as fh:
        json.dump({"live": live, "top": ok[:30], "stable": stable[:20], "days": days, "split": split}, fh, indent=1, default=str)
    print("\nWrote %s" % os.path.join(OUT, "report_fno.txt"))
    return 0


# ------------------------------------------------------------------ crypto: live entry timing

LIVE_V3 = {"min_vol_x": 1.5, "min_stop_pct": 1.0, "regime": True, "target_r": 2.0, "max_chase_r": 0.5,
           "max_fee_r": 0.25, "fee": 0.001, "hold_min": 360}


def bars5(d):
    rows = [(t, o, h, l, c, v) for t, o, h, l, c, v in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"])
            if not datetime.fromtimestamp(t, UTC).minute % 5 and None not in (o, h, l, c)]
    rows.sort()
    return rows


def live_timing(events, data5, rules=LIVE_V3):
    """Each live-rule breakout (15-minute signal) scored three ways, all on 5-minute bars after the entry:
         close    enter at the breakout candle's close (what the plain backtest assumes)
         fast     enter at the first price after the close (open of the next 5-minute bar): a runner that
                  decides within ~1 minute
         plus5    enter 5 minutes after the close (close of that 5-minute bar): today's live runner, which
                  waits SETTLE_MIN = 5 for Yahoo's volume
       The live entry checks run on the entry price: moved back inside the range -> skip, more than
       max_chase_r past the trigger -> skip, stop closer than min_stop_pct -> skip, fees > max_fee_r -> skip."""
    idx = {}
    for sym, d in data5.items():
        rows = bars5(d)
        idx[sym] = (rows, [r[0] for r in rows])
    out = {"close": [], "fast": [], "plus5": []}
    for ev in events:
        if ev["vol_x"] < rules["min_vol_x"] or (rules["regime"] and ev["regime"] is not True):
            continue
        if ev["sym"] not in idx:
            continue
        rows, ts = idx[ev["sym"]]
        j = bisect.bisect_left(ts, ev["_end"])  # first 5-minute bar starting at/after the 15m close
        if j >= len(rows) or rows[j][0] != ev["_end"]:
            continue
        for model in out:
            if model == "close":
                px, k = ev["_entry"], j
            elif model == "fast":
                px, k = rows[j][1], j
            else:
                px, k = rows[j][4], j + 1
            hi, stop = ev["_hi"], ev["_mid"]
            risk = px - stop
            rec = {"day": ev["day"], "sym": ev["sym"]}
            if risk <= 0:
                rec["skip"] = "past the stop"
            elif px < hi:
                rec["skip"] = "moved back inside"
            elif (px - hi) / risk > rules["max_chase_r"]:
                rec["skip"] = "chasing"
            elif risk / px * 100 < rules["min_stop_pct"]:
                rec["skip"] = "stop too tight"
            else:
                tgt = px + rules["target_r"] * risk
                fee_r = (px + tgt) * rules["fee"] / risk
                if fee_r > rules["max_fee_r"]:
                    rec["skip"] = "fees too high"
                else:
                    path = [(datetime.fromtimestamp(r[0], UTC),) + tuple(r[1:]) for r in rows[k:k + rules["hold_min"] // 5]]
                    rec["r"] = outcome(path, px, stop, rules["target_r"], False, fee_r)[0]
            out[model].append(rec)
    return out


def live_timing_main(a, syms, src):
    print("Fetching 60 days of 15-minute AND 5-minute bars for %d coins (%s)..." % (len(syms), src), flush=True)
    data, failed = fetch_all(syms, "-USD", "15m", a.workers)
    data5, failed5 = fetch_all(syms, "-USD", "5m", a.workers)
    btc = data.get("BTC") or fetch("BTC", "-USD", "15m")
    events = crypto_events(data, btc)
    res = live_timing(events, data5)
    if not res["close"]:
        print("No events: no data came back (check the internet / Yahoo).")
        return 1
    days = sorted({r["day"] for r in res["close"]})
    split = days[int(len(days) * 0.7)]
    names = {"close": "Enter at the candle close (plain backtest)",
             "fast": "Enter ~1 min after the close (fast runner)",
             "plus5": "Enter 5 min after the close (TODAY'S LIVE RUNNER)"}
    lines = ["research.py crypto-live  %s" % datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
             "Live rules v3 (volume >= 1.5x, BTC regime, stop >= 1%%, target 2R, chase <= 0.5R, fees <= 0.25R, "
             "6h time stop), %d coins, %d days (%s..%s). Out-of-sample = days from %s. R after 0.1%% fee each side."
             % (len(data), len(days), days[0], days[-1], split), ""]
    for m in ("close", "fast", "plus5"):
        rows = res[m]
        taken = [r for r in rows if "r" in r]
        skips = {}
        for r in rows:
            if "skip" in r:
                skips[r["skip"]] = skips.get(r["skip"], 0) + 1
        ins = {}
        oos = {}
        for r in taken:
            (ins if r["day"] < split else oos).setdefault(r["day"], []).append(r["r"])
        def s(x):
            if not x.get("trades"):
                return "no trades"
            return "%4d tr  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
                x["trades"], 100 * x["win_rate"], x["avg_r"], x["total_r"], x["worst_day_r"], x["max_drawdown_r"])
        lines += [names[m],
                  "     signals %d, taken %d (%.1f a day), skipped: %s" % (
                      len(rows), len(taken), len(taken) / max(1, len(days)),
                      ", ".join("%s %d" % kv for kv in sorted(skips.items(), key=lambda x: -x[1])) or "none"),
                  "     in-sample   " + s(stats(ins)),
                  "     OUT-sample  " + s(stats(oos)), ""]
    lines += ["How to read it: if 'fast' beats 'plus5' out-of-sample, the 5-minute wait is costing money and the",
              "runner should decide faster (volume from Coinbase instead of waiting for Yahoo). If 'plus5' holds up,",
              "the live runner is fine as it is. ~60 days is a short sample. Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    with open(os.path.join(OUT, "report_crypto-live.txt"), "w", encoding="utf-8") as fh:
        fh.write(report)
    print("\nWrote %s" % os.path.join(OUT, "report_crypto-live.txt"))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Walk-forward backtest of the breakout rules. Not financial advice.")
    p.add_argument("mode", choices=["nse", "nse-v2", "crypto", "crypto-short", "crypto-mr", "crypto-5m", "crypto-live", "crypto-v4", "crypto-v4-5m", "crypto-v4-short", "crypto-smc", "crypto-smcp", "crypto-smcp-5m", "nse-smcp", "crypto-abcd", "crypto-abcd-5m", "nse-abcd", "us-abcd", "us-orb", "crypto-v3", "crypto-v3-5m", "nse-v3", "us-v3", "crypto-sv4", "crypto-sv4-5m", "nse-sv4", "us-sv4", "us-tm", "nse-tm", "crypto-tm", "crypto-tm-5m", "fno", "fno-sv4", "bnf-sv4", "nifty-sv4", "usopt-sv4", "crypto-sv5", "crypto-sv5-5m", "us-sv5", "nse-sv5", "gold-sv5"])
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--universe", help="crypto: a symbols file instead of trader/universe_crypto.txt "
                                      "(e.g. trader/universe_crypto_wide.txt)")
    p.add_argument("--max-per-day", type=int, default=0, help="0 = every qualifying trade (best for comparing filters)")
    a = p.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)

    if a.mode == "fno":
        return fno_main(a)
    if a.mode == "nse-v2":
        import research_nse2
        syms, src = S.universe_for("NSE")
        if a.limit:
            syms = syms[:a.limit]
        return research_nse2.main(a, syms, src, fetch_all, fetch, stats, bars_by_day, OUT, IST)
    if a.mode == "us-orb":  # the live US opening-range rule vs earlier entries: research_usorb.py
        import research_abcd
        import research_usorb
        syms, src = list(research_abcd.US_LIQUID), "built-in liquid US list"
        if a.universe:
            with open(a.universe, encoding="utf-8") as fh:
                syms = S.dedup([ln.split("|")[0].strip().upper() for ln in fh
                                if ln.strip() and not ln.lstrip().startswith("#")])
            src = a.universe
        if a.limit:
            syms = syms[:a.limit]
        return research_usorb.main(a, syms, src, fetch_all, fetch, stats, OUT, IST)
    if a.mode in ("nse-tm", "us-tm"):  # the Trade Manager on the playbook entries: research_tm.py
        import research_abcd
        import research_tm
        if a.mode == "nse-tm":
            syms, src = S.universe_for("NSE")
        else:
            syms, src = list(research_abcd.US_LIQUID), "built-in liquid US list"
        if a.limit:
            syms = syms[:a.limit]
        return research_tm.main(a, syms, src, fetch_all, fetch, stats, OUT, IST,
                                market="nse" if a.mode == "nse-tm" else "us")
    if a.mode in ("nse-sv5", "us-sv5", "gold-sv5"):  # Scanner v5 (the 0.146 level): research_scanner_v5.py
        import research_abcd
        import research_scanner_v5
        if a.mode == "nse-sv5":
            syms, src, mkt = list(S.NIFTY50), "Nifty 50", "nse"
        elif a.mode == "gold-sv5":
            syms, src, mkt = ["GC=F"], "gold futures (the reel's market)", "gold"
        else:
            syms, src, mkt = list(research_abcd.US_LIQUID), "built-in liquid US list", "us"
        if a.limit:
            syms = syms[:a.limit]
        return research_scanner_v5.main(a, syms, src, fetch_all, stats, OUT, IST, market=mkt)
    if a.mode == "bnf-sv4":  # Scanner v4 on the Bank Nifty index, bought as ATM options (the only F&O traded)
        import research_fno_sv4
        import fno as F
        return research_fno_sv4.main(a, ["^NSEBANK"], "Bank Nifty index", fetch_all, stats, OUT, IST, suffix="",
                                     lot_size=F.FNO["BANKNIFTY"]["lot"], mode="bnf-sv4")
    if a.mode == "usopt-sv4":  # US F&O: Scanner v4 on QQQ / SPY, bought as ATM weekly options (owner, 13 Nov 2026)
        import research_fno_sv4
        from zoneinfo import ZoneInfo
        return research_fno_sv4.main(a, ["QQQ", "SPY", "DIA"], "QQQ + SPY + DIA", fetch_all, stats, OUT, ZoneInfo("America/New_York"),
                                     suffix="", lot_size=100, mode="usopt-sv4", spec=research_fno_sv4.SPEC_US)
    if a.mode == "nifty-sv4":  # Scanner v4 on the Nifty 50 index, bought as ATM options (owner, 12 Nov 2026)
        import research_fno_sv4
        import fno as F
        return research_fno_sv4.main(a, ["^NSEI"], "Nifty 50 index", fetch_all, stats, OUT, IST, suffix="",
                                     lot_size=F.FNO["NIFTY"]["lot"], mode="nifty-sv4")
    if a.mode == "fno-sv4":  # Scanner v4 on F&O stocks, bought as ATM options: research_fno_sv4.py
        import research_fno_sv4
        syms, src = list(S.NIFTY50), "Nifty 50 (all in F&O)"
        if a.limit:
            syms = syms[:a.limit]
        return research_fno_sv4.main(a, syms, src, fetch_all, stats, OUT, IST)
    if a.mode in ("nse-sv4", "us-sv4"):  # Scanner v4 on stocks: research_scanner_v4.py
        import research_abcd
        import research_scanner_v4
        if a.mode == "nse-sv4":
            syms, src = S.universe_for("NSE")
        else:
            syms, src = list(research_abcd.US_LIQUID), "built-in liquid US list"
        if a.limit:
            syms = syms[:a.limit]
        return research_scanner_v4.main(a, syms, src, fetch_all, fetch, stats, OUT, IST,
                                        market="nse" if a.mode == "nse-sv4" else "us")
    if a.mode in ("nse-v3", "us-v3"):  # Scanner v3's sweep reversal on stocks: research_v3.py
        import research_abcd
        import research_v3
        if a.mode == "nse-v3":
            syms, src = S.universe_for("NSE")
        else:
            syms, src = list(research_abcd.US_LIQUID), "built-in liquid US list"
            if a.universe:
                with open(a.universe, encoding="utf-8") as fh:
                    syms = S.dedup([ln.split("|")[0].strip().upper() for ln in fh
                                    if ln.strip() and not ln.lstrip().startswith("#")])
                src = a.universe
        if a.limit:
            syms = syms[:a.limit]
        return research_v3.main(a, syms, src, fetch_all, fetch, stats, OUT, IST,
                                market="nse" if a.mode == "nse-v3" else "us")
    if a.mode in ("nse-abcd", "us-abcd"):  # the owner's A-B-C-D entry on stocks: research_abcd.py
        import research_abcd
        if a.mode == "nse-abcd":
            syms, src = S.universe_for("NSE")
        else:
            syms, src = list(research_abcd.US_LIQUID), "built-in liquid US list"
            if a.universe:
                with open(a.universe, encoding="utf-8") as fh:
                    syms = S.dedup([ln.split("|")[0].strip().upper() for ln in fh
                                    if ln.strip() and not ln.lstrip().startswith("#")])
                src = a.universe
        if a.limit:
            syms = syms[:a.limit]
        return research_abcd.main(a, syms, src, fetch_all, fetch, stats, OUT, IST,
                                  market="nse" if a.mode == "nse-abcd" else "us")
    if a.mode == "nse-smcp":  # the user's SMC playbook on NSE stocks: research_smcp.py
        import research_smcp
        syms, src = S.universe_for("NSE")
        if a.limit:
            syms = syms[:a.limit]
        return research_smcp.main(a, syms, src, fetch_all, fetch, stats, OUT, IST, market="nse")
    if a.mode == "nse":
        syms, src = S.universe_for("NSE")
        if a.limit:
            syms = syms[:a.limit]
        print("Fetching 60 days of 5-minute bars for %d NSE symbols (%s) + Nifty 50..." % (len(syms), src), flush=True)
        data, failed = fetch_all(syms, ".NS", "5m", a.workers)
        nifty = fetch("^NSEI", "", "5m")
        events = nse_events(data, nifty)
        grid = {"entry_end": ["10:30", "11:30", "13:00", "14:30"], "min_vol_x": [0.0, 1.0, 1.5, 2.0],
                "min_stop_pct": [0.3, 0.5], "max_gap": [3.0, 99], "regime": [False, True],
                "min_hist_r": [None, 0.0, 0.1], "target_r": [1.0, 1.5, 2.0], "breakeven": [False, True]}
        live = {"entry_end": "11:30", "min_vol_x": 1.5, "min_stop_pct": 0.5, "max_gap": 3.0, "regime": True,
                "min_hist_r": 0.1, "target_r": 2.0, "breakeven": True}
        max_per_day = a.max_per_day or 10**6
    else:
        import scan_crypto as C
        syms, src = C.universe()
        if a.universe:
            with open(a.universe, encoding="utf-8") as fh:
                syms = S.dedup([ln.split("|")[0].strip().upper().replace("-USD", "") for ln in fh
                                if ln.strip() and not ln.lstrip().startswith("#")])
            src = a.universe
        if a.limit:
            syms = syms[:a.limit]
        if a.mode == "crypto-live":
            return live_timing_main(a, syms, src)
        if a.mode == "crypto-smc":  # liquidity sweep and reclaim: research_smc.py
            import research_smc
            return research_smc.main(a, syms, src, fetch_all, fetch, stats, OUT, IST)
        if a.mode in ("crypto-tm", "crypto-tm-5m"):  # the Trade Manager: research_tm.py
            import research_tm
            return research_tm.main(a, syms, src, fetch_all, fetch, stats, OUT, IST, market="crypto",
                                    step=5 if a.mode.endswith("5m") else 15)
        if a.mode in ("crypto-sv5", "crypto-sv5-5m"):  # Scanner v5 (the 0.146 level): research_scanner_v5.py
            import research_scanner_v5
            return research_scanner_v5.main(a, syms, src, fetch_all, stats, OUT, IST,
                                            step=5 if a.mode.endswith("5m") else 15)
        if a.mode in ("crypto-sv4", "crypto-sv4-5m"):  # Scanner v4: research_scanner_v4.py
            import research_scanner_v4
            return research_scanner_v4.main(a, syms, src, fetch_all, fetch, stats, OUT, IST,
                                            step=5 if a.mode.endswith("5m") else 15)
        if a.mode in ("crypto-v3", "crypto-v3-5m"):  # Scanner v3's sweep reversal: research_v3.py
            import research_v3
            return research_v3.main(a, syms, src, fetch_all, fetch, stats, OUT, IST,
                                    step=5 if a.mode.endswith("5m") else 15)
        if a.mode in ("crypto-abcd", "crypto-abcd-5m"):  # the owner's A-B-C-D entry: research_abcd.py
            import research_abcd
            return research_abcd.main(a, syms, src, fetch_all, fetch, stats, OUT, IST,
                                      step=5 if a.mode.endswith("5m") else 15)
        if a.mode in ("crypto-smcp", "crypto-smcp-5m"):  # the user's SMC playbook: research_smcp.py
            import research_smcp
            return research_smcp.main(a, syms, src, fetch_all, fetch, stats, OUT, IST,
                                      step=5 if a.mode.endswith("5m") else 15)
        if a.mode == "crypto-v4":  # stop / exit / squeeze variants: research_v4.py
            import research_v4
            return research_v4.main(a, syms, src, fetch_all, fetch, stats, OUT, IST)
        if a.mode == "crypto-v4-5m":
            import research_v4
            return research_v4.main(a, syms, src, fetch_all, fetch, stats, OUT, IST, step=5)
        if a.mode == "crypto-v4-short":
            import research_v4
            return research_v4.main(a, syms, src, fetch_all, fetch, stats, OUT, IST, short=True)
        iv = "5m" if a.mode == "crypto-5m" else "15m"
        print("Fetching 60 days of %s bars for %d coins (%s)..." % (iv, len(syms), src), flush=True)
        data, failed = fetch_all(syms, "-USD", iv, a.workers)
        btc = data.get("BTC") or fetch("BTC", "-USD", iv)
        if a.mode == "crypto-5m":  # the same breakout rule on 5-minute bars: 4h range (48 bars) and 1h range (12)
            events = (crypto_events(data, btc, step=5, rb=48, hold=72, tag="4h")
                      + crypto_events(data, btc, step=5, rb=12, hold=72, tag="1h"))
            events.sort(key=lambda e: (e["day"], e["time"]))
        elif a.mode == "crypto-mr":
            events = mr_events(data, btc)
        else:
            events = crypto_events(data, btc, short=(a.mode == "crypto-short"))
        grid = {"entry_end": ["23:59"], "min_vol_x": [0.0, 1.5, 2.0, 3.0], "min_stop_pct": [0.5, 1.0],
                "max_gap": [99], "regime": [False, True], "min_hist_r": [None, 0.0],
                "target_r": [1.0, 1.5, 2.0, 3.0], "breakeven": [False, True],
                "trend": ["off", "btc"], "stop_mode": ["skip", "widen"]}
        if a.mode == "crypto-5m":
            grid = {"entry_end": ["23:59"], "min_vol_x": [0.0, 1.5, 2.0, 3.0], "min_stop_pct": [0.3, 0.5, 1.0],
                    "max_gap": [99], "regime": [False, True], "min_hist_r": [None],
                    "target_r": [1.0, 1.5, 2.0, 3.0], "breakeven": [False, True],
                    "trend": ["off", "btc"], "stop_mode": ["skip"], "range": ["4h", "1h"]}
        # the live long rules (v3); for crypto-short, the same filters applied to breakdowns
        live = {"entry_end": "23:59", "min_vol_x": 1.5, "min_stop_pct": 1.0, "max_gap": 99, "regime": True,
                "min_hist_r": None, "target_r": 2.0, "breakeven": False, "trend": "off", "stop_mode": "skip"}
        if a.mode == "crypto-5m":  # the live filters on 5-minute bars with a 4h range
            live = dict(live, range="4h")
        max_per_day = a.max_per_day or 10**6

    if not events:
        print("No events: no data came back (check the internet / Yahoo).")
        return 1
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    print("%d charts (%d failed), %d trading days %s to %s, %d raw breakouts. In-sample: days before %s."
          % (len(data), len(failed), len(days), days[0], days[-1], len(events), split), flush=True)
    res = run_grid(events, grid, split, max_per_day)
    base = next(r for r in res if r["filters"] == {"entry_end": grid["entry_end"][-1], "min_vol_x": 0.0,
                                                    "min_stop_pct": grid["min_stop_pct"][0], "max_gap": 99 if 99 in grid["max_gap"] else grid["max_gap"][-1],
                                                    "regime": False, "min_hist_r": None, "target_r": 2.0, "breakeven": False,
                                                    **({"trend": "off"} if "trend" in grid else {}),
                                                    **({"stop_mode": "skip"} if "stop_mode" in grid else {}),
                                                    **({"range": "4h"} if "range" in grid else {})})
    cur = next((r for r in res if r["filters"] == live), None)
    min_is = 30 if a.mode == "nse" else 20
    ok = [r for r in res if r["in_sample"].get("trades", 0) >= min_is and r["out_of_sample"].get("trades", 0) >= 8]
    ok.sort(key=lambda r: -r["in_sample"]["avg_r"])
    stable = [r for r in ok if r["out_of_sample"]["avg_r"] > 0 and r["in_sample"]["avg_r"] > 0]

    lines = ["research.py %s  %s" % (a.mode, datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")),
             "%d charts, %d days (%s..%s), %d raw breakouts, %d filter combinations." % (
                 len(data), len(days), days[0], days[-1], len(events), len(res)),
             "R is after charges. One trade per stock per day; %s." % ("at most %d trades a day" % max_per_day if max_per_day < 10**6 else "no daily cap (every qualifying trade counts)"), "",
             fmt_row(base, "NO FILTERS (baseline): "), ""]
    if cur:
        lines += [fmt_row(cur, "CURRENT LIVE RULES:     "), ""]
    lines += ["TOP %d BY IN-SAMPLE (check the OUT-sample line; that is the honest one):" % a.top]
    for n, r in enumerate(ok[:a.top], 1):
        lines.append(fmt_row(r, "%2d. " % n))
    lines += ["", "%d of %d combinations (with enough trades) were positive both in- and out-of-sample." % (len(stable), len(ok))]
    if stable:
        stable.sort(key=lambda r: -min(r["in_sample"]["avg_r"], r["out_of_sample"]["avg_r"]))
        lines += ["Most consistent (best of the weaker half):", fmt_row(stable[0], "  ")]
    lines += ["", "A backtest is history, not a promise; ~60 days is a short sample. Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    tag = a.mode + ("-" + os.path.splitext(os.path.basename(a.universe))[0].replace("universe_", "") if a.universe else "")
    with open(os.path.join(OUT, "report_%s.txt" % tag), "w", encoding="utf-8") as fh:
        fh.write(report)
    with open(os.path.join(OUT, "report_%s.json" % tag), "w", encoding="utf-8") as fh:
        json.dump({"baseline": base, "current": cur, "top": ok[:50], "stable": stable[:20],
                   "days": days, "split": split, "events": len(events)}, fh, indent=1, default=str)
    print("\nWrote %s" % os.path.join(OUT, "report_%s.txt" % tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
