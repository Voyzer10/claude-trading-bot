#!/usr/bin/env python3
"""No late entry and margin-aware sizing (owner, 19 Nov 2026). Offline.

  1. first_trigger: the first candle a v4 signal triggered on is kept; a later call returns it.
  2. setup_decision (HLT, 18 Nov): the trigger is blocked on its own candle (no free cash); the same signal offered
     on the next candle is skipped as a late entry, not taken. The same candle offered again (a restart) is not late.
  3. The "0 units fit" check counts the intraday margin: a $300 US stock fits a $1,000 account at 4x (25% cap).

    python tests/test_no_late_entry.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        ET = timezone(timedelta(hours=-5))
        sig = datetime(2026, 11, 18, 14, 0, tzinfo=ET)
        b1, b2 = "2026-11-18T14:10:00-05:00", "2026-11-18T14:15:00-05:00"

        # 1. first_trigger
        now_b1 = datetime.now(timezone.utc).isoformat()
        check("1. a new signal records this candle", P.first_trigger("US:HLT", "short", sig, now_b1) == now_b1)
        check("   a later candle gets the first one back",
              P.first_trigger("US:HLT", "short", sig, "2099-01-01T00:00:00+00:00") == now_b1)
        check("   the other side is its own signal",
              P.first_trigger("US:HLT", "long", sig, "2099-01-01T00:00:00+00:00") == "2099-01-01T00:00:00+00:00")
        os.remove(P.V4_TRIGGERS)

        # 2. setup_decision: blocked on its candle, skipped on the next
        cfg = P.load_config()
        cfg["accounts"]["US"]["scanner_version"] = "v4"
        P.save_json(P.CONFIG, cfg)
        led = P.load_ledger(cfg)
        P.book_of(led, "US")["cash"] = 4.16                    # open positions tie up the rest (HLT, 00:41 IST)
        P.save_json(P.LEDGER, led)
        P.fetch_price = lambda m, t: (372.77, datetime.now(timezone.utc))
        P.session = lambda m, n: "open"
        P.past_flat_by = lambda m, acc, n: False
        P.v4_timemachine = lambda *a, **k: None
        s = {"setup": "v4_primary_short", "side": "short", "scanner": "v4", "name": "v4 primary short",
             "price": 372.77, "stop": 374.53, "target": 369.37, "v4_signal_at": sig.isoformat(), "bar_end": b1,
             "details": {}}
        rec1 = P.setup_decision("US", "HLT", dict(s))
        check("2. on its own candle the trigger is blocked ($4.16 left: nothing fits)",
              rec1["result"] == "blocked", (rec1["result"], rec1.get("why")))
        led = P.load_ledger(P.load_config())
        P.book_of(led, "US")["cash"] = 1000.0                  # cash is free again a candle later
        P.save_json(P.LEDGER, led)
        rec2 = P.setup_decision("US", "HLT", dict(s, price=372.8, bar_end=b2))
        check("   the next candle: skipped as a late entry, not taken",
              rec2["result"] == "skipped" and rec2["why"].startswith("late entry") and "14:10" in rec2["why"]
              and not P.load_ledger(P.load_config())["open"], (rec2["result"], rec2.get("why")))
        rec3 = P.setup_decision("US", "HLT", dict(s))
        check("   the same candle offered again (a restart) is not late: it is taken now that cash is free",
              rec3["result"] == "PAPER SHORT", (rec3["result"], rec3.get("why")))
        rec4 = P.setup_decision("US", "HLT", dict(s, v4_signal_at=(sig + timedelta(minutes=30)).isoformat(),
                                                  bar_end="2026-11-18T14:40:00-05:00", details={"latest_bos": True}))
        check("   a newer signal is a new trigger (not a late entry)", not rec4["why"].startswith("late entry"),
              rec4.get("why"))

        # 3. margin-aware sizing
        acc = P.load_config()["accounts"]["US"]
        check("3. margin_x: US stocks 4x, options 1x", P.margin_x(acc, "US") == 4.0 and P.margin_x(acc, "USOPT") == 1.0
              and P.margin_x(acc, "US", "option") == 1.0)
        os.remove(P.V4_TRIGGERS)
        led = P.load_ledger(P.load_config())
        led["open"] = []
        P.book_of(led, "US")["cash"] = 1000.0
        P.save_json(P.LEDGER, led)
        P.fetch_price = lambda m, t: (300.0, datetime.now(timezone.utc))
        sz = dict(s, price=300.0, stop=301.0, target=297.0, bar_end=b1, v4_signal_at=(sig + timedelta(hours=2)).isoformat())
        rec5 = P.setup_decision("US", "XYZ", sz)
        check("   a $300 stock in the $1,000 account (25% cap, 4x) is not '0 units fit'",
              "0 units fit" not in (rec5.get("why") or "") and rec5["result"] == "PAPER SHORT",
              (rec5["result"], rec5.get("why")))
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("%d check(s) failed" % len(FAILS))
        sys.exit(1)
    print("all checks passed")
