#!/usr/bin/env python3
"""Sweep v1 (owner, 20 Nov 2026): a wick through the protected swing, closing back inside, within the windows. Offline.

The chart is test_scanner_v4's: a bullish BOS at candle 40 (swing high 100.6), its protected Higher Low 99.8;
candles 41-44 run to 103 and drop to 100.6; the tail starts at candle 45. ATR there ~0.81, so 0.25 ATR ~0.20.

  1. A wick to 99.75 (0.05 deep) closing 100.1: a valid sweep and reclaim; a doji, then its break and close: a BUY.
  2. A close below 99.8 (any candle, before or after the sweep): the BOS is invalidated; no ATR tolerance.
  3. A wick deeper than 0.25 ATR: rejected (too deep), even with the close back inside.
  4. No sweep within sweep_max_bars: expired. No entry within entry_max_bars of the sweep: expired.
  5. NSE / US (intraday): a setup never crosses the night. Crypto (not intraday): only the candle expiry.
  6. The old "close" rule is unchanged (sweep_rule default).

    python tests/test_sweep_v1.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


if __name__ == "__main__":
    import scanner_v4 as V4
    V4.DEFAULTS.update(swing_k=2, bos_gap_skip=False, structure_bos=False, bos_rule="swings")  # the hand-built chart
    from test_scanner_v4 import build, SWEEP, TRIG, UP1, TP, DAY

    def run(rows, **kw):
        ended = []
        trades = [t for t in V4.sequence(rows, DAY, _ended=ended, **dict({"sweep_rule": "v1"}, **kw))
                  if t["side"] == "long" and t["kind"] == "primary"]
        return trades, [(st["bos"], j, why) for st, j, why in ended if st["bos"] == 40]

    WSW = (100.2, 100.3, 99.75, 100.1)       # wick to 99.75 (0.05 under 99.8), close back above
    DOJ = (100.1, 100.35, 99.95, 100.11)     # long-legged doji (high 100.35)
    TRG = (100.11, 100.6, 100.05, 100.55)    # closes above the doji's high
    FLAT = (100.3, 100.4, 100.2, 100.3)      # nothing happens

    t, e = run(build([WSW, DOJ, TRG, UP1, TP]))
    check("1. wick sweep + reclaim on the same candle, doji, break and close: a BUY with the fields kept apart",
          len(t) == 1 and t[0]["sweep"] == t[0]["reclaim"] == 45 and t[0]["signal"] == 46 and t[0]["i"] == 47
          and abs(t[0]["liq_ref"] - 99.8) < 1e-9 and abs(t[0]["bos_origin"] - 99.8) < 1e-9
          and abs(t[0]["bos_level"] - 100.6) < 1e-9 and abs(t[0]["sweep_pen"] - 0.05) < 1e-9 and t[0]["sweep_atr"] > 0,
          (t, e))

    t, e = run(build([SWEEP, DOJ, TRG, UP1, TP]))
    check("2. a candle CLOSING below the protected Higher Low (99.6 < 99.8): invalidated, no trade",
          not t and e and e[0][1] == 45 and "protected swing" in e[0][2], (t, e))
    t, e = run(build([(100.2, 100.3, 99.79, 99.795), DOJ, TRG, UP1, TP]))
    check("   even 0.005 under it (no ATR tolerance on closes)", not t and e and "protected swing" in e[0][2], (t, e))
    t, e = run(build([WSW, (100.1, 100.2, 99.7, 99.78), TRG, UP1, TP]))
    check("   a close below it AFTER a valid sweep also invalidates", not t and e and "after the sweep" in e[0][2], (t, e))

    t, e = run(build([(100.2, 100.3, 99.5, 100.1), DOJ, TRG, UP1, TP]))
    check("3. a wick 0.30 deep (> 0.25 ATR ~0.20) closing back inside: rejected as too deep",
          not t and e and e[0][2].startswith("wick too deep"), (t, e))
    t, e = run(build([(100.2, 100.3, 99.5, 100.1), DOJ, TRG, UP1, TP]), sweep_pen_atr=0.5)
    check("   with sweep_pen_atr 0.5 the same wick is a valid sweep", len(t) == 1, (t, e))

    t, e = run(build([FLAT] * 8 + [WSW, DOJ, TRG, UP1, TP]))
    check("4. no sweep in the 12 candles after the BOS (41-52): expired at 52", not t and e and e[0][1] == 52
          and e[0][2].startswith("no sweep within 12"), (t, e))
    t, e = run(build([FLAT] * 8 + [WSW, DOJ, TRG, UP1, TP]), sweep_max_bars=16)
    check("   with sweep_max_bars 16 it trades", len(t) == 1, (t, e))
    t, e = run(build([WSW] + [FLAT] * 13 + [DOJ, TRG, UP1, TP]))
    check("   no entry within 12 candles of the sweep: expired", not t and e and e[0][2].startswith("no entry within 12"),
          (t, e))

    base = build([])

    def next_day(rows, cands):
        t0 = rows[-1][0]
        t1 = datetime(t0.year, t0.month, t0.day, tzinfo=timezone.utc) + timedelta(days=1, hours=4)
        return list(rows) + [(t1 + timedelta(minutes=5 * k), *c, 100) for k, c in enumerate(cands)]
    nd = next_day(base, [WSW, DOJ, TRG, UP1, TP])
    t, e = run(nd, intraday=True)
    check("5. NSE / US: the next session's sweep does not count (the setup ended overnight)",
          not t and e and e[0][2] == "overnight", (t, e))
    t, e = run(nd, intraday=False, sweep_max_bars=20)
    check("   crypto: the day changes nothing, only the candle count (the sweep 5 candles after the BOS day's end)",
          len(t) == 1, (t, e))

    old = [x for x in V4.sequence(build([SWEEP, (99.62, 100.0, 99.58, 99.70), TRIG, UP1, TP]), DAY)
           if x["side"] == "long" and x["kind"] == "primary"]
    check("6. the old \"close\" rule (the default) is unchanged: the close below 99.8 is its sweep, a BUY",
          V4.DEFAULTS["sweep_rule"] == "close" and len(old) == 1 and old[0]["sweep"] == 45, old)
    print()
    if FAILS:
        print("%d check(s) failed" % len(FAILS))
        sys.exit(1)
    print("all checks passed")
