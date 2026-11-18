#!/usr/bin/env python3
"""setup_decision's size check uses the same intraday margin as the paper buy (offline).

Since the 17 Nov budget the US account is $1,000 with 4x intraday margin. A $500 stock: without the margin the
check computed 1,000 x 25% / 500 = 0.5 shares -> "0 units fit" and skipped it, while paper.py's own buy (margin)
sizes 2 shares. The check must agree with the buy.

    python tests/test_setup_sizing.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

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
        cfg = P.load_config()
        cfg["accounts"]["US"]["scanner_version"] = "v3"   # a v3 setup: no v4 chart bookkeeping needed here
        P.save_json(P.CONFIG, cfg)
        P.session = lambda m, utc: "open"                 # any time of day
        P.past_flat_by = lambda m, acc, utc: False
        P.fetch_price = lambda m, t: (500.0, datetime.now(timezone.utc))
        setup = {"setup": "v3_sweep_long", "name": "sweep reversal long", "side": "long", "price": 500.0,
                 "stop": 495.0, "target": 515.0, "liquidity": "test"}
        rec = P.setup_decision("US", "MSFT", setup, news=[])
        check("a $500 stock in the $1,000 US account (4x margin) is not skipped as '0 units fit'",
              "0 units fit" not in (rec.get("why") or ""), (rec["result"], rec.get("why")))
        check("   it is paper bought, sized by the buy itself",
              rec["result"] == "PAPER BUY" and rec["steps"]["6-8_budget_risk_broker"]["qty"] >= 1,
              (rec["result"], rec.get("why")))
        cfg = P.load_config()
        cfg["accounts"]["US"]["intraday_leverage"] = 1     # no margin: then one share really does not fit
        P.save_json(P.CONFIG, cfg)
        rec = P.setup_decision("US", "MSFT2", dict(setup), news=[])
        check("   without margin (leverage 1) it is still skipped: 0 units fit",
              rec["result"] == "skipped" and "0 units fit" in rec["why"], (rec["result"], rec.get("why")))
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
