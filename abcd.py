#!/usr/bin/env python3
"""
abcd.py - the owner's own A-B-C-D entry (PDF "A-B-C-D Bullish Trade Setup", MAR 5m, 3 Nov 2026), as a state
machine on CLOSED candles. Used by the backtest (research_abcd.py) and, once it passes, the live bot.

    IDLE    --A: bullish BOS/CHoCH (first close above the latest confirmed swing high)-->      WAIT_B
    WAIT_B  --B: a RED candle trades below the first swing low and CLOSES below it-->          WAIT_C
    WAIT_C  --C: a GREEN doji closes (within c_max candles of B); store C-high / C-low-->     WAIT_D
    WAIT_D  --D: a later candle CLOSES strictly above C-high (within d_max candles of C)-->     BUY once
    reset   a bearish structure break before B, A older than a_max candles, C/D window over, or a close
            below C-low (back to WAIT_C while the C window is still open)

Not an entry: A alone, A+B, A+B+C, a D wick above C-high that closes at or below it (the PDF's acceptance tests).
"First swing low" = the latest confirmed swing low (2 candles each side) known when B happens.

The PDF leaves one thing open (its own "technical note"): a close below the swing is a breakdown, not a classic
sweep. Each signal records `reclaimed` (some close from B to D got back above the swing level), so the backtest
scores both readings: B = close below only, and B = close below + reclaim.

Shorts = the same machine on prices turned upside down (bearish CHoCH, green candle closing above the first swing
high, RED doji, close below C-low).
"""
import smc_playbook as PB


def mirror(rows):
    return [(r[0], -r[1], -r[3], -r[2], -r[4], r[5]) for r in rows]


def ema(vals, n):
    k, e, out = 2 / (n + 1), None, []
    for v in vals:
        e = v if e is None else e + k * (v - e)
        out.append(e)
    return out


def signals(rows, day_of, doji_pct=0.15, a_max=48, c_max=6, d_max=12, short=False, ctx=None):
    """Every D (entry) the machine reaches over rows (t, o, h, l, c, v). Returns (ctx, [signal dicts]); prices in a
    short's signals are back in normal (not mirrored) terms."""
    src = mirror(rows) if short else rows
    ctx = ctx or PB.Context(src, day_of)
    bars = src
    e200 = ema([b[4] for b in bars], 200)
    out = []
    state, a = "IDLE", None
    b_i = b_lvl = c_i = c_hi = c_lo = None
    for i in range(30, len(bars)):
        o, h, l, c = bars[i][1], bars[i][2], bars[i][3], bars[i][4]
        if state != "IDLE" and i - a > a_max and state in ("WAIT_B",):
            state = "IDLE"
        if state == "IDLE":
            if ctx.bull[i]:
                state, a = "WAIT_B", i
            continue
        if state == "WAIT_B":
            if ctx.bull[i]:            # a newer bullish break: A moves up
                a = i
                continue
            piv = ctx.sl_known[i - 1]
            if piv:
                lvl = piv[-1][1]
                if c < o and l < lvl and c < lvl:
                    state, b_i, b_lvl = "WAIT_C", i, lvl
                    continue
            if ctx.bear[i]:            # structure broke down some other way: setup gone
                state = "IDLE"
            continue
        if state == "WAIT_C":
            if i - b_i > c_max:
                state = "IDLE"
                continue
            s = PB.shape(bars[i])
            if s and c > o and s["body"] <= doji_pct:
                state, c_i, c_hi, c_lo = "WAIT_D", i, h, l
            continue
        if state == "WAIT_D":
            if c > c_hi:                                  # D: strictly above C-high, on the close
                atr = ctx.atr[i]
                if atr:
                    reclaimed = any(bars[k][4] > b_lvl for k in range(b_i + 1, i + 1))
                    sweep_low = min(bars[k][3] for k in range(b_i, i + 1))
                    sg = -1 if short else 1
                    out.append({"i": i, "side": "short" if short else "long", "a": a, "b": b_i, "c": c_i,
                                "entry": sg * c, "c_low": sg * c_lo, "c_high": sg * c_hi, "b_level": sg * b_lvl,
                                "sweep_low": sg * sweep_low, "atr": atr, "reclaimed": reclaimed,
                                "d_offset": i - c_i, "c_body": PB.shape(bars[c_i])["body"],
                                "trend": c > e200[i], "d_body_atr": abs(c - o) / atr})
                state = "IDLE"
                continue
            if c < c_lo:                                  # closed through the doji: wait for a new C
                state = "WAIT_C" if i - b_i <= c_max else "IDLE"
                continue
            if i - c_i >= d_max:
                state = "IDLE"
    return ctx, out


def stop_for(sig, mode, buffer_atr=0.1):
    """mode: c_low (below the doji, the PDF's example) | sweep (below the lowest low from B to D)."""
    a = sig["atr"] * buffer_atr
    long = sig["side"] == "long"
    base = sig["c_low"] if mode == "c_low" else sig["sweep_low"]
    return base - a if long else base + a


def target_for(ctx, sig, mode, stop):
    """2R | trail (far target, the trailing stop exits) | internal: the nearest confirmed swing beyond the entry."""
    entry, long = sig["entry"], sig["side"] == "long"
    risk = (entry - stop) if long else (stop - entry)
    if mode == "2R":
        return entry + 2 * risk if long else entry - 2 * risk
    if mode == "trail":
        return entry + 20 * risk if long else max(entry * 0.05, entry - 20 * risk)
    i = sig["i"]
    # ctx is the mirrored context for shorts: a swing high there is a swing low in real prices
    t = ctx.nearest_swing_beyond(i, entry if long else -entry, True)
    if t is None:
        return None
    return t if long else -t
