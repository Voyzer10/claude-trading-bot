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
    """kite.py's interface with a RELIANCE chain: monthly 2026-11-24, strikes 1380..1440 step 20, lot 500.
    `expiries` overrides the expiry dates of the chain (the expiry-rule checks below)."""
    def __init__(self, prem, expiries=("2026-11-12", "2026-11-24")):   # a too-near expiry first: must be skipped
        import kite
        self.paper_name = kite.paper_name
        self.prem = prem
        self.expiries = tuple(expiries)
        self.asked = []

    def fno_underlyings(self):
        return ["NIFTY", "BANKNIFTY", "RELIANCE"]

    def fno_chain(self, name, expiry=None):
        out = []
        lo, hi, step, lot = (52000, 53100, 100, 30) if name == "BANKNIFTY" else (1380, 1460, 20, 500)
        for e in self.expiries:
            for k in range(lo, hi, step):
                for t in ("CE", "PE"):
                    out.append({"type": t, "strike": float(k), "expiry": e, "tradingsymbol": "X", "token": 1, "lot": lot})
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
        import _old_budget
        _old_budget.apply(P)   # written against the pre-17-Nov budgets
        now = datetime(2026, 11, 10, 5, 0, tzinfo=timezone.utc)      # 10:30 IST
        setup = {"setup": "v4_primary_long", "name": "v4 primary long", "side": "long", "price": 1412.0,
                 "stop": 1402.0, "target": 1432.0, "scanner": "v4", "liquidity": "swept 1404, reclaimed",
                 "v4_signal_at": now.isoformat()}
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
        cfg["accounts"]["INDIA"].update({"scanner_version": "v4", "trade_setups": True})
        cfg["accounts"]["FNO"].update({"scanner_version": "v4", "fno_stock_options": True, "trade_setups": True,
                                       "fno_underlyings": ["BANKNIFTY", "RELIANCE"]})
        P.save_json(P.CONFIG, cfg)
        # paper.setup_decision calls FS.plan(symbol, setup) without `now`, so plan() would read the real clock and the
        # fixed 2026-11-24 expiry would stop qualifying once it is < MIN_DAYS away (CI failure from 22 Nov 2026 IST).
        # Inject the same reference clock as checks 1-4, together with the fake Zerodha.
        FS.plan.__defaults__ = (now, fk)
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
              pos.get("scanner") == "v4" and pos.get("v4_chart") == "NSE:RELIANCE"
              and "ATM CE" in pos.get("entry_reason", "") and "1407" in pos.get("entry_reason", ""),
              pos.get("entry_reason"))
        if pos:
            pos.pop("v4_chart", None)
            pos.pop("v4_signal_at", None)
            P.save_json(P.LEDGER, led)
            again = P.setup_decision("NSE", "RELIANCE", tight)
            check("   an older v4 option without chart metadata still blocks overlap",
                  again["result"] == "skipped" and ("wait for the open trade" in again["why"]
                                                    or "is still open on this chart" in again["why"]), again)
        cfg = P.load_config()
        cfg["accounts"]["FNO"]["fno_stock_options"] = False
        P.save_json(P.CONFIG, cfg)
        led["open"] = []
        P.save_json(P.LEDGER, led)
        P.fetch_price = lambda m, t: (1412.0, datetime.now(timezone.utc))
        rec2 = P.setup_decision("NSE", "RELIANCE", setup)
        led = P.load_ledger(P.load_config())
        check("6. switch off (the default): the shares, as before",
              rec2["result"] == "PAPER BUY" and led["open"] and led["open"][0]["key"] == "NSE:RELIANCE", rec2)
        check("   the default config has stock options OFF until the backtest passes",
              P.DEFAULT_CONFIG["accounts"]["FNO"]["fno_stock_options"] is False)

        # owner, 12 Nov 2026: F&O only on Nifty 50 and Bank Nifty, in its own FNO account
        check("7. the default F&O list is Nifty 50 + Bank Nifty, stock options off",
              P.DEFAULT_CONFIG["accounts"]["FNO"]["fno_underlyings"] == ["NIFTY", "BANKNIFTY"]
              and not P.DEFAULT_CONFIG["accounts"]["FNO"]["fno_stock_options"])
        cfg = P.load_config()
        cfg["accounts"]["FNO"].update({"fno_stock_options": True, "fno_underlyings": ["BANKNIFTY"]})
        P.save_json(P.CONFIG, cfg)
        led = P.load_ledger(cfg)
        led["open"], led["closed"] = [], []
        P.save_json(P.LEDGER, led)
        rec3 = P.setup_decision("NSE", "RELIANCE", setup)
        led = P.load_ledger(P.load_config())
        check("   stock options on, but RELIANCE is not in the F&O list: the shares, not an option",
              rec3["result"] == "PAPER BUY" and led["open"] and led["open"][0]["key"] == "NSE:RELIANCE", rec3)
        nifty = dict(setup, price=24500.0, stop=24470.0, target=24560.0)
        rec4 = P.setup_decision("NSE", "NIFTY", nifty)
        check("   an index not in the F&O list: skipped with the reason", rec4["result"] == "skipped"
              and "only on BANKNIFTY" in rec4["why"], rec4)
        bnf = dict(setup, price=52540.0, stop=52480.0, target=52640.0)
        fk.prem = 250.0
        led["open"] = []                                   # free the cash the RELIANCE shares tied up
        P.save_json(P.LEDGER, led)
        P.fetch_price = lambda m, t: (250.0, datetime.now(timezone.utc))
        P.lot_of = lambda m, t: 30 if m == "NFO" else 1
        rec5 = P.setup_decision("NSE", "BANKNIFTY", bnf)
        led = P.load_ledger(P.load_config())
        bpos = [p for p in led["open"] if p["key"].startswith("NFO:BANKNIFTY")]
        check("   a v4 setup on Bank Nifty buys its ATM call (52500 CE), linked to the Bank Nifty chart",
              rec5["result"] == "PAPER BUY" and bpos and bpos[0]["key"] == "NFO:BANKNIFTY-20261124-52500-CE"
              and bpos[0].get("v4_chart") == "NSE:BANKNIFTY", (rec5.get("why"), [p["key"] for p in led["open"]]))
        check("   the option is paid from the FNO account, not the INDIA stock account",
              P.account_of("NFO") == "FNO" and led["accounts"]["FNO"]["cash"] < 100000
              and P.account_of("NSE") == "INDIA", led["accounts"])

        # 8. the expiry rule itself (fno_stock.MIN_DAYS = 3 calendar days, counted on the IST date of `now`), with a
        # controlled clock: reference date 10 Nov 2026 IST
        ref = datetime(2026, 11, 10, 5, 0, tzinfo=timezone.utc)                  # 10:30 IST on 10 Nov
        check("8. the rule under test is 3+ calendar days", FS.MIN_DAYS == 3, FS.MIN_DAYS)

        def first_expiry(expiries, at=ref):
            return FS.plan("RELIANCE", setup, now=at, kite=FakeKite(prem=30.0, expiries=expiries))["expiry"]

        def no_option(expiries, at=ref):
            try:
                FS.plan("RELIANCE", setup, now=at, kite=FakeKite(prem=30.0, expiries=expiries))
                return False, "an option was chosen"
            except FS.NoOption as e:
                return "no option expiry 3+ days away" in str(e), e

        ok, why = no_option(["2026-11-05"])
        check("   an expiry in the past never qualifies", ok, why)
        ok, why = no_option(["2026-11-10"])
        check("   an expiry on the reference date itself (0 days) does not qualify", ok, why)
        ok, why = no_option(["2026-11-11", "2026-11-12"])
        check("   expiries 1 and 2 days away do not qualify", ok, why)
        ok, why = no_option(["2026-11-05", "2026-11-10", "2026-11-12"])
        check("   no qualifying expiry (past, same day, too near): NoOption with the reason, no guessed contract", ok, why)
        got = first_expiry(["2026-11-12", "2026-11-13", "2026-11-17"])
        check("   exactly 3 days away qualifies (boundary inclusive) and is the nearest chosen", got == "2026-11-13", got)
        got = first_expiry(["2026-11-05", "2026-11-10", "2026-11-12", "2026-11-17"])
        check("   more than 3 days away qualifies; past / same-day / too-near ones are skipped", got == "2026-11-17", got)
        got = first_expiry(["2026-11-24", "2026-11-17", "2026-11-13"])
        check("   the nearest qualifying expiry wins whatever the chain order", got == "2026-11-13", got)
        late_utc = datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc)             # 01:30 IST on 10 Nov (UTC: 9 Nov)
        ok, why = no_option(["2026-11-12"], at=late_utc)
        check("   days are counted on the IST date (9 Nov UTC = 10 Nov IST: 12 Nov is only 2 days away)", ok, why)
        got = first_expiry(["2026-11-12", "2026-11-13"], at=late_utc)
        check("   ... and 13 Nov is exactly 3 IST days away from that instant", got == "2026-11-13", got)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
