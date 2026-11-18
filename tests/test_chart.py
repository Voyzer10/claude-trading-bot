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

        # 6. closed trades and skipped candidates explained (owner, 13 Nov 2026)
        T0 = int((now - timedelta(hours=6)).timestamp()) // 300 * 300
        def bars(spec):   # [(o, h, l, c)] every 5 min from T0
            return {"t": [T0 + 300 * i for i in range(len(spec))], "o": [b[0] for b in spec], "h": [b[1] for b in spec],
                    "l": [b[2] for b in spec], "c": [b[3] for b in spec], "v": [1] * len(spec)}
        iso = lambda i: datetime.fromtimestamp(T0 + 300 * i, timezone.utc).isoformat()   # noqa: E731
        # a long: entry 100 at bar 3, stop 99, target 102; up to 100.6, down to the stop at bar 6, then up to 102.5
        path = [(100, 100.2, 99.8, 100)] * 3 + [(100, 100.4, 99.9, 100.3), (100.3, 100.6, 100.1, 100.2),
                (100.2, 100.3, 99.6, 99.7), (99.7, 99.8, 98.9, 99.0), (99.0, 100.5, 98.95, 100.4),
                (100.4, 102.5, 100.3, 102.3), (102.3, 102.4, 102.0, 102.1)]
        S.yahoo_chart = lambda sym, rng, interval, suffix="": bars(path)
        led = P.load_ledger(P.load_config())
        led["closed"] = [dict(base, key="US:AMD", market="US", symbol="AMD", side="long", entry=100.0, stop=99.0,
                              risk_stop=99.0, target=102.0, entry_time=iso(3), exit_time=iso(6), exit=99.0, reason="stop",
                              r=-1.0, pnl=-10, setup_name="v4 primary long", v4_signal_at=iso(2),
                              tm_log=[{"t": iso(4), "text": "breakeven: price reached +1.0R"}])]
        P.save_json(P.LEDGER, led)
        os.makedirs("trader/live", exist_ok=True)
        recs = [{"time": iso(3), "symbol": "US:AMD", "setup": "v4_primary_long", "result": "PAPER BUY", "why": "ok",
                 "steps": {"1_scanner": {"scanner": "v4", "setup_name": "v4 primary long", "side": "long",
                                         "BOS_at": iso(0), "sweep_at": iso(1), "swept_px": 99.8, "signal_at": iso(2),
                                         "signal": "doji", "bar_end": iso(2), "price": 100.0},
                           "4_exit": {"entry": 100.0, "stop": 99.0, "target": 102.0}}},
                {"time": iso(3), "symbol": "US:INTC", "setup": "v4_primary_long", "result": "blocked",
                 "why": "planned R:R 0.13 is below the account's minimum reward:risk 1.0",
                 "steps": {"1_scanner": {"scanner": "v4", "setup_name": "v4 primary long", "side": "long",
                                         "sweep_at": iso(1), "signal_at": iso(2), "signal": "doji", "bar_end": iso(3),
                                         "price": 100.3},
                           "4_exit": {"entry": 100.3, "stop": 98.8, "target": 102.0}}},
                {"time": iso(4), "symbol": "US:MU", "setup": "v4_primary_long", "result": "skipped",
                 "why": "price 99.0 is already past the stop 99.5",
                 "steps": {"1_scanner": {"side": "long", "bar_end": iso(4), "price": 100.2},
                           "4_exit": {"entry": 100.2, "stop": 99.9, "target": 101.0}}}]
        with open("trader/live/decisions.jsonl", "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in recs) + "\n")
        r = cl.get("/api/py/chart/position", params={"key": "US:AMD"}).json()
        v, kinds = r["verdict"], [m["kind"] for m in r["markers"]]
        check("6. a losing closed trade: Loss -1R, why (the stop), its best (+0.6R vs the +2R target), and that price "
              "reached the target after the exit",
              v["tone"] == "bad" and v["title"].startswith("Loss -1.00R") and any("original stop" in x for x in v["lines"])
              and any(x.startswith("Best it went: +0.60R") and "+2.00R" in x for x in v["lines"])
              and any(x.startswith("After the exit: price reached the target") for x in v["lines"]), v)
        check("   setup markers from the decisions log (BOS, sweep, signal), entry, the Trade Manager action, the exit",
              kinds[:3] == ["bos", "sweep", "signal"] and "entry" in kinds and "tm" in kinds and kinds[-1] == "loss"
              and any(x.startswith("Setup: BOS") and "sweep" in x and "doji" in x for x in v["lines"]), (kinds, v["lines"][:1]))
        r = cl.get("/api/py/chart/decision", params={"time": iso(3), "symbol": "US:INTC"}).json()
        v = r["verdict"]
        check("7. a blocked candidate: the planned box, the agents' reason in plain words, and what it would have done "
              "(target first -> skipping missed a winner)",
              r["box"] and r["pos"]["planned"] and r["pos"]["entry"] == 100.3 and r["pos"]["target"] == 102.0
              and any("below the account's minimum" in x for x in v["lines"])
              and any(x.startswith("In short: the reward : risk") for x in v["lines"])
              and any(x.startswith("If taken: the target came first") for x in v["lines"])
              and "So skipping it missed a winner" in v["lines"] and r["markers"][-1]["kind"] == "win", v)
        r = cl.get("/api/py/chart/decision", params={"time": iso(4), "symbol": "US:MU"}).json()
        check("   a skipped one that would have lost: stop first -> skipping saved a loss",
              any(x.startswith("If taken: the stop came first") for x in r["verdict"]["lines"])
              and "So skipping it saved a loss" in r["verdict"]["lines"]
              and any("already moved past the stop" in x for x in r["verdict"]["lines"]), r["verdict"])
        check("   an unknown decision: 404", cl.get("/api/py/chart/decision", params={"time": "x", "symbol": "US:X"}).status_code == 404)

        # 8. live candles for India and US (owner, 16 Nov 2026: "indian market and usa market m live chart data nahi")
        import alpaca as AL
        import kite as K
        now = 1_800_000_000 - 1_800_000_000 % 300 + 130          # 2 min 10 s into a 5-minute candle
        yh = [(now - 130 - 300 * k, 100.0, 101.0, 99.0, 100.0) for k in range(20, 3, -1)]   # Yahoo stops 4 candles back
        mins = [(datetime.fromtimestamp(yh[-1][0] + 60 * j, timezone.utc), 100.0 + j * 0.1, 100.2 + j * 0.1,
                 99.9 + j * 0.1, 100.1 + j * 0.1) for j in range(0, 22)]                     # minute bars up to now
        AL.configured, AL.minutes = (lambda: True), (lambda s, a, b: [m for m in mins if m[0] >= a])
        AL.tick_price = lambda s, max_age=10.0: (103.5, datetime.fromtimestamp(now, timezone.utc))
        got = CH.top_up("US", "AAPL", list(yh), now=now)
        five = [r[0] for r in got]
        check("8. US: Yahoo 4 candles behind -> filled from Alpaca minute bars up to the forming candle",
              five == sorted(set(five)) and five[-1] == now - 130 and len(got) == len(yh) + 4, (len(got), five[-3:]))
        check("   the forming candle closes at the live tick and its range takes it in",
              got[-1][4] == 103.5 and got[-1][2] >= 103.5, got[-1])
        b = got[-2]
        check("   a filled candle = its 5 minute bars (open of the first, high / low of all, close of the last)",
              b[1] == mins[15][1] and abs(b[2] - max(m[2] for m in mins[15:20])) < 1e-9 and b[4] == mins[19][4], (b, mins[15]))
        AL.minutes = lambda s, a, b: (_ for _ in ()).throw(RuntimeError("no network"))
        CH._FORMING.clear()     # (the forming candle is remembered across refreshes; a fresh chart here)
        got = CH.top_up("US", "AAPL", list(yh), now=now)
        check("   no minute bars (feed down): the live tick still adds the forming candle, nothing raises",
              got[-1][0] == now - 130 and got[-1][4] == 103.5 and got[-1][1] == yh[-1][4], got[-1])
        AL.tick_price = lambda s, max_age=10.0: None
        check("   no feed at all: Yahoo's candles unchanged", CH.top_up("US", "AAPL", list(yh), now=now) == yh)
        check("   market closed (Yahoo's last candle is from yesterday): unchanged",
              CH.top_up("US", "AAPL", list(yh), now=now + 20 * 3600) == yh)
        K.connected = lambda: False
        seen = {}
        def kt(key, max_age=5.0):
            seen["key"] = key
            return (24050.0, datetime.fromtimestamp(now, timezone.utc))
        K.tick_price = kt
        got = CH.top_up("INDEX", "NIFTY", list(yh), now=now)
        check("   India: the Nifty chart reads the ticker's NSE:NIFTY50 price (Kite minute bars off: tick only)",
              seen.get("key") == "NSE:NIFTY50" and got[-1][4] == 24050.0, (seen, got[-1]))
        CH.top_up("NSE", "TCS", list(yh), now=now)
        check("   a stock reads NSE:<symbol>", seen.get("key") == "NSE:TCS", seen)

        # 9. Yahoo's live point (stamped 16:46) joins the forming 16:45 candle instead of drawing as its own candle
        #    (VPS, 18 Nov 2026: BTC and NFLX both showed a one-price "16:46" candle)
        t0 = 1795000000 - 1795000000 % 300
        rows = [(t0, 100.0, 101.0, 99.5, 100.5), (t0 + 300, 100.5, 101.2, 100.2, 100.8), (t0 + 360, 102.0, 102.0, 102.0, 102.0)]
        got = CH.on_grid(rows)
        check("9. the off-grid live point joins its 5-minute candle (high / close move to it, no extra candle)",
              got == [rows[0], (t0 + 300, 100.5, 102.0, 100.2, 102.0)], got)
        got = CH.on_grid(rows[:1] + [(t0 + 420, 99.0, 99.0, 99.0, 99.0)])
        check("   a live point past the last candle starts its own candle (on the grid)",
              got[-1] == (t0 + 300, 99.0, 99.0, 99.0, 99.0) and len(got) == 2, got)
        check("   on-grid candles are unchanged", CH.on_grid(rows[:2]) == rows[:2])
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)
