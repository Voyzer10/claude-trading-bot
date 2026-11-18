#!/usr/bin/env python3
"""
tm_india.py - a time machine for NSE (stocks and the Nifty / Bank Nifty indices), IST session.

Two views of one opening-range-breakout trade, both from the instrument's own last ~60 days of
5-minute bars (Yahoo):

  history(...)   every past session where the same rule fired (15-minute opening range from 9:15,
                 the first 5-minute close beyond it before the entry cut-off, stop at the range
                 midpoint, target N x the risk, flat by 15:15): how each one ended, in R.
  replay(...)    the rest of today, rebuilt `paths` times from the instrument's own 5-minute moves
                 after 9:30 (each drawn whole as high/low/close vs the prior close); a candle that
                 touches both levels counts as the stop (cautious).

`direction` "up" is a long breakout above the range; "down" is a breakdown below it, scored as a
short in index points (used for buying puts). `cost_r` is the round-trip charge in R, subtracted
from every result. A simulation is a reality check, not a prediction.
"""
import random
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
OPEN = (9, 15)


def _sessions(d):
    days = {}
    for t, o, h, l, c in zip(d["t"], d["o"], d["h"], d["l"], d["c"]):
        st = datetime.fromtimestamp(t, IST)
        if st.minute % 5 or st.second:
            continue
        days.setdefault(st.date(), []).append((st, o, h, l, c))
    return [sorted(v) for k, v in sorted(days.items())]


def _hm(s):
    h, m = s.split(":")
    return int(h), int(m)


def history(d, direction="up", target_r=2.0, or_minutes=15, entry_end="11:30", flat_by="15:15",
            cost_r=0.0, before=None):
    """The rule on every past full session (dates before `before`)."""
    results = []
    for bars in _sessions(d):
        day = bars[0][0].date()
        if before and day >= before:
            continue
        o_start = bars[0][0].replace(hour=OPEN[0], minute=OPEN[1])
        o_end = o_start + timedelta(minutes=or_minutes)
        cut = o_start.replace(hour=_hm(entry_end)[0], minute=_hm(entry_end)[1])
        flat = o_start.replace(hour=_hm(flat_by)[0], minute=_hm(flat_by)[1])
        rng = [b for b in bars if o_start <= b[0] < o_end]
        if len(rng) < or_minutes // 5:
            continue
        hi, lo = max(b[2] for b in rng), min(b[3] for b in rng)
        mid = (hi + lo) / 2
        after = [b for b in bars if b[0] >= o_end]
        entry_i = None
        for i, b in enumerate(after):
            if b[0] + timedelta(minutes=5) > cut:
                break
            if (direction == "up" and b[4] > hi) or (direction == "down" and b[4] < lo):
                entry_i = i
                break
        if entry_i is None:
            continue
        entry = after[entry_i][4]
        risk = (entry - mid) if direction == "up" else (mid - entry)
        if risk <= 0:
            continue
        target = entry + target_r * risk if direction == "up" else entry - target_r * risk
        r = None
        last_c = entry
        for b in after[entry_i + 1:]:
            if b[0] >= flat:
                break
            last_c = b[4]
            if direction == "up":
                if b[3] <= mid:
                    r = -1.0
                    break
                if b[2] >= target:
                    r = target_r
                    break
            else:
                if b[2] >= mid:
                    r = -1.0
                    break
                if b[3] <= target:
                    r = target_r
                    break
        if r is None:
            r = ((last_c - entry) if direction == "up" else (entry - last_c)) / risk
        results.append(r - cost_r)
    if not results:
        return {"fired": 0}
    return {"fired": len(results), "target": sum(1 for r in results if r >= target_r - cost_r - 1e-9),
            "stop": sum(1 for r in results if r <= -1 - cost_r + 1e-9),
            "avg_r": round(sum(results) / len(results), 3)}


def replay(d, entry, stop, target, now_ist, direction="up", flat_by="15:15", paths=2000, seed=None, cost_r=0.0):
    """Rebuild the rest of today from the instrument's own 5-minute moves after 9:30."""
    moves = []
    for bars in _sessions(d):
        for i in range(1, len(bars)):
            st = bars[i][0]
            if (st.hour, st.minute) < (9, 30) or bars[i - 1][4] <= 0:
                continue
            pc = bars[i - 1][4]
            moves.append((bars[i][2] / pc, bars[i][3] / pc, bars[i][4] / pc))
    if len(moves) < 200:
        return None
    flat = now_ist.replace(hour=_hm(flat_by)[0], minute=_hm(flat_by)[1], second=0, microsecond=0)
    n = max(0, int((flat - now_ist).total_seconds() // 300))
    if n == 0:
        return None
    rnd = random.Random(seed)
    risk = (entry - stop) if direction == "up" else (stop - entry)
    reward = abs(target - entry)
    tgt = stp = 0
    total = 0.0
    for _ in range(paths):
        px = entry
        r = None
        for _ in range(n):
            mh, ml, mc = moves[rnd.randrange(len(moves))]
            hi, lo = px * mh, px * ml
            if direction == "up":
                if lo <= stop:
                    r, stp = -1.0, stp + 1
                    break
                if hi >= target:
                    r, tgt = reward / risk, tgt + 1
                    break
            else:
                if hi >= stop:
                    r, stp = -1.0, stp + 1
                    break
                if lo <= target:
                    r, tgt = reward / risk, tgt + 1
                    break
            px *= mc
        if r is None:
            r = ((px - entry) if direction == "up" else (entry - px)) / risk
        total += r - cost_r
    return {"paths": paths, "bars_left": n, "target_first": round(tgt / paths, 3), "stop_first": round(stp / paths, 3),
            "neither": round((paths - tgt - stp) / paths, 3), "avg_r": round(total / paths, 3)}
