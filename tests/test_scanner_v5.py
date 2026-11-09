#!/usr/bin/env python3
"""Scanner v5 (scanner_v5.py, the "0.146 level" from the owner's reel, 10 Nov 2026). Offline.

    python tests/test_scanner_v5.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scanner_v5 as V5  # noqa: E402
import smc_playbook as PB  # noqa: E402

FAILS = []
DAY = lambda x: x.date()  # noqa: E731


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def build(tail):
    """A quiet base, an up-move from 99.0 to ~110, a pull-back towards 101.8, then `tail` (o, h, l, c).
    Level for C=0.146: 99.0 + 0.146 x 11.1 ~ 100.62."""
    t, rows = [datetime(2026, 11, 3, 3, 45, tzinfo=timezone.utc)], []

    def add(o, h, l, c):
        rows.append((t[0], o, h, l, c, 100))
        t[0] += timedelta(minutes=5)
    for k in range(40):
        b = 100 + (0.3 if (k // 3) % 2 else 0)
        add(b, b + 0.2, b - 0.2, b + 0.05)
    for c in [(100.0, 100.1, 99.0, 99.2), (99.2, 99.5, 99.1, 99.4), (99.4, 99.6, 99.3, 99.5)]:
        add(*c)
    px = 99.5
    for _ in range(10):
        n = px + 1.05
        add(px, n + 0.1, px - 0.05, n)
        px = n
    add(px, 110.0, px - 0.2, 109.6)
    for c in [(109.6, 109.7, 108.5, 108.8), (108.8, 108.9, 107.0, 107.2), (107.2, 107.3, 105.0, 105.3),
              (105.3, 105.4, 103.0, 103.2), (103.2, 103.3, 101.5, 101.8)]:
        add(*c)
    for c in tail:
        add(*c)
    return rows


TOUCH = (101.8, 101.9, 100.55, 101.0)      # wicks to the level, closes back above it
UP = [(101.0, 103, 100.9, 102.8), (102.8, 106, 102.7, 105.9), (105.9, 110.2, 105.8, 110.1)]


if __name__ == "__main__":
    good = build([TOUCH] + UP)
    s = [t for t in V5.sequence(good, DAY) if t["side"] == "long"]
    check("1. up-move 99 -> 110, pull-back touches low + 0.146 x range (~100.62) and closes above: LONG",
          len(s) == 1 and abs(s[0]["level"] - (99.0 + 0.146 * s[0]["range"])) < 1e-9 and s[0]["entry"] == 101.0, s)
    if s:
        check("   stop just below the move's low 99.0, target the move's high, exit at the target",
              98.8 < s[0]["stop"] < 99.0 and s[0]["target"] == s[0]["leg_high"] and s[0]["exit_reason"] == "target", s[0])
    through = build([(101.8, 101.9, 100.3, 100.4)] + UP)
    check("2. a candle CLOSES below the level: that move is cancelled, no trade",
          not [t for t in V5.sequence(through, DAY) if t["side"] == "long"])
    swept = build([(101.8, 101.9, 98.7, 100.8)] + UP)
    check("3. price trades below the move's low (99.0): no trade (the level failed)",
          not [t for t in V5.sequence(swept, DAY) if t["side"] == "long"])
    far = build([(101.8, 101.9, 101.2, 101.6)] + UP)
    check("4. the pull-back stops short of the level: no trade", not [t for t in V5.sequence(far, DAY) if t["side"] == "long"])
    c30 = [t for t in V5.sequence(good, DAY, c=0.30) if t["side"] == "long"]
    c10 = [t for t in V5.sequence(good, DAY, c=0.10) if t["side"] == "long"]
    check("5. the constant moves the level: same chart, C=0.30 (~102.3: the pull-back closed below it -> cancelled) "
          "and C=0.10 (~100.1: never reached) give no trade; only 0.146 is touched and held", not c30 and not c10,
          (c30, c10))
    sh = V5.sequence(V5.mirror(good), DAY)
    check("6. mirror: the same picture upside down is a SHORT at high - 0.146 x range", [t["side"] for t in sh] == ["short"], sh)
    check("7. the 'day' move (today's low -> high) finds the same trade here",
          [t["side"] for t in V5.sequence(good, DAY, move="day") if t["side"] == "long"] == ["long"])
    check("8. target 2R: the target is entry + 2 x risk",
          all(abs(t["target"] - (t["entry"] + 2 * (t["entry"] - t["stop"]))) < 1e-9
              for t in V5.sequence(good, DAY, target="2R") if t["side"] == "long"))

    # the scanner: v5 setups only for a v5 account, named, never from v2 / v3 / v4
    i = s[0]["i"] if s else -1
    got = PB.owner_setups(good[:i + 1], DAY, version="v5")
    check("9. Scanner v5 names the trade on its candle ('v5 0.146 support long', the level in words)",
          [g["setup"] for g in got] == ["v5_level_long"] and got[0]["scanner"] == "v5" and "support level" in
          got[0]["liquidity"] and PB.setup_version("v5_level_long") == "v5", got)
    for v in ("v2", "v3", "v4"):
        check("   Scanner %s never returns v5 setups" % v,
              not [g for g in PB.owner_setups(good[:i + 1], DAY, version=v) if g["setup"].startswith("v5_")])

    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        cfg = P.load_config()
        cfg["accounts"]["CRYPTO"].update({"scanner_version": "v5", "trade_setups": False})
        P.save_json(P.CONFIG, cfg)
        check("10. the switch accepts v5, and v5 is 'own setups only' (older rules off)",
              PB.scanner_version("CRYPTO") == "v5" and PB.v4_only("CRYPTO") == "v5")
        check("    v5 settings come from the account (C, move, target)",
              PB.v5_params("CRYPTO") == {"c": 0.146, "move": "swing", "target": "leg"})
        rec = P.setup_decision("CRYPTO", "TST", got[0], news=[])
        v4rec = P.setup_decision("CRYPTO", "TST", {"setup": "v4_primary_long", "name": "v4 primary long",
                                                   "side": "long", "price": 100.0, "stop": 99.0, "target": 103.0})
        check("    a v5 account takes the v5 setup through the agents and skips a v4 one",
              rec["result"] == "LOG ONLY" and v4rec["result"] == "skipped" and "Scanner v5" in v4rec["why"], (rec, v4rec))
        cfg = P.load_config()
        cfg["accounts"]["CRYPTO"]["v5_setups"] = ["v5_level_short"]
        P.save_json(P.CONFIG, cfg)
        r2 = P.setup_decision("CRYPTO", "TST", got[0], news=[])
        check("    an unticked v5 setup is skipped with the reason", r2["result"] == "skipped" and "unticked" in r2["why"], r2)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
