#!/usr/bin/env python3
"""research_fno_sv4.py: Scanner v4 trades priced as ATM options. Offline (made-up candles).

    python tests/test_fno_sv4.py
"""
import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research_fno_sv4 as R  # noqa: E402
import paper as P  # noqa: E402

FAILS = []
IST = timezone(timedelta(hours=5, minutes=30))


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def history(n=400, px=1000.0, start=datetime(2026, 10, 27, 4, 0, tzinfo=timezone.utc)):
    random.seed(7)
    rows, t = [], start
    for _ in range(n):
        c = px * (1 + random.gauss(0, 0.0015))
        rows.append((t, px, max(px, c) * 1.0005, min(px, c) * 0.9995, c, 1000))
        px, t = c, t + timedelta(minutes=5)
    return rows


if __name__ == "__main__":
    cfg = P.DEFAULT_CONFIG
    acc = cfg["accounts"]["INDIA"]
    rows = history()
    i = 380
    win = {"i": i, "exit_i": i + 12, "side": "long", "entry": 1000.0, "stop": 995.0, "exit": 1010.0}
    o = R.option_trade(win, rows, IST, cfg, acc)
    check("1. a +2R stock long bought as a call: profit, but under +2R (theta, spread, charges)",
          isinstance(o, dict) and 0 < o["r"] < o["stock_r"] and abs(o["stock_r"] - 2.0) < 1e-9, o)
    if isinstance(o, dict):
        check("   sizing inside the account: loss at the premium stop <= Rs 1,500, premium <= 40% of Rs 50,000",
              o["risk"] <= acc["max_loss_per_trade_fno"] + 1e-6
              and o["premium"] * o["lots"] * o["lot"] <= acc["capital"] * acc["max_position_pct_fno"] / 100 + 1e-6, o)
    loss = dict(win, exit=995.0)
    o2 = R.option_trade(loss, rows, IST, cfg, acc)
    check("2. stopped out: about -1R plus costs (a bit worse than -1R)", isinstance(o2, dict) and -1.35 < o2["r"] < -1.0, o2)
    short = dict(win, side="short", stop=1005.0, exit=990.0)
    o3 = R.option_trade(short, rows, IST, cfg, acc)
    check("3. a short setup buys the put and profits when the stock falls", isinstance(o3, dict) and o3["r"] > 0, o3)
    slow = dict(win, exit_i=i + 18, exit=1000.0)
    o4 = R.option_trade(slow, rows, IST, cfg, acc)
    check("4. flat stock after 90 min: the option loses (theta + costs)", isinstance(o4, dict) and o4["r"] < 0, o4)
    wide = dict(win, stop=950.0, exit=1100.0)
    check("5. a stop so wide that one lot risks more than Rs 1,500: not traded",
          R.option_trade(wide, rows, IST, cfg, acc) == "does not fit the account")
    check("6. expiry: last Tuesday of the month, rolled over inside 3 days",
          R.monthly_expiry(datetime(2026, 11, 10).date()).isoformat() == "2026-11-24"
          and R.monthly_expiry(datetime(2026, 11, 23).date()).isoformat() == "2026-12-29")
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
