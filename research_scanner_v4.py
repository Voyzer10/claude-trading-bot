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
import research_costs as RC
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
           "sweep_v1": {"sweep_rule": "v1"},
           "sweep_v1_pen010": {"sweep_rule": "v1", "sweep_pen_atr": 0.10},
           "sweep_v1_6bars": {"sweep_rule": "v1", "sweep_max_bars": 6},
           "bos_swings_k3": {"bos_rule": "swings"},
           "bos_swings_old": {"bos_rule": "swings", "structure_bos": False, "swing_k": 4},
           "no_structure_bos": {"structure_bos": False},
           "no_structure_k4": {"structure_bos": False, "swing_k": 4},
           "structure_k4": {"swing_k": 4},
           "structure_k2": {"swing_k": 2},
           "short_only": {"only_side": "short"},
           "long_only": {"only_side": "long"},
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


def rules_table(events, split, min_rr=None):
    """The owner's view of a rule (19 Nov 2026): out-of-sample primaries, BEFORE costs: how often the target, the
    stop or something else ended the trade, and the average R. A rule passes at >= PASS_R a trade."""
    out = ["RULES TABLE (out-of-sample, primary trades, BEFORE costs; pass = avg >= %+.2fR):" % PASS_R,
           "  %-28s %6s %7s %7s %7s %8s %8s %9s" % ("setting", "trades", "TP hit", "SL hit", "other", "avg R",
                                                   "after c.", "in-sample")]
    for rr_, fname in sorted({(rr_, f) for rr_, f in VARIANTS}, key=lambda x: (x[1] != "all", x[1], x[0])):
        if min_rr is not None and rr_ != min_rr:
            continue
        es = [e for e in events if e["filters"] == fname and e["kind"] == "primary" and e["min_rr"] == rr_
              and e["day"] >= split]
        if not es:
            continue
        n = len(es)
        tp = sum(1 for e in es if e["exit_reason"] == "target")
        sl = sum(1 for e in es if e["exit_reason"] in ("stop", "stop (gapped past it)"))
        g = sum(e["r_gross"] for e in es) / n
        net = sum(e["r"] for e in es) / n
        ins = [e["r_gross"] for e in events if e["filters"] == fname and e["kind"] == "primary" and e["min_rr"] == rr_
               and e["day"] < split]
        gi = sum(ins) / len(ins) if ins else 0.0
        out.append("  %-28s %6d %6.0f%% %6.0f%% %6.0f%% %+7.2fR %+7.2fR %+8.2fR%s" % (
            fname + (" rr>=%g" % rr_ if rr_ else ""), n, 100.0 * tp / n, 100.0 * sl / n, 100.0 * (n - tp - sl) / n, g, net,
            gi, "  PASS" if g >= PASS_R and gi >= PASS_R and n >= 300 else ""))
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
        cfg_c = P.load_config()
        fee = float(cfg_c["accounts"]["CRYPTO"]["fee_pct"]) / 100

        def cost_fn(sym, entry, stop, exit_px, side):         # research_costs.crypto_main (unchanged formula)
            got = RC.crypto_main(sym, side, entry, exit_px, stop, cfg_c)
            return None if got is None else got["total_r"]
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

        def cost_fn(sym, entry, stop, exit_px, side):         # research_costs.nse (the same formula, moved)
            got = RC.nse(sym, side, entry, exit_px, stop, cfg)
            return None if got is None else got["total_r"]

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
        cfg_u = P.load_config()
        fee = float(cfg_u["accounts"]["US"].get("fee_pct", 0)) / 100 + RC.US_SPREAD_SLIP_SIDE

        def cost_fn(sym, entry, stop, exit_px, side):         # research_costs.us (the same formula, moved)
            got = RC.us(sym, side, entry, exit_px, stop, cfg_u)
            return None if got is None else got["total_r"]

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


# --- the liquidity-sweep stage (owner, 20 Nov 2026): one scanner, the sweep rule switched by settings only --------
# The same Scanner v4 sequence (legs BOS, live rules, the account's Trade Manager) on the long broker history
# (research_data.py, the research_tf.py splits), with the sweep stage set three ways, entry_max_bars 12 throughout:
#   close         the original rule (a close beyond the BOS origin or a post-BOS swing low is the sweep)
#   v1            wick through the PROTECTED swing (<= sweep_pen_atr x ATR(14)), close back inside
#   v2            wick through the nearest resting confirmed LOCAL swing of the BOS leg, close back above it;
#                 the protected swing stays the invalidation level
# Prints the funnel, the results in- and out-of-sample (R before costs, avg R and max drawdown after costs) and
# the filter quality against "close".    python research_scanner_v4.py sweep nse|us|crypto
SWEEP_CONFIGS = [("close", {"sweep_rule": "close"}),
                 ("v1 12/0.25", {"sweep_rule": "v1", "sweep_max_bars": 12, "sweep_pen_atr": 0.25}),
                 ("v2 12/0.25", {"sweep_rule": "v2", "sweep_max_bars": 12, "sweep_pen_atr": 0.25}),
                 ("v2 12/0.10", {"sweep_rule": "v2", "sweep_max_bars": 12, "sweep_pen_atr": 0.10}),
                 ("v2 6/0.25", {"sweep_rule": "v2", "sweep_max_bars": 6, "sweep_pen_atr": 0.25}),
                 # (21 Nov 2026) the structural correction: internal liquidity (deepest level taken), failed reclaim /
                 # too deep = not a sweep (setup stays while its protected swing holds), CHoCH + newer-BOS ends;
                 # the same windows / penetration as v1 / v2 (no new threshold)
                 ("internal", {"sweep_rule": "internal", "sweep_max_bars": 12, "sweep_pen_atr": 0.25})]
SWEEP_BE = 0.05            # |R| under this = breakeven


def _sweep_chart(args):
    import research_features as F
    import research_tf as TF
    market, sym, rows, tm = args
    m = F.MARKETS[market]
    day_of = (lambda t: m["local"](t).date())
    out = {}
    for name, kw in SWEEP_CONFIGS:
        ended, stats = [], {}
        seq = V4.sequence(rows, day_of, intraday=m["intraday"], max_hold=None, _ended=ended, _stats=stats,
                          **dict(tm, entry_max_bars=12, **kw))
        trades = []
        for t in seq:
            if t["kind"] != "primary" or t.get("exit") is None or t.get("exit_reason") == "open":
                continue
            sg = 1 if t["side"] == "long" else -1
            risk = (t["entry"] - t["stop"]) * sg
            if risk <= 0:
                continue
            r = (t["exit"] - t["entry"]) * sg / risk
            trades.append({"sym": sym, "bos": t["bos"], "side": t["side"], "i": t["i"], "t": rows[t["i"]][0].timestamp(),
                           "day": day_of(rows[t["i"]][0]).isoformat(), "r": r, "exit": t["exit_reason"],
                           "cost": RC.cost_r(market, sym, t["side"], t["entry"], t["exit"], t["stop"])})
        why = {}
        for st, j, w in ended:
            k = ("invalidated" if "protected swing" in w else "too deep" if w.startswith("wick too deep") else
                 "expired: no sweep" if w.startswith("no sweep") else "expired: no entry" if w.startswith("no entry")
                 else "no reclaim" if w.startswith("no reclaim") else "overnight" if w == "overnight" else w)
            why[k] = why.get(k, 0) + 1
        why["local ref"] = sum(1 for t in seq if t["kind"] == "primary" and t.get("level_name") == "local_swing")
        exact = {}
        for st, j, w in ended:
            k = w.split(" (")[0]
            exact[k] = exact.get(k, 0) + 1
        for k in ("too_deep", "failed_reclaim"):
            if stats.get(k):
                exact["attempt (setup stays): " + k.replace("_", " ")] = stats[k]
        why["_exact"] = exact
        out[name] = {"trades": trades, "stats": stats, "why": why}
    return sym, out


def _sweep_summary(trades):
    n = len(trades)
    if not n:
        return None
    w = [t for t in trades if t["r"] >= SWEEP_BE]
    l_ = [t for t in trades if t["r"] <= -SWEEP_BE]
    gp = sum(t["r"] for t in w)
    gl = -sum(t["r"] for t in l_)
    net = sum(t["r"] for t in trades)
    eq = peak = dd = eqc = peakc = ddc = 0.0
    for t in sorted(trades, key=lambda x: x["t"]):
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        eqc += t["r"] - t["cost"] if t["cost"] is not None else 0.0
        peakc = max(peakc, eqc)
        ddc = max(ddc, peakc - eqc)
    return {"n": n, "w": len(w), "l": len(l_), "be": n - len(w) - len(l_), "wr": 100.0 * len(w) / n, "gp": gp, "gl": gl,
            "net": net, "pf": gp / gl if gl else float("inf"), "dd": dd, "avg": net / n,
            "net_c": (sum(t["r"] - t["cost"] for t in trades if t["cost"] is not None)
                      / max(1, sum(1 for t in trades if t["cost"] is not None))), "dd_c": ddc,
            "tp": 100.0 * sum(1 for t in trades if t["exit"] == "target") / n}


def sweep_report(argv=None):
    import argparse
    import json
    from multiprocessing import Pool
    import research_features as F
    import research_tf as TF
    p = argparse.ArgumentParser(prog="research_scanner_v4.py sweep")
    p.add_argument("market", choices=list(F.MARKETS))
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--json")
    a = p.parse_args(argv)
    tm = {}
    try:
        import paper as P
        tm = V4.tm_settings(P.load_config()["accounts"].get({"nse": "INDIA", "us": "US", "crypto": "CRYPTO"}[a.market], {}))
    except Exception:
        pass
    data = F.load(a.market)
    jobs = [(a.market, s, rows, tm) for s, rows in data.items()]
    with Pool(a.workers) as pool:
        res = dict(pool.imap_unordered(_sweep_chart, jobs))
    split = TF.SPLIT[a.market]
    print("%s: %d symbols; out-of-sample from %s; R BEFORE costs unless marked" % (a.market, len(res), split))
    agg = {}
    for name, _kw in SWEEP_CONFIGS:
        trades = [t for r in res.values() for t in r[name]["trades"]]
        stats, why = {}, {}
        for r in res.values():
            for k, v in r[name]["stats"].items():
                stats[k] = stats.get(k, 0) + v
            for k, v in r[name]["why"].items():
                if k == "_exact":
                    ex = why.setdefault("_exact", {})
                    for k2, v2 in v.items():
                        ex[k2] = ex.get(k2, 0) + v2
                    continue
                why[k] = why.get(k, 0) + v
        agg[name] = {"trades": trades, "stats": stats, "why": why}

    print("\nFUNNEL (whole period)")
    print("  %-10s %7s %7s %8s %8s %8s %8s %8s %8s %8s %7s %7s" % (
        "config", "BOS", "sweeps", "exp:sw", "exp:ent", "invalid", "too deep", "no recl", "overnt", "confirm", "trades",
        "loc.ref"))
    for name, _ in SWEEP_CONFIGS:
        s, w = agg[name]["stats"], agg[name]["why"]
        print("  %-10s %7d %7s %8d %8d %8d %8d %8d %8d %8d %7d %7d" % (
            name, s.get("bos", 0), s.get("sweeps", "-") if name != "close" else "-", w.get("expired: no sweep", 0),
            w.get("expired: no entry", 0), w.get("invalidated", 0), w.get("too deep", 0), w.get("no reclaim", 0),
            w.get("overnight", 0), s.get("confirmations", 0), len(agg[name]["trades"]), w.get("local ref", 0)))
    print("\nEXACT END REASONS (setups ended, whole period; attempts = rejected sweep candles, the setup stayed)")
    for name, _ in SWEEP_CONFIGS:
        ex = agg[name]["why"].get("_exact", {})
        print("  %-10s %s" % (name, ", ".join("%s %d" % (k, v) for k, v in sorted(ex.items(), key=lambda x: -x[1]))
                               or "-"))
    for part, f in (("OUT-OF-SAMPLE", lambda t: t["day"] >= split), ("IN-SAMPLE", lambda t: t["day"] < split)):
        print("\n%s results (R before costs)" % part)
        print("  %-10s %6s %5s %5s %5s %6s %6s %8s %8s %8s %6s %7s %8s %8s %8s" % (
            "config", "trades", "win", "loss", "BE", "win%", "TP%", "gross+", "gross-", "net R", "PF", "maxDD", "avg R",
            "after c.", "DD aft.c"))
        for name, _ in SWEEP_CONFIGS:
            s = _sweep_summary([t for t in agg[name]["trades"] if f(t)])
            if not s:
                print("  %-10s no trades" % name)
                continue
            print("  %-10s %6d %5d %5d %5d %5.1f%% %5.1f%% %+8.1f %8.1f %+8.1f %6.2f %7.1f %+7.3fR %+7.3fR %8.1f" % (
                name, s["n"], s["w"], s["l"], s["be"], s["wr"], s["tp"], s["gp"], s["gl"], s["net"], s["pf"], s["dd"],
                s["avg"], s["net_c"], s["dd_c"]))
    print("\nFILTER QUALITY vs close (out-of-sample, same symbol + BOS candle + side)")
    base = {(t["sym"], t["bos"], t["side"]): t for t in agg["close"]["trades"] if t["day"] >= split}
    for name, _ in SWEEP_CONFIGS[1:]:
        keys = {(t["sym"], t["bos"], t["side"]) for t in agg[name]["trades"] if t["day"] >= split}
        rej = [t for k, t in base.items() if k not in keys]
        new = [t for t in agg[name]["trades"] if t["day"] >= split and (t["sym"], t["bos"], t["side"]) not in base]
        kept = [t for k, t in base.items() if k in keys]
        print("  %-10s baseline trades rejected %d of %d: target %d, stop %d, other %d, their avg %+.3fR | kept avg "
              "%+.3fR | new trades not in baseline %d, avg %+.3fR" % (
                  name, len(rej), len(base), sum(1 for t in rej if t["exit"] == "target"),
                  sum(1 for t in rej if t["exit"] in ("stop", "stop (gapped past it)")),
                  sum(1 for t in rej if t["exit"] not in ("target", "stop", "stop (gapped past it)")),
                  sum(t["r"] for t in rej) / max(1, len(rej)), sum(t["r"] for t in kept) / max(1, len(kept)), len(new),
                  sum(t["r"] for t in new) / max(1, len(new))))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({k: {"stats": v["stats"], "why": v["why"]} for k, v in agg.items()}, fh)



# --- BOS quality analysis (owner, 20 Nov 2026): research and reporting only, no trading change ---------------------
# The baseline ("close" sweep, live defaults, the account's Trade Manager) primary trades of the same long broker
# history and splits as the sweep comparison, each tagged with BOS-quality / freshness / entry measurements taken from
# the scanner's own context (its ATR(14), its legs() BOS events) and the trade's own setup. Bins are fixed in advance
# (round numbers, below) and never tuned on the data. Every trade lands in exactly one bin per metric ("missing" when
# a measurement cannot be made); the metrics are different views of the SAME trades, never added together.
#     python research_scanner_v4.py bos nse|us|crypto
BOS_BINS = [
    # name, what, edges (bin k = [edge k-1, edge k)), unit
    ("body_atr", "BOS candle body / ATR(14) at the BOS candle", [0.5, 1.0, 1.5]),
    ("range_atr", "BOS candle high-low / ATR", [1.0, 1.5, 2.0]),
    ("beyond_atr", "BOS close beyond the broken swing / ATR", [0.1, 0.25, 0.5]),
    ("leg_atr", "broken swing - BOS origin (= protected swing) / ATR", [1.0, 2.0, 4.0]),
    ("prot_broken", "a close beyond the protected swing between BOS and entry (1 = yes)", [0.5]),
    ("bars", "candles from the BOS to the entry", [4, 13, 37, 79]),
    ("minutes", "minutes from the BOS to the entry", [30, 60, 180, 1440]),
    ("overnight", "BOS and entry on different session days (1 = yes)", [0.5]),
    ("entry_origin_atr", "entry - BOS origin (= protected swing) / ATR at entry", [0.0, 0.5, 1.0, 2.0]),
    ("entry_level_atr", "entry - broken swing / ATR at entry", [-2.0, -1.0, 0.0]),
]


def _bos_chart(args):
    import research_features as F
    import research_tf as TF
    market, sym, rows, tm = args
    m = F.MARKETS[market]
    day_of = (lambda t: m["local"](t).date())
    p = dict(V4.DEFAULTS, **tm)
    k = int(p.get("swing_k") or 2)
    cx = V4.contexts(rows, day_of, bool(p.get("htf")), k=k)
    atr = cx["ctx"][0].atr                     # the mirror chart has the same candle ranges, so the same ATR
    lg = V4.legs(rows)
    day = cx["day"]
    out, bad, dup, seen = [], {"open": 0, "risk": 0, "ref_mismatch": 0}, 0, set()
    for t in V4.sequence(rows, day_of, intraday=m["intraday"], max_hold=None, ctxs=cx, **tm):
        if t["kind"] != "primary":
            continue
        if t.get("exit") is None or t.get("exit_reason") == "open":
            bad["open"] += 1
            continue
        sg = 1 if t["side"] == "long" else -1
        risk = (t["entry"] - t["stop"]) * sg
        if risk <= 0:
            bad["risk"] += 1
            continue
        key = (t["side"], t["bos"], t["i"])
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        j, i = t["bos"], t["i"]
        ev = lg.get(j)
        lvl, org = t.get("bos_level"), t.get("bos_origin")
        if p.get("bos_rule") == "legs" and (not ev or ev[0] != t["side"] or abs(ev[1] - lvl) > 1e-9
                                            or abs(ev[2] - org) > 1e-9):
            bad["ref_mismatch"] += 1               # the trade's BOS / protected swing are not the scanner's event
        o, h, l, c = rows[j][1:5]
        aj, ai = atr[j], t.get("atr") or atr[i]
        closes = [rows[x][4] for x in range(j + 1, i)]
        f = {"r": (t["exit"] - t["entry"]) * sg / risk,
             "cost": RC.cost_r(market, sym, t["side"], t["entry"], t["exit"], t["stop"]),
             "t": rows[i][0].timestamp(), "day": day_of(rows[i][0]).isoformat(), "sym": sym, "side": t["side"],
             "exit": t["exit_reason"],
             "body_atr": abs(c - o) / aj if aj else None,
             "range_atr": (h - l) / aj if aj else None,
             "beyond_atr": (c - lvl) * sg / aj if aj else None,
             "leg_atr": (lvl - org) * sg / aj if aj else None,
             "prot_broken": float(any((x - org) * sg < 0 for x in closes)),
             "bars": i - j,
             "minutes": (rows[i][0] - rows[j][0]).total_seconds() / 60,
             "overnight": float(day[i] != day[j]),
             "entry_origin_atr": (t["entry"] - org) * sg / ai if ai else None,
             "entry_level_atr": (t["entry"] - lvl) * sg / ai if ai else None}
        out.append(f)
    return sym, out, bad, dup


def _bin_label(edges, k):
    if len(edges) == 1 and edges[0] == 0.5:
        return ("no", "yes")[k]
    lo = "-inf" if k == 0 else "%g" % edges[k - 1]
    hi = "inf" if k == len(edges) else "%g" % edges[k]
    return "[%s, %s)" % (lo, hi)


def _bin_stats(tr):
    import math
    n = len(tr)
    if not n:
        return None
    rs = [t["r"] for t in tr]
    avg = sum(rs) / n
    sd = math.sqrt(sum((x - avg) ** 2 for x in rs) / (n - 1)) if n > 1 else 0.0
    gp = sum(x for x in rs if x > 0)
    gl = -sum(x for x in rs if x < 0)
    eq = pk = dd = 0.0
    for t in sorted(tr, key=lambda x: x["t"]):
        eq += t["r"]
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    return {"n": n, "avg": avg, "se": sd / math.sqrt(n) if n > 1 else float("nan"), "pf": gp / gl if gl else float("inf"),
            "wr": 100.0 * sum(1 for x in rs if x >= SWEEP_BE) / n, "dd": dd,
            "avg_c": (sum(t["r"] - t["cost"] for t in tr if t["cost"] is not None)
                      / max(1, sum(1 for t in tr if t["cost"] is not None)))}


def _spearman(xs, ys):
    import math
    n = len(xs)
    if n < 10:
        return float("nan")

    def rank(v):
        order = sorted(range(n), key=lambda q: v[q])
        r = [0.0] * n
        a = 0
        while a < n:
            b = a
            while b + 1 < n and v[order[b + 1]] == v[order[a]]:
                b += 1
            for q in range(a, b + 1):
                r[order[q]] = (a + b) / 2.0
            a = b + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else float("nan")


def bos_report(argv=None):
    import argparse
    import bisect
    import math
    from multiprocessing import Pool
    import research_features as F
    import research_tf as TF
    ap = argparse.ArgumentParser(prog="research_scanner_v4.py bos")
    ap.add_argument("market", choices=list(F.MARKETS))
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    tm = {}
    try:
        import paper as P
        tm = V4.tm_settings(P.load_config()["accounts"].get({"nse": "INDIA", "us": "US", "crypto": "CRYPTO"}[a.market], {}))
    except Exception:
        pass
    data = F.load(a.market)
    with Pool(a.workers) as pool:
        res = list(pool.imap_unordered(_bos_chart, [(a.market, s, r, tm) for s, r in data.items()]))
    trades = [t for _, tr, _, _ in res for t in tr]
    bad = {k: sum(b[k] for _, _, b, _ in res) for k in ("open", "risk", "ref_mismatch")}
    dup = sum(d for _, _, _, d in res)
    split = TF.SPLIT[a.market]
    ins = [t for t in trades if t["day"] < split]
    oos = [t for t in trades if t["day"] >= split]
    print("%s: %d symbols, baseline close-rule primary trades: %d (in-sample %d, out-of-sample %d from %s)" % (
        a.market, len(res), len(trades), len(ins), len(oos), split))
    print("excluded: still open %d, zero/negative risk %d; duplicates %d; BOS / protected swing not matching the "
          "scanner's legs() event: %d" % (bad["open"], bad["risk"], dup, bad["ref_mismatch"]))
    print("R before costs; 'aft.c' = avg R after ~%.3f%% round-trip costs; +-95%% = 1.96 x standard error of the avg"
          % TF.COST_PCT[a.market])
    for nm, label in (("ALL", "all trades"),):
        for part, tr in (("IS", ins), ("OOS", oos)):
            s = _bin_stats(tr)
            print("  %-4s %-3s n=%5d avg %+.3fR +-%.3f PF %.2f win %.1f%% maxDD %.1fR aft.c %+.3fR" % (
                nm, part, s["n"], s["avg"], 1.96 * s["se"], s["pf"], s["wr"], s["dd"], s["avg_c"]))
    for key, what, edges in BOS_BINS:
        print("\n%s: %s" % (key, what))
        miss = sum(1 for t in trades if t[key] is None)
        xs = {part: [(t[key], t["r"]) for t in tr if t[key] is not None] for part, tr in (("IS", ins), ("OOS", oos))}
        print("  Spearman(metric, R): IS %+.3f (n %d)   OOS %+.3f (n %d)   missing %d" % (
            _spearman(*zip(*xs["IS"])) if len(xs["IS"]) > 9 else float("nan"), len(xs["IS"]),
            _spearman(*zip(*xs["OOS"])) if len(xs["OOS"]) > 9 else float("nan"), len(xs["OOS"]), miss))
        print("  %-14s | %-50s | %-50s" % ("bin", "IN-SAMPLE  n  avgR  +-95%  PF  win%  maxDD  aft.c",
                                          "OUT-OF-SAMPLE  n  avgR  +-95%  PF  win%  maxDD  aft.c"))
        for kb in range(len(edges) + 1):
            cells = []
            for tr in (ins, oos):
                sub = [t for t in tr if t[key] is not None and bisect.bisect_right(edges, t[key]) == kb]
                s = _bin_stats(sub)
                cells.append("%5d  --" % 0 if not s else "%5d %+.3f %.3f %5.2f %5.1f %6.1f %+.3f" % (
                    s["n"], s["avg"], 1.96 * s["se"] if not math.isnan(s["se"]) else 0, min(s["pf"], 99), s["wr"],
                    s["dd"], s["avg_c"]))
            print("  %-14s | %-50s | %-50s" % (_bin_label(edges, kb), cells[0], cells[1]))
    return 0

if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["sweep"]:
        sys.exit(sweep_report(sys.argv[2:]))
    if sys.argv[1:2] == ["bos"]:
        sys.exit(bos_report(sys.argv[2:]))
    if sys.argv[1:2] == ["lifecycle"]:
        import research_trade_lifecycle_v4        # E1 trade lifecycle and execution economics
        sys.exit(research_trade_lifecycle_v4.main(sys.argv[2:]))
    if sys.argv[1:2] == ["cohortb"]:
        import research_cohortb_v4                # cohort B: do sweep-time features predict E1 net R?
        sys.exit(research_cohortb_v4.main(sys.argv[2:]))
    if sys.argv[1:2] == ["sweepq"]:
        import research_sweep_quality_v4          # sweep quality: cohorts A (invalidated first) / B (confirmed first)
        sys.exit(research_sweep_quality_v4.main(sys.argv[2:]))
    if sys.argv[1:2] == ["entry"]:
        import research_entry_v4                 # entry-quality research on the internal-sweep setups
        sys.exit(research_entry_v4.main(sys.argv[2:]))
    print("usage: python research_scanner_v4.py sweep nse|us|crypto [--workers 2]  (the grid runs via research.py)")
