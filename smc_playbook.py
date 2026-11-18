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
ZONE_SETUPS = ("fvg_long", "fvg_short", "ob_long", "ob_short")
LONG = {"doji_long", "star_long", "fvg_long", "ob_long"}
MAJOR = {"PDH", "PDL", "PWH", "PWL"}   # "strong" liquidity: these, or a swing with an equal twin


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


def _week(d):
    try:
        return d.isocalendar()[:2]
    except AttributeError:
        return d


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
        # day levels: previous day high/low, and today's high/low BEFORE each candle. The first day in the data
        # may be partial, so it never becomes a "previous day" (same for the first week).
        self.pdh, self.pdl, self.cdh, self.cdl = [None] * n, [None] * n, [None] * n, [None] * n
        self.pwh, self.pwl = [None] * n, [None] * n
        prev_hl, cur_day, ch, cl, days_seen = None, None, None, None, 0
        prev_w, cur_w, wh, wl, weeks_seen = None, None, None, None, 0
        for i, b in enumerate(bars):
            if self.day[i] != cur_day:
                if cur_day is not None and days_seen > 1:
                    prev_hl = (ch, cl)
                cur_day, ch, cl = self.day[i], None, None
                days_seen += 1
            wk = _week(self.day[i])
            if wk != cur_w:
                if cur_w is not None and weeks_seen > 1:
                    prev_w = (wh, wl)
                cur_w, wh, wl = wk, None, None
                weeks_seen += 1
            self.pdh[i], self.pdl[i] = (prev_hl if prev_hl else (None, None))
            self.pwh[i], self.pwl[i] = (prev_w if prev_w else (None, None))
            self.cdh[i], self.cdl[i] = ch, cl
            ch = b[2] if ch is None else max(ch, b[2])
            cl = b[3] if cl is None else min(cl, b[3])
            wh = b[2] if wh is None else max(wh, b[2])
            wl = b[3] if wl is None else min(wl, b[3])
        self._zones = {}

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
            if self.pwl[i] is not None:
                out.append(("PWL", self.pwl[i]))
        else:
            if self.pdh[i] is not None:
                out.append(("PDH", self.pdh[i]))
            if self.cdh[i] is not None:
                out.append(("CDH", self.cdh[i]))
            out += [("swing high", p) for idx, p in self.sh_known[i - 1] if i - idx <= 192]
            if self.pwh[i] is not None:
                out.append(("PWH", self.pwh[i]))
        return out

    def equal_level(self, i, side, lvl, tol_atr=0.1):
        """True if the swept level has a twin: another confirmed swing within tol_atr x ATR (equal highs / lows,
        a pool of stops). PDH/PDL/PWH/PWL count as major levels in their own right."""
        a = self.atr[i] or 0
        piv = self.sl_known[i - 1] if side == "low" else self.sh_known[i - 1]
        near = [p for idx, p in piv if i - idx <= 192 and abs(p - lvl) <= tol_atr * a]
        return len(near) >= 2

    def sweep_at(self, j, side):
        """A sweep of mapped liquidity ending at candle j? -> (name, level, extreme) of the most important level
        swept (PDH/PDL > CDH/CDL > swings), or None. One candle: candle j trades beyond a level mapped before it
        and closes back inside. Two candles: candle j-1 closes beyond a level mapped before IT, candle j closes
        back inside. A close that stays beyond is a breakout, not a sweep."""
        if j < 2:
            return None
        rank = {"PDL": 0, "PDH": 0, "CDL": 1, "CDH": 1, "swing low": 2, "swing high": 2, "PWL": 3, "PWH": 3}
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
                        "body_pct": shape(bars[p])["body"],
                        "eq": ctx.equal_level(j, "low" if long else "high", lvl),
                        "disp": abs(bars[i][4] - bars[i][1]) / (ctx.atr[i] or a)})
    return out


def is_displacement(b, a, disp_atr=1.0):
    """A strong candle: body >= disp_atr x ATR and at least 60% of its range."""
    s = shape(b)
    return bool(s and a and s["body_abs"] >= disp_atr * a and s["body"] >= 0.6)


def _build_zones(ctx, disp_atr, min_gap_atr, expiry_fvg, expiry_ob):
    """Every FVG / order-block zone, frozen when it forms, and the candle of its FIRST retest (if that candle is a
    valid trigger). Returns {trigger index: [setup dicts]}."""
    bars, n, out = ctx.bars, len(ctx.bars), {}

    def add(t, d):
        out.setdefault(t, []).append(d)

    def retest(kind, long, born, top, bot, last):
        # first candle after `born` that trades into the zone; a close through the far side first kills it
        for t in range(born + 1, min(n, last + 1)):
            b = bars[t]
            if (b[4] < bot) if long else (b[4] > top):
                return
            if (b[3] <= top) if long else (b[2] >= bot):
                mid = (top + bot) / 2
                ok = (b[4] > b[1] and b[4] > mid) if long else (b[4] < b[1] and b[4] < mid)
                if ok and ctx.atr[t]:
                    far = bot if long else top
                    add(t, {"setup": "%s_%s" % (kind, "long" if long else "short"), "side": "long" if long else "short",
                            "trigger": t, "confirm_at": 1, "sweep_at": born, "level_name": kind.upper(),
                            "level": top if long else bot, "extreme": min(far, b[3]) if long else max(far, b[2]),
                            "hi": b[2], "lo": b[3], "struct_before": True, "struct_any": True, "atr": ctx.atr[t],
                            "entry": b[4], "body_pct": shape(b)["body"] if shape(b) else 0.0, "eq": False,
                            "disp": abs(b[4] - b[1]) / ctx.atr[t], "zone_top": top, "zone_bottom": bot})
                return

    for k in range(3, n):
        a = ctx.atr[k - 1]
        if not a:
            continue
        mid = bars[k - 1]
        # fair value gap: candle k-1 is a displacement that breaks structure, candles k-2 and k do not overlap
        if is_displacement(mid, a, disp_atr):
            up = mid[4] > mid[1]
            brk = (ctx.bull[k - 1] or ctx.bull[k]) if up else (ctx.bear[k - 1] or ctx.bear[k])
            if brk:
                if up and bars[k][3] - bars[k - 2][2] >= min_gap_atr * a:
                    retest("fvg", True, k, bars[k][3], bars[k - 2][2], k + expiry_fvg)
                if not up and bars[k - 2][3] - bars[k][2] >= min_gap_atr * a:
                    retest("fvg", False, k, bars[k - 2][3], bars[k][2], k + expiry_fvg)
        # order block: the last opposite candle (within 3) before a displacement candle that breaks structure
        d, ad = k - 1, ctx.atr[k - 1]
        if is_displacement(bars[d], ad, disp_atr):
            up = bars[d][4] > bars[d][1]
            if (ctx.bull[d] if up else ctx.bear[d]):
                for o in (d - 1, d - 2, d - 3):
                    ob = bars[o]
                    if (ob[4] < ob[1]) if up else (ob[4] > ob[1]):
                        retest("ob", up, d + 1, ob[2], ob[3], d + expiry_ob)
                        break
    return out


def zone_setups(ctx, i, disp_atr=1.0, min_gap_atr=0.2, expiry_fvg=24, expiry_ob=48):
    """FVG continuation and order-block retest setups whose trigger candle is i (the rulebook's sequences:
    structure -> impulse -> gap -> retracement -> trigger; zone -> impulse -> retest). Zones are frozen at creation
    and only the first retest counts. The entry is candle i's close; the stop goes beyond the zone."""
    key = (disp_atr, min_gap_atr, expiry_fvg, expiry_ob)
    if key not in ctx._zones:
        ctx._zones[key] = _build_zones(ctx, *key)
    return list(ctx._zones[key].get(i, []))


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


# ------------------------------------------------------------------ the scanner's view (Scanner v3 / v2)

SETUP_NAMES = {"abcd_long": "A-B-C-D long", "abcd_short": "A-B-C-D short",
               "smcp_doji_long": "Playbook doji long", "smcp_doji_short": "Playbook doji short",
               "smcp_star_long": "Playbook bottom star", "smcp_hammer_short": "Playbook top hammer",
               "smcp_fvg_long": "FVG retest long", "smcp_fvg_short": "FVG retest short",
               "smcp_ob_long": "Order block long", "smcp_ob_short": "Order block short",
               "v3_sweep_long": "v3 sweep long", "v3_sweep_short": "v3 sweep short",
               "v3_retest_long": "v3 FVG/OB retest long", "v3_retest_short": "v3 FVG/OB retest short",
               "v4_primary_long": "v4 primary long", "v4_primary_short": "v4 primary short",
               "v4_secondary_long": "v4 OB/FVG secondary long", "v4_secondary_short": "v4 OB/FVG secondary short",
               "v5_level_long": "v5 0.146 support long", "v5_level_short": "v5 0.146 resistance short"}


def _r(x):
    if x is None:
        return None
    ax = abs(x)
    return round(x, 2) if ax >= 100 else round(x, 4) if ax >= 1 else float("%.6g" % x)


SCANNER_VERSIONS = ("v5", "v4", "v3", "v2", "rules")   # "rules": only the older rules (no Scanner setups)


def setup_version(setup):
    """Which scanner version a setup belongs to: v5_ / v4_ / v3_ prefixes, everything else is v2."""
    s = str(setup or "")
    return "v5" if s.startswith("v5_") else "v4" if s.startswith("v4_") else "v3" if s.startswith("v3_") else "v2"


V4_SETUPS = ["v4_primary_long", "v4_primary_short", "v4_secondary_long", "v4_secondary_short"]
V5_SETUPS = ["v5_level_long", "v5_level_short"]
OWN_ONLY = ("v5", "v4", "v3", "v2")   # every scanner version trades ONLY its own setups (owner, 10 Nov 2026)


def v4_only(market):
    """The selected scanner version's rules ONLY (owner, 10 Nov 2026: "jo scanner version selected h sirf ussi k rules
    execute hone chahiye"). For v5 / v4 / v3 / v2 the older "rules" paths (crypto 4h breakout / SMC / playbook /
    rulebook hits, NSE / US / index F&O opening-range breakouts) are off; returns the version. For "rules" those are
    the only thing that runs (no Scanner setups); returns None. Name kept from v4."""
    v = scanner_version(market)
    return v if v in OWN_ONLY else None


def v5_params(market):
    """Scanner v5's settings for this market's account: constant, move, target (paper_config.json)."""
    try:
        import paper as P
        acc = P.load_config()["accounts"].get(P.MARKETS.get(market, {}).get("account", market), {})
    except Exception:
        acc = {}
    return {"c": float(acc.get("v5_constant", 0.146)), "move": acc.get("v5_move", "swing"),
            "target": acc.get("v5_target", "leg")}


def scanner_version(market):
    """Which Scanner a market runs: "v4" (the owner's v4 rules of 11 Nov, Final Trading Workflow + his answers: primary sweep reversal, then a sequential OB/FVG
    secondary), "v3" (the 5 Nov workflow: sweep reversal + FVG/OB retest) or "v2" (A-B-C-D, playbook doji / star /
    hammer, FVG / order-block retests). Versions never mix (owner, 5 and 7 Nov 2026).
    One switch per paper account (paper_config.json accounts.<X>.scanner_version, Settings > Risk limits). Missing:
    paper.DEFAULT_SCANNER. If the config cannot be read (a typo in a hand edit), the last version read for that market
    stays: never a silent switch to another strategy."""
    import paper as P
    try:
        acc = P.MARKETS.get(market, {}).get("account", market)
        v = P.load_config()["accounts"].get(acc, {}).get("scanner_version", P.DEFAULT_SCANNER)
        v = v if v in SCANNER_VERSIONS else P.DEFAULT_SCANNER
    except Exception:
        return _LAST_VERSION.get(market, P.DEFAULT_SCANNER)
    _LAST_VERSION[market] = v
    return v


_LAST_VERSION = {}   # the last scanner_version read per market (used only when the config cannot be read)


# the candles each chart's v4 setups came from (owner, 14 Nov 2026): paper.py's v4 time machine replays them
LAST_ROWS = {}


def owner_setups(rows, day_of, ctx=None, version="v3", intraday=False, market=None, symbol=None, ledger=None):
    """The owner's setups that complete on the LAST row (closed candles, oldest first), for one scanner version:
      v4: only the 7 Nov final workflow (scanner_v4.py): primary, then a sequential OB / FVG secondary.
      v3: only the 5 Nov workflow PDFs (sweep_reversal.py): v3 sweep reversal and v3 FVG / OB retest.
      v2: the playbook's doji / star / hammer (structure before the sweep), FVG / order-block first retests and his
          A-B-C-D (abcd.py).
    Each: {setup, name, scanner, side, price, stop, target_2r, liquidity, details}; a v3 setup also has "target" (the
    opposing liquidity, R:R >= 1). "liquidity" says in words which level was swept / which zone was retested."""
    if len(rows) < 35:
        return []
    i = len(rows) - 1
    if version == "rules":
        return []                     # "rules" selected: no Scanner setups at all
    if version == "v5":
        out = v5_setups(rows, day_of, i, intraday, v5_params(market) if market else {})
    elif version == "v4":
        out = v4_setups(rows, day_of, i, intraday, ledger, "%s:%s" % (market, symbol))
        if out:
            if len(LAST_ROWS) > 400:
                LAST_ROWS.clear()
            LAST_ROWS["%s:%s" % (market, symbol)] = (rows, day_of, intraday)
    elif version == "v3":
        out = v3_setups(rows, day_of, i, ctx)
    else:
        out = v2_setups(rows, day_of, i, ctx)
    for o in out:
        o["name"] = SETUP_NAMES.get(o["setup"], o["setup"])
        o["scanner"] = version
    return out


def v2_setups(rows, day_of, i, ctx=None):
    """Scanner v2's setups on candle i: playbook doji / star / hammer, FVG / OB retests, A-B-C-D."""
    import abcd as A   # abcd imports this module, so import here
    out, done = [], set()
    try:
        ctx = ctx or Context(rows, day_of)
        found = find_setups(ctx, i) + zone_setups(ctx, i)
    except Exception:
        found = []
    for s in found:
        key = "smcp_" + s["setup"]
        if key in done or (s["setup"] in SETUPS and not s.get("struct_before")):
            continue
        done.add(key)
        stop = stop_for(s, 0.1)
        risk = abs(s["entry"] - stop)
        out.append({"setup": key, "side": s["side"], "price": _r(s["entry"]), "stop": _r(stop),
                    "target_2r": _r(s["entry"] + 2 * risk if s["side"] == "long" else s["entry"] - 2 * risk),
                    "liquidity": ("%s zone %s-%s" % (s.get("level_name"), _r(s.get("zone_bottom")), _r(s.get("zone_top")))
                                  if s.get("zone_top") is not None else
                                  "swept %s %s" % (s.get("level_name"), _r(s.get("level")))),
                    "details": {"level": s.get("level_name"), "level_px": _r(s.get("level")),
                                "confirmed_on_candle": s.get("confirm_at"), "body_pct": round(s.get("body_pct") or 0, 3)}})
    for short in (False, True):
        try:
            _, sigs = A.signals(rows, day_of, short=short, ctx=None if short else ctx)
        except Exception:
            sigs = []
        for s in sigs:
            if s["i"] != i:
                continue
            stop = A.stop_for(s, "c_low")
            risk = abs(s["entry"] - stop)
            out.append({"setup": "abcd_short" if short else "abcd_long", "side": s["side"], "price": _r(s["entry"]),
                        "stop": _r(stop), "target_2r": _r(s["entry"] - 2 * risk if short else s["entry"] + 2 * risk),
                        "liquidity": "closed %s swing %s %s" % ("above" if short else "below",
                                                                "high" if short else "low", _r(s["b_level"])),
                        "details": {"A_at": rows[s["a"]][0].isoformat(), "B_level": _r(s["b_level"]),
                                    "C_high": _r(s["c_low"] if short else s["c_high"]),
                                    "C_low": _r(s["c_high"] if short else s["c_low"]),
                                    "D_candles_after_C": s["d_offset"], "reclaimed": s["reclaimed"]}})
    return out


def v3_setups(rows, day_of, i, ctx=None):
    """Scanner v3 (the owner's workflow PDFs, 5 Nov 2026), two entries. Sweep reversal: BOS -> a close below the swept low -> doji / inverted hammer
    -> a close above the trigger within 2 candles; extended moves skipped; target = the opposing liquidity, R:R >= 1.
    Live reading: either low (the BOS move's start or a later swing low), either trigger (signal or sweep candle).
    FVG / OB retest: after that reversal, the first return into its order block / fair value gap, then a close above
    the retest candle's high within 2 candles; stop below the zone, same target, R:R >= 1."""
    import sweep_reversal as V
    out = []
    for short in (False, True):
        try:
            _, sigs = V.signals(rows, day_of, short=short, ctx=None if short else ctx)
        except Exception:
            sigs = []
        for s in sigs:
            if s["i"] != i:
                continue
            stop = V.stop_for(s)
            tgt = V.target_for(s, "swing", stop)
            r = V.rr(s, stop, tgt)
            if tgt is None or r < 1.0:
                continue
            risk = abs(s["entry"] - stop)
            out.append({"setup": "v3_sweep_short" if short else "v3_sweep_long", "side": s["side"],
                        "price": _r(s["entry"]), "stop": _r(stop), "target": _r(tgt),
                        "target_2r": _r(s["entry"] - 2 * risk if short else s["entry"] + 2 * risk),
                        "liquidity": "swept %s %s %s" % ("swing high" if short else "swing low",
                                                         "(BOS start)" if s["level_name"] == "bos_origin" else "(after BOS)",
                                                         _r(s["level"])),
                        "details": {"swept": s["level_name"], "swept_px": _r(s["level"]), "BOS_at": rows[s["bos"]][0].isoformat(),
                                    "signal": s["signal_pattern"], "trigger_px": _r(s["trigger_px"]),
                                    "above_signal_candle": s["above_signal"], "above_sweep_candle": s["above_sweep"],
                                    "confirmed_on_candle": s["conf_offset"], "reclaimed": s["reclaimed"],
                                    "rr": round(r, 2)}})
        # the FVG / OB retest after a sweep reversal (third PDF): stop below the zone, same liquidity target
        try:
            _, rts = V.retest_signals(rows, day_of, short=short)
        except Exception:
            rts = []
        for s in rts:
            if s["i"] != i or s["swing_target"] is None:
                continue
            stop, tgt = s["stop"], s["swing_target"]
            r = V.rr(s, stop, tgt)
            if r < 1.0 or (tgt <= s["entry"] if not short else tgt >= s["entry"]):
                continue
            risk = abs(s["entry"] - stop)
            out.append({"setup": "v3_retest_short" if short else "v3_retest_long", "side": s["side"],
                        "price": _r(s["entry"]), "stop": _r(stop), "target": _r(tgt),
                        "target_2r": _r(s["entry"] - 2 * risk if short else s["entry"] + 2 * risk),
                        "liquidity": "%s retest %s-%s (after a sweep of %s)" % (
                            s["zone"], _r(min(s["zone_top"], s["zone_bottom"])), _r(max(s["zone_top"], s["zone_bottom"])),
                            _r(s["extreme"])),
                        "details": {"zone": s["zone"], "zone_top": _r(s["zone_top"]), "zone_bottom": _r(s["zone_bottom"]),
                                    "reversal_at": rows[s["reversal_at"]][0].isoformat(),
                                    "first_entry_was_extended": s["reversal_extended"],
                                    "confirmed_on_candle": s["conf_offset"], "rr": round(r, 2)}})
    return out


def v5_setups(rows, day_of, i, intraday=False, params=None):
    """Scanner v5 (scanner_v5.py, the 0.146 level): the trade whose entry is candle i."""
    import scanner_v5 as V5
    try:
        seq = V5.sequence(rows, day_of, intraday=intraday, **(params or {}))
    except Exception:
        return []
    out = []
    for t in seq:
        if t["i"] != i:
            continue
        short = t["side"] == "short"
        risk = abs(t["entry"] - t["stop"])
        liq = "%s move %s -> %s (range %s): %s level %s = %s %s %s x range, rejected" % (
            "down" if short else "up", _r(t["leg_high"] if short else t["leg_low"]),
            _r(t["leg_low"] if short else t["leg_high"]), _r(t["range"]), "resistance" if short else "support",
            _r(t["level"]), "high" if short else "low", "-" if short else "+", t["c"])
        out.append({"setup": "v5_level_%s" % t["side"], "side": t["side"], "price": _r(t["entry"]),
                    "stop": _r(t["stop"]), "target": _r(t["target"]),
                    "target_2r": _r(t["entry"] - 2 * risk if short else t["entry"] + 2 * risk), "liquidity": liq,
                    "details": {"move": t["move"], "constant": t["c"], "level": _r(t["level"]),
                                "leg_low": _r(t["leg_low"]), "leg_high": _r(t["leg_high"]), "rr": round(V5.rr(t), 2)}})
    return out


def v4_setups(rows, day_of, i, intraday=False, ledger=None, chart=None):
    """Format the current v4 signal from the live ledger or from a chart-only simulation."""
    import scanner_v4 as V4
    try:
        seq = (V4.live_candidate(rows, day_of, ledger, chart, intraday=intraday) if ledger is not None
               else V4.sequence(rows, day_of, intraday=intraday))
    except Exception:
        return []
    out = []
    for t in seq:
        if t["i"] != i:
            continue
        short, prim = t["side"] == "short", t["kind"] == "primary"
        risk = abs(t["entry"] - t["stop"])
        if prim:
            liq = "closed %s %s %s %s, then a %s" % ("above" if short else "below",
                                                 "the swing high" if short else "the swing low",
                                                 {"bos_origin": "(BOS start)", "near_swing": "(near the entry, beyond the BOS start)"}
                                                 .get(t["level_name"], "(after BOS)"),
                                                 _r(t["level"]), t["signal_pattern"])
            det = {"swept": t["level_name"], "swept_px": _r(t["level"]), "BOS_at": rows[t["bos"]][0].isoformat(),
                   "sweep_at": rows[t["sweep"]][0].isoformat(), "signal": t["signal_pattern"],
                   "signal_at": rows[t["signal"]][0].isoformat(), "trigger_px": _r(t["trigger_px"]),
                   "rr": round(V4.rr(t), 2)}
            if t.get("latest_bos"):
                det["latest_bos"] = True
            if t.get("flip"):
                fr = t.get("flip_from") or {}
                det.update(flip=True, flip_from_side=fr.get("side"), flip_from_entry=_r(fr["entry"]) if fr.get("entry") else None)
        else:
            lo, hi = sorted((t["zone_top"], t["zone_bottom"]))
            liq = "%s tap %s-%s after the primary closed" % (t["zone"], _r(lo), _r(hi))
            det = {"zone": t["zone"], "zone_low": _r(lo), "zone_high": _r(hi),
                   "primary_at": rows[t["primary_at"]][0].isoformat(),
                   "primary_closed_at": t.get("primary_exit_time") or rows[t["primary_closed_at"]][0].isoformat(),
                   "tapped_at": rows[t["tap"]][0].isoformat(), "rr": round(V4.rr(t), 2)}
        out.append({"setup": "v4_%s_%s" % (t["kind"], t["side"]), "side": t["side"], "price": _r(t["entry"]),
                    "stop": _r(t["stop"]), "target": _r(t["target"]),
                    "target_2r": _r(t["entry"] - 2 * risk if short else t["entry"] + 2 * risk),
                    "liquidity": liq, "details": det, "v4_signal_at": rows[i][0].isoformat()})
    return out
