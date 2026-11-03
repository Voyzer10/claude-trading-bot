"""
research_v4.py - crypto strategy research, round 4: a "pro trader" breakout setup vs the live rule.

Why: since the first day the live rule (v3) has taken no trades. It puts the stop at the middle of the 4h
range and skips the trade when that stop is closer than 1%, so in quiet markets almost every breakout is
skipped, including clean ones that then run (TRX, 1 Nov).

What a disciplined breakout trader checks, and how this file tests each one:
  1. Trend      only buy breakouts in an uptrend: price above the 15m EMA50 and EMA50 above EMA200
                ("ema"), optionally also EMA200 rising ("ema+slope")
  2. Squeeze    the best breakouts come out of a tight, quiet range: 4h range under 1% of price
  3. Volume     the breakout candle trades more than the range average (1.5x)
  4. Market     BTC not falling (BTC above the middle of its own 4h range)
  5. Session    skip the thin hours (00:00-06:00 UTC = 05:30-11:30 IST), when breakouts fail more often
  6. Risk       stop where the idea is wrong: 1.5 x ATR(14) under the entry (or the range middle, as live)
                and size the trade from that stop; skip only if fees eat too much of the risk (0.25R / 0.40R)
                instead of a fixed 1% minimum stop
  7. Exit       2R target (live), a trailing stop (break-even at +1R, then 2 x ATR under the high), or
                "partial": half off at +1R, stop to break-even, the other half trails
Every combination is scored on the same fresh 4h breakouts, 70/30 walk-forward, with the paper CRYPTO account's
fee per side (trader/paper/config.json fee_pct: CoinDCX futures taker + GST = 0.059% since 2 Nov 2026; 0.1% before).
The report shows the live rule, the full PRO SETUP, the best combinations and which ingredient helps.
Run: python research.py crypto-v4   (or the dashboard's Backtest -> Strategy v4)
"""
import bisect
import itertools
import os
from datetime import datetime, timezone

def _fee():
    """Fee per side as a fraction, from the paper CRYPTO account (what the live bot is charged)."""
    try:
        import paper as P
        return float(P.load_config()["accounts"]["CRYPTO"]["fee_pct"]) / 100
    except Exception:
        return 0.00059


FEE = _fee()  # per side
UTC = timezone.utc


def _ema(values, n):
    k, out, e = 2 / (n + 1), [], None
    for v in values:
        e = v if e is None else e + k * (v - e)
        out.append(e)
    return out


def _atr(rows, i, n=14):
    trs = [max(rows[j][2] - rows[j][3], abs(rows[j][2] - rows[j - 1][4]), abs(rows[j][3] - rows[j - 1][4]))
           for j in range(max(1, i - n + 1), i + 1)]
    return sum(trs) / len(trs) if trs else 0.0


def _fixed(path, entry, stop, target_r):
    risk = entry - stop
    target = entry + target_r * risk
    for b in path:
        if b[3] <= stop:
            return (stop - entry) / risk
        if b[2] >= target:
            return target_r
    return ((path[-1][4] if path else entry) - entry) / risk


def _trail(path, entry, stop, atr, k=2.0, arm_r=1.0):
    """Break-even once +arm_r is reached, then trail k x ATR under the highest high."""
    risk = entry - stop
    cur, armed, hi = stop, False, entry
    for b in path:
        if b[3] <= cur:
            return (cur - entry) / risk
        hi = max(hi, b[2])
        if not armed and hi >= entry + arm_r * risk:
            armed, cur = True, max(cur, entry)
        if armed:
            cur = max(cur, hi - k * atr)
    return ((path[-1][4] if path else entry) - entry) / risk


def _partial(path, entry, stop, atr):
    """Half off at +1R, the rest trails (with its stop at break-even from then on)."""
    risk = entry - stop
    one_r = entry + risk
    for n, b in enumerate(path):
        if b[3] <= stop:
            return -1.0
        if b[2] >= one_r:  # half banked at +1R; the other half continues from this bar with a break-even stop
            return 0.5 * 1.0 + 0.5 * _trail_from_be(path[n + 1:], entry, risk, atr)
    return ((path[-1][4] if path else entry) - entry) / risk


def _trail_from_be(path, entry, risk, atr, k=2.0):
    cur, hi = entry, entry + risk
    for b in path:
        if b[3] <= cur:
            return (cur - entry) / risk
        hi = max(hi, b[2])
        cur = max(cur, hi - k * atr)
    return ((path[-1][4] if path else entry) - entry) / risk


STOPS = ("mid", "atr1.5")
EXITS = ("2R", "trail", "partial")
HOLDS = (24, 48)


def events_v4(data, btc, rb=16, step=15, short=False):
    """Fresh closes above the prior 4h high on `step`-minute candles (15, or 5 with rb=48), with every stop /
    exit / hold variant scored. Holds are counted in 15-minute units (24 = 6 h, 48 = 12 h) on any step.
    short=True: the same on prices turned upside down, i.e. fresh closes BELOW the 4h low sold short: the stop
    sits above, the trail follows the lowest price, "regime" means BTC is below its 4h midpoint and "trend"
    means a downtrend (close < EMA50 < EMA200)."""
    scale = 15 // step
    sgn = -1 if short else 1
    btc_close = {t: sgn * c for t, c in zip(btc["t"], btc["c"]) if c is not None} if btc else {}
    bt = sorted(btc_close)
    evs = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"])
                if not datetime.fromtimestamp(t, UTC).minute % step and None not in (o, h, l, c)]
        if short:  # upside down: high <-> -low, so the long-only exit functions score a short
            rows = [(r[0], -r[1], -r[3], -r[2], -r[4], r[5]) for r in rows]
        if len(rows) < 300:
            continue
        closes = [r[4] for r in rows]
        e50, e200 = _ema(closes, 50), _ema(closes, 200)
        i = max(210, rb + 10)
        while i < len(rows) - 48 * scale:
            hi = max(r[2] for r in rows[i - rb:i])
            lo = min(r[3] for r in rows[i - rb:i])
            prev_hi = max(r[2] for r in rows[i - rb - 1:i - 1])
            if not (rows[i][4] > hi and rows[i - 1][4] <= prev_hi):
                i += 1
                continue
            entry, mid = rows[i][4], (hi + lo) / 2
            atr = _atr(rows, i)
            avg_v = sum(r[5] for r in rows[i - rb:i]) / rb
            regime = None
            if bt:
                j = bisect.bisect_right(bt, int(rows[i][0].timestamp()))
                k = bt[max(0, j - rb - 1):j]
                if len(k) > rb:
                    w = [btc_close[x] for x in k]
                    regime = w[-1] > (max(w[:-1]) + min(w[:-1])) / 2
            trend = "none"
            if entry > e50[i] and e50[i] > e200[i]:
                trend = "ema+slope" if e200[i] > e200[i - 4] else "ema"
            ev = {"sym": sym, "day": rows[i][0].date().isoformat(), "hour": rows[i][0].hour,
                  "vol_x": rows[i][5] / avg_v if avg_v else 0.0, "regime": regime, "trend": trend,
                  "range_pct": (hi - lo) / abs(entry) * 100, "out": {}, "stop_pct": {}, "fee_r": {}, "chase": {}}
            for sname, stop in (("mid", mid), ("atr1.5", entry - 1.5 * atr)):
                risk = entry - stop
                if risk <= 0:
                    continue
                ev["stop_pct"][sname] = risk / abs(entry) * 100
                ev["fee_r"][sname] = 2 * abs(entry) * FEE / risk
                ev["chase"][sname] = (entry - hi) / risk  # how far the close already is past the 4h high, in R
                for hold in HOLDS:
                    path = rows[i + 1:i + 1 + hold * scale]
                    for ex in EXITS:
                        if ex == "2R":
                            r = _fixed(path, entry, stop, 2.0)
                            cost = (2 * abs(entry) + sgn * 2 * risk) * FEE / risk
                        elif ex == "trail":
                            r, cost = _trail(path, entry, stop, atr), ev["fee_r"][sname]
                        else:
                            r, cost = _partial(path, entry, stop, atr), ev["fee_r"][sname]
                        ev["out"][(sname, ex, hold)] = r - cost
            evs.append(ev)
            i += 24 * scale  # one trade at a time per coin (6h), as in research.py
    evs.sort(key=lambda e: e["day"])
    return evs


GRID = {"stop": list(STOPS), "exit": list(EXITS), "hold": [48], "min_vol_x": [0.0, 1.0, 1.5],
        "regime": [False, True], "trend": ["off", "ema", "ema+slope"], "max_range_pct": [None, 1.0],
        "session": ["all", "active"], "max_fee_r": [0.25, 0.40], "max_chase_r": [None, 0.5]}
PRO = {"stop": "atr1.5", "exit": "partial", "hold": 48, "min_vol_x": 1.5, "regime": True, "trend": "ema",
       "max_range_pct": 1.0, "session": "active", "max_fee_r": 0.40, "max_chase_r": None}


def keep(ev, f):
    """Does this breakout pass the filters f? (the live rule uses min_stop_pct instead of max_fee_r)"""
    s = f["stop"]
    if s not in ev["stop_pct"]:
        return False
    if ev["vol_x"] < f["min_vol_x"] or (f["regime"] and ev["regime"] is not True):
        return False
    if f.get("trend", "off") == "ema" and ev["trend"] not in ("ema", "ema+slope"):
        return False
    if f.get("trend", "off") == "ema+slope" and ev["trend"] != "ema+slope":
        return False
    if f.get("max_range_pct") is not None and ev["range_pct"] > f["max_range_pct"]:
        return False
    if f.get("session", "all") == "active" and ev["hour"] < 6:
        return False
    if "min_stop_pct" in f and ev["stop_pct"][s] < f["min_stop_pct"]:
        return False
    if "max_fee_r" in f and ev["fee_r"][s] > f["max_fee_r"]:
        return False
    if f.get("max_chase_r") is not None and ev["chase"][s] > f["max_chase_r"]:
        return False
    return True


def score(events, f, split, stats):
    key = (f["stop"], f["exit"], f["hold"])
    ins, oos = {}, {}
    for ev in events:
        if key in ev["out"] and keep(ev, f):
            (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["out"][key])
    return {"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos)}


LIVE = {"stop": "mid", "exit": "2R", "hold": 24, "min_vol_x": 1.5, "regime": True, "min_stop_pct": 1.0}
# the rule the live bot runs (auto_crypto.py DEFAULTS, rules v6 = v4 without the chase skip, volume >= 1.0x)
# the live crypto SHORT rule (auto_crypto range_breakdown_4h): the long rule's filters, fixed 2R target
LIVE_SHORT = {"stop": "atr1.5", "exit": "2R", "hold": 48, "min_vol_x": 1.0, "regime": True, "trend": "off",
              "max_range_pct": None, "session": "active", "max_fee_r": 0.25, "max_chase_r": None}
LIVE_V4 = {"stop": "atr1.5", "exit": "trail", "hold": 48, "min_vol_x": 1.0, "regime": True, "trend": "off",
           "max_range_pct": None, "session": "active", "max_fee_r": 0.25, "max_chase_r": None}


def row(r, label=""):
    f, i, o = r["filters"], r["in_sample"], r["out_of_sample"]

    def s(x):
        if not x.get("trades"):
            return "no trades"
        return "%4d tr (%.1f/active day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
            x["worst_day_r"], x["max_drawdown_r"])
    parts = ["stop=%s" % f["stop"], "exit=%s" % f["exit"], "hold=%dh" % (f["hold"] // 4),
             "vol>=%.1f" % f["min_vol_x"], "btc=%s" % ("on" if f["regime"] else "off")]
    if "trend" in f:
        parts.append("trend=%s" % f["trend"])
    if "max_range_pct" in f:
        parts.append("range<=%s" % (("%.1f%%" % f["max_range_pct"]) if f["max_range_pct"] else "any"))
    if "session" in f:
        parts.append("hours=%s" % f["session"])
    if "max_fee_r" in f:
        parts.append("fees<=%.2fR" % f["max_fee_r"])
    if "min_stop_pct" in f:
        parts.append("stop>=%.1f%%" % f["min_stop_pct"])
    if "max_chase_r" in f:
        parts.append("chase<=%s" % (("%.1fR" % f["max_chase_r"]) if f["max_chase_r"] is not None else "off"))
    return "%s%s\n     in-sample   %s\n     OUT-sample  %s" % (label, " ".join(parts), s(i), s(o))


def main(a, syms, src, fetch_all, fetch, stats, out_dir, ist, step=15, short=False):
    iv = "%dm" % step
    print("Fetching 60 days of %s bars for %d coins (%s)..." % (iv, len(syms), src), flush=True)
    data, failed = fetch_all(syms, "-USD", iv, a.workers)
    btc = data.get("BTC") or fetch("BTC", "-USD", iv)
    events = events_v4(data, btc, rb=240 // step, step=step, short=short)
    if not events:
        print("No events: no data came back (check the internet / Yahoo).")
        return 1
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    live = score(events, LIVE, split, stats)
    pro = score(events, PRO, split, stats)
    res = [score(events, dict(zip(GRID, c)), split, stats) for c in itertools.product(*GRID.values())]
    ok = [r for r in res if r["in_sample"].get("trades", 0) >= 20 and r["out_of_sample"].get("trades", 0) >= 8]
    ok.sort(key=lambda r: -r["in_sample"]["avg_r"])
    stable = [r for r in ok if r["in_sample"]["avg_r"] > 0 and r["out_of_sample"]["avg_r"] > 0]
    stable.sort(key=lambda r: -min(r["in_sample"]["avg_r"], r["out_of_sample"]["avg_r"]))

    # which ingredient helps: average out-of-sample R of all combinations with vs without it
    def effect(name, on, off):
        a_ = [r["out_of_sample"]["avg_r"] for r in ok if r["filters"][name] == on]
        b_ = [r["out_of_sample"]["avg_r"] for r in ok if r["filters"][name] == off]
        if not a_ or not b_:
            return "  %-34s not enough trades to compare" % name
        ma, mb = sum(a_) / len(a_), sum(b_) / len(b_)
        return "  %-34s %+.2fR vs %+.2fR without  (%s)" % (
            "%s=%s" % (name, on), ma, mb, "helps" if ma > mb + 0.03 else "hurts" if ma < mb - 0.03 else "no clear effect")

    tight_n = sum(1 for e in events if e["range_pct"] <= 1.0)
    mode = ("crypto-v4" if step == 15 else "crypto-v4-%dm" % step) + ("-short" if short else "")
    cur = LIVE_SHORT if short else LIVE_V4
    lines = ["research.py %s  %s" % (mode, datetime.now(ist).strftime("%Y-%m-%d %H:%M IST")),
             "Candles: %s (4h range = %d candles, ATR(14) and the trailing stop on %s candles; holds are the same "
             "6 h / 12 h on every timeframe)." % (iv, 240 // step, iv),
             ("SHORT SIDE: fresh closes below the 4h low, sold short (stop above, trail follows the low; btc=on means "
              "BTC below its 4h midpoint, trend=ema means a downtrend)." if short else "Long side: fresh closes above the 4h high."),
             "%d coins, %d days (%s..%s), %d fresh 4h breaks (%d from a range under 1%%). R after %.3f%% fee "
             "each side (paper CRYPTO account). Out-of-sample = days from %s." % (len(data), len(days), days[0], days[-1], len(events),
                                                           tight_n, FEE * 100, split), "",
             row(live, "OLD LIVE RULE (v3):      "), "",
             row(score(events, cur, split, stats), "LIVE SHORT RULE NOW:     " if short else "LIVE RULE NOW (v6):      "), "",
             "LIVE RULE NEIGHBOURS (one setting changed at a time; a robust rule has neighbours that also do well):"]
    for k, vals in GRID.items():
        for v in vals:
            if v == cur[k]:
                continue
            f = dict(cur, **{k: v})
            lines.append(row(score(events, f, split, stats), "  %s=%s -> " % (k, v)))
    lines += ["",
             row(pro, "PRO SETUP (all 7 checks): "), "",
             "WHICH INGREDIENT HELPS (average OUT-sample R of the combinations with it vs without it):",
             effect("trend", "ema", "off"), effect("max_range_pct", 1.0, None), effect("session", "active", "all"),
             effect("regime", True, False), effect("min_vol_x", 1.0, 1.5), effect("min_vol_x", 1.5, 0.0), effect("stop", "atr1.5", "mid"),
             effect("exit", "partial", "2R"), effect("exit", "trail", "2R"), effect("max_fee_r", 0.40, 0.25),
             effect("max_chase_r", 0.5, None), "",
             "TOP 10 BY IN-SAMPLE (the OUT-sample line is the honest one):"]
    for n, r in enumerate(ok[:10], 1):
        lines.append(row(r, "%2d. " % n))
    lines += ["", "%d of %d combinations (with enough trades) were positive both in- and out-of-sample." % (
        len(stable), len(ok))]
    if stable:
        best = stable[0]
        lines += ["", "MOST CONSISTENT (best of its weaker half):", row(best, "  "), "",
                  "ITS NEIGHBOURS (one setting changed at a time; a robust rule has neighbours that also do well):"]
        for k, vals in GRID.items():
            for v in vals:
                if v != best["filters"].get(k):
                    lines.append(row(score(events, dict(best["filters"], **{k: v}), split, stats), "  %s=%s -> " % (k, v)))
    lines += ["", "Decision rule: switch the live bot to a rule only if it beats the CURRENT LIVE RULE out-of-sample",
              "with enough trades (20+), and its neighbours (one setting changed) also do well. ~60 days is short.",
              "Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report_%s.txt" % mode), "w", encoding="utf-8") as fh:
        fh.write(report)
    print("\nWrote %s" % os.path.join(out_dir, "report_%s.txt" % mode))
    return 0
