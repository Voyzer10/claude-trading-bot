#!/usr/bin/env python3
"""Can this machine get market data? Yahoo blocks some datacenter IPs; run this first on a new VPS.
    python deploy/check_data.py          (exit code 1 if any source failed)"""
import json
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
Y = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=15m&range=1d"
PROBES = [("Yahoo crypto  BTC-USD", Y % "BTC-USD", "y"), ("Yahoo NSE     RELIANCE.NS", Y % "RELIANCE.NS", "y"),
          ("Yahoo US      AAPL", Y % "AAPL", "y"), ("Yahoo index   ^NSEI", Y % "%5ENSEI", "y"),
          ("Coinbase      BTC-USD", "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=900", "c")]
bad = 0
for name, url, kind in PROBES:
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=12) as r:
            doc = json.loads(r.read())
        n = len(((doc.get("chart") or {}).get("result") or [{}])[0].get("timestamp") or []) if kind == "y" else len(doc)
        ok = n > 0
        detail = "%d candles" % n
    except Exception as e:
        ok, detail = False, str(e)[:120]
    bad += not ok
    print("  %-4s %-28s %5d ms  %s" % ("OK" if ok else "FAIL", name, (time.time() - t0) * 1000, detail))
if bad:
    print("\n  %d source(s) failed. If Yahoo fails here but works on your PC, this VPS's IP is blocked by Yahoo:"
          "\n  crypto still works through Coinbase; NSE/US scans will not. Try another region/provider." % bad)
sys.exit(1 if bad else 0)
