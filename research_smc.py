#!/usr/bin/env python3
"""
research_smc.py - Smart Money Concepts "liquidity sweep and reclaim" vs the live 4h breakout rule
(python research.py crypto-smc, or the dashboard's Backtest -> Crypto SMC).

Setup (smc.py): a 15-minute candle sweeps the 4-hour range's low (or high) and closes back inside, in one
candle (wick) or two (2bar). Long after a swept low, short after a swept high; entry at the reclaiming
close. Every combination of:

  variant   wick | 2bar | any
  side      long | short | both
  stop      sweep (the sweep's extreme, minus 0.1 ATR) | atr1.5 (1.5 x ATR(14) from the entry)
  exit      2R target | mid (target = the 4h range's middle, skipped if under 0.5R away) |
            trail (break-even at +1R, then 2 x ATR behind the best price)
  filters   sweep volume >= 1.5x the range average (on/off); BTC regime with the trade (long only while
            BTC is above its 4h midpoint, short only below) on/off; thin hours 00-06 UTC skipped on/off;
            fee cap 0.25R / 0.40R of the risk

Same data, fee and walk-forward split as crypto-v4; the live 4h breakout rule (v6, and with volume 1.5x)
is scored on the same days for a straight comparison. 12-hour time stop. Trust the out-of-sample line.
"""
import bisect
import itertools
import os
from datetime import datetime, timezone

import research_v4 as V4
import smc

UTC = timezone.utc
HOLD = 48
STOPS = ("sweep", "atr1.5")
EXITS = ("2R", "mid", "trail")
GRID = {"variant": ["wick", "2bar", "any"], "side": ["long", "short", "both"], "stop": list(STOPS),
        "exit": list(EXITS), "min_vol_x": [0.0, 1.5], "regime": [False, True], "session": ["all", "active"],
        "max_fee_r": [0.25, 0.40]}
# what the live bot's SMC setup does by default (auto_crypto.py DEFAULTS smc_*)
LIVE_SMC = {"variant": "any", "side": "both", "stop": "sweep", "exit": "2R", "min_vol_x": 0.0, "regime": False,
            "session": "active", "max_fee_r": 0.25}


def _mirror(rows):
    """Prices upside down, so a short is scored with the long-only exit functions."""
    return [(r[0], -r[1], -r[3], -r[2], -r[4], r[5]) for r in rows]


def _target(path, entry, stop, target):
    risk = entry - stop
    for b in path:
        if b[3] <= stop:
            return -1.0
        if b[2] >= target:
            return (target - entry) / risk
    return ((path[-1][4] if path else entry) - entry) / risk


def events_smc(data, btc):
    btc_close = {t: c for t, c in zip(btc["t"], btc["c"])} if btc else {}
    bt = sorted(btc_close)
    fee = V4.FEE
    evs = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"])
                if not datetime.fromtimestamp(t, UTC).minute % 15 and None not in (o, h, l, c)]
        if len(rows) < 300:
            continue
        bars = [(r[1], r[2], r[3], r[4], r[5]) for r in rows]
        mrows = _mirror(rows)
        last_i = -999
        for i in range(30, len(rows) - HOLD):
            s = smc.sweep_at(bars, i)
            if not s or i - last_i < smc.RANGE_BARS:   # one trade per coin per 4 h, like the breakout rule
                continue
            last_i = i
            short = s["side"] == "short"
            src = mrows if short else rows
            sgn = -1 if short else 1
            entry, extreme, mid = sgn * s["entry"], sgn * s["extreme"], sgn * s["range_mid"]
            atr = V4._atr(rows, i)
            regime = None
            if bt:
                j = bisect.bisect_right(bt, int(rows[i][0].timestamp()))
                k = bt[max(0, j - smc.RANGE_BARS - 1):j]
                if len(k) > smc.RANGE_BARS:
                    w = [btc_close[x] for x in k]
                    up = w[-1] > (max(w[:-1]) + min(w[:-1])) / 2
                    regime = (not up) if short else up      # True = BTC agrees with the trade's direction
            ev = {"sym": sym, "day": rows[i][0].date().isoformat(), "hour": rows[i][0].hour, "side": s["side"],
                  "variant": s["variant"], "vol_x": s["vol_x"], "regime": regime, "out": {}, "fee_r": {}}
            path = src[i + 1:i + 1 + HOLD]
            for sname, stop in (("sweep", extreme - 0.1 * atr), ("atr1.5", entry - 1.5 * atr)):
                risk = entry - stop
                if risk <= 0:
                    continue
                ev["fee_r"][sname] = 2 * abs(entry) * fee / risk
                for ex in EXITS:
                    if ex == "2R":
                        r = V4._fixed(path, entry, stop, 2.0)
                        cost = (2 * abs(entry) + 2 * risk) * fee / risk
                    elif ex == "mid":
                        if mid - entry < 0.5 * risk:
                            continue
                        r = _target(path, entry, stop, mid)
                        cost = (2 * abs(entry) + (mid - entry)) * fee / risk
                    else:
                        r = V4._trail(path, entry, stop, atr)
                        cost = 2 * abs(entry) * fee / risk
                    ev["out"][(sname, ex)] = r - cost
            if ev["out"]:
                evs.append(ev)
    evs.sort(key=lambda e: e["day"])
    return evs


def keep(ev, f):
    if (f["stop"], f["exit"]) not in ev["out"]:
        return False
    if f["variant"] != "any" and ev["variant"] != f["variant"]:
        return False
    if f["side"] != "both" and ev["side"] != f["side"]:
        return False
    if ev["vol_x"] < f["min_vol_x"] or (f["regime"] and ev["regime"] is not True):
        return False
    if f["session"] == "active" and ev["hour"] < 6:
        return False
    return ev["fee_r"][f["stop"]] <= f["max_fee_r"]


def score(events, f, split, stats):
    ins, oos = {}, {}
    k = (f["stop"], f["exit"])
    for ev in events:
        if keep(ev, f):
            (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["out"][k])
    return {"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos)}


def row(r, label=""):
    f, i, o = r["filters"], r["in_sample"], r["out_of_sample"]

    def s(x):
        if not x.get("trades"):
            return "no trades"
        return "%4d tr (%.1f/active day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
            x["worst_day_r"], x["max_drawdown_r"])
    parts = ["variant=%s" % f["variant"], "side=%s" % f["side"], "stop=%s" % f["stop"], "exit=%s" % f["exit"],
             "vol>=%.1f" % f["min_vol_x"], "btc=%s" % ("with" if f["regime"] else "off"), "hours=%s" % f["session"],
             "fees<=%.2fR" % f["max_fee_r"]]
    return "%s%s\n     in-sample   %s\n     OUT-sample  %s" % (label, " ".join(parts), s(i), s(o))


def main(a, syms, src, fetch_all, fetch, stats, out_dir, ist):
    print("Fetching 60 days of 15-minute bars for %d coins (%s)..." % (len(syms), src), flush=True)
    data, failed = fetch_all(syms, "-USD", "15m", a.workers)
    btc = data.get("BTC") or fetch("BTC", "-USD", "15m")
    events = events_smc(data, btc)
    brk = V4.events_v4(data, btc)
    if not events or not brk:
        print("No events: no data came back (check the internet / Yahoo).")
        return 1
    days = sorted({e["day"] for e in brk} | {e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    live_brk = V4.score(brk, V4.LIVE_V4, split, stats)
    live_brk15 = V4.score(brk, dict(V4.LIVE_V4, min_vol_x=1.5), split, stats)
    res = [score(events, dict(zip(GRID, c)), split, stats) for c in itertools.product(*GRID.values())]
    live = score(events, LIVE_SMC, split, stats)
    ok = [r for r in res if r["in_sample"].get("trades", 0) >= 20 and r["out_of_sample"].get("trades", 0) >= 8]
    ok.sort(key=lambda r: -r["in_sample"]["avg_r"])
    stable = [r for r in ok if r["in_sample"]["avg_r"] > 0 and r["out_of_sample"]["avg_r"] > 0]
    stable.sort(key=lambda r: -min(r["in_sample"]["avg_r"], r["out_of_sample"]["avg_r"]))

    def effect(name, on, off):
        a_ = [r["out_of_sample"]["avg_r"] for r in ok if r["filters"][name] == on]
        b_ = [r["out_of_sample"]["avg_r"] for r in ok if r["filters"][name] == off]
        if not a_ or not b_:
            return "  %-24s not enough trades to compare" % ("%s=%s" % (name, on))
        ma, mb = sum(a_) / len(a_), sum(b_) / len(b_)
        return "  %-24s %+.2fR vs %+.2fR with %s  (%s)" % (
            "%s=%s" % (name, on), ma, mb, off, "helps" if ma > mb + 0.03 else "hurts" if ma < mb - 0.03 else "no clear effect")

    n_long = sum(1 for e in events if e["side"] == "long")
    lines = ["research.py crypto-smc  %s" % datetime.now(ist).strftime("%Y-%m-%d %H:%M IST"),
             "%d coins, %d days (%s..%s), %d reclaimed sweeps of the 4h range (%d of the low -> long, %d of the high "
             "-> short; at most one per coin per 4h). R after %.3f%% fee each side. Out-of-sample = days from %s." % (
                 len(data), len(days), days[0], days[-1], len(events), n_long, len(events) - n_long, V4.FEE * 100, split),
             "",
             "THE LIVE 4H BREAKOUT RULE ON THE SAME DAYS (what SMC has to beat):",
             V4.row(live_brk, "  v6 now (vol>=1.0):  "),
             V4.row(live_brk15, "  with vol>=1.5:      "), "",
             row(live, "SMC AS THE LIVE BOT WOULD RUN IT (defaults): "), "",
             "WHICH INGREDIENT HELPS (average OUT-sample R of the combinations with it vs the alternative):",
             effect("variant", "wick", "2bar"), effect("side", "long", "short"), effect("stop", "atr1.5", "sweep"),
             effect("exit", "mid", "2R"), effect("exit", "trail", "2R"), effect("min_vol_x", 1.5, 0.0),
             effect("regime", True, False), effect("session", "active", "all"), effect("max_fee_r", 0.40, 0.25), "",
             "TOP 10 BY IN-SAMPLE (the OUT-sample line is the honest one):"]
    for n, r in enumerate(ok[:10], 1):
        lines.append(row(r, "%2d. " % n))
    lines += ["", "%d of %d combinations (with enough trades) were positive both in- and out-of-sample." % (
        len(stable), len(ok))]
    if stable:
        best = stable[0]
        lines += ["", "MOST CONSISTENT SMC COMBINATION (best of its weaker half):", row(best, "  "), "",
                  "ITS NEIGHBOURS (one setting changed at a time; a robust rule has neighbours that also do well):"]
        for k, vals in GRID.items():
            for v in vals:
                if v != best["filters"][k]:
                    lines.append(row(score(events, dict(best["filters"], **{k: v}), split, stats), "  %s=%s -> " % (k, v)))
    lines += ["", "Decision rule: replace the 4h breakout with SMC only if an SMC combination beats the live rule",
              "out-of-sample (avg R and total, 20+ trades) and its neighbours mostly stay positive. Both can also run",
              "together (Settings -> Setups traded). ~60 days is short. Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report_crypto-smc.txt"), "w", encoding="utf-8") as fh:
        fh.write(report)
    print("\nWrote %s" % os.path.join(out_dir, "report_crypto-smc.txt"))
    return 0
