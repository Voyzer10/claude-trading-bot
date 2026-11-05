#!/usr/bin/env python3
"""
sweep_reversal.py - Scanner v3's setup, the owner's "Trading Workflow" PDF (5 Nov 2026), on CLOSED candles.

BUY (low sweep):
  1. BOS: a candle CLOSES above the latest confirmed swing high (pivot, 2 candles each side).
  2. The low to sweep: the low the BOS move started from (lowest low between the broken swing high and the BOS
     candle), OR a swing low that formed after the BOS. Either counts (owner, 5 Nov).
  3. Sweep: a RED candle trades below that low AND CLOSES below it (a wick alone is not a sweep), within bos_max
     candles of the BOS. Only the first close below a level counts.
  4. Signal: a doji or an inverted hammer (any colour) at the low: the sweep candle itself or one of the next
     sig_max candles, its low within near_atr x ATR of the lowest low since the sweep.
  5. Confirmation: one of the next conf_max (= 2) candles CLOSES above the trigger: the signal candle's high
     ("signal"), the sweep candle's high ("sweep"), or whichever is lower ("either", the live reading: the owner
     said both cases count). A close below the swept extreme first cancels it.
  6. Skip if extended: the confirmation candle's range is over ext_range_atr (2) x ATR, or the entry is more than
     ext_dist_atr (3) x ATR above the swept extreme.
  7. Stop: the swept extreme minus 0.1 ATR. Target: the nearest of the BOS move's high and the untaken swing highs
     above the entry (the opposing liquidity), with a minimum R:R (1 live; the backtest also tries 2, 1R and 2R).

SELL = the same machine on prices turned upside down (bearish BOS, a GREEN candle closes above the high it
sweeps, doji or hammer at the top, a close below the trigger).
"""
import smc_playbook as PB


def mirror(rows):
    return [(r[0], -r[1], -r[3], -r[2], -r[4], r[5]) for r in rows]


def signals(rows, day_of, trigger="either", level="any", ext=True, bos_max=48, sig_max=3, conf_max=2,
            doji_pct=0.15, near_atr=0.5, ext_range_atr=2.0, ext_dist_atr=3.0, short=False, ctx=None):
    """Every entry over rows (t, o, h, l, c, v), oldest first. Returns (ctx, [signal dicts]). ext=False keeps the
    extended entries too (flagged "extended") so the backtest can score the filter. A short's prices are returned in
    normal terms; ctx is the (mirrored, for shorts) context, reusable for the same rows and side."""
    src = mirror(rows) if short else rows
    ctx = ctx or PB.Context(src, day_of)
    bars, n, out, taken = src, len(src), [], set()
    sg = -1 if short else 1
    bos = None
    for j in range(30, n):
        if ctx.bull[j]:
            sh_i, sh_px = ctx.sh_known[j - 1][-1]
            bos = {"i": j, "level": sh_px, "origin": min(bars[k][3] for k in range(sh_i, j + 1))}
            continue
        if bos is None or j - bos["i"] > bos_max:
            continue
        o, h, l, c = bars[j][1], bars[j][2], bars[j][3], bars[j][4]
        if not c < o:
            continue
        lv = []
        if level in ("any", "origin"):
            lv.append(("bos_origin", bos["origin"]))
        if level in ("any", "post"):
            lv += [("post_bos", p) for idx, p in ctx.sl_known[j - 1] if idx > bos["i"]]
        hit = [(nm, p) for nm, p in lv if l < p and c < p
               and all(bars[k][4] >= p for k in range(bos["i"], j))]        # the first close below it since the BOS
        if not hit:
            continue
        lname, lvl = max(hit, key=lambda x: x[1])
        # signal candle at the low
        s_i = None
        for s in range(j, min(n, j + sig_max + 1)):
            a = ctx.atr[s]
            if not a:
                break
            low_so_far = min(bars[k][3] for k in range(j, s + 1))
            pats = PB.patterns(bars[s], doji_pct)
            if ("doji" in pats or "star" in pats) and bars[s][3] <= low_so_far + near_atr * a:
                s_i = s
                break
        if s_i is None:
            continue
        extreme = min(bars[k][3] for k in range(j, s_i + 1))
        t_sig, t_sw = bars[s_i][2], h
        trig = {"signal": t_sig, "sweep": t_sw, "either": min(t_sig, t_sw)}[trigger]
        for i in range(s_i + 1, min(n, s_i + conf_max + 1)):
            ci = bars[i][4]
            if ci > trig:
                a = ctx.atr[i]
                if not a or i in taken:
                    break
                ext_range = (bars[i][2] - bars[i][3]) > ext_range_atr * a
                ext_dist = (ci - extreme) > ext_dist_atr * a
                if ext and (ext_range or ext_dist):
                    break
                taken.add(i)
                move_hi = max(bars[k][2] for k in range(bos["i"], j + 1))
                # swing highs price has not traded through since they formed (a broken high is no liquidity)
                tgts = [move_hi] + [p for idx, p in ctx.sh_known[i]
                                    if max(bars[k][2] for k in range(idx + 1, i + 1)) < p]
                tgts = [p for p in tgts if p > ci]
                out.append({"i": i, "side": "short" if short else "long", "bos": bos["i"], "sweep": j, "signal": s_i,
                            "level_name": lname, "level": sg * lvl, "bos_level": sg * bos["level"],
                            "entry": sg * ci, "extreme": sg * extreme, "atr": a,
                            "trigger": trigger, "trigger_px": sg * trig, "signal_high": sg * t_sig,
                            "sweep_high": sg * t_sw, "above_signal": ci > t_sig, "above_sweep": ci > t_sw,
                            "conf_offset": i - s_i, "signal_pattern": "doji" if "doji" in PB.patterns(bars[s_i], doji_pct)
                            else ("hammer" if short else "inverted hammer"),
                            "extended": ext_range or ext_dist, "ext_range": ext_range, "ext_dist": ext_dist,
                            "swing_target": sg * min(tgts) if tgts else None})
                break
            if ci < extreme:
                break
    return ctx, out


def stop_for(sig, buffer_atr=0.1):
    a = sig["atr"] * buffer_atr
    return sig["extreme"] - a if sig["side"] == "long" else sig["extreme"] + a


def target_for(sig, mode, stop):
    """mode: 1R | 2R | swing (the opposing liquidity; None if there is none). The caller applies the min R:R."""
    entry, long = sig["entry"], sig["side"] == "long"
    risk = (entry - stop) if long else (stop - entry)
    if mode in ("1R", "2R"):
        k = 1.0 if mode == "1R" else 2.0
        return entry + k * risk if long else entry - k * risk
    return sig["swing_target"]


def rr(sig, stop, target):
    risk = abs(sig["entry"] - stop)
    return abs(target - sig["entry"]) / risk if risk > 0 and target is not None else 0.0
