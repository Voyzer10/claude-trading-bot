#!/usr/bin/env python3
"""Can this machine get market data? Yahoo blocks some datacenter IPs; run this first on a new VPS.
    python deploy/check_data.py          (exit code 1 if any source failed)
The dashboard's Operations > "Check market data" runs the same probes (api/_ops.py)."""
import json
import sys
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
Y = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=15m&range=1d"
PROBES = [("Yahoo crypto (BTC-USD)", Y % "BTC-USD", "yahoo"),
          ("Yahoo NSE (RELIANCE.NS)", Y % "RELIANCE.NS", "yahoo"),
          ("Yahoo US (AAPL)", Y % "AAPL", "yahoo"),
          ("Yahoo index (^NSEI)", Y % "%5ENSEI", "yahoo"),
          ("Coinbase crypto fallback (BTC-USD)",
           "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=900", "coinbase")]


def probe(name, url, kind):
    """One source: {"name", "ok", "ms", "detail"}."""
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
        ms = int((time.time() - t0) * 1000)
        doc = json.loads(raw)
        if kind == "yahoo":
            res = (doc.get("chart") or {}).get("result") or []
            ts = (res[0].get("timestamp") or []) if res else []
            if not ts:
                return {"name": name, "ok": False, "ms": ms, "detail": "answered but no candles"}
            age = int(time.time() - ts[-1])
            return {"name": name, "ok": True, "ms": ms, "detail": "%d candles, last %d min ago" % (len(ts), age // 60)}
        rows = doc if isinstance(doc, list) else []
        if not rows:
            return {"name": name, "ok": False, "ms": ms, "detail": "answered but no candles"}
        return {"name": name, "ok": True, "ms": ms,
                "detail": "%d candles, last %d min ago" % (len(rows), int(time.time() - rows[0][0]) // 60)}
    except urllib.error.HTTPError as e:
        return {"name": name, "ok": False, "ms": int((time.time() - t0) * 1000),
                "detail": "HTTP %s %s (blocked or rate-limited?)" % (e.code, e.reason)}
    except Exception as e:
        return {"name": name, "ok": False, "ms": int((time.time() - t0) * 1000), "detail": str(e)[:200]}


def main():
    bad = 0
    for p in PROBES:
        r = probe(*p)
        bad += not r["ok"]
        print("  %-4s %-36s %5d ms  %s" % ("OK" if r["ok"] else "FAIL", r["name"], r["ms"], r["detail"]))
    if bad:
        print("\n  %d source(s) failed. If Yahoo fails here but works on your PC, this VPS's IP is blocked by Yahoo:"
              "\n  crypto still works through Coinbase; NSE/US scans will not. Try another region/provider." % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
