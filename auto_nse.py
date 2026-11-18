#!/usr/bin/env python3
"""
auto_nse.py - NSE equity opening-range breakouts, run through the agent pipeline automatically,
with PAPER trades only (paper.py's INDIA account; nothing reaches a broker).

live.py --auto-paper calls process() after every NSE opening-range scan. Each NEW breakout that is
still above its range goes through:

  1 scanner      the hit (first 5-minute close above the 9:15-9:30 range)
  2 news         Yahoo Finance headlines for SYMBOL.NS (recorded, never acted on)
  3 entry        live price; skips a chase, a breakout that fell back, a late one (entry window)
     filters     market regime (Nifty above its own range midpoint and its open), breakout volume
                 >= min_vol_x times the range bars' average, opening gap within max_gap_pct
                 (a big gap usually means results or news: skipped)
  4 exit         stop at the range midpoint, target N x the risk; skips stops tighter than min_stop_pct
  5 timemachine  tm_india: the stock's own last 60 days (history of the rule + replays of the rest of
                 today), after charges; both must clear their minimum
  6 budget  \\
  7 risk     >   paper.py buy (INDIA account: max loss, position cap, cash, daily loss limit, trades/day)
  8 broker  /
  9 alerts       live.py's paper check: stop, breakeven at +1R, target, flat by 15:15
 10 analyst      n/a here (results season: the gap filter is a stand-in, not an earnings calendar)
 11 pelosi       n/a for India

Rules: trader/live/auto_nse_config.json (made on first run). Decisions: trader/live/decisions.jsonl.
"""
import contextlib
import io
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import paper as P
import scan_nse as S
import tm_india as TM

LIVE_DIR = os.path.join("trader", "live")
CFG_FILE = os.path.join(LIVE_DIR, "auto_nse_config.json")
DECISIONS = os.path.join(LIVE_DIR, "decisions.jsonl")

DEFAULTS = {
    "_note": "Auto PAPER trading rules for NSE stocks (INDIA account). Paper money only.",
    "entry_start": "09:35",
    "entry_end": "11:30",
    "fresh_minutes": 10,
    "target_r": 2.0,
    "stop": "range-mid",
    "min_stop_pct": 0.4,
    "max_chase_r": 0.5,
    "min_vol_x": 1.5,
    "max_gap_pct": 3.0,
    "regime_filter": True,
    "min_sim_avg_r": 0.10,
    "min_history_trades": 10,
    "min_history_avg_r": 0.10,
    "sim_paths": 2000,
    "max_new_per_cycle": 3,
    "auto_buy": False,            # research.py nse (31 Oct 2026): no filter combination had an edge after
                                  # charges over 60 days, so candidates are evaluated and logged, not bought
}


def load_cfg():
    os.makedirs(LIVE_DIR, exist_ok=True)
    if not os.path.exists(CFG_FILE):
        with open(CFG_FILE, "w", encoding="utf-8") as fh:
            json.dump(DEFAULTS, fh, indent=2)
    cfg = dict(DEFAULTS)
    with open(CFG_FILE, encoding="utf-8") as fh:
        cfg.update(json.load(fh))
    return cfg


def hm(s):
    h, m = s.split(":")
    return int(h), int(m)


def headlines(sym, suffix=".NS", n=3):
    url = ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=IN&lang=en-IN"
           % urllib.parse.quote(sym + suffix))
    req = urllib.request.Request(url, headers={"User-Agent": S.UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        root = ET.fromstring(r.read())
    out = []
    for item in root.iter("item"):
        out.append({"title": (item.findtext("title") or "").strip(), "published": (item.findtext("pubDate") or "").strip()})
        if len(out) >= n:
            break
    return out


def regime(now):
    """Nifty 50 vs its own opening range and open, from today's 5-minute bars."""
    d = S.yahoo_chart("^NSEI", "1d", "5m", "")
    if not d:
        return None
    bars = [(datetime.fromtimestamp(t, S.IST), o, h, l, c) for t, o, h, l, c in zip(d["t"], d["o"], d["h"], d["l"], d["c"])
            if datetime.fromtimestamp(t, S.IST).date() == now.date()]
    o_start = S.at(now, S.OPEN)
    rng = [b for b in bars if o_start <= b[0] < o_start + timedelta(minutes=15)]
    if not rng or not bars:
        return None
    hi, lo = max(b[2] for b in rng), min(b[3] for b in rng)
    last, day_open = bars[-1][4], bars[0][1]
    return {"nifty": round(last, 2), "open": round(day_open, 2), "or_high": round(hi, 2), "or_low": round(lo, 2),
            "or_mid": round((hi + lo) / 2, 2), "bullish": last > (hi + lo) / 2 and last > day_open,
            "bearish": last < (hi + lo) / 2 and last < day_open}


def record(rec):
    with open(DECISIONS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def run_one(h, cfg, reg, now, log):
    sym = h["symbol"]
    rec = {"time": datetime.now(S.IST).isoformat(), "symbol": "NSE:" + sym, "setup": "orb", "steps": {}, "result": None}
    st = rec["steps"]
    st["1_scanner"] = {k: h.get(k) for k in ("time", "price", "range_high", "range_low", "pct_over", "last",
                                             "vol_x", "vol_x_recent", "gap_pct")}

    def done(result, why):
        rec["result"], rec["why"] = result, why
        st["10_analyst"] = "n/a (gap filter stands in for results days)"
        st["11_pelosi"] = "n/a for India"
        record(rec)
        log("AUTO NSE %s: %s (%s)" % (sym, result, why))
        return rec

    try:
        st["2_news"] = headlines(sym)
    except Exception as e:
        st["2_news"] = "unavailable: %s" % e

    if cfg["regime_filter"]:
        st["regime"] = reg
        if not reg or not reg["bullish"]:
            return done("skipped", "market regime: Nifty is not above its range midpoint and its open" if reg
                        else "market regime unknown (no Nifty data)")
    vx = h.get("vol_x_recent", h.get("vol_x"))
    if vx is not None and vx < cfg["min_vol_x"]:
        return done("skipped", "breakout volume %.2fx the 6 bars before it (min %.2fx)" % (vx, cfg["min_vol_x"]))
    if h.get("gap_pct") is not None and abs(h["gap_pct"]) > cfg["max_gap_pct"]:
        return done("skipped", "opened %+.2f%% vs yesterday (max %.1f%%): likely results/news" % (h["gap_pct"], cfg["max_gap_pct"]))

    try:
        price, _ = P.fetch_price("NSE", sym)
    except Exception as e:
        return done("skipped", "no live price: %s" % e)
    stop = h["range_low"] if cfg["stop"] == "range-low" else (h["range_high"] + h["range_low"]) / 2
    stop = P.round_px("NSE", stop)
    risk = price - stop
    st["3_entry"] = {"price_now": price, "trigger": h["range_high"],
                     "chase_r": round((price - h["range_high"]) / risk, 2) if risk > 0 else None}
    if risk <= 0:
        return done("skipped", "price %s is at/below the stop %s" % (price, stop))
    if price < h["range_high"]:
        return done("skipped", "price %s fell back under the range high %s" % (price, h["range_high"]))
    if (price - h["range_high"]) / risk > cfg["max_chase_r"]:
        return done("skipped", "chasing: %.2fR past the trigger (max %.2fR)" % ((price - h["range_high"]) / risk, cfg["max_chase_r"]))
    stop_pct = risk / price * 100
    target = P.round_px("NSE", price + cfg["target_r"] * risk, down=False)
    pcfg = P.load_config()
    acc = pcfg["accounts"]["INDIA"]
    q_est = max(1, int(min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / price)))
    cost = P.charges(pcfg, "NSE", sym, "buy", q_est * price) + P.charges(pcfg, "NSE", sym, "sell", q_est * target)
    cost_r = cost / (q_est * risk)
    st["4_exit"] = {"entry": price, "stop": stop, "target": target, "stop_pct": round(stop_pct, 2),
                    "charges_r": round(cost_r, 3), "flat_by": acc["flat_by"]}
    if stop_pct < cfg["min_stop_pct"]:
        return done("skipped", "stop too tight: %.2f%% (min %.2f%%)" % (stop_pct, cfg["min_stop_pct"]))

    try:
        d = S.yahoo_chart(sym, "60d", "5m", ".NS")
    except Exception as e:
        return done("skipped", "time machine: no history (%s)" % e)
    if not d:
        return done("skipped", "time machine: no history")
    hist = TM.history(d, "up", cfg["target_r"], 15, cfg["entry_end"], acc["flat_by"], cost_r, before=now.date())
    sim = TM.replay(d, price, stop, target, now, "up", acc["flat_by"], cfg["sim_paths"], None, cost_r)
    st["5_timemachine"] = {"history": hist, "replay": sim}
    if sim is None:
        return done("skipped", "time machine: too little history or no time left")
    if sim["avg_r"] < cfg["min_sim_avg_r"]:
        return done("skipped", "time machine: replays average %+.2fR after charges (min %+.2fR)" % (sim["avg_r"], cfg["min_sim_avg_r"]))
    if hist.get("fired", 0) >= cfg["min_history_trades"] and hist["avg_r"] < cfg["min_history_avg_r"]:
        return done("skipped", "time machine: the rule averaged %+.2fR over %d past sessions (min %+.2fR)"
                    % (hist["avg_r"], hist["fired"], cfg["min_history_avg_r"]))
    if hist.get("fired", 0) < cfg["min_history_trades"]:
        st["5_timemachine"]["note"] = "history too short to judge (%d fires); replays only" % hist.get("fired", 0)

    if not cfg.get("auto_buy", False):
        return done("LOG ONLY", "would paper-buy @ %s, stop %s, target %s; replays %+.2fR (auto_buy is off: "
                    "the backtest found no edge for this rule)" % (price, stop, target, sim["avg_r"]))
    led = P.load_ledger(pcfg)
    args = type("A", (), {"symbol": "NSE:" + sym, "stop": str(stop), "target": str(target), "qty": None, "lots": None,
                          "price": str(price), "note": "auto_nse: orb", "force": False})()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            pos = P.cmd_buy(args, pcfg, led)
        P.save_json(P.LEDGER, led)
    except P.PaperError as e:
        st["6-8_budget_risk_broker"] = "BLOCK: %s" % e
        return done("blocked", str(e))
    st["6-8_budget_risk_broker"] = {"verdict": "PASS, paper buy filled", "report": buf.getvalue().strip().splitlines()}
    st["9_alerts"] = "live.py checks stop %s (breakeven at +%sR) / target %s every cycle; flat by %s" % (
        pos["stop"], acc.get("breakeven_at_r"), pos["target"], acc["flat_by"])
    return done("PAPER BUY", "%d sh @ %s, stop %s, target %s; replays %+.2fR, history %s" % (
        pos["qty"], pos["entry"], pos["stop"], pos["target"], sim["avg_r"],
        ("%d fires %+.2fR" % (hist["fired"], hist["avg_r"])) if hist.get("fired") else "none"))


def process(state, res, log):
    """Called by live.py after an NSE ORB scan (res = scan_nse.orb_scan result with new/first_seen flags)."""
    cfg = load_cfg()
    now = datetime.now(S.IST)
    if not (S.at(now, hm(cfg["entry_start"])) <= now < S.at(now, hm(cfg["entry_end"]))):
        return []
    cutoff = datetime.fromisoformat(res["as_of"])
    cands = []
    for h in res.get("hits", []):
        if not h.get("new") or not h.get("holding"):
            continue
        trig = S.at(now, hm(h["time"]))
        if cutoff - trig > timedelta(minutes=cfg["fresh_minutes"]):
            continue
        cands.append(h)
    if not cands:
        return []
    try:
        reg = regime(now)
    except Exception as e:
        reg = None
        log("NSE regime check failed: %s" % e)
    state.setdefault("markets", {}).setdefault("NSE", {})["regime"] = reg
    cands.sort(key=lambda h: (-(h.get("vol_x_recent") or h.get("vol_x") or 0)))
    out = []
    for h in cands[:cfg["max_new_per_cycle"]]:
        try:
            out.append(run_one(h, cfg, reg, now, log))
        except Exception as e:
            log("AUTO NSE %s failed: %s" % (h["symbol"], e))
    auto = state.setdefault("auto", {"recent": []})
    auto["recent"] = (auto.get("recent", []) + [{"time": r["time"], "symbol": r["symbol"], "result": r["result"],
                                                 "why": r["why"]} for r in out])[-20:]
    return out
