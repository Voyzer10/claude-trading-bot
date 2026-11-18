#!/usr/bin/env python3
"""Scanner v4 live: with NO v4 trade open in the paper ledger, the last candle's trigger is offered even when the
chart's simulation still holds a trade there (one paper never opened, e.g. the buy was blocked by cash, a cooldown or
0 units). Before 18 Nov 2026 such a phantom trade hid every later trigger on that chart until it exited. Offline.

    python tests/test_v4_flat_ledger.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def pending(seq, last):
    return [(t["i"], t["side"], t["kind"]) for t in seq if t.get("pending") and t["i"] == last]


if __name__ == "__main__":
    import scanner_v4 as V4
    from test_v4_flip import walk, day_of

    flat = {"open": [], "closed": []}
    rescued, same_when_free, wrong = 0, 0, []
    for seed in range(3):
        rows = walk(10, seed)
        for k in range(200, len(rows), 5):
            pre = rows[:k + 1]
            # flip / latest-BOS off: a trigger while the simulation holds a trade is otherwise dropped
            opts = {"flip_same_day": False, "latest_bos": False}
            full = V4.sequence(pre, day_of, intraday=True, **opts)
            sim_open = any(t.get("exit_reason") == "open" and not t.get("pending") for t in full)
            old = pending(full, k)
            new = pending(V4.live_candidate(pre, day_of, flat, "NSE:TST", intraday=True, **opts), k)
            if not sim_open:
                same_when_free += 1
                if new != old:
                    wrong.append((seed, k, old, new))
            elif new and not old:
                rescued += 1
    check("simulation holds no trade: the flat ledger changes nothing", not wrong and same_when_free > 0,
          (same_when_free, wrong[:3]))
    print("    (%d candles with no simulated trade, %d triggers rescued)" % (same_when_free, rescued))
    check("simulation holds a trade paper never took: the last candle's trigger is offered", rescued > 0, rescued)

    # a REAL open v4 trade in the ledger still blocks: live_candidate returns every trigger for paper to decide on,
    # and paper.setup_decision skips one without the flip / latest-BOS mark (test_v4_flip covers that path)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
