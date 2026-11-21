#!/usr/bin/env python3
"""Cost-aware eligibility (_Side._cost_ok, min_net_rr) for LONG and SHORT setups (21 Nov 2026). The short side runs on
the mirrored chart (prices negated), so _cost_ok converts its src prices back to REAL positive prices before calling
the cost function; these tests pin that down, the NSE / US cost on shorts, accept / reject, the default-off path and
the explicit rejection of trades the market cannot size. Offline.

    python tests/test_cost_ok_sides.py
"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import paper as P  # noqa: E402
import research_costs as RC  # noqa: E402
import scanner_v4 as V4  # noqa: E402
from test_choch_lifecycle import walk  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def side(name, k=1.0, fn=None):
    return SimpleNamespace(p={"min_net_rr": k, "_cost_fn": fn}, side_name=name, stats={}, ended=[])


def ok(sd, c, stop, tgt):
    return V4._Side._cost_ok(sd, c, stop, tgt, 7, {"bos": 1})


if __name__ == "__main__":
    day = lambda t: t.date()                                  # noqa: E731
    w = walk(40, 9)
    calls = {"long": [], "short": []}
    src = {"long": [], "short": []}
    orig = V4._Side._cost_ok

    def spy(self, c, stop, tgt, j, st=None):
        src[self.side_name].append(c)
        return orig(self, c, stop, tgt, j, st)

    def rec(side_, e, x, s):
        calls[side_].append((e, x, s))
        return 0.3
    V4._Side._cost_ok = spy
    try:
        V4.sequence(w, day, intraday=True, min_net_rr=1.0, _cost_fn=rec)
    finally:
        V4._Side._cost_ok = orig
    L, S = calls["long"], calls["short"]
    check("1. long: the cost function gets positive real prices, stop < entry < target",
          L and all(e > 0 and x > 0 and s > 0 and s < e < x for e, x, s in L), L[:2])
    check("2. short: the engine's own prices are negative (mirrored chart), the cost function gets positive real "
          "prices, target < entry < stop", S and all(c < 0 for c in src["short"])
          and all(e > 0 and x > 0 and s > 0 and x < e < s for e, x, s in S), (src["short"][:1], S[:2]))
    # 3. short NSE through research_costs: the INDIA sizing and both orders (entry = SELL, exit = BUY)
    nse_calls = []

    def nse_fn(side_, e, x, s):
        got = RC.nse("X", side_, e, x, s)
        nse_calls.append((side_, e, x, s, got))
        return None if got is None else got["total_r"]
    V4.sequence(w, day, intraday=True, min_net_rr=1.0, _cost_fn=nse_fn)
    cfg = P.DEFAULT_CONFIG
    acc = cfg["accounts"]["INDIA"]
    good = 0
    shorts = [x for x in nse_calls if x[0] == "short" and x[4] is not None]
    for side_, e, x, s, got in shorts:
        qty = int(min(acc["max_loss_per_trade"] / (s - e), acc["capital"] * acc["max_position_pct"] / 100 / e))
        good += (got["qty"] == qty and abs(got["entry_fees"] - P.charges(cfg, "NSE", "X", "sell", qty * e)) < 1e-9
                 and abs(got["exit_fees"] - P.charges(cfg, "NSE", "X", "buy", qty * x)) < 1e-9
                 and abs(got["total_r"] - (got["entry_fees"] + got["exit_fees"]) / (qty * (s - e))) < 1e-12)
    check("3. short NSE: quantity from the INDIA sizing, the SELL entry and the BUY exit both charged (%d calls)" % len(
        shorts), shorts and good == len(shorts), (good, len(shorts)))
    # 4. short US
    us_calls = []

    def us_fn(side_, e, x, s):
        got = RC.us("X", side_, e, x, s, P.DEFAULT_CONFIG)
        us_calls.append((side_, e, x, s, got))
        return got["total_r"]
    V4.sequence(w, day, intraday=True, min_net_rr=1.0, _cost_fn=us_fn)
    us_short = [x for x in us_calls if x[0] == "short"]
    check("4. short US: (entry + exit) x (fee_pct + 0.02%%) a side / risk, at the real prices (%d calls)" % len(us_short),
          us_short and all(abs(got["total_r"] - (e + x) * RC.US_SPREAD_SLIP_SIDE / (s - e)) < 1e-12
                           for _, e, x, s, got in us_short))
    # 5 / 6. a short in src terms: entry -100 (real 100), stop -101 (real 101), target -97 (real 97): 3R planned
    seen = []

    def half(side_, e, x, s):
        seen.append((side_, e, x, s))
        return 0.5
    sd = side("short", 1.0, half)
    check("6. short accepted: 3R planned, 0.5R cost -> net 2.5R >= 1.5R; real prices (100, 97, 101) passed",
          ok(sd, -100.0, -101.0, -97.0) is True and seen == [("short", 100.0, 97.0, 101.0)], seen)
    sd = side("short", 1.0, half)
    check("5. short rejected: 0.8R planned, 0.5R cost -> net 0.3R < 1.5R; counted as a short rejection with a reason",
          ok(sd, -100.0, -101.0, -100.8) is False and sd.stats.get("cost_rejected_short") == 1
          and sd.ended and sd.ended[0][2].startswith("cost: net reward"), (sd.stats, sd.ended))
    sl = side("long", 1.0, half)
    check("   long mirror of 5 / 6: accepted at 3R, rejected at 0.8R",
          ok(sl, 100.0, 99.0, 103.0) is True and ok(sl, 100.0, 99.0, 100.8) is False
          and sl.stats.get("cost_rejected_long") == 1)
    # 7. default off / no cost function
    key = lambda ts: [(t["kind"], t["side"], t["i"], t.get("exit_i"), t.get("exit")) for t in ts]   # noqa: E731
    base = V4.sequence(w, day, intraday=True)
    check("7. default off: no min_net_rr, min_net_rr with _cost_fn None, min_net_rr 0 -> identical trades",
          "min_net_rr" not in V4.DEFAULTS and key(base) == key(V4.sequence(w, day, intraday=True, min_net_rr=1.0))
          and key(base) == key(V4.sequence(w, day, intraday=True, min_net_rr=0, _cost_fn=half))
          and ok(side("short", 1.0, None), -100.0, -101.0, -100.8) is True
          and ok(side("short", 0, half), -100.0, -101.0, -100.8) is True)
    # 8. a trade the market cannot size: rejected, never costed as zero
    sd = side("short", 1.0, lambda *a: None)
    check("8. not sizeable (cost None): REJECTED with 'cost: not sizeable', counted per side; not treated as 0 cost",
          ok(sd, -100.0, -101.0, -97.0) is False and sd.stats.get("cost_unsizeable_short") == 1
          and sd.ended[0][2] == "cost: not sizeable", (sd.stats, sd.ended))
    big = RC.nse("X", "short", 30000.0, 29000.0, 30100.0)
    check("   (NSE: one share above the INDIA position cap -> research_costs returns None)", big is None)
    # 9. defaults unchanged
    check("9. defaults unchanged: sweep close, target opp_bos_cap, breakeven 1R, buffer 0.1 ATR, min_rr 0",
          V4.DEFAULTS["sweep_rule"] == "close" and V4.DEFAULTS["target_rule"] == "opp_bos_cap"
          and V4.DEFAULTS["tm_be_r"] == 1.0 and V4.DEFAULTS["buffer_atr"] == 0.1 and V4.DEFAULTS["min_rr"] == 0.0)
    print("\n%d failed" % len(FAILS) if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
