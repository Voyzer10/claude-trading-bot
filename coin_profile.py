#!/usr/bin/env python3
"""
coin_profile.py - how each watched coin has behaved lately, measured from its own candles.

For every coin, from the last 30 days of 15-minute candles (the same data the strategy trades on):

  trend        variance ratio of 1-hour returns: do moves keep going (trending, > 1) or snap back
               (mean-reverting, < 1)? With a z-score, so noise is called "random", not a style.
  breakouts    the strategy's own trigger: a fresh 15m close above the 4-hour high. How often did price
               then gain 1 ATR before losing 1 ATR (within 4 hours)? A coin flip is 50%.
  levels       support / resistance: when price touched its prior 24-hour high or low, how often did it
               turn back 1 ATR before pushing 1 ATR through?
  btc          correlation of 1-hour returns with BTC (how much it just follows BTC).
  volume       big-volume candles (2x the 4h average, a move of at least half an ATR): did price 4 hours
               later continue in that direction or fade? A rough proxy for "smart money" (large
               participants); real order flow is not in free candle data.

The style label only appears when the numbers say something beyond noise and the sample is big enough;
otherwise it says "no clear style". This describes the past 30 days. It is not a prediction and it is
NOT a trading filter: using it to pick trades would need a backtest first (research.py).

The runner (live.py) refreshes trader/live/coin_profiles.json once a day in a background thread;
the dashboard shows it on the coin cards.
    python coin_profile.py SOL ETH        # print profiles for a few coins
"""
import json
import math
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

OUT = os.path.join("trader", "live", "coin_profiles.json")
DAYS = 30
RANGE_BARS = 16      # 4 hours of 15m bars (the strategy's range)
LEVEL_BARS = 96      # 24 hours: support / resistance
AHEAD = 16           # judge outcomes over the next 4 hours
MIN_N = 15           # fewer events than this: not enough to call a style
SURE = 2.0           # standard errors from a coin flip before a style is named (1.5 named random walks)

_lock = threading.Lock()
_running = False


# ------------------------------------------------------------------ maths

def _bars(d):
    """Clean 15m bars: (t, o, h, l, c, v) with prices present."""
    out = []
    for i, t in enumerate(d.get("t") or []):
        try:
            o, h, l, c = d["o"][i], d["h"][i], d["l"][i], d["c"][i]
            v = (d.get("v") or [0] * len(d["t"]))[i] or 0
        except (IndexError, KeyError):
            continue
        if None in (o, h, l, c) or c <= 0:
            continue
        if datetime.fromtimestamp(t, timezone.utc).minute % 15:
            continue
        out.append((t, o, h, l, c, v))
    return out


def _atr(bars, n=14):
    out, trs = [None] * len(bars), []
    for i, b in enumerate(bars):
        pc = bars[i - 1][4] if i else b[4]
        trs.append(max(b[2] - b[3], abs(b[2] - pc), abs(b[3] - pc)))
        if i >= n:
            out[i] = sum(trs[i - n + 1:i + 1]) / n
    return out


def _hourly(bars):
    """Hour -> last close in that hour."""
    h = {}
    for b in bars:
        h[b[0] // 3600] = b[4]
    return h


def _returns(closes):
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0 and closes[i] > 0]


def variance_ratio(rets, q):
    """Lo-MacKinlay variance ratio and its z-score (iid null)."""
    n = len(rets)
    if n < q * 8:
        return None, None
    mu = sum(rets) / n
    var1 = sum((r - mu) ** 2 for r in rets) / (n - 1)
    if var1 <= 0:
        return None, None
    sums = [sum(rets[i:i + q]) for i in range(n - q + 1)]
    varq = sum((s - q * mu) ** 2 for s in sums) / (len(sums) - 1)
    vr = varq / (q * var1)
    z = (vr - 1) / math.sqrt(2 * (2 * q - 1) * (q - 1) / (3 * q * n))
    return vr, z


def _race(bars, i, up, down):
    """From bar i+1 on, which is hit first within AHEAD bars: price >= up ('up') or <= down ('down')?"""
    for j in range(i + 1, min(len(bars), i + 1 + AHEAD)):
        hi, lo = bars[j][2], bars[j][3]
        if hi >= up and lo <= down:
            return None  # both inside one bar: unknown order
        if hi >= up:
            return "up"
        if lo <= down:
            return "down"
    return None


def breakouts(bars, atr):
    """Fresh closes above the prior 4h high: share that gained 1 ATR before losing 1 ATR."""
    won = n = 0
    last = -RANGE_BARS
    for i in range(RANGE_BARS + 1, len(bars) - 1):
        if atr[i] is None or i - last < RANGE_BARS:
            continue
        hi = max(b[2] for b in bars[i - RANGE_BARS:i])
        prev_hi = max(b[2] for b in bars[i - 1 - RANGE_BARS:i - 1])
        if bars[i][4] > hi and bars[i - 1][4] <= prev_hi:
            r = _race(bars, i, bars[i][4] + atr[i], bars[i][4] - atr[i])
            if r:
                n += 1
                won += r == "up"
                last = i
    return won, n


def levels(bars, atr):
    """Touches of the prior 24h high or low: share that turned back 1 ATR before going 1 ATR through."""
    held = n = 0
    last = -AHEAD
    for i in range(LEVEL_BARS + 1, len(bars) - 1):
        if atr[i] is None or i - last < AHEAD:
            continue
        w = bars[i - LEVEL_BARS:i]
        res, sup = max(b[2] for b in w), min(b[3] for b in w)
        b = bars[i]
        if b[2] >= res > bars[i - 1][2]:      # first touch of resistance
            r = _race(bars, i, res + atr[i], res - atr[i])
            if r:
                n += 1
                held += r == "down"
                last = i
        elif b[3] <= sup < bars[i - 1][3]:    # first touch of support
            r = _race(bars, i, sup + atr[i], sup - atr[i])
            if r:
                n += 1
                held += r == "up"
                last = i
    return held, n


def volume_moves(bars, atr):
    """Big-volume candles that moved at least half an ATR: share where price 4h later kept that direction."""
    cont = n = 0
    last = -AHEAD
    for i in range(RANGE_BARS, len(bars) - AHEAD):
        if atr[i] is None or i - last < AHEAD:
            continue
        avg = sum(b[5] for b in bars[i - RANGE_BARS:i]) / RANGE_BARS
        move = bars[i][4] - bars[i][1]
        if avg <= 0 or bars[i][5] < 2 * avg or abs(move) < 0.5 * atr[i]:
            continue
        later = bars[i + AHEAD][4] - bars[i][4]
        if later == 0:
            continue
        n += 1
        cont += (later > 0) == (move > 0)
        last = i
    return cont, n


def correlation(a, b):
    n = len(a)
    if n < 30:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if sa == 0 or sb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


def _share(k, n):
    return round(k / n * 100) if n else None


def _evidence(k, n):
    """How far the share is from a coin flip, in standard errors."""
    if not n:
        return 0.0
    return (k / n - 0.5) / math.sqrt(0.25 / n)


# ------------------------------------------------------------------ one coin

def profile(sym, d, btc_hourly=None):
    bars = _bars(d or {})
    if len(bars) < LEVEL_BARS * 3:
        return {"symbol": sym, "style": "not enough data", "candles": len(bars), "notes": []}
    atr = _atr(bars)
    hourly = _hourly(bars)
    hours = sorted(hourly)
    rets = _returns([hourly[h] for h in hours])
    vr4, z4 = variance_ratio(rets, 4)
    vr16, z16 = variance_ratio(rets, 16)
    bw, bn = breakouts(bars, atr)
    lh, ln = levels(bars, atr)
    vc, vn = volume_moves(bars, atr)
    corr = None
    if btc_hourly and sym != "BTC":
        common = [h for h in hours if h in btc_hourly and h - 1 in btc_hourly and h - 1 in hourly]
        a = [math.log(hourly[h] / hourly[h - 1]) for h in common]
        b = [math.log(btc_hourly[h] / btc_hourly[h - 1]) for h in common]
        corr = correlation(a, b)
    last = bars[-1][4]
    atr_pct = (atr[-1] / last * 100) if atr[-1] else None

    trend = "random"
    zs = [z for z in (z4, z16) if z is not None]
    if zs and min(zs) > SURE:
        trend = "trending"
    elif zs and max(zs) < -SURE:
        trend = "mean-reverting"

    be, le, ve = _evidence(bw, bn), _evidence(lh, ln), _evidence(vc, vn)
    style, why = "no clear style", "nothing in the last %d days stands out from a coin flip" % DAYS
    if bn >= MIN_N and be >= SURE and trend != "mean-reverting":
        style, why = "breakout / trend follower", "breakouts above the 4h high carried on %d%% of %d times" % (
            _share(bw, bn), bn)
    elif ln >= MIN_N and le >= SURE and trend != "trending":
        style, why = "range trader (respects support / resistance)", "turned back at the 24h high or low %d%% of %d times" % (
            _share(lh, ln), ln)
    elif bn >= MIN_N and be <= -SURE:
        style, why = "fakeout-prone (breakouts fail)", "breakouts above the 4h high failed %d%% of %d times" % (
            100 - _share(bw, bn), bn)
    elif trend == "trending":
        style, why = "trending", "1-hour moves tended to keep going (variance ratio %.2f)" % (vr16 or vr4)
    elif trend == "mean-reverting":
        style, why = "mean-reverting", "1-hour moves tended to snap back (variance ratio %.2f)" % (vr16 or vr4)

    notes = []
    if corr is not None:
        notes.append("follows BTC closely" if corr >= 0.8 else "partly follows BTC" if corr >= 0.5 else "moves on its own")
    if vn >= MIN_N and ve >= SURE:
        notes.append("big-volume moves continue")
    elif vn >= MIN_N and ve <= -SURE:
        notes.append("big-volume moves fade")
    if atr_pct is not None:
        notes.append("high volatility" if atr_pct >= 1.0 else "low volatility" if atr_pct < 0.35 else "normal volatility")

    return {
        "symbol": sym, "style": style, "why": why, "notes": notes, "candles": len(bars),
        "trend": {"label": trend, "vr_4h": _r(vr4), "z_4h": _r(z4, 1), "vr_16h": _r(vr16), "z_16h": _r(z16, 1)},
        "breakouts": {"follow_pct": _share(bw, bn), "n": bn},
        "levels": {"hold_pct": _share(lh, ln), "n": ln},
        "volume": {"continue_pct": _share(vc, vn), "n": vn},
        "btc_corr": _r(corr), "atr_pct_15m": _r(atr_pct),
    }


def _r(x, k=2):
    return None if x is None else round(x, k)


# ------------------------------------------------------------------ all coins

def build(symbols, fetch, workers=6):
    """fetch(sym) -> chart dict (t, o, h, l, c, v). Returns the profiles document."""
    syms = list(dict.fromkeys(["BTC"] + list(symbols)))
    with ThreadPoolExecutor(workers) as ex:
        charts = dict(zip(syms, ex.map(lambda s: _safe(fetch, s), syms)))
    btc = charts.get("BTC")
    btc_hourly = _hourly(_bars(btc)) if btc else None
    out = {}
    for s in symbols:
        d = charts.get(s)
        out[s] = profile(s, d, btc_hourly) if d else {"symbol": s, "style": "no data", "notes": []}
    return {"as_of": datetime.now(timezone.utc).isoformat(), "days": DAYS, "coins": out}


def _safe(fetch, s):
    try:
        return fetch(s)
    except Exception:
        return None


def due(path=OUT):
    """True if the saved profiles are not from today (UTC)."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc.get("as_of", "")[:10] != datetime.now(timezone.utc).date().isoformat()
    except (OSError, ValueError):
        return True


def refresh_async(symbols, log=print):
    """Rebuild the profiles in a background thread (never delays a scan). No-op if one is running."""
    global _running
    with _lock:
        if _running:
            return False
        _running = True

    def work():
        global _running
        try:
            import scan_crypto as C
            doc = build(symbols, lambda s: C.crypto_chart(s, "%dd" % DAYS, "15m"))
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            tmp = OUT + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=1)
            os.replace(tmp, OUT)
            styles = {}
            for p in doc["coins"].values():
                styles[p["style"]] = styles.get(p["style"], 0) + 1
            log("CRYPTO coin profiles (%d days): %s" % (DAYS, ", ".join("%s %d" % kv for kv in sorted(styles.items()))))
        except Exception as e:
            log("CRYPTO coin profiles failed: %s" % e)
        finally:
            with _lock:
                _running = False

    threading.Thread(target=work, name="coin-profiles", daemon=True).start()
    return True


if __name__ == "__main__":
    import scan_crypto as C
    syms = [s.upper() for s in sys.argv[1:]] or C.universe()[0]
    doc = build(syms, lambda s: C.crypto_chart(s, "%dd" % DAYS, "15m"))
    for s, p in doc["coins"].items():
        print("%-6s %-44s %s | %s" % (s, p["style"], p.get("why", ""), ", ".join(p.get("notes", []))))
