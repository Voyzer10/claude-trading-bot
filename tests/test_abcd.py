#!/usr/bin/env python3
"""The A-B-C-D entry (abcd.py) against the acceptance tests in the owner's PDF (offline).

    python tests/test_abcd.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import abcd as A  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": " + str(extra)) if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


def build(tail):
    """Base with a swing high at 100.6, then A, a pullback swing low at 100.6, then `tail` candles (o, h, l, c)."""
    t, rows = [datetime(2026, 11, 3, tzinfo=timezone.utc)], []

    def add(o, h, l, c):
        rows.append((t[0], o, h, l, c, 100))
        t[0] += timedelta(minutes=5)
    for k in range(40):
        b = 100 + (0.4 if (k // 3) % 2 else 0.0)
        add(b, b + 0.2, b - 0.2, b + 0.05)
    for c in [(100.4, 101.4, 100.3, 101.3),      # A: closes above the 100.6 swing high
              (101.3, 101.6, 101.0, 101.5), (101.5, 101.6, 100.9, 101.0),
              (101.0, 101.1, 100.6, 100.7),      # pullback low 100.6 = the first swing low
              (100.7, 101.2, 100.65, 101.1), (101.1, 101.5, 101.0, 101.4), (101.4, 101.5, 101.0, 101.1)]:
        add(*c)
    for c in tail:
        add(*c)
    return rows


B = (101.1, 101.2, 100.3, 100.4)        # red, trades below 100.6 and closes below it
C = (100.40, 100.55, 100.25, 100.42)    # green doji (body 7% of the range), high 100.55
D = (100.42, 100.7, 100.40, 100.65)     # closes 100.65 > 100.55
D_WICK = (100.42, 100.7, 100.40, 100.50)  # trades above C-high, closes below it


def sigs(rows, short=False):
    return A.signals(rows, lambda x: x.date(), short=short)[1]


if __name__ == "__main__":
    check("1. A only: no order", not sigs(build([])))
    check("2. A then B: no order", not sigs(build([B])))
    check("3. A, B, C: no order", not sigs(build([B, C])))
    check("4. D wick above C-high, close below: no order", not sigs(build([B, C, D_WICK])))
    got = sigs(build([B, C, D]))
    check("5. D closes above C-high: one buy", len(got) == 1 and got[0]["side"] == "long", got)
    if got:
        g = got[0]
        check("   C-high / C-low / swing level stored", (g["c_high"], g["c_low"], g["b_level"]) == (100.55, 100.25, 100.6), g)
        check("   stop below C-low", A.stop_for(g, "c_low") < 100.25)
        check("   2R target", abs(A.target_for(None, g, "2R", 100.0) - (100.65 + 2 * 0.65)) < 1e-9)
    more = sigs(build([B, C, D, (100.65, 100.9, 100.6, 100.85), (100.85, 101.0, 100.8, 100.95)]))
    check("6. later candles: still one buy (no duplicates)", len(more) == 1, more)
    dead = sigs(build([B, C, (100.4, 100.45, 100.0, 100.1)] + [(100.1, 100.15, 99.9, 99.95)] * 6 + [D]))
    check("7. close below C-low and the window runs out: no order", not dead, dead)
    red_doji = sigs(build([B, (100.42, 100.55, 100.25, 100.40), D]))
    check("   a RED doji is not a C", not red_doji, red_doji)
    sh = sigs(A.mirror(build([B, C, D])), short=True)
    check("mirror: the same picture upside down is one short", len(sh) == 1 and sh[0]["side"] == "short", sh)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
