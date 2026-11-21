#!/usr/bin/env python3
"""Loss-fix candidates for Scanner v4 on research/rules-pass (21 Nov 2026). Research only; every candidate is a switch
(defaults unchanged), backtested with the engine's own sequence() per chart (one trade per chart, flips, latest-BOS,
secondaries: the production rules), on the long broker history, NSE and US separately, the research_tf split, costs
from research_costs (NSE paper.charges on the INDIA sizing, US fee_pct + 0.02%/side; entry AND exit).

Candidates (declared before any run; no grid, no OOS selection):
  baseline   the rules-pass defaults (close sweep, opp_bos_cap target, Trade Manager BE at +1R, trail 1R / 1R)
  A          cost-aware eligibility: min_net_rr 1.0 with the market's cost function (scanner _cost_ok)
  B          breakeven off (tm_be_r 0; the trailing stop unchanged)
  C          target at least 2R (target_rule "min_r", target_r 2.0: existing options)
  D          50% partial profit at +1R on the baseline trades (exit replay: the rest exits exactly as the baseline,
             so occupancy and the portfolio rules are unchanged); costs on every fill; stop-first on ambiguous candles
  v1, v2     the existing alternative sweep rules (independently tested against the default)
Decision rule (declared): a candidate is ACCEPTED in a market only if its net mean beats the baseline in-sample AND
out-of-sample, and the OOS Welch 95% CI of (candidate - baseline) excludes 0. Otherwise REJECTED.

    python research_scanner_v4.py fixes nse|us [--json out.json]"""
import math
import os
import sys

import paper as P
import research_costs as RC
import scanner_v4 as V4

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CONFIGS = [("baseline", {}),
           ("A cost-aware min_net_rr 1.0", {"min_net_rr": 1.0}),
           ("B breakeven off", {"tm_be_r": 0.0}),
           ("C target >= 2R", {"target_rule": "min_r", "target_r": 2.0}),
           ("sweep v1", {"sweep_rule": "v1"}),
           ("sweep v2", {"sweep_rule": "v2"})]
PARTIAL = "D partial 50% at +1R"
STOPS = ("stop", "stop (gapped past it)")


def exit_cat(reason):
    r = str(reason)
    if r in STOPS:
        return "stop"
    if r == "breakeven stop":
        return "breakeven"
    if r in ("trailing stop", "profit lock stop"):
        return "trailing"
    if r == "target":
        return "target"
    if r == "day end":
        return "day end"
    return "other (flip / replace / time)"


def partial_leg(market, sym, side, entry, p1, exit_px, stop):
    """Cost in R of a trade closed in two halves (p1 at +1R, the rest at exit_px), entry once, both exits charged;
    None when it cannot be split (NSE: fewer than 2 shares) or not sized."""
    risk = abs(entry - stop)
    if market == "nse":
        cfg = P.DEFAULT_CONFIG
        acc = cfg["accounts"]["INDIA"]
        qty = int(min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / entry))
        if qty < 2:
            return None
        q1 = qty // 2
        o, c = ("buy", "sell") if side == "long" else ("sell", "buy")
        cost = (P.charges(cfg, "NSE", sym, o, qty * entry) + P.charges(cfg, "NSE", sym, c, q1 * p1)
                + P.charges(cfg, "NSE", sym, c, (qty - q1) * exit_px))
        return cost / (qty * risk), q1 / qty
    cfg = RC._config()
    side_pct = float(cfg["accounts"]["US"].get("fee_pct", 0)) / 100 + RC.US_SPREAD_SLIP_SIDE
    return (entry + 0.5 * p1 + 0.5 * exit_px) * side_pct / risk, 0.5


def replay_partial(rows, t):
    """(partial taken?, the +1R price) for one baseline trade, from its own candles: candles before the exit candle
    count fully; on the exit candle a stop-type exit comes first (no partial), a target exit means the price passed
    +1R first only if the target is at or beyond +1R, a close-based exit counts the whole candle."""
    sg = 1 if t["side"] == "long" else -1
    e, stp = sg * t["entry"], sg * t["stop"]
    risk = e - stp
    lvl = e + risk
    bars = rows if sg == 1 else V4.mirror(rows)
    fill = t["i"] + 1
    for k in range(fill, t["exit_i"]):
        if bars[k][2] >= lvl:
            return True, sg * lvl
    cat = exit_cat(t["exit_reason"])
    if cat in ("stop", "breakeven", "trailing"):
        return False, None
    if cat == "target":
        return (sg * t["target"] >= lvl), sg * lvl
    return bars[t["exit_i"]][2] >= lvl, sg * lvl


def chart(args):
    import research_features as F
    market, sym, rows, tm = args
    m = F.MARKETS[market]
    day_of = (lambda t: m["local"](t).date())
    cx = V4.contexts(rows, day_of, False, k=int(V4.DEFAULTS["swing_k"]))

    def cost_fn(side, e, x, st):
        got = RC.HARNESS[market](sym, side, e, x, st)
        return None if got is None else got["total_r"]
    out = {}
    for name, kw in CONFIGS:
        ended, stats = [], {}
        cfg = dict(tm, **kw)
        if "min_net_rr" in kw:
            cfg["_cost_fn"] = cost_fn
        seq = V4.sequence(rows, day_of, intraday=m["intraday"], ctxs=cx, max_hold=None, _ended=ended, _stats=stats,
                          **cfg)
        trades, n_open = [], 0
        for t in seq:
            if t.get("exit") is None or t.get("exit_reason") == "open":
                n_open += 1
                continue
            sg = 1 if t["side"] == "long" else -1
            risk = (t["entry"] - t["stop"]) * sg
            if risk <= 0:
                continue
            c = RC.cost_r(market, sym, t["side"], t["entry"], t["exit"], t["stop"])
            rec = {"sym": sym, "kind": t["kind"], "side": t["side"], "i": t["i"], "exit_i": t["exit_i"],
                   "day": day_of(rows[t["i"]][0]).isoformat(), "t_exit": rows[t["exit_i"]][0].timestamp(),
                   "gross": (t["exit"] - t["entry"]) * sg / risk, "cost": c, "reason": t["exit_reason"],
                   "stop_pct": 100 * risk / abs(t["entry"]), "stop_atr": risk / t["atr"] if t.get("atr") else None,
                   "planned": (t["target"] - t["entry"]) * sg / risk}
            if name == "baseline":
                took, p1 = replay_partial(rows, t)
                if took:
                    pc = partial_leg(market, sym, t["side"], abs(t["entry"]), abs(p1), abs(t["exit"]), abs(t["stop"]))
                    if pc is not None:
                        cost_p, frac = pc
                        rec["partial"] = {"gross": frac * 1.0 + (1 - frac) * rec["gross"], "cost": cost_p}
                    else:
                        rec["partial"] = None          # cannot split: the trade stays whole
                else:
                    rec["partial"] = {"gross": rec["gross"], "cost": c}
            trades.append(rec)
        why = {}
        for _st, _j, w in ended:
            k = w.split(" (")[0].split(":")[0]
            why[k] = why.get(k, 0) + 1
        out[name] = {"trades": trades, "stats": stats, "why": why, "open": n_open}
    return sym, out


def summary(trs, key_g="gross", key_c="cost"):
    xs = [t[key_g] - t[key_c] for t in sorted(trs, key=lambda t: t["t_exit"]) if t[key_c] is not None]
    n = len(xs)
    if not n:
        return None
    mu = sum(xs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1)) if n > 1 else float("nan")
    s = sorted(xs)
    pos, neg = sum(x for x in xs if x > 0), -sum(x for x in xs if x < 0)
    eq = pk = dd = 0.0
    for x in xs:
        eq += x
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    g = [t[key_g] for t in trs if t[key_c] is not None]
    c = [t[key_c] for t in trs if t[key_c] is not None]
    return {"n": n, "net": mu, "ci": 1.96 * sd / math.sqrt(n) if n > 1 else float("nan"), "sd": sd,
            "median": s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2, "win": sum(1 for x in xs if x > 0) / n,
            "pf": pos / neg if neg else float("inf"), "dd": dd, "gross": sum(g) / n, "cost": sum(c) / n}


def _partial_view(trs):
    out = []
    for t in trs:
        p_ = t.get("partial")
        if p_ is None:
            out.append(dict(t, pg=t["gross"], pc=t["cost"]))
        else:
            out.append(dict(t, pg=p_["gross"], pc=p_["cost"]))
    return out


def report(market, res, split):
    L = []
    P_ = L.append
    names = [n for n, _ in CONFIGS] + [PARTIAL]

    def trades_of(name):
        if name == PARTIAL:
            return _partial_view([t for r in res.values() for t in r["baseline"]["trades"]])
        return [t for r in res.values() for t in r[name]["trades"]]
    keys = lambda name: ("pg", "pc") if name == PARTIAL else ("gross", "cost")   # noqa: E731
    P_("%s: %d symbols; IS before %s, OOS from it. All closed trades (primary + OB / FVG secondary) of the engine's "
       "sequence(); R per trade; costs research_costs (entry + exit)." % (market, len(res), split))
    base = {}
    for part, sel in (("IS", lambda t: t["day"] < split), ("OOS", lambda t: t["day"] >= split)):
        P_("\n" + "=" * 20 + " %s %s" % (market.upper(), part))
        P_("  %-28s %6s %8s %7s %8s %7s %8s %6s %5s %7s | %s" % (
            "config", "trades", "gross", "cost", "net", "±CI", "median", "win%", "PF", "maxDD", "exits"))
        for name in names:
            trs = [t for t in trades_of(name) if sel(t)]
            kg, kc = keys(name)
            s = summary(trs, kg, kc)
            if not s:
                P_("  %-28s no trades" % name)
                continue
            if name == "baseline":
                base[part] = (s, trs)
            cats = {}
            for t in trs:
                cats[exit_cat(t["reason"])] = cats.get(exit_cat(t["reason"]), 0) + 1
            P_("  %-28s %6d %+8.3f %7.3f %+8.3f %7.3f %+8.3f %5.1f%% %5.2f %7.1f | %s" % (
                name, s["n"], s["gross"], s["cost"], s["net"], s["ci"], s["median"], 100 * s["win"], s["pf"], s["dd"],
                ", ".join("%s %d" % kv for kv in sorted(cats.items(), key=lambda x: -x[1]))))
        P_("  stop distance / planned R (baseline): stop %% median %.3f, stop ATR median %.2f, planned R median %.2f "
           "mean %.2f" % (_med([t["stop_pct"] for t in base[part][1]]),
                          _med([t["stop_atr"] for t in base[part][1] if t["stop_atr"] is not None]),
                          _med([t["planned"] for t in base[part][1]]),
                          sum(t["planned"] for t in base[part][1]) / len(base[part][1])))
    P_("\nREJECTIONS / FUNNEL (whole period): setups created, confirmations, ended reasons")
    for name, _ in CONFIGS:
        st, why = {}, {}
        for r in res.values():
            for k, v in r[name]["stats"].items():
                st[k] = st.get(k, 0) + v
            for k, v in r[name]["why"].items():
                why[k] = why.get(k, 0) + v
        P_("  %-28s BOS setups %d, confirmations %d, cost-rejected %d | ended: %s" % (
            name, st.get("bos", 0), st.get("confirmations", 0), st.get("cost_rejected", 0),
            ", ".join("%s %d" % kv for kv in sorted(why.items(), key=lambda x: -x[1])) or "-"))
    npart = sum(1 for r in res.values() for t in r["baseline"]["trades"] if t.get("partial") and
                abs(t["partial"]["gross"] - t["gross"]) > 1e-12)
    P_("  %s: partial taken on %d baseline trades (NSE trades of 1 share cannot be split: kept whole)" % (PARTIAL, npart))
    P_("\nDECISION (declared rule: better net mean IS and OOS, OOS Welch 95% CI of the difference excludes 0):")
    for name in names[1:]:
        kg, kc = keys(name)
        verdict = []
        ok = True
        for part, sel in (("IS", lambda t: t["day"] < split), ("OOS", lambda t: t["day"] >= split)):
            trs = [t for t in trades_of(name) if sel(t)]
            s, b = summary(trs, kg, kc), base[part][0]
            if not s:
                ok = False
                verdict.append("%s no trades" % part)
                continue
            d = s["net"] - b["net"]
            se = math.sqrt(s["sd"] ** 2 / s["n"] + b["sd"] ** 2 / b["n"])
            verdict.append("%s %+.3f (n %d vs %d) diff %+.3f ±%.3f" % (part, s["net"], s["n"], b["n"], d, 1.96 * se))
            if d <= 0 or (part == "OOS" and d - 1.96 * se <= 0):
                ok = False
        P_("  %-28s %s -> %s" % (name, " | ".join(verdict), "ACCEPTED" if ok else "REJECTED"))
    return "\n".join(L)


def _med(xs):
    s = sorted(xs)
    n = len(s)
    return float("nan") if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)


def main(argv=None):
    import argparse
    import json
    from multiprocessing import Pool
    import research_features as F
    import research_tf as TF
    ap = argparse.ArgumentParser(prog="research_scanner_v4.py fixes")
    ap.add_argument("market", choices=["nse", "us"])
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    tm = V4.tm_settings(P.load_config()["accounts"].get({"nse": "INDIA", "us": "US"}[a.market], {}))
    data = F.load(a.market)
    with Pool(a.workers, maxtasksperchild=4) as pool:
        res = dict(pool.imap_unordered(chart, [(a.market, s, r, tm) for s, r in data.items()]))
    print(report(a.market, res, TF.SPLIT[a.market]))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({s: {n: v["trades"] for n, v in r.items()} for s, r in res.items()}, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
