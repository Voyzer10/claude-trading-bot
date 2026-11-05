#!/usr/bin/env python3
"""Stops and targets touched BETWEEN two runner checks (owner's report, 5 Nov 2026): the runner looks every ~5
minutes; if price touched the stop or target in between and came back, the trade must still exit, at that level.
Offline (prices and 1-minute candles are faked).

    python tests/test_intrabar_exits.py
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


def run(P, side, bars_fn, now_price, stop, target, seen_min_ago=5, entry_min_ago=20):
    """Open a CRYPTO paper position at 100, pretend it was last checked `seen_min_ago` minutes ago, then run one
    check with the given 1-minute candles (built relative to now) and live price. Returns (open pos or None, closed)."""
    cfg = P.load_config()
    led = P.load_ledger(cfg)
    led["open"], led["closed"] = [], []
    P.fetch_price = lambda m, t: (100.0, datetime.now(timezone.utc))
    args = type("A", (), {"symbol": "CRYPTO:TST", "stop": str(stop), "target": str(target), "qty": None,
                          "price": None, "note": "test", "force": True, "side": side})()
    P.cmd_buy(args, cfg, led)
    now = datetime.now(timezone.utc)
    pos = led["open"][0]
    pos["entry_time"] = (now - timedelta(minutes=entry_min_ago)).isoformat()
    if seen_min_ago is not None:
        pos["last_seen"] = (now - timedelta(minutes=seen_min_ago)).isoformat()
    P.fetch_minutes = lambda m, t: bars_fn(now)
    P.fetch_price = lambda m, t: (now_price, now)
    P.check_once(cfg, led)
    return (led["open"][0] if led["open"] else None), led["closed"]


def m(now, mins_ago, o, h, l, c):
    return (now - timedelta(minutes=mins_ago), o, h, l, c)


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        cfg = P.load_config()
        cfg["accounts"]["CRYPTO"]["fee_pct"] = 0.0
        P.save_json(P.CONFIG, cfg)

        pos, closed = run(P, "long", lambda n: [m(n, 4, 100, 100.2, 98.9, 99.5), m(n, 3, 99.5, 100.1, 99.4, 100.0)],
                          100.0, 99.0, 102.0)
        check("1. long: stop touched between checks, price back at 100 -> exit at the stop 99",
              pos is None and closed and closed[0]["exit"] == 99.0 and closed[0]["reason"] == "stop", closed)

        pos, closed = run(P, "long", lambda n: [m(n, 4, 100, 102.3, 99.9, 101.0), m(n, 2, 101, 101.0, 99.6, 99.7)],
                          99.6, 99.0, 102.0)
        check("2. long: target touched between checks, price fell back -> exit at the target 102",
              pos is None and closed and closed[0]["exit"] == 102.0 and closed[0]["reason"] == "target", closed)

        pos, closed = run(P, "long", lambda n: [m(n, 3, 100, 102.5, 98.5, 100.0)], 100.0, 99.0, 102.0)
        check("3. one candle touches both -> the stop (the worse case)",
              closed and closed[0]["reason"] == "stop" and closed[0]["exit"] == 99.0, closed)

        pos, closed = run(P, "long", lambda n: [m(n, 4, 100, 102.2, 99.8, 101.5), m(n, 2, 101.5, 101.5, 98.0, 98.2)],
                          98.2, 99.0, 102.0)
        check("4. target candle first, stop candle later -> the target (first touch wins)",
              closed and closed[0]["reason"] == "target", closed)

        pos, closed = run(P, "long", lambda n: [m(n, 3, 98.4, 98.8, 98.1, 98.6)], 98.6, 99.0, 102.0)
        check("5. a candle that opens below the stop (gap) -> filled at its open 98.4, not at the stop",
              closed and closed[0]["exit"] == 98.4 and "gapped" in closed[0]["reason"], closed)

        pos, closed = run(P, "long", lambda n: [m(n, 4, 100, 100.8, 99.3, 100.4)], 100.4, 99.0, 102.0)
        check("6. nothing touched -> still open, last check time moved on",
              pos is not None and not closed and pos["last_seen"] > (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), (pos, closed))

        pos, closed = run(P, "short", lambda n: [m(n, 4, 100, 101.2, 99.8, 100.5), m(n, 2, 100.5, 100.6, 99.9, 100.0)],
                          100.0, 101.0, 98.0)
        check("7. short: stop above touched between checks -> exit at 101",
              closed and closed[0]["exit"] == 101.0 and closed[0]["reason"] == "stop", closed)

        pos, closed = run(P, "long", lambda n: [m(n, 25, 100, 100.1, 97.0, 100.0), m(n, 3, 100, 100.5, 99.5, 100.2)],
                          100.2, 99.0, 102.0, seen_min_ago=None)
        check("8. a candle from before the entry does not stop it out", pos is not None and not closed, closed)

        pos, closed = run(P, "long", lambda n: [], 98.7, 99.0, 102.0)
        check("9. no 1-minute data (fallback): the live price past the stop still exits", closed and closed[0]["reason"] == "stop", closed)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
