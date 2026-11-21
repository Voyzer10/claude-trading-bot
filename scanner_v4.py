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
  2. Sweep: after that BOS, a completed candle CLOSES BELOW the low the BOS move started from (owner, 17 Nov 2026:
     "BOS jha se start hua h vha se"; a swing low formed after the BOS no longer counts: sweep_post_bos). A wick
     below is not a sweep. Further closes lower only deepen it.
  3. Signal: after the sweep, at any time, one of the owner's buying candles (12 Nov 2026), any colour: classic doji,
     gravestone doji, long-legged doji (body <= 15% of the range) or inverted hammer (upper wick >= 1x the body, >= half
     the range; owner, 13 Nov 2026). A dragonfly doji or a hammer
     is not a BUY signal (they are the SELL signals at a top). See signal_kind().
  4. Trigger: the 1st or 2nd candle after the signal CLOSES ABOVE THE SIGNAL CANDLE'S HIGH (that close may still be
     below the swept low). No trigger in 2 candles: a later signal candle gives a new chance.
  5. Entry: right after the trigger candle closes, at the current price (backtest: the next candle's open).
  6. Stop: below the lowest low from the sweep candle to the signal candle, minus 0.1 ATR.
  7. Target (owner, 17 Nov 2026, "against wale BOS ... max target bada swing"): the high the latest bearish BOS
     move started from, above the entry and not taken since, but never beyond the nearest big swing high (a high of
     big_k = 6 candles each side). No such BOS: the nearest untaken liquidity above the entry (a confirmed swing
     high, or the BOS move's high), the 12 Nov rule (target_rule "near"). The target must be above the entry;
     there is no minimum reward:risk in the engine (min_rr = 0; the account's min reward:risk still applies).
  8. Trade Manager, trailing only: at +1R the stop goes to the entry, at +2R to +1R, then up 1R per R. No other
     exit (intraday charts still close at the session's end). That is the default of the account's Trade Manager
     (Settings > Trade Manager), which applies to every scanner's trades; it can add a profit lock, a reversal
     exit and a no-follow-through exit (tm_settings / trail_lock_r / lock_stop_r / reversal_candle).
  Day rule (owner, 12 Nov 2026): at a new day only the previous day's BOS setups whose sweep has not happened stay
  active, and for that day only; today's BOS add up as they form. Setups that were swept but not traded, and older
  ones, end with their day. NSE / US 5-minute: the day = the trading session. Crypto (24h): the day starts at
  00:00 UTC (5:30 IST), where the crypto daily candle starts. The POV's higher timeframes keep every setup
  (pov.py passes day_carry=False).
  One trade at a time per chart. A setup that triggers while a trade is open is skipped but stays active; when two
  trigger on the same candle, the oldest BOS is taken. One trade per setup.
  Flip rule (owner, 14 Nov 2026, both ways): when the open trade came from an earlier day's BOS setup and a setup of
  the OPPOSITE side whose BOS formed today triggers, the open trade is closed at that candle's close and the new one
  is taken. (Backtest, Nifty 50 5m, out-of-sample: same -0.36R a trade, ~15% more trades; the owner chose to test it
  live on paper. Switch: flip_same_day.)
  Latest-BOS rule (owner, 14 Nov 2026): with a trade open, a setup whose BOS is newer than the open trades' BOS
  (either side) that triggers is taken as well, up to max_open = 2 trades open on a chart (live: a second position,
  key ...#2). (Backtest, Nifty 50 5m, out-of-sample: -0.34R a trade vs -0.36R, ~45% more trades in all with the
  flip rule; the owner chose to test it live on paper. Switch: latest_bos.)

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
from datetime import datetime, timezone

import smc_playbook as PB


def mirror(rows):
    return [(r[0], -r[1], -r[3], -r[2], -r[4], r[5]) for r in rows]


# The Trade Manager: ONE set per market account (Settings > Trade Manager), the same for every scanner (owner,
# 13 Nov 2026: "scanner koii bhi selected ho jo trade manager pr settings apply hui h vahi chlni chahiye"). The engine
# here and paper.py run the same rules. Defaults = the owner's 11 Nov v4 rule: +1R -> the entry, +2R -> +1R, then
# 1R higher per R; profit lock, reversal and no-follow-through exits off.
TM_DEFAULTS = {"trade_manager": True, "tm_be_r": 1.0, "tm_trail": True, "tm_trail_step": 1.0, "tm_trail_gap": 1.0,
               "tm_lock_at": 0.0, "tm_lock_keep": 0.5, "tm_reversal": False, "tm_rev_min_r": 1.0,
               "tm_stale_min": 0, "tm_candle_min": 5}
TM_KEYS = tuple(TM_DEFAULTS)


def tm_settings(acc):
    """An account's Trade Manager settings (missing keys: the defaults), typed."""
    out = {}
    for k, d in TM_DEFAULTS.items():
        v = (acc or {}).get(k, d)
        out[k] = bool(v) if isinstance(d, bool) else float(v if v is not None else d)
    return out


DEFAULTS = {"buffer_atr": 0.1, "min_rr": 0.0, "doji_pct": 0.15,
            "hammer_x": 1.0, "conf_max": 2, "max_hold": None, **TM_DEFAULTS,
            # BOS by close only (owner, 12 Nov 2026): the weak-BOS check is off (0); the backtest can set 0.8 / 1.2
            "htf": False, "bos_body_atr": 0, "bos_vol_x": 0, "vol_n": 20,
            # off by the owner's choice (kept so older backtest settings still run)
            "chop_er": 0, "er_n": 20, "opp_zone": False, "opp_lookback": 48,
            # the flip rule (owner, 14 Nov 2026: on, tested live on paper): see _flip()
            "flip_same_day": True,
            # the owner's sweep and target (17 Nov 2026): ON, tested live on paper (owner: "live market m test
            # karenge, kuch problem hui to remove kar denge"). Switches (the 12 Nov rules: True / "near"):
            #   sweep_post_bos: True = a close beyond the BOS-start level OR a swing formed after the BOS sweeps (the
            #     12 Nov rule); False = only the level the BOS move started from ("BOS jha se start hua h vha se")
            #   target_rule: "near" = the nearest untaken swing / the BOS move's extreme (12 Nov); "opp_bos" = where the
            #     latest opposite-side BOS move started ("against wale BOS"); "opp_bos_cap" = that, but never beyond
            #     the nearest big swing (a pivot of big_k candles each side; "max target bada swing")
            "sweep_post_bos": False, "target_rule": "opp_bos_cap", "big_k": 6,
            # from the owner's 43 opinions (17 Nov 2026), switches for the backtest first:
            #   bos_pick "newest": when several setups trigger on a candle the newest BOS is taken ("oldest" = 12 Nov)
            #   skip_open_bos: no BOS on a session's first candle (intraday; a sweep there still counts)
            #   latest_signal: the trigger needs the most recent signal candle (a newer one replaces an older one)
            #   replace_newer: a setup whose BOS is newer than the open trade's replaces it, either side ("naya bos
            #     wala purani trade ki jgha lelo, same side ho to bhi"); one trade per chart (flip / latest-BOS off)
            # bos_pick "newest" and latest_signal ON (owner, 18 Nov 2026: "Krdo on"; Nifty 50 backtest out-of-sample:
            #   newest -0.33R vs -0.30R a trade, latest_signal -0.30R, i.e. about even; live test)
            "bos_pick": "newest", "skip_open_bos": False, "latest_signal": True, "replace_newer": False,
            # sweep_shift (owner, 18 Nov 2026: "sweep sirf bos origin tak and entry ke paas wala swing bhi"): after the
            #   BOS-start sweep, a later close below an older swing low that is beyond it (lower) moves the sweep there,
            #   so the stop sits under the sweep nearest the entry; a swing inside the move (above the origin) never sweeps
            "sweep_shift": True,
            # gap_cancel (owner, 19 Nov 2026, GILLETTE / AZAD): a previous day's setup is cancelled when the session
            #   opens beyond its BOS start (a gap through the level is not a sweep)
            "gap_cancel": True,
            # sweep_max_atr (owner, 19 Nov 2026): a sweep's close may be at most this many ATRs beyond the level; a
            #   close further beyond is a breakout and cancels the setup (also for the sweep shift). 0 = no limit
            #   Backtest 19 Nov (Nifty 50, out-of-sample): 0.5 ATR -0.40R a trade vs -0.32R without: off (owner's call)
            "sweep_max_atr": 0,
            # swing_k (owner, 19 Nov 2026, GILLETTE / AZAD BOS): a swing is the highest high / lowest low of swing_k
            #   candles on each side; 2 makes every small edge inside a range a swing, so a 1-point poke is a BOS.
            #   Backtest 19 Nov (Nifty 50, out-of-sample): k=4 -0.31R a trade on 1,282 trades vs -0.35R on 2,054: on
            "swing_k": 4,
            # bos_gap_skip (owner, 19 Nov 2026, AWL): a candle that OPENS beyond the swing (a gap through it, mostly the
            #   session's first candle) does not make a BOS; the break has to happen inside the candle
            "bos_gap_skip": True,
            # signal_on_sweep (owner, 19 Nov 2026, HLT): the sweep candle itself may be the signal candle (a hammer /
            #   doji that closed beyond the level); the next 1-2 candles' break and close of it is the entry.
            #   Backtest 19 Nov (Nifty 50 primaries, out-of-sample): +29 trades at about -0.8R each: off (owner's call)
            "signal_on_sweep": False,
            # the latest-BOS rule (owner, 14 Nov 2026): see _latest(); max_open = trades open at once on one chart
            "latest_bos": True, "max_open": 2}

# The signal candle (owner, 12 Nov 2026, "Trading candlestick patterns for buying & selling"), any colour.
#   BUY at the low:  classic doji, gravestone doji, long-legged doji, inverted hammer
#   SELL at the top: classic doji, dragonfly doji, long-legged doji, hammer
# A dragonfly doji or a hammer at a low is NOT a buy signal; a gravestone doji or an inverted hammer at a top is NOT a
# sell signal. Shorts read mirrored prices, so one classifier (src terms) serves both: a real dragonfly at a top is
# a gravestone in src terms, a real hammer an inverted hammer.
TRIGGERS = {"doji", "gravestone doji", "long-legged doji", "inverted hammer"}
SHORT_NAME = {"gravestone doji": "dragonfly doji", "inverted hammer": "hammer"}


def signal_kind(bar, doji_pct=0.15, tiny=0.10, leg=0.30, hammer_x=1.0, one_side=0.6, side_x=3.0):
    """The signal-candle name of one candle in src terms, or None. Shares of the candle's range (high - low):
    doji = body <= doji_pct. A ONE-SIDED doji is a dragonfly (long lower wick: not a buy signal) or a gravestone (long
    upper wick): its long wick is >= one_side of the range and >= side_x times the other wick, or the other wick is
    < tiny (owner, 13 Nov 2026, RTX 12 Nov 20:30 IST: lower wick 85%, upper 11% was read as a doji and bought; it is a
    dragonfly / hammer). Both wicks >= leg = long-legged; otherwise a classic doji. Inverted hammer = upper wick >= hammer_x x body (owner, 13 Nov
    2026: 1x, was 2x; QCOM 12 Nov 21:55 IST, wick 1.27x body) and >= half the range, lower wick <= a quarter."""
    o, h, l, c = bar[1], bar[2], bar[3], bar[4]
    rng = h - l
    if rng <= 0:
        return None
    body, up, lo = abs(c - o), h - max(o, c), min(o, c) - l
    if body <= doji_pct * rng:
        if up < tiny * rng or (lo >= one_side * rng and lo >= side_x * up):
            return None                    # dragonfly doji (src): a sell signal only, at a top
        if lo < tiny * rng or (up >= one_side * rng and up >= side_x * lo):
            return "gravestone doji"
        if up >= leg * rng and lo >= leg * rng:
            return "long-legged doji"
        return "doji"
    if up >= hammer_x * body and up >= 0.5 * rng and lo <= 0.25 * rng:
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
        self.other = None         # the opposite side (sequence sets it): its BOS origins are this side's targets
        self.bos_hist = []        # every BOS of this side: (BOS candle, the level its move started from), never pruned
        # research only (cost-aware eligibility, off by default): rejections with why, and counters
        self.ended = p["_ended"] if isinstance(p.get("_ended"), list) else []
        self.stats = p["_stats"] if isinstance(p.get("_stats"), dict) else {}

    def pat(self, k):
        """The signal-candle name of candle k (src terms), or None."""
        if k not in self.pats:
            self.pats[k] = signal_kind(self.b[k], self.p["doji_pct"], hammer_x=self.p["hammer_x"])
        return self.pats[k]

    def step(self, j):
        """Advance to candle j; return the primary trigger of candle j or None:
        {"setup", "i", "signal", "entry" (close), "stop", "target", "atr", ...} (the oldest active setup)."""
        b, ctx, p = self.b, self.ctx, self.p
        c = b[j][4]
        self.last_today = None    # the trigger of candle j from a setup whose BOS formed today (flip rule)
        self.trig = []            # every setup that triggers on candle j, oldest BOS first (latest-BOS rule)
        if self.day is not None and j > 0 and self.day[j] != self.day[j - 1]:
            # a new session (owner, 12 Nov 2026, 5-minute intraday): only the previous day's BOS setups whose sweep
            # has not happened stay active, for this day only; swept-but-untraded and older setups end
            prev = self.day[j - 1]
            keep = [st for st in self.setups if not st["used"] and st["sweep"] is None and st["day"] == prev]
            if p.get("gap_cancel"):
                keep = [st for st in keep if b[j][1] >= st["origin"]]   # opened beyond the BOS start: a gap, cancelled
            self.setups, self.waiting = keep, [st for st in keep]
        # sweeps first: a close below the setup's BOS-start low or a swing low confirmed after its BOS
        still, gone = [], []
        lim = (p.get("sweep_max_atr") or 0) * (ctx.atr[j] or 0)
        for st in self.waiting:
            if j <= st["bos"]:
                still.append(st)
                continue
            lv = [("bos_origin", st["origin"])] + ([("post_bos", px) for idx, px in ctx.sl_known[j - 1]
                                                   if idx > st["bos"]] if p.get("sweep_post_bos", True) else [])
            broken = [(nm, px) for nm, px in lv if c < px]
            if broken:
                nm, px = max(broken, key=lambda x: x[1])
                if lim and c < px - lim:
                    gone.append(st)               # closed too far beyond the level: a breakout, not a sweep
                    continue
                st["lvl_name"], st["lvl"] = nm, px
                st["sweep"] = j
            else:
                still.append(st)
        self.waiting = still
        if p.get("sweep_shift"):
            # a swept, untraded setup: a close below a confirmed swing low beyond its sweep level moves the sweep there
            for st in self.setups:
                if st["used"] or st["sweep"] is None or st["sweep"] >= j:
                    continue
                deeper = [px for idx, px in ctx.sl_known[j - 1] if px < st["lvl"] and c < px]
                if deeper:
                    if lim and c < max(deeper) - lim:
                        gone.append(st)           # broke through the deeper swing too: a breakout
                        continue
                    st["lvl_name"], st["lvl"], st["sweep"] = "near_swing", max(deeper), j
        if gone:
            self.setups = [st for st in self.setups if all(st is not g for g in gone)]
        open_candle = bool(p.get("skip_open_bos") and p.get("_intraday") and self.day is not None
                           and (j == 0 or self.day[j] != self.day[j - 1]))
        if ctx.bull[j] and ctx.sh_known[j - 1] and not open_candle:
            ok, _ = bos_quality(b, ctx, j, p)
            if ok:
                sh_i, sh_px = ctx.sh_known[j - 1][-1]
                if p.get("bos_gap_skip") and b[j][1] > sh_px:
                    ok = False                    # opened above the swing high: a gap, not a break (AWL, 19 Nov)
            if ok:
                st = {"bos": j, "level": sh_px, "origin": self.lows.q(sh_i, j), "sweep": None, "used": False,
                      "day": self.day[j] if self.day is not None else None}
                self.setups.append(st)
                self.waiting.append(st)
                self.bos_hist.append((j, st["origin"]))
        # trigger: candle j closes above the high of a signal 1 or 2 candles back
        for s in range(j - 1, max(j - p["conf_max"], 0) - 1, -1):
            if not self.pat(s):
                continue
            if c <= b[s][2]:
                if p.get("latest_signal"):
                    break           # the newest signal candle decides; an older one no longer triggers
                continue
            a = ctx.atr[j]
            if not a or (p.get("htf") and self.htf is not None and self.htf[j] == "down"):
                return None
            liq = _targets(ctx, b, j, c)          # the swing-high liquidity, the same for every setup
            self.setups = [st for st in self.setups if not st["used"]]
            for st in self.setups:              # oldest BOS first
                # the signal candle comes after the sweep, or (signal_on_sweep) IS the sweep candle
                if st["used"] or st["sweep"] is None or st["sweep"] > s or (st["sweep"] == s and not p.get("signal_on_sweep")):
                    continue
                t = self._trade(st, s, j, a, liq)
                if not t:
                    continue
                self.trig.append(t)
                if self.last_today is None and self.day is not None and st["day"] == self.day[j]:
                    self.last_today = t
            if not self.trig:
                return None
            return max(self.trig, key=lambda t: t["bos"]) if p.get("bos_pick") == "newest" else self.trig[0]
        return None

    def _trade(self, st, s, j, a, liq):
        b, p = self.b, self.p
        c = b[j][4]
        stop = self.lows.q(st["sweep"], s) - p["buffer_atr"] * a
        move_hi = self.highs.q(st["bos"], st["sweep"])
        tgt = min([x for x in (liq, move_hi if move_hi > c else None) if x is not None], default=None)
        rule = p.get("target_rule", "near")
        if rule != "near":
            ot = self._opp_target(j, c)
            if ot is not None:
                if rule == "opp_bos_cap":
                    cap = self._big_swing(j, c, int(p.get("big_k") or 6))
                    if cap is not None:
                        ot = min(ot, cap)
                tgt = ot
        if tgt is None or stop >= c or (tgt - c) < p["min_rr"] * (c - stop):
            return None
        if not self._cost_ok(c, stop, tgt, j, st):
            return None
        return {"i": j, "kind": "primary", "setup": st, "bos": st["bos"], "sweep": st["sweep"], "reclaim": st["sweep"],
                "signal": s, "level_name": st["lvl_name"], "level": st["lvl"], "entry": c, "stop": stop,
                "target": tgt, "atr": a, "trigger_px": b[s][2], "signal_pattern": self.pat(s)}

    def _cost_ok(self, c, stop, tgt, j, st=None):
        """Cost-aware eligibility (research switch min_net_rr, off by default; 21 Nov 2026). With a cost function in
        p["_cost_fn"](side, entry, exit, stop) -> cost in R (real prices; e.g. research_costs), a trade is taken only if
        its planned NET reward at the target is at least min_net_rr x its NET risk at the stop:
            (reward_R - cost_R) >= min_net_rr x (1 + cost_R)
        (min_net_rr 1.0 = a 50% hit rate breaks even after costs). The cost is the round trip to the target (entry +
        exit at the planned prices, the market's own sizing). No cost function (or min_net_rr off): no check.
        A cost of None means the market's sizing cannot size the trade (NSE: under one share in the INDIA account):
        the trade is REJECTED ("cost: not sizeable"); a missing cost is never treated as zero.

        PRICES: this side's prices are in src terms. The short side runs on the mirrored chart (every price
        negated, see mirror()), so c / tgt / stop are NEGATIVE there; sg x price gives the REAL positive market
        price for both sides (verified in tests/test_cost_ok_sides.py). Do not pass c / tgt / stop unsigned."""
        p = self.p
        k = p.get("min_net_rr")
        fn = p.get("_cost_fn")
        if not k or fn is None:
            return True
        side = getattr(self, "side_name", "long")
        sg = -1 if side == "short" else 1                 # src -> real prices (shorts are mirrored)
        cost = fn(side, sg * c, sg * tgt, sg * stop)
        if cost is None:
            self.stats["cost_rejected"] = self.stats.get("cost_rejected", 0) + 1
            self.stats["cost_rejected_" + side] = self.stats.get("cost_rejected_" + side, 0) + 1
            self.stats["cost_unsizeable_" + side] = self.stats.get("cost_unsizeable_" + side, 0) + 1
            if st is not None:
                self.ended.append((st, j, "cost: not sizeable"))
            return False
        rr = (tgt - c) / (c - stop)
        if rr - cost >= float(k) * (1 + cost):
            return True
        self.stats["cost_rejected"] = self.stats.get("cost_rejected", 0) + 1
        self.stats["cost_rejected_" + side] = self.stats.get("cost_rejected_" + side, 0) + 1
        if st is not None:
            self.ended.append((st, j, "cost: net reward %.2fR below %.2f x net risk %.2fR" % (
                rr - cost, float(k), 1 + cost)))
        return False

    def _opp_target(self, j, c):
        """Where the latest opposite-side BOS move started (in this side's terms), above the entry and not traded
        through since that BOS; None if there is none."""
        if self.other is None:
            return None
        for bi, origin in reversed(self.other.bos_hist):
            if bi >= j:
                continue
            lvl = -origin                      # the other side's prices are this side's, negated (mirror)
            if lvl > c and (bi + 1 > j or self.highs.q(bi + 1, j) < lvl):
                return lvl
        return None

    def _big_swing(self, j, c, k):
        """The nearest big swing above the entry: a high that is the highest of k candles each side (confirmed k
        candles later), not traded through since."""
        b = self.b
        best = None
        for idx in range(j - k, max(k, j - 600) - 1, -1):
            h = b[idx][2]
            if h <= c or (best is not None and h >= best):
                continue
            if self.highs.q(idx - k, idx + k) == h and (idx + 1 > j or self.highs.q(idx + 1, j) <= h):
                best = h
        return best

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
        if not self._cost_ok(c, stop, tgt, m):
            return None
        if p.get("htf") and self.htf is not None and self.htf[m] == "down":
            return None
        return {"i": m, "kind": "secondary", "zone": z["name"], "zone_top": z["top"], "zone_bottom": z["bot"],
                "tap": m, "entry": c, "stop": stop, "target": tgt, "atr": a, "primary_at": prim["i"],
                "prim_bos": prim.get("bos"),
                "primary_closed_at": k_exit, "signal_pattern": self.pat(m)}


def trail_lock_r(gain_r, p):
    """Where the Trade Manager's stop goes, in R from the entry (0 = the entry), for a best price gain_r R in profit,
    or None (not moved). Breakeven at +tm_be_r R (0 = no breakeven move); with tm_trail on, for every whole
    tm_trail_step R the stop sits tm_trail_gap R behind it (step 1, gap 1: +2R -> +1R, +3R -> +2R)."""
    if not p.get("trade_manager", True):
        return None
    lock = None
    be = float(p.get("tm_be_r", 1.0) or 0)
    if be > 0 and gain_r + 1e-9 >= be:
        lock = 0.0
    step, gap = float(p.get("tm_trail_step", 1.0) or 0), float(p.get("tm_trail_gap", 1.0) or 0)
    if p.get("tm_trail", True) and step > 0:
        k = int(gain_r / step + 1e-9)
        if k >= 1 and k * step - gap > 1e-9:
            lock = max(lock or 0.0, k * step - gap)
    return lock


def lock_stop_r(gain_r, rr, p):
    """The profit lock, in R: once price has covered tm_lock_at of the way to the target (rr R away), the stop sits
    at tm_lock_keep of that way. None when off or not reached."""
    at = float(p.get("tm_lock_at") or 0)
    if not p.get("trade_manager", True) or at <= 0 or rr <= 0 or gain_r / rr + 1e-9 < at:
        return None
    return float(p.get("tm_lock_keep", 0.5)) * rr


def reversal_candle(prev, cur, peak, risk):
    """A completed candle near the trade's best price (long terms) that is a bearish engulfing or a long upper-wick
    rejection: the name, or None. The same test as paper.tm_react."""
    _, po, ph, pl, pc = prev[:5]
    _, o, h, l, c = cur[:5]
    rng = h - l
    engulf = pc > po and c < o and o >= pc and c <= po
    reject = rng > 0 and (h - max(o, c)) / rng >= 0.6 and (c - l) / rng <= 0.4
    if (engulf or reject) and h >= peak - 0.25 * risk:
        return "engulfing" if engulf else "wick rejection"
    return None


def _exit_step(bars, k, tr, p, day, intraday):
    """One candle of an open trade (src terms, long): stop first, then target, then the trailing stop for the next
    candle, then the session's end. Returns (exit price, reason) or None."""
    o, h, l, c = bars[k][1], bars[k][2], bars[k][3], bars[k][4]
    if l <= tr["cur_stop"]:
        why = tr.get("stop_kind", "stop")
        return (o if o < tr["cur_stop"] else tr["cur_stop"]), why
    if h >= tr["target"]:
        return (o if o > tr["target"] else tr["target"]), "target"
    risk = tr["entry"] - tr["stop"]
    if risk > 0 and p.get("trade_manager", True):
        gain = (h - tr["entry"]) / risk
        tr["mfe"] = max(tr.get("mfe", 0.0), gain)
        moves = [(trail_lock_r(gain, p), None), (lock_stop_r(gain, (tr["target"] - tr["entry"]) / risk, p), "profit lock stop")]
        for lock, kind in moves:
            if lock is None:
                continue
            ns = tr["entry"] + lock * risk
            if ns > tr["cur_stop"]:
                tr["cur_stop"] = ns
                tr["stop_kind"] = kind or ("breakeven stop" if lock == 0 else "trailing stop")
        # the Trade Manager's exits on the chart's candles (paper.py reads tm_candle_min candles)
        if p.get("tm_reversal") and tr["mfe"] >= float(p.get("tm_rev_min_r", 1.0)) and k > tr["i"] + 1:
            if reversal_candle(bars[k - 1], bars[k], tr["entry"] + tr["mfe"] * risk, risk):
                return c, "trade manager: reversal"
        stale = float(p.get("tm_stale_min") or 0)
        if stale > 0 and len(bars) > 1:
            mins = (bars[k][0] - bars[tr["i"]][0]).total_seconds() / 60
            if mins >= stale and tr["mfe"] < 0.5 and abs((c - tr["entry"]) / risk) < 0.3:
                return c, "trade manager: no follow-through"
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


def contexts(rows, day_of, htf=True, k=2):
    """Everything sequence() needs that does not depend on the settings (but the swing size k): build once per
    chart, pass as ctxs=."""
    m = mirror(rows)
    cl, cs = PB.Context(rows, day_of, k=k), PB.Context(m, day_of, k=k)
    return {"rows": rows, "mirror": m, "ctx": (cl, cs), "day": [day_of(r[0]) for r in rows], "k": k,
            "htf": (htf_dirs(rows, day_of), htf_dirs(m, day_of)) if htf else (None, None)}


def sequence(rows, day_of, intraday=False, ctxs=None, **kw):
    """Scanner v4 on one chart: every primary and secondary trade in order, each with its simulated exit, prices
    normal (shorts un-mirrored). A trigger on the last candle comes back with exit_reason "open" and pending=True
    (entry = that candle's close; live, the paper trade fills at the current price)."""
    p = dict(DEFAULTS, **kw)
    p["_intraday"] = intraday
    k = int(p.get("swing_k") or 2)
    cx = ctxs if ctxs and ctxs.get("k", 2) == k else contexts(rows, day_of, bool(p.get("htf")), k=k)
    srcs = (rows, cx["mirror"])
    carry_day = None
    if p.get("day_carry", True):
        # intraday: the session's day; crypto (not intraday): the UTC day (owner, 12 Nov 2026)
        carry_day = cx["day"] if intraday else [r[0].astimezone(timezone.utc).date() for r in rows]
    sides = [_Side(srcs[s], cx["ctx"][s], cx["htf"][s] if p.get("htf") else None, p, carry_day) for s in (0, 1)]
    sides[0].other, sides[1].other = sides[1], sides[0]
    sides[0].side_name, sides[1].side_name = "long", "short"
    day, n = cx["day"], len(rows)
    out, opens, sec = [], [], None       # sec: (side, primary trade, exit candle) while a secondary is looked for
    for k in range(31, n):
        still = []
        for tr in opens:
            got = _exit_step(srcs[tr["_side"]], k, tr, p, day, intraday) if k > tr["i"] else None
            if got:
                tr.update(exit_i=k, exit=got[0], exit_reason=got[1])
                out.append(_real(tr, tr["_side"] == 1))
                sec = (tr["_side"], tr, k) if tr["kind"] == "primary" else None
            else:
                still.append(tr)
        opens = still
        cands = [(s, sides[s].step(k)) for s in (0, 1)]
        if opens:
            if p.get("replace_newer"):
                extra, how = _replace(opens, sides, srcs, day, k, intraday, p), "replace"
            else:
                extra = _flip(opens, sides, srcs, day, carry_day, k, intraday, p)
                how = "flip"
                if extra is None:
                    extra, how = _latest(opens, sides, srcs, day, k, intraday, p), "latest"
            if extra is None:
                continue
            s, t, fill, olds = extra
            if fill is None:       # live: the trigger is on the last candle; paper.py acts on it
                tag = ({"flip": True, "flip_from": _real(dict(olds[0]), olds[0]["_side"] == 1)} if how == "flip" else
                       {"replace": True, "flip_from": _real(dict(olds[0]), olds[0]["_side"] == 1)} if how == "replace"
                       else {"latest_bos": True})
                pend = dict(t, signal_close=t["entry"], exit_i=None, exit=None, exit_reason="open", pending=True,
                            _side=s, **tag)
                out.append(_real(pend, s == 1))
                continue
            for old in olds:
                old.update(exit_i=k, exit=srcs[old["_side"]][k][4],
                           exit_reason="replaced: a newer BOS setup" if how == "replace" else "flip: today's opposite BOS setup")
                out.append(_real(old, old["_side"] == 1))
                opens.remove(old)
            t["setup"]["used"] = True
            sec = None
            opens.append(dict(t, signal_close=t["entry"], entry=fill, cur_stop=t["stop"], _side=s,
                              **({"flipped": True} if how == "flip" else {"replaced": True} if how == "replace"
                                 else {"latest_bos": True})))
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
                pick = (max if p.get("bos_pick") == "newest" else min)(prims, key=lambda x: x[1]["bos"])
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
        opens.append(dict(t, signal_close=t["entry"], entry=fill, cur_stop=t["stop"], _side=s))
    for tr in opens:
        out.append(_real(dict(tr, exit_i=None, exit=None, exit_reason="open"), tr["_side"] == 1))
    return sorted(out, key=lambda t: (t["i"], t["kind"]))


def _flip(opens, sides, srcs, day, carry_day, k, intraday, p):
    """The flip rule (owner, 14 Nov 2026), both ways: open primary trades that came from an earlier day's BOS setup
    (swept today) and a setup of the OPPOSITE side whose BOS formed today triggers: close those at this candle's
    close and take the new one. (side, trigger, fill, trades to close) or None; fill None = the live, pending case."""
    if not p.get("flip_same_day") or carry_day is None:
        return None
    for s in (0, 1):
        t = sides[s].last_today
        if not t:
            continue
        olds = [tr for tr in opens if tr["_side"] != s and tr.get("kind") == "primary" and k > tr["i"]
                and (tr.get("setup") or {}).get("day") is not None and tr["setup"]["day"] != carry_day[k]]
        if not olds or len(opens) - len(olds) >= int(p.get("max_open") or 1):
            continue
        fill, why = _fill(srcs[s], day, t, intraday)
        if fill is None and why != "pending":
            continue
        return s, t, fill, olds
    return None


def _replace(opens, sides, srcs, day, k, intraday, p):
    """The replace rule (owner, 17 Nov 2026): a setup of either side whose BOS is newer than every open trade's BOS
    (a secondary counts its primary's BOS) triggers: the open trades are closed at this candle's close and the newest
    such setup is taken. (side, trigger, fill, trades to close) or None; fill None = the live, pending case."""
    if any(k <= tr["i"] for tr in opens):
        return None
    ref = max(tr.get("bos", tr.get("prim_bos")) if tr.get("bos", tr.get("prim_bos")) is not None else tr["i"]
              for tr in opens)
    best = None
    for s in (0, 1):
        for t in sides[s].trig:
            if t["bos"] > ref and (best is None or t["bos"] > best[1]["bos"]):
                best = (s, t)
    if best is None:
        return None
    s, t = best
    fill, why = _fill(srcs[s], day, t, intraday)
    if fill is None and why != "pending":
        return None
    return s, t, fill, list(opens)


def _latest(opens, sides, srcs, day, k, intraday, p):
    """The latest-BOS rule (owner, 14 Nov 2026): with a trade open, a setup whose BOS is newer than the open trades'
    BOS triggers: take it as well (either side), up to max_open trades on the chart. (side, trigger, fill, []) or
    None; the oldest of the newer setups first."""
    if not p.get("latest_bos") or len(opens) >= int(p.get("max_open") or 1):
        return None
    newest = max(tr.get("bos", tr["i"]) for tr in opens)
    best = None
    for s in (0, 1):
        for t in sides[s].trig:
            if t["bos"] > newest and (best is None or t["bos"] < best[1]["bos"]):
                best = (s, t)
                break
    if best is None:
        return None
    s, t = best
    fill, why = _fill(srcs[s], day, t, intraday)
    if fill is None and why != "pending":
        return None
    return s, t, fill, []


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


def chart_open(ledger, chart):
    """Every open v4 position of this chart (the latest-BOS rule can hold max_open at once)."""
    market, _, symbol = chart.partition(":")
    out = []
    for pos in ledger["open"]:
        if pos.get("scanner") != "v4":
            continue
        if pos.get("v4_chart") == chart or (not pos.get("v4_chart") and pos.get("key") == chart):
            out.append(pos)
    return out



def live_candidate(rows, day_of, ledger, chart, intraday=False):
    """The v4 entry on the last closed candle, if any: the chart's own simulated sequence (the same code as the
    backtest) gives the signal; the paper ledger blocks it while a v4 trade is open on this chart. paper.py's
    setup_decision checks the rest (fresh signal, a secondary's primary really closed)."""
    opened, _ = chart_state(ledger, chart)
    opens = chart_open(ledger, chart) or ([opened] if opened else [])
    last = len(rows) - 1
    seq = [t for t in sequence(rows, day_of, intraday=intraday) if t.get("pending") and t["i"] == last]
    if opens:
        # every trigger comes back: paper.setup_decision takes the flip / latest-BOS ones and records the others as
        # skipped (before 17 Nov they were dropped here unseen, e.g. when an option's premium stop kept a trade open
        # that the engine had closed on the chart). The trade a position came from is not offered again.
        took = set()
        for o in opens:
            try:
                took.add(datetime.fromisoformat(o["v4_signal_at"]).timestamp())
            except (KeyError, TypeError, ValueError):
                pass
        return [t for t in seq if rows[t["i"]][0].timestamp() not in took]
    return seq


def direction(pos):
    """long / short of a v4 position: its setup name (an option bought on a short setup is still a short view)."""
    s = pos.get("setup") or ""
    if s.endswith("_short"):
        return "short"
    if s.endswith("_long"):
        return "long"
    return pos.get("side", "long")


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
