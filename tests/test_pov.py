#!/usr/bin/env python3
"""The bigger picture (pov.py): 1h -> 4h, daily -> weekly / monthly candles, the POV = the direction of the last
complete Scanner v4 setup, the file and the dashboard endpoint. Offline: no request leaves the machine.

    python tests/test_pov.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def mirror(rows):
    return [(t, 200 - o, 200 - l, 200 - h, 200 - c, v) for t, o, h, l, c, v in rows]


if __name__ == "__main__":
    import pov as PV
    import test_scanner_v4 as TV

    # 1. bigger candles
    t0 = datetime(2026, 11, 2, 3, 45, tzinfo=timezone.utc)
    hourly = [(t0 + timedelta(hours=k), 10 + k, 11 + k, 9 + k, 10.5 + k, 100) for k in range(7)]
    hourly += [(t0 + timedelta(days=1, hours=k), 20 + k, 21 + k, 19 + k, 20.5 + k, 10) for k in range(7)]
    h4 = PV.group(hourly, lambda r, n: (r[0].date(), n // 4))
    check("1. 4h from 1h: four per block, a new day starts a new block (7 hours -> 4 + 3)", len(h4) == 4, len(h4))
    check("   open of the first, high max, low min, close of the last, volume summed",
          h4[0][1:] == (10, 14, 9, 13.5, 400) and h4[1][1:] == (14, 17, 13, 16.5, 300), h4[:2])
    d0 = datetime(2026, 9, 28, tzinfo=timezone.utc)   # a Monday
    daily = [(d0 + timedelta(days=k), 1, 2 + k, 0.5, 1.5, 1) for k in range(40) if (d0 + timedelta(days=k)).weekday() < 5]
    fr = PV.frames(hourly, daily)
    check("   weeks by ISO week, months by calendar month",
          len(fr["1W"]) == 6 and len(fr["1M"]) == 3 and fr["1W"][0][2] == 6 and set(fr) == set(PV.TFS),
          (len(fr["1W"]), len(fr["1M"])))

    # 2. the POV
    buy = TV.build([TV.SWEEP, TV.INV, TV.TRIG, TV.UP1, TV.TP])
    p = PV.pov_of(buy)
    check("2. a complete BUY setup -> bullish, with when and which setup", p["pov"] == "bullish" and p.get("at")
          and p.get("setup") == "primary", p)
    q = PV.pov_of(mirror(buy))
    check("   the mirrored SELL setup -> bearish", q["pov"] == "bearish", q)
    n = PV.pov_of(TV.build([TV.SWEEP, TV.HAMMER, TV.TRIG]))
    check("   no complete setup -> no POV, with the reason", n["pov"] is None and n.get("why"), n)
    check("   too little history -> no POV", PV.pov_of(buy[:10])["pov"] is None)
    both = buy + [(r[0] + timedelta(days=1), *r[1:]) for r in mirror(buy)]
    check("   the LAST complete setup decides (a BUY then a SELL -> bearish)", PV.pov_of(both)["pov"] == "bearish",
          PV.pov_of(both))

    # 3. the file and the endpoint, nothing fetched
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        PV.charts = lambda: [("US:AAPL", "US", "AAPL"), ("NSE:BANKNIFTY", "INDEX", "BANKNIFTY")]
        PV.fetch = lambda market, sym, rng, interval: buy if market == "US" else []
        n_ok, failed = PV.run_once({}, True, workers=1)
        doc = json.load(open(PV.POV_FILE))
        check("3. run_once writes every chart and timeframe", n_ok == 2 and not failed
              and doc["charts"]["US:AAPL"]["1h"]["pov"] == "bullish" and doc["charts"]["NSE:BANKNIFTY"]["1D"]["pov"] is None
              and doc["tfs"] == list(PV.TFS), doc)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import api._kite as AK
        AK.K.LIVE_DIR = os.path.join(tmp, "trader", "live")
        app = FastAPI()
        app.include_router(AK.router)
        r = TestClient(app).get("/api/py/pov").json()
        check("   /api/py/pov serves it with its age", r["charts"]["US:AAPL"]["1h"]["pov"] == "bullish"
              and r["age_s"] is not None, r)
        src = open(os.path.join(ROOT, "pov.py"), encoding="utf-8").read()
        check("   display only: pov.py never touches the paper engine", "import paper" not in src and "open_position" not in src)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)
