#!/usr/bin/env python3
"""F&O in its own paper account (owner, 12 Nov 2026): INDIA = NSE / BSE stocks (Rs 50,000), FNO = NFO (Rs 1,00,000),
F&O only on Nifty 50 and Bank Nifty. Offline. (The one-time split of an older shared INDIA account ran on the VPS
and was removed on 18 Nov 2026.)

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
        import _old_budget
        _old_budget.apply(P)   # written against the pre-17-Nov budgets
        cfg = P.load_config()
        india, fno = cfg["accounts"]["INDIA"], cfg["accounts"]["FNO"]
        check("1. config: INDIA (stocks) and FNO (F&O) are separate accounts",
              india["capital"] == 50000 and fno["capital"] == 100000, (india["capital"], fno["capital"]))
        check("   F&O list = Nifty 50 + Bank Nifty, stock options off; the F&O keys live in FNO only",
              fno["fno_underlyings"] == ["NIFTY", "BANKNIFTY"] and fno["fno_stock_options"] is False
              and "fno_underlyings" not in india and "fno_stock_options" not in india, (fno, india))
        led = P.load_ledger(cfg)
        check("2. ledger: one book each, at its capital",
              led["accounts"]["INDIA"]["cash"] == 50000 and led["accounts"]["FNO"]["cash"] == 100000, led["accounts"])
        check("3. NFO trades belong to FNO, NSE / BSE to INDIA",
              P.account_of("NFO") == "FNO" and P.account_of("NSE") == "INDIA" and P.account_of("BSE") == "INDIA")
        fee = P.charges(cfg, "NFO", "BANKNIFTY-20261124-52500-CE", "sell", 15000)
        check("   F&O still pays Indian option charges (STT etc.), not a fee_pct", fee > 20, fee)
        check("   F&O sizing uses the FNO account's limits", P.acct_cfg(cfg, "NFO") is cfg["accounts"]["FNO"])

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
