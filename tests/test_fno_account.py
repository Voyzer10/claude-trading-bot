#!/usr/bin/env python3
"""F&O in its own paper account (owner, 12 Nov 2026): INDIA = NSE / BSE stocks (Rs 50,000), FNO = NFO (Rs 1,00,000),
F&O only on Nifty 50 and Bank Nifty. Checks the one-time split of an old shared INDIA config and ledger. Offline.

    python tests/test_fno_account.py
"""
import json
import os
import shutil
import sys
import tempfile

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
        # an old install: one INDIA account for stocks and F&O, on Scanner v4, capital raised to 80,000
        old_india = dict(P.DEFAULT_CONFIG["accounts"]["INDIA"], capital=80000, scanner_version="v4",
                         v4_setups=["v4_primary_long"], max_loss_per_trade_fno=1200, fno_stock_options=True,
                         fno_underlyings=["BANKNIFTY"])
        os.makedirs(os.path.dirname(P.CONFIG), exist_ok=True)
        json.dump({"accounts": {"INDIA": old_india}}, open(P.CONFIG, "w"))
        # ledger: INDIA started 80,000; a closed stock trade +300, a closed option trade -900, an open option (2 lots
        # of 30 @ 250 + Rs 25 fee) and an open stock (10 @ 1,000 + Rs 5 fee)
        opt = {"key": "NFO:BANKNIFTY-20261124-52500-CE", "market": "NFO", "symbol": "BANKNIFTY-20261124-52500-CE",
               "qty": 60, "entry": 250.0, "stop": 200.0, "target": 350.0, "entry_fee": 25.0, "kind": "option",
               "entry_date": "2026-11-12", "entry_time": "2026-11-12T05:00:00+00:00", "side": "long"}
        stk = {"key": "NSE:TCS", "market": "NSE", "symbol": "TCS", "qty": 10, "entry": 1000.0, "stop": 990.0,
               "target": 1020.0, "entry_fee": 5.0, "kind": "equity", "entry_date": "2026-11-12",
               "entry_time": "2026-11-12T05:00:00+00:00", "side": "long"}
        cash = 80000 + 300 - 900 - (60 * 250 + 25) - (10 * 1000 + 5)
        json.dump({"accounts": {"INDIA": {"cash": cash, "start_capital": 80000}}, "open": [opt, stk],
                   "closed": [{"market": "NSE", "symbol": "INFY", "pnl": 300.0, "exit_date": "2026-11-11"},
                              {"market": "NFO", "symbol": "BANKNIFTY-X-CE", "pnl": -900.0, "exit_date": "2026-11-11"}]},
                  open(P.LEDGER, "w"))

        cfg = P.load_config()
        india, fno = cfg["accounts"]["INDIA"], cfg["accounts"]["FNO"]
        check("1. config: INDIA stocks = Rs 50,000, FNO = Rs 1,00,000", india["capital"] == 50000 and fno["capital"] == 100000,
              (india["capital"], fno["capital"]))
        check("   FNO keeps INDIA's Scanner switches (v4, ticked setups, F&O max loss)",
              fno["scanner_version"] == "v4" and fno["v4_setups"] == ["v4_primary_long"]
              and fno["max_loss_per_trade_fno"] == 1200, fno)
        check("   F&O list = Nifty 50 + Bank Nifty, stock options off; the F&O keys leave INDIA",
              fno["fno_underlyings"] == ["NIFTY", "BANKNIFTY"] and fno["fno_stock_options"] is False
              and "fno_underlyings" not in india and "fno_stock_options" not in india, (fno, india))
        again = P.load_config()
        check("   one time only: a later change to FNO stays", again["accounts"]["FNO"] == fno)

        led = P.load_ledger(cfg)
        a, f = led["accounts"]["INDIA"], led["accounts"]["FNO"]
        check("2. ledger: FNO = 1,00,000 + the options' realised P&L - the open option's cost",
              abs(f["cash"] - (100000 - 900 - 15025)) < 1e-6 and f["start_capital"] == 100000, f)
        check("   INDIA = 50,000 + the stocks' P&L - the open stock's cost (the capital cut to 50,000 is a withdrawal)",
              abs(a["cash"] - (50000 + 300 - 10005)) < 1e-6 and a["start_capital"] == 50000, a)
        led2 = P.load_ledger(P.load_config())
        check("   the split happens once", led2["accounts"] == led["accounts"])
        check("3. NFO trades belong to FNO, NSE / BSE to INDIA",
              P.account_of("NFO") == "FNO" and P.account_of("NSE") == "INDIA" and P.account_of("BSE") == "INDIA")
        fee = P.charges(cfg, "NFO", "BANKNIFTY-20261124-52500-CE", "sell", 15000)
        check("   F&O still pays Indian option charges (STT etc.), not a fee_pct", fee > 20, fee)
        check("   F&O sizing uses the FNO account's limits", P.acct_cfg(cfg, "NFO")["max_loss_per_trade_fno"] == 1200)

        # auto_fno: Nifty 50 joins Bank Nifty once, even if an old config file listed Bank Nifty only
        import auto_fno as AF
        os.makedirs(AF.LIVE_DIR, exist_ok=True)
        json.dump({"v4_indices": ["BANKNIFTY"], "auto_buy": False}, open(AF.CFG_FILE, "w"))
        c = AF.load_cfg()
        check("4. auto_fno: v4 scans Nifty 50 and Bank Nifty (an old Bank-Nifty-only file is updated once)",
              c["v4_indices"] == ["NIFTY", "BANKNIFTY"] and json.load(open(AF.CFG_FILE))["_v4_nifty"], c["v4_indices"])
        mine = json.load(open(AF.CFG_FILE))
        mine["v4_indices"] = ["BANKNIFTY"]
        json.dump(mine, open(AF.CFG_FILE, "w"))
        check("   after that the owner's own choice stays", AF.load_cfg()["v4_indices"] == ["BANKNIFTY"])

        # a stock setup never becomes an option now (stock options off in FNO)
        import api._ops as O
        check("5. dashboard performance / downloads split NFO into FNO",
              O._acct("NFO") == "FNO" and O._acct("NSE") == "INDIA" and O._ACCT["NFO"] == "FNO")
        check("   F&O settings (F&O max loss: FNO and USFNO; stock options: FNO)",
              O.RISK_FIELDS["max_loss_per_trade_fno"]["accounts"] == ["FNO", "USFNO"] and O.MARKET_RULES["FNO"]["account"] == "FNO")
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)
