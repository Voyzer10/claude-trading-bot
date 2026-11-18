#!/usr/bin/env python3
"""The owner's budget of 17 Nov 2026 and the P&L since the reset. Offline.

  1. The defaults: Rs 1 lakh for INDIA / FNO, $1,000 for US / crypto, $1,200 for US options; max loss per trade
     (stocks and F&O) 3%, daily loss limit 9%. (The one-time change of an older config ran on the VPS on 17 Nov and
     was removed on 18 Nov 2026.)
  2. A Bank Nifty lot (risk ~Rs 2,600) fits the FNO account's max loss per trade.
  3. The dashboard's P&L counts only the trades closed after each book's budget reset (the ledger's "budget_reset"
     note); older trades stay in the ledger as history.
  4. A capital change in Settings is a top-up / withdrawal of the difference: the P&L is kept.

    python tests/test_budget.py
"""
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
        a = P.load_config()["accounts"]
        want = {"INDIA": 100000, "FNO": 100000, "US": 1000, "USFNO": 1200, "CRYPTO": 1000}
        check("1. budgets: INDIA / FNO Rs 1 lakh, US / crypto $1,000, US options $1,200",
              {k: a[k]["capital"] for k in want} == want, {k: a[k]["capital"] for k in want})
        check("   max loss per trade 3% (stocks and F&O), daily loss limit 9%",
              all(a[k]["max_loss_per_trade"] == round(v * 0.03, 2) and a[k]["daily_loss_limit"] == round(v * 0.09, 2)
                  for k, v in want.items())
              and a["FNO"]["max_loss_per_trade_fno"] == 3000 and a["USFNO"]["max_loss_per_trade_fno"] == 36,
              {k: (a[k]["max_loss_per_trade"], a[k].get("max_loss_per_trade_fno"), a[k]["daily_loss_limit"]) for k in want})

        lot_risk = 30 * (300.0 - 213.7)            # one Bank Nifty lot, premium 300 -> stop 213.7 = Rs 2,589
        check("2. a Bank Nifty lot (risk Rs %.0f) fits the FNO max loss per trade (Rs %s)" % (lot_risk,
              a["FNO"]["max_loss_per_trade_fno"]), lot_risk <= a["FNO"]["max_loss_per_trade_fno"])

        # 3. the dashboard's P&L after the reset (a VPS ledger carries each book's budget_reset note)
        led = P.load_ledger(P.load_config())
        at = "2026-11-17T12:00:00+00:00"
        for name in led["accounts"]:
            led["accounts"][name]["budget_reset"] = {"at": at}
        led["closed"] = [{"key": "US:MSFT", "market": "US", "pnl": 1288.21, "r": 1.2, "exit_time": "2026-11-16T20:00:00+00:00",
                          "exit_date": "2026-11-16"},
                         {"key": "US:AAPL", "market": "US", "pnl": -12.5, "r": -0.4, "exit_time": "2099-01-01T00:00:00+00:00",
                          "exit_date": "2099-01-01"}]
        P.save_json(P.LEDGER, led)
        import api._ops as O
        O.LEDGER, O.PREFS = os.path.abspath(P.LEDGER), os.path.join(tmp, "prefs.json")
        perf = O.performance()
        check("3. dashboard P&L: only trades after the reset count; every account shows (from zero)",
              perf["accounts"]["US"]["trades"] == 1 and perf["accounts"]["US"]["pnl"] == -12.5
              and perf["accounts"]["INDIA"]["trades"] == 0 and perf["history_trades"] == 1 and perf["since"], perf["accounts"])

        # 4. capital raised in Settings: the difference is added, the P&L kept
        led = P.load_ledger(P.load_config())
        led["accounts"]["US"]["cash"] = 987.5           # $12.50 lost since the reset
        P.save_json(P.LEDGER, led)
        cfg = P.load_config()
        cfg["accounts"]["US"]["capital"] = 1500
        P.save_json(P.CONFIG, cfg)
        b = P.load_ledger(P.load_config())["accounts"]["US"]
        check("4. capital 1,000 -> 1,500 in Settings: cash +500, the loss kept", b["cash"] == 1487.5 and b["start_capital"] == 1500,
              b)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("%d check(s) failed" % len(FAILS))
        sys.exit(1)
    print("all checks passed")
