#!/usr/bin/env python3
"""smc_playbook.v4_setups, the bridge from the live scan to Scanner v4 (offline):
  - the chart's simulation gets the ACCOUNT's Trade Manager (as the backtest and the paper trades), not the defaults;
  - an index chart uses the FNO account's settings (paper.setup_account), like setup_decision;
  - a scanner error is printed (journalctl shows it), not hidden.

    python tests/test_v4_bridge.py
"""
import contextlib
import io
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
        import scanner_v4 as V4
        import smc_playbook as PB
        cfg = P.load_config()
        cfg["accounts"]["CRYPTO"].update(tm_trail=False, tm_be_r=0.5)
        cfg["accounts"]["FNO"].update(tm_be_r=2.0)
        P.save_json(P.CONFIG, cfg)
        seen = {}
        real = V4.live_candidate
        V4.live_candidate = lambda rows, day_of, ledger, chart, intraday=False, **kw: seen.update({chart: kw}) or []
        PB.v4_setups([], None, 0, ledger={"open": [], "closed": []}, chart="CRYPTO:BTC")
        PB.v4_setups([], None, 0, intraday=True, ledger={"open": [], "closed": []}, chart="NSE:NIFTY")
        kw = seen.get("CRYPTO:BTC") or {}
        check("crypto chart: the CRYPTO account's Trade Manager reaches the simulation",
              kw.get("tm_trail") is False and kw.get("tm_be_r") == 0.5, kw)
        check("index chart: the FNO account's (the account that trades it)",
              (seen.get("NSE:NIFTY") or {}).get("tm_be_r") == 2.0, seen.get("NSE:NIFTY"))

        def broken(*a, **k):
            raise IndexError("list index out of range")
        V4.live_candidate = broken
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = PB.v4_setups([], None, 0, ledger={"open": [], "closed": []}, chart="US:AAPL")
        check("a scanner error: no setups, and it is printed (not hidden)",
              out == [] and "Scanner v4 failed on US:AAPL" in buf.getvalue(), buf.getvalue())
        V4.live_candidate = real

        # QQQ / SPY / DIA are decided by USFNO: the scanner must look for USFNO's version on those charts
        cfg = P.load_config()
        cfg["accounts"]["US"]["scanner_version"], cfg["accounts"]["USFNO"]["scanner_version"] = "v3", "v4"
        P.save_json(P.CONFIG, cfg)
        check("scanner_version per chart: QQQ -> USFNO's v4, AAPL -> US's v3, no symbol -> US's v3",
              PB.scanner_version("US", "QQQ") == "v4" and PB.scanner_version("US", "AAPL") == "v3"
              and PB.scanner_version("US") == "v3")
        import scan_nse as S
        asked = {}
        S.earlier_days = lambda syms, suffix, today, tz, workers, keep: {x: [] for x in syms}
        S.chart_rows = lambda d, tz: d
        PB.owner_setups = lambda rows, day_of, version="v3", **k: asked.update({k.get("symbol"): version}) or []
        from datetime import datetime, timedelta, timezone
        t = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
        S.setups_scan({"QQQ": [(t, 1, 1, 1, 1, 1)], "AAPL": [(t, 1, 1, 1, 1, 1)]}, "US", "", t + timedelta(minutes=10),
                      timezone.utc)
        check("the US scan asks each chart for its own version", asked == {"QQQ": "v4", "AAPL": "v3"}, asked)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
