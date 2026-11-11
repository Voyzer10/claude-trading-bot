#!/usr/bin/env python3
"""Live crypto prices (coinbase.py, crypto_ticker.py): Coinbase public market data only, no API key, never an
order. Offline: REST answers come from a fake, WebSocket messages are fed to the ticker by hand.

    python tests/test_crypto_live.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


PRODUCTS = [{"id": "BTC-USD", "status": "online"}, {"id": "ETH-USD", "status": "online"},
            {"id": "PEPE-USD", "status": "online"}, {"id": "BTC-EUR", "status": "online"},
            {"id": "OLD-USD", "status": "delisted"}, {"id": "HALT-USD", "status": "online", "trading_disabled": True}]


class Fake:
    def __init__(self):
        self.sent = []

    def __call__(self, req, timeout=None):
        self.sent.append((req.get_method(), req.full_url, dict(req.header_items())))
        path = urllib.parse.urlsplit(req.full_url).path
        if path == "/products":
            body = PRODUCTS
        elif path == "/products/ETH-USD/ticker":
            body = {"price": "3900.5", "time": "2026-11-11T08:30:00.123Z"}
        else:
            raise AssertionError("unexpected request %s" % req.full_url)
        return io.BytesIO(json.dumps(body).encode())


def ticker_msg(pid, price, open24=None):
    d = {"type": "ticker", "product_id": pid, "price": str(price), "time": "2026-11-11T08:31:00.000Z",
         "high_24h": str(price * 1.02), "low_24h": str(price * 0.97)}
    if open24:
        d["open_24h"] = str(open24)
    return json.dumps(d)


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import coinbase as CB
        fake = Fake()
        CB.urllib.request.urlopen = fake

        # 1. only public market data
        bad = [("POST", "https://api.exchange.coinbase.com/orders"), ("GET", "https://api.exchange.coinbase.com/orders"),
               ("GET", "https://api.exchange.coinbase.com/accounts"), ("GET", "https://api.exchange.coinbase.com/fills"),
               ("GET", "http://api.exchange.coinbase.com/products"), ("POST", CB.REST + "/products"),
               ("GET", "https://evil.example/products")]
        refused = []
        for m, u in bad:
            try:
                CB._get(u, m)
            except CB.CoinbaseBlocked:
                refused.append(u)
        check("1. orders, accounts, fills, POSTs, plain http and other hosts are refused before sending",
              len(refused) == len(bad) and not fake.sent, (refused, fake.sent))
        src = open(os.path.join(ROOT, "coinbase.py"), encoding="utf-8").read() + \
            open(os.path.join(ROOT, "crypto_ticker.py"), encoding="utf-8").read()
        check("   no API key anywhere: no signature, no CB-ACCESS header, no key from the environment",
              "CB-ACCESS" not in src and "hmac" not in src and "environ" not in src and "base64" not in src)

        # 2. products, prices
        ids = CB.products()
        check("2. online USD products only (no EUR, delisted or disabled)", ids == {"BTC-USD", "ETH-USD", "PEPE-USD"}, ids)
        check("   coin -> product; a coin Coinbase does not list -> none",
              CB.product_of("btc") == "BTC-USD" and CB.product_of("HYPE") is None)
        q = CB.price("ETH")
        check("   REST price for one coin", q and q[0] == 3900.5 and q[1].year == 2026, q)
        check("   every request a plain GET with no credentials",
              all(m == "GET" and not any(k.lower().startswith(("cb-access", "authorization")) for k in h)
                  for m, _, h in fake.sent), fake.sent)

        # 3. the ticker: subscription, messages, file
        import crypto_ticker as T
        os.makedirs("trader/paper", exist_ok=True)
        with open("trader/universe_crypto.txt", "w") as fh:
            fh.write("# coins\nBTC\nETH\nPEPE\nHYPE\n")
        with open("trader/paper/ledger.json", "w") as fh:
            json.dump({"open": [{"market": "CRYPTO", "symbol": "SOL"}, {"market": "NSE", "symbol": "TCS"}]}, fh)
        coins = T.wanted()
        subs, missing = T.plan(coins, ids)
        check("3. watches the universe + open crypto positions; subscribes only to listed products",
              coins == ["BTC", "ETH", "PEPE", "HYPE", "SOL"] and subs == ["BTC-USD", "ETH-USD", "PEPE-USD"]
              and missing == ["HYPE", "SOL"], (coins, subs, missing))
        msg = json.loads(T.subscribe_msg(subs))
        check("   the only message sent is a public ticker subscription (no signature, no key)",
              msg == {"type": "subscribe", "product_ids": subs, "channels": ["ticker"]}, msg)
        tk = T.Ticker()
        tk.subs, tk.missing, tk.ws = subs, missing, object()
        tk.on_message(None, json.dumps({"type": "subscriptions", "channels": []}))
        tk.on_message(None, ticker_msg("BTC-USD", 104250.5, open24=103000))
        tk.on_message(None, ticker_msg("PEPE-USD", 0.0000123))
        tk.on_message(None, json.dumps({"type": "ticker", "product_id": "BTC-EUR", "price": "90000"}))
        tk.on_message(None, json.dumps({"type": "ticker", "product_id": "ETH-USD", "price": "0"}))
        tk.on_message(None, "not json")
        check("   ticker messages -> ticks keyed like paper positions; bad, zero and non-USD prices ignored",
              set(tk.ticks) == {"CRYPTO:BTC", "CRYPTO:PEPE"} and tk.ticks["CRYPTO:BTC"]["ltp"] == 104250.5
              and tk.ticks["CRYPTO:BTC"]["chg_pct"] == round((104250.5 - 103000) / 103000 * 100, 3), tk.ticks)
        check("   the stream is alive after a message", tk.alive())
        tk.write()
        check("   tick_price reads the fresh file", CB.tick_price("BTC")[0] == 104250.5)
        tk.last_msg = time.time() - T.QUIET_S - 1
        check("   a stream silent for a minute counts as dead (the writer stops, paper.py falls back)", not tk.alive())
        doc = json.load(open(CB.TICKS_FILE))
        doc["written"] = time.time() - 30
        json.dump(doc, open(CB.TICKS_FILE, "w"))
        check("   a 30-second-old file is ignored", CB.tick_price("BTC") is None)

        # 4. paper.py
        import paper as P
        tk.last_msg = time.time()
        tk.write()
        p, _ = P.fetch_price("CRYPTO", "BTC")
        check("4. paper.py: the crypto price comes from the live Coinbase file", p == 104250.5, p)
        p2, _ = P.fetch_price("CRYPTO", "ETH")
        check("   a coin not in the file: one Coinbase REST request", p2 == 3900.5, p2)

        # 5. the dashboard endpoint
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        here = os.path.join(tmp, "trader", "live", "crypto_ticks.json")
        import api._kite as AK
        AK.CX.TICKS_FILE = here
        AK.K.TICKS_FILE = os.path.join(tmp, "trader", "live", "ticks.json")
        app = FastAPI()
        app.include_router(AK.router)
        c = TestClient(app)
        r = c.get("/api/py/live/ticks").json()
        check("5. /api/py/live/ticks serves the crypto ticks while the feed is live",
              r["crypto_live"] and r["ticks"]["CRYPTO:BTC"]["ltp"] == 104250.5 and r["crypto_missing"] == ["HYPE", "SOL"]
              and "Coinbase" in r["crypto_source"], r)
        doc = json.load(open(here))
        doc["written"] = time.time() - 30
        json.dump(doc, open(here, "w"))
        r2 = c.get("/api/py/live/ticks").json()
        check("   and not when it stopped", not r2["crypto_live"] and "CRYPTO:BTC" not in r2["ticks"], r2)
        hosts = {urllib.parse.urlsplit(u).hostname for _, u, _ in fake.sent}
        check("   every REST request in this test went to Coinbase's public API", hosts == {"api.exchange.coinbase.com"}, hosts)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)
