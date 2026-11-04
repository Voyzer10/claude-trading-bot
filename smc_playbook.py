#!/usr/bin/env python3
"""
smc_playbook.py - the user's "SMC Trading Playbook" (Expanded English edition) as code. One engine, used by the
backtests (research_smcp.py: crypto-smcp, crypto-smcp-5m, nse-smcp) and the live crypto scanner/agent.

Governing rule (playbook): SMC first, liquidity and structure second, a qualified candle pattern third. Entry only
when candle 1 or candle 2 after the trigger candle CLOSES strictly beyond the trigger candle's extreme; a close
equal to it, or a wick, is not confirmation; candle 3 cannot revive the setup.

Sequence: location -> structure -> liquidity -> candle -> confirmation.

Objective definitions used here (the playbook asks for predeclared rules; each is a setting):
  swing pivot      a high higher than the 2 candles on each side (lows mirror); known only 2 candles later
  liquidity map    PDH / PDL (previous day), CDH / CDL (today so far, before this candle), the last confirmed
                   swing highs / lows of the last 2 days
  sweep            a candle trades beyond a mapped level and closes back inside it (one candle), or closes beyond
                   it and the next candle closes back inside (two candles); a close-and-hold beyond is a breakout
  structure        bullish BOS/CHoCH = the first close above the latest confirmed swing high (bearish mirrors);
                   "before": one within `struct_lookback` candles before the sweep; "any": up to the
                   confirmation candle; "none": not required (to measure what it adds)
  trigger candle   at the swept level (its low / high within `near_atr` x ATR of it), the sweep candle itself or
                   one of the next 2:
                     doji              body <= doji_pct of the range
                     top hammer        lower wick >= 2 x body and >= 50% of the range, upper wick <= 25%
                                       (classically a "hanging man"; the playbook's custom short)
                     bottom star       upper wick >= 2 x body and >= 50% of the range, lower wick <= 25%
                                       (classically an "inverted hammer"; the playbook's custom long)
                   long setups follow a sweep of sell-side liquidity (a low), short setups of buy-side (a high)
  confirmation     candle 1 (or 2, if confirm=2) CLOSES strictly beyond the trigger extreme; a close beyond the
                   opposite extreme first cancels the setup
  stop             doji: beyond the doji's other extreme; star long: below the lower of its low and the swept low;
                   hammer short: above the hammer high (and the swept high); plus buffer_atr x ATR(14)
  target           internal: the nearest confirmed swing beyond the entry, else CDH/CDL; external: the nearest of
                   CDH/PDH (CDL/PDL); 2R; trail (break-even at +1R, then 2 x ATR behind the best price).
                   A target under min_rr x the risk away is skipped ("skip if net reward does not justify the stop")

The playbook is a testing framework: no positive expectancy is assumed, and neither is it here.
"""

SETUPS = ("doji_long", "doji_short", "star_long", "hammer_short")
LONG = {"doji_long", "star_long"}


def atr_series(bars, n=14):
    """bars: (t, o, h, l, c, v). ATR(n) at every index (None until n bars)."""
    out, trs = [], []
    for i, b in enumerate(bars):
        pc = bars[i - 1][4] if i else b[4]
        trs.append(max(b[2] - b[3], abs(b[2] - pc), abs(b[3] - pc)))
        out.append(sum(trs[-n:]) / n if i >= n - 1 else None)
    return out


def shape(b):
    """Candle anatomy: body, upper wick, lower wick as fractions of the range (None for a zero range)."""
    o, h, l, c = b[1], b[2], b[3], b[4]
    rng = h - l
    if rng <= 0:
        return None
    body = abs(c - o)
    return {"body": body / rng, "upper": (h - max(o, c)) / rng, "lower": (min(o, c) - l) / rng, "body_abs": body}


def patterns(b, doji_pct=0.15):
    """Which trigger patterns this candle is (a candle can be several, e.g. a doji with a long wick)."""
    s = shape(b)
    if not s:
        return set()
    out = set()
    if s["body"] <= doji_pct:
        out.add("doji")
    body = max(s["body"], 1e-9)
    if s["lower"] >= 2 * body and s["lower"] >= 0.5 and s["upper"] <= 0.25:
        out.add("hammer")
    if s["upper"] >= 2 * body and s["upper"] >= 0.5 and s["lower"] <= 0.25:
        out.add("star")
    return out


class Context:
    """Precomputed, causal context for one symbol's candles: pivots, structure events, day levels, ATR."""

    def __init__(self, bars, day_of, k=2):
        self.bars, self.k = bars, k
        n = len(bars)
        self.atr = atr_series(bars)
        self.day = [day_of(b[0]) for b in bars]
        # swing pivots, each usable from index p + k on
        self.sh_known = [[] for _ in range(n)]   # at index i: confirmed swing highs (index, price) known by i
        self.sl_known = [[] for _ in range(n)]
        sh, sl = [], []
        for i in range(n):
            p = i - k
            if p >= k:
                hp = bars[p][2]
                if all(hp > bars[j][2] for j in range(p - k, p)) and all(hp >= bars[j][2] for j in range(p + 1, p + k + 1)):
                    sh.append((p, hp))
                lp = bars[p][3]
                if all(lp < bars[j][3] for j in range(p - k, p)) and all(lp <= bars[j][3] for j in range(p + 1, p + k + 1)):
                    sl.append((p, lp))
            self.sh_known[i] = sh[-12:]
            self.sl_known[i] = sl[-12:]
        # structure events: first close beyond the latest confirmed swing (bull: above a swing high)
        self.bull, self.bear = [False] * n, [False] * n
        for i in range(1, n):
            hs, ls = self.sh_known[i - 1], self.sl_known[i - 1]
            if hs and bars[i][4] > hs[-1][1] >= bars[i - 1][4]:
                self.bull[i] = True
            if ls and bars[i][4] < ls[-1][1] <= bars[i - 1][4]:
                self.bear[i] = True
        # day levels: previous day high/low, and today's high/low BEFORE each candle
        self.pdh, self.pdl, self.cdh, self.cdl = [None] * n, [None] * n, [None] * n, [None] * n
        prev_hl, cur_day, ch, cl = None, None, None, None
        for i, b in enumerate(bars):
            if self.day[i] != cur_day:
                if cur_day is not None:
                    prev_hl = (ch, cl)
                cur_day, ch, cl = self.day[i], None, None
            self.pdh[i], self.pdl[i] = (prev_hl if prev_hl else (None, None))
            self.cdh[i], self.cdl[i] = ch, cl
            ch = b[2] if ch is None else max(ch, b[2])
            cl = b[3] if cl is None else min(cl, b[3])

    def levels(self, i, side):
        """Mapped liquidity known before candle i: side 'low' = sell-side (PDL, CDL, swing lows of about the
        last 192 candles), 'high' = buy-side (PDH, CDH, swing highs)."""
        if i < 1:
            return []
        out = []
        if side == "low":
            if self.pdl[i] is not None:
                out.append(("PDL", self.pdl[i]))
            if self.cdl[i] is not None:
                out.append(("CDL", self.cdl[i]))
            out += [("swing low", p) for idx, p in self.sl_known[i - 1] if i - idx <= 192]
        else:
            if self.pdh[i] is not None:
                out.append(("PDH", self.pdh[i]))
            if self.cdh[i] is not None:
                out.append(("CDH", self.cdh[i]))
            out += [("swing high", p) for idx, p in self.sh_known[i - 1] if i - idx <= 192]
        return out

    def sweep_at(self, j, side):
        """A sweep of mapped liquidity ending at candle j? -> (name, level, extreme) of the most important level
        swept (PDH/PDL > CDH/CDL > swings), or None. One candle: candle j trades beyond a level mapped before it
        and closes back inside. Two candles: candle j-1 closes beyond a level mapped before IT, candle j closes
        back inside. A close that stays beyond is a breakout, not a sweep."""
        if j < 2:
            return None
        rank = {"PDL": 0, "PDH": 0, "CDL": 1, "CDH": 1, "swing low": 2, "swing high": 2}
        b, a = self.bars[j], self.bars[j - 1]
        best = None
        for name, lvl in self.levels(j, side):
            hit = (b[3] < lvl < b[4]) if side == "low" else (b[4] < lvl < b[2])
            if hit:
                cand = (rank[name], 1, name, lvl, b[3] if side == "low" else b[2])
                best = cand if best is None or cand[:2] < best[:2] else best
        for name, lvl in self.levels(j - 1, side):
            hit = (a[4] < lvl < b[4]) if side == "low" else (a[4] > lvl > b[4])
            if hit:
                ext = min(a[3], b[3]) if side == "low" else max(a[2], b[2])
                cand = (rank[name], 2, name, lvl, ext)
                best = cand if best is None or cand[:2] < best[:2] else best
        return best[2:] if best else None

    def nearest_swing_beyond(self, i, price, up):
        hs = self.sh_known[i] if up else self.sl_known[i]
        cands = [p for _, p in hs if (p > price if up else p < price)]
        if not cands:
            return None
        return min(cands) if up else max(cands)


def find_setups(ctx, i, doji_pct=0.15, near_atr=0.5, struct_lookback=48, max_confirm=2):
    """Setups whose confirmation candle is i (just closed). Returns a list of dicts (usually 0 or 1).
    For each trigger candle p in (i-1, i-2) and each long / short pattern, checks the playbook sequence."""
    bars, out = ctx.bars, []
    for p in (i - 1, i - 2):
        if p < 30 or p >= len(bars):
            continue
        offs = i - p
        if offs > max_confirm:
            continue
        a = ctx.atr[p]
        if not a:
            continue
        pats = patterns(bars[p], doji_pct)
        if not pats:
            continue
        for setup in SETUPS:
            long = setup in LONG
            kind = setup.split("_")[0]
            if kind not in pats:
                continue
            hi, lo = bars[p][2], bars[p][3]
            # confirmation: candle i closes strictly beyond the trigger extreme; candles in between must not have
            # confirmed already (then that one was the entry) nor closed beyond the opposite extreme (cancel)
            between = bars[p + 1:i]
            if long:
                if not bars[i][4] > hi or any(x[4] > hi or x[4] < lo for x in between) or bars[i][4] < lo:
                    continue
            else:
                if not bars[i][4] < lo or any(x[4] < lo or x[4] > hi for x in between) or bars[i][4] > hi:
                    continue
            # liquidity event: a sweep on the sweep candle j = p, p-1 or p-2, of the right side
            sw = None
            for j in (p, p - 1, p - 2):
                s = ctx.sweep_at(j, "low" if long else "high")
                if s:
                    sw = (j,) + s
                    break
            if not sw:
                continue
            j, lname, lvl, extreme = sw
            # location: the trigger candle sits at the swept level
            if long and lo > lvl + near_atr * a:
                continue
            if not long and hi < lvl - near_atr * a:
                continue
            # structure: index of the latest BOS/CHoCH of the trade's direction
            ev = ctx.bull if long else ctx.bear
            before = any(ev[m] for m in range(max(0, j - struct_lookback), j))
            after = any(ev[m] for m in range(j, i + 1))
            out.append({"setup": setup, "side": "long" if long else "short", "trigger": p, "confirm_at": offs,
                        "sweep_at": j, "level_name": lname, "level": lvl, "extreme": extreme, "hi": hi, "lo": lo,
                        "struct_before": before, "struct_any": before or after, "atr": a, "entry": bars[i][4],
                        "body_pct": shape(bars[p])["body"]})
    return out


def stop_for(s, buffer_atr):
    a = s["atr"] * buffer_atr
    if s["side"] == "long":
        base = s["lo"] if s["setup"] == "doji_long" else min(s["lo"], s["extreme"])
        return base - a
    base = s["hi"] if s["setup"] == "doji_short" else max(s["hi"], s["extreme"])
    return base + a


def target_for(ctx, i, s, mode, stop):
    """Target price, or None if there is no level / not enough room (caller checks min R)."""
    entry, long = s["entry"], s["side"] == "long"
    risk = (entry - stop) if long else (stop - entry)
    if mode == "2R":
        return entry + 2 * risk if long else entry - 2 * risk
    if mode == "trail":
        return entry + 20 * risk if long else max(entry * 0.05, entry - 20 * risk)
    day_hi = max(x for x in (ctx.cdh[i], ctx.bars[i][2]) if x is not None)
    day_lo = min(x for x in (ctx.cdl[i], ctx.bars[i][3]) if x is not None)
    if mode == "internal":
        t = ctx.nearest_swing_beyond(i, entry, long)
        if t is None:
            t = day_hi if long else day_lo
        return t if (t > entry if long else t < entry) else None
    # external: the nearest of current-day and previous-day extremes beyond the entry
    cands = [x for x in ((day_hi, ctx.pdh[i]) if long else (day_lo, ctx.pdl[i])) if x is not None]
    cands = [x for x in cands if (x > entry if long else x < entry)]
    if not cands:
        return None
    return min(cands) if long else max(cands)
