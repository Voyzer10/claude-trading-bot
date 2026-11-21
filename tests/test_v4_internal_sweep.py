#!/usr/bin/env python3
"""sweep_rule="internal" (21 Nov 2026) on the legs structure: a BOS setup stays valid only while its protected
HL (LH) holds by close; a sweep is a wick through INTERNAL liquidity (a resting confirmed swing low of the BOS leg,
or the protected swing itself as the deepest pool), at most sweep_pen_atr x ATR beyond the deepest level taken, with
the candle closing back above it; a failed reclaim or a too-deep wick is not a sweep and not an invalidation; a sweep
is never an entry by itself (signal candle after the sweep, then a break and close of it). Bullish and mirrored
bearish charts. Offline.

    python tests/test_v4_internal_sweep.py
"""
import os
import sys
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import scanner_v4 as V4  # noqa: E402
from test_choch_lifecycle import base, rows_of, reflect  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


# BOS at 47 (close 105.4 > the leg top 105; protected HL 101.5 = candle 44). The leg tops at 106.2 (48), dips to an
# internal swing low 103.6 (50, confirmed at 53), recovers (51-53, no close above 106.2) and pulls back (54).
# ATR(14) at 55 ~1.17, so sweep_pen_atr 0.25 ~0.29.
HEAD = base() + [(103.8, 105.6, 103.7, 105.4), (105.4, 106.2, 105.3, 106.0), (106.0, 106.1, 104.8, 105.0),
                 (105.0, 105.1, 103.6, 104.3), (104.3, 105.0, 104.2, 104.9), (104.9, 105.6, 104.8, 105.5),
                 (105.5, 105.9, 105.3, 105.8), (105.8, 105.9, 104.6, 104.8)]
DOJI = (103.9, 104.2, 103.7, 103.92)          # long-legged doji (a BUY signal candle)
BREAK = (103.92, 104.6, 103.9, 104.5)         # closes above the doji's high 104.2
TAIL = [(104.5, 104.7, 104.3, 104.6), (104.6, 104.8, 104.4, 104.7)]
CH = {
    # 55: wick 103.5 (0.10 under 103.6), close 103.9: a valid internal sweep; 56 doji; 57 break and close: entry
    "valid": HEAD + [(104.8, 104.9, 103.5, 103.9), DOJI, BREAK] + TAIL,
    # 55 closes 103.55 below the swept 103.6 (above the HL): no sweep; 56 wicks 0.10 under the HL 101.5 and closes
    # back at 102.0: a sweep of the protected swing's liquidity; 57 doji, 58 break: entry
    "failed_then_hl": HEAD + [(104.8, 104.9, 103.5, 103.55), (103.55, 103.6, 101.4, 102.0),
                              (102.0, 102.3, 101.8, 102.02), (102.02, 102.6, 102.0, 102.5)] + TAIL,
    # 55: wick 0.40 under 103.6 (> 0.25 ATR), close back above: too deep, not a sweep
    "too_deep": HEAD + [(104.8, 104.9, 103.2, 103.9), DOJI, BREAK] + TAIL,
    # 55 closes 101.3 below the protected HL 101.5: structure broken (CHoCH): the setup ends, no trade
    "broken_before": HEAD + [(104.8, 104.9, 101.2, 101.3), (101.3, 101.6, 101.0, 101.4), (101.4, 101.9, 101.3, 101.8)],
    # valid sweep at 55, then 56 closes 101.3 below the HL before any entry: ended, no trade
    "broken_after": HEAD + [(104.8, 104.9, 103.5, 103.9), (103.9, 104.0, 101.2, 101.3), (101.3, 101.6, 101.0, 101.4)]
    + TAIL,
    # nothing takes 103.6 for 12 candles after the BOS: stale (ended at 59)
    "stale": HEAD + [(104.8, 105.0, 104.7, 104.9)] * 8,
    # 55 closes above the leg top 106.2 after the pullback: a newer BOS; the setup of 47 is superseded
    "superseded": HEAD + [(104.8, 106.6, 104.7, 106.5), (106.5, 106.7, 106.3, 106.6)],
    # a valid sweep, but no signal candle and break: strong-bodied candles only -> no entry; expires after 12
    "no_confirmation": HEAD + [(104.8, 104.9, 103.5, 103.9)] + [(103.9, 104.4, 103.85, 104.35),
                                                               (104.35, 104.4, 103.95, 104.0)] * 7,
    # the sweep candle is itself a long-legged doji; 56 closes above its high: not an entry (signal_on_sweep off)
    "signal_on_sweep": HEAD + [(103.9, 104.3, 103.5, 103.92), (103.92, 104.5, 103.9, 104.45),
                               (104.45, 104.5, 104.3, 104.35)],
    # wick-only / equal close at 47: no BOS
    "wick_only": base() + [(103.8, 105.8, 103.7, 104.9), (104.9, 105.0, 104.5, 104.6)],
    "equal": base() + [(103.8, 105.2, 103.7, 105.0), (105.0, 105.1, 104.8, 104.9)],
}


def run(cands, tag, rule="internal", intraday=False, next_day_from=None, **kw):
    rows = rows_of(cands)
    if next_day_from is not None:
        rows = [(r[0] + timedelta(days=1), *r[1:]) if i >= next_day_from else r for i, r in enumerate(rows)]
    if tag == "bear":
        rows = reflect(rows)
    ended, attempts = [], []
    out = V4.sequence(rows, lambda t: t.date(), intraday=intraday, _ended=ended, _attempts=attempts,
                      **dict({"sweep_rule": rule}, **kw))
    prim = [t for t in out if t["kind"] == "primary"]
    return rows, prim, [(s.get("bos"), j, w) for s, j, w in ended], [(s.get("bos"), j, w) for s, j, w in attempts]


def suite(tag):
    side = "long" if tag == "bull" else "short"
    sg = 1 if tag == "bull" else -1
    T = "%s:" % tag
    # --- BOS
    rows, tr, e, _ = run(CH["valid"], tag)
    lg = V4.legs(rows)
    check("%s valid BOS: legs BOS at 47 (%s), protected %s 101.5 mirrored" % (T, side, "HL" if sg == 1 else "LH"),
          lg.get(47, ("",))[0] == side and abs(lg[47][2] - (101.5 if sg == 1 else 210 - 101.5)) < 1e-9, lg.get(47))
    for nm in ("wick_only", "equal"):
        rows2, tr2, _, _ = run(CH[nm], tag)
        check("%s invalid BOS (%s close): no BOS at 47, no trade" % (T, nm.replace("_", "-")),
              47 not in V4.legs(rows2) and not tr2, (sorted(V4.legs(rows2)), tr2))
    # --- valid internal sweep and entry confirmation
    check("%s valid internal sweep: wick 0.10 through the internal swing (103.6), close back above -> sweep at 55; "
          "doji 56, break 57 -> one entry" % T,
          [(t["side"], t["bos"], t["sweep"], t["signal"], t["i"], t["level_name"]) for t in tr]
          == [(side, 47, 55, 56, 57, "local_swing")], [(t["side"], t["bos"], t.get("sweep"), t["i"]) for t in tr])
    if tr:
        t = tr[0]
        a = V4.contexts(rows, lambda x: x.date(), False, k=3)["ctx"][0 if sg == 1 else 1].atr[57]
        want = sg * (103.5 - 0.1 * a) if sg == 1 else sg * (-(210 - 103.5) - 0.1 * a)
        check("%s stop below the swept wick: low(55..56) -/+ 0.1 ATR; swept level and penetration recorded" % T,
              abs(t["stop"] - want) < 1e-9 and abs(t["liq_ref"] - (103.6 if sg == 1 else 210 - 103.6)) < 1e-9
              and abs(t["sweep_pen"] - 0.1) < 1e-9, (t["stop"], want, t.get("liq_ref"), t.get("sweep_pen")))
    # --- protected swing invalidation
    _, tr, e, _ = run(CH["broken_before"], tag)
    check("%s protected HL closed through before any sweep (55): setup ended at 55 (CHoCH), no trade" % T,
          not tr and (47, 55, "invalidated by CHoCH") in e, e)
    _, tr, e, _ = run(CH["broken_after"], tag)
    check("%s protected HL closed through after a valid sweep, before the entry (56): ended at 56, no trade" % T,
          not tr and any(b == 47 and j == 56 for b, j, w in e), e)
    # --- failed reclaim: not a sweep, not an invalidation; a later sweep of the HL's liquidity can still trade
    _, tr, e, att = run(CH["failed_then_hl"], tag)
    check("%s failed reclaim at 55 (closed below the swept 103.6, above the HL): an attempt, the setup stays" % T,
          (47, 55, "failed reclaim: closed below the swept local_swing") in att and not any(b == 47 and j == 55
                                                                                            for b, j, w in e), (att, e))
    check("%s ... then a 0.10 wick through the protected HL closing back above (56): sweep of bos_origin; doji 57, "
          "break 58 -> entry" % T, [(t["bos"], t["sweep"], t["i"], t["level_name"]) for t in tr]
          == [(47, 56, 58, "bos_origin")], [(t["bos"], t.get("sweep"), t["i"], t.get("level_name")) for t in tr])
    _, tr_v2, e_v2, _ = run(CH["failed_then_hl"], tag, rule="v2")
    check("%s (v2 on the same chart ends the setup at the failed reclaim: no trade)" % T,
          not tr_v2 and any(w.startswith("no reclaim") for _, _, w in e_v2), e_v2)
    # --- excessive penetration
    _, tr, e, att = run(CH["too_deep"], tag)
    check("%s excessive penetration (0.40 > 0.25 ATR beyond 103.6): not a sweep, no entry; setup still active" % T,
          not tr and any(j == 55 and w.startswith("wick too deep") for _, j, w in att)
          and not any(b == 47 and j == 55 for b, j, w in e), (att, e))
    # --- stale setups
    _, tr, e, _ = run(CH["stale"], tag)
    check("%s stale: no sweep within 12 candles of the BOS -> ended at 59" % T,
          not tr and (47, 59, "no sweep within 12 candles") in e, e)
    _, tr, e, _ = run(CH["superseded"], tag)
    check("%s stale: a newer BOS (55) supersedes the unswept setup of 47" % T,
          (47, 55, "superseded by a newer BOS") in e, e)
    _, tr, e, _ = run(CH["valid"], tag, intraday=True, next_day_from=55)
    check("%s stale: intraday, the sweep comes on the next session -> the setup ended overnight, no trade" % T,
          not tr and (47, 55, "overnight") in e, e)
    # --- entry confirmation is separate from the sweep
    _, tr, e, _ = run(CH["no_confirmation"], tag)
    check("%s sweep without a signal candle and break: no entry; expires 12 candles after the sweep" % T,
          not tr and any(b == 47 and w.startswith("no entry within 12") for b, j, w in e), e)
    _, tr, e, _ = run(CH["signal_on_sweep"], tag)
    check("%s the sweep candle itself is not the signal candle (signal_on_sweep off): no entry from it" % T,
          not any(t["signal"] == 55 for t in tr), [(t["signal"], t["i"]) for t in tr])
    # --- the old rules on the same chart
    _, tr, _, _ = run(CH["valid"], tag, rule="close")
    check("%s baseline close rule on the valid chart: no trade (the protected HL never closed through)" % T, not tr, tr)


if __name__ == "__main__":
    suite("bull")
    suite("bear")
    check("defaults unchanged: sweep_rule 'close'", V4.DEFAULTS["sweep_rule"] == "close")
    print("\n%d failed" % len(FAILS) if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
