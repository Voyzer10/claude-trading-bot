#!/usr/bin/env python3
"""Dashboard watch lists for NSE / US / F&O (10 Nov 2026). Offline.

    python tests/test_watchlists.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


if __name__ == "__main__":
    import scan_nse as S
    q = S.watch_quote({"t": [1, 2, 3], "c": [100.0, None, 102.0], "meta": {"chartPreviousClose": 100.0}})
    check("1. a quote from a 5-minute chart: last close, previous close, % change",
          q == {"price": 102.0, "prev_close": 100.0, "t": 3, "chg_pct": 2.0}, q)
    check("   an empty chart is no quote", S.watch_quote({"t": []}) is None and S.watch_quote(None) is None)
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import dashboard_push as D
        nse = {"orb": {"as_of": "2026-11-10T04:15:00+00:00", "quotes": {"RELIANCE": {"price": 1400}},
                       "hits": [{"symbol": "SUZLON", "side": "short", "price": 58.2, "time": "10:05", "holding": False,
                                 "extra_field": "dropped"}]}}
        w = D._nse_watch(nse)
        check("2. NSE watch: the Nifty 50, their quotes, today's breaks (only the fields the dashboard needs)",
              len(w["symbols"]) == len(S.NIFTY50) and w["quotes"]["RELIANCE"]["price"] == 1400
              and w["hits"] == [{"symbol": "SUZLON", "side": "short", "price": 58.2, "time": "10:05", "holding": False}], w)
        os.makedirs(os.path.join("trader", "live"))
        with open(os.path.join("trader", "live", "us_watch.json"), "w") as fh:
            json.dump({"as_of": "x", "symbols": ["AAPL", "MSFT"], "quotes": {"AAPL": {"price": 230.1, "chg_pct": 1.2}}}, fh)
        u = D._us_watch()
        check("3. US watch: the scanner's list and its last 5-minute quotes", u["symbols"] == ["AAPL", "MSFT"]
              and u["quotes"]["AAPL"]["chg_pct"] == 1.2, u)
        check("   no file yet: empty, not an error", D._nse_watch({})["hits"] == [] and isinstance(D._us_watch()["hits"], list))
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
