#!/usr/bin/env python3
"""
auto_crypto.py - the day-trader pipeline, run automatically on live crypto hits,
with PAPER trades only (virtual money in paper.py; nothing reaches an exchange).

live.py --auto-paper calls process() after every crypto scan. For each NEW hit of an
enabled setup (default: the 4-hour range breakout) it runs the agents in order and
records every verdict in trader/live/decisions.jsonl:

  1 scanner      the hit itself (15-minute close above the 4-hour high)
  2 news         the coin's latest Yahoo Finance headlines (recorded, never acted on)
  3 entry        live price now; skips a chase if price ran too far past the trigger
  4 exit         stop at the 4-hour range midpoint (or low), target at N x the risk
  5 timemachine  2,000 replays from the coin's own last 30 days of 15-minute candles,
                 plus every past time the same rule fired; skips a negative edge
  6 budget       \\
  7 risk          >  paper.py buy: sizes to your max loss, checks every limit, fills on paper
  8 broker       /
  9 alerts       live.py checks stops/targets every cycle; a time stop closes stale trades
 10 analyst      n/a for crypto (SEC filings)
 11 pelosi       n/a for crypto (US Congress stock disclosures)

Rules live in trader/live/auto_config.json (made on first run).
A simulation is not a prediction; a paper result is not a real result.
"""
import contextlib
import io
import json
import os
import random
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import paper as P
import scan_crypto as C
import scan_nse as S

LIVE_DIR = os.path.join("trader", "live")
AUTO_CONFIG = os.path.join(LIVE_DIR, "auto_config.json")
DECISIONS = os.path.join(LIVE_DIR, "decisions.jsonl")

DEFAULTS = {
    "_note": "Auto PAPER trading rules for crypto. Paper money only.",
    "enabled_setups": ["range_breakout_4h"],   # add "range_breakdown_4h" for shorts, only if research.py
                                               # crypto-short is positive out-of-sample
    # rules v4 (research.py crypto-v4, 2 Nov 2026, 20 coins, 58 days, 70/30 walk-forward): the stop is 1.5 x
    # ATR(14) of the 15m bars instead of the range middle with a 1% minimum, thin hours are skipped, the hold
    # is 12h and the exit trails. Out-of-sample: v4 trail 42 trades +0.69R avg, v3 68 trades +0.20R avg.
    # rules v5 (2 Nov 2026, same data, v4 neighbours): the 0.5R "chasing" skip is off. With it the v4 rule took
    # 20 out-of-sample trades at +0.52R (in-sample 110 at +0.45R); without it 42 at +0.69R (in-sample 168 at
    # +0.41R): the strongest breakout candles were being thrown away. The thin-hours skip stays: trading those
    # hours added 23 in-sample trades that lost about -0.37R each.
    # rules v6 (2 Nov 2026, owner's decision): breakout volume >= 1.0x the 4h average instead of 1.5x. NOT
    # backtested at 1.0x (the v4 grid had 0 and 1.5); research.py crypto-v4 now includes 1.0 so the next run
    # shows whether it helps. Go back to 1.5 from Settings if the live trades or that report say so.
    # rules v7 (3 Nov 2026): the long rule is v6 unchanged; new short_* settings (used only when
    # range_breakdown_4h is ticked, off by default) default to the most consistent short combination of
    # research.py crypto-v4-short: trailing exit, coin in a downtrend (close < EMA50 < EMA200, EMA200 falling),
    # 4h range under 1%, no volume rule, all hours, BTC below its 4h midpoint. Out-of-sample 35 trades +0.40R
    # (in-sample 44, +0.27R); 33 of 1,608 combinations were positive in both halves, so paper-test it first.
    "rules_version": 7,
    "stop": "atr",                # atr (v4), range-mid or range-low (v3 and older)
    "stop_atr_k": 1.5,            # stop = entry - k x ATR(14, 15m)
    "exit": "trail",              # trail: break-even at +trail_arm_r, then trail_atr_k x ATR under the high
                                  # target: fixed target at target_r
    "trail_atr_k": 2.0,
    "trail_arm_r": 1.0,
    "target_r": 2.0,              # used when exit = target
    "max_chase_r": 0,             # 0 = off (v5). >0: skip if price already ran this many R past the range high
    "min_stop_pct": 0.0,          # v3 used 1.0; v4 sizes the stop from ATR and caps the fee share instead
    "min_vol_x": 1.0,             # breakout candle volume vs the 4h range's average (v6: 1.0, was 1.5)
    "btc_regime": True,           # BTC's last close above the midpoint of its own prior 4h of closes
    "max_fee_r": 0.25,            # skip if the round-trip fee costs more than this many R
    "skip_hours_utc": [0, 1, 2, 3, 4, 5],  # thin hours (05:30-11:30 IST): breakouts there are skipped
    "sim_paths": 2000,
    "sim_bars": 24,               # 24 x 15 min = 6 hours
    "history_days": 30,
    "min_sim_avg_r": -99,         # replays are recorded but do not gate (the backtest never tested them)
    "min_history_trades": 5,      # history only counts once the rule fired this often
    "min_history_avg_r": -99,     # history recorded, not a gate
    "max_hold_hours": 12,         # time stop for open crypto paper trades (v4: 12h)
    # Smart Money "liquidity sweep and reclaim" (smc.py), used when "smc_sweep_long" / "smc_sweep_short" is in
    # enabled_setups (off by default). Test it first: python research.py crypto-smc, then set these to the
    # report's most consistent combination. Thin hours, the fee cap and the time stop above apply too.
    "short_exit": "trail",        # shorts (range_breakdown_4h): 2R target | trail (break-even at +1R, then
                                  # trail_atr_k x ATR above the lowest price)
    "short_trend": "ema+slope",   # off | ema (close < EMA50 < EMA200, 15m) | ema+slope (and EMA200 falling)
    "short_max_range_pct": 1.0,   # the 4h range at most this % of the price (a squeeze); 0 = any
    "short_min_vol_x": 0.0,       # breakdown candle volume vs the 4h average (shorts only)
    "short_skip_thin_hours": False,  # shorts trade all hours (the long rule skips 00-06 UTC)
    "timeframe": "15m",           # candles the breakout is read on: 15m (backtested) | 5m (crypto-v4-5m first);
                                  # the 4h range, ATR(14) stop and trailing stop all use this timeframe
    "smc_variant": "any",         # any | wick (one candle sweeps and closes back in) | 2bar (failed breakdown)
    "smc_stop": "sweep",          # sweep: beyond the sweep's extreme (0.1 ATR buffer) | atr1.5: 1.5 x ATR
    "smc_exit": "2R",             # 2R target | mid: target the 4h range's middle | trail (longs; shorts use 2R)
    "smc_min_vol_x": 0.0,         # sweep candle volume vs the 4h average
    "smc_regime": False,          # True: long only while BTC is above its 4h midpoint, short only below
    # The user's SMC Trading Playbook (smc_playbook.py), used when any of "smcp_doji_long", "smcp_doji_short",
    # "smcp_star_long", "smcp_hammer_short" is in enabled_setups (all off by default). Sequence: liquidity sweep
    # (PDH/PDL, CDH/CDL, swing) -> doji / top hammer / bottom star at the level -> candle 1 or 2 CLOSES beyond its
    # extreme. Test first: python research.py crypto-smcp (Backtest: "Playbook crypto 15m") and set these to the
    # report's most consistent combination. The fee cap and the time stop above apply too.
    "smcp_confirm": 2,            # 2: candle 1 or candle 2 may confirm | 1: candle 1 only
    "smcp_struct": "before",      # before: a BOS/CHoCH in the trade's direction in the 48 candles before the sweep
                                  # any: before or up to the entry | none: no structure rule
    "smcp_doji_pct": 0.15,        # doji body at most this share of the candle's range (0.10 = stricter)
    "smcp_buffer_atr": 0.1,       # stop buffer beyond the pattern / sweep extreme, x ATR(14)
    "smcp_target": "internal",    # internal: nearest swing beyond (else today's high/low) | external: CDH/PDH
                                  # (CDL/PDL) | 2R | trail (break-even at +1R, then trail_atr_k x ATR)
    "smcp_min_rr": 1.0,           # skip if the liquidity target is under this many R away (after fees)
    "smcp_regime": False,         # True: long only while BTC is above its 4h midpoint, short only below
    "smcp_skip_thin_hours": False,  # True: skip skip_hours_utc (00-06 UTC) like the long breakout rule
    "smcp_liq": "base",           # which sweeps count: base (PDH/PDL, CDH/CDL, swings) | all (+ last week's high/low)
                                  # | strong (only PDH/PDL/PWH/PWL or equal highs/lows)
    "smcp_min_disp": 0.0,         # entry candle body at least this many ATRs (rulebook "displacement"); 0 = off
    # smcp_fvg_long / smcp_fvg_short / smcp_ob_long / smcp_ob_short (rulebook zone setups, off by default): the first
    # retest of a fair value gap / order block left by a structure-breaking impulse; the stop goes beyond the zone.
    "seed": None,
}


def load_cfg():
    os.makedirs(LIVE_DIR, exist_ok=True)
    try:
        with open(AUTO_CONFIG, encoding="utf-8") as fh:
            old = json.load(fh)
    except Exception:
        old = None
    if old is not None and old.get("rules_version", 1) < DEFAULTS["rules_version"]:
        os.replace(AUTO_CONFIG, AUTO_CONFIG + ".v%d.bak" % old.get("rules_version", 1))  # keep the old rules
    if not os.path.exists(AUTO_CONFIG):
        with open(AUTO_CONFIG, "w", encoding="utf-8") as fh:
            json.dump(DEFAULTS, fh, indent=2)
    with open(AUTO_CONFIG, encoding="utf-8") as fh:
        cfg = dict(DEFAULTS)
        cfg.update(json.load(fh))
    return cfg


# ------------------------------------------------------------------ news

def headlines(sym, n=3):
    url = ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=US&lang=en-US"
           % urllib.parse.quote(sym + C.SUFFIX))
    req = urllib.request.Request(url, headers={"User-Agent": S.UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        root = ET.fromstring(r.read())
    out = []
    for item in root.iter("item"):
        out.append({"title": (item.findtext("title") or "").strip(),
                    "published": (item.findtext("pubDate") or "").strip(),
                    "link": (item.findtext("link") or "").strip()})
        if len(out) >= n:
            break
    return out


# ------------------------------------------------------------------ time machine

def candles(d):
    rows = []
    for t, o, h, l, c in zip(d["t"], d["o"], d["h"], d["l"], d["c"]):
        st = datetime.fromtimestamp(t, timezone.utc)
        if st.minute % C.BAR_MIN or st.second:
            continue
        rows.append((h, l, c))
    return rows


def atr15(sym, bar_end_iso, n=14):
    """ATR(n) of the coin's completed candles (the live timeframe) up to the breakout candle (inclusive)."""
    d = C.crypto_chart(sym, "5d", "%dm" % C.BAR_MIN)
    if not d:
        return None
    cut = datetime.fromisoformat(bar_end_iso)
    bars = []
    for t, h, l, c in zip(d["t"], d["h"], d["l"], d["c"]):
        st = datetime.fromtimestamp(t, timezone.utc)
        if st.minute % C.BAR_MIN or st.second or None in (h, l, c):
            continue
        if st + timedelta(minutes=C.BAR_MIN) > cut:
            continue
        bars.append((h, l, c))
    if len(bars) < n + 1:
        return None
    trs = [max(bars[j][0] - bars[j][1], abs(bars[j][0] - bars[j - 1][2]), abs(bars[j][1] - bars[j - 1][2]))
           for j in range(len(bars) - n, len(bars))]
    return sum(trs) / n


def simulate(rows, entry, stop, target, paths, bars, seed):
    """Replay `bars` candles `paths` times, each drawn whole (as moves vs the prior close)
    from the coin's own history. A candle touching both levels counts as the stop (cautious)."""
    moves = [(rows[i][0] / rows[i - 1][2], rows[i][1] / rows[i - 1][2], rows[i][2] / rows[i - 1][2])
             for i in range(1, len(rows)) if rows[i - 1][2] > 0]
    if len(moves) < 100:
        return None
    rnd = random.Random(seed)
    risk = entry - stop
    tgt = stp = 0
    total_r = 0.0
    for _ in range(paths):
        px = entry
        r = None
        for _ in range(bars):
            mh, ml, mc = moves[rnd.randrange(len(moves))]
            if px * ml <= stop:
                r, stp = -1.0, stp + 1
                break
            if px * mh >= target:
                r, tgt = (target - entry) / risk, tgt + 1
                break
            px *= mc
        if r is None:
            r = (px - entry) / risk
        total_r += r
    return {"paths": paths, "bars": bars, "target_first": round(tgt / paths, 3),
            "stop_first": round(stp / paths, 3), "neither": round((paths - tgt - stp) / paths, 3),
            "avg_r": round(total_r / paths, 3)}


def history(rows, target_r, bars, stop_mode):
    """Every past fresh 4-hour breakout in the window, traded with the same stop/target/time limit."""
    rb = 16  # the time machine replays 15-minute candles (recorded only, not a gate) on any timeframe
    results, i = [], rb + 1
    while i < len(rows) - 1:
        hi = max(r[0] for r in rows[i - rb:i])
        lo = min(r[1] for r in rows[i - rb:i])
        prev_hi = max(r[0] for r in rows[i - rb - 1:i - 1])
        fresh = rows[i][2] > hi and rows[i - 1][2] <= prev_hi
        if not fresh:
            i += 1
            continue
        entry = rows[i][2]
        stop = lo if stop_mode == "range-low" else (hi + lo) / 2
        risk = entry - stop
        if risk <= 0:
            i += 1
            continue
        target = entry + target_r * risk
        r, j = None, i + 1
        while j < len(rows) and j <= i + bars:
            if rows[j][1] <= stop:
                r = -1.0
                break
            if rows[j][0] >= target:
                r = target_r
                break
            j += 1
        if r is None:
            if j > i + bars and i + bars < len(rows):
                r = (rows[i + bars][2] - entry) / risk
            else:
                break  # too recent to know
        results.append(r)
        i = j + 1  # one trade at a time
    if not results:
        return {"fired": 0}
    return {"fired": len(results), "target": sum(1 for r in results if r > 0 and r == target_r),
            "stop": sum(1 for r in results if r == -1.0),
            "neither": sum(1 for r in results if r not in (-1.0, target_r)),
            "avg_r": round(sum(results) / len(results), 3)}


# ------------------------------------------------------------------ pipeline

_RULES = {}


def rules_tag(cfg):
    """Rule version + a short hash of the config, stored with every decision (rulebook: which rules made it)."""
    import hashlib
    body = json.dumps({k: v for k, v in cfg.items() if not k.startswith("_")}, sort_keys=True, default=str)
    return {"version": cfg.get("rules_version"), "hash": hashlib.sha1(body.encode()).hexdigest()[:10]}


def record(rec):
    if _RULES:
        rec.setdefault("rules", dict(_RULES))
    os.makedirs(LIVE_DIR, exist_ok=True)
    with open(DECISIONS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


_btc_cache = {}


def btc_regime():
    """True if BTC's last 15-minute close is above the midpoint of the 16 closes before it (cached 5 min)."""
    hit = _btc_cache.get("v")
    if hit and (datetime.now(timezone.utc) - hit[0]).total_seconds() < 300:
        return hit[1]
    try:
        d = C.crypto_chart("BTC", "2d", "15m")
        closes = [c for t, c in zip(d["t"], d["c"]) if not datetime.fromtimestamp(t, timezone.utc).minute % 15]
        if len(closes) < 18:
            return None
        w = closes[-17:-1]
        v = closes[-1] > (max(w) + min(w)) / 2
    except Exception:
        return None
    _btc_cache["v"] = (datetime.now(timezone.utc), v)
    return v


def run_smc(h, cfg, log):
    """A reclaimed liquidity sweep of the 4h range (smc.py): long after a swept low, short after a swept high."""
    sym, s = h["symbol"], h.get("smc") or {}
    short = h["setup"] == "smc_sweep_short"
    rec = {"time": datetime.now(S.IST).isoformat(), "symbol": "CRYPTO:" + sym, "setup": h["setup"],
           "steps": {}, "result": None}
    st = rec["steps"]
    st["1_scanner"] = {"bar_end": h["bar_end"], "close": h["price"], "range_high": h["range_high"],
                       "range_low": h["range_low"], "variant": s.get("variant"), "level": s.get("level"),
                       "extreme": s.get("extreme"), "vol_ratio": round(s.get("vol_x", 0), 2),
                       "setup_name": "SMC sweep %s" % ("short" if short else "long"), "scanner": "rules",
                       "liquidity": "swept 4h %s %s (%s)" % ("high" if short else "low", s.get("level"), s.get("variant"))}

    def done(result, why):
        rec["result"], rec["why"] = result, why
        st["10_analyst"] = "n/a for crypto"
        st["11_pelosi"] = "n/a for crypto"
        record(rec)
        log("AUTO %s: %s (%s)" % (sym, result, why))
        return rec

    if not s:
        return done("skipped", "scanner sent no sweep details")
    if cfg.get("smc_variant", "any") != "any" and s.get("variant") != cfg["smc_variant"]:
        return done("skipped", "SMC variant: a %s sweep (rule takes %s only)" % (s.get("variant"), cfg["smc_variant"]))
    try:
        st["2_news"] = headlines(sym)
    except Exception as e:
        st["2_news"] = "unavailable: %s" % e
    bar_start = datetime.fromisoformat(h["bar_end"]) - timedelta(minutes=C.BAR_MIN)
    if bar_start.astimezone(timezone.utc).hour in (cfg.get("skip_hours_utc") or []):
        return done("skipped", "thin hours: sweep candle at %02d:%02d UTC (rule skips %s UTC)" % (
            bar_start.hour, bar_start.minute, ",".join(str(x) for x in cfg["skip_hours_utc"])))
    try:
        price, _ = P.fetch_price("CRYPTO", sym)
    except Exception as e:
        return done("skipped", "no live price: %s" % e)
    try:
        atr = atr15(sym, h["bar_end"])
    except Exception as e:
        return done("skipped", "no candles for the ATR: %s" % e)
    if not atr:
        return done("skipped", "not enough candles for the ATR")
    level, extreme, mid = s["level"], s["extreme"], (h["range_high"] + h["range_low"]) / 2
    if short:
        stop = extreme + 0.1 * atr if cfg["smc_stop"] == "sweep" else price + 1.5 * atr
        stop = P.round_px("CRYPTO", stop, down=False)
        risk, back_in = stop - price, price < level
    else:
        stop = extreme - 0.1 * atr if cfg["smc_stop"] == "sweep" else price - 1.5 * atr
        stop = P.round_px("CRYPTO", stop)
        risk, back_in = price - stop, price > level
    st["3_entry"] = {"side": "short" if short else "long", "price_now": price, "reclaimed_level": level,
                     "sweep_extreme": extreme, "atr14_15m": round(atr, 8)}
    if risk <= 0:
        return done("skipped", "price %s is already past the stop %s" % (price, stop))
    if not back_in:
        return done("skipped", "price %s is back outside the 4h range (level %s): the reclaim failed" % (price, level))
    trail = cfg["smc_exit"] == "trail" and not short
    if cfg["smc_exit"] == "mid":
        target = P.round_px("CRYPTO", mid, down=not short)
        if (price - target if short else target - price) < 0.5 * risk:
            return done("skipped", "the 4h range middle %s is under 0.5R away" % target)
    else:
        tr_r = 20.0 if trail else 2.0
        target = P.round_px("CRYPTO", max(price * 0.05, price - tr_r * risk) if short else price + tr_r * risk, down=short)
    fee_pct = P.load_config()["accounts"]["CRYPTO"].get("fee_pct", 0)
    fee_r = 2 * price * fee_pct / 100 / risk
    st["4_exit"] = {"entry": price, "stop": stop, "target": target, "risk": round(risk, 6),
                    "stop_pct": round(risk / price * 100, 3), "fee_r": round(fee_r, 3), "exit": cfg["smc_exit"],
                    "time_stop_hours": cfg["max_hold_hours"]}
    if fee_r > cfg["max_fee_r"]:
        return done("skipped", "fees eat %.2fR of the trade (max %.2fR)" % (fee_r, cfg["max_fee_r"]))
    if s.get("vol_x", 0) < cfg.get("smc_min_vol_x", 0):
        return done("skipped", "sweep volume %.2fx the 4h average (min %.1fx)" % (s.get("vol_x", 0), cfg["smc_min_vol_x"]))
    if cfg.get("smc_regime"):
        reg = btc_regime()
        st["regime"] = reg
        if reg is None:
            return done("skipped", "BTC regime unknown")
        if short and reg is True:
            return done("skipped", "BTC regime: BTC is above its 4h midpoint (no shorts against it)")
        if not short and reg is False:
            return done("skipped", "BTC regime: BTC is not above its 4h midpoint")
    st["5_timemachine"] = "n/a for SMC sweeps (crypto-smc backtest instead): not a gate"
    pcfg = P.load_config()
    led = P.load_ledger(pcfg)
    args = type("A", (), {"symbol": "CRYPTO:" + sym, "stop": str(stop), "target": str(target), "qty": None,
                          "price": str(price), "note": "auto: %s %s" % (h["setup"], s.get("variant")), "force": False,
                          "side": "short" if short else "long", "setup": h["setup"], "scanner": "rules",
                          "setup_name": "SMC sweep %s" % ("short" if short else "long"),
                          "liquidity": "swept 4h %s %s (%s)" % ("high" if short else "low", s.get("level"), s.get("variant")),
                          "entry_reason": "SMC sweep: wick past the 4h %s and a close back inside" % ("high" if short else "low")})()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            P.cmd_buy(args, pcfg, led)
        P.save_json(P.LEDGER, led)
    except P.PaperError as e:
        st["6-8_budget_risk_broker"] = "BLOCK: %s" % e
        return done("blocked", str(e))
    pos = next(p for p in led["open"] if p["key"] == "CRYPTO:" + sym)
    if trail:
        pos.update({"trail_atr": round(atr, 8), "trail_k": cfg["trail_atr_k"], "trail_arm_r": cfg["trail_arm_r"],
                    "peak": pos["entry"]})
        P.save_json(P.LEDGER, led)
    st["6-8_budget_risk_broker"] = {"verdict": "PASS, paper %s filled" % ("short" if short else "buy"), "qty": pos["qty"],
                                    "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
                                    "max_loss": round(abs(pos["entry"] - pos["stop"]) * pos["qty"] + pos["entry_fee"], 2),
                                    "report": buf.getvalue().strip().splitlines()}
    st["9_alerts"] = "live.py checks stop %s / target %s every cycle%s; time stop after %dh" % (
        pos["stop"], pos["target"], " (trailing)" if trail else "", cfg["max_hold_hours"])
    return done("PAPER SHORT" if short else "PAPER BUY", "%s @ %s, stop %s, %s (SMC %s sweep of the 4h %s)" % (
        P.fmt_qty("CRYPTO", pos["qty"]), pos["entry"], pos["stop"],
        "trailing exit" if trail else "target %s" % pos["target"], s.get("variant"), "high" if short else "low"))


_trend_cache = {}


def downtrend(sym, bar_end_iso):
    """'ema+slope', 'ema' or 'none' for a short: close < EMA50 < EMA200 on 15m candles up to the breakdown candle,
    plus EMA200 falling over the last 4 candles for 'ema+slope' (as research_v4 scores trend on mirrored prices)."""
    key = (sym, bar_end_iso)
    if key in _trend_cache:
        return _trend_cache[key]
    d = C.crypto_chart(sym, "15d", "15m")
    cut = datetime.fromisoformat(bar_end_iso)
    closes = [c for t, c in zip(d["t"], d["c"]) if c is not None and not datetime.fromtimestamp(t, timezone.utc).minute % 15
              and datetime.fromtimestamp(t, timezone.utc) + timedelta(minutes=15) <= cut] if d else []
    out = "unknown"
    if len(closes) >= 400:
        def ema(vals, n):
            k, e, res = 2 / (n + 1), None, []
            for v in vals:
                e = v if e is None else e + k * (v - e)
                res.append(e)
            return res
        e50, e200 = ema(closes, 50), ema(closes, 200)
        out = "none"
        if closes[-1] < e50[-1] < e200[-1]:
            out = "ema+slope" if e200[-1] < e200[-5] else "ema"
    _trend_cache[key] = out
    return out


def run_smcp(h, cfg, log):
    """The user's SMC Trading Playbook (smc_playbook.py). Agent steps: scanner = liquidity map and sweep, entry =
    trigger pattern + candle 1/2 close, exit = buffer stop and liquidity target."""
    sym, s = h["symbol"], h.get("smcp") or {}
    short = s.get("side") == "short"
    rec = {"time": datetime.now(S.IST).isoformat(), "symbol": "CRYPTO:" + sym, "setup": h["setup"],
           "steps": {}, "result": None}
    st = rec["steps"]

    def done(result, why):
        rec["result"], rec["why"] = result, why
        st["10_analyst"] = "n/a for crypto"
        st["11_pelosi"] = "n/a for crypto"
        record(rec)
        log("AUTO %s: %s (%s)" % (sym, result, why))
        return rec

    if not s:
        return done("skipped", "scanner sent no playbook details")
    st["1_scanner"] = {"bar_end": h["bar_end"], "close": h["price"], "liquidity_swept": s.get("level_name"),
                       "setup_name": "Playbook %s" % str(s.get("setup", "")).replace("_", " "), "scanner": "rules",
                       "liquidity": "swept %s %s" % (s.get("level_name"), s.get("level")),
                       "level": s.get("level"), "sweep_extreme": s.get("extreme"),
                       "sweep_candles_ago": s.get("trigger", 0) - s.get("sweep_at", 0) + s.get("confirm_at", 0),
                       "bos_choch_before_sweep": s.get("struct_before"), "bos_choch_any": s.get("struct_any")}
    pattern = {"doji_long": "doji", "doji_short": "doji", "star_long": "bottom star", "hammer_short": "top hammer",
               "fvg_long": "FVG retest", "fvg_short": "FVG retest", "ob_long": "order block retest",
               "ob_short": "order block retest"}
    st["3_entry"] = {"side": "short" if short else "long", "pattern": pattern.get(s.get("setup"), s.get("setup")),
                     "trigger_high": s.get("hi"), "trigger_low": s.get("lo"), "body_pct": round(s.get("body_pct", 0), 3),
                     "confirmed_by": "candle %s close %s %s" % (s.get("confirm_at"), "<" if short else ">",
                                                                s.get("lo") if short else s.get("hi"))}
    if s.get("confirm_at", 9) > int(cfg.get("smcp_confirm", 2)):
        return done("skipped", "playbook: confirmed on candle %s (rule takes candle 1 only)" % s.get("confirm_at"))
    need = cfg.get("smcp_struct", "before")
    if need == "before" and not s.get("struct_before") or need == "any" and not s.get("struct_any"):
        return done("skipped", "playbook: no %s BOS/CHoCH %s the sweep" % (
            "bearish" if short else "bullish", "before" if need == "before" else "around"))
    liq = cfg.get("smcp_liq", "base")
    zone = s.get("level_name") in ("FVG", "OB")
    if not zone and liq == "base" and s.get("level_name") in ("PWH", "PWL"):
        return done("skipped", "playbook: sweep of last week's %s (smcp_liq = base ignores weekly levels)" % s["level_name"])
    if not zone and liq == "strong" and not (s.get("level_name") in ("PDH", "PDL", "PWH", "PWL") or s.get("eq")):
        return done("skipped", "playbook: %s is not strong liquidity (needs PDH/PDL/PWH/PWL or equal highs/lows)"
                    % s.get("level_name"))
    if s.get("disp", 0) < float(cfg.get("smcp_min_disp", 0) or 0):
        return done("skipped", "playbook: entry candle body %.2f ATR, no displacement (min %.2f)" % (
            s.get("disp", 0), float(cfg["smcp_min_disp"])))
    if s.get("setup", "").startswith("doji") and s.get("body_pct", 1) > float(cfg.get("smcp_doji_pct", 0.15)):
        return done("skipped", "playbook: doji body %.0f%% of the range (max %.0f%%)" % (
            100 * s.get("body_pct", 0), 100 * float(cfg.get("smcp_doji_pct", 0.15))))
    try:
        st["2_news"] = headlines(sym)
    except Exception as e:
        st["2_news"] = "unavailable: %s" % e
    bar_start = datetime.fromisoformat(h["bar_end"]) - timedelta(minutes=C.BAR_MIN)
    if cfg.get("smcp_skip_thin_hours") and bar_start.astimezone(timezone.utc).hour in (cfg.get("skip_hours_utc") or []):
        return done("skipped", "thin hours: candle at %02d:%02d UTC" % (bar_start.hour, bar_start.minute))
    try:
        price, _ = P.fetch_price("CRYPTO", sym)
    except Exception as e:
        return done("skipped", "no live price: %s" % e)
    import smc_playbook as PB
    stop = PB.stop_for(s, float(cfg.get("smcp_buffer_atr", 0.1)))
    stop = P.round_px("CRYPTO", stop, down=not short)
    risk = (stop - price) if short else (price - stop)
    if risk <= 0:
        return done("skipped", "price %s is already past the stop %s" % (price, stop))
    if (price > s["hi"]) if short else (price < s["lo"]):
        return done("skipped", "price %s is back beyond the other side of the trigger candle: setup cancelled" % price)
    mode = cfg.get("smcp_target", "internal")
    trail = mode == "trail"
    if mode in ("internal", "external"):
        target = s.get("%s_target" % mode)
        if target is None or (target >= price if short else target <= price):
            return done("skipped", "playbook: no %s liquidity left beyond the price for a target" % mode)
    elif trail:
        target = max(price * 0.05, price - 20 * risk) if short else price + 20 * risk
    else:
        target = price - 2 * risk if short else price + 2 * risk
    target = P.round_px("CRYPTO", target, down=short)
    fee_pct = P.load_config()["accounts"]["CRYPTO"].get("fee_pct", 0)
    fee_r = (2 * price if trail else price + target) * fee_pct / 100 / risk
    rr = abs(target - price) / risk
    st["4_exit"] = {"entry": price, "stop": stop, "stop_rule": "%s + %g ATR" % (
                        "other side of the doji" if s["setup"].startswith("doji") else "pattern / sweep extreme",
                        float(cfg.get("smcp_buffer_atr", 0.1))),
                    "target": target, "target_rule": mode, "risk": round(risk, 6), "reward_r": round(rr, 2),
                    "net_r_after_fees": None if trail else round(rr - fee_r, 2), "fee_r": round(fee_r, 3),
                    "time_stop_hours": cfg["max_hold_hours"]}
    if fee_r > cfg["max_fee_r"]:
        return done("skipped", "fees eat %.2fR of the trade (max %.2fR)" % (fee_r, cfg["max_fee_r"]))
    if not trail and rr - fee_r < float(cfg.get("smcp_min_rr", 1.0)):
        return done("skipped", "playbook: target only %.2fR away after fees (min %.1fR): reward does not justify "
                               "the stop" % (rr - fee_r, float(cfg.get("smcp_min_rr", 1.0))))
    if cfg.get("smcp_regime"):
        reg = btc_regime()
        st["regime"] = reg
        if reg is None:
            return done("skipped", "BTC regime unknown")
        if short and reg is True:
            return done("skipped", "BTC regime: BTC is above its 4h midpoint (no shorts against it)")
        if not short and reg is False:
            return done("skipped", "BTC regime: BTC is not above its 4h midpoint")
    st["5_timemachine"] = "n/a for the playbook (crypto-smcp backtest instead): not a gate"
    pcfg = P.load_config()
    led = P.load_ledger(pcfg)
    args = type("A", (), {"symbol": "CRYPTO:" + sym, "stop": str(stop), "target": str(target), "qty": None,
                          "price": str(price), "note": "auto: playbook %s after %s sweep" % (
                              s["setup"], s.get("level_name")), "force": False,
                          "side": "short" if short else "long", "setup": "smcp_" + s["setup"], "scanner": "rules",
                          "setup_name": "Playbook %s" % s["setup"].replace("_", " "),
                          "liquidity": "swept %s %s" % (s.get("level_name"), s.get("level")),
                          "entry_reason": "Playbook %s after a sweep of %s, confirmed on candle %s" % (
                              s["setup"].replace("_", " "), s.get("level_name"), s.get("confirm_at"))})()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            P.cmd_buy(args, pcfg, led)
        P.save_json(P.LEDGER, led)
    except P.PaperError as e:
        st["6-8_budget_risk_broker"] = "BLOCK: %s" % e
        return done("blocked", str(e))
    pos = next(p for p in led["open"] if p["key"] == "CRYPTO:" + sym)
    if trail:
        pos.update({"trail_atr": round(s["atr"], 8), "trail_k": cfg["trail_atr_k"], "trail_arm_r": cfg["trail_arm_r"],
                    "peak": pos["entry"]})
        P.save_json(P.LEDGER, led)
    st["6-8_budget_risk_broker"] = {"verdict": "PASS, paper %s filled" % ("short" if short else "buy"), "qty": pos["qty"],
                                    "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
                                    "max_loss": round(abs(pos["entry"] - pos["stop"]) * pos["qty"] + pos["entry_fee"], 2),
                                    "report": buf.getvalue().strip().splitlines()}
    st["9_alerts"] = "live.py checks stop %s / target %s every cycle%s; time stop after %dh" % (
        pos["stop"], pos["target"], " (trailing)" if trail else "", cfg["max_hold_hours"])
    return done("PAPER SHORT" if short else "PAPER BUY", "%s @ %s, stop %s, %s (playbook %s after a %s sweep)" % (
        P.fmt_qty("CRYPTO", pos["qty"]), pos["entry"], pos["stop"],
        "trailing exit" if trail else "target %s (%s)" % (pos["target"], mode), pattern.get(s["setup"]),
        s.get("level_name")))


def run_one(h, cfg, log):
    if h["setup"].startswith("smcp_"):
        return run_smcp(h, cfg, log)
    if h["setup"].startswith("smc_sweep"):
        return run_smc(h, cfg, log)
    sym = h["symbol"]
    rec = {"time": datetime.now(S.IST).isoformat(), "symbol": "CRYPTO:" + sym, "setup": h["setup"],
           "steps": {}, "result": None}
    st = rec["steps"]
    brk_short = h["setup"] == "range_breakdown_4h"
    st["1_scanner"] = {"bar_end": h["bar_end"], "close": h["price"], "range_high": h["range_high"],
                       "range_low": h["range_low"], "pct_vs_high": h["pct_vs_high"], "vol_ratio": h["vol_ratio"],
                       "setup_name": "4h breakdown" if brk_short else "4h breakout", "scanner": "rules",
                       "liquidity": "4h range %s %s" % ("low" if brk_short else "high",
                                                        h["range_low"] if brk_short else h["range_high"])}

    def done(result, why):
        rec["result"], rec["why"] = result, why
        st["10_analyst"] = "n/a for crypto"
        st["11_pelosi"] = "n/a for crypto"
        record(rec)
        log("AUTO %s: %s (%s)" % (sym, result, why))
        return rec

    try:
        st["2_news"] = headlines(sym)
    except Exception as e:
        st["2_news"] = "unavailable: %s" % e

    try:
        price, qt = P.fetch_price("CRYPTO", sym)
    except Exception as e:
        return done("skipped", "no live price: %s" % e)
    short = h["setup"] == "range_breakdown_4h"
    mid = (h["range_high"] + h["range_low"]) / 2
    bar_start = datetime.fromisoformat(h["bar_end"]) - timedelta(minutes=C.BAR_MIN)
    if short:   # short-only filters (crypto-v4-short): a squeeze range and a coin already in a downtrend
        rng_pct = (h["range_high"] - h["range_low"]) / price * 100
        if cfg.get("short_max_range_pct") and rng_pct > cfg["short_max_range_pct"]:
            return done("skipped", "short: 4h range %.2f%% wide (max %.1f%%: shorts take tight ranges only)"
                        % (rng_pct, cfg["short_max_range_pct"]))
        want = cfg.get("short_trend", "off")
        if want != "off":
            try:
                tr = downtrend(sym, h["bar_end"])
            except Exception as e:
                tr = "unknown (%s)" % e
            st["short_trend"] = tr
            if tr not in (("ema", "ema+slope") if want == "ema" else ("ema+slope",)):
                return done("skipped", "short: coin not in a downtrend (%s; rule wants %s: close < EMA50 < EMA200%s)"
                            % (tr, want, ", EMA200 falling" if want == "ema+slope" else ""))
    thin = cfg.get("skip_hours_utc") or []
    if short and not cfg.get("short_skip_thin_hours", True):
        thin = []
    if bar_start.astimezone(timezone.utc).hour in thin:
        return done("skipped", "thin hours: breakout candle at %02d:%02d UTC (rule skips %s UTC)" % (
            bar_start.hour, bar_start.minute, ",".join(str(x) for x in cfg["skip_hours_utc"])))
    atr = None
    if cfg["stop"] == "atr":
        try:
            atr = atr15(sym, h["bar_end"])
        except Exception as e:
            return done("skipped", "no candles for the ATR stop: %s" % e)
        if not atr:
            return done("skipped", "not enough candles for the ATR stop")
        st["3_atr"] = {"atr14_15m": round(atr, 8), "k": cfg["stop_atr_k"]}
    if short:   # breakdown below the 4h low: short, stop at the range midpoint (or the high), above the entry
        if atr:
            stop = P.round_px("CRYPTO", price + cfg["stop_atr_k"] * atr, down=False)
        else:
            stop = P.round_px("CRYPTO", h["range_high"] if cfg["stop"] == "range-low" else mid, down=False)
        trigger, risk = h["range_low"], stop - price
        beyond = trigger - price
    else:
        if atr:
            stop = P.round_px("CRYPTO", price - cfg["stop_atr_k"] * atr)
        else:
            stop = P.round_px("CRYPTO", h["range_low"] if cfg["stop"] == "range-low" else mid)
        trigger, risk = h["range_high"], price - stop
        beyond = price - trigger
    chase = beyond / risk if risk > 0 else None
    st["3_entry"] = {"side": "short" if short else "long", "price_now": price, "trigger": trigger,
                     "chase_r": round(chase, 2) if chase is not None else None}
    if risk <= 0:
        return done("skipped", "price %s is already past the stop %s" % (price, stop))
    if beyond < 0:
        return done("skipped", "price %s moved back inside the 4h range (%s %s)" % (
            price, "low" if short else "high", trigger))
    if cfg.get("max_chase_r") and chase > cfg["max_chase_r"]:
        return done("skipped", "chasing: price is %.2fR past the trigger (max %.2fR)" % (chase, cfg["max_chase_r"]))

    trail = (cfg.get("short_exit") == "trail") if short else (cfg.get("exit") == "trail")
    tr_r = 20.0 if trail else cfg["target_r"]  # trailing: a far "target" only for display; the trail exits
    target = P.round_px("CRYPTO", price - tr_r * risk if short else price + tr_r * risk, down=short)
    fee_pct = P.load_config()["accounts"]["CRYPTO"].get("fee_pct", 0)
    if trail:  # buy fee + sell fee near the entry, in R (as research_v4 scores the trailing exit)
        fee_r = 2 * price * fee_pct / 100 / risk
    else:      # buy fee + sell fee at the target, in R
        fee_r = (price + target) * fee_pct / 100 / risk
    stop_pct = risk / price * 100
    st["4_exit"] = {"entry": price, "stop": stop, "target": target, "risk": round(risk, 6),
                    "stop_pct": round(stop_pct, 3), "fee_r": round(fee_r, 3),
                    "r_multiple": "trailing" if trail else cfg["target_r"], "time_stop_hours": cfg["max_hold_hours"]}
    if cfg.get("min_stop_pct") and stop_pct < cfg["min_stop_pct"]:
        return done("skipped", "stop too tight: %.2f%% below the entry (min %.2f%%)" % (stop_pct, cfg["min_stop_pct"]))
    if fee_r > cfg["max_fee_r"]:
        return done("skipped", "fees eat %.2fR of the trade (max %.2fR)" % (fee_r, cfg["max_fee_r"]))
    min_vol = cfg.get("short_min_vol_x", cfg.get("min_vol_x", 0)) if short else cfg.get("min_vol_x", 0)
    if min_vol and h.get("vol_ratio") is None:
        return done("skipped", "breakout candle's volume not reported yet by Yahoo (cannot check the volume rule)")
    if h.get("vol_ratio") is not None and h["vol_ratio"] < min_vol:
        return done("skipped", "breakout volume %.2fx the 4h average (min %.1fx)" % (h["vol_ratio"], min_vol))
    if cfg.get("btc_regime"):
        reg = btc_regime()
        st["regime"] = reg
        if reg is None:
            return done("skipped", "BTC regime unknown")
        if short and reg is True:
            return done("skipped", "BTC regime: BTC is above its 4h midpoint (no shorts against it)")
        if not short and reg is False:
            return done("skipped", "BTC regime: BTC is not above its 4h midpoint")

    if short:  # the replay/history time machine is long-only; it is not a gate since rules v2 anyway
        sim, hist = {"avg_r": 0.0}, {}
        st["5_timemachine"] = "n/a for shorts (not a gate since rules v2)"
    else:
        try:
            d = C.crypto_chart(sym, "%dd" % cfg["history_days"], "15m")
            rows = candles(d) if d else []
        except Exception as e:
            return done("skipped", "time machine had no history: %s" % e)
        sim = simulate(rows, price, stop, target, cfg["sim_paths"], cfg["sim_bars"], cfg["seed"])
        hist = history(rows, cfg["target_r"], cfg["sim_bars"], cfg["stop"])
        if sim is None:
            st["5_timemachine"] = {"candles": len(rows), "sim": None, "history": hist}
            return done("skipped", "time machine: too little history (%d candles)" % len(rows))
        # every R below is after the round-trip fee
        sim["avg_r_before_fees"] = sim["avg_r"]
        sim["avg_r"] = round(sim["avg_r"] - fee_r, 3)
        if hist.get("fired"):
            hist["avg_r_before_fees"] = hist["avg_r"]
            hist["avg_r"] = round(hist["avg_r"] - fee_r, 3)
        st["5_timemachine"] = {"candles": len(rows), "sim": sim, "history": hist, "fee_r": round(fee_r, 3)}
        if sim["avg_r"] < cfg["min_sim_avg_r"]:
            return done("skipped", "time machine: replays average %+.2fR (min %+.2fR)" % (sim["avg_r"], cfg["min_sim_avg_r"]))
        if hist.get("fired", 0) >= cfg["min_history_trades"] and hist["avg_r"] < cfg["min_history_avg_r"]:
            return done("skipped", "time machine: this rule averaged %+.2fR over its last %d trades"
                        % (hist["avg_r"], hist["fired"]))

    pcfg = P.load_config()
    led = P.load_ledger(pcfg)
    args = type("A", (), {"symbol": "CRYPTO:" + sym, "stop": str(stop), "target": str(target), "qty": None,
                          "price": str(price), "note": "auto: %s" % h["setup"], "force": False,
                          "side": "short" if short else "long", "setup": h["setup"], "scanner": "rules",
                          "setup_name": "4h breakdown" if short else "4h breakout",
                          "liquidity": "4h range %s %s" % ("low" if short else "high", trigger),
                          "entry_reason": "close %s the 4h range %s %s (volume %sx)" % (
                              "below" if short else "above", "low" if short else "high", trigger, h.get("vol_ratio"))})()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            P.cmd_buy(args, pcfg, led)
        P.save_json(P.LEDGER, led)
    except P.PaperError as e:
        st["6-8_budget_risk_broker"] = "BLOCK: %s" % e
        return done("blocked", str(e))
    pos = next(p for p in led["open"] if p["key"] == "CRYPTO:" + sym)
    if trail:  # paper.py check_once moves the stop: break-even at +arm R, then k x ATR under the peak
        pos.update({"trail_atr": round(atr if atr else risk / max(cfg["stop_atr_k"], 1e-9), 8),
                    "trail_k": cfg["trail_atr_k"], "trail_arm_r": cfg["trail_arm_r"], "peak": pos["entry"]})
        P.save_json(P.LEDGER, led)
    st["6-8_budget_risk_broker"] = {"verdict": "PASS, paper %s filled" % ("short" if short else "buy"), "qty": pos["qty"],
                                    "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
                                    "max_loss": round(abs(pos["entry"] - pos["stop"]) * pos["qty"] + pos["entry_fee"], 2),
                                    "report": buf.getvalue().strip().splitlines()}
    st["9_alerts"] = ("live.py checks the stop every cycle; it trails (break-even at +%gR, then %g x ATR under the "
                      "high); time stop after %dh" % (cfg["trail_arm_r"], cfg["trail_atr_k"], cfg["max_hold_hours"])
                      if trail else "live.py checks stop %s / target %s every cycle; time stop after %dh" % (
                          pos["stop"], pos["target"], cfg["max_hold_hours"]))
    return done("PAPER SHORT" if short else "PAPER BUY", "%s @ %s, stop %s, %s; sim avg %+.2fR, history %s"
                % (P.fmt_qty("CRYPTO", pos["qty"]), pos["entry"], pos["stop"],
                   "trailing exit" if trail else "target %s" % pos["target"], sim["avg_r"],
                   ("%d trades avg %+.2fR" % (hist["fired"], hist["avg_r"])) if hist.get("fired") else "no past fires"))


def time_stops(cfg, log):
    pcfg = P.load_config()
    if not os.path.exists(P.LEDGER):
        return
    led = P.load_ledger(pcfg)
    now = datetime.now(timezone.utc)
    changed = False
    for pos in list(led["open"]):
        if pos["market"] != "CRYPTO" or P.pdf_only(pos):   # v4 trades: TP / SL only (the PDF)
            continue
        age = now - datetime.fromisoformat(pos["entry_time"])
        if age >= timedelta(hours=cfg["max_hold_hours"]):
            try:
                price = P.fetch_price("CRYPTO", pos["symbol"])[0]
            except Exception as e:
                log("AUTO time stop for %s waiting on a price: %s" % (pos["key"], e))
                continue
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rec = P.close_position(led, pcfg, pos, price, "time stop %dh" % cfg["max_hold_hours"], now)
            log("AUTO %s closed by time stop at %s: %+.2fR" % (pos["key"], price, rec["r"]))
            changed = True
    if changed:
        P.save_json(P.LEDGER, led)


def process(state, res, log):
    """Called by live.py after each crypto scan."""
    cfg = load_cfg()
    _RULES.clear()
    _RULES.update(rules_tag(cfg))
    time_stops(cfg, log)
    out = []
    import smc_playbook as PB
    v4 = PB.v4_only("CRYPTO")
    if v4:   # Scanner v4 / v5 only: the rules setups (4h breakout, SMC, playbook, rulebook) are not traded
        n = sum(1 for h in res.get("hits", []) if h.get("new") and h["setup"] in cfg["enabled_setups"])
        if n:
            log("AUTO CRYPTO: Scanner %s only: %d rules-setup hit%s ignored (%s); only %s setups are traded" % (
                v4, n, "" if n == 1 else "s", ", ".join(sorted({h["setup"] for h in res.get("hits", [])
                                                            if h.get("new") and h["setup"] in cfg["enabled_setups"]})), v4))
    for h in ([] if v4 else res.get("hits", [])):
        if h.get("new") and h["setup"] in cfg["enabled_setups"]:
            try:
                out.append(run_one(h, cfg, log))
            except Exception as e:
                log("AUTO %s failed: %s" % (h["symbol"], e))
    # The Scanner (v4, v3 or v2, per Settings): the owner's setups on this candle. One ticked in enabled_setups went
    # through run_smcp above; every other one goes through the agents (P.setup_decision: paper trade or LOG ONLY).
    for x in res.get("setups", []):
        if x["setup"] in cfg["enabled_setups"] and not v4:
            continue
        try:
            rec = P.setup_decision("CRYPTO", x["symbol"], x, news=headlines(x["symbol"]))
        except Exception as e:
            log("AUTO %s %s failed: %s" % (x["symbol"], x["setup"], e))
            continue
        rec["rules"] = dict(_RULES)
        record(rec)
        log("AUTO CRYPTO: Scanner %s found %s on %s: %s (%s)" % (
            x.get("scanner") or "?", x.get("name"), x["symbol"], rec["result"], rec["why"]))
    auto = state.setdefault("auto", {"recent": []})
    auto["recent"] = (auto.get("recent", []) + [{"time": r["time"], "symbol": r["symbol"], "result": r["result"],
                                                 "why": r["why"]} for r in out])[-20:]
    auto["config"] = AUTO_CONFIG
    return out
