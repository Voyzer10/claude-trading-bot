#!/usr/bin/env python3
"""
auto_fno.py - Nifty 50 / Bank Nifty opening-range breakouts traded with F&O, PAPER only
(paper.py's INDIA account; nothing reaches a broker). With the INDIA account on Scanner v4 (owner, 12 Nov 2026):
Scanner v4 on Bank Nifty's own 5-minute chart instead, each setup bought as the ATM option (v4_process).

live.py --markets ...,FNO --auto-paper calls process() every cycle during the NSE session.
For each index, on the first 5-minute close beyond its 9:15-9:30 range:

  breakout UP    -> buy the ATM call (CE); also try the index future (long)
  breakdown DOWN -> buy the ATM put (PE)   (short futures are not supported in paper.py)

Agents, in order (every verdict lands in trader/live/decisions.jsonl):
  1 scanner      the index's opening-range break (fno.yahoo_bars)
  2 news         index-level headlines are not fetched (n/a): macro news is in the regime itself
  3 entry        live index level; skips a chase or a break that has already reversed
  4 exit         index stop at the range midpoint, index target N x the risk, flat by 15:15;
                 option stop/target = premium -/+ |delta| x the index move (model delta)
  5 timemachine  tm_india on the index's own last 60 days (history + replays), minus a theta
                 haircut for option buyers; both must clear their minimum
  6 budget  \\
  7 risk     >   paper.py buy NFO:... (lot sizes, futures margin, F&O max loss, position cap, charges)
  8 broker  /
  9 alerts       live.py's paper check: premium stop, breakeven at +1R, target, flat by 15:15
 10-11           n/a for index F&O

Prices: fno.py (NSE option chain if it answers, else a Black-Scholes model from India VIX: an
estimate, not a market quote). Rules: trader/live/auto_fno_config.json.
"""
import contextlib
import io
import json
import os
from datetime import datetime, timedelta, timezone

import fno as F
import paper as P
import tm_india as TM

LIVE_DIR = os.path.join("trader", "live")
CFG_FILE = os.path.join(LIVE_DIR, "auto_fno_config.json")
DECISIONS = os.path.join(LIVE_DIR, "decisions.jsonl")
IST = F.IST

DEFAULTS = {
    "_note": "Auto PAPER trading rules for Nifty / Bank Nifty F&O (INDIA account). Paper money only.",
    "indices": ["NIFTY", "BANKNIFTY"],
    "instruments": ["options", "futures"],
    "entry_start": "09:35",
    "entry_end": "13:00",
    "fresh_minutes": 10,
    "target_r": 2.0,
    "max_chase_r": 0.5,
    "min_days_to_expiry": 1,      # never buy an option on its expiry day: roll to the next expiry
    "theta_haircut_r": 0.15,      # option buyers lose time value: subtract this from the index edge
    "min_history_trades": 10,
    "min_history_avg_r": 0.10,
    "min_sim_avg_r": 0.05,
    "sim_paths": 2000,
    "auto_buy": False,            # research.py fno (31 Oct 2026): 6 of 264 combinations positive both halves, all
                                  # marginal (+0.01..+0.05R in-sample); no edge distinguishable from zero: log only
    # Scanner v4 on the index chart (owner, 12 Nov 2026: F&O only on Bank Nifty); backtest: research.py bnf-sv4
    "v4_indices": ["BANKNIFTY"],
    "v4_entry_start": "09:20",
    "v4_entry_end": "15:00",
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


def at(day, s):
    h, m = hm(s)
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def record(rec):
    with open(DECISIONS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def orb_break(d, now):
    """Today's 15-minute range and the first completed 5-minute close beyond it (up or down)."""
    bars = []
    for t, o, h, l, c in zip(d["t"], d["o"], d["h"], d["l"], d["c"]):
        st = datetime.fromtimestamp(t, IST)
        if st.date() != now.date() or st.minute % 5 or st.second:
            continue
        if st + timedelta(minutes=5) > now:
            continue  # still forming
        bars.append((st, o, h, l, c))
    o_start = at(now, "09:15")
    rng = [b for b in bars if o_start <= b[0] < o_start + timedelta(minutes=15)]
    if len(rng) < 3:
        return None
    hi, lo = max(b[2] for b in rng), min(b[3] for b in rng)
    for b in bars:
        if b[0] < o_start + timedelta(minutes=15):
            continue
        if b[4] > hi:
            return {"direction": "up", "level": hi, "or_high": hi, "or_low": lo, "close": b[4],
                    "time": (b[0] + timedelta(minutes=5)).strftime("%H:%M")}
        if b[4] < lo:
            return {"direction": "down", "level": lo, "or_high": hi, "or_low": lo, "close": b[4],
                    "time": (b[0] + timedelta(minutes=5)).strftime("%H:%M")}
    return {"direction": None, "or_high": hi, "or_low": lo}


def buy(pcfg, symbol, stop, target, price, note):
    led = P.load_ledger(pcfg)
    args = type("A", (), {"symbol": symbol, "stop": str(stop), "target": str(target), "qty": None, "lots": None,
                          "price": str(price), "note": note, "force": False})()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pos = P.cmd_buy(args, pcfg, led)
    P.save_json(P.LEDGER, led)
    return pos, buf.getvalue().strip().splitlines()


def run_one(idx, brk, cfg, now, log):
    direction = brk["direction"]
    rec = {"time": datetime.now(IST).isoformat(), "symbol": "FNO:%s" % idx, "setup": "index orb %s" % direction,
           "steps": {}, "result": None}
    st = rec["steps"]
    st["1_scanner"] = brk
    st["2_news"] = "n/a (index)"

    def done(result, why):
        rec["result"], rec["why"] = result, why
        st["10-11"] = "n/a for index F&O"
        record(rec)
        log("AUTO FNO %s %s: %s (%s)" % (idx, direction, result, why))
        return rec

    spot, _, _ = F.yahoo_last(F.FNO[idx]["yahoo"])
    mid = (brk["or_high"] + brk["or_low"]) / 2
    risk = (spot - mid) if direction == "up" else (mid - spot)
    beyond = (spot - brk["level"]) if direction == "up" else (brk["level"] - spot)
    st["3_entry"] = {"index_now": spot, "level": brk["level"], "chase_r": round(beyond / risk, 2) if risk > 0 else None}
    if risk <= 0 or beyond < 0:
        return done("skipped", "the break reversed: index %.2f is back inside the range" % spot)
    if beyond / risk > cfg["max_chase_r"]:
        return done("skipped", "chasing: index is %.2fR past the level (max %.2fR)" % (beyond / risk, cfg["max_chase_r"]))
    reward = cfg["target_r"] * risk
    st["4_exit"] = {"index_entry": spot, "index_stop": round(mid, 2),
                    "index_target": round(spot + reward if direction == "up" else spot - reward, 2), "flat_by": "15:15"}

    d = F.yahoo_bars(F.FNO[idx]["yahoo"], "60d", "5m")
    hist = TM.history(d, direction, cfg["target_r"], 15, cfg["entry_end"], "15:15", cfg["theta_haircut_r"],
                      before=now.date())
    sim = TM.replay(d, spot, mid, spot + reward if direction == "up" else spot - reward, now, direction, "15:15",
                    cfg["sim_paths"], None, cfg["theta_haircut_r"])
    st["5_timemachine"] = {"history": hist, "replay": sim, "theta_haircut_r": cfg["theta_haircut_r"]}
    if sim is None:
        return done("skipped", "time machine: no history or no time left")
    if sim["avg_r"] < cfg["min_sim_avg_r"]:
        return done("skipped", "time machine: replays average %+.2fR after the theta haircut (min %+.2fR)"
                    % (sim["avg_r"], cfg["min_sim_avg_r"]))
    if hist.get("fired", 0) >= cfg["min_history_trades"] and hist["avg_r"] < cfg["min_history_avg_r"]:
        return done("skipped", "time machine: the %s rule averaged %+.2fR over %d past sessions (min %+.2fR)"
                    % (direction, hist["avg_r"], hist["fired"], cfg["min_history_avg_r"]))

    if not cfg.get("auto_buy", False):
        return done("LOG ONLY", "would buy the ATM %s; index replays %+.2fR, history %s (auto_buy is off: the "
                    "backtest found no reliable edge)" % ("CE" if direction == "up" else "PE", sim["avg_r"],
                    ("%d fires %+.2fR" % (hist["fired"], hist["avg_r"])) if hist.get("fired") else "none"))
    pcfg = P.load_config()
    legs, bought = {}, []
    if "options" in cfg["instruments"]:
        kind = "CE" if direction == "up" else "PE"
        exp = F.next_expiry(idx, now.date(), cfg["min_days_to_expiry"])
        name = F.make_option(idx, exp, F.atm_strike(idx, spot), kind)
        try:
            prem, _, src, extra = F.quote(name, now.astimezone(timezone.utc))
            dlt = abs(extra.get("delta") or F.delta(name, now.astimezone(timezone.utc)))
            p_stop = P.round_px("NFO", prem - dlt * risk)
            p_tgt = P.round_px("NFO", prem + dlt * reward, down=False)
            if p_stop <= 0:
                raise P.PaperError("premium stop would be <= 0 (premium %.2f, delta %.2f)" % (prem, dlt))
            pos, report = buy(pcfg, "NFO:" + name, p_stop, p_tgt, prem, "auto_fno: %s %s" % (idx, direction))
            legs["option"] = {"instrument": name, "premium": prem, "source": src, "delta": round(dlt, 3),
                              "stop": pos["stop"], "target": pos["target"], "lots": pos.get("lots"), "report": report}
            bought.append("%s x%d lot @ %.2f (%s)" % (name, pos.get("lots", 0), prem, src.split(" ")[0]))
        except (P.PaperError, F.FnoError) as e:
            legs["option"] = {"instrument": name, "BLOCK": str(e)}
    if "futures" in cfg["instruments"]:
        if direction == "down":
            legs["future"] = "skipped: short futures are not supported in paper.py (the put covers the bearish view)"
        else:
            fname = F.make_future(idx, F.futures_expiry(idx, now.date()))
            try:
                fpx, _, src, _ = F.quote(fname, now.astimezone(timezone.utc))
                pos, report = buy(pcfg, "NFO:" + fname, P.round_px("NFO", fpx - risk),
                                  P.round_px("NFO", fpx + reward, down=False), fpx, "auto_fno: %s up" % idx)
                legs["future"] = {"instrument": fname, "price": fpx, "lots": pos.get("lots"), "report": report}
                bought.append("%s x%d lot @ %.2f" % (fname, pos.get("lots", 0), fpx))
            except (P.PaperError, F.FnoError) as e:
                legs["future"] = {"instrument": fname, "BLOCK": str(e)}
    st["6-8_budget_risk_broker"] = legs
    st["9_alerts"] = "live.py checks premium stop/target, breakeven and the 15:15 flat-by every cycle"
    if bought:
        return done("PAPER BUY", "; ".join(bought) + "; index replays %+.2fR, history %s" % (
            sim["avg_r"], ("%d fires %+.2fR" % (hist["fired"], hist["avg_r"])) if hist.get("fired") else "none"))
    why = "; ".join("%s: %s" % (k, v["BLOCK"] if isinstance(v, dict) and "BLOCK" in v else v) for k, v in legs.items())
    return done("blocked", why or "no instrument enabled")


def index_rows(idx, now):
    """The index's completed 5-minute candles of the last 5 days: [(utc start, o, h, l, c, volume)]."""
    d = F.yahoo_bars(F.FNO[idx]["yahoo"], "5d", "5m")
    rows = []
    for t, o, h, l, c, v in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d.get("v") or [0] * len(d["t"])):
        st = datetime.fromtimestamp(t, timezone.utc)
        if st + timedelta(minutes=5) <= now.astimezone(timezone.utc):
            rows.append((st, o, h, l, c, v or 0))
    return rows


def v4_process(cfg, now, ms, log):
    """INDIA on Scanner v4: v4 on the index's own 5-minute chart; a setup buys the index's ATM option through
    paper.setup_decision (the same gates as every v4 trade: one at a time per chart, fresh signal, F&O list)."""
    import smc_playbook as PB
    out = []
    ms["status"] = "Scanner v4 on %s (5-minute chart, ATM options)" % ", ".join(cfg["v4_indices"])
    if now.weekday() >= 5 or not (at(now, cfg["v4_entry_start"]) <= now < at(now, cfg["v4_entry_end"])):
        return out
    seen = ms.setdefault("v4_seen", {})
    for idx in cfg["v4_indices"]:
        try:
            rows = index_rows(idx, now)
        except Exception as e:
            log("FNO %s data failed: %s" % (idx, e))
            continue
        if len(rows) < 40:
            continue
        last = rows[-1][0].isoformat()
        if seen.get(idx) == last:
            continue                    # this candle was read already
        seen[idx] = last
        led = P.load_ledger(P.load_config())
        try:
            setups = PB.owner_setups(rows, lambda x: x.astimezone(IST).date(), version="v4", market="NSE",
                                     symbol=idx, ledger=led, intraday=True)
        except Exception as e:
            log("AUTO FNO %s v4 scan failed: %s" % (idx, e))
            continue
        for s in setups:
            rec = P.setup_decision("NSE", idx, s)
            record(rec)
            log("AUTO FNO %s v4 %s: %s (%s)" % (idx, s.get("name") or s["setup"], rec["result"], rec.get("why")))
            out.append(rec)
    return out


def process(state, log):
    cfg = load_cfg()
    now = datetime.now(IST)
    ms = state.setdefault("markets", {}).setdefault("FNO", {})
    import smc_playbook as PB
    own = PB.v4_only("NFO")
    if own == "v4":  # owner, 12 Nov 2026: v4 trades F&O only on Bank Nifty's own chart
        out = v4_process(cfg, now, ms, log)
        auto = state.setdefault("auto", {"recent": []})
        auto["recent"] = (auto.get("recent", []) + [{"time": r["time"], "symbol": r["symbol"], "result": r["result"],
                                                     "why": r.get("why")} for r in out])[-20:]
        return out
    if own:          # INDIA on another Scanner version: no index opening-range breakout trades
        ms["status"] = "Scanner %s only: the index opening-range breakout rules are off" % own
        if ms.get("v4_note") != now.date().isoformat():
            ms["v4_note"] = now.date().isoformat()
            log("AUTO FNO: Scanner %s only: Nifty / Bank Nifty opening-range breakouts are off today" % own)
        return []
    if now.weekday() >= 5 or not (at(now, cfg["entry_start"]) <= now < at(now, cfg["entry_end"])):
        ms["status"] = "outside the F&O entry window (%s-%s IST)" % (cfg["entry_start"], cfg["entry_end"])
        return []
    today = now.date().isoformat()
    done_today = ms.get("done") if ms.get("date") == today else {}
    out = []
    for idx in cfg["indices"]:
        try:
            d = F.yahoo_bars(F.FNO[idx]["yahoo"], "1d", "5m")
            brk = orb_break(d, now)
        except Exception as e:
            log("FNO %s data failed: %s" % (idx, e))
            continue
        ms[idx] = brk
        if not brk or not brk.get("direction"):
            continue
        k = "%s/%s" % (idx, brk["direction"])
        if k in done_today:
            continue
        if now - at(now, brk["time"]) > timedelta(minutes=cfg["fresh_minutes"]):
            done_today[k] = "stale at %s" % now.strftime("%H:%M")
            log("FNO %s %s break at %s is older than %d min: not traded" % (idx, brk["direction"], brk["time"], cfg["fresh_minutes"]))
            continue
        done_today[k] = brk["time"]
        try:
            out.append(run_one(idx, brk, cfg, now, log))
        except Exception as e:
            log("AUTO FNO %s failed: %s" % (idx, e))
    ms["done"], ms["date"] = done_today, today
    auto = state.setdefault("auto", {"recent": []})
    auto["recent"] = (auto.get("recent", []) + [{"time": r["time"], "symbol": r["symbol"], "result": r["result"],
                                                 "why": r["why"]} for r in out])[-20:]
    return out
