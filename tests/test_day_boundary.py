#!/usr/bin/env python3
"""The dashboard's "today" is India's day for every market (offline).

exit_date is the market's own date: New York for US, UTC for crypto. A US trade that closed at 01:10 IST on 19 Nov
has exit_date 18 Nov; on 19 Nov (IST) the Performance card's "Today" must still count it.

    python tests/test_day_boundary.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAILS = []
IST = timezone(timedelta(hours=5, minutes=30))


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        late_us = {"market": "US", "exit_time": "2026-11-18T19:40:00+00:00", "exit_date": "2026-11-18", "pnl": 12.0,
                   "r": 1.0}
        check("ist_day: a US close at 01:10 IST on 19 Nov is 19 Nov", P.ist_day(late_us) == "2026-11-19", P.ist_day(late_us))
        check("ist_day: an old record without exit_time keeps its exit_date",
              P.ist_day({"exit_date": "2026-11-18"}) == "2026-11-18")

        sys.path.insert(0, os.path.join(ROOT, "api"))
        import api._ops as O
        O.LEDGER = os.path.join(tmp, "ledger.json")   # api/_ops.py's paths start at the repo: keep the test out of it
        O.PREFS = os.path.join(tmp, "prefs.json")
        with open(O.LEDGER, "w", encoding="utf-8") as fh:
            json.dump({"accounts": {"US": {"cash": 1012.0, "start_capital": 1000.0}}, "open": [], "closed": [late_us]}, fh)
        O._now = lambda: datetime(2026, 11, 19, 9, 0, tzinfo=IST)
        perf = O.performance()
        check("Performance 'Today' on 19 Nov (IST) counts that US trade",
              perf["accounts"]["US"]["today"] == 12.0, perf["accounts"].get("US"))
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
