#!/usr/bin/env python3
"""The "rules" path's US scan (whole universe, 4-15 minutes) runs in the background, so the runner keeps checking
stops meanwhile; its watchlist is used only if it is from today (offline).

    python tests/test_us_background_scan.py
"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


if __name__ == "__main__":
    os.chdir(tempfile.mkdtemp())
    import auto_us as U
    logs = []
    U._scan.update({"proc": subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"]), "kind": "orb",
                    "started": datetime.now(timezone.utc)})
    check("a scan still running: not done, the runner moves on", U.finished_scan(logs.append) is None)
    U._scan["proc"].kill()
    U._scan.clear()
    U._scan.update({"proc": subprocess.Popen([sys.executable, "-c", "pass"]), "kind": "orb",
                    "started": datetime.now(timezone.utc)})
    U._scan["proc"].wait()
    check("a finished scan is picked up once", U.finished_scan(logs.append) == "orb" and U._scan == {})

    et = datetime(2026, 11, 26, 10, 30)      # Thanksgiving: the scanner refuses and writes nothing new
    ran = []
    U.us_json = lambda path: {"as_of": "2026-11-25 10:25 ET", "hits": [{"symbol": "AAPL", "at": "10:20 AM"}]}
    U.run_one = lambda *a, **k: ran.append(a[0]) or {"time": "", "symbol": a[0], "result": "", "why": ""}
    ms = {}
    U.take_hits({}, ms, dict(U.DEFAULTS), logs.append, False, et)
    check("yesterday's watchlist is not replayed as today's hits", not ran and "no result for today" in ms["status"],
          (ran, ms))
    U.us_json = lambda path: {"as_of": "2026-11-26 10:25 ET", "hits": [{"symbol": "AAPL", "at": "10:20 AM"}]}
    U.take_hits({}, ms, dict(U.DEFAULTS), logs.append, False, et)
    check("today's fresh hit goes to the agents", ran == ["AAPL"], ran)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
