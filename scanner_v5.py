#!/usr/bin/env python3
"""
scanner_v5.py - Scanner v5: the "0.146 level" (owner, 10 Nov 2026, from a trader's reel on XAUUSD 3m).

The idea: after a move, price comes most of the way back and turns BEFORE retesting the move's extreme, at
    extreme -/+ C x range,   C = 0.146 (a constant; the backtest also tries other values).
  * after an UP move (low L -> high H, range R = H - L): support at  L + C x R  -> LONG
  * after a DOWN move (high H -> low L):                resistance at H - C x R  -> SHORT
"Not a single candle closed beyond the level": a candle that touches the level and CLOSES back on the right
side of it is the entry; a close through the level (or a trade beyond the extreme) cancels that move.

Rules here (long, in "src" terms; shorts are the mirror image, like scanner_v4):
  move     "swing": the last confirmed swing high H and the swing low L before it (pivots, k=2), the up-leg L -> H.
           "day":   today's low so far, then today's high after it (the day's up-move so far).
  size     the range must be at least min_range_atr x ATR (a real move, not noise).
  wait     the level must be touched within max_wait candles of the high (the move is "fresh").
  entry    the first candle whose low reaches the level (within touch_atr x ATR above it) and whose close is
           above the level, while price never traded below L. Entry = that candle's close.
  cancel   a close below the level, or a trade below L, before the entry: that move is done.
  stop     below L by buffer_atr x ATR (beyond the move's extreme, as in the reel).
  target   "leg": H (the other end of the move);  "2R": twice the risk. Skipped if reward:risk < min_rr.
  exits    stop first, then target; intraday charts close at the day's last candle; max_hold candles.
One trade at a time per chart and side, one trade per move.
"""
import smc_playbook as PB

DEFAULTS = {"c": 0.146, "move": "swing", "target": "leg", "min_rr": 1.0, "min_range_atr": 1.5,
            "max_wait": 48, "touch_atr": 0.1, "buffer_atr": 0.1, "max_hold": 48}


def mirror(rows):
    return [(r[0], -r[1], -r[3], -r[2], -r[4], r[5]) for r in rows]


def _legs_swing(ctx, i):
    """The up-leg known at candle i: (L index, L, H index, H) from the latest swing high and the swing low before
    it, or None."""
    hs, ls = ctx.sh_known[i], ctx.sl_known[i]
    if not hs or not ls:
        return None
    hi_i, hi = hs[-1]
    lows = [(j, p) for j, p in ls if j < hi_i]
    if not lows:
        return None
    lo_i, lo = lows[-1]
    # the leg's real start: the lowest low between that swing low and the high
    j = min(range(lo_i, hi_i + 1), key=lambda x: ctx.bars[x][3])
    return j, ctx.bars[j][3], hi_i, hi


def _legs_day(ctx, i, day):
    """Today's up-move up to candle i-1: (L index, L, H index, H) with the low before the high, or None."""
    start = i
    while start > 0 and day[start - 1] == day[i]:
        start -= 1
    if i - start < 3:
        return None
    bars = ctx.bars
    hi_i = max(range(start, i), key=lambda x: bars[x][2])
    if hi_i == start:
        return None
    lo_i = min(range(start, hi_i), key=lambda x: bars[x][3])
    return lo_i, bars[lo_i][3], hi_i, bars[hi_i][2]


def _walk(bars, day, i, entry, stop, target, p, intraday):
    n = len(bars)
    for k in range(i + 1, n):
        o, h, l, c = bars[k][1], bars[k][2], bars[k][3], bars[k][4]
        if l <= stop:
            return k, (o if o < stop else stop), "stop"
        if h >= target:
            return k, (o if o > target else target), "target"
        if intraday and (k + 1 >= n or day[k + 1] != day[k]):
            if k + 1 < n:
                return k, c, "day end"
        if k - i >= p["max_hold"]:
            return k, c, "time"
    return None, None, "open"


def longs(src, day_of, p, intraday=False):
    """Long trades in src terms."""
    ctx = PB.Context(src, day_of)
    day = ctx.day
    out, used, busy_until = [], set(), -1
    dead = set()                       # moves cancelled before an entry
    for i in range(30, len(src)):
        if i <= busy_until:
            continue
        leg = _legs_swing(ctx, i) if p["move"] == "swing" else _legs_day(ctx, i, day)
        if not leg:
            continue
        lo_i, lo, hi_i, hi = leg
        key = (lo_i, hi_i)
        if key in used or key in dead:
            continue
        atr = ctx.atr[i] or 0
        rng = hi - lo
        if atr <= 0 or rng < p["min_range_atr"] * atr or i - hi_i > p["max_wait"] or i <= hi_i:
            continue
        if intraday and day[i] != day[hi_i]:
            continue
        level = lo + p["c"] * rng
        o, h, l, c = src[i][1], src[i][2], src[i][3], src[i][4]
        # cancelled: price already went below L, or closed below the level, after the high
        seg = src[hi_i + 1:i]
        if any(b[3] <= lo for b in seg) or any(b[4] < level for b in seg) or l <= lo:
            dead.add(key)
            continue
        if any(b[3] <= level + p["touch_atr"] * atr for b in seg):
            dead.add(key)              # touched earlier without a qualifying close: the first touch counts
            continue
        if l > level + p["touch_atr"] * atr:
            continue                   # not there yet
        if c < level:
            dead.add(key)
            continue
        entry = c
        stop = lo - p["buffer_atr"] * atr
        target = hi if p["target"] == "leg" else entry + 2 * (entry - stop)
        risk = entry - stop
        if risk <= 0 or (target - entry) / risk < p["min_rr"]:
            dead.add(key)
            continue
        used.add(key)
        k, px, why = _walk(src, day, i, entry, stop, target, p, intraday)
        out.append({"i": i, "entry": entry, "stop": stop, "target": target, "level": level, "leg_low": lo,
                    "leg_high": hi, "leg_low_i": lo_i, "leg_high_i": hi_i, "range": rng, "c": p["c"],
                    "move": p["move"], "exit_i": k, "exit": px, "exit_reason": why})
        busy_until = k if k is not None else len(src)
    return out


def _real(t, short):
    t = dict(t)
    t["side"] = "short" if short else "long"
    if short:
        for f in ("entry", "stop", "target", "level", "exit"):
            if t.get(f) is not None:
                t[f] = -t[f]
        t["leg_low"], t["leg_high"] = -t["leg_high"], -t["leg_low"]
    return t


def sequence(rows, day_of, intraday=False, **kw):
    """Every v5 trade on one chart, both sides, in time order: [{i, side, entry, stop, target, level, leg_low,
    leg_high, range, c, move, exit_i, exit, exit_reason}]."""
    p = dict(DEFAULTS, **kw)
    trades = [_real(t, False) for t in longs(rows, day_of, p, intraday)]
    trades += [_real(t, True) for t in longs(mirror(rows), day_of, p, intraday)]
    return sorted(trades, key=lambda t: (t["i"], t["side"]))


def rr(t):
    risk = abs(t["entry"] - t["stop"])
    return abs(t["target"] - t["entry"]) / risk if risk > 0 else 0.0
