#!/usr/bin/env python3
"""
research_nse2.py - NSE opening-range breakout, v2 variants (python research.py nse-v2).

Why: the live NSE rule (15-minute range, stop at the range midpoint) has stops of ~0.5%. The INDIA paper
account caps a position at 25% of Rs 50,000, so a 0.5% stop risks only ~Rs 60 while a round trip costs
~Rs 10-12 in brokerage, STT, exchange fees, stamp and GST: about 0.2R before the trade starts. The 31 Oct
backtest found no edge after charges. This mode tries what fixed the same problem in crypto (rules v4):

  range      15 or 30 minutes from 9:15
  stop       range midpoint (live) | range low | 2 x ATR(14, 5m) | 3 x ATR(14, 5m) under the entry
  exit       2R target with break-even at +1R (live) | trailing (break-even at +1R, then 2 x ATR under
             the high) | stop only, out at 15:15
  entry by   10:30 | 11:30 | 13:00 (first 5-minute close above the range)
  filters    breakout volume >= 1.0x or 1.5x the 6 bars before it (or off); Nifty above its own range midpoint and open;
             charges at most 0.15R / 0.25R of the risk (like the crypto fee cap); chase at most 0.5R
             past the range high; opening gap within 3% (always on, as live)

Positions are sized like the live INDIA account (max loss per trade, position cap) and every R is after
paper.py's india_charges. One trade per stock per day; every flat by 15:15. The live time machine gate is
not modelled. Walk-forward 70/30: trust the out-of-sample line.
"""
import itertools
import os
from datetime import datetime, timedelta

import paper as P

FLAT = (15, 15)
LAST_ENTRY = "13:00"
STOPS = ("mid", "low", "atr2", "atr3")
EXITS = ("2R", "trail", "close")
TRAIL_K = 2.0

GRID = {"range": [15, 30], "stop": list(STOPS), "exit": list(EXITS), "entry_end": ["10:30", "11:30", "13:00"],
        "min_vol_x": [0.0, 1.0, 1.5], "regime": [False, True], "max_cost_r": [0.15, 0.25, None],
        "max_chase_r": [None, 0.5]}
# what the live bot runs now (auto_nse.py DEFAULTS), minus the time machine gate
LIVE = {"range": 15, "stop": "mid", "exit": "2R", "entry_end": "11:30", "min_vol_x": 1.0, "regime": True,
        "max_cost_r": None, "max_chase_r": 0.5, "min_stop_pct": 0.4}


# ------------------------------------------------------------------ trade outcomes (R before charges)

def _target_be(path, entry, stop, target_r=2.0):
    risk = entry - stop
    cur, be = stop, False
    for b in path:
        if b[3] <= cur:
            return (cur - entry) / risk
        if b[2] >= entry + target_r * risk:
            return target_r
        if not be and b[2] >= entry + risk:
            cur, be = max(cur, entry), True   # from the next bar
    return ((path[-1][4] if path else entry) - entry) / risk


def _trail(path, entry, stop, atr, k=TRAIL_K):
    risk = entry - stop
    cur, armed, hi = stop, False, entry
    for b in path:
        if b[3] <= cur:
            return (cur - entry) / risk
        hi = max(hi, b[2])
        if not armed and hi >= entry + risk:
            armed, cur = True, max(cur, entry)
        if armed:
            cur = max(cur, hi - k * atr)
    return ((path[-1][4] if path else entry) - entry) / risk


def _close(path, entry, stop):
    risk = entry - stop
    for b in path:
        if b[3] <= stop:
            return -1.0
    return ((path[-1][4] if path else entry) - entry) / risk


# ------------------------------------------------------------------ events

def _atr_series(bars, n=14):
    out, trs = [], []
    for i, b in enumerate(bars):
        pc = bars[i - 1][4] if i else b[4]
        trs.append(max(b[2] - b[3], abs(b[2] - pc), abs(b[3] - pc)))
        out.append(sum(trs[-n:]) / n if i >= n - 1 else None)
    return out


def events_nse2(data, nifty, bars_by_day, ist, add_history=None):
    cfg = P.DEFAULT_CONFIG
    acc = cfg["accounts"]["INDIA"]
    nday = bars_by_day(nifty, ist, 5) if nifty else {}
    events = []
    for sym, d in data.items():
        days = bars_by_day(d, ist, 5)
        flat_list = [b for day in sorted(days) for b in days[day]]
        atr_all = _atr_series(flat_list)
        atr_at = {b[0]: a for b, a in zip(flat_list, atr_all)}
        prev_close = None
        for day in sorted(days):
            bars = days[day]
            o_start = datetime(day.year, day.month, day.day, 9, 15, tzinfo=ist)
            flat = o_start.replace(hour=FLAT[0], minute=FLAT[1])
            gap = (bars[0][1] / prev_close - 1) * 100 if prev_close else 0.0
            prev_close = bars[-1][4]
            if abs(gap) > 3.0:
                continue
            nb = nday.get(day)
            for rmin in (15, 30):
                rng = [b for b in bars if o_start <= b[0] < o_start + timedelta(minutes=rmin)]
                if len(rng) < rmin // 5:
                    continue
                hi, lo = max(b[2] for b in rng), min(b[3] for b in rng)
                after = [b for b in bars if b[0] >= o_start + timedelta(minutes=rmin)]
                for i, b in enumerate(after):
                    end = b[0] + timedelta(minutes=5)
                    if end.strftime("%H:%M") > LAST_ENTRY:
                        break
                    if b[4] <= hi:
                        continue
                    entry = b[4]
                    atr = atr_at.get(b[0])
                    prior = (rng + after[:i])[-6:]
                    base = sum(x[5] for x in prior) / len(prior)
                    regime = None
                    if nb:
                        nr = [x for x in nb if o_start <= x[0] < o_start + timedelta(minutes=rmin)]
                        upto = [x for x in nb if x[0] + timedelta(minutes=5) <= end]
                        if nr and upto:
                            nmid = (max(x[2] for x in nr) + min(x[3] for x in nr)) / 2
                            regime = upto[-1][4] > nmid and upto[-1][4] > nb[0][1]
                    path = [x for x in after[i + 1:] if x[0] < flat]
                    stops = {"mid": (hi + lo) / 2, "low": lo}
                    if atr:
                        stops["atr2"] = entry - 2 * atr
                        stops["atr3"] = entry - 3 * atr
                    ev = {"sym": sym, "day": day.isoformat(), "time": end.strftime("%H:%M"), "range": rmin,
                          "vol_x": b[5] / base if base else 0.0, "regime": regime,
                          "out": {}, "cost": {}, "chase": {}, "stop_pct": {}}
                    for sname, stop in stops.items():
                        risk = entry - stop
                        if risk <= 0:
                            continue
                        qty = int(min(acc["max_loss_per_trade"] / risk,
                                      acc["capital"] * acc["max_position_pct"] / 100 / entry))
                        if qty < 1:
                            continue
                        for ex in EXITS:
                            exit_px = entry + 2 * risk if ex == "2R" else entry  # sell value for the charges
                            cost = (P.charges(cfg, "NSE", sym, "buy", qty * entry)
                                    + P.charges(cfg, "NSE", sym, "sell", qty * exit_px)) / (qty * risk)
                            if ex == "2R":
                                r = _target_be(path, entry, stop)
                            elif ex == "trail":
                                r = _trail(path, entry, stop, atr or risk / 2)
                            else:
                                r = _close(path, entry, stop)
                            ev["out"][(sname, ex)] = r - cost
                            ev["cost"][(sname, ex)] = cost
                        ev["chase"][sname] = (entry - hi) / risk
                        ev["stop_pct"][sname] = risk / entry * 100
                    if ev["out"]:
                        events.append(ev)
                    break  # one trade per stock per day per range length
    events.sort(key=lambda e: (e["day"], e["time"]))
    return events


# ------------------------------------------------------------------ scoring

def keep(ev, f):
    s = f["stop"]
    if ev["range"] != f["range"] or (s, f["exit"]) not in ev["out"]:
        return False
    if ev["time"] > f["entry_end"] or ev["vol_x"] < f["min_vol_x"]:
        return False
    if f["regime"] and ev["regime"] is not True:
        return False
    if f["max_cost_r"] is not None and ev["cost"][(s, f["exit"])] > f["max_cost_r"]:
        return False
    if f["max_chase_r"] is not None and ev["chase"][s] > f["max_chase_r"]:
        return False
    if f.get("min_stop_pct") and ev["stop_pct"][s] < f["min_stop_pct"]:
        return False
    return True


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
        return "%4d tr (%.1f/day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
            x["worst_day_r"], x["max_drawdown_r"])
    parts = ["range=%dm" % f["range"], "stop=%s" % f["stop"], "exit=%s" % f["exit"], "until=%s" % f["entry_end"],
             "vol>=%.1f" % f["min_vol_x"], "nifty=%s" % ("on" if f["regime"] else "off"),
             "charges<=%s" % (("%.2fR" % f["max_cost_r"]) if f["max_cost_r"] is not None else "any"),
             "chase<=%s" % (("%.1fR" % f["max_chase_r"]) if f["max_chase_r"] is not None else "off")]
    if f.get("min_stop_pct"):
        parts.append("stop>=%.1f%%" % f["min_stop_pct"])
    return "%s%s\n     in-sample   %s\n     OUT-sample  %s" % (label, " ".join(parts), s(i), s(o))


def main(a, syms, src, fetch_all, fetch, stats, bars_by_day, out_dir, ist):
    print("Fetching 60 days of 5-minute bars for %d NSE symbols (%s) + Nifty 50..." % (len(syms), src), flush=True)
    data, failed = fetch_all(syms, ".NS", "5m", a.workers)
    nifty = fetch("^NSEI", "", "5m")
    events = events_nse2(data, nifty, bars_by_day, ist)
    import tm_test
    tm_test.add_history(events)
    k2 = lambda f: (f["stop"], f["exit"])
    if not events:
        print("No events: no data came back (check the internet / Yahoo).")
        return 1
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    print("%d charts (%d failed), %d days, %d breakouts. Scoring %d combinations..." % (
        len(data), len(failed), len(days), len(events), len(list(itertools.product(*GRID.values())))), flush=True)
    by_range = {r: [e for e in events if e["range"] == r] for r in GRID["range"]}
    res = []
    for c in itertools.product(*GRID.values()):
        f = dict(zip(GRID, c))
        res.append(score(by_range[f["range"]], f, split, stats))
    live = score(by_range[15], LIVE, split, stats)
    ok = [r for r in res if r["in_sample"].get("trades", 0) >= 30 and r["out_of_sample"].get("trades", 0) >= 10]
    ok.sort(key=lambda r: -r["in_sample"]["avg_r"])
    stable = [r for r in ok if r["in_sample"]["avg_r"] > 0 and r["out_of_sample"]["avg_r"] > 0]
    stable.sort(key=lambda r: -min(r["in_sample"]["avg_r"], r["out_of_sample"]["avg_r"]))

    def effect(name, on, off):
        a_ = [r["out_of_sample"]["avg_r"] for r in ok if r["filters"][name] == on]
        b_ = [r["out_of_sample"]["avg_r"] for r in ok if r["filters"][name] == off]
        if not a_ or not b_:
            return "  %-26s not enough trades to compare" % ("%s=%s" % (name, on))
        ma, mb = sum(a_) / len(a_), sum(b_) / len(b_)
        return "  %-26s %+.2fR vs %+.2fR with %s  (%s)" % (
            "%s=%s" % (name, on), ma, mb, off, "helps" if ma > mb + 0.03 else "hurts" if ma < mb - 0.03 else "no clear effect")

    # how much the charges take, by stop type (15-minute range, 2R exit, every breakout)
    cost_lines = []
    for s in STOPS:
        cs = [e["cost"][(s, "2R")] for e in by_range[15] if (s, "2R") in e["cost"]]
        sp = [e["stop_pct"][s] for e in by_range[15] if s in e["stop_pct"]]
        if cs:
            cs.sort()
            cost_lines.append("  stop=%-5s median stop %.2f%% away, charges median %.2fR (a quarter of trades above %.2fR)"
                              % (s, sorted(sp)[len(sp) // 2], cs[len(cs) // 2], cs[int(len(cs) * 0.75)]))

    lines = ["research.py nse-v2  %s" % datetime.now(ist).strftime("%Y-%m-%d %H:%M IST"),
             "%d NSE charts, %d days (%s..%s), %d breakouts (15m and 30m ranges). R after india_charges, sized like "
             "the live INDIA account (max loss Rs %s, position cap %s%% of Rs %s). Out-of-sample = days from %s." % (
                 len(data), len(days), days[0], days[-1], len(events), P.DEFAULT_CONFIG["accounts"]["INDIA"]["max_loss_per_trade"],
                 P.DEFAULT_CONFIG["accounts"]["INDIA"]["max_position_pct"], P.DEFAULT_CONFIG["accounts"]["INDIA"]["capital"], split),
             "No daily cap: every qualifying breakout counts (the live account takes at most 5 a day).", "",
             "WHAT THE CHARGES TAKE (15m range, 2R exit):"] + cost_lines + ["",
             row(live, "LIVE NSE RULE NOW (no time machine): "), "",
             "WHICH INGREDIENT HELPS (average OUT-sample R of the combinations with it vs the alternative):",
             effect("stop", "low", "mid"), effect("stop", "atr2", "mid"), effect("stop", "atr3", "mid"),
             effect("exit", "trail", "2R"), effect("exit", "close", "2R"), effect("range", 30, 15),
             effect("entry_end", "10:30", "13:00"), effect("min_vol_x", 1.0, 1.5), effect("min_vol_x", 1.5, 0.0), effect("regime", True, False),
             effect("max_cost_r", 0.15, None), effect("max_cost_r", 0.25, None), effect("max_chase_r", 0.5, None), "",
             "TOP 10 BY IN-SAMPLE (the OUT-sample line is the honest one):"]
    for n, r in enumerate(ok[:10], 1):
        lines.append(row(r, "%2d. " % n))
    if ok and not [r for r in ok if r["in_sample"]["avg_r"] > 0 and r["out_of_sample"]["avg_r"] > 0]:
        lines += [""] + tm_test.section(by_range[ok[0]["filters"]["range"]], ok[0]["filters"], k2(ok[0]["filters"]), keep,
                                        split, stats, "the best in-sample combination (can a history gate rescue it?)")
    lines += [""] + tm_test.section(by_range[15], LIVE, k2(LIVE), keep, split, stats,
                                    "the live NSE rule (its +0.10R time machine gate, history half)")
    lines += ["", "%d of %d combinations (with enough trades) were positive both in- and out-of-sample." % (len(stable), len(ok))]
    if stable:
        best = stable[0]
        lines += [""] + tm_test.section(by_range[best["filters"]["range"]], best["filters"], k2(best["filters"]), keep,
                                        split, stats, "the most consistent combination")
        lines += ["", "MOST CONSISTENT (best of its weaker half):", row(best, "  "), "",
                  "ITS NEIGHBOURS (one setting changed at a time; a robust rule has neighbours that also do well):"]
        for k, vals in GRID.items():
            for v in vals:
                if v == best["filters"][k]:
                    continue
                f = dict(best["filters"], **{k: v})
                lines.append(row(score(by_range[f["range"]], f, split, stats), "  %s=%s -> " % (k, v)))
    lines += ["", "Decision rule: move the live NSE rule only to a combination that is positive out-of-sample with 20+",
              "trades, beats the live rule, and whose neighbours are mostly positive too. Then paper-trade it before",
              "real money. ~60 days is a short sample. Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report_nse-v2.txt"), "w", encoding="utf-8") as fh:
        fh.write(report)
    print("\nWrote %s" % os.path.join(out_dir, "report_nse-v2.txt"))
    return 0
