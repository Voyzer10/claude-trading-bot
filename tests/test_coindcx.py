#!/usr/bin/env python3
"""CoinDCX (coindcx.py, coindcx_ticker.py): public market data only, no API key, never an order.
Offline: every request is answered by a fake; nothing leaves the machine.

    python tests/test_coindcx.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


PAIRS = ["B-BTC_USDT", "B-ETH_USDT", "B-1000PEPE_USDT", "B-SOL_USDT"]
# the public spot ticker (api.coindcx.com/exchange/ticker), as the VPS got it on 11 Nov 2026
TICKER = [
    {"market": "BTCUSDT", "change_24_hour": "1.250", "high": "105000", "low": "103000", "last_price": "104250.5",
     "timestamp": 1794380421},
    {"market": "ETHUSDT", "change_24_hour": "-0.500", "high": "4000", "low": "3800", "last_price": "3900.0",
     "timestamp": 1794380420},
    {"market": "1000PEPEUSDT", "change_24_hour": "2.000", "high": "0.013", "low": "0.012", "last_price": "0.0123",
     "timestamp": 1794380419},                                                # only the 1000x market exists
    {"market": "SOLUSDT", "last_price": "0", "timestamp": 1794380418},        # no usable price
    {"market": "BTCINR", "last_price": "9100000", "timestamp": 1794380418}]   # INR market: never used


def candles_doc(start, n, step_min=5):
    t0 = int(start.timestamp())
    return {"s": "ok", "data": [{"time": (t0 + k * step_min * 60) * 1000, "open": 100 + k, "high": 101 + k,
                                 "low": 99 + k, "close": 100.5 + k, "volume": 10} for k in range(n)]}


class Fake:
    def __init__(self):
        self.sent = []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        self.sent.append((req.get_method(), url, dict(req.header_items())))
        u = urllib.parse.urlsplit(url)
        if u.path.endswith("/active_instruments"):
            body = PAIRS
        elif u.path == "/exchange/ticker":
            body = TICKER
        elif u.path == "/market_data/candlesticks":
            q = urllib.parse.parse_qs(u.query)
            body = candles_doc(datetime.fromtimestamp(int(q["from"][0]), timezone.utc), 6)
        else:
            raise AssertionError("unexpected request %s" % url)
        return io.BytesIO(json.dumps(body).encode())


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import coindcx as C
        fake = Fake()
        C.urllib.request.urlopen = fake

        # 1. only public GET market data can be sent
        ok_urls = [C.TICKER_URL, C.RT_URL, C.INSTR_URL, C.CANDLES_URL + "?pair=B-BTC_USDT&resolution=5&pcode=f"]
        bad = [("POST", "https://api.coindcx.com/exchange/v1/orders/create"),
               ("POST", "https://api.coindcx.com/exchange/v1/derivatives/futures/orders/create"),
               ("GET", "https://api.coindcx.com/exchange/v1/users/balances"),
               ("GET", "http://public.coindcx.com/market_data/v3/current_prices/futures/rt"),
               ("GET", "https://evil.example/market_data/candlesticks"),
               ("POST", C.TICKER_URL)]
        check("1. the public market-data URLs are allowed", all(C.allowed(u) for u in ok_urls))
        refused = []
        for m, u in bad:
            try:
                C._get(u, m)
            except C.CoinDCXBlocked:
                refused.append(u)
        check("   orders, balances, plain http, other hosts and POSTs are refused before sending",
              len(refused) == len(bad) and not fake.sent, (refused, fake.sent))
        src = open(os.path.join(ROOT, "coindcx.py"), encoding="utf-8").read() + \
            open(os.path.join(ROOT, "coindcx_ticker.py"), encoding="utf-8").read()
        check("   no API key anywhere: no auth header, no signature, no key from the environment",
              "X-AUTH" not in src and "hmac" not in src and "environ" not in src)

        # 2. pairs, prices
        check("2. coin -> futures pair: BTC -> B-BTC_USDT, PEPE -> B-1000PEPE_USDT (x1000), MKR -> none",
              C.pair_of("BTC") == ("B-BTC_USDT", 1) and C.pair_of("pepe") == ("B-1000PEPE_USDT", 1000)
              and C.pair_of("MKR") is None)
        px = C.prices(["BTC", "ETH", "PEPE", "SOL", "MKR"])
        check("   prices from the USDT spot ticker; PEPE from 1000PEPEUSDT in its own units; no price -> left out",
              px["BTC"][0] == 104250.5 and px["ETH"][0] == 3900.0 and abs(px["PEPE"][0] - 0.0000123) < 1e-12
              and "SOL" not in px and "MKR" not in px, px)
        allp, _ = C.current_prices()
        check("   coin -> USDT market (never the INR one); 1000x market only when the plain one is missing",
              C.market_of("BTC", allp) == ("BTCUSDT", 1) and C.market_of("PEPE", allp) == ("1000PEPEUSDT", 1000)
              and C.market_of("MKR", allp) is None)
        check("   every request was a plain GET with no credentials",
              all(m == "GET" and not any(k.lower().startswith(("x-auth", "authorization")) for k in h)
                  for m, _, h in fake.sent), fake.sent)
        check("   the instrument list is cached (one request for many lookups)",
              sum(1 for _, u, _ in fake.sent if "active_instruments" in u) == 1)

        # 3. candles: 15 minutes built from 5; ms timestamps
        start = datetime(2026, 11, 11, 6, 0, tzinfo=timezone.utc)
        c15 = C.candles("BTC", 15, start, start + timedelta(minutes=30))
        check("3. 15-minute candles from 5-minute ones, on the clock grid, OHLCV combined",
              len(c15) == 2 and c15[0][0] == start and c15[0][1:] == (100, 103, 99, 102.5, 30)
              and c15[1][0] == start + timedelta(minutes=15), c15)
        c1 = C.candles("PEPE", 1, start, start + timedelta(minutes=6))
        check("   1000PEPE candles are divided back to PEPE prices", c1 and abs(c1[0][1] - 0.1) < 1e-12, c1[:1])

        # 4. the ticker's file
        import coindcx_ticker as T
        os.makedirs("trader/paper", exist_ok=True)
        with open("trader/universe_crypto.txt", "w") as fh:
            fh.write("# coins\nBTC\nETH\nPEPE\nMKR\n")
        with open("trader/paper/ledger.json", "w") as fh:
            json.dump({"open": [{"market": "CRYPTO", "symbol": "SOL"}, {"market": "NSE", "symbol": "TCS"}]}, fh)
        coins = T.wanted()
        check("4. the ticker watches the universe plus open crypto positions", coins == ["BTC", "ETH", "PEPE", "MKR", "SOL"], coins)
        ticks, missing = T.build(coins, C.current_prices())
        T.write(ticks, missing)
        check("   ticks keyed like paper positions, with high / low / change; missing coins listed",
              set(ticks) == {"CRYPTO:BTC", "CRYPTO:ETH", "CRYPTO:PEPE"} and ticks["CRYPTO:BTC"]["chg_pct"] == 1.25
              and abs(ticks["CRYPTO:PEPE"]["high"] - 0.000013) < 1e-12 and missing == ["MKR", "SOL"], (ticks, missing))
        check("   tick_price reads a fresh file", C.tick_price("BTC")[0] == 104250.5)
        doc = json.load(open(C.TICKS_FILE))
        doc["written"] = time.time() - 30
        json.dump(doc, open(C.TICKS_FILE, "w"))
        check("   and ignores a stale one (30 s old)", C.tick_price("BTC") is None)

        # 5. paper.py prices crypto from CoinDCX
        import paper as P
        T.write(ticks, missing)
        p, _ = P.fetch_price("CRYPTO", "BTC")
        check("5. paper.py: a crypto price comes from the live CoinDCX file", p == 104250.5, p)
        doc = json.load(open(C.TICKS_FILE))
        doc["written"] = time.time() - 30
        json.dump(doc, open(C.TICKS_FILE, "w"))
        p2, _ = P.fetch_price("CRYPTO", "ETH")
        check("   with the file stale, one CoinDCX REST call", p2 == 3900.0, p2)
        before = len(fake.sent)
        P.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
        P.fetch_minutes("CRYPTO", "BTC")
        check("   1-minute candles do not go to public.coindcx.com (403 from the VPS)", len(fake.sent) == before)

        # 6. the dashboard endpoint
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import api._kite as AK
        AK.CX.TICKS_FILE = os.path.join(tmp, C.TICKS_FILE)
        AK.K.TICKS_FILE = os.path.join(tmp, "trader", "live", "ticks.json")
        app = FastAPI()
        app.include_router(AK.router)
        c = TestClient(app)
        T.write(ticks, missing)
        r = c.get("/api/py/live/ticks").json()
        check("6. /api/py/live/ticks serves the crypto ticks when the feed is live",
              r["crypto_live"] and r["ticks"]["CRYPTO:BTC"]["ltp"] == 104250.5 and r["crypto_missing"] == ["MKR", "SOL"], r)
        doc = json.load(open(C.TICKS_FILE))
        doc["written"] = time.time() - 30
        json.dump(doc, open(C.TICKS_FILE, "w"))
        r2 = c.get("/api/py/live/ticks").json()
        check("   and not when it stopped", not r2["crypto_live"] and "CRYPTO:BTC" not in r2["ticks"], r2)
        hosts = {urllib.parse.urlsplit(u).hostname for _, u, _ in fake.sent}
        check("   every request in this test went to CoinDCX's public hosts", hosts <= {"public.coindcx.com", "api.coindcx.com"}, hosts)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)
