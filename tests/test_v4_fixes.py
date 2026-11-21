#!/usr/bin/env python3
"""Loss-fix candidates (21 Nov 2026): the cost-aware eligibility switch (min_net_rr + _cost_fn, off by default) and
the partial-profit replay of research_fixes_v4, long and mirrored short. Offline.

    python tests/test_v4_fixes.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import paper as P  # noqa: E402
import research_costs as RC  # noqa: E402
import research_fixes_v4 as FX  # noqa: E402
import scanner_v4 as V4  # noqa: E402
from test_choch_lifecycle import walk, reflect  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


if __name__ == "__main__":
    day = lambda t: t.date()                                  # noqa: E731
    key = lambda ts: [(t["kind"], t["side"], t["i"], t.get("exit_i"), t.get("exit")) for t in ts]   # noqa: E731
    w = walk(40, 9)
    base = V4.sequence(w, day, intraday=True)
    check("defaults: min_net_rr off; the same trades with no cost function, or min_net_rr 0",
          "min_net_rr" not in V4.DEFAULTS and key(base) == key(V4.sequence(w, day, intraday=True, min_net_rr=0,
                                                                            _cost_fn=lambda *a: 0.5))
          and key(base) == key(V4.sequence(w, day, intraday=True, min_net_rr=1.0)))
    # cost-aware: with zero costs the rule is reward >= 1 x risk (= min_rr 1 on the gross targets)
    zero = V4.sequence(w, day, intraday=True, min_net_rr=1.0, _cost_fn=lambda *a: 0.0)
    rr1 = V4.sequence(w, day, intraday=True, min_rr=1.0)
    check("min_net_rr 1.0 with zero cost == min_rr 1.0 (the same trades)", key(zero) == key(rr1), (len(zero), len(rr1)))
    calls = []

    def fn(side, e, x, st):
        calls.append((side, e, x, st))
        return 0.3
    stats, ended = {}, []
    got = V4.sequence(w, day, intraday=True, min_net_rr=1.0, _cost_fn=fn, _stats=stats, _ended=ended)
    ok_rr = all((t["target"] - t["entry"]) * (1 if t["side"] == "long" else -1) >= 0 for t in got)
    check("with a 0.3R cost every taken trade's planned net reward >= net risk; rejections counted with a reason",
          ok_rr and stats.get("cost_rejected", 0) > 0 and any(w_.startswith("cost: net reward") for _, _, w_ in ended),
          (stats, ended[:2]))
    check("the cost function gets REAL prices for both sides (short: entry above the stop is wrong, stop above entry "
          "right)", calls and all((st < e < x or x < e) if side == "long" else (st > e) for side, e, x, st in calls)
          and {"long", "short"} <= {c[0] for c in calls}, calls[:3])
    # partial replay, long and short (real prices)
    rows = walk(3, 4)
    sh = reflect(rows, axis=2000.0)
    t = {"side": "long", "entry": rows[10][1], "stop": rows[10][1] - 1.0, "target": rows[10][1] + 5.0, "i": 9,
         "exit_i": 30, "exit": rows[30][4], "exit_reason": "day end"}
    hi = max(r[2] for r in rows[10:31])
    took, p1 = FX.replay_partial(rows, t)
    check("partial (long): taken iff a candle from the fill to the exit reaches +1R; at entry + 1R",
          took == (hi >= t["entry"] + 1.0) and (not took or abs(p1 - (t["entry"] + 1.0)) < 1e-9), (took, p1, hi))
    ts = {"side": "short", "entry": sh[10][1], "stop": sh[10][1] + 1.0, "target": sh[10][1] - 5.0, "i": 9,
          "exit_i": 30, "exit": sh[30][4], "exit_reason": "day end"}
    lo = min(r[3] for r in sh[10:31])
    took_s, p1_s = FX.replay_partial(sh, ts)
    check("partial (short, mirrored chart): taken iff a low reaches entry - 1R; at entry - 1R",
          took_s == (lo <= ts["entry"] - 1.0) and (not took_s or abs(p1_s - (ts["entry"] - 1.0)) < 1e-9)
          and took_s == took, (took_s, p1_s, lo))
    stop_t = dict(t, exit_i=10, exit_reason="stop", exit=t["stop"])
    check("partial: a stop exit on the fill candle takes no partial (stop first)", FX.replay_partial(rows, stop_t)[0]
          is False)
    tgt_t = dict(t, exit_i=10, exit_reason="target", target=t["entry"] + 0.8, exit=t["entry"] + 0.8)
    check("partial: a target below +1R exits whole at the target", FX.replay_partial(rows, tgt_t)[0] is False)
    # partial costs: NSE entry once, two exit orders; US per side on every fill
    c, frac = FX.partial_leg("nse", "X", "long", 2000.0, 2010.0, 2020.0, 1990.0)
    cfg = P.DEFAULT_CONFIG
    want = (P.charges(cfg, "NSE", "X", "buy", 12 * 2000.0) + P.charges(cfg, "NSE", "X", "sell", 6 * 2010.0)
            + P.charges(cfg, "NSE", "X", "sell", 6 * 2020.0)) / (12 * 10.0)
    check("partial cost NSE: buy 12 once, sell 6 at +1R and 6 at the exit; R over the whole position",
          abs(c - want) < 1e-12 and frac == 0.5, (c, want))
    check("partial cost NSE: one share cannot be split -> None",
          FX.partial_leg("nse", "X", "long", 30000.0, 30100.0, 30200.0, 29900.0) is None)
    cu, fu = FX.partial_leg("us", "X", "long", 100.0, 101.0, 103.0, 99.0)
    check("partial cost US: (entry + half x p1 + half x exit) x 0.02% / risk",
          abs(cu - (100 + 50.5 + 51.5) * RC.US_SPREAD_SLIP_SIDE) < 1e-12 and fu == 0.5, cu)
    print("\n%d failed" % len(FAILS) if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
