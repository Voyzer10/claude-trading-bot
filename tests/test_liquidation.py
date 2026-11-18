#!/usr/bin/env python3
"""Margin trades end when their margin is used up (owner-approved, 18 Nov 2026). Offline.

  1. A 5x crypto long whose stop is wider than its margin (entry 100, stop 70): the margin is gone at 80 (100 - 100/5),
     so it closes at 80 ("liquidated"), not at 70.
  2. A 5x crypto long gapping past its stop and past 80 (open 75): crypto futures on isolated margin never lose more
     than the margin, so it fills at 80.
  3. A 4x US stock long gapping the same way (open 70, liquidation at 75): the broker squares it off, but the loss is
     the real one: it fills at the open, 70.
  4. A normal stop (entry 100, stop 99) is untouched: it fills at 99.

    python tests/test_liquidation.py
"""
import contextlib
import io
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


def trade(P, cfg, led, symbol, stop, target, candle):
    """Open a long at 100, then walk one 1-minute candle (o, h, l, c). Returns the closed record or None."""
    led["open"], led["closed"] = [], []
    P.fetch_price = lambda m, t: (100.0, datetime.now(timezone.utc))
    with contextlib.redirect_stdout(io.StringIO()):
        P.cmd_buy(type("A", (), {"symbol": symbol, "stop": str(stop), "target": str(target), "qty": None, "price": None,
                                 "note": "t", "force": True, "side": "long"})(), cfg, led)
    pos = led["open"][0]
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(minutes=2)
    pos["entry_time"] = (t0 - timedelta(minutes=1)).isoformat()
    with contextlib.redirect_stdout(io.StringIO()):
        P.step_bar(led, cfg, pos, P.acct_cfg(cfg, pos["market"]), (t0,) + candle, now, False)
    return (led["closed"] or [None])[0], pos


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        P.session = lambda m, utc: "open"
        P.past_flat_by = lambda m, acc, utc: False
        cfg = P.load_config()
        for a in cfg["accounts"].values():
            a["min_reward_risk"] = 0.0
        led = P.load_ledger(cfg)

        rec, pos = trade(P, cfg, led, "CRYPTO:TST", 70, 140, (100.0, 100.0, 79.0, 85.0))
        check("1. crypto 5x, stop 70 wider than the margin: liquidated at 80",
              rec and abs(rec["exit"] - 80.0) < 0.01 and rec["reason"].startswith("liquidated"), rec and (rec["exit"], rec["reason"]))
        check("   the loss is the margin (plus fees), never more", rec and abs(rec["pnl"] + pos["margin"]) < 1.0,
              rec and (rec["pnl"], pos["margin"]))
        rec, _ = trade(P, cfg, led, "CRYPTO:TS2", 99, 102, (75.0, 76.0, 74.0, 75.5))
        check("2. crypto 5x gapping past the stop and the margin: filled at 80 (isolated margin)",
              rec and abs(rec["exit"] - 80.0) < 0.01 and rec["reason"].startswith("liquidated"), rec and (rec["exit"], rec["reason"]))
        rec, _ = trade(P, cfg, led, "US:TST", 99, 102, (70.0, 71.0, 69.0, 70.5))
        check("3. US stock 4x gapping past the stop and the margin: filled at the open, 70 (the loss is real)",
              rec and rec["exit"] == 70.0, rec and (rec["exit"], rec["reason"]))
        rec, _ = trade(P, cfg, led, "CRYPTO:TS3", 99, 102, (100.0, 100.0, 98.8, 99.2))
        check("4. a normal stop inside the margin: filled at the stop, 99", rec and rec["exit"] == 99.0
              and rec["reason"] == "stop", rec and (rec["exit"], rec["reason"]))
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
