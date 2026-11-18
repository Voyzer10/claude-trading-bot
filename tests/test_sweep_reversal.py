#!/usr/bin/env python3
"""Scanner v3's setup (sweep_reversal.py) against the owner's workflow PDF (offline).

    python tests/test_sweep_reversal.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import smc_playbook as PB  # noqa: E402
import sweep_reversal as V  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


def build(tail):
    """Zigzag base (swing highs 100.6, lows 99.8), a BOS candle closing 101.3, a pullback, then `tail` (o, h, l, c).
    The BOS move started from the 99.8 low: the level to sweep."""
    t, rows = [datetime(2026, 11, 3, tzinfo=timezone.utc)], []

    def add(o, h, l, c):
        rows.append((t[0], o, h, l, c, 100))
        t[0] += timedelta(minutes=5)
    for k in range(40):
        b = 100 + (0.4 if (k // 3) % 2 else 0.0)
        add(b, b + 0.2, b - 0.2, b + 0.05)
    for c in [(100.4, 101.4, 100.3, 101.3),          # BOS: closes above the 100.6 swing high
              (101.3, 101.6, 101.0, 101.5), (101.5, 101.6, 100.9, 101.0)]:
        add(*c)
    for c in tail:
        add(*c)
    return rows


SWEEP = (101.0, 101.05, 99.6, 99.7)       # red, below 99.8 and closes below it
WICK_SWEEP = (101.0, 101.05, 99.6, 99.9)  # red, trades below 99.8 but closes above it
STAR = (99.70, 100.20, 99.66, 99.80)      # inverted hammer at the low (body 19%, upper wick 74%)
CONF = (99.8, 100.5, 99.75, 100.4)        # closes 100.4 > the star's high 100.2
CONF_WICK = (99.8, 100.5, 99.75, 100.15)  # trades above 100.2, closes below it
INSIDE = (99.8, 100.0, 99.7, 99.85)


def sigs(rows, **kw):
    return V.signals(rows, lambda x: x.date(), **kw)[1]


if __name__ == "__main__":
    check("1. BOS + sweep + signal, no confirmation yet: no order", not sigs(build([SWEEP, STAR])))
    got = sigs(build([SWEEP, STAR, CONF]))
    check("2. close above the signal high: one buy", len(got) == 1 and got[0]["side"] == "long", got)
    if got:
        g = got[0]
        check("   swept the BOS move's starting low 99.8", g["level_name"] == "bos_origin" and abs(g["level"] - 99.8) < 1e-9, g)
        check("   signal = inverted hammer, confirmed on the next candle",
              g["signal_pattern"] == "inverted hammer" and g["conf_offset"] == 1, g)
        stop = V.stop_for(g)
        check("   stop below the swept low 99.6", stop < 99.6, stop)
        check("   target = the BOS move's high 101.6 (broken swing highs are not targets)",
              abs(g["swing_target"] - 101.6) < 1e-9, g["swing_target"])
        check("   reclaimed: the entry closed back above the swept 99.8", g["reclaimed"] is True, g)
        check("   R:R of that target is over 1", V.rr(g, stop, V.target_for(g, "swing", stop)) > 1)
    check("3. wick above the trigger, close below: no order", not sigs(build([SWEEP, STAR, CONF_WICK])))
    check("4. sweep by a wick only (close back above the low): no order", not sigs(build([WICK_SWEEP, STAR, CONF])))
    check("5. confirmation on the 3rd candle: no order", not sigs(build([SWEEP, STAR, INSIDE, INSIDE, CONF])))
    check("6. trigger = sweep candle high (101.05): 100.4 is not above it", not sigs(build([SWEEP, STAR, CONF]), trigger="sweep"))
    big = sigs(build([SWEEP, STAR, (99.8, 102.6, 99.75, 102.5)]), ext=False)
    check("7. a huge confirmation candle is flagged extended", len(big) == 1 and big[0]["extended"], big)
    check("   ... and skipped by default", not sigs(build([SWEEP, STAR, (99.8, 102.6, 99.75, 102.5)])))
    check("8. no BOS first: no order", not sigs(build([SWEEP, STAR, CONF])[:40] + build([SWEEP, STAR, CONF])[43:]))
    sh = sigs(V.mirror(build([SWEEP, STAR, CONF])), short=True)
    check("mirror: the same picture upside down is one short (hammer at the top)",
          len(sh) == 1 and sh[0]["side"] == "short" and sh[0]["signal_pattern"] == "hammer", sh)
    own = PB.owner_setups(build([SWEEP, STAR, CONF]), lambda x: x.date())
    v3 = [o for o in own if o["setup"] == "v3_sweep_long"]
    check("Scanner v3: owner_setups names it on the confirmation candle", len(v3) == 1 and v3[0]["name"] == "v3 sweep long", own)
    if v3:
        check("   it carries the liquidity target", abs(v3[0]["target"] - 101.6) < 1e-9, v3[0])
    # FVG / OB retest (third PDF): reversal, an up-move that leaves gaps, a pullback into the gap, a close above
    # the pullback candle's high
    BIG_UP = (101.0, 103.0, 100.95, 102.9)          # the BOS move runs to 103 (the target)
    SWEEP_BIG = (102.9, 102.95, 99.6, 99.7)
    LEG = [(100.4, 100.9, 100.35, 100.85), (100.85, 101.45, 100.8, 101.4), (101.4, 101.55, 101.2, 101.5)]
    PULL = (101.5, 101.52, 101.1, 101.15)           # dips into the FVG 100.9..101.2, closes inside
    RT_CONF = (101.15, 101.58, 101.1, 101.55)       # closes above the pullback high 101.52
    rows_rt = build([BIG_UP, SWEEP_BIG, STAR, CONF] + LEG + [PULL, RT_CONF])
    rt = V.retest_signals(rows_rt, lambda x: x.date())[1]
    check("retest: no entry before the confirmation", not V.retest_signals(rows_rt[:-1], lambda x: x.date())[1])
    check("retest: pullback into the FVG + close above its high -> one buy",
          len(rt) == 1 and rt[0]["zone"] == "FVG" and abs(rt[0]["zone_top"] - 101.2) < 1e-9 and rt[0]["entry"] == 101.55, rt)
    if rt:
        check("   stop below the FVG (100.9), target the BOS move high 103",
              rt[0]["stop"] < 100.9 and abs(rt[0]["swing_target"] - 103.0) < 1e-9, rt[0])
    check("retest: a wick above the pullback high, close below -> no buy",
          not V.retest_signals(build([BIG_UP, SWEEP_BIG, STAR, CONF] + LEG + [PULL, (101.15, 101.58, 101.1, 101.45)]),
                               lambda x: x.date())[1])
    low_fvg = V.retest_signals(build([BIG_UP, SWEEP_BIG, STAR, CONF] + LEG + [(101.5, 101.52, 100.6, 100.7), RT_CONF]),
                               lambda x: x.date())[1]
    check("retest: closes below the upper gap but inside the lower one -> the lower FVG is the retest",
          len(low_fvg) == 1 and abs(low_fvg[0]["zone_top"] - 100.8) < 1e-9, low_fvg)
    check("retest: pullback closes below every zone -> no buy",
          not V.retest_signals(build([BIG_UP, SWEEP_BIG, STAR, CONF] + LEG + [(101.5, 101.52, 100.0, 100.1), RT_CONF]),
                               lambda x: x.date())[1])
    own_rt = [o for o in PB.owner_setups(rows_rt, lambda x: x.date()) if o["setup"] == "v3_retest_long"]
    check("Scanner v3 names it 'v3 FVG/OB retest long' with the liquidity target",
          len(own_rt) == 1 and own_rt[0]["name"] == "v3 FVG/OB retest long" and own_rt[0]["target"] == 103.0, own_rt)
    check("rollback v2: no retest setups either",
          not [o for o in PB.owner_setups(rows_rt, lambda x: x.date(), version="v2") if o["setup"].startswith("v3_")])
    sh_rt = V.retest_signals(V.mirror(rows_rt), lambda x: x.date(), short=True)[1]
    check("retest mirror: one short", len(sh_rt) == 1 and sh_rt[0]["side"] == "short", sh_rt)

    # rollback to Scanner v2: one switch per account, scanners and the broker both obey it
    check("rollback: owner_setups(version='v2') has no v3 setup",
          not [o for o in PB.owner_setups(build([SWEEP, STAR, CONF]), lambda x: x.date(), version="v2")
               if o["setup"].startswith("v3_")])
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        P.fetch_price = lambda m, t: (100.4, None)
        check("scanner_version defaults to v3", PB.scanner_version("CRYPTO") == "v3" and PB.scanner_version("NSE") == "v3")
        if v3:
            rec = P.setup_decision("CRYPTO", "TST", v3[0], news=[])
            check("v3: the sweep long is paper traded with its liquidity target",
                  rec["result"] == "PAPER BUY" and rec["steps"]["4_exit"]["target"] == v3[0]["target"]
                  and rec["steps"]["1_scanner"]["scanner"] == "v3", rec)
            pos = next((x for x in P.load_ledger(P.load_config())["open"] if x["key"] == "CRYPTO:TST"), {})
            check("   the position records why: setup, scanner, liquidity, entry reason",
                  pos.get("setup") == "v3_sweep_long" and pos.get("scanner") == "v3"
                  and "swept" in (pos.get("liquidity") or "") and "Scanner v3" in (pos.get("entry_reason") or "") and "R:R" in pos["entry_reason"], pos)
            v2rec = P.setup_decision("CRYPTO", "ABC", {"setup": "abcd_long", "name": "A-B-C-D long", "side": "long",
                                                       "price": 100.4, "stop": 99.0, "target_2r": 103.2}, news=[])
            check("a v3 account never trades a v2 setup", v2rec["result"] == "skipped" and "v2 setups are off" in v2rec["why"], v2rec)
        cfg = P.load_config()
        cfg["accounts"]["INDIA"]["scanner_version"] = "v2"
        P.save_json(P.CONFIG, cfg)
        check("rollback is per account: INDIA v2, CRYPTO still v3",
              PB.scanner_version("NSE") == "v2" and PB.scanner_version("CRYPTO") == "v3")
        if v3:
            rec = P.setup_decision("NSE", "TST", dict(v3[0]), news=[])
            check("rolled back: a v3 setup reaching the broker is skipped, not traded",
                  rec["result"] == "skipped" and "v2" in rec["why"], rec)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
