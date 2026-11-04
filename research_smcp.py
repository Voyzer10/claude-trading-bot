#!/usr/bin/env python3
"""
research_smcp.py - backtest of the user's SMC Trading Playbook (smc_playbook.py), as the playbook's own
section 13 asks: each setup separately, candle 1 vs candle 2, with and without the structure (BOS/CHoCH) rule,
stop buffers, liquidity targets vs fixed / trailing exits, walk-forward 70/30.

    python research.py crypto-smcp       # crypto, 15-minute candles (the playbook's intraday execution frame)
    python research.py crypto-smcp-5m    # crypto, 5-minute candles
    python research.py nse-smcp          # NSE stocks, 5-minute candles, intraday (flat by 15:15)

Grid: setup (doji_long, doji_short, star_long, hammer_short, longs, shorts, all) x confirmation (candle 1 only, or
1 or 2) x structure (none, BOS/CHoCH before the sweep, any up to confirmation) x doji body (10%, 15%) x stop buffer
(0.1, 0.25 ATR) x target (internal liquidity, external liquidity, 2R, trail) x BTC/Nifty filter x hours (crypto).
A trade whose target is under 1R away is skipped. One trade per symbol at a time (4-hour spacing).
R is after fees (crypto: the paper CRYPTO fee; NSE: paper.py's india charges, sized like the INDIA account).
"""
import bisect
import itertools
import os
from datetime import datetime, timedelta, timezone

import smc_playbook as M

UTC = timezone.utc
BUFFERS = (0.1, 0.25)
TARGETS = ("internal", "external", "2R", "trail")
MIN_RR = 1.0
PLAYBOOK = {"setup": "playbook", "confirm": 2, "struct": "before", "doji_pct": 0.15, "buffer": 0.1, "target": "internal",
            "regime": False, "liq": "base", "disp": 0.0, "session": "all"}
SETUP_GRID = ["doji_long", "doji_short", "star_long", "hammer_short", "fvg_long", "fvg_short", "ob_long", "ob_short",
              "playbook", "zones", "all"]


def _mirror(rows):
    return [(r[0], -r[1], -r[3], -r[2], -r[4], r[5]) for r in rows]


def _exit(path, entry, stop, target, trail_atr=None):
    """R of a long over path (t,o,h,l,c,v): stop first if a bar touches both; out at the last close."""
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


def events_smcp(data, day_of, hold, cost_fn, regime_fn=None, entry_ok=None, path_end=None):
    """data {sym: chart}; day_of(t) -> day key for PDH/CDH; hold in candles; cost_fn(sym, entry, stop, exit_px,
    side) -> R of costs (None = untradeable); regime_fn(t, side) -> True if the market filter agrees; entry_ok(t);
    path_end(t_entry) -> last time the trade may stay open (NSE flat by 15:15)."""
    evs = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]) if None not in (o, h, l, c)]
        if len(rows) < 200:
            continue
        ctx = M.Context(rows, day_of)
        mrows = _mirror(rows)
        for i in range(40, len(rows) - 2):
            if entry_ok and not entry_ok(rows[i][0]):
                continue
            for s in (M.find_setups(ctx, i, doji_pct=0.15, near_atr=0.5, struct_lookback=48, max_confirm=2)
                      + M.zone_setups(ctx, i)):
                long = s["side"] == "long"
                end = path_end(rows[i][0]) if path_end else None
                src = rows if long else mrows
                path = [b for b in src[i + 1:i + 1 + hold] if end is None or b[0] < end]
                if not path:
                    continue
                ev = {"sym": sym, "day": rows[i][0].date().isoformat(), "i": i, "hour": rows[i][0].hour,
                      "setup": s["setup"], "side": s["side"], "confirm_at": s["confirm_at"],
                      "struct_before": s["struct_before"], "struct_any": s["struct_any"], "body_pct": s["body_pct"],
                      "level": s["level_name"], "strong": s["level_name"] in M.MAJOR or s.get("eq", False),
                      "disp": s.get("disp", 0.0), "regime": regime_fn(rows[i][0], s["side"]) if regime_fn else None,
                      "out": {}, "rr": {}}
                for buf in BUFFERS:
                    stop = M.stop_for(s, buf)
                    risk = (s["entry"] - stop) if long else (stop - s["entry"])
                    if risk <= 0:
                        continue
                    for tg in TARGETS:
                        tp = M.target_for(ctx, i, s, tg, stop)
                        if tp is None:
                            continue
                        rr = abs(tp - s["entry"]) / risk
                        if tg in ("internal", "external") and rr < MIN_RR:
                            continue
                        sgn = 1 if long else -1
                        e, st, tgt = sgn * s["entry"], sgn * stop, sgn * tp
                        r = _exit(path, e, st, tgt, trail_atr=s["atr"] if tg == "trail" else None)
                        cost = cost_fn(sym, s["entry"], stop, s["entry"] if tg == "trail" else tp, s["side"])
                        if cost is None:
                            continue
                        ev["out"][(buf, tg)] = r - cost
                        ev["rr"][(buf, tg)] = rr
                if ev["out"]:
                    evs.append(ev)
    evs.sort(key=lambda e: (e["day"], e["sym"], e["i"]))
    return evs


GROUPS = {"playbook": set(M.SETUPS), "zones": set(M.ZONE_SETUPS), "all": set(M.SETUPS) | set(M.ZONE_SETUPS),
          "longs": M.LONG, "shorts": (set(M.SETUPS) | set(M.ZONE_SETUPS)) - M.LONG}
_POOLS = {}


def _pool(events, st):
    """Only the events of the setup(s) a combination can keep (scoring every event for every combination is slow)."""
    key = (id(events), st)
    if key not in _POOLS:
        names = GROUPS.get(st, {st})
        _POOLS[key] = [e for e in events if e["setup"] in names]
    return _POOLS[key]


def keep(ev, f):
    st = f["setup"]
    if ev["setup"] not in GROUPS.get(st, {st}):
        return False
    liq = f.get("liq", "base")
    if liq == "base" and ev["level"] in ("PWH", "PWL"):
        return False
    if liq == "strong" and ev["setup"] in M.SETUPS and not ev["strong"]:
        return False
    if ev["disp"] < f.get("disp", 0.0):
        return False
    if (f["buffer"], f["target"]) not in ev["out"]:
        return False
    if ev["confirm_at"] > f["confirm"]:
        return False
    if f["struct"] == "before" and not ev["struct_before"] or f["struct"] == "any" and not ev["struct_any"]:
        return False
    if ev["setup"].startswith("doji") and ev["body_pct"] > f["doji_pct"]:
        return False
    if f["regime"] and ev["regime"] is not True:
        return False
    if f.get("session") == "active" and ev["hour"] < 6:
        return False
    return True


def score(events, f, split, stats, spacing):
    ins, oos, last = {}, {}, {}
    k = (f["buffer"], f["target"])
    for ev in _pool(events, f["setup"]):
        if not keep(ev, f):
            continue
        if ev["sym"] in last and ev["i"] - last[ev["sym"]] < spacing:   # one trade per symbol at a time
            continue
        last[ev["sym"]] = ev["i"]
        (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["out"][k])
    return {"filters": f, "in_sample": stats(ins), "out_of_sample": stats(oos),
            "rs": [r for d in (ins, oos) for v in d.values() for r in v]}


def concentration(r):
    """Rulebook: do a few trades make all the money? Share of the total R from the best 3 trades."""
    rs = sorted(r.get("rs", []), reverse=True)
    tot = sum(rs)
    if len(rs) < 10 or tot <= 0:
        return "  concentration: not meaningful (total R not positive or under 10 trades)"
    top = sum(rs[:3])
    return "  concentration: the best 3 of %d trades = %.0f%% of the total %+.1fR%s" % (
        len(rs), 100 * top / tot, tot, "  <- a few lucky trades carry it" if top >= 0.6 * tot else "")


def row(r, label=""):
    f, i, o = r["filters"], r["in_sample"], r["out_of_sample"]

    def s(x):
        if not x.get("trades"):
            return "no trades"
        return "%4d tr (%.1f/day)  win %3.0f%%  avg %+.2fR  total %+6.1fR  worst day %+.1fR  dd %+.1fR" % (
            x["trades"], x["trades"] / max(1, x["days_traded"]), 100 * x["win_rate"], x["avg_r"], x["total_r"],
            x["worst_day_r"], x["max_drawdown_r"])
    parts = ["setup=%s" % f["setup"], "confirm=%s" % ("c1" if f["confirm"] == 1 else "c1/c2"),
             "struct=%s" % f["struct"], "doji<=%d%%" % round(100 * f["doji_pct"]), "buffer=%.2fATR" % f["buffer"],
             "target=%s" % f["target"], "mkt=%s" % ("with" if f["regime"] else "off"),
             "liq=%s" % f.get("liq", "base"), "disp>=%.1fATR" % f.get("disp", 0.0)]
    if "session" in f:
        parts.append("hours=%s" % f["session"])
    return "%s%s\n     in-sample   %s\n     OUT-sample  %s" % (label, " ".join(parts), s(i), s(o))


def main(a, syms, src, fetch_all, fetch, stats, out_dir, ist, market="crypto", step=15):
    import paper as P
    import tm_test
    if market == "crypto":
        iv = "%dm" % step
        print("Fetching 60 days of %s bars for %d coins (%s)..." % (iv, len(syms), src), flush=True)
        data, failed = fetch_all(syms, "-USD", iv, a.workers)
        btc = data.get("BTC") or fetch("BTC", "-USD", iv)
        fee = float(P.load_config()["accounts"]["CRYPTO"]["fee_pct"]) / 100
        bt = sorted(btc["t"]) if btc else []
        bc = dict(zip(btc["t"], btc["c"])) if btc else {}
        rb = 240 // step

        def regime_fn(t, side):
            j = bisect.bisect_right(bt, int(t.timestamp()))
            k = bt[max(0, j - rb - 1):j]
            w = [bc[x] for x in k if bc.get(x) is not None]
            if len(w) <= rb:
                return None
            up = w[-1] > (max(w[:-1]) + min(w[:-1])) / 2
            return up if side == "long" else not up

        def cost_fn(sym, entry, stop, exit_px, side):
            return (entry + exit_px) * fee / abs(entry - stop)

        events = events_smcp(data, lambda t: t.date(), hold=12 * 60 // step, cost_fn=cost_fn, regime_fn=regime_fn)
        grid = {"setup": SETUP_GRID, "confirm": [1, 2], "struct": ["none", "before", "any"], "doji_pct": [0.10, 0.15],
                "buffer": list(BUFFERS), "target": list(TARGETS), "regime": [False, True], "liq": ["base", "all", "strong"],
                "disp": [0.0, 0.7], "session": ["all", "active"]}
        spacing = 240 // step
        mode = "crypto-smcp" + ("" if step == 15 else "-%dm" % step)
        what = "%d coins, %s candles" % (len(data), iv)
    else:
        print("Fetching 60 days of 5-minute bars for %d NSE symbols (%s) + Nifty 50..." % (len(syms), src), flush=True)
        data, failed = fetch_all(syms, ".NS", "5m", a.workers)
        nifty = fetch("^NSEI", "", "5m")
        cfg = P.DEFAULT_CONFIG
        acc = cfg["accounts"]["INDIA"]
        nt = sorted(nifty["t"]) if nifty else []
        nc = dict(zip(nifty["t"], nifty["c"])) if nifty else {}

        def regime_fn(t, side):   # Nifty above (long) / below (short) its own close of an hour earlier
            j = bisect.bisect_right(nt, int(t.timestamp()))
            if j < 13:
                return None
            now, ago = nc.get(nt[j - 1]), nc.get(nt[j - 13])
            if now is None or ago is None:
                return None
            return now > ago if side == "long" else now < ago

        def cost_fn(sym, entry, stop, exit_px, side):
            risk = abs(entry - stop)
            qty = int(min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / entry))
            if qty < 1:
                return None
            o, c = ("buy", "sell") if side == "long" else ("sell", "buy")
            return (P.charges(cfg, "NSE", sym, o, qty * entry) + P.charges(cfg, "NSE", sym, c, qty * exit_px)) / (qty * risk)

        def entry_ok(t):
            lt = t.astimezone(ist)
            return (9, 30) <= (lt.hour, lt.minute) <= (14, 30)

        def path_end(t):
            lt = t.astimezone(ist)
            return lt.replace(hour=15, minute=15, second=0, microsecond=0)

        events = events_smcp(data, lambda t: t.astimezone(ist).date(), hold=75, cost_fn=cost_fn, regime_fn=regime_fn,
                             entry_ok=entry_ok, path_end=path_end)
        grid = {"setup": SETUP_GRID, "confirm": [1, 2], "struct": ["none", "before", "any"], "doji_pct": [0.10, 0.15],
                "buffer": list(BUFFERS), "target": list(TARGETS), "regime": [False, True], "liq": ["base", "all", "strong"],
                "disp": [0.0, 0.7]}
        spacing = 48
        mode = "nse-smcp"
        what = "%d NSE stocks, 5m candles, intraday" % len(data)

    if not events:
        print("No events: no data came back (check the internet / Yahoo).")
        return 1
    days = sorted({e["day"] for e in events})
    split = days[int(len(days) * 0.7)]
    tm_test.add_history(events)
    pb = dict(PLAYBOOK) if market == "crypto" else {k: v for k, v in PLAYBOOK.items() if k != "session"}
    print("%d setups found; scoring %d combinations..." % (len(events), len(list(itertools.product(*grid.values())))),
          flush=True)
    res = [score(events, dict(zip(grid, c)), split, stats, spacing) for c in itertools.product(*grid.values())]
    ok, seen = [], set()
    for r in res:   # many settings are no-ops for some setups (doji size for an FVG): keep one of identical results
        if r["in_sample"].get("trades", 0) < 20 or r["out_of_sample"].get("trades", 0) < 10:
            continue
        sig = (r["filters"]["setup"], r["in_sample"]["trades"], r["in_sample"]["total_r"],
               r["out_of_sample"]["trades"], r["out_of_sample"]["total_r"])
        if sig not in seen:
            seen.add(sig)
            ok.append(r)
    ok.sort(key=lambda r: -r["in_sample"]["avg_r"])
    stable = [r for r in ok if r["in_sample"]["avg_r"] > 0 and r["out_of_sample"]["avg_r"] > 0]
    stable.sort(key=lambda r: -min(r["in_sample"]["avg_r"], r["out_of_sample"]["avg_r"]))

    def effect(name, on, off):
        a_ = [r["out_of_sample"]["avg_r"] for r in ok if r["filters"][name] == on]
        b_ = [r["out_of_sample"]["avg_r"] for r in ok if r["filters"][name] == off]
        if not a_ or not b_:
            return "  %-26s not enough trades to compare" % ("%s=%s" % (name, on))
        ma, mb = sum(a_) / len(a_), sum(b_) / len(b_)
        return "  %-26s %+.2fR vs %+.2fR with %s  (%s)" % ("%s=%s" % (name, on), ma, mb, off,
                                                         "helps" if ma > mb + 0.03 else "hurts" if ma < mb - 0.03
                                                         else "no clear effect")

    counts = {}
    for e in events:
        counts[e["setup"]] = counts.get(e["setup"], 0) + 1
    lines = ["research.py %s  %s" % (mode, datetime.now(ist).strftime("%Y-%m-%d %H:%M IST")),
             "SMC Trading Playbook (user's rules, smc_playbook.py): liquidity sweep -> trigger candle -> candle 1/2 "
             "CLOSE strictly beyond its extreme.",
             "Plus the rulebook's zone setups: fvg_* (structure-breaking impulse leaves a gap, first retest) and ob_* "
             "(last opposite candle before that impulse, first retest). liq: base = PDH/PDL/CDH/CDL/swings, all = "
             "+ last week's high/low, strong = PDH/PDL/PWH/PWL or equal highs/lows only. disp = confirmation candle body.",
             "%s, %d days (%s..%s). Setups found: %s. R after costs; a liquidity target under 1R away is skipped. "
             "Out-of-sample = days from %s." % (what, len(days), days[0], days[-1],
                                                ", ".join("%s %d" % kv for kv in sorted(counts.items())), split), "",
             row(score(events, pb, split, stats, spacing), "PLAYBOOK DEFAULTS (the 4 playbook setups):  "),
             row(score(events, dict(pb, setup="zones"), split, stats, spacing), "ZONES (FVG + order block), same:  "), "",
             "EACH SETUP ALONE (playbook defaults otherwise):"]
    for st in M.SETUPS + M.ZONE_SETUPS:
        lines.append(row(score(events, dict(pb, setup=st), split, stats, spacing), "  %-13s " % st))
    lines += ["", "WHICH INGREDIENT HELPS (average OUT-sample R of the combinations with it vs the alternative):",
              effect("confirm", 1, 2), effect("struct", "before", "none"), effect("struct", "any", "none"),
              effect("doji_pct", 0.10, 0.15), effect("buffer", 0.25, 0.1), effect("target", "external", "internal"),
              effect("target", "2R", "internal"), effect("target", "trail", "internal"), effect("regime", True, False),
              effect("liq", "all", "base"), effect("liq", "strong", "base"), effect("disp", 0.7, 0.0)]
    if market == "crypto":
        lines.append(effect("session", "active", "all"))
    lines += ["", "TOP 10 BY IN-SAMPLE (the OUT-sample line is the honest one):"]
    for n, r in enumerate(ok[:10], 1):
        lines.append(row(r, "%2d. " % n))
    lines += ["", "%d of %d distinct combinations (with enough trades) were positive both in- and out-of-sample." % (
        len(stable), len(ok))]
    keyf = lambda f: (f["buffer"], f["target"])
    keepf = lambda ev, f: keep(ev, f)
    if stable:
        best = stable[0]
        lines += ["", "MOST CONSISTENT (best of its weaker half):", row(best, "  "), concentration(best), "",
                  "ITS NEIGHBOURS (one setting changed at a time; a robust rule has neighbours that also do well):"]
        for k, vals in grid.items():
            for v in vals:
                if v != best["filters"][k]:
                    lines.append(row(score(events, dict(best["filters"], **{k: v}), split, stats, spacing),
                                     "  %s=%s -> " % (k, v)))
        lines += [""] + tm_test.section(events, best["filters"], keyf(best["filters"]), keepf, split, stats,
                                        "the most consistent combination")
    if market == "crypto" and step == 15:   # the live crypto rules on the same days, for comparison
        import research_v4 as V4
        brk = V4.events_v4(data, btc)
        sh = V4.events_v4(data, btc, short=True)
        lines += ["", "THE LIVE CRYPTO RULES ON THE SAME DATA (what the playbook has to beat):",
                  V4.row(V4.score(brk, dict(V4.LIVE_V4), split, stats), "  breakout long (live v6):  "),
                  V4.row(V4.score(sh, dict(V4.LIVE_SHORT, exit="trail", trend="ema+slope", max_range_pct=1.0,
                                           min_vol_x=0.0, session="all"), split, stats), "  short v7:                ")]
    lines += ["", "Multiple testing (rulebook 224): with this many combinations some look good in both halves by luck",
              "alone (on random-walk test data about 1% did). Trust a result only if its neighbours agree.",
              "", "Decision rule: put a playbook setup live (paper) only if it is positive out-of-sample with 20+ trades,",
              "its neighbours mostly stay positive, and it adds to (or beats) the live rules. ~60 days is short.",
              "The playbook itself assumes no positive expectancy. Not financial advice."]
    report = "\n".join(lines)
    print("\n" + report)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report_%s.txt" % mode), "w", encoding="utf-8") as fh:
        fh.write(report)
    print("\nWrote %s" % os.path.join(out_dir, "report_%s.txt" % mode))
    return 0
