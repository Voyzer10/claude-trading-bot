#!/usr/bin/env python3
"""US F&O (owner, 13 Nov 2026): QQQ / SPY Scanner v4 setups bought as ATM weekly options in their own USFNO paper
account ($50,000); Alpaca options data (paper key, data host only, indicative feed); the Nasdaq-100 on the US watch
list; the usopt-sv4 backtest. Offline: every request is answered by a fake.

    python tests/test_us_fno.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


NOW = datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc)     # Mon 16 Nov 2026, 11:00 New York


def chain_doc(und, kind):
    """A fake Alpaca chain: expiries 17, 18, 20 Nov (1, 2, 4 days), strikes 498-502."""
    out = {}
    for d in (date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 20)):
        for k in (498, 499, 500, 501, 502):
            sym = "%s%s%s%08d" % (und, d.strftime("%y%m%d"), "C" if kind == "call" else "P", k * 1000)
            out[sym] = {"latestQuote": {"bp": 4.9, "ap": 5.1, "t": "2026-11-16T16:00:00Z"},
                        "latestTrade": {"p": 5.0, "t": "2026-11-16T15:59:00Z"},
                        "greeks": {"delta": 0.5}, "impliedVolatility": 0.2}
    return {"snapshots": out, "next_page_token": None}


class Fake:
    def __init__(self):
        self.sent = []

    def __call__(self, req, timeout=None):
        self.sent.append((req.get_method(), req.full_url))
        u = urllib.parse.urlsplit(req.full_url)
        q = urllib.parse.parse_qs(u.query)
        if u.path.startswith("/v1beta1/options/snapshots/"):
            body = chain_doc(u.path.rsplit("/", 1)[1], q.get("type", ["call"])[0])
        elif u.path == "/v1beta1/options/snapshots":
            body = {"snapshots": {s: {"latestQuote": {"bp": 5.9, "ap": 6.1, "t": "2026-11-16T16:05:00Z"}}
                                  for s in q["symbols"][0].split(",")}}
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
        os.environ.update(ALPACA_KEY_ID="PKTEST123", ALPACA_SECRET_KEY="papersecret")

        # 1. data only: the options market-data paths, nothing that trades
        check("1. options chain / snapshots allowed on the data host",
              A.allowed(A.DATA + "/v1beta1/options/snapshots/QQQ?feed=indicative")
              and A.allowed(A.DATA + "/v1beta1/options/snapshots?symbols=QQQ261120C00500000"))
        for u in ("https://paper-api.alpaca.markets/v2/orders", "https://data.alpaca.markets/v2/orders",
                  "https://data.alpaca.markets/v1beta1/options/orders", "https://api.alpaca.markets/v2/positions"):
            check("   refused: %s" % u, not A.allowed(u))
        ch = A.option_chain("QQQ", "call", "2026-11-18", "2026-11-26", 485, 515)
        check("   chain parsed: bid / ask / midpoint / last; indicative feed; GET to the data host only",
              len(ch) == 15 and ch[0]["mid"] == 5.0 and ch[0]["bid"] == 4.9
              and all(m == "GET" and "data.alpaca.markets" in u and "feed=indicative" in u for m, u in fake.sent), ch[:1])

        # 2. the contract
        import us_options as UO
        setup = {"setup": "v4_primary_long", "name": "v4 primary long", "side": "long", "price": 500.3, "stop": 498.8,
                 "target": 503.3, "scanner": "v4", "v4_signal_at": NOW.isoformat()}
        op = UO.plan("QQQ", setup, now=NOW)
        check("2. long QQQ setup -> the ATM CALL of the first expiry 2+ days away (18 Nov, strike 500)",
              op["name"] == "QQQ261118C00500000" and op["lot"] == 100 and op["premium"] == 5.0
              and op["stop"] < 5.0 < op["target"], op)
        ops = UO.plan("SPY", dict(setup, side="short", price=499.7, stop=501.2, target=496.7), now=NOW)
        check("   short SPY setup -> the ATM PUT (bought, never sold)", ops["name"] == "SPY261118P00500000", ops)
        for bad, why in (("AAPL", "only QQQ, SPY, DIA"),):
            try:
                UO.plan(bad, setup, now=NOW)
                got = None
            except UO.NoOption as e:
                got = str(e)
            check("   not an F&O underlying: %s" % why, got and "only QQQ, SPY, DIA" in got, got)
        check("   OCC symbols parse", UO.parse("SPY261120P00672500") == {"underlying": "SPY", "expiry": date(2026, 11, 20),
                                                                         "kind": "PE", "strike": 672.5})
        check("   a held contract is priced from its quote midpoint", UO.price("QQQ261118C00500000")[0] == 6.0)

        # 3. the account and the trade through the agents
        import paper as P
        os.makedirs(os.path.dirname(P.CONFIG), exist_ok=True)
        json.dump({"accounts": {"US": dict(P.DEFAULT_CONFIG["accounts"]["US"], scanner_version="v4",
                                           v4_setups=["v4_primary_long", "v4_primary_short"])}}, open(P.CONFIG, "w"))
        cfg = P.load_config()
        u = cfg["accounts"]["USFNO"]
        check("3. USFNO account: $50,000, its own limits, US's scanner switches copied once, QQQ / SPY / DIA only",
              u["capital"] == 50000 and u["scanner_version"] == "v4" and u["v4_setups"] == ["v4_primary_long", "v4_primary_short"]
              and u["usopt_underlyings"] == ["QQQ", "SPY", "DIA"] and P.account_of("USOPT") == "USFNO"
              and P.lot_of("USOPT", "x") == 100 and P.kind_of("USOPT", "QQQ261118C00500000") == "options", u)
        dia = UO.plan("DIA", dict(setup, price=500.3), now=NOW, chain=[dict(r, symbol=r["symbol"].replace("QQQ", "DIA"))
                                                                        for r in A.option_chain("QQQ", "call")])
        check("   DIA (the Dow) is a US F&O underlying too", dia["name"] == "DIA261118C00500000", dia)
        prev = dict(cfg)
        prev["accounts"] = dict(cfg["accounts"], USFNO=dict(u, usopt_underlyings=["QQQ", "SPY"]))
        prev.pop("_usopt_dia", None)
        json.dump(prev, open(P.CONFIG, "w"))
        check("   an older USFNO (QQQ / SPY) gets DIA added once", P.load_config()["accounts"]["USFNO"]["usopt_underlyings"]
              == ["QQQ", "SPY", "DIA"])
        P.session = lambda m, n: "open"
        P.past_flat_by = lambda m, a, n: False
        P.fetch_price = lambda m, t: (5.0, datetime.now(timezone.utc)) if m == "USOPT" else (190.0, datetime.now(timezone.utc))
        UO.plan.__defaults__ = (NOW, None)
        rec = P.setup_decision("US", "QQQ", setup)
        led = P.load_ledger(P.load_config())
        pos = next((p for p in led["open"] if p["market"] == "USOPT"), {})
        check("   a QQQ v4 setup paper BUYS the call in USFNO, never QQQ shares",
              rec["result"] == "PAPER BUY" and pos.get("key") == "USOPT:QQQ261118C00500000"
              and not any(p["key"] == "US:QQQ" for p in led["open"]), (rec.get("result"), rec.get("why")))
        check("   whole contracts (x100), loss at the premium stop within $500, stop / target on the premium",
              pos.get("qty", 0) % 100 == 0 and pos["qty"] >= 100
              and abs(pos["entry"] - pos["stop"]) * pos["qty"] <= 500 + 1e-6 and pos["stop"] < pos["entry"] < pos["target"], pos)
        check("   the trade says why (ATM call, IV / delta, the ETF's stop / target) and keeps the v4 chart",
              "ATM call" in pos.get("entry_reason", "") and "498.8" in pos.get("entry_reason", "")
              and pos.get("v4_chart") == "US:QQQ" and rec["steps"]["4_exit"]["instrument"] == pos["key"], pos.get("entry_reason"))
        check("   paid from the USFNO book, the US stock book untouched",
              led["accounts"]["USFNO"]["cash"] < 50000 and led["accounts"]["US"]["cash"] == 50000, led["accounts"])
        again = P.setup_decision("US", "QQQ", setup)
        check("   one trade at a time per chart: the next QQQ setup waits", again["result"] == "skipped"
              and ("open trade on this chart" in again["why"] or "is still open on this chart" in again["why"]), again.get("why"))
        UO.plan.__defaults__ = (NOW, [])
        rec2 = P.setup_decision("US", "SPY", dict(setup, v4_signal_at=(NOW + timedelta(minutes=5)).isoformat()))
        check("   no priced contract -> skipped with the reason", rec2["result"] == "skipped" and rec2["why"].startswith("option:"),
              rec2.get("why"))
        fee = P.charges(cfg, "USOPT", "QQQ261118C00500000", "buy", 1000.0)
        check("   costs: the account's fee_pct a side (0.5%: contract fees + spread)", abs(fee - 5.0) < 1e-9, fee)

        # 4. the dashboard / API pieces
        import api._ops as O
        import api._chart as CH
        check("4. API maps USOPT trades to the USFNO account; Settings can edit its option max loss and fees",
              O._acct("USOPT") == "USFNO" and O._ACCT["USOPT"] == "USFNO"
              and "USFNO" in O.RISK_FIELDS["max_loss_per_trade_fno"]["accounts"] and "USFNO" in O.RISK_FIELDS["fee_pct"]["accounts"])
        check("   View on chart draws an option on its ETF's chart (no box)",
              CH.chart_of({"market": "USOPT", "symbol": "QQQ261118C00500000"}) == ("US", "QQQ", "US:QQQ", False))
        import auto_us as AU
        check("5. the US watch list has the Nasdaq-100 and the Dow 30 + DIA (no duplicates) and the four index cards",
              len(AU.NASDAQ_100) >= 100 and set(AU.NASDAQ_100) <= set(AU.US_WATCH) and len(AU.US_WATCH) == len(set(AU.US_WATCH))
              and "QQQ" in AU.US_WATCH and "DIA" in AU.US_WATCH and set(AU.DOW_30) <= set(AU.US_WATCH) and len(AU.DOW_30) == 30
              and [k for k, _, _ in AU.US_INDICES] == ["NDX", "IXIC", "SPX", "DJI"], len(AU.US_WATCH))

        # 6. the backtest's US option pricing (one trade, no data download)
        import research_fno_sv4 as R
        rows = [(datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc) + timedelta(minutes=5 * i), 500 + (i % 7) * 0.1,
                 500.6 + (i % 7) * 0.1, 499.6 + (i % 7) * 0.1, 500.2 + (i % 9) * 0.07 - (i % 4) * 0.05, 1000) for i in range(500)]
        t = {"i": 450, "exit_i": 470, "entry": 500.3, "stop": 498.8, "exit": 503.3, "side": "long"}
        o = R.option_trade(t, rows, __import__("zoneinfo").ZoneInfo("America/New_York"), P.DEFAULT_CONFIG,
                           dict(P.DEFAULT_CONFIG["accounts"]["USFNO"]), 100, R.SPEC_US)
        check("6. backtest: a winning QQQ long priced as a weekly call: positive R after the 0.5% a side, whole contracts",
              isinstance(o, dict) and o["r"] > 0 and o["lot"] == 100 and o["lots"] >= 1 and o["money"] > 0, o)
        check("   weekly expiry: the Friday at least 2 days away",
              R.weekly_expiry_us(date(2026, 11, 16)) == date(2026, 11, 20) and R.weekly_expiry_us(date(2026, 11, 19)) == date(2026, 11, 27))
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)
