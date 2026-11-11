#!/usr/bin/env python3
"""
us_ticker.py - live US stock prices from Alpaca Market Data (IEX, free plan), written to trader/live/us_ticks.json
every 2 seconds for the dashboard and paper.py (stops / targets on the freshest price).

One request for every watched symbol's snapshot each time (30 requests a minute; the free plan allows 200). Data
only: alpaca.py refuses the trading API and any key that is not a paper key.

Watches: the US watch list (auto_us.US_WATCH, the dashboard's US list) and every open US paper position. Outside
the US session the request is made every 30 seconds (prices do not move; the file stays fresh).
Needs ALPACA_KEY_ID / ALPACA_SECRET_KEY in /etc/trader/trader.env; without them it waits and checks again.

Service: deploy/trader-us-ticker.service.   By hand:  python us_ticker.py
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import alpaca as A

LEDGER = os.path.join("trader", "paper", "ledger.json")
EVERY_OPEN, EVERY_CLOSED = 2.0, 30.0


def log(msg):
    print("%s %s" % (datetime.now(timezone.utc).strftime("%H:%M:%S"), msg), flush=True)


def watch_list():
    try:
        import auto_us
        syms = list(auto_us.US_WATCH)
    except Exception:
        syms = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "SPY", "QQQ"]
    try:
        with open(LEDGER, encoding="utf-8") as fh:
            led = json.load(fh)
        syms = [p.get("symbol", "").upper() for p in led.get("open") or [] if p.get("market") == "US"] + syms
    except (FileNotFoundError, ValueError):
        pass
    return list(dict.fromkeys(s for s in syms if s))


def session_open(now=None):
    try:
        import paper as P
        return P.session("US", now or datetime.now(timezone.utc)) == "open"
    except Exception:
        return True


def build(syms, snaps):
    ticks, missing = {}, []
    for s in syms:
        d = snaps.get(s)
        if not d:
            missing.append(s)
            continue
        t = {"ltp": d["price"], "t": d["t"]}
        for f in ("prev_close", "chg_pct", "high", "low"):
            if d.get(f) is not None:
                t["close" if f == "prev_close" else f] = d[f]
        ticks["US:" + s] = t
    return ticks, missing


def write(ticks, missing):
    doc = {"written": time.time(), "source": "alpaca iex", "ticks": ticks, "missing": missing}
    os.makedirs(os.path.dirname(A.TICKS_FILE), exist_ok=True)
    tmp = A.TICKS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    os.replace(tmp, A.TICKS_FILE)


def run():
    fails, warned = 0, False
    syms, syms_at = [], 0.0
    while True:
        t0 = time.time()
        if not A.configured():
            if not warned:
                k, _ = A.keys()
                log("no Alpaca paper key (%s): waiting" % ("missing" if not k else "the key id does not start with PK: refused"))
                warned = True
            time.sleep(60)
            continue
        warned = False
        try:
            if t0 - syms_at > 30:
                syms, syms_at = watch_list(), t0
            ticks, missing = build(syms, A.snapshots(syms))
            write(ticks, missing)
            if fails:
                log("Alpaca prices back (%d symbols, %d without an IEX price)" % (len(ticks), len(missing)))
            fails = 0
        except Exception as e:
            fails += 1
            if fails in (1, 10) or fails % 60 == 0:
                log("Alpaca prices failed (%d in a row): %s" % (fails, e))
        every = EVERY_OPEN if session_open() else EVERY_CLOSED
        wait = every if not fails else min(120.0, every * 2 ** min(fails, 5))
        time.sleep(max(0.0, wait - (time.time() - t0)))


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)) if len(sys.argv) < 2 else sys.argv[1])
    log("us ticker starting (Alpaca market data, paper key only, no orders)")
    run()
