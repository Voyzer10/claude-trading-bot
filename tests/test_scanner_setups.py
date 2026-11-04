#!/usr/bin/env python3
"""Scanner v2: the scanner finds the owner's setups on the candle that just closed and the agents take them on
(paper trade while testing, or record when trade_setups is off). Offline.

    python tests/test_scanner_setups.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import smc_playbook as PB  # noqa: E402
import test_abcd as T  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def chart(rows):
    return {"t": [int(r[0].timestamp()) for r in rows], "o": [r[1] for r in rows], "h": [r[2] for r in rows],
            "l": [r[3] for r in rows], "c": [r[4] for r in rows], "v": [r[5] for r in rows]}


if __name__ == "__main__":
    rows = T.build([T.B, T.C, T.D])
    got = PB.owner_setups(rows, lambda t: t.date())
    a = next((o for o in got if o["setup"] == "abcd_long"), {})
    check("owner_setups: A-B-C-D long on the D candle", bool(a), got)
    check("   name, stop below C-low, 2R, details", a.get("name") == "A-B-C-D long" and a.get("stop", 99) < 100.25
          and a.get("target_2r") and a.get("details", {}).get("C_high") == 100.55, a)
    check("   nothing on the candle before D",
          not [o for o in PB.owner_setups(rows[:-1], lambda t: t.date()) if o["setup"] == "abcd_long"])

    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        cfg = P.load_config()
        cfg["accounts"]["US"]["trade_setups"] = False
        P.save_json(P.CONFIG, cfg)
        rec = P.setup_decision("US", "MAR", dict(a, price=418.9, stop=416.2, target_2r=424.3))
        check("agents: trade_setups off -> a US setup passes and is only recorded (LOG ONLY)",
              rec["result"] == "LOG ONLY" and rec["scanner_v2"] and rec["steps"]["6-8_budget_risk_broker"]["qty"] >= 1, rec)
        P.fetch_price = lambda m, t: ({"CRYPTO": 50.0}.get(m, 418.9), None)
        crypto_ok = dict(a, price=50.0, stop=49.0, target_2r=52.0, name="A-B-C-D long", setup="abcd_long")
        trec = P.setup_decision("CRYPTO", "TST", crypto_ok, news=[])
        led = P.load_ledger(P.load_config())
        check("paper testing (trade_setups on): the setup is paper traded with its stop and 2R target",
              trec["result"] == "PAPER BUY" and any(p["key"] == "CRYPTO:TST" and p["stop"] == 49.0 and p["target"] == 52.0
                                                     for p in led["open"]), trec)
        crec = P.setup_decision("CRYPTO", "TEST", a, news=[])
        check("agents: crypto setup stopped by Exit when fees > 0.25R (here 0.26R)",
              crec["result"] == "skipped" and "fees eat" in crec["why"], crec)
        # the crypto agent path: scanner result -> auto_crypto.process records it, places no trade
        import auto_crypto as AC
        AC.headlines = lambda sym, n=3: []
        AC.process({}, {"hits": [], "setups": [dict(a, symbol="TEST", market="CRYPTO", bar_end="x")]}, lambda *_: None)
        decs = [json.loads(x) for x in open(AC.DECISIONS)]
        check("auto_crypto takes the setup through the agents with its name",
              any(d.get("setup") == "abcd_long" and d.get("scanner_v2") for d in decs), decs)
        # NSE: setups_scan joins earlier days fetched ONCE a day in one batch
        import scan_nse as S
        calls = []

        def fake_many(syms, rng, iv, workers, suffix=".NS", quiet=False, fetcher=None):
            calls.append(rng)
            return {s: chart(rows) for s in syms}, []
        S.fetch_many = fake_many
        cutoff = rows[-1][0] + timedelta(minutes=5)
        today_chart = {"ABC": chart(rows)}
        s1 = S.setups_scan(today_chart, "NSE", ".NS", cutoff, S.IST)
        S.setups_scan(today_chart, "NSE", ".NS", cutoff, S.IST)
        check("NSE: earlier days fetched once a day", calls.count("5d") == 1, calls)
        check("NSE: setups carry symbol / market / candle end", all(x.get("symbol") == "ABC" and x.get("market") == "NSE"
                                                                    and x.get("bar_end") for x in s1), s1)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED" % len(FAILS)))
    sys.exit(1 if FAILS else 0)
