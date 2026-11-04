#!/usr/bin/env python3
"""US long path: the live price must still be above the opening-range high before the paper buy (offline).
Replays the 3 Nov AAPL case (fill 331.96 under the 332.67 high) and the MAR case (418.90 over 418.27).

    python tests/test_us_long_entry.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAILS = []


def run(tk, hit, plan, live):
    import auto_us as U
    import paper as P
    calls = []
    files = {"entry.json": {"symbol": tk, "status": "triggered", "date": "2026-11-03", "level": hit["or_high"]},
             "plan.json": dict(plan, symbol=tk, date="2026-11-03")}
    U.sh = lambda args, **k: (calls.append(os.path.basename(args[0])) or 0, "")
    U.us_json = lambda path: files.get(os.path.basename(path))
    U.record = lambda rec: None
    P.fetch_price = lambda m, t: (live, None)
    rec = U.run_one(tk, hit, dict(U.DEFAULTS), lambda *_: None, auto=False)
    return rec, calls


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


if __name__ == "__main__":
    os.chdir(tempfile.mkdtemp())
    aapl, calls = run("AAPL", {"or_high": 332.67, "or_low": 325.33, "side": "long"},
                      {"entry": 333.82, "stop": 329.0, "target": 343.46}, live=331.959)
    check("AAPL 3 Nov: fill back inside the range -> skipped as reversed",
          aapl["result"] == "skipped" and "reversed" in aapl["why"], aapl.get("why"))
    check("   time machine not even run", "timemachine.py" not in calls, calls)
    mar, calls = run("MAR", {"or_high": 418.27, "or_low": 414.06, "side": "long"},
                     {"entry": 418.44, "stop": 416.16, "target": 423.0}, live=418.90)
    check("MAR 3 Nov: still above the high, 0.23R past it -> goes on to the time machine",
          "timemachine.py" in calls, (mar.get("result"), mar.get("why")))
    far, _ = run("XYZ", {"or_high": 100.0, "or_low": 98.0, "side": "long"},
                 {"entry": 100.2, "stop": 99.0, "target": 102.6}, live=101.5)
    check("1.5R past the high -> skipped as chasing", far["result"] == "skipped" and "chasing" in far["why"], far.get("why"))
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED" % len(FAILS)))
    sys.exit(1 if FAILS else 0)
