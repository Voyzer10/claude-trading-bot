#!/usr/bin/env python3
"""Scanner v2: finds the owner's setups on the candle that just closed, once, hands them to the agents, never trades.

    python tests/test_scanner_v2.py
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

import scanner_v2 as O  # noqa: E402
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
    import auto_crypto
    auto_crypto.headlines = lambda sym, n=3: []   # offline
    tmp = tempfile.mkdtemp()
    old = os.getcwd()
    os.chdir(tmp)
    try:
        rows = T.build([T.B, T.C, T.D])
        got = O.observe("CRYPTO", "TEST", rows, lambda t: t.date(), 5)
        check("A-B-C-D long seen on the D candle", any(o["setup"] == "abcd_long" for o in got), got)
        a = next((o for o in got if o["setup"] == "abcd_long"), {})
        check("   stop below C-low, 2R level, details", a.get("stop", 99) < 100.25 and a.get("target_2r")
              and a.get("details", {}).get("C_high") == 100.55, a)
        check("nothing on the candle before D", not [o for o in O.observe("CRYPTO", "TEST", rows[:-1], lambda t: t.date(), 5)
                                                     if o["setup"] == "abcd_long"])
        state = {}
        cutoff = rows[-1][0] + timedelta(minutes=5)
        first = O.crypto(state, {"TEST": chart(rows)}, 5, cutoff)
        again = O.crypto(state, {"TEST": chart(rows)}, 5, cutoff)
        check("recorded once (no duplicates on a rescan)", len([o for o in first if o["setup"] == "abcd_long"]) == 1
              and not again, (first, again))
        lines = [json.loads(x) for x in open(O.OBS_FILE)]
        check("written to scanner_v2.jsonl and state", lines and state.get("scanner_v2"))
        decs = [json.loads(x) for x in open(O.DECISIONS)]
        d = next((x for x in decs if x.get("setup") == "v2:abcd_long"), {})
        check("handed to the agents: decision with the setup name, through Exit (fees 0.26R stop it here)",
              d.get("result") in ("LOG ONLY", "skipped") and d["steps"]["1_scanner"]["setup_name"] == "A-B-C-D long"
              and "4_exit" in d["steps"], d)
        us = O.agents({"market": "US", "symbol": "MAR", "setup": "abcd_long", "side": "long", "bar_end": "x",
                       "price": 418.9, "stop": 416.2, "target_2r": 424.3, "details": {}})
        check("US setup passes the agents and is LOG ONLY (the broker does not trade it)",
              us["result"] == "LOG ONLY" and us["steps"]["6-8_budget_risk_broker"]["qty"] >= 1, us)
        # NSE path: today's 1-day charts + earlier days fetched ONCE in one batch
        calls = []

        def fetch_many(syms, rng, iv, workers, suffix, quiet):
            calls.append((tuple(syms), rng))
            return {s: chart(rows) for s in syms}, []
        import scan_nse as S
        O.nse({}, "NSE", {"ABC": chart(rows)}, cutoff, ".NS", fetch_many, S.IST)
        O.nse({}, "NSE", {"ABC": chart(rows)}, cutoff, ".NS", fetch_many, S.IST)
        check("NSE: earlier days fetched once a day", sum(1 for c in calls if c[1] == "5d") == 1, calls)
        check("no paper trade made (no ledger written)", not os.path.exists(os.path.join("trader", "paper", "ledger.json")))
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED" % len(FAILS)))
    sys.exit(1 if FAILS else 0)
