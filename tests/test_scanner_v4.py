#!/usr/bin/env python3
"""Scanner v4 (scanner_v4.py) against the owner's "Final Trading Workflow" PDF (7 Nov 2026). Offline.

    python tests/test_scanner_v4.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scanner_v4 as V4  # noqa: E402
import smc_playbook as PB  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def build(tail, bos_vol=300, drop_low=100.0):
    """Zigzag base (swing highs 100.6, lows 99.8), a decisive BOS candle closing 101.3 above 100.6 on 3x volume, a
    pullback, a run to 103 (the liquidity above), a drop, then `tail` (o, h, l, c). The BOS move started from the
    99.8 low. drop_low=100.5 leaves a bearish FVG right above the entry (an opposing zone)."""
    t, rows = [datetime(2026, 11, 3, tzinfo=timezone.utc)], []

    def add(o, h, l, c, v=100):
        rows.append((t[0], o, h, l, c, v))
        t[0] += timedelta(minutes=5)
    for k in range(40):
        b = 100 + (0.4 if (k // 3) % 2 else 0.0)
        add(b, b + 0.2, b - 0.2, b + 0.05)
    add(100.4, 101.4, 100.3, 101.3, bos_vol)        # BOS: closes above the 100.6 swing high
    for c in [(101.3, 101.6, 101.0, 101.5), (101.5, 101.6, 100.9, 101.0),
              (101.0, 103.0, 100.95, 102.9),         # the move's high 103 = liquidity for the target
              (102.9, 102.95, drop_low, 100.6)]:     # a drop (does not trade below 99.8)
        add(*c)
    for c in tail:
        add(*c)
    return rows


SWEEP = (100.6, 101.0, 99.6, 99.9)       # trades below 99.8 and closes back above it (sweep + reclaim, one candle)
HAMMER = (99.9, 100.05, 99.62, 100.0)    # hammer at the low
TRIG = (100.0, 100.4, 99.95, 100.3)      # breaks and CLOSES above the hammer high 100.05 -> primary BUY
TRIG_WICK = (100.0, 100.4, 99.95, 100.04)
LEG = [(100.3, 100.9, 100.25, 100.85), (100.85, 101.45, 100.8, 101.4), (101.4, 101.55, 101.2, 101.5)]  # FVG 100.9-101.2
TP = (101.5, 103.1, 101.45, 103.0)       # primary target 103 hit -> primary CLOSED
PULL = [(103.0, 103.05, 102.0, 102.1), (102.1, 102.15, 101.3, 101.35)]
TAP = (101.35, 101.4, 101.1, 101.15)     # taps the FVG (top 101.2) and closes inside
NEAR = (101.35, 101.4, 101.25, 101.3)    # comes near (101.25) but does not touch 101.2
CONF = (101.15, 101.6, 101.1, 101.5)     # closes above the tap candle's high 101.4 -> secondary BUY
DAY = lambda x: x.date()  # noqa: E731


def seq(rows):
    return V4.sequence(rows, DAY)


if __name__ == "__main__":
    full = build([SWEEP, HAMMER, TRIG] + LEG + [TP] + PULL + [TAP, CONF])
    s = seq(full)
    prim = [t for t in s if t["kind"] == "primary"]
    sec = [t for t in s if t["kind"] == "secondary"]
    check("1. primary BUY: BOS -> sweep + reclaim -> hammer -> break + close", len(prim) == 1 and prim[0]["side"] == "long"
          and prim[0]["entry"] == 100.3 and prim[0]["signal_pattern"] == "hammer", s)
    if prim:
        p = prim[0]
        check("   SL below the sweep low 99.6, TP the next liquidity 103", p["stop"] < 99.6 and p["target"] == 103.0, p)
        check("   the primary closes at its target before anything else", p["exit_reason"] == "target", p)
    check("2. secondary BUY only after the primary closed: FVG tapped + close above the tap high",
          len(sec) == 1 and sec[0]["zone"] == "FVG" and sec[0]["entry"] == 101.5 and sec[0]["i"] > prim[0]["exit_i"], s)
    if sec:
        check("   secondary SL below the zone (100.9), target above", sec[0]["stop"] < 100.9 and sec[0]["target"] > 101.5, sec[0])

    no_reclaim = build([(100.6, 100.7, 99.5, 99.55), (99.55, 99.7, 99.4, 99.5), (99.5, 99.7, 99.45, 99.6),
                        (99.6, 99.75, 99.5, 99.65), (99.65, 99.78, 99.5, 99.7), HAMMER, TRIG])
    check("3. price accepts below the old low (no reclaim within 3 candles): no trade",
          not [t for t in seq(no_reclaim) if t["side"] == "long"], seq(no_reclaim))
    check("4. trigger wick above the hammer high, close below: no trade",
          not [t for t in seq(build([SWEEP, HAMMER, TRIG_WICK])) if t["side"] == "long"])
    check("5. confirmation on the 3rd candle: no trade",
          not [t for t in seq(build([SWEEP, HAMMER, (100.0, 100.05, 99.9, 100.0), (100.0, 100.05, 99.9, 99.98), TRIG]))
               if t["side"] == "long"])
    open_prim = build([SWEEP, HAMMER, TRIG] + LEG + [(101.5, 101.6, 101.1, 101.15), CONF])
    s5 = seq(open_prim)
    check("6. no OB/FVG trade while the primary is still open (tap + confirmation ignored)",
          len(s5) == 1 and s5[0]["kind"] == "primary" and s5[0]["exit_i"] is None, s5)
    near = seq(build([SWEEP, HAMMER, TRIG] + LEG + [TP] + PULL + [NEAR, CONF]))
    check("7. near the zone is not a tap: no secondary", not [t for t in near if t["kind"] == "secondary"], near)
    no_conf = seq(build([SWEEP, HAMMER, TRIG] + LEG + [TP] + PULL + [TAP, (101.15, 101.38, 101.1, 101.3),
                                                                     (101.3, 101.39, 101.2, 101.35)]))
    check("8. tap without a break-and-close: no secondary", not [t for t in no_conf if t["kind"] == "secondary"], no_conf)
    stopped = seq(build([SWEEP, HAMMER, TRIG] + LEG + [(101.5, 101.55, 99.0, 99.2), (99.2, 99.6, 99.1, 99.5),
                                                       (99.5, 101.0, 99.4, 100.95)]))
    check("9. primary stopped out (closed through the zones): no secondary",
          stopped and stopped[0]["exit_reason"] == "stop" and not [t for t in stopped if t["kind"] == "secondary"], stopped)
    sh = V4.sequence(V4.mirror(full), DAY)
    check("10. mirror: the same picture upside down is a primary SELL then a secondary SELL",
          [(t["kind"], t["side"]) for t in sh] == [("primary", "short"), ("secondary", "short")], sh)

    # the PDF's skip rules (pages 1, 2, 4)
    base_tail = [SWEEP, HAMMER, TRIG]
    check("13. weak break: BOS on ordinary volume (1.0x < 1.2x) -> no trade",
          not [t for t in seq(build(base_tail, bos_vol=100)) if t["side"] == "long"])
    check("14. nearby opposing zone: an unfilled bearish FVG inside the first 1R -> no trade",
          not [t for t in seq(build([(100.6, 100.7, 99.6, 99.9), HAMMER, TRIG], drop_low=100.5)) if t["side"] == "long"])
    check("    ... the same picture with that rule off trades (the rule is what skipped it)",
          [t for t in V4.sequence(build([(100.6, 100.7, 99.6, 99.9), HAMMER, TRIG], drop_low=100.5), DAY, opp_zone=False)
           if t["side"] == "long"])
    weak = build(base_tail)
    weak[40] = (weak[40][0], 100.4, 101.4, 100.3, 100.65, 300)          # BOS closes just above: tiny body
    check("15. weak BOS candle body (under 0.8 ATR) -> no trade", not [t for t in seq(weak) if t["side"] == "long"])
    zig = [(datetime(2026, 11, 3, tzinfo=timezone.utc) + timedelta(minutes=5 * k), 100, 101, 99, 100 + (0.5 if k % 2 else -0.5), 1)
           for k in range(30)]
    check("16. choppy market: efficiency ratio of a zigzag is under 0.30", V4.efficiency(zig, 29, 20) < 0.30)
    h0 = datetime(2026, 11, 3, tzinfo=timezone.utc)
    down = []
    legs = []
    for w in range(8):                       # an hourly downtrend: 3 hours down, 2 hours up, lower each time
        top = 200 - 3 * w
        legs += [top, top - 2, top - 4, top - 2, top - 1]
    for hr, base in enumerate(legs):         # 12 x 5m candles per hour
        for q in range(12):
            down.append((h0 + timedelta(minutes=60 * hr + 5 * q), base, base + 0.6, base - 0.6, base, 1))
    dirs = V4.htf_dirs(down, DAY)
    check("17. higher timeframe: an hourly downtrend reads 'down' (longs skipped there)", dirs[-1] == "down", dirs[-12:])
    check("    and the mirror of it reads 'up' for shorts' (src) terms", V4.htf_dirs(V4.mirror(down), DAY)[-1] == "up")

    # the scanner: only v4 setups for a v4 account, named; v2 / v3 never return them
    i_prim = prim[0]["i"] if prim else -1
    got = PB.owner_setups(full[:i_prim + 1], DAY, version="v4")
    check("11. Scanner v4 names the primary on its candle ('v4 primary long', liquidity in words)",
          [g["setup"] for g in got] == ["v4_primary_long"] and got[0]["name"] == "v4 primary long"
          and "reclaimed" in got[0]["liquidity"] and got[0]["scanner"] == "v4", got)
    got2 = PB.owner_setups(full, DAY, version="v4")
    check("    and the secondary on its candle ('v4 OB/FVG secondary long')",
          [g["setup"] for g in got2] == ["v4_secondary_long"] and "FVG tap" in got2[0]["liquidity"], got2)
    for v in ("v2", "v3"):
        check("    Scanner %s never returns v4 setups" % v,
              not [g for g in PB.owner_setups(full[:i_prim + 1], DAY, version=v) if g["setup"].startswith("v4_")])

    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        P.fetch_price = lambda m, t: (100.3, datetime.now(timezone.utc))
        cfg = P.load_config()
        cfg["accounts"]["CRYPTO"]["scanner_version"] = "v4"
        P.save_json(P.CONFIG, cfg)
        check("12. the switch accepts v4", PB.scanner_version("CRYPTO") == "v4")
        rec = P.setup_decision("CRYPTO", "TST", got[0], news=[])
        check("    a v4 account paper trades the v4 primary with its liquidity target",
              rec["result"] == "PAPER BUY" and rec["steps"]["1_scanner"]["scanner"] == "v4"
              and rec["steps"]["4_exit"]["target"] == got[0]["target"], rec)
        v2rec = P.setup_decision("CRYPTO", "ABC", {"setup": "abcd_long", "name": "A-B-C-D long", "side": "long",
                                                   "price": 100.3, "stop": 99.0, "target_2r": 102.9}, news=[])
        v3rec = P.setup_decision("CRYPTO", "XYZ", {"setup": "v3_sweep_long", "name": "v3 sweep long", "side": "long",
                                                   "price": 100.3, "stop": 99.0, "target": 103.0}, news=[])
        check("    a v4 account skips v2 and v3 setups",
              v2rec["result"] == "skipped" and v3rec["result"] == "skipped" and "Scanner v4" in v3rec["why"], (v2rec, v3rec))
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
