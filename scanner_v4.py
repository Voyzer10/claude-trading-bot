#!/usr/bin/env python3
"""
scanner_v4.py - Scanner v4, the owner's "Final Trading Workflow" PDF (7 Nov 2026). No rule of Scanner v2 or v3.
Closed candles only; shorts are the same rules on prices turned upside down.

PRIMARY (BUY; SELL is the mirror)
  1. BOS: a candle CLOSES above the latest confirmed swing high (a wick through it is not a BOS).
  2. Liquidity sweep: price trades BELOW an old low (the low the BOS move started from, or a swing low formed after
     the BOS) - by a wick or a whole candle - and then RECLAIMS it: a close back above the level within
     reclaim_max candles. Price that stays below (accepts) cancels the idea.
  3. Signal at the low: a doji, hammer or inverted hammer (any colour) within sig_max candles of the sweep, its low
     near the sweep extreme. The candle alone is not an entry.
  4. Trigger: one of the next conf_max candles BREAKS and CLOSES above the signal candle's high, with the level
     reclaimed by then. A close below the sweep extreme first cancels it. Extended moves are skipped (no chasing).
  5. Stop beyond the sweep extreme (+ buffer); target = the next liquidity (the BOS move's high or an untaken
     swing high). Poor R:R (under min_rr) -> skip.

SECONDARY (OB / FVG), strictly in sequence - the PDF's bot hard gate:
     secondary_enabled = primary_trade_closed AND valid_zone_exists
     entry_allowed     = secondary_enabled AND zone_tapped AND confirmation_closed
  6. Only after the primary trade is CLOSED (target, stop or time exit) - never overlapping it.
  7. A real zone from the primary move must exist: the bullish order block (the last bearish candle between the
     sweep and the trigger) or a bullish FVG in the move (candle 1 high .. candle 3 low). A zone closed through is
     invalid. No zone -> stay flat.
  8. Price must TAP the zone (trade into it; near is not enough) after the primary closed, without closing through.
  9. Confirmation: within conf_max candles of the tap, a candle CLOSES above the tap candle's high. Then the
     secondary entry, stop beyond the zone, target the next liquidity, R:R >= min_rr.
 10. After the secondary (or when there is no zone / no tap / a fresh primary appears) the sequence resets.

One sequence per chart: while a primary or a secondary is open, or a secondary is being looked for, no new
primary is taken. The trades are walked candle by candle (stop first when a candle touches both) to know when they
close; intraday markets close at the day's last candle.
"""
import smc_playbook as PB


def mirror(rows):
    return [(r[0], -r[1], -r[3], -r[2], -r[4], r[5]) for r in rows]


DEFAULTS = {"bos_max": 48, "reclaim_max": 3, "sig_max": 3, "conf_max": 2, "near_atr": 0.5, "ext_range_atr": 2.0,
            "ext_dist_atr": 3.0, "buffer_atr": 0.1, "min_rr": 1.0, "zone_window": 48, "leg_max": 24,
            "max_hold": 48, "doji_pct": 0.15}


def _targets(ctx, bars, i, entry, extra=()):
    """Liquidity above `entry` known at candle i: untaken confirmed swing highs, plus `extra` levels."""
    out = [p for p in extra if p > entry]
    for idx, p in ctx.sh_known[i]:
        if p > entry and max(bars[k][2] for k in range(idx + 1, i + 1)) < p:
            out.append(p)
    return min(out) if out else None


def primaries(src, ctx, p):
    """Every primary entry on src (normal prices for longs, mirrored for shorts). Stateless: the sequence decides
    which ones are taken."""
    bars, n, out, taken = src, len(src), [], set()
    bos, used = None, set()
    for j in range(30, n):
        if ctx.bull[j]:
            sh_i, sh_px = ctx.sh_known[j - 1][-1]
            bos = {"i": j, "level": sh_px, "origin": min(bars[k][3] for k in range(sh_i, j + 1))}
            continue
        if bos is None or j - bos["i"] > p["bos_max"]:
            continue
        lv = [("bos_origin", bos["origin"])] + [("post_bos", px) for idx, px in ctx.sl_known[j - 1] if idx > bos["i"]]
        hit = [(nm, px) for nm, px in lv if bars[j][3] < px and (nm, px) not in used
               and all(bars[k][3] >= px for k in range(bos["i"], j))]        # the first trade below it since the BOS
        if not hit:
            continue
        lname, lvl = max(hit, key=lambda x: x[1])
        used.add((lname, lvl))
        # reclaim: a close back above the level within reclaim_max candles (the sweep candle itself counts)
        rec = next((k for k in range(j, min(n, j + p["reclaim_max"] + 1)) if bars[k][4] > lvl), None)
        if rec is None:
            continue                                                         # accepted below: no reversal idea
        # signal candle at the low
        s_i = None
        for s in range(j, min(n, j + p["sig_max"] + 1)):
            a = ctx.atr[s]
            if not a:
                break
            low = min(bars[k][3] for k in range(j, s + 1))
            pats = PB.patterns(bars[s], p["doji_pct"])
            if pats & {"doji", "hammer", "star"} and bars[s][3] <= low + p["near_atr"] * a:
                s_i = s
                break
        if s_i is None:
            continue
        extreme = min(bars[k][3] for k in range(j, s_i + 1))
        trig = bars[s_i][2]
        for i in range(s_i + 1, min(n, s_i + p["conf_max"] + 1)):
            c = bars[i][4]
            if c < extreme:
                break
            if c > trig and c > lvl and rec <= i:
                a = ctx.atr[i]
                if not a or i in taken:
                    break
                if (bars[i][2] - bars[i][3]) > p["ext_range_atr"] * a or (c - extreme) > p["ext_dist_atr"] * a:
                    break                                                    # extended: no chasing
                stop = extreme - p["buffer_atr"] * a
                move_hi = max(bars[k][2] for k in range(bos["i"], j + 1))
                tgt = _targets(ctx, bars, i, c, (move_hi,))
                if tgt is None or (tgt - c) < p["min_rr"] * (c - stop):
                    break                                                    # poor R:R
                taken.add(i)
                pats = PB.patterns(bars[s_i], p["doji_pct"])
                out.append({"i": i, "kind": "primary", "bos": bos["i"], "sweep": j, "reclaim": rec, "signal": s_i,
                            "level_name": lname, "level": lvl, "extreme": extreme, "entry": c, "stop": stop,
                            "target": tgt, "atr": a, "trigger_px": trig,
                            "signal_pattern": "doji" if "doji" in pats else ("hammer" if "hammer" in pats else "star")})
                break
    return out


def _walk(bars, day, i, entry, stop, target, p, intraday):
    """Walk a long (src terms) from candle i+1: stop first, then target, intraday day end, max_hold.
    Returns (exit index, exit price, reason) or (None, None, 'open') if the data ends first."""
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
            return None, None, "open"
        if k - i >= p["max_hold"]:
            return k, c, "time"
    return None, None, "open"


def _zones(bars, prim, upto):
    """Bullish OB and FVGs of the primary move (src terms), formed up to candle `upto`."""
    j, i, s = prim["sweep"], prim["i"], prim["signal"]
    zones = []
    reds = [k for k in range(j, i) if bars[k][4] < bars[k][1]]
    if reds:
        k = reds[-1]
        zones.append({"name": "OB", "top": bars[k][2], "bot": bars[k][3], "born": i})
    for k in range(max(s + 2, 2), upto + 1):
        if bars[k][3] > bars[k - 2][2] and bars[k - 1][4] > bars[k - 1][1]:
            zones.append({"name": "FVG", "top": bars[k][3], "bot": bars[k - 2][2], "born": k})
    return zones


def secondary(bars, ctx, prim, closed_at, stop_at, p):
    """The OB / FVG secondary after a primary closed at candle closed_at; looked for until stop_at (exclusive):
    zone must exist, be tapped, then confirmed by a close above the tap candle's high. None if there is none."""
    n = len(bars)
    zones = [z for z in _zones(bars, prim, min(closed_at, prim["i"] + p["leg_max"])) if z["born"] <= closed_at]
    for z in zones:              # closed through before the scan starts -> invalid
        z["dead"] = any(bars[k][4] < z["bot"] for k in range(z["born"] + 1, closed_at + 1))
    zones = [z for z in zones if not z["dead"]]
    if not zones:
        return None, "no valid zone"
    end = min(n, closed_at + 1 + p["zone_window"], stop_at)
    t = closed_at + 1
    while t < end:
        o, h, l, c = bars[t][1], bars[t][2], bars[t][3], bars[t][4]
        for z in zones:
            if c < z["bot"]:
                z["dead"] = True
        live = [z for z in zones if not z["dead"]]
        if not live:
            return None, "zone invalidated"
        tapped = [z for z in live if l <= z["top"]]
        if tapped:
            z = max(tapped, key=lambda x: x["top"])
            for i in range(t + 1, min(n, t + p["conf_max"] + 1, end + p["conf_max"])):
                ci = bars[i][4]
                if ci < z["bot"]:
                    break
                if ci > bars[t][2]:
                    a = ctx.atr[i]
                    if not a:
                        break
                    stop = z["bot"] - p["buffer_atr"] * a
                    move_hi = max(bars[k][2] for k in range(prim["i"], i + 1))
                    tgt = _targets(ctx, bars, i, ci, (move_hi,))
                    if tgt is None or (tgt - ci) < p["min_rr"] * (ci - stop):
                        return None, "poor R:R"
                    return {"i": i, "kind": "secondary", "zone": z["name"], "zone_top": z["top"],
                            "zone_bottom": z["bot"], "tap": t, "entry": ci, "stop": stop, "target": tgt, "atr": a,
                            "primary_at": prim["i"], "primary_closed_at": closed_at}, "entry"
            t += 1
            continue
        t += 1
    return None, "no tap / no confirmation"


def sequence(rows, day_of, intraday=False, **kw):
    """Scanner v4 on one chart: every primary and secondary trade, in order, each with its simulated exit.
    Prices are normal (shorts un-mirrored). Returns a list of dicts sorted by entry candle."""
    p = dict(DEFAULTS, **kw)
    mrows = mirror(rows)
    sides = {}
    for short in (False, True):
        src = mrows if short else rows
        ctx = PB.Context(src, day_of)
        sides[short] = (src, ctx, primaries(src, ctx, p))
    day = [day_of(r[0]) for r in rows]
    cands = sorted([(c["i"], short, c) for short in (False, True) for c in sides[short][2]], key=lambda x: (x[0], x[1]))
    out, free = [], 0
    for idx, (i, short, prim) in enumerate(cands):
        if i < free:
            continue
        src, ctx, _ = sides[short]
        k, px, why = _walk(src, day, i, prim["entry"], prim["stop"], prim["target"], p, intraday)
        out.append(_real(dict(prim, exit_i=k, exit=px, exit_reason=why), short))
        if k is None:
            break                                            # primary still open: nothing else on this chart
        nxt = next((c[0] for c in cands[idx + 1:] if c[0] > k), len(rows))
        sec, note = secondary(src, ctx, prim, k, nxt, p)
        out[-1]["secondary_note"] = note
        if sec is None:
            free = k + 1
            continue
        k2, px2, why2 = _walk(src, day, sec["i"], sec["entry"], sec["stop"], sec["target"], p, intraday)
        out.append(_real(dict(sec, exit_i=k2, exit=px2, exit_reason=why2), short))
        if k2 is None:
            break
        free = k2 + 1
    return out


def _real(t, short):
    """src-terms trade -> normal prices and a side."""
    t = dict(t)
    t["side"] = "short" if short else "long"
    if short:
        for f in ("level", "extreme", "entry", "stop", "target", "trigger_px", "zone_top", "zone_bottom", "exit"):
            if t.get(f) is not None:
                t[f] = -t[f]
        if t.get("zone_top") is not None:
            t["zone_top"], t["zone_bottom"] = t["zone_bottom"], t["zone_top"]
    return t


def rr(t):
    risk = abs(t["entry"] - t["stop"])
    return abs(t["target"] - t["entry"]) / risk if risk > 0 else 0.0
