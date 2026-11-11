#!/usr/bin/env python3
"""
coindcx_ticker.py - live crypto prices from CoinDCX USDT markets, written every second to
trader/live/crypto_ticks.json for the dashboard (prices changing every second) and paper.py (stops / targets on
the freshest price).

Public data only: one GET of CoinDCX's public ticker a second (every market in one answer). No API key, no
private endpoint, nothing that can place an order (coindcx.py refuses anything else before it is sent).

Watches: the crypto universe (trader/universe_crypto.txt, the dashboard's coin list) and every open CRYPTO paper
position. The list is re-read every 30 seconds; coins with no USDT market on CoinDCX are listed as "missing".

Service: deploy/trader-crypto-ticker.service.   By hand:  python coindcx_ticker.py
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import coindcx as C

LEDGER = os.path.join("trader", "paper", "ledger.json")
UNIVERSE = os.path.join("trader", "universe_crypto.txt")
DEFAULT_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT"]


def log(msg):
    print("%s %s" % (datetime.now(timezone.utc).strftime("%H:%M:%S"), msg), flush=True)


def wanted():
    coins = []
    try:
        with open(UNIVERSE, encoding="utf-8") as fh:
            coins = [ln.split("|")[0].strip().upper().replace("-USD", "") for ln in fh
                     if ln.strip() and not ln.lstrip().startswith("#")]
    except FileNotFoundError:
        pass
    try:
        with open(LEDGER, encoding="utf-8") as fh:
            led = json.load(fh)
        coins += [p.get("symbol", "").upper() for p in led.get("open") or [] if p.get("market") == "CRYPTO"]
    except (FileNotFoundError, ValueError):
        pass
    return list(dict.fromkeys(c for c in coins if c)) or list(DEFAULT_COINS)


def build(coins, rt):
    """(ticks, missing) for the file, from one current_prices() answer."""
    allp, t = rt
    ticks, missing = {}, []
    for s in coins:
        po = C.market_of(s, allp)
        d = allp.get(po[0]) if po else None
        px = C.last_price(d) if isinstance(d, dict) else None
        if not px:
            missing.append(s)
            continue
        m = po[1]
        tick = {"ltp": px / m, "t": t.timestamp(), "pair": po[0]}
        for src, dst in (("high", "high"), ("low", "low")):
            v = C._num(d.get(src))
            if v:
                tick[dst] = v / m
        try:
            tick["chg_pct"] = round(float(d.get("change_24_hour")), 3)
        except (TypeError, ValueError):
            pass
        ticks["CRYPTO:" + s] = tick
    return ticks, missing


def write(ticks, missing):
    doc = {"written": time.time(), "source": "coindcx usdt spot ticker (public)", "ticks": ticks, "missing": missing}
    os.makedirs(os.path.dirname(C.TICKS_FILE), exist_ok=True)
    tmp = C.TICKS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    os.replace(tmp, C.TICKS_FILE)


def run(every=1.0):
    coins, coins_at, fails = [], 0.0, 0
    while True:
        t0 = time.time()
        try:
            if t0 - coins_at > 30:
                coins, coins_at = wanted(), t0
            ticks, missing = build(coins, C.current_prices())
            write(ticks, missing)
            if fails:
                log("CoinDCX prices back (%d coins, %d missing)" % (len(ticks), len(missing)))
            fails = 0
        except Exception as e:
            fails += 1
            if fails in (1, 10) or fails % 60 == 0:
                log("CoinDCX prices failed (%d in a row): %s" % (fails, e))
        wait = every if not fails else min(60.0, 2.0 ** min(fails, 6))
        time.sleep(max(0.0, wait - (time.time() - t0)))


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)) if len(sys.argv) < 2 else sys.argv[1])
    log("coindcx ticker starting (public data only, no API key, no orders)")
    run()
