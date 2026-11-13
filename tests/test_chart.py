#!/usr/bin/env python3
"""View on chart (api/_chart.py): a paper position's 5-minute candles, levels and broker links. Offline: the candle
fetch is faked.

    python tests/test_chart.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        import scan_nse as S
        import scan_crypto as C
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        t0 = int((now - timedelta(hours=40)).timestamp()) // 300 * 300
        fake = {"t": [t0 + 300 * i for i in range(480)], "o": [100.0] * 480, "h": [100.5] * 480, "l": [99.5] * 480,
                "c": [100.2] * 480, "v": [1] * 480}
        asked = []
        S.yahoo_chart = lambda sym, rng, interval, suffix="": asked.append(("yahoo", sym + suffix, rng, interval)) or fake
        C.crypto_chart = lambda sym, rng, interval, suffix=None: asked.append(("crypto", sym, rng, interval)) or fake
        cfg = P.load_config()
        et = (now - timedelta(hours=2)).isoformat()
        base = {"qty": 1, "entry_fee": 0, "kind": "equity", "entry_date": now.date().isoformat(), "entry_time": et}
        led = {"accounts": P.load_ledger(cfg)["accounts"], "closed": [], "open": [
            dict(base, key="US:QCOM", market="US", symbol="QCOM", side="short", entry=182.6, stop=183.5, risk_stop=184.4,
                 target=179.0, setup_name="v4 primary short", v4_signal_at=(now - timedelta(hours=2, minutes=10)).isoformat(),
                 trailing=True),
            dict(base, key="CRYPTO:BTC", market="CRYPTO", symbol="BTC", side="long", entry=100, stop=99, target=103),
            dict(base, key="NFO:BANKNIFTY-20261124-52500-CE", market="NFO", symbol="BANKNIFTY-20261124-52500-CE",
                 entry=250, stop=200, target=350, v4_chart="NSE:BANKNIFTY", kind="option")]}
        led["closed"].append(dict(base, key="NSE:TCS", market="NSE", symbol="TCS", entry=4000, stop=3980, target=4040,
                                  exit=4040, exit_time=now.isoformat(), reason="target"))
        P.save_json(P.LEDGER, led)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import api._chart as CH
        import kite as K
        K.resolve = lambda key: (_ for _ in ()).throw(K.KiteError("offline"))
        app = FastAPI()
        app.include_router(CH.router)
        cl = TestClient(app)

        r = cl.get("/api/py/chart/position", params={"key": "US:QCOM"}).json()
        check("1. a US short: 5m candles from ~30h before the entry, its levels, the box, a TradingView link",
              r["box"] and r["pos"]["side"] == "short" and r["pos"]["risk_stop"] == 184.4 and r["pos"]["stop"] == 183.5
              and r["pos"]["signal_at"] and r["candles"] and r["candles"][0][0] >= int((now - timedelta(hours=32)).timestamp())
              and asked[-1] == ("yahoo", "QCOM", "5d", "5m")
              and r["links"][0]["url"] == "https://www.tradingview.com/chart/?symbol=QCOM&interval=5", (r["links"], asked[-1]))
        r = cl.get("/api/py/chart/position", params={"key": "CRYPTO:BTC"}).json()
        check("2. crypto: the crypto chart (the bot's feed), a Coinbase TradingView link and a note about CoinDCX",
              asked[-1][0] == "crypto" and "COINBASE:BTCUSD" in r["links"][0]["url"] and "CoinDCX" in (r["note"] or ""), r["links"])
        r = cl.get("/api/py/chart/position", params={"key": "NFO:BANKNIFTY-20261124-52500-CE"}).json()
        check("3. an option: drawn on Bank Nifty's index chart, no box (premiums), says why",
              r["chart"] == "NSE:BANKNIFTY" and not r["box"] and asked[-1][1] == "^NSEBANK" and "premium" in r["note"], r["note"])
        r = cl.get("/api/py/chart/position", params={"key": "NSE:TCS"}).json()
        check("4. a closed trade too: exit and reason; NSE on Yahoo .NS; TradingView NSE link (no Kite token offline)",
              not r["open"] and r["pos"]["exit"] == 4040 and asked[-1][1] == "TCS.NS"
              and r["links"][-1]["url"].endswith("symbol=NSE:TCS&interval=5"), (r["pos"], r["links"]))
        K.resolve = lambda key: {"exchange": "NSE", "tradingsymbol": "TCS", "token": 2953217}
        r = cl.get("/api/py/chart/position", params={"key": "NSE:TCS"}).json()
        check("   with Kite instruments: a Kite chart link with the token",
              r["links"][0] == {"name": "Kite", "url": "https://kite.zerodha.com/chart/ext/ciq/NSE/TCS/2953217"}, r["links"])
        check("5. an unknown position: 404", cl.get("/api/py/chart/position", params={"key": "US:NOPE"}).status_code == 404)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)
