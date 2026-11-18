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
from datetime import datetime, timedelta, timezone

import paper as P
import tm_india as TM
from autolib import headlines, record
import scan_crypto as C
import scan_nse as S

LIVE_DIR = os.path.join("trader", "live")
AUTO_CONFIG = os.path.join(LIVE_DIR, "auto_config.json")

DEFAULTS = {
    "_note": "Auto PAPER trading rules for crypto. Paper money only.",
    "enabled_setups": ["range_breakout_4h"],   # add "range_breakdown_4h" for shorts, only if research.py
                                               # crypto-short is positive out-of-sample
    "stop": "range-mid",          # range-mid or range-low
    "target_r": 2.0,
    "max_chase_r": 0.5,           # skip if price already ran more than this many R past the range high
    "rules_version": 3,           # v3: volume 1.5x (same out-of-sample edge as 2x, ~20% more trades; research 31 Oct)
    "min_stop_pct": 1.0,          # the stop must be at least this % below the entry (noise + fees)
    "min_vol_x": 1.5,             # breakout candle volume vs the 4h range's average
    "btc_regime": True,           # BTC's last close above the midpoint of its own prior 4h of closes
    "max_fee_r": 0.25,            # skip if the round-trip fee costs more than this many R
    "sim_paths": 2000,
    "sim_bars": 24,               # 24 x 15 min = 6 hours
    "history_days": 30,
    "min_sim_avg_r": -99,         # replays are recorded but no longer gate (the backtest never tested them)
    "min_history_trades": 5,      # history only counts once the rule fired this often
    "min_history_avg_r": -99,     # history recorded, not a gate (the backtest winner did not use it)
    "max_hold_hours": 6,          # time stop for open crypto paper trades
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


# ------------------------------------------------------------------ time machine

def candles(d):
    rows = []
    for t, o, h, l, c in zip(d["t"], d["o"], d["h"], d["l"], d["c"]):
        st = datetime.fromtimestamp(t, timezone.utc)
        if st.minute % C.BAR_MIN or st.second:
            continue
        rows.append((h, l, c))
    return rows


def simulate(rows, entry, stop, target, paths, bars, seed):
    """Replay `bars` candles `paths` times, each drawn whole (as moves vs the prior close)
    from the coin's own history (tm_india.walk). A candle touching both levels counts as the stop (cautious)."""
    moves = [(rows[i][0] / rows[i - 1][2], rows[i][1] / rows[i - 1][2], rows[i][2] / rows[i - 1][2])
             for i in range(1, len(rows)) if rows[i - 1][2] > 0]
    if len(moves) < 100:
        return None
    return dict({"paths": paths, "bars": bars}, **TM.walk(moves, entry, stop, target, bars, paths, seed))


def history(rows, target_r, bars, stop_mode):
    """Every past fresh 4-hour breakout in the window, traded with the same stop/target/time limit."""
    rb = C.RANGE_BARS
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


def run_one(h, cfg, log):
    sym = h["symbol"]
    rec = {"time": datetime.now(S.IST).isoformat(), "symbol": "CRYPTO:" + sym, "setup": h["setup"],
           "steps": {}, "result": None}
    st = rec["steps"]
    st["1_scanner"] = {"bar_end": h["bar_end"], "close": h["price"], "range_high": h["range_high"],
                       "range_low": h["range_low"], "pct_vs_high": h["pct_vs_high"], "vol_ratio": h["vol_ratio"]}

    def done(result, why):
        rec["result"], rec["why"] = result, why
        st["10_analyst"] = "n/a for crypto"
        st["11_pelosi"] = "n/a for crypto"
        record(rec)
        log("AUTO %s: %s (%s)" % (sym, result, why))
        return rec

    try:
        st["2_news"] = headlines(sym + C.SUFFIX)
    except Exception as e:
        st["2_news"] = "unavailable: %s" % e

    try:
        price, qt = P.fetch_price("CRYPTO", sym)
    except Exception as e:
        return done("skipped", "no live price: %s" % e)
    short = h["setup"] == "range_breakdown_4h"
    mid = (h["range_high"] + h["range_low"]) / 2
    if short:   # breakdown below the 4h low: short, stop at the range midpoint (or the high), above the entry
        stop = P.round_px("CRYPTO", h["range_high"] if cfg["stop"] == "range-low" else mid, down=False)
        trigger, risk = h["range_low"], stop - price
        beyond = trigger - price
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
    if chase > cfg["max_chase_r"]:
        return done("skipped", "chasing: price is %.2fR past the trigger (max %.2fR)" % (chase, cfg["max_chase_r"]))

    target = P.round_px("CRYPTO", price - cfg["target_r"] * risk if short else price + cfg["target_r"] * risk,
                        down=short)
    fee_pct = P.load_config()["accounts"]["CRYPTO"].get("fee_pct", 0)
    fee_r = (price + target) * fee_pct / 100 / risk  # buy fee + sell fee at the target, in R
    stop_pct = risk / price * 100
    st["4_exit"] = {"entry": price, "stop": stop, "target": target, "risk": round(risk, 6),
                    "stop_pct": round(stop_pct, 3), "fee_r": round(fee_r, 3),
                    "r_multiple": cfg["target_r"], "time_stop_hours": cfg["max_hold_hours"]}
    if stop_pct < cfg["min_stop_pct"]:
        return done("skipped", "stop too tight: %.2f%% below the entry (min %.2f%%)" % (stop_pct, cfg["min_stop_pct"]))
    if fee_r > cfg["max_fee_r"]:
        return done("skipped", "fees eat %.2fR of the trade (max %.2fR)" % (fee_r, cfg["max_fee_r"]))
    if cfg.get("min_vol_x", 0) and h.get("vol_ratio") is None:
        return done("skipped", "breakout candle's volume not reported yet by Yahoo (cannot check the volume rule)")
    if h.get("vol_ratio") is not None and h["vol_ratio"] < cfg.get("min_vol_x", 0):
        return done("skipped", "breakout volume %.2fx the 4h average (min %.1fx)" % (h["vol_ratio"], cfg["min_vol_x"]))
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
                          "side": "short" if short else "long"})()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            P.cmd_buy(args, pcfg, led)
        P.save_json(P.LEDGER, led)
    except P.PaperError as e:
        st["6-8_budget_risk_broker"] = "BLOCK: %s" % e
        return done("blocked", str(e))
    pos = next(p for p in led["open"] if p["key"] == "CRYPTO:" + sym)
    st["6-8_budget_risk_broker"] = {"verdict": "PASS, paper %s filled" % ("short" if short else "buy"), "qty": pos["qty"],
                                    "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
                                    "max_loss": round(abs(pos["entry"] - pos["stop"]) * pos["qty"] + pos["entry_fee"], 2),
                                    "report": buf.getvalue().strip().splitlines()}
    st["9_alerts"] = "live.py checks stop %s / target %s every cycle; time stop after %dh" % (
        pos["stop"], pos["target"], cfg["max_hold_hours"])
    return done("PAPER SHORT" if short else "PAPER BUY", "%s @ %s, stop %s, target %s; sim avg %+.2fR, history %s"
                % (P.fmt_qty("CRYPTO", pos["qty"]), pos["entry"], pos["stop"], pos["target"], sim["avg_r"],
                   ("%d trades avg %+.2fR" % (hist["fired"], hist["avg_r"])) if hist.get("fired") else "no past fires"))


def time_stops(cfg, log):
    pcfg = P.load_config()
    if not os.path.exists(P.LEDGER):
        return
    led = P.load_ledger(pcfg)
    now = datetime.now(timezone.utc)
    changed = False
    for pos in list(led["open"]):
        if pos["market"] != "CRYPTO":
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
    time_stops(cfg, log)
    out = []
    for h in res.get("hits", []):
        if h.get("new") and h["setup"] in cfg["enabled_setups"]:
            try:
                out.append(run_one(h, cfg, log))
            except Exception as e:
                log("AUTO %s failed: %s" % (h["symbol"], e))
    auto = state.setdefault("auto", {"recent": []})
    auto["recent"] = (auto.get("recent", []) + [{"time": r["time"], "symbol": r["symbol"], "result": r["result"],
                                                 "why": r["why"]} for r in out])[-20:]
    auto["config"] = AUTO_CONFIG
    return out
