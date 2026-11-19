#!/usr/bin/env python3
"""
research_scanner_v4.py - backtest of Scanner v4 (scanner_v4.py, the owner's rules of 11 Nov 2026), walk-forward 70/30,
R after costs. The engine's own sequence is replayed on every chart (the same code the live scanner runs): every
BOS keeps its setup until traded, one trade at a time, an OB / FVG secondary only after a primary closed, the v4
trailing stop (+1R -> entry, +2R -> +1R, ...).

    python research.py crypto-sv4       # crypto, 15-minute candles (12h max hold)
    python research.py crypto-sv4-5m    # crypto, 5-minute candles
    python research.py us-sv4           # US stocks, 5m, intraday (closed at the day's last candle)
    python research.py nse-sv4          # NSE stocks, 5m, intraday

Grid (small on purpose): side (long, short, both) x trades (primary only, primary + secondary, secondary only) x
min R:R (0 = the owner's rule, 1, 2) x skip rules (none = live: BOS by close only; the old weak-BOS skip; the 1-hour
trend skip; the intraday day rule off) and
the trailing stop off [x hours for crypto]. "Live" = what Scanner v4 paper trades: both sides, primary + secondary,
no minimum R:R, BOS by close only (no weak-BOS skip), trailing on. Exits: stop, target, trailing stop, the session's end (no time stop).
"""
import itertools
import os
from datetime import datetime, timezone

import research_abcd as RA
import scanner_v4 as V4

UTC = timezone.utc
FILTERS = {"all": {}, "with_weak_bos": {"bos_body_atr": 0.8, "bos_vol_x": 1.2},
           "with_htf": {"htf": True}, "no_trailing": {"tm_trail": False},
           "no_day_rule": {"day_carry": False}, "hammer_2x": {"hammer_x": 2.0},
           "old_candles": {"hammer_x": 2.0, "one_side": 1.01}, "no_flip": {"flip_same_day": False},
           "no_latest_bos": {"latest_bos": False},
           "old_one_trade": {"flip_same_day": False, "latest_bos": False},
           # the owner's sweep / target (17 Nov 2026)
           # the 12 Nov sweep / target, to compare with the owner's 17 Nov rules (now live)
           "old_sweep_target": {"sweep_post_bos": True, "target_rule": "near"},
           "old_sweep_only": {"sweep_post_bos": True},
           "old_target_only": {"target_rule": "near"},
           "target_nocap": {"target_rule": "opp_bos"},
           # the owner's 43 opinions (17 Nov 2026)
           "newest_bos": {"bos_pick": "newest"},
           "skip_open_bos": {"skip_open_bos": True},
           "latest_signal": {"latest_signal": True},
           "no_sweep_shift": {"sweep_shift": False},
           # the owner's 19 Nov trades (GILLETTE, AZAD, AWL)
           "no_gap_cancel": {"gap_cancel": False},
           "sweep_max_05atr": {"sweep_max_atr": 0.5},
           "sweep_max_1atr": {"sweep_max_atr": 1.0},
           "swing_k3": {"swing_k": 3},
           "swing_k4": {"swing_k": 4},
           "swing_k5": {"swing_k": 5},
           "bos_gap_skip": {"bos_gap_skip": True},
           "swing_k2_19nov": {"swing_k": 2, "bos_gap_skip": False},
           "no_signal_on_sweep": {"signal_on_sweep": False},
           "no_carry_swept": {"carry_swept": False},
           # round 1 of the rules work (owner, 19 Nov 2026): the target, with and without the Trade Manager
           "tgt_fixed_15r": {"target_rule": "fixed_r", "target_r": 1.5},
           "tgt_fixed_2r": {"target_rule": "fixed_r", "target_r": 2.0},
           "tgt_fixed_3r": {"target_rule": "fixed_r", "target_r": 3.0},
           "tgt_min_2r": {"target_rule": "min_r", "target_r": 2.0},
           "tgt_near": {"target_rule": "near"},
           "tm_off": {"trade_manager": False},
           "tgt_fixed_2r_tm_off": {"target_rule": "fixed_r", "target_r": 2.0, "trade_manager": False},
           "tgt_fixed_3r_tm_off": {"target_rule": "fixed_r", "target_r": 3.0, "trade_manager": False},
           # the Trade Manager (PYTH, 19 Nov: +0.91R given back, the breakeven move waits for +1R)
           "tm_be_05": {"tm_be_r": 0.5},
           "tm_be_075": {"tm_be_r": 0.75},
           "tm_lock_40_20": {"tm_lock_at": 0.4, "tm_lock_keep": 0.2},
           "tm_lock_50_25": {"tm_lock_at": 0.5, "tm_lock_keep": 0.25},
           "old_bos_pick": {"bos_pick": "oldest", "latest_signal": False},
           "replace_newer": {"replace_newer": True, "flip_same_day": False, "latest_bos": False},
           "four_rules": {"bos_pick": "newest", "skip_open_bos": True, "latest_signal": True, "replace_newer": True,
                          "flip_same_day": False, "latest_bos": False},
           "three_no_replace": {"bos_pick": "newest", "skip_open_bos": True, "latest_signal": True}}
RRS = (0.0, 1.0, 2.0)
VARIANTS = [(rr, f) for rr in RRS for f in FILTERS]
LIVE = {"side": "both", "trades": "both", "min_rr": 0.0, "filters": "all", "session": "all"}


def trail_settings(account):
    """The account's Trade Manager (Settings > Trade Manager, the same for every scanner) as sequence() arguments:
    the backtest manages trades the way the paper account does."""
    import paper as P
    return V4.tm_settings(P.load_config()["accounts"].get(account, {}))


def trail_text(tm):
    """The Trade Manager in words, for the report."""
    if not tm.get("trade_manager", True):
        return "Trade Manager off: stop / target only"
    be, st, gp = tm["tm_be_r"], tm["tm_trail_step"], tm["tm_trail_gap"]
    parts = ["+%gR -> entry" % be if be else "no breakeven move"]
    if tm.get("tm_trail"):
        first = next((k * st for k in range(1, 50) if k * st - gp > 1e-9), None)
        parts.append("then every %gR the stop sits %gR behind%s" % (
            st, gp, (" (first at +%gR -> +%gR)" % (first, first - gp)) if first else ""))
    else:
        parts.append("no trailing")
    if tm.get("tm_lock_at"):
        parts.append("profit lock at %d%% of the way keeps %d%%" % (tm["tm_lock_at"] * 100, tm["tm_lock_keep"] * 100))
    if tm.get("tm_reversal"):
        parts.append("reversal exit after +%gR" % tm["tm_rev_min_r"])
    if tm.get("tm_stale_min"):
        parts.append("no-follow-through exit after %d min" % tm["tm_stale_min"])
    return "; ".join(parts)


def events_v4(data, day_of, cost_fn, intraday=False, max_hold=48, entry_ok=None, tm=None):
    evs = []
    for sym, d in data.items():
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]) if None not in (o, h, l, c)]
        if len(rows) < 250:
            continue
        try:
            cx = V4.contexts(rows, day_of)           # once per chart, shared by every setting
        except Exception:
            continue
        for rr, fname in VARIANTS:
            try:
                seq = V4.sequence(rows, day_of, intraday=intraday, ctxs=cx, min_rr=rr, max_hold=max_hold,
                                  **dict(tm or {}, **FILTERS[fname]))
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
                            "r_gross": (t["exit"] - t["entry"]) * sg / risk,
                            "exit_reason": t["exit_reason"]})
    evs.sort(key=lambda e: (e["day"], e["sym"], e["i"]))
    return evs


PASS_R = 0.15        # the owner's bar (19 Nov 2026): out-of-sample, before costs, primaries only


def rules_table(events, split, min_rr=0.0):
    """The owner's view of a rule (19 Nov 2026): out-of-sample primaries, BEFORE costs: how often the target, the
    stop or something else ended the trade, and the average R. A rule passes at >= PASS_R a trade."""
    out = ["RULES TABLE (out-of-sample, primary trades, BEFORE costs; pass = avg >= %+.2fR):" % PASS_R,
           "  %-22s %6s %7s %7s %7s %8s %8s" % ("setting", "trades", "TP hit", "SL hit", "other", "avg R", "after c.")]
    for fname in FILTERS:
        es = [e for e in events if e["filters"] == fname and e["kind"] == "primary" and e["min_rr"] == min_rr
              and e["day"] >= split]
        if not es:
            continue
        n = len(es)
        tp = sum(1 for e in es if e["exit_reason"] == "target")
        sl = sum(1 for e in es if e["exit_reason"] in ("stop", "stop (gapped past it)"))
        g = sum(e["r_gross"] for e in es) / n
        net = sum(e["r"] for e in es) / n
        out.append("  %-22s %6d %6.0f%% %6.0f%% %6.0f%% %+7.2fR %+7.2fR%s" % (
            fname, n, 100.0 * tp / n, 100.0 * sl / n, 100.0 * (n - tp - sl) / n, g, net,
            "  PASS" if g >= PASS_R and n >= 300 else ""))
    return "\n".join(out)


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
        tm = trail_settings("CRYPTO")
        events = events_v4(data, lambda t: t.date(), cost_fn, max_hold=None, tm=tm)   # TP / SL / trailing only
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
        tm = trail_settings("INDIA")
        events = events_v4(data, lambda t: t.astimezone(tz_local).date(), cost_fn, intraday=True, max_hold=None,
                           entry_ok=entry_ok, tm=tm)
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
        tm = trail_settings("US")
        events = events_v4(data, lambda t: t.astimezone(et).date(), cost_fn, intraday=True, max_hold=None,
                           entry_ok=entry_ok, tm=tm)
        mode, what = "us-sv4", "%d US stocks/ETFs, 5m candles, intraday" % len(data)
        costs = "%.3f%% a side (paper fee + 0.02%% assumed spread/slippage)" % (fee * 100)
        grid_extra = {}

    if not events:
        print("No Scanner v4 trades found: no data came back (check the internet / Yahoo).")
        return 1
    grid = {"side": ["long", "short", "both"], "trades": ["primary", "secondary", "both"], "min_rr": list(RRS),
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
    base = [e for e in events if e["min_rr"] == LIVE["min_rr"] and e["filters"] == "all"]
    n_p = sum(1 for e in base if e["kind"] == "primary")
    exits = {}
    for e in base:
        exits[e["exit_reason"]] = exits.get(e["exit_reason"], 0) + 1
    lines = ["research.py %s  %s" % (mode, datetime.now(tz_local).strftime("%Y-%m-%d %H:%M %Z")),
             "Scanner v4 (scanner_v4.py, the owner's rules of 11 Nov 2026): PRIMARY BUY = bullish BOS (close) -> a close "
             "below an old low -> classic / gravestone / long-legged doji or inverted hammer -> the next or next-to-next "
             "candle closes above its high (SELL: mirror, classic / dragonfly / long-legged doji or hammer); every BOS setup stays active until traded; stop below the sweep-to-signal "
             "low; target = next liquidity; the account's Trade Manager (%s). SECONDARY = only after the primary "
             "closed: a reversal candle tapping the move's OB / FVG. One trade at a time per chart. Shorts = mirror." % trail_text(tm),
             "%s, %d days (%s..%s). Live-reading trades: %d primary, %d secondary; exits %s. R after costs (%s). "
             "Out-of-sample = days from %s." % (what, len(days), days[0], days[-1], n_p, len(base) - n_p, exits, costs,
                                                split), "",
             row(score(events, live, split, stats), "LIVE (what Scanner v4 paper trades):  "),
             row(score([dict(e, r=e["r_gross"]) for e in events], live, split, stats),
                 "LIVE, the same trades BEFORE costs:  "),
             row(score(events, dict(live, trades="primary"), split, stats), "LIVE, primary trades only:  "),
             row(score(events, dict(live, trades="secondary"), split, stats), "LIVE, secondary (OB/FVG) only:  "),
             row(score(events, dict(live, side="long"), split, stats), "LIVE, longs only:  "),
             row(score(events, dict(live, side="short"), split, stats), "LIVE, shorts only:  "), "",
             "SKIP RULES AND TRAILING (live setting, one switched off at a time; trades/day shows how much each cuts):"]
    for fname in FILTERS:
        if fname != "all":
            lines.append(row(score(events, dict(live, filters=fname), split, stats), "  skip_rules=%s -> " % fname))
    lines += ["", rules_table(events, split)]
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
