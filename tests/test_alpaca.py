#!/usr/bin/env python3
"""US live prices (alpaca.py, us_ticker.py): Alpaca market data only, a paper key only, never an order.
Offline: every request is answered by a fake; nothing leaves the machine.

    python tests/test_alpaca.py
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


SNAPS = {"AAPL": {"latestTrade": {"t": "2026-11-11T15:30:01.123456789Z", "p": 228.45},
                  "prevDailyBar": {"c": 225.0}, "dailyBar": {"h": 229.1, "l": 226.0}},
         "MSFT": {"latestTrade": {"t": "2026-11-11T15:30:00Z", "p": 410.1}, "prevDailyBar": {"c": 412.0}},
         "ZZZZ": {"latestTrade": {"p": 0}}}


class Fake:
    def __init__(self):
        self.sent = []

    def __call__(self, req, timeout=None):
        self.sent.append((req.get_method(), req.full_url, dict(req.header_items())))
        u = urllib.parse.urlsplit(req.full_url)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/v2/stocks/snapshots":
            body = {s: SNAPS[s] for s in q["symbols"][0].split(",") if s in SNAPS}
        elif u.path == "/v2/stocks/trades/latest":
            s = q["symbols"][0]
            body = {"trades": {s: SNAPS[s]["latestTrade"]}} if s in SNAPS else {"trades": {}}
        elif u.path == "/v2/stocks/bars":
            body = {"bars": {q["symbols"][0]: [{"t": "2026-11-11T15:29:00Z", "o": 228, "h": 228.6, "l": 227.9, "c": 228.4,
                                                "v": 100}]}, "next_page_token": None}
        else:
            raise AssertionError("unexpected request %s" % req.full_url)
        return io.BytesIO(json.dumps(body).encode())


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import alpaca as A
        fake = Fake()
        A.urllib.request.urlopen = fake

        # 1. no trading API, no live key
        for u in ("https://paper-api.alpaca.markets/v2/orders", "https://api.alpaca.markets/v2/orders",
                  "https://data.alpaca.markets/v2/account", "http://data.alpaca.markets/v2/stocks/snapshots"):
            check("1. refused: %s" % u, not A.allowed(u))
        check("   the market-data paths are allowed", A.allowed(A.DATA + "/v2/stocks/snapshots?symbols=AAPL"))
        os.environ.pop("ALPACA_KEY_ID", None)
        os.environ.pop("ALPACA_SECRET_KEY", None)
        check("   no keys: not configured, and price() asks nothing", not A.configured() and A.price("AAPL") is None
              and not fake.sent)
        os.environ.update(ALPACA_KEY_ID="AKLIVEKEY123", ALPACA_SECRET_KEY="livesecret")
        try:
            A.snapshots(["AAPL"])
            refused = False
        except A.AlpacaBlocked:
            refused = True
        check("   a live-account key (not PK...) is refused before sending", refused and not A.configured() and not fake.sent)
        os.environ.update(ALPACA_KEY_ID="PKTEST123", ALPACA_SECRET_KEY="papersecret")
        check("   a paper key (PK...) is accepted", A.configured())

        # 2. snapshots, latest trade, minutes
        sn = A.snapshots(["aapl", "MSFT", "ZZZZ", "NOPE"])
        check("2. snapshots: price, change vs the previous close, day high / low; no price -> left out",
              sn["AAPL"]["price"] == 228.45 and sn["AAPL"]["chg_pct"] == round((228.45 - 225) / 225 * 100, 3)
              and sn["AAPL"]["high"] == 229.1 and "ZZZZ" not in sn and "NOPE" not in sn, sn)
        check("   nanosecond timestamps parse", abs(sn["AAPL"]["t"] - datetime(2026, 11, 11, 15, 30, 1, 123456,
                                                                                tzinfo=timezone.utc).timestamp()) < 1e-3)
        q = A.price("MSFT")
        check("   latest trade for one symbol", q and q[0] == 410.1, q)
        mins = A.minutes("AAPL", datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc))
        check("   1-minute IEX bars", mins and mins[0][4] == 228.4 and len(mins[0]) == 5, mins)
        check("   every request: GET to data.alpaca.markets with the key headers, feed=iex",
              all(m == "GET" and urllib.parse.urlsplit(u).hostname == "data.alpaca.markets" and "feed=iex" in u
                  and h.get("Apca-api-key-id") == "PKTEST123" for m, u, h in fake.sent), fake.sent)

        # 3. the ticker's file
        import us_ticker as T
        os.makedirs("trader/paper", exist_ok=True)
        with open("trader/paper/ledger.json", "w") as fh:
            json.dump({"open": [{"market": "US", "symbol": "ZZZZ"}, {"market": "NSE", "symbol": "TCS"}]}, fh)
        syms = T.watch_list()
        check("3. the ticker watches open US positions first, then the US watch list",
              syms[0] == "ZZZZ" and "AAPL" in syms and "TCS" not in syms, syms[:5])
        ticks, missing = T.build(["AAPL", "MSFT", "ZZZZ"], A.snapshots(["AAPL", "MSFT", "ZZZZ"]))
        T.write(ticks, missing)
        check("   ticks keyed like paper positions, with the previous close and change; missing listed",
              set(ticks) == {"US:AAPL", "US:MSFT"} and ticks["US:AAPL"]["close"] == 225.0 and missing == ["ZZZZ"],
              (ticks, missing))
        check("   tick_price reads the fresh file", A.tick_price("AAPL")[0] == 228.45)

        # 4. paper.py
        import paper as P
        p, _ = P.fetch_price("US", "AAPL")
        check("4. paper.py: a US price comes from the live Alpaca file", p == 228.45, p)
        doc = json.load(open(A.TICKS_FILE))
        doc["written"] = time.time() - 60
        json.dump(doc, open(A.TICKS_FILE, "w"))
        p2, _ = P.fetch_price("US", "MSFT")
        check("   with the file stale, one Alpaca REST request", p2 == 410.1, p2)
        check("   1-minute candles for stop / target checks come from Alpaca", P.fetch_minutes("US", "AAPL")[0][4] == 228.4)

        # 5. the dashboard endpoint
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        here = os.path.join(tmp, "trader", "live", "us_ticks.json")
        import api._kite as AK
        AK.AL.TICKS_FILE = here
        AK.K.TICKS_FILE = os.path.join(tmp, "trader", "live", "ticks.json")
        AK.CX.TICKS_FILE = os.path.join(tmp, "trader", "live", "crypto_ticks.json")
        app = FastAPI()
        app.include_router(AK.router)
        c = TestClient(app)
        T.write(ticks, missing)
        r = c.get("/api/py/live/ticks").json()
        check("5. /api/py/live/ticks serves the US ticks while the feed is live",
              r["us_live"] and r["us_configured"] and r["ticks"]["US:AAPL"]["ltp"] == 228.45 and r["us_missing"] == ["ZZZZ"], r)
        doc = json.load(open(here))
        doc["written"] = time.time() - 60
        json.dump(doc, open(here, "w"))
        r2 = c.get("/api/py/live/ticks").json()
        check("   and not when it stopped", not r2["us_live"] and "US:AAPL" not in r2["ticks"], r2)
        src = open(os.path.join(ROOT, "alpaca.py"), encoding="utf-8").read()
        check("   the code holds no trading URL (orders, positions, account)",
              "/v2/orders" not in src and "https://paper-api" not in src and "https://api.alpaca" not in src)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)
