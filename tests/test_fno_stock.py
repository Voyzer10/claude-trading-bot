#!/usr/bin/env python3
"""F&O stocks bought as ATM options (fno_stock.py + paper.setup_decision, fno_stock_options on). Offline: a fake
Zerodha with a made-up chain.

    python tests/test_fno_stock.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


class FakeKite:
    """kite.py's interface with a RELIANCE chain: monthly 2026-11-24, strikes 1380..1440 step 20, lot 500."""
    def __init__(self, prem):
        import kite
        self.paper_name = kite.paper_name
        self.prem = prem
        self.asked = []

    def fno_underlyings(self):
        return ["NIFTY", "RELIANCE"]

    def fno_chain(self, name, expiry=None):
        out = []
        for e in ("2026-11-12", "2026-11-24"):            # a too-near expiry first: must be skipped
            for k in range(1380, 1460, 20):
                for t in ("CE", "PE"):
                    out.append({"type": t, "strike": float(k), "expiry": e, "tradingsymbol": "X", "token": 1, "lot": 500})
        return out

    def quotes(self, keys):
        self.asked += keys
        return {k: (self.prem, datetime.now(timezone.utc), {}) for k in keys}

    def tick_price(self, key):
        return None


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import fno_stock as FS
        import paper as P
        now = datetime(2026, 11, 10, 5, 0, tzinfo=timezone.utc)      # 10:30 IST
        setup = {"setup": "v4_primary_long", "name": "v4 primary long", "side": "long", "price": 1412.0,
                 "stop": 1402.0, "target": 1432.0, "scanner": "v4", "liquidity": "swept 1404, reclaimed"}
        fk = FakeKite(prem=30.0)
        op = FS.plan("RELIANCE", setup, now=now, kite=fk)
        check("1. long setup -> the ATM CALL of the first expiry 3+ days away (24 Nov, strike 1420 nearest 1412)",
              op["name"] == "RELIANCE-20261124-1420-CE" and op["lot"] == 500, op)
        check("   premium stop below / target above the premium, from the stock's own stop / target",
              op["stop"] < 30.0 < op["target"] and 0.3 < op["delta"] < 0.7, op)
        ops = FS.plan("RELIANCE", dict(setup, side="short", stop=1422.0, target=1392.0), now=now, kite=fk)
        check("2. short setup -> the ATM PUT (buying it, never selling an option)",
              ops["name"].endswith("-PE") and ops["stop"] < 30.0 < ops["target"], ops)
        try:
            FS.plan("TINYCO", setup, now=now, kite=fk)
            check("3. a stock without F&O is NoOption", False)
        except FS.NoOption as e:
            check("3. a stock without F&O is NoOption (the shares are traded instead)", "has no F&O" in str(e), e)
        try:
            import kite
            kite.forget_session()
            FS.plan("RELIANCE", setup, now=now)
            check("4. Zerodha not connected: NoOption, no guessed price", False)
        except FS.NoOption as e:
            check("4. Zerodha not connected: NoOption, no guessed price", "not connected" in str(e), e)

        # through the agents: an INDIA account on Scanner v4 with stock options on
        cfg = P.load_config()
        cfg["accounts"]["INDIA"].update({"scanner_version": "v4", "fno_stock_options": True, "trade_setups": True})
        P.save_json(P.CONFIG, cfg)
        FS.plan.__defaults__ = (None, fk)
        P.session = lambda m, n: "open"
        P.past_flat_by = lambda m, a, n: False
        P.fetch_price = lambda m, t: (30.0, datetime.now(timezone.utc))
        P.lot_of = lambda m, t: 500 if m == "NFO" else 1
        wide = P.setup_decision("NSE", "RELIANCE", setup)
        check("5. a Rs 10 stock stop on a 500 lot risks ~Rs 2,400 of premium: blocked, with the reason (max Rs 1,500)",
              wide["result"] == "blocked" and "0 lots fit" in wide["why"], wide.get("why"))
        tight = dict(setup, stop=1407.0, target=1422.0)
        rec = P.setup_decision("NSE", "RELIANCE", tight)
        led = P.load_ledger(P.load_config())
        pos = led["open"][0] if led["open"] else {}
        check("   a Rs 5 stop fits: setup_decision paper BUYS the call, not the shares: NFO:RELIANCE-20261124-1420-CE",
              rec["result"] == "PAPER BUY" and pos.get("key") == "NFO:RELIANCE-20261124-1420-CE", rec)
        check("   1 lot of 500 (loss at the premium stop within Rs 1,500), stops / targets on the premium",
              pos.get("qty") == 500 and abs(pos["entry"] - pos["stop"]) * pos["qty"] <= 1500
              and pos["stop"] < pos["entry"] < pos["target"], pos)
        check("   the trade says why: setup, scanner, IV / delta, the stock's stop and target",
              pos.get("scanner") == "v4" and "ATM CE" in pos.get("entry_reason", "") and "1407" in pos.get("entry_reason", ""),
              pos.get("entry_reason"))
        cfg = P.load_config()
        cfg["accounts"]["INDIA"]["fno_stock_options"] = False
        P.save_json(P.CONFIG, cfg)
        led["open"] = []
        P.save_json(P.LEDGER, led)
        P.fetch_price = lambda m, t: (1412.0, datetime.now(timezone.utc))
        rec2 = P.setup_decision("NSE", "RELIANCE", setup)
        led = P.load_ledger(P.load_config())
        check("6. switch off (the default): the shares, as before",
              rec2["result"] == "PAPER BUY" and led["open"] and led["open"][0]["key"] == "NSE:RELIANCE", rec2)
        check("   the default config has stock options OFF until the backtest passes",
              P.DEFAULT_CONFIG["accounts"]["INDIA"]["fno_stock_options"] is False)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
