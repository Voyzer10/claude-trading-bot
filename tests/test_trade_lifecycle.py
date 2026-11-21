#!/usr/bin/env python3
"""research_trade_lifecycle_v4 (21 Nov 2026): MFE / MAE from the trade's own candles (long and mirrored short;
stop, target and close exits), the Trade Manager re-run, and the R reconciliation. Offline.

    python tests/test_trade_lifecycle.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import research_trade_lifecycle_v4 as LC  # noqa: E402
import scanner_v4 as V4  # noqa: E402
from test_choch_lifecycle import rows_of, reflect  # noqa: E402
from test_entry_models import RETEST  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def bars(hl):
    t0 = datetime(2026, 1, 5, 4, 0, tzinfo=timezone.utc)
    return [(t0 + timedelta(minutes=5 * i), (h + l) / 2, h, l, (h + l) / 2, 1) for i, (h, l) in enumerate(hl)]


if __name__ == "__main__":
    # long: entry 100, risk 1 (stop 99), target 102; candles 0..3 open, exit candle 3
    b = bars([(100.4, 99.8), (101.2, 99.6), (101.5, 100.1), (103.0, 98.0)])
    check("long, stop exit: MFE from the open candles only (+1.5R), MAE = the exit price (99 -> 1.0R)",
          LC.excursions(b, 0, 3, 100.0, 1.0, "stop", 99.0, 102.0) == (1.5, 1.0))
    check("long, target exit: MFE = the target (+2.0R), MAE from the open candles only (0.4R)",
          tuple(round(x, 9) for x in LC.excursions(b, 0, 3, 100.0, 1.0, "target", 102.0, 102.0)) == (2.0, 0.4))
    check("long, day-end exit: the whole exit candle counts (MFE +3.0R, MAE 2.0R)",
          LC.excursions(b, 0, 3, 100.0, 1.0, "day end", 100.5, 102.0) == (3.0, 2.0))
    m = V4.mirror(b)
    got = tuple(round(x, 9) for x in LC.excursions(m, 0, 3, -100.0, 1.0, "stop", -101.0, -98.0))
    check("short (mirrored candles): the same arithmetic gives MFE / MAE in R against the short", got == (0.4, 1.5), got)
    check("a breakeven / trailing stop exit is a stop-type exit (its price is the adverse extreme)",
          tuple(round(x, 9) for x in LC.excursions(b, 0, 3, 100.0, 1.0, "breakeven stop", 100.0, 102.0)) == (1.5, 0.4))
    # the full chain on the hand-built chart (crypto key: no session), long and mirrored short
    for tag in ("bull", "bear"):
        rows = rows_of(RETEST)
        if tag == "bear":
            rows = reflect(rows)
        sym, out = LC.chart(("crypto", "TEST", rows, {}))
        check("%s: one closed E1 trade; the Trade Manager re-run gives the recorded exit; gross R reconciles; TM MFE "
              "= the candle MFE; net = gross - cost" % tag,
              len(out) == 1 and out[0]["tm_ok"] and abs(out[0]["gross"] - out[0]["gross_rec"]) < 1e-9
              and abs(out[0]["tm_mfe"] - out[0]["tm_mfe_mine"]) < 1e-9
              and abs(out[0]["net"] - (out[0]["gross"] - out[0]["cost"])) < 1e-12, out)
        if out:
            r = out[0]
            risk = r["stop_dist"]
            check("%s: entry 58's open, stopped on 61; MFE = (105.4 - 104.5) / risk, MAE = 1.0R; bars held 4" % tag,
                  r["exit_reason"] == "stop" and abs(r["mfe"] - 0.9 / risk) < 1e-9 and abs(r["mae"] - 1.0) < 1e-9
                  and r["bars"] == 4 and r["side"] == ("short" if tag == "bear" else "long")
                  and r["entry"] == (104.5 if tag == "bull" else 210 - 104.5), r)
    print("\n%d failed" % len(FAILS) if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
