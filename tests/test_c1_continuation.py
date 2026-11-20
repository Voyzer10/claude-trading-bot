#!/usr/bin/env python3
"""Candidate 1 (research id entry_rule="c1_continuation", 21 Nov 2026): fresh BOS -> pullback -> continuation BOS.
The trend must start with a CHoCH; its first BOS (BOS1) is not an entry; the next same-side BOS after a pullback that
held BOS1's protected level by close (BOS2) is the entry signal; fill at the next open; stop = BOS2's protected level
-/+ 0.1 ATR. Structure only from legs(). Offline.

    python tests/test_c1_continuation.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import scanner_v4 as V4  # noqa: E402
from test_choch_lifecycle import base, rows_of, reflect, walk  # noqa: E402

FAILS = []
C1 = {"entry_rule": "c1_continuation", "choch_invalidate": True}


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


HEAD = base() + [(103.8, 105.6, 103.7, 105.4),                                   # 47 long BOS (old structure)
                 (105.4, 105.5, 100.9, 101.0),                                   # 48 bearish CHoCH
                 (101.0, 101.2, 100.2, 100.3), (100.3, 100.4, 99.6, 99.7),       # 49-50 first down leg (low 99.6)
                 (99.7, 100.6, 99.65, 100.5), (100.5, 100.9, 100.3, 100.8),      # 51-52 pullback (LH 100.9)
                 (100.8, 100.85, 99.2, 99.3),                                    # 53 BOS1 (close < 99.6), not entry
                 (99.3, 99.4, 98.8, 98.9),                                       # 54 leg low 98.8
                 (98.9, 99.5, 98.85, 99.4), (99.4, 99.7, 99.2, 99.6)]            # 55-56 pullback (holds < 100.9)
SEQ = HEAD + [(99.6, 99.6, 98.4, 98.5),                                          # 57 BOS2: close < 98.8 -> entry signal
              (98.45, 98.6, 98.0, 98.1), (98.1, 98.2, 97.8, 97.9)]               # 58 fill at its open; 59
WICK = HEAD + [(99.6, 99.6, 98.6, 98.85), (98.85, 99.0, 98.82, 98.9), (98.9, 99.0, 98.85, 98.95)]   # wick only
EQUAL = HEAD + [(99.6, 99.6, 98.7, 98.8), (98.8, 99.0, 98.75, 98.9), (98.9, 99.0, 98.85, 98.95)]    # close == 98.8
# BOS2 at 57, then another pullback and a third BOS (BOS3 at 62): only BOS2 is an entry
BOS3 = SEQ + [(97.9, 98.3, 97.85, 98.2), (98.2, 98.5, 98.1, 98.4), (98.4, 98.45, 97.5, 97.6)]


def trades(rows, **kw):
    return V4.sequence(rows, lambda t: t.date(), intraday=False, **dict(C1, **kw))


def scenario(tag, rows, s):
    side = "long" if s == 0 else "short"
    cx = V4.contexts(rows, lambda t: t.date(), False, k=3)
    ctx = cx["ctx"][s]
    lg = V4.legs(rows)
    run = ctx.c1.get(57)
    check("%s legs: BOS1 53, BOS2 57 (%s), CHoCH 48 starts the run, pullback starts at 55" % (tag, side),
          lg.get(53, ("",))[0] == side and lg.get(57, ("",))[0] == side and run is not None
          and (run["choch"], run["bos1"], run["pull"], run["bos2"]) == (48, 53, 55, 57), (run, sorted(lg)[-3:]))
    out = trades(rows)
    check("%s exactly one entry, on BOS2 (candle 57); none on the CHoCH (48) or BOS1 (53)" % tag,
          [(t["side"], t["i"]) for t in out] == [(side, 57)], [(t["side"], t["i"]) for t in out])
    if not out:
        return
    t = out[0]
    check("%s next-candle-open fill: entry = candle 58's open" % tag, abs(t["entry"] - rows[58][1]) < 1e-9,
          (t["entry"], rows[58][1]))
    a = ctx.atr[57]
    sg = 1 if s == 0 else -1
    want_stop = sg * (ctx.legs[57][1] - 0.1 * a)        # BOS2's protected level (src terms) - 0.1 ATR, back to real
    check("%s stop = BOS2's protected %s %s 0.1 ATR (%.4f)" % (tag, "HL" if s == 0 else "LH", "-" if s == 0 else "+",
                                                                want_stop),
          abs(t["stop"] - want_stop) < 1e-9 and abs(sg * ctx.legs[57][1] - (99.7 if s == 1 else 210 - 99.7)) < 1e-9,
          (t["stop"], want_stop))
    check("%s trade carries its run (CHoCH 48, BOS1 53, pullback 55)" % tag,
          (t.get("c1_choch"), t.get("c1_bos1"), t.get("c1_pull"), t.get("entry_rule")) == (48, 53, 55, "c1_continuation"))
    check("%s no OB / FVG secondaries in this entry model" % tag, all(x["kind"] == "primary" for x in out))


def rejections(tag, rows, s, what):
    out = trades(rows)
    lg = V4.legs(rows)
    check("%s %s is no BOS (legs) and no entry" % (tag, what), 57 not in lg and not out, (sorted(lg)[-2:], out))


def no_duplicate(tag, rows, s):
    side = "long" if s == 0 else "short"
    lg = V4.legs(rows)
    out = trades(rows)
    check("%s precondition: BOS3 at 62 (%s)" % (tag, side), lg.get(62, ("",))[0] == side, sorted(lg)[-3:])
    check("%s one run, one entry: BOS3 and the further closes beyond the level are not entries" % tag,
          [t["i"] for t in out] == [57], [t["i"] for t in out])
    check("%s no duplicate BOS: legs has no event at 58-61" % tag, not any(j in lg for j in range(58, 62)))


def walk_checks(tag, rows):
    day_of = lambda t: t.date()                       # noqa: E731
    cx = V4.contexts(rows, day_of, False, k=3)
    lg = V4.legs(rows)
    out = [t for t in V4.sequence(rows, day_of, intraday=True, ctxs=cx, **C1) if t.get("exit_reason") != "open"
           or t.get("pending")]
    full = [t for t in out if not t.get("pending")]
    check("%s has entries (%d)" % (tag, len(full)), len(full) >= 5)
    ok_sig = ok_fill = ok_stop = ok_run = 0
    for t in full:
        s = 0 if t["side"] == "long" else 1
        ctx, sg = cx["ctx"][s], (1 if s == 0 else -1)
        ok_sig += t["i"] in ctx.c1 and lg.get(t["i"], ("",))[0] == t["side"]
        ok_fill += abs(t["entry"] - rows[t["i"] + 1][1]) < 1e-9
        ok_stop += abs(t["stop"] - sg * (ctx.legs[t["i"]][1] - 0.1 * ctx.atr[t["i"]])) < 1e-9
        r = ctx.c1[t["i"]] if t["i"] in ctx.c1 else None
        ok_run += bool(r and r["choch"] < r["bos1"] < r["pull"] < t["i"] and lg[r["bos1"]][0] == t["side"]
                       and not any(r["choch"] < x <= t["i"] for x in ctx.choch_against))
    n = len(full)
    check("%s every entry is on a BOS2 of its side (no entry before BOS2)" % tag, ok_sig == n, (ok_sig, n))
    check("%s every fill = the next candle's open" % tag, ok_fill == n, (ok_fill, n))
    check("%s every stop = BOS2 protected -/+ 0.1 x ATR(14) of the BOS2 candle" % tag, ok_stop == n, (ok_stop, n))
    check("%s every run: CHoCH < BOS1 < pullback < BOS2, no CHoCH against it in between" % tag, ok_run == n,
          (ok_run, n))
    # no look-ahead: the entries known on every prefix are the full run's entries up to there
    keyset = lambda ts: sorted((t["side"], t["i"], round(t["entry"], 9), round(t["stop"], 9)) for t in ts)  # noqa
    bad = []
    for m in range(len(rows) // 3, len(rows), len(rows) // 7):
        pre = [t for t in V4.sequence(rows[:m], day_of, intraday=True, **C1) if not t.get("pending")]
        want = [t for t in full if t["i"] + 1 < m]
        if keyset(pre) != keyset(want):
            bad.append(m)
    check("%s prefix invariance: entries on 6 prefixes equal the full run's" % tag, not bad, bad)


def defaults_unchanged():
    w = walk(20, 3)
    a = V4.sequence(w, lambda t: t.date(), intraday=True)
    b = V4.sequence(w, lambda t: t.date(), intraday=True, entry_rule="close_sweep")
    key = lambda ts: [(t["kind"], t["side"], t["i"], t.get("exit_i"), t.get("exit")) for t in ts]   # noqa: E731
    check("baseline: defaults == explicit close_sweep, entry_rule / choch_invalidate not in DEFAULTS",
          key(a) == key(b) and "entry_rule" not in V4.DEFAULTS and "choch_invalidate" not in V4.DEFAULTS)


if __name__ == "__main__":
    for tag, f, s in (("bear", lambda r: r, 1), ("bull", reflect, 0)):
        scenario(tag, f(rows_of(SEQ)), s)
        rejections(tag, f(rows_of(WICK)), s, "wick-only break (wick beyond 98.8, close back inside)")
        rejections(tag, f(rows_of(EQUAL)), s, "equal-level close (98.8)")
        no_duplicate(tag, f(rows_of(BOS3)), s)
    w = walk(60, 11)
    walk_checks("walk", w)
    walk_checks("walk reflected", reflect(w, axis=2000.0))
    defaults_unchanged()
    print("\n%d failed" % len(FAILS) if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
