#!/usr/bin/env python3
"""The owner's budget of 17 Nov 2026, applied once. Offline.

  1. An existing config (old limits) gets Rs 1 lakh for INDIA / FNO, $1,000 for US / crypto, $1,200 for US options;
     max loss per trade (stocks and F&O) 3%, daily loss limit 9%. A second load changes nothing; a later edit in
     Settings is kept.
  2. The ledger: every book restarts at its budget, minus what open positions tie up (margin or entry value); the
     closed trades stay; it runs once; the old cash is noted.
  3. A Bank Nifty lot (risk ~Rs 2,600) now fits the FNO account's max loss per trade.

    python tests/test_budget.py
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
        os.makedirs(os.path.dirname(P.CONFIG), exist_ok=True)
        # an existing install before 17 Nov: the old budgets and limits, no _budget_1117 flag
        cfg0 = json.loads(json.dumps(P.DEFAULT_CONFIG))
        olds = {"INDIA": (50000, 500, 1500, 2500), "FNO": (100000, 1500, 1500, 5000), "US": (50000, 50, None, 150),
               "USFNO": (50000, 500, 500, 1500), "CRYPTO": (1000, 10, None, 30)}
        for name, (cap, ml, mlf, dl) in olds.items():
            a = cfg0["accounts"][name]
            a.update(capital=cap, max_loss_per_trade=ml, daily_loss_limit=dl)
            if mlf is not None:
                a["max_loss_per_trade_fno"] = mlf
        cfg0["_tm_global"] = True
        cfg0.pop("_budget_1117", None)
        P.save_json(P.CONFIG, cfg0)
        led0 = {"accounts": {"INDIA": {"cash": 47427.96, "start_capital": 50000.0},
                             "FNO": {"cash": 101397.2, "start_capital": 100000.0},
                             "US": {"cash": 51288.21, "start_capital": 50000.0},
                             "USFNO": {"cash": 50472.49, "start_capital": 50000.0},
                             "CRYPTO": {"cash": 331.77, "start_capital": 1000.0}},
                "open": [{"key": "CRYPTO:HYPE", "market": "CRYPTO", "symbol": "HYPE", "side": "long", "qty": 10.0,
                          "entry": 40.0, "stop": 39.0, "target": 42.0, "entry_fee": 0.4},
                         {"key": "US:AAPL", "market": "US", "symbol": "AAPL", "side": "long", "qty": 4.0, "entry": 200.0,
                          "stop": 199.0, "target": 202.0, "margin": 200.0, "leverage": 4}],
                "closed": [{"key": "US:MSFT", "market": "US", "pnl": 1288.21, "r": 1.2},
                           {"key": "NSE:TCS", "market": "NSE", "pnl": -2572.04, "r": -1.0}]}
        P.save_json(P.LEDGER, led0)

        cfg = P.load_config()
        a = cfg["accounts"]
        want = {"INDIA": 100000, "FNO": 100000, "US": 1000, "USFNO": 1200, "CRYPTO": 1000}
        check("1. budgets: INDIA / FNO Rs 1 lakh, US / crypto $1,000, US options $1,200",
              {k: a[k]["capital"] for k in want} == want, {k: a[k]["capital"] for k in want})
        check("   max loss per trade 3% (stocks and F&O), daily loss limit 9%",
              all(a[k]["max_loss_per_trade"] == round(v * 0.03, 2) and a[k]["daily_loss_limit"] == round(v * 0.09, 2)
                  for k, v in want.items())
              and a["FNO"]["max_loss_per_trade_fno"] == 3000 and a["USFNO"]["max_loss_per_trade_fno"] == 36,
              {k: (a[k]["max_loss_per_trade"], a[k].get("max_loss_per_trade_fno"), a[k]["daily_loss_limit"]) for k in want})
        a["US"]["max_loss_per_trade"] = 25        # the owner edits it later in Settings
        P.save_json(P.CONFIG, cfg)
        check("   applied once: a later Settings edit is kept", P.load_config()["accounts"]["US"]["max_loss_per_trade"] == 25)

        led = P.load_ledger(P.load_config())
        b = led["accounts"]
        check("2. every book restarts at its budget (old P&L gone from the cash)",
              b["INDIA"]["cash"] == 100000 and b["FNO"]["cash"] == 100000 and b["USFNO"]["cash"] == 1200
              and all(b[k]["start_capital"] == v for k, v in want.items()), {k: b[k]["cash"] for k in b})
        check("   minus what open positions tie up: crypto 10 x $40 = $400, US margin $200",
              b["CRYPTO"]["cash"] == 600 and b["US"]["cash"] == 800, (b["CRYPTO"]["cash"], b["US"]["cash"]))
        check("   open positions and closed trades stay in the ledger (history)",
              len(led["open"]) == 2 and len(led["closed"]) == 2)
        check("   the old cash is noted", b["US"]["budget_reset"]["old_cash"] == 51288.21 and led.get("_budget_1117"))
        led["accounts"]["US"]["cash"] = 777.0
        P.save_json(P.LEDGER, led)
        check("   it runs once (later cash moves are not reset again)",
              P.load_ledger(P.load_config())["accounts"]["US"]["cash"] == 777.0)

        fno = P.load_config()["accounts"]["FNO"]
        lot_risk = 30 * (300.0 - 213.7)            # one Bank Nifty lot, premium 300 -> stop 213.7 = Rs 2,589
        check("3. a Bank Nifty lot (risk Rs %.0f) fits the FNO max loss per trade (Rs %s)" % (lot_risk,
              fno["max_loss_per_trade_fno"]), lot_risk <= fno["max_loss_per_trade_fno"])
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("%d check(s) failed" % len(FAILS))
        sys.exit(1)
    print("all checks passed")
