#!/usr/bin/env python3
"""
smc.py - the Smart Money Concepts "liquidity sweep and reclaim" setup, in one place, used by both the
backtest (research_smc.py, python research.py crypto-smc) and the live scanner (scan_crypto.py).

The idea (SMC / ICT): stop-losses pile up just beyond an obvious level, here the 4-hour range's low or high.
Larger players push price through it to fill their orders against those stops (the "sweep"), then price
snaps back inside. A sweep that is reclaimed is a reversal signal: long after a sweep of the low, short
after a sweep of the high. It is the opposite of the breakout rule, which buys the break of the high.

Two shapes, on 15-minute candles, with the range = the 16 candles (4 h) before the sweep:
  wick   one candle trades below the range low but CLOSES back above it (a long lower wick)
  2bar   one candle closes below the range low, the next closes back above it (a failed breakdown)
Mirror for the high (short). The entry is the reclaiming candle's close; the "extreme" is the furthest
point of the sweep, the natural place for the stop.
"""

RANGE_BARS = 16


def sweep_at(bars, i, rb=RANGE_BARS):
    """bars: list of (o, h, l, c, v). Is candle i (just closed) a reclaimed sweep? -> dict or None."""
    if i < rb + 2 or i >= len(bars):
        return None
    o, h, l, c, v = bars[i]
    rng = bars[i - rb:i]
    lo, hi = min(b[2] for b in rng), max(b[1] for b in rng)
    avg_v = sum(b[4] for b in rng) / rb
    prng = bars[i - 1 - rb:i - 1]           # the range as candle i-1 saw it
    plo, phi = min(b[2] for b in prng), max(b[1] for b in prng)
    p = bars[i - 1]
    out = []
    # long: sweep of the low, reclaimed
    if l < lo and c > lo and p[2] >= plo:                           # wick: this candle swept and closed back in
        out.append({"side": "long", "variant": "wick", "level": lo, "extreme": l, "vol": v})
    elif p[3] < plo and c > plo and bars[i - 2][3] >= min(b[2] for b in bars[i - 2 - rb:i - 2]):
        out.append({"side": "long", "variant": "2bar", "level": plo, "extreme": min(p[2], l), "vol": max(p[4], v)})
    # short: sweep of the high, reclaimed
    if h > hi and c < hi and p[1] <= phi:
        out.append({"side": "short", "variant": "wick", "level": hi, "extreme": h, "vol": v})
    elif p[3] > phi and c < phi and bars[i - 2][3] <= max(b[1] for b in bars[i - 2 - rb:i - 2]):
        out.append({"side": "short", "variant": "2bar", "level": phi, "extreme": max(p[1], h), "vol": max(p[4], v)})
    if len(out) != 1:          # nothing, or both sides in one candle (a whipsaw): no signal
        return None
    s = out[0]
    s.update({"entry": c, "range_high": hi, "range_low": lo, "range_mid": (hi + lo) / 2,
              "vol_x": s["vol"] / avg_v if avg_v else 0.0})
    return s
