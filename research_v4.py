"""
research_v4.py - crypto strategy research, round 4: catch the clean breakouts the live rule skips.

Why: the live rule (v3) puts the stop at the middle of the 4h range and skips the trade when that stop is
closer than 1% (fees + noise). In quiet markets the 4h range is often only 0.3-0.6% wide, so most breakouts
from tight ranges are skipped, including ones that then run (TRX, 1 Nov). This tests other ways to trade them:

  stop    mid      middle of the 4h range (live)
          atrK     K x ATR(14) of the 15-minute bars below the entry (K = 1.0, 1.5, 2.0): sized to the
                   coin's own movement, not to how tight the range happened to be
  exit    2R / 3R  fixed target (live: 2R), time stop at the end of the hold
          trail    no fixed target: after +1R the stop moves to break-even, then trails 2 x ATR under the
                   highest high, so a run is ridden instead of cut at 2R
  hold    6h / 12h
  range   all breakouts, or only tight ranges (4h range under 0.6% / 1.0% of price): the "squeeze" setups
  filters volume vs the 4h average (0 / 1.5x / 2x), BTC regime on/off, minimum stop distance (0.5 / 1.0%)

Every trade pays 0.1% per side. Walk-forward as in research.py: the first 70% of days pick, the last 30% judge.
Read the OUT-sample lines. Run: python research.py crypto-v4
"""
import itertools
import os
from datetime import datetime

FEE = 0.001  # per side


def _atr(rows, i, n=14):
    trs = []
    for j in range(max(1, i - n + 1), i + 1):
        h, l, pc = rows[j][2], rows[j][3], rows[j - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
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


def _trail(path, entry, stop, atr, k_trail=2.0):
    risk = entry - stop
    cur, armed, hi = stop, False, entry
    for b in path:
        if b[3] <= cur:
            return (cur - entry) / risk
        hi = max(hi, b[2])
        if not armed and hi >= entry + risk:
            armed = True
            cur = max(cur, entry)
        if armed:
            cur = max(cur, hi - k_trail * atr)
    return ((path[-1][4] if path else entry) - entry) / risk


def events_v4(data, btc, rb=16):
    """Fresh 15-minute closes above the prior 4h high, with every stop / exit / hold variant scored."""
    from datetime import timezone
    import bisect
    UTC = timezone.utc
    btc_close = {t: c for t, c in zip(btc["t"], btc["c"])} if btc else {}
    bt = sorted(btc_close)
    evs = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"])
                if not datetime.fromtimestamp(t, UTC).minute % 15 and None not in (o, h, l, c)]
        i = rb + 15
        while i < len(rows) - 48:
            hi = max(r[2] for r in rows[i - rb:i])
            lo = min(r[3] for r in rows[i - rb:i])
            prev_hi = max(r[2] for r in rows[i - rb - 1:i - 1])
            if not (rows[i][4] > hi and rows[i - 1][4] <= prev_hi):
                i += 1
                continue
            entry, mid = rows[i][4], (hi + lo) / 2
            atr = _atr(rows, i)
            avg_v = sum(r[5] or 0 for r in rows[i - rb:i]) / rb
            regime = None
            if bt:
                ts = int(rows[i][0].timestamp())
                j = bisect.bisect_right(bt, ts)
                k = bt[max(0, j - rb - 1):j]
                if len(k) > rb:
                    w = [btc_close[x] for x in k]
                    regime = w[-1] > (max(w[:-1]) + min(w[:-1])) / 2
            ev = {"sym": sym, "day": rows[i][0].date().isoformat(), "vol_x": (rows[i][5] or 0) / avg_v if avg_v else 0.0,
                  "regime": regime, "range_pct": (hi - lo) / entry * 100, "out": {}, "stop_pct": {}}
            stops = {"mid": mid}
            for kk in (1.0, 1.5, 2.0):
                stops["atr%g" % kk] = entry - kk * atr
            for sname, stop in stops.items():
                risk = entry - stop
                if risk <= 0:
                    continue
                ev["stop_pct"][sname] = risk / entry * 100
                for hold in (24, 48):
                    path = rows[i + 1:i + 1 + hold]
                    for ex in ("2R", "3R", "trail"):
                        if ex == "trail":
                            r = _trail(path, entry, stop, atr)
                            cost = 2 * entry * FEE / risk
                        else:
                            tr = float(ex[0])
                            r = _fixed(path, entry, stop, tr)
                            cost = (2 * entry + tr * risk) * FEE / risk
                        ev["out"][(sname, ex, hold)] = r - cost
            evs.append(ev)
            i += 24  # one trade at a time per coin (6h), as in research.py
    evs.sort(key=lambda e: e["day"])
    return evs


GRID = {"stop": ["mid", "atr1", "atr1.5", "atr2"], "exit": ["2R", "3R", "trail"], "hold": [24, 48],
        "min_vol_x": [0.0, 1.5, 2.0], "regime": [False, True], "min_stop_pct": [0.5, 1.0],
        "max_range_pct": [None, 0.6, 1.0]}
LIVE = {"stop": "mid", "exit": "2R", "hold": 24, "min_vol_x": 1.5, "regime": True, "min_stop_pct": 1.0,
        "max_range_pct": None}


def run(events, split, stats):
    res = []
    for combo in itertools.product(*GRID.values()):
        f = dict(zip(GRID, combo))
        key = (f["stop"], f["exit"], f["hold"])
        ins, oos = {}, {}
        for ev in events:
            if key not in ev["out"]:
                continue
            if ev["vol_x"] < f["min_vol_x"] or (f["regime"] and ev["regime"] is not True):
                continue
            if ev["stop_pct"].get(f["stop"], 0) < f["min_stop_pct"]:
                continue
            if f["max_range_pct"] is not None and ev["range_pct"] > f["max_range_pct"]:
                continue
            (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["out"][key])
        res.append({"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos)})
    return res


def row(r, label=""):
    f, i, o = r["filters"], r["in_sample"], r["out_of_sample"]

    def s(x):
        if not x.get("trades"):
            return "no trades"
        return "%4d tr (%.1f/active day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
            x["worst_day_r"], x["max_drawdown_r"])
    fs = "stop=%s exit=%s hold=%dh vol>=%.1f regime=%s stop>=%.1f%% range<=%s" % (
        f["stop"], f["exit"], f["hold"] // 4, f["min_vol_x"], "on" if f["regime"] else "off", f["min_stop_pct"],
        ("%.1f%%" % f["max_range_pct"]) if f["max_range_pct"] else "any")
    return "%s%s\n     in-sample   %s\n     OUT-sample  %s" % (label, fs, s(i), s(o))


def main(a, syms, src, fetch_all, fetch, stats, out_dir, ist):
    print("Fetching 60 days of 15-minute bars for %d coins (%s)..." % (len(syms), src), flush=True)
    data, failed = fetch_all(syms, "-USD", "15m", a.workers)
    btc = data.get("BTC") or fetch("BTC", "-USD", "15m")
    events = events_v4(data, btc)
    if not events:
        print("No events: no data came back (check the internet / Yahoo).")
        return 1
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    res = run(events, split, stats)
    live = next(r for r in res if r["filters"] == LIVE)
    ok = [r for r in res if r["in_sample"].get("trades", 0) >= 20 and r["out_of_sample"].get("trades", 0) >= 8]
    ok.sort(key=lambda r: -r["in_sample"]["avg_r"])
    stable = [r for r in ok if r["in_sample"]["avg_r"] > 0 and r["out_of_sample"]["avg_r"] > 0]
    stable.sort(key=lambda r: -min(r["in_sample"]["avg_r"], r["out_of_sample"]["avg_r"]))
    tight = [r for r in stable if r["filters"]["max_range_pct"] is not None]
    trail = [r for r in stable if r["filters"]["exit"] == "trail"]
    tight_n = sum(1 for e in events if e["range_pct"] <= 1.0)
    lines = ["research.py crypto-v4  %s" % datetime.now(ist).strftime("%Y-%m-%d %H:%M IST"),
             "%d coins, %d days (%s..%s), %d fresh breakouts (%d from a 4h range under 1%%), %d combinations. "
             "R after 0.1%% fee each side. Out-of-sample = days from %s." % (
                 len(data), len(days), days[0], days[-1], len(events), tight_n, len(res), split), "",
             row(live, "CURRENT LIVE RULE (v3):  "), "",
             "TOP 10 BY IN-SAMPLE (the OUT-sample line is the honest one):"]
    for n, r in enumerate(ok[:10], 1):
        lines.append(row(r, "%2d. " % n))
    lines += ["", "%d of %d combinations (with enough trades) were positive both in- and out-of-sample." % (
        len(stable), len(ok))]
    if stable:
        lines += ["", "MOST CONSISTENT (best of its weaker half):", row(stable[0], "  ")]
    lines += ["", "Best consistent rule for TIGHT-RANGE breakouts (the ones v3 skips):",
              row(tight[0], "  ") if tight else "  none was positive both in- and out-of-sample",
              "", "Best consistent rule with a TRAILING exit (ride the run):",
              row(trail[0], "  ") if trail else "  none was positive both in- and out-of-sample",
              "", "Switch the live rule only if a rule beats the CURRENT LIVE RULE out-of-sample with enough trades,",
              "and is not a lone lucky combination (look for its neighbours doing well too). ~60 days is short.",
              "Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report_crypto-v4.txt"), "w", encoding="utf-8") as fh:
        fh.write(report)
    print("\nWrote %s" % os.path.join(out_dir, "report_crypto-v4.txt"))
    return 0
