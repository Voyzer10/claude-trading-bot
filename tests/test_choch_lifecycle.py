#!/usr/bin/env python3
"""T9 (BOS spec v2.1 §6), research switch choch_invalidate (off by default): a CHoCH ends the old direction's
unused primary setups, terminally, before the sweeps / triggers of its candle; the linked OB / FVG search of a
parent primary trade ends with its parent's structure; open trades are untouched; both sides mirror. Offline.

    python tests/test_choch_lifecycle.py
"""
import os
import random
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import scanner_v4 as V4  # noqa: E402

FAILS = []
T0 = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def base():
    """36 rising candles, a leg top (high 105) at 40, a pullback to 101.5 (44); last close 103.8 (< 105)."""
    c, x = [], 100.0
    for _ in range(36):
        c.append((x, x + 0.3, x - 0.3, x + 0.08))
        x += 0.08
    c += [(102.9, 103.6, 102.8, 103.5), (103.5, 104.1, 103.4, 104.0), (104.0, 104.5, 103.9, 104.4),
          (104.4, 104.8, 104.2, 104.6), (104.6, 105.0, 104.3, 104.5),
          (104.5, 104.7, 103.8, 103.9), (103.9, 104.2, 103.0, 103.1), (103.1, 103.4, 102.2, 102.3),
          (102.3, 102.6, 101.5, 101.8), (101.8, 102.9, 101.7, 102.8), (102.8, 103.9, 102.7, 103.8)]
    return c


def rows_of(cands):
    return [(T0 + timedelta(minutes=5 * i), o, h, l, c, 1000) for i, (o, h, l, c) in enumerate(cands)]


def reflect(rows, axis=210.0):
    return [(t, axis - o, axis - l, axis - h, axis - c, v) for t, o, h, l, c, v in rows]


def drive(rows, **kw):
    """The engine's two sides advanced candle by candle exactly as sequence() does (no trades taken), recording each
    side's setups after every step: {side: {j: [(bos, sweep, invalidated)]}}, plus the setup objects."""
    p = dict(V4.DEFAULTS, **kw)
    p["_intraday"] = False
    k = int(p.get("swing_k") or 2)
    cx = V4.contexts(rows, lambda t: t.date(), False, k=k)
    carry = [r[0].date() for r in rows]
    sides = [V4._Side((rows, cx["mirror"])[s], cx["ctx"][s], None, p, carry) for s in (0, 1)]
    sides[0].other, sides[1].other = sides[1], sides[0]
    snap, objs = {0: {}, 1: {}}, {0: {}, 1: {}}
    for j in range(31, len(rows)):
        for s in (0, 1):
            sides[s].step(j)
            for st in sides[s].setups + sides[s].waiting:
                objs[s].setdefault(st["bos"], st)
            snap[s][j] = sorted({(st["bos"], st["sweep"]) for st in sides[s].setups})
    return sides, snap, objs, cx


# BOS A at 47 (origin 101.5), up leg to 105.8, pullback to 104.5, BOS B at 51 (origin 104.5, the new protected HL),
# CHoCH at 53 (close 103.0 < 104.5, but above A's origin 101.5), then a close below 101.5 at 54 (A's baseline sweep).
SEQ_BEFORE = base() + [(103.8, 105.6, 103.7, 105.4), (105.4, 105.8, 105.2, 105.7), (105.7, 105.75, 104.9, 105.0),
                       (105.0, 105.2, 104.5, 104.6), (104.6, 106.3, 104.6, 106.2), (106.2, 106.4, 106.0, 106.3),
                       (106.3, 106.3, 102.9, 103.0), (103.0, 103.1, 100.8, 101.0), (101.0, 101.4, 100.6, 101.2),
                       (101.2, 101.3, 100.4, 100.5), (100.5, 101.6, 100.4, 101.5)]
# BOS at 47, CHoCH at 48 (close 101.0 < 101.5) on the candle that would be its close sweep
SEQ_ON = base() + [(103.8, 105.6, 103.7, 105.4), (105.4, 105.5, 100.9, 101.0), (101.0, 101.2, 100.2, 100.3),
                   (100.3, 100.4, 99.6, 99.7), (99.7, 100.6, 99.65, 100.5), (100.5, 100.9, 100.3, 100.8),
                   (100.8, 100.85, 99.2, 99.3), (99.3, 99.4, 98.8, 98.9),
                   # the trend returns up (CHoCH up at 58), price trades back below 101.5 later: A must not revive
                   (98.9, 101.2, 98.9, 101.1), (101.1, 101.3, 100.9, 101.2), (101.2, 101.4, 101.0, 101.3)]


def scenario_tests(tag, rows, long_side):
    """long_side: the engine side (0 = long, 1 = short) of the setups under test (1 on reflected rows)."""
    s = long_side
    lg = V4.legs(rows)
    bos_47 = lg.get(47)
    check("%s precondition: legs BOS at 47 and 51, CHoCH at 53" % tag,
          bos_47 is not None and lg.get(51) is not None, sorted(lg.items())[:4])
    # --- CHoCH before the sweep (SEQ_BEFORE)
    _, off, objs_off, _ = drive(rows)
    _, on, objs_on, cx = drive(rows, choch_invalidate=True)
    ag = cx["ctx"][s].choch_against
    check("%s CHoCH candle against the side is 53" % tag, 53 in ag, ag)
    A_off, A_on = objs_off[s].get(47), objs_on[s].get(47)
    B_off, B_on = objs_off[s].get(51), objs_on[s].get(51)
    # (per-candle snapshots: the existing sweep_shift later moves a sweep deeper, so the final field is not the
    # first sweep candle)
    check("%s baseline (off): B swept on the CHoCH candle (53), A first swept after it (54)" % tag,
          A_off and B_off and (51, 53) in off[s][53] and (47, None) in off[s][53] and (47, 54) in off[s][54],
          (off[s][53], off[s][54]))
    check("%s CHoCH before sweep: A invalidated at 53, never swept" % tag,
          A_on and A_on.get("invalidated") == 53 and A_on["sweep"] is None, A_on)
    check("%s CHoCH on B's sweep candle: B invalidated at 53 and the CHoCH candle is not its sweep" % tag,
          B_on and B_on.get("invalidated") == 53 and B_on["sweep"] is None, B_on)
    check("%s no setup of the side left after the CHoCH candle" % tag,
          all(not on[s][j] for j in range(53, len(rows))), [(j, on[s][j]) for j in range(53, len(rows)) if on[s][j]])
    check("%s before the CHoCH the switch changes nothing" % tag,
          all(on[s][j] == off[s][j] for j in range(31, 53)))


def on_candle_tests(tag, rows, s):
    sides_off, off, objs_off, _ = drive(rows)
    sides_on, on, objs_on, cx = drive(rows, choch_invalidate=True)
    A_off, A_on = objs_off[s].get(47), objs_on[s].get(47)
    check("%s baseline (off): the CHoCH candle 48 is the setup's close sweep" % tag, A_off and A_off["sweep"] == 48,
          A_off)
    check("%s CHoCH on the potential sweep candle: invalidated at 48, sweep None" % tag,
          A_on and A_on.get("invalidated") == 48 and A_on["sweep"] is None, A_on)
    check("%s cannot revive: absent from every later candle (the trend turns back up at 55, closes below its origin "
          "follow)" % tag,
          all(47 not in [b for b, _ in on[s][j]] for j in range(48, len(rows))))
    ends = [w for st, j, w in sides_on[s].ended if st.get("bos") == 47]
    check("%s ended record says why" % tag, ends == ["invalidated by CHoCH"], ends)
    # opposite side: the bearish CHoCH is not against the short side; its setups (the short BOS at 53) are created and
    # live exactly as without the switch
    o = 1 - s
    nxt = min(x for x in cx["ctx"][o].choch_against if x > 48)          # the next CHoCH, against the other side (55)
    check("%s opposite side unaffected by this CHoCH (identical setups every candle until its own CHoCH at %d)" % (
        tag, nxt), nxt == 55 and all(on[o][j] == off[o][j] for j in range(31, nxt)),
        [(j, on[o][j], off[o][j]) for j in range(44, nxt + 1)])
    check("%s ... and that later CHoCH ends the other side's setup (53) on its own candle" % tag,
          objs_on[o][53].get("invalidated") == nxt, objs_on[o][53])
    check("%s opposite side's own setup (BOS 53) exists" % tag, 53 in objs_on[o], sorted(objs_on[o]))
    check("%s CHoCH 48 is against side %d only" % (tag, s), 48 in cx["ctx"][s].choch_set and 48 not in cx["ctx"][o].choch_set)


def injected_opposite_test():
    """A live setup of the other side at the CHoCH candle (injected: legs cannot make one there) is not touched."""
    rows = rows_of(SEQ_ON)
    p = dict(V4.DEFAULTS, choch_invalidate=True, _intraday=False)
    cx = V4.contexts(rows, lambda t: t.date(), False, k=int(p["swing_k"]))
    carry = [r[0].date() for r in rows]
    sides = [V4._Side((rows, cx["mirror"])[s], cx["ctx"][s], None, p, carry) for s in (0, 1)]
    sides[0].other, sides[1].other = sides[1], sides[0]
    for j in range(31, 48):
        for s in (0, 1):
            sides[s].step(j)
    fake = {"bos": 40, "level": -105.0, "origin": -110.0, "sweep": None, "used": False, "day": carry[40], "leg_i": 39}
    sides[1].setups.append(fake)
    sides[1].waiting.append(fake)
    for s in (0, 1):
        sides[s].step(48)
    check("injected short setup survives the bearish CHoCH at 48", any(st is fake for st in sides[1].setups)
          and "invalidated" not in fake)
    check("long setup 47 invalidated at 48 in the same run", not any(st["bos"] == 47 for st in sides[0].setups))


def walk(days, seed, n=75):
    rnd = random.Random(seed)
    out, c = [], 1000.0
    t0 = datetime(2026, 8, 3, 3, 45, tzinfo=timezone.utc)
    for d in range(days):
        drift = 0.0006 * (1 if (d // 3) % 2 == 0 else -1)
        for j in range(n):
            o = c
            c = o * (1 + drift + rnd.gauss(0, 0.003))
            h = max(o, c) * (1 + abs(rnd.gauss(0, 0.0015)))
            l = min(o, c) * (1 - abs(rnd.gauss(0, 0.0015)))
            out.append((t0 + timedelta(days=d, minutes=5 * j), o, h, l, c, 1000))
    return out


def replay_exit(rows, tr, p, day, intraday):
    """The trade's exit from _exit_step alone (no setups involved), long or short (mirror)."""
    sg = 1 if tr["side"] == "long" else -1
    bars = rows if sg == 1 else V4.mirror(rows)
    t = {"i": tr["i"], "entry": sg * tr["entry"], "stop": sg * tr["stop"], "cur_stop": sg * tr["stop"],
         "target": sg * tr["target"]}
    for k in range(tr["i"] + 1, len(rows)):
        got = V4._exit_step(bars, k, t, p, day, intraday)
        if got:
            return k, sg * got[0]
    return None, None


def walk_tests(tag, rows):
    day_of = lambda t: t.date()                  # noqa: E731
    day = [day_of(r[0]) for r in rows]
    cx = V4.contexts(rows, day_of, False, k=int(V4.DEFAULTS["swing_k"]))
    ag = {"long": cx["ctx"][0].choch_against, "short": cx["ctx"][1].choch_against}
    off = V4.sequence(rows, day_of, intraday=True)
    on = V4.sequence(rows, day_of, intraday=True, choch_invalidate=True)
    closed = lambda ts: [t for t in ts if t.get("exit") is not None and t.get("exit_reason") != "open"]  # noqa: E731
    on_p = [t for t in closed(on) if t["kind"] == "primary"]
    # no primary trade of the switch-on run had a CHoCH against it between its BOS and its trigger candle
    bad = [t for t in on_p if any(t["bos"] < x <= t["i"] for x in ag[t["side"]])]
    off_bad = [t for t in closed(off) if t["kind"] == "primary" and any(t["bos"] < x <= t["i"] for x in ag[t["side"]])]
    check("%s primaries: none traded after a CHoCH against its setup (baseline has %d)" % (tag, len(off_bad)),
          not bad and len(off_bad) > 0, len(bad))
    # secondaries: linked = the OB / FVG of a parent primary whose structure saw a CHoCH against it before the trigger
    sec_on = [t for t in closed(on) if t["kind"] == "secondary"]
    sec_off = [t for t in closed(off) if t["kind"] == "secondary"]
    linked_on = [t for t in sec_on if any(t["prim_bos"] < x <= t["i"] for x in ag[t["side"]])]
    linked_off = [t for t in sec_off if any(t["prim_bos"] < x <= t["i"] for x in ag[t["side"]])]
    check("%s linked secondary invalidation: none after its parent's CHoCH (baseline has %d)" % (tag, len(linked_off)),
          not linked_on and len(linked_off) > 0, len(linked_on))


# A trade open across a CHoCH: BOS A at 47 (origin 101.5); a pullback WICKS to 100.9 (closes above 101.5: no CHoCH);
# BOS B at 52 takes 100.9 as its protected HL; A's close sweep at 55 (101.42 < 101.5, above 100.9: no CHoCH); doji
# signal 56; trigger 57 (close above 101.6); fill 58's open; CHoCH 59 (close 100.85 < 100.9) while open; stop at 60.
OPEN_HEAD = base() + [(103.8, 105.6, 103.7, 105.4), (105.4, 106.0, 105.3, 105.9), (105.9, 105.95, 104.0, 104.2),
                      (104.2, 104.3, 100.9, 101.8), (101.8, 103.0, 101.7, 102.9), (102.9, 106.5, 102.8, 106.4),
                      (106.4, 106.5, 104.0, 104.1), (104.1, 104.2, 102.5, 102.6), (102.6, 102.7, 100.7, 101.42),
                      (101.42, 101.6, 101.3, 101.43), (101.43, 101.8, 101.4, 101.75), (101.75, 101.9, 101.5, 101.6)]
OPEN_CHOCH = OPEN_HEAD + [(101.6, 101.65, 100.8, 100.85), (100.85, 100.9, 100.2, 100.3), (100.3, 100.5, 100.1, 100.4),
                          (100.4, 100.6, 100.2, 100.5)]
# the same, without the CHoCH: 59 / 60 close above 100.9 (60 still hits the stop), then quiet candles
OPEN_NO_CHOCH = OPEN_HEAD + [(101.6, 101.65, 101.0, 101.1), (101.1, 101.2, 100.4, 100.95), (100.95, 101.2, 100.92, 101.1),
                             (101.1, 101.3, 101.0, 101.2)]


def open_and_secondary_tests(tag, rows, s):
    side = "long" if s == 0 else "short"
    day_of = lambda t: t.date()                  # noqa: E731
    res = {}
    for flag in (False, True):
        ended = []
        out = V4.sequence(rows, day_of, intraday=False, choch_invalidate=flag, _ended=ended)
        res[flag] = ([(t["kind"], t["side"], t.get("bos"), t["i"], t.get("entry"), t.get("stop"), t.get("exit_i"),
                       t.get("exit"), t.get("exit_reason")) for t in out], ended)
    return res


def open_tests(tag, rows, s):
    side = "long" if s == 0 else "short"
    res = open_and_secondary_tests(tag, rows, s)
    trades_off, _ = res[False]
    trades_on, ended_on = res[True]
    tr = [t for t in trades_on if t[0] == "primary" and t[2] == 47]
    check("%s precondition: the %s trade from BOS 47 triggers at 57, fills at 58's open" % (tag, side),
          len(tr) == 1 and tr[0][3] == 57 and abs(tr[0][4] - rows[58][1]) < 1e-9, trades_on)
    check("%s open position untouched: open across the CHoCH at 59, identical trade and exit with the switch on and "
          "off" % tag, trades_on == trades_off and tr and tr[0][6] == 60, (trades_on, trades_off))
    check("%s the CHoCH at 59 still ends the unused setup B (52)" % tag,
          [(st.get("bos"), j) for st, j, w in ended_on if w == "invalidated by CHoCH"] == [(52, 59)],
          [(st.get("bos", st.get("parent_bos")), j, w) for st, j, w in ended_on])
    sec = [(st.get("parent_bos"), j) for st, j, w in ended_on if w.startswith("secondary invalidated")]
    check("%s linked secondary: the OB / FVG search of parent 47 ends on the first candle after the parent closed "
          "(61), because its structure saw the CHoCH at 59" % tag, sec == [(47, 61)], sec)
    _, ended_off = res[False]
    check("%s ... and only with the switch on" % tag, not any(w.startswith("secondary") for _, _, w in ended_off))


def unlinked_tests(tag, rows, s):
    res = open_and_secondary_tests(tag, rows, s)
    trades_off, _ = res[False]
    trades_on, ended_on = res[True]
    check("%s precondition: no CHoCH in this variant" % tag, not V4.contexts(
        rows, lambda t: t.date(), False, k=3)["ctx"][s].choch_against)
    check("%s secondary not wrongly invalidated: the search of parent 47 (no CHoCH against its structure) "
          "continues; output identical on / off" % tag,
          not any(w.startswith("secondary") for _, _, w in ended_on) and trades_on == trades_off, ended_on)


if __name__ == "__main__":
    scenario_tests("bull", rows_of(SEQ_BEFORE), 0)
    scenario_tests("bear", reflect(rows_of(SEQ_BEFORE)), 1)
    on_candle_tests("bull", rows_of(SEQ_ON), 0)
    on_candle_tests("bear", reflect(rows_of(SEQ_ON)), 1)
    injected_opposite_test()
    w = walk(40, 7)
    walk_tests("walk", w)
    walk_tests("walk reflected", reflect(w, axis=2000.0))
    open_tests("bull", rows_of(OPEN_CHOCH), 0)
    open_tests("bear", reflect(rows_of(OPEN_CHOCH)), 1)
    unlinked_tests("bull", rows_of(OPEN_NO_CHOCH), 0)
    unlinked_tests("bear", reflect(rows_of(OPEN_NO_CHOCH)), 1)
    check("default is off (baseline unchanged)", not V4.DEFAULTS.get("choch_invalidate")
          and V4.DEFAULTS.get("entry_rule", "close_sweep") == "close_sweep")
    print("\n%d failed" % len(FAILS) if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
