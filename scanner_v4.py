#!/usr/bin/env python3
"""
scanner_v4.py - Scanner v4: the owner's rules of 11 Nov 2026, from "Final Trading Workflow (complete, merged pages
2 to 5)" and his answers to five rounds of questions (every open point of the PDF decided by him, not by the code).
Completed candles only; shorts are the same rules on prices turned upside down (a real hammer at a top is the
mirror of an inverted hammer at a low). No rule of Scanner v2 / v3 / v5 or the older rules.

PRIMARY BUY (SELL is the mirror)
  1. BOS: a completed candle CLOSES above the latest confirmed swing high (a wick through it is not a BOS). A
     reversal also needs this bullish BOS (the CHoCH) first. Swings are confirmed causally: a pivot is known once
     2 candles have closed after it (smc_playbook.Context, k=2), whatever the shape of the move.
     Every BOS starts its own setup; all stay active, buy and sell, until one is traded (owner: "jitne bhi bane
     saare active ho"), except the intraday day rule below.
  2. Sweep: after that BOS, a completed candle CLOSES BELOW an old low: the low the BOS move started from, or a
     confirmed swing low formed after the BOS. A wick below is not a sweep. Further closes lower only deepen it.
  3. Signal: after the sweep, at any time, one of the owner's buying candles (12 Nov 2026), any colour: classic doji,
     gravestone doji, long-legged doji (body <= 15% of the range) or inverted hammer. A dragonfly doji or a hammer
     is not a BUY signal (they are the SELL signals at a top). See signal_kind().
  4. Trigger: the 1st or 2nd candle after the signal CLOSES ABOVE THE SIGNAL CANDLE'S HIGH (that close may still be
     below the swept low). No trigger in 2 candles: a later signal candle gives a new chance.
  5. Entry: right after the trigger candle closes, at the current price (backtest: the next candle's open).
  6. Stop: below the lowest low from the sweep candle to the signal candle, minus 0.1 ATR.
  7. Target: the nearest untaken liquidity above the entry (a confirmed swing high, or the BOS move's high). The
     target must be above the entry; there is no minimum reward:risk (min_rr = 0; the backtest also tries 1 and 2).
  8. Trade Manager, trailing only: at +1R the stop goes to the entry, at +2R to +1R, then up 1R per R. No other
     exit (intraday charts still close at the session's end). Settable per account (Settings > Trade Manager:
     v4_trail, v4_be_r, v4_trail_step, v4_trail_gap; trail_lock_r()).
  Intraday charts (NSE / US 5-minute; owner, 12 Nov 2026): at the session's start only the previous day's BOS
  setups whose sweep has not happened stay active, and for that day only; today's BOS add up as they form. Setups
  that were swept but not traded, and older ones, end with their day. Crypto (no session) keeps every setup.
  One trade at a time per chart. A setup that triggers while a trade is open is skipped but stays active; when two
  trigger on the same candle, the oldest BOS is taken. One trade per setup.

SECONDARY (OB / FVG), strictly after the primary trade CLOSED:
  9. A real zone of the primary move must exist and be unbroken (not closed through): the order block (the last
     bearish candle between the sweep and the trigger) or a 3-candle FVG (candle 1 high below candle 3 low).
 10. Entry when a candle TAPS the zone and is itself a signal candle (the buying candles for a buy; mirrored
     for a sell), closing inside or above the zone: entry right after it closes. Stop below the zone (or that
     candle's low, if lower) minus 0.1 ATR; target and Trade Manager as above. At most one secondary per primary;
     a new primary trade ends the search.

SKIPS: none. BOS = a close above the last swing high (higher high) / below the last swing low (lower low), nothing
more (owner, 12 Nov 2026, the BULLISH / BEARISH BOS image: "high ke upper break and close kre to hi higher high ...
bn gya bos"). The weak-BOS check (bos_body_atr 0.8 ATR body, bos_vol_x 1.2x volume) is off; the backtest can still
switch it on (variant with_weak_bos), as it can the 1-hour trend skip (htf). Chop and opposing-zone filters: off.
"""
import smc_playbook as PB


def mirror(rows):
    return [(r[0], -r[1], -r[3], -r[2], -r[4], r[5]) for r in rows]


# the v4 Trade Manager (trailing only), per account in Settings > Trade Manager (owner, 13 Nov 2026); defaults =
# the owner's 11 Nov rule: +1R -> the entry, +2R -> +1R, then 1R higher per R
TRAIL_KEYS = ("trail", "v4_be_r", "v4_trail_step", "v4_trail_gap")
DEFAULTS = {"buffer_atr": 0.1, "min_rr": 0.0, "v4_be_r": 1.0, "v4_trail_step": 1.0, "v4_trail_gap": 1.0, "doji_pct": 0.15, "conf_max": 2, "max_hold": None, "trail": True,
            # BOS by close only (owner, 12 Nov 2026): the weak-BOS check is off (0); the backtest can set 0.8 / 1.2
            "htf": False, "bos_body_atr": 0, "bos_vol_x": 0, "vol_n": 20,
            # off by the owner's choice (kept so older backtest settings still run)
            "chop_er": 0, "er_n": 20, "opp_zone": False, "opp_lookback": 48}

# The signal candle (owner, 12 Nov 2026, "Trading candlestick patterns for buying & selling"), any colour.
#   BUY at the low:  classic doji, gravestone doji, long-legged doji, inverted hammer
#   SELL at the top: classic doji, dragonfly doji, long-legged doji, hammer
# A dragonfly doji or a hammer at a low is NOT a buy signal; a gravestone doji or an inverted hammer at a top is NOT a
# sell signal. Shorts read mirrored prices, so one classifier (src terms) serves both: a real dragonfly at a top is
# a gravestone in src terms, a real hammer an inverted hammer.
TRIGGERS = {"doji", "gravestone doji", "long-legged doji", "inverted hammer"}
SHORT_NAME = {"gravestone doji": "dragonfly doji", "inverted hammer": "hammer"}


def signal_kind(bar, doji_pct=0.15, tiny=0.10, leg=0.30):
    """The signal-candle name of one candle in src terms, or None. Shares of the candle's range (high - low):
    doji = body <= doji_pct; a doji whose upper wick is < tiny is a dragonfly (not a buy signal); lower wick < tiny
    = gravestone; both wicks >= leg = long-legged. Inverted hammer = upper wick >= 2 x body and >= half the range,
    lower wick <= a quarter."""
    o, h, l, c = bar[1], bar[2], bar[3], bar[4]
    rng = h - l
    if rng <= 0:
        return None
    body, up, lo = abs(c - o), h - max(o, c), min(o, c) - l
    if body <= doji_pct * rng:
        if up < tiny * rng:
            return None                    # dragonfly doji (src): a sell signal only, at a top
        if lo < tiny * rng:
            return "gravestone doji"
        if up >= leg * rng and lo >= leg * rng:
            return "long-legged doji"
        return "doji"
    if up >= 2 * body and up >= 0.5 * rng and lo <= 0.25 * rng:
        return "inverted hammer"
    return None


def efficiency(bars, j, n):
    """Kaufman efficiency ratio of the n closes up to candle j: |net move| / sum of |moves| (1 = straight line)."""
    if j - n < 0:
        return None
    path = sum(abs(bars[k][4] - bars[k - 1][4]) for k in range(j - n + 1, j + 1))
    return abs(bars[j][4] - bars[j - n][4]) / path if path > 0 else 0.0


def htf_dirs(bars, day_of, minutes=60):
    """For every candle: the higher-timeframe trend known when it closed, from completed `minutes` candles built out
    of these ones: "up" (last HTF BOS bullish), "down" (bearish) or None. In src terms (mirrored for shorts)."""
    n = len(bars)
    if n < 2:
        return [None] * n
    step = min(bars[k + 1][0] - bars[k][0] for k in range(min(n - 1, 50)))
    hb, idx_end = [], []          # hour candles and the index of their last small candle
    for k, b in enumerate(bars):
        ts = b[0].timestamp()
        key = int(ts // (minutes * 60))
        if hb and hb[-1][6] == key:
            t, o, h, l, c, v, _ = hb[-1]
            hb[-1] = (t, o, max(h, b[2]), min(l, b[3]), b[4], v + (b[5] or 0), key)
            idx_end[-1] = k
        else:
            hb.append((b[0], b[1], b[2], b[3], b[4], b[5] or 0, key))
            idx_end.append(k)
    hbars = [x[:6] for x in hb]
    if len(hbars) < 8:
        return [None] * n
    hctx = PB.Context(hbars, day_of)
    hdir, cur = [], None
    for m in range(len(hbars)):
        if hctx.bull[m]:
            cur = "up"
        elif hctx.bear[m]:
            cur = "down"
        hdir.append(cur)
    out, m, known = [None] * n, -1, None
    span = minutes * 60
    for k in range(n):
        close_t = bars[k][0] + step
        # hour candles completed by the close of candle k
        while m + 1 < len(hb) and (hb[m + 1][6] + 1) * span <= close_t.timestamp():
            m += 1
            known = hdir[m]
        out[k] = known
    return out


def opposing_zone(bars, i, entry, risk, lookback):
    """An unfilled bearish FVG (src terms: candle k's high below candle k-2's low) overlapping (entry, entry + 1R)."""
    lo, hi = entry, entry + risk
    for k in range(max(2, i - lookback), i + 1):
        top, bot = bars[k - 2][3], bars[k][2]
        if bot >= top:
            continue
        if any(bars[q][4] > top for q in range(k + 1, i + 1)):
            continue                                          # filled: price closed back above it
        if bot < hi and top > lo:
            return (bot, top)
    return None


def _targets(ctx, bars, i, entry, extra=()):
    """Liquidity above `entry` known at candle i: untaken confirmed swing highs, plus `extra` levels."""
    out = [p for p in extra if p > entry]
    for idx, p in ctx.sh_known[i]:
        if p > entry and max(bars[k][2] for k in range(idx + 1, i + 1)) < p:
            out.append(p)
    return min(out) if out else None


def bos_quality(bars, ctx, j, p):
    """The PDF's page-1 checks on a BOS candle j: not out of chop, decisive body, volume. (ok, why-not)."""
    if p.get("chop_er"):
        er = efficiency(bars, j, p["er_n"])
        if er is not None and er < p["chop_er"]:
            return False, "choppy before the BOS (efficiency %.2f < %.2f)" % (er, p["chop_er"])
    a = ctx.atr[j]
    if p.get("bos_body_atr") and a:
        body = abs(bars[j][4] - bars[j][1])
        if body < p["bos_body_atr"] * a:
            return False, "weak BOS candle (body %.2f ATR)" % (body / a)
    if p.get("bos_vol_x") and j >= p["vol_n"]:
        vols = [bars[k][5] or 0 for k in range(j - p["vol_n"], j)]
        avg = sum(vols) / len(vols)
        if avg > 0 and (bars[j][5] or 0) > 0 and bars[j][5] < p["bos_vol_x"] * avg:
            return False, "BOS volume %.2fx (< %.1fx)" % (bars[j][5] / avg, p["bos_vol_x"])
    return True, None


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



class _Range:
    """O(1) min / max of a list over [a, b] (sparse table), for the never-cancelled setups' long look-backs."""

    def __init__(self, xs, fn):
        self.fn, self.t = fn, [list(xs)]
        k = 1
        while (1 << k) <= len(xs):
            prev, half = self.t[-1], 1 << (k - 1)
            self.t.append([fn(prev[i], prev[i + half]) for i in range(len(xs) - (1 << k) + 1)])
            k += 1

    def q(self, a, b):
        k = (b - a + 1).bit_length() - 1
        return self.fn(self.t[k][a], self.t[k][b - (1 << k) + 1])


class _Side:
    """The setups of one side of a chart (src terms), advanced candle by candle."""

    def __init__(self, src, ctx, htf, p, day=None):
        self.b, self.ctx, self.htf, self.p = src, ctx, htf, p
        self.day = day            # session days (intraday charts): setups carry over one day only if unswept
        self.setups = []          # every BOS setup, oldest first: {"bos", "level", "origin", "sweep", "lvl", "used"}
        self.waiting = []         # not swept yet
        self.pats = {}
        self.lows = _Range([r[3] for r in src], min)
        self.highs = _Range([r[2] for r in src], max)

    def pat(self, k):
        """The signal-candle name of candle k (src terms), or None."""
        if k not in self.pats:
            self.pats[k] = signal_kind(self.b[k], self.p["doji_pct"])
        return self.pats[k]

    def step(self, j):
        """Advance to candle j; return the primary trigger of candle j or None:
        {"setup", "i", "signal", "entry" (close), "stop", "target", "atr", ...} (the oldest active setup)."""
        b, ctx, p = self.b, self.ctx, self.p
        c = b[j][4]
        if self.day is not None and j > 0 and self.day[j] != self.day[j - 1]:
            # a new session (owner, 12 Nov 2026, 5-minute intraday): only the previous day's BOS setups whose sweep
            # has not happened stay active, for this day only; swept-but-untraded and older setups end
            prev = self.day[j - 1]
            keep = [st for st in self.setups if not st["used"] and st["sweep"] is None and st["day"] == prev]
            self.setups, self.waiting = keep, [st for st in keep]
        # sweeps first: a close below the setup's BOS-start low or a swing low confirmed after its BOS
        still = []
        for st in self.waiting:
            if j <= st["bos"]:
                still.append(st)
                continue
            lv = [("bos_origin", st["origin"])] + [("post_bos", px) for idx, px in ctx.sl_known[j - 1]
                                                  if idx > st["bos"]]
            broken = [(nm, px) for nm, px in lv if c < px]
            if broken:
                st["lvl_name"], st["lvl"] = max(broken, key=lambda x: x[1])
                st["sweep"] = j
            else:
                still.append(st)
        self.waiting = still
        if ctx.bull[j] and ctx.sh_known[j - 1]:
            ok, _ = bos_quality(b, ctx, j, p)
            if ok:
                sh_i, sh_px = ctx.sh_known[j - 1][-1]
                st = {"bos": j, "level": sh_px, "origin": self.lows.q(sh_i, j), "sweep": None, "used": False,
                      "day": self.day[j] if self.day is not None else None}
                self.setups.append(st)
                self.waiting.append(st)
        # trigger: candle j closes above the high of a signal 1 or 2 candles back
        for s in range(j - 1, max(j - p["conf_max"], 0) - 1, -1):
            if not self.pat(s) or c <= b[s][2]:
                continue
            a = ctx.atr[j]
            if not a or (p.get("htf") and self.htf is not None and self.htf[j] == "down"):
                return None
            liq = _targets(ctx, b, j, c)          # the swing-high liquidity, the same for every setup
            self.setups = [st for st in self.setups if not st["used"]]
            for st in self.setups:              # oldest BOS first
                if st["used"] or st["sweep"] is None or st["sweep"] >= s:
                    continue
                t = self._trade(st, s, j, a, liq)
                if t:
                    return t
            break
        return None

    def _trade(self, st, s, j, a, liq):
        b, p = self.b, self.p
        c = b[j][4]
        stop = self.lows.q(st["sweep"], s) - p["buffer_atr"] * a
        move_hi = self.highs.q(st["bos"], st["sweep"])
        tgt = min([x for x in (liq, move_hi if move_hi > c else None) if x is not None], default=None)
        if tgt is None or stop >= c or (tgt - c) < p["min_rr"] * (c - stop):
            return None
        return {"i": j, "kind": "primary", "setup": st, "bos": st["bos"], "sweep": st["sweep"], "reclaim": st["sweep"],
                "signal": s, "level_name": st["lvl_name"], "level": st["lvl"], "entry": c, "stop": stop,
                "target": tgt, "atr": a, "trigger_px": b[s][2], "signal_pattern": self.pat(s)}

    def secondary_at(self, prim, k_exit, m):
        """The OB / FVG secondary on candle m after the primary closed at candle k_exit, or None; "dead" when no
        valid zone is left. Zones: the primary move's, born by k_exit, never closed through since."""
        b, ctx, p = self.b, self.ctx, self.p
        zones = prim.setdefault("_zones", None)
        if zones is None:
            zones = [z for z in _zones(b, prim, k_exit) if z["born"] <= k_exit]
            for z in zones:
                z["dead"] = any(b[k][4] < z["bot"] for k in range(z["born"] + 1, k_exit + 1))
            prim["_zones"] = zones
        o, h, l, c = b[m][1], b[m][2], b[m][3], b[m][4]
        for z in zones:
            if not z["dead"] and c < z["bot"]:
                z["dead"] = True
        live = [z for z in zones if not z["dead"]]
        if not live:
            return "dead"
        tapped = [z for z in live if l <= z["top"] and h >= z["bot"]]
        if not tapped or not self.pat(m):
            return None
        z = max(tapped, key=lambda x: x["top"])
        a = ctx.atr[m]
        if not a:
            return None
        stop = min(z["bot"], l) - p["buffer_atr"] * a
        tgt = _targets(ctx, b, m, c, (self.highs.q(prim["i"], m),))
        if tgt is None or stop >= c or (tgt - c) < p["min_rr"] * (c - stop):
            return None
        if p.get("htf") and self.htf is not None and self.htf[m] == "down":
            return None
        return {"i": m, "kind": "secondary", "zone": z["name"], "zone_top": z["top"], "zone_bottom": z["bot"],
                "tap": m, "entry": c, "stop": stop, "target": tgt, "atr": a, "primary_at": prim["i"],
                "primary_closed_at": k_exit, "signal_pattern": self.pat(m)}


def trail_lock_r(gain_r, p):
    """Where the v4 trailing stop goes, in R from the entry (0 = the entry), for a best price gain_r R in profit, or
    None (not moved yet). Breakeven at +v4_be_r R (0 = no breakeven move); then for every whole v4_trail_step R the
    stop sits v4_trail_gap R behind it (step 1, gap 1: +2R -> +1R, +3R -> +2R)."""
    lock = None
    be = float(p.get("v4_be_r", 1.0) or 0)
    if be > 0 and gain_r + 1e-9 >= be:
        lock = 0.0
    step, gap = float(p.get("v4_trail_step", 1.0) or 0), float(p.get("v4_trail_gap", 1.0) or 0)
    if step > 0:
        k = int(gain_r / step + 1e-9)
        if k >= 1 and k * step - gap > 1e-9:
            lock = max(lock or 0.0, k * step - gap)
    return lock


def _exit_step(bars, k, tr, p, day, intraday):
    """One candle of an open trade (src terms, long): stop first, then target, then the trailing stop for the next
    candle, then the session's end. Returns (exit price, reason) or None."""
    o, h, l, c = bars[k][1], bars[k][2], bars[k][3], bars[k][4]
    if l <= tr["cur_stop"]:
        why = tr.get("stop_kind", "stop")
        return (o if o < tr["cur_stop"] else tr["cur_stop"]), why
    if h >= tr["target"]:
        return (o if o > tr["target"] else tr["target"]), "target"
    if p.get("trail"):
        risk = tr["entry"] - tr["stop"]
        lock = trail_lock_r((h - tr["entry"]) / risk, p) if risk > 0 else None
        if lock is not None:
            ns = tr["entry"] + lock * risk
            if ns > tr["cur_stop"]:
                tr["cur_stop"] = ns
                tr["stop_kind"] = "breakeven stop" if lock == 0 else "trailing stop"
    if intraday and k + 1 < len(bars) and day[k + 1] != day[k]:
        return c, "day end"
    if p.get("max_hold") and k - tr["i"] >= p["max_hold"]:
        return c, "time"
    return None


def _fill(bars, day, t, intraday):
    """The entry of a signal on candle t["i"]: the next candle's open. (price, None), or (None, why): "pending" when
    that candle has not opened yet (the live scan), or a skip."""
    i, n = t["i"], len(bars)
    if i + 1 >= n:
        return None, "pending"
    if intraday and day[i + 1] != day[i]:
        return None, "the session ended before the next open"
    o = bars[i + 1][1]
    if o <= t["stop"] or o >= t["target"]:
        return None, "opened past the stop / target"
    return o, None


def contexts(rows, day_of, htf=True):
    """Everything sequence() needs that does not depend on the settings: build once per chart, pass as ctxs=."""
    m = mirror(rows)
    cl, cs = PB.Context(rows, day_of), PB.Context(m, day_of)
    return {"rows": rows, "mirror": m, "ctx": (cl, cs), "day": [day_of(r[0]) for r in rows],
            "htf": (htf_dirs(rows, day_of), htf_dirs(m, day_of)) if htf else (None, None)}


def sequence(rows, day_of, intraday=False, ctxs=None, **kw):
    """Scanner v4 on one chart: every primary and secondary trade in order, each with its simulated exit, prices
    normal (shorts un-mirrored). A trigger on the last candle comes back with exit_reason "open" and pending=True
    (entry = that candle's close; live, the paper trade fills at the current price)."""
    p = dict(DEFAULTS, **kw)
    cx = ctxs or contexts(rows, day_of, bool(p.get("htf")))
    srcs = (rows, cx["mirror"])
    carry_day = cx["day"] if (intraday and p.get("day_carry", True)) else None
    sides = [_Side(srcs[s], cx["ctx"][s], cx["htf"][s] if p.get("htf") else None, p, carry_day) for s in (0, 1)]
    day, n = cx["day"], len(rows)
    out, open_tr, sec = [], None, None       # sec: (side, primary trade, exit candle) while a secondary is looked for
    for k in range(31, n):
        if open_tr is not None and k > open_tr["i"]:
            src = srcs[open_tr["_side"]]
            got = _exit_step(src, k, open_tr, p, day, intraday)
            if got:
                open_tr.update(exit_i=k, exit=got[0], exit_reason=got[1])
                out.append(_real(open_tr, open_tr["_side"] == 1))
                if open_tr["kind"] == "primary":
                    sec = (open_tr["_side"], open_tr, k)
                else:
                    sec = None
                open_tr = None
        cands = [(s, sides[s].step(k)) for s in (0, 1)]
        if open_tr is not None:
            continue
        pick = None
        if sec is not None and k > sec[2]:
            s, prim, kx = sec
            got = sides[s].secondary_at(prim, kx, k)
            if got == "dead":
                sec = None
            elif got:
                pick = (s, got)
        if pick is None:
            prims = [(s, t) for s, t in cands if t]
            if prims:
                pick = min(prims, key=lambda x: x[1]["bos"])
        if pick is None:
            continue
        s, t = pick
        src = srcs[s]
        fill, why = _fill(src, day, t, intraday)
        if fill is None:
            if why == "pending":
                pend = dict(t, signal_close=t["entry"], exit_i=None, exit=None, exit_reason="open", pending=True,
                            _side=s)
                out.append(_real(pend, s == 1))
            continue
        if t["kind"] == "primary":
            t["setup"]["used"] = True
            sec = None
        else:
            sec = None
        open_tr = dict(t, signal_close=t["entry"], entry=fill, cur_stop=t["stop"], _side=s)
    if open_tr is not None:
        out.append(_real(dict(open_tr, exit_i=None, exit=None, exit_reason="open"), open_tr["_side"] == 1))
    return sorted(out, key=lambda t: (t["i"], t["kind"]))


def chart_state(ledger, chart):
    """The open trade and latest close for this v4 chart, including a mapped option position."""
    market, _, symbol = chart.partition(":")

    def matches(pos):
        if pos.get("scanner") != "v4":
            return False
        if pos.get("v4_chart"):
            return pos["v4_chart"] == chart
        if pos.get("key") == chart:
            return True
        # Older stock-option fills identify the chart only through the option's underlying.
        contract = pos.get("symbol", "").rsplit("-", 3)
        return (market in ("NSE", "BSE") and pos.get("market") == "NFO" and len(contract) == 4
                and contract[0] == symbol and contract[-1] in ("CE", "PE"))

    opened = next((pos for pos in ledger["open"] if matches(pos)), None)
    closed = next((pos for pos in reversed(ledger["closed"]) if matches(pos)), None)
    return opened, closed



def live_candidate(rows, day_of, ledger, chart, intraday=False):
    """The v4 entry on the last closed candle, if any: the chart's own simulated sequence (the same code as the
    backtest) gives the signal; the paper ledger blocks it while a v4 trade is open on this chart. paper.py's
    setup_decision checks the rest (fresh signal, a secondary's primary really closed)."""
    opened, _ = chart_state(ledger, chart)
    if opened:
        return []
    last = len(rows) - 1
    return [t for t in sequence(rows, day_of, intraday=intraday) if t.get("pending") and t["i"] == last]


def _real(t, short):
    """src-terms trade -> normal prices and a side."""
    t = {k: v for k, v in t.items() if k not in ("setup", "_zones", "cur_stop", "stop_kind", "_side")}
    t["side"] = "short" if short else "long"
    if short and t.get("signal_pattern") in SHORT_NAME:   # mirrored back: a real dragonfly doji / hammer at the top
        t["signal_pattern"] = SHORT_NAME[t["signal_pattern"]]
    if short:
        for f in ("level", "extreme", "entry", "stop", "target", "trigger_px", "zone_top", "zone_bottom", "exit",
                  "signal_close"):
            if t.get(f) is not None:
                t[f] = -t[f]
        if t.get("zone_top") is not None:
            t["zone_top"], t["zone_bottom"] = t["zone_bottom"], t["zone_top"]
    return t


def rr(t):
    risk = abs(t["entry"] - t["stop"])
    return abs(t["target"] - t["entry"]) / risk if risk > 0 else 0.0
