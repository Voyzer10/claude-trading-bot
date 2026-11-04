#!/usr/bin/env python3
"""
research_usorb.py - US opening-range breakout (the live auto_us rule) vs EARLIER entries, 5-minute candles,
walk-forward 70/30, R after an assumed 0.02% a side spread/slippage.

    python research.py us-orb

Why: the live US rule buys a 5-minute close above the first 15 minutes' high, so it enters AFTER the opening move
(3 Nov AAPL: the range itself was +2.25%, the bot bought its top). This tests ways to get in earlier or better:

  orb       the live rule: first close above the 15-minute range high (shorts: below the low)
  drive     opening drive: the 9:30 candle is strong (body >= 60% of its range, range >= 0.4% of price): enter at its
            close (9:35) in its direction, without waiting for the range
  squeeze   before the break: after 9:45 a green candle closes in the top 20% of a range it has not broken yet
  pullback  after an orb break, the first candle (within 6) that dips back to the range high and closes above it

Filters: max range width (any / 1.0% / 0.6% of price), in play (gap >= 1% or first-15-minute volume >= 2x its
5-day average), relative strength (stock up more than SPY since the open; shorts: down more), chase (orb: skip if
the entry is more than 0.5R past the range edge), entries until 11:00 or 15:30 ET, entry at the signal candle's
close or the NEXT candle's open (the bot's real delay), stop at the range middle or its far edge (drive: candle
middle / low), target 2R, trail (break-even at +1R, then 1R behind the best price) or hold to 15:55.
One trade per stock per day per direction. Min stop 0.3% of price (as live).
"""
import itertools
import os
from datetime import datetime, timezone

UTC = timezone.utc
COST = 0.0002          # a side
ENTRIES = ("orb", "drive", "squeeze", "pullback")
LIVE = {"entry": "orb", "side": "both", "width": None, "inplay": False, "rs": False, "lat": "next", "stop": "mid",
        "target": "2R", "until": 72, "chase": 0.5}


def _mirror(b):
    return (b[0], -b[1], -b[3], -b[2], -b[4], b[5])


def _days(d, et):
    """{ET date: [bars 9:30..15:55 as (t_et, o, h, l, c, v)]} with the 9:30 bar at index 0 (days missing it dropped)."""
    out = {}
    for t, o, h, l, c, v in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]):
        if None in (o, h, l, c):
            continue
        lt = datetime.fromtimestamp(t, UTC).astimezone(et)
        if (9, 30) <= (lt.hour, lt.minute) < (16, 0):
            out.setdefault(lt.date(), []).append((lt, o, h, l, c, v or 0))
    good = {}
    for day, bars in out.items():
        bars.sort(key=lambda b: b[0])
        if bars and (bars[0][0].hour, bars[0][0].minute) == (9, 30) and len(bars) >= 60:
            good[day] = bars
    return good


def _exit(path, entry, stop, target, trail):
    risk = entry - stop
    cur, armed, hi = stop, False, entry
    for b in path:
        if b[3] <= cur:
            return (cur - entry) / risk
        if trail:
            hi = max(hi, b[2])
            if not armed and hi >= entry + risk:
                armed, cur = True, max(cur, entry)
            if armed:
                cur = max(cur, hi - risk)
        elif target is not None and b[2] >= target:
            return (target - entry) / risk
    return ((path[-1][4] if path else entry) - entry) / risk


def _signals(B):
    """Long signals of one day's bars (mirror the bars for shorts): {entry: (bar index, stops dict)}."""
    orh, orl = max(b[2] for b in B[:3]), min(b[3] for b in B[:3])
    mid = (orh + orl) / 2
    out = {}
    b0 = B[0]
    rng0 = b0[2] - b0[3]
    if rng0 > 0 and b0[4] > b0[1] and (b0[4] - b0[1]) / rng0 >= 0.6 and rng0 / abs(b0[1]) >= 0.004:
        out["drive"] = (0, {"mid": (b0[2] + b0[3]) / 2, "far": b0[3]})
    k0 = None
    for k in range(3, len(B)):
        if B[k][4] > orh:
            k0 = k
            break
    if k0 is not None:
        out["orb"] = (k0, {"mid": mid, "far": orl})
        for j in range(k0 + 1, min(len(B), k0 + 7)):
            if B[j][3] <= orh and B[j][4] > orh:
                out["pullback"] = (j, {"mid": mid, "far": orl})
                break
    w = orh - orl
    for k in range(3, k0 if k0 is not None else len(B)):
        b, p = B[k], B[k - 1]
        if w > 0 and b[4] > b[1] and orh - 0.2 * w <= b[4] <= orh and b[3] > p[3]:
            out["squeeze"] = (k, {"mid": mid, "far": orl})
            break
    return out, orh, orl


def events_usorb(data, spy, et):
    sd = _days(spy, et) if spy else {}
    evs = []
    for sym, d in data.items():
        days = _days(d, et)
        keys = sorted(days)
        for n, day in enumerate(keys):
            B = days[day]
            prev = days[keys[n - 1]] if n else None
            gap = (B[0][1] / prev[-1][4] - 1) * 100 if prev else 0.0
            v15 = sum(b[5] for b in B[:3])
            past = [sum(b[5] for b in days[k][:3]) for k in keys[max(0, n - 5):n]]
            relvol = v15 / (sum(past) / len(past)) if past and sum(past) > 0 else 0.0
            inplay = abs(gap) >= 1.0 or relvol >= 2.0
            S = sd.get(day)
            for short in (False, True):
                bars = [_mirror(b) for b in B] if short else B
                sigs, orh, orl = _signals(bars)
                width = (orh - orl) / abs(bars[0][1]) * 100
                for name, (k, stops) in sigs.items():
                    ev = {"sym": sym, "day": day.isoformat(), "entry": name, "side": "short" if short else "long",
                          "k": k, "width": width, "inplay": inplay, "out": {}, "chase": None, "rs": None}
                    if S and len(S) > k:
                        sr = (S[k][4] / S[0][1] - 1) * (-1 if short else 1)
                        r = (bars[k][4] / bars[0][1] - 1)
                        ev["rs"] = r > sr
                    for lat in ("close", "next"):
                        if lat == "close":
                            e, start = bars[k][4], k + 1
                        else:
                            if k + 1 >= len(bars):
                                continue
                            e, start = bars[k + 1][1], k + 1
                        path = bars[start:78]
                        if not path:
                            continue
                        for sname, stop in stops.items():
                            risk = e - stop
                            if risk <= 0 or risk / abs(e) < 0.003:
                                continue
                            if name == "orb" and sname == "mid" and lat == "next":
                                ev["chase"] = (e - orh) / risk
                            cost = 2 * abs(e) * COST / risk
                            for tg in ("2R", "trail", "eod"):
                                tgt = e + 2 * risk if tg == "2R" else None
                                ev["out"][(lat, sname, tg)] = _exit(path, e, stop, tgt, tg == "trail") - cost
                    if ev["out"]:
                        evs.append(ev)
    evs.sort(key=lambda e: (e["day"], e["k"], e["sym"]))
    return evs


def keep(ev, f):
    if ev["entry"] != f["entry"] or (f["side"] != "both" and ev["side"] != f["side"]):
        return False
    if (f["lat"], f["stop"], f["target"]) not in ev["out"]:
        return False
    if f["width"] is not None and ev["width"] > f["width"]:
        return False
    if f["inplay"] and not ev["inplay"]:
        return False
    if f["rs"] and ev["rs"] is not True:
        return False
    if ev["k"] > f["until"]:
        return False
    if f["chase"] is not None and ev["entry"] == "orb" and (ev["chase"] is None or ev["chase"] > f["chase"]):
        return False
    return True


def score(events, f, split, stats):
    ins, oos, rs = {}, {}, []
    key = (f["lat"], f["stop"], f["target"])
    for ev in events:
        if keep(ev, f):
            (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["out"][key])
            rs.append(ev["out"][key])
    return {"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos), "rs": rs}


def row(r, label=""):
    f, i, o = r["filters"], r["in_sample"], r["out_of_sample"]

    def s(x):
        if not x.get("trades"):
            return "no trades"
        return "%4d tr (%.1f/day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
            x["worst_day_r"], x["max_drawdown_r"])
    parts = ["entry=%s" % f["entry"], "side=%s" % f["side"],
             "range<=%s" % ("any" if f["width"] is None else "%.1f%%" % f["width"]),
             "inplay=%s" % ("on" if f["inplay"] else "off"), "rs=%s" % ("on" if f["rs"] else "off"),
             "fill=%s" % ("next-open" if f["lat"] == "next" else "close"), "stop=%s" % f["stop"],
             "target=%s" % f["target"], "until=%s" % ("11:00" if f["until"] == 18 else "15:30"),
             "chase<=%s" % ("off" if f["chase"] is None else "%.1fR" % f["chase"])]
    return "%s%s\n     in-sample   %s\n     OUT-sample  %s" % (label, " ".join(parts), s(i), s(o))


def main(a, syms, src, fetch_all, fetch, stats, out_dir, ist):
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    print("Fetching 60 days of 5-minute bars for %d US symbols (%s) + SPY..." % (len(syms), src), flush=True)
    data, _ = fetch_all(syms, "", "5m", a.workers)
    spy = data.get("SPY") or fetch("SPY", "", "5m")
    events = events_usorb(data, spy, et)
    if not events:
        print("No events: no data came back (check the internet / Yahoo).")
        return 1
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    grid = {"entry": list(ENTRIES), "side": ["long", "short", "both"], "width": [None, 1.0, 0.6],
            "inplay": [False, True], "rs": [False, True], "lat": ["close", "next"], "stop": ["mid", "far"],
            "target": ["2R", "trail", "eod"], "until": [18, 72], "chase": [None, 0.5]}
    combos = list(itertools.product(*grid.values()))
    print("%d signals; scoring %d combinations..." % (len(events), len(combos)), flush=True)
    res = [score(events, dict(zip(grid, c)), split, stats) for c in combos]
    ok, seen = [], set()
    for r in res:
        if r["in_sample"].get("trades", 0) < 20 or r["out_of_sample"].get("trades", 0) < 10:
            continue
        sig = (r["filters"]["entry"], r["in_sample"]["trades"], r["in_sample"]["total_r"],
               r["out_of_sample"]["trades"], r["out_of_sample"]["total_r"])
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

    counts = {}
    for e in events:
        counts[(e["entry"], e["side"])] = counts.get((e["entry"], e["side"]), 0) + 1
    lines = ["research.py us-orb  %s" % datetime.now(ist).strftime("%Y-%m-%d %H:%M IST"),
             "US opening-range breakout (the live auto_us rule) vs earlier entries: opening drive, squeeze before the "
             "break, pullback after it.",
             "%d US stocks/ETFs, 5m candles, %d days (%s..%s). Signals: %s. R after 0.02%% a side. Out-of-sample = days "
             "from %s." % (len(data), len(days), days[0], days[-1],
                           ", ".join("%s %s %d" % (k[0], k[1], v) for k, v in sorted(counts.items())), split), "",
             row(score(events, LIVE, split, stats), "LIVE RULE NOW (orb, next-open fill, mid stop, 2R, chase 0.5R):  "),
             row(score(events, dict(LIVE, side="long"), split, stats), "  its longs:  "),
             row(score(events, dict(LIVE, side="short"), split, stats), "  its shorts: "), "",
             "EACH ENTRY, same settings as the live rule:"]
    for en in ENTRIES:
        lines.append(row(score(events, dict(LIVE, entry=en), split, stats), "  %-9s " % en))
    lines += ["", "WHICH INGREDIENT HELPS (average OUT-sample R of the combinations with it vs the alternative):",
              effect("entry", "drive", "orb"), effect("entry", "squeeze", "orb"), effect("entry", "pullback", "orb"),
              effect("width", 1.0, None), effect("width", 0.6, None), effect("inplay", True, False),
              effect("rs", True, False), effect("lat", "close", "next"), effect("stop", "far", "mid"),
              effect("target", "trail", "2R"), effect("target", "eod", "2R"), effect("until", 18, 72),
              effect("chase", 0.5, None), effect("side", "short", "long"), "",
              "TOP 10 BY IN-SAMPLE (the OUT-sample line is the honest one):"]
    for n, r in enumerate(ok[:10], 1):
        lines.append(row(r, "%2d. " % n))
    lines += ["", "%d of %d distinct combinations (with enough trades) were positive both in- and out-of-sample." % (
        len(stable), len(ok))]
    if stable:
        best = stable[0]
        rs = sorted(best["rs"], reverse=True)
        tot = sum(rs)
        lines += ["", "MOST CONSISTENT (best of its weaker half):", row(best, "  ")]
        if tot > 0 and len(rs) >= 10:
            lines.append("  concentration: the best 3 of %d trades = %.0f%% of the total %+.1fR" % (
                len(rs), 100 * sum(rs[:3]) / tot, tot))
        lines += ["", "ITS NEIGHBOURS (one setting changed at a time; a robust rule has neighbours that also do well):"]
        for k, vals in grid.items():
            for v in vals:
                if v != best["filters"][k]:
                    lines.append(row(score(events, dict(best["filters"], **{k: v}), split, stats),
                                     "  %s=%s -> " % (k, v)))
    lines += ["", "Luck check: with the low US costs about 5-10% of combinations look positive in both halves on random",
              "data. Trust a result only if its neighbours agree. Decision rule: change the live rule only if a",
              "combination beats it out-of-sample with 20+ trades and robust neighbours. ~60 days is short.",
              "Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report_us-orb.txt"), "w", encoding="utf-8") as fh:
        fh.write(report)
    print("\nWrote %s" % os.path.join(out_dir, "report_us-orb.txt"))
    return 0
