#!/usr/bin/env python3
"""The owner's sweep and target for Scanner v4 (17 Nov 2026), on by default. Offline.

  1. Sweep: only a close beyond the level the BOS move started from (a swing formed after the BOS no longer counts).
  2. Target: where the latest opposite-side BOS move started, above the entry and untaken, capped at the nearest big
     swing; none -> the 12 Nov target. Switches give back the 12 Nov rules.

    python tests/test_v4_sweep_target.py
"""
import os
import random
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def walk(days, seed):
    rnd = random.Random(seed)
    out, c = [], 1000.0
    t0 = datetime(2026, 8, 3, 3, 45, tzinfo=timezone.utc)
    for d in range(days):
        drift = 0.0006 * (1 if (d // 3) % 2 == 0 else -1)
        for j in range(75):
            o = c
            c = o * (1 + drift + rnd.gauss(0, 0.003))
            h = max(o, c) * (1 + abs(rnd.gauss(0, 0.0015)))
            l = min(o, c) * (1 - abs(rnd.gauss(0, 0.0015)))
            if rnd.random() < 0.08:
                c = o * (1 + rnd.gauss(0, 0.0002))
            out.append((t0 + timedelta(days=d, minutes=5 * j), o, h, l, c, 1000))
    return out


def day_of(t):
    return t.date()


if __name__ == "__main__":
    import scanner_v4 as V4
    check("defaults: sweep only from the BOS start, target from the opposite BOS with the big-swing cap",
          V4.DEFAULTS["sweep_post_bos"] is False and V4.DEFAULTS["target_rule"] == "opp_bos_cap")
    check("defaults (19 Nov): BOS on 4-candle swings, a gap is no BOS and no sweep, no sweep-distance limit",
          V4.DEFAULTS["swing_k"] == 3 and V4.DEFAULTS["structure_bos"] is True and V4.DEFAULTS["bos_gap_skip"] is True and V4.DEFAULTS["gap_cancel"] is True
          and not V4.DEFAULTS["sweep_max_atr"] and V4.DEFAULTS["signal_on_sweep"] is False and V4.DEFAULTS["carry_swept"] is True)
    # the owner's BOS concept (20 Nov): BOS only with the structure (HH + HL / LH + LL); a break against it is a CHoCH
    def zig(pts, n=5):
        out, prev, t0 = [], pts[0], datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
        cl = [a + (b - a) * (k + 1) / n for a, b in zip(pts, pts[1:]) for k in range(n)]
        for i, c in enumerate(cl):
            out.append((t0 + timedelta(minutes=5 * i), prev, max(prev, c) + 0.05, min(prev, c) - 0.05, c, 1000))
            prev = c
        return out

    def bos_of(rows, **kw):
        p = dict(V4.DEFAULTS, **dict({"bos_rule": "swings"}, **kw))   # the 3-candle structure swings (20 Nov, early)
        cx = V4.contexts(rows, day_of, k=p["swing_k"])
        L = V4._Side(rows, cx["ctx"][0], None, p, None)
        S = V4._Side(cx["mirror"], cx["ctx"][1], None, p, None)
        L.other, S.other = S, L
        for k in range(10, len(rows)):
            L.step(k)
            S.step(k)
        return [st["bos"] for st in L.setups], [st["bos"] for st in S.setups]

    up = zig([100, 102, 100.5, 103, 101, 104, 102, 106, 103.5, 101])       # HH / HL, then a drop below the HL
    check("structure BOS: in an uptrend the breaks of the Higher Highs are BOS; the drop below the Higher Low (a CHoCH) "
          "is not a sell BOS", bos_of(up) == ([23, 32], []), bos_of(up))
    check("   without structure_bos every break was a BOS, both sides", bos_of(up, structure_bos=False)[1] == [43],
          bos_of(up, structure_bos=False))
    dn = zig([110, 107, 109, 106, 108, 104, 106.5, 102, 104, 101])
    check("   in a downtrend: sell BOS only", bos_of(dn) == ([], [22, 32, 43]), bos_of(dn))
    ul = V4.legs(zig([100, 102, 100.5, 103, 101, 104, 102, 106, 103.5, 101, 102.5, 100]))
    check("legs (owner, 20 Nov): BOS above each leg's top after a pullback, origin = the pullback low; the close below "
          "the Higher Low is a CHoCH (no setup); the downtrend's first BOS breaks its first leg's low, origin = the "
          "Lower High", [(j, sd) for j, (sd, lv, og, oi) in sorted(ul.items())] == [(13, "long"), (23, "long"),
          (32, "long"), (53, "short")] and abs(ul[23][2] - 100.95) < 1e-6 and abs(ul[53][2] - 102.55) < 1e-6, ul)
    check("defaults (20 Nov): the leg structure makes the BOS", V4.DEFAULTS["bos_rule"] == "legs")
    V4.DEFAULTS.update(bos_rule="swings")
    V4.DEFAULTS.update(swing_k=2, bos_gap_skip=False, structure_bos=False)   # the checks below: 2-candle swings
    check("defaults (18 Nov): the newest BOS is taken and the latest signal candle decides; replace stays off",
          V4.DEFAULTS["bos_pick"] == "newest" and V4.DEFAULTS["latest_signal"] is True
          and V4.DEFAULTS["replace_newer"] is False and V4.DEFAULTS["skip_open_bos"] is False)

    names, old_names, diff, n, wrong_side, shifted = set(), set(), 0, 0, 0, 0
    for seed in range(10):
        rows = walk(30, seed)
        new = [t for t in V4.sequence(rows, day_of, intraday=True) if t["kind"] == "primary"]
        old = [t for t in V4.sequence(rows, day_of, intraday=True, sweep_post_bos=True, target_rule="near")
               if t["kind"] == "primary"]
        names |= {t["level_name"] for t in new}
        shifted += sum(1 for t in new if t["level_name"] == "near_swing")
        noshift = [t for t in V4.sequence(rows, day_of, intraday=True, sweep_shift=False) if t["kind"] == "primary"]
        old_names |= {"noshift:" + t["level_name"] for t in noshift}
        old_names |= {t["level_name"] for t in old}
        n += len(new)
        wrong_side += sum(1 for t in new if ((t["target"] <= t["entry"]) if t["side"] == "long" else (t["target"] >= t["entry"])))
        diff += len({(t["i"], t["side"], round(t["target"], 6)) for t in new} ^ {(t["i"], t["side"], round(t["target"], 6)) for t in old})
    check("1. every primary's sweep is the BOS-start level or, 18 Nov, a swing beyond it near the entry "
          "(the 12 Nov rule also had post-BOS swings)",
          n > 0 and names == {"bos_origin", "near_swing"} and "post_bos" in old_names and shifted > 0, (n, names, old_names))
    check("   sweep_shift off: only the BOS-start level (the 17 Nov rule)",
          {x for x in old_names if x.startswith("noshift:")} == {"noshift:bos_origin"}, old_names)
    check("2. targets stay on the right side of the entry", wrong_side == 0, wrong_side)
    check("   and differ from the 12 Nov ones on these charts", diff > 0, diff)

    # the target helpers on a small hand-made chart (src terms: a long side and its mirror)
    rows = [(datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc) + timedelta(minutes=5 * k), 100, h, 99, 100, 0)
            for k, h in enumerate([101, 103, 102, 101, 100.5, 101, 102, 106, 102, 101, 100, 101, 101.5, 101, 100.8, 101])]
    ctx = V4.contexts(rows, day_of)
    long_side = V4._Side(rows, ctx["ctx"][0], None, V4.DEFAULTS, None)
    short_side = V4._Side(ctx["mirror"], ctx["ctx"][1], None, V4.DEFAULTS, None)
    long_side.other = short_side
    short_side.other = long_side
    short_side.bos_hist = [(3, -103.0), (9, -106.0)]     # bearish BOS moves that started from 103 and from 106
    check("3. target = where the latest opposite BOS move started (106), above the entry, untaken",
          long_side._opp_target(15, 101.0) == 106.0, long_side._opp_target(15, 101.0))
    short_side.bos_hist = [(3, -103.0), (9, -101.2)]     # the latest one started at 101.2: traded through since
    check("   the latest opposite BOS's level was traded through since (high 101.5 > 101.2): no target from it",
          long_side._opp_target(15, 101.0) is None, long_side._opp_target(15, 101.0))
    check("   the nearest big swing above the entry: 106 (the highest of 6 candles each side)",
          long_side._big_swing(15, 101.0, 6) == 106.0, long_side._big_swing(15, 101.0, 6))
    check("   below the entry or none: no opposite target", long_side._opp_target(15, 200.0) is None)
    print()
    if FAILS:
        print("%d check(s) failed" % len(FAILS))
        sys.exit(1)
    print("all checks passed")
