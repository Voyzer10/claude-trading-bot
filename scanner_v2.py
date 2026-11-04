#!/usr/bin/env python3
"""
scanner_v2.py - Scanner v2: watches EVERY market for the owner's setups and hands each one to the agents.

The setups (all from the owner's PDFs):
  abcd_long / abcd_short             the owner's own A-B-C-D entry (abcd.py)
  doji_long, doji_short, star_long,  the SMC Trading Playbook (smc_playbook.py)
  hammer_short
  fvg_long / fvg_short, ob_long /    the rulebook's FVG and order-block first retests (smc_playbook.py)
  ob_short

Each scan, on the candle that just closed, every setup that completes is written to
trader/live/scanner_v2.jsonl (one JSON line: time, market, symbol, setup, side, candle end, price, the stop and
2R level the setup implies, and its A/B/C or sweep details) and the newest 60 go into state["observations"] for the
dashboard, and each one is handed to the agents (agents()): News (crypto headlines), Entry (the candle close),
Exit (stop, 2R, costs in R), Time machine (n/a: backtested instead), Budget (size from the paper account's limits),
Risk (costs and size), then the Broker records it as LOG ONLY instead of trading. The decision lands in
decisions.jsonl with setup "v2:<name>", so the dashboard's Agents section shows how far each one got and its
setup name. Purpose: forward-test the owner's rules on live markets and compare them with his own charts,
without paper trades on rules that failed their backtests.

Markets: CRYPTO (the scanner's 15m/5m candles), NSE (5m, the ORB scan's candles + earlier days fetched once a day),
US (5m, a fixed list of ~95 liquid stocks, fetched by observer itself while the US session is open).
"""
import json
import os
from datetime import datetime, timezone

import abcd as A
import smc_playbook as PB

LIVE_DIR = os.path.join("trader", "live")
OBS_FILE = os.path.join(LIVE_DIR, "scanner_v2.jsonl")
DECISIONS = os.path.join(LIVE_DIR, "decisions.jsonl")
MAX_STATE = 60
_history = {}      # (market, symbol) -> (day_key, [earlier days' rows])
_seen = set()      # (market, symbol, setup, bar_end) already written this run


def rows_of(d, closed_before=None):
    """Yahoo/Coinbase chart dict -> [(t_utc, o, h, l, c, v)] of complete candles (end <= closed_before)."""
    out = []
    for t, o, h, l, c, v in zip(d.get("t", []), d.get("o") or d.get("c", []), d.get("h", []), d.get("l", []),
                                d.get("c", []), d.get("v", [])):
        if None in (o, h, l, c):
            continue
        out.append((datetime.fromtimestamp(t, timezone.utc), o, h, l, c, v or 0))
    out.sort(key=lambda r: r[0])
    if closed_before is not None:
        out = [r for r in out if r[0] < closed_before]
    return out


def _round(x):
    if x is None:
        return None
    ax = abs(x)
    return round(x, 2) if ax >= 100 else round(x, 4) if ax >= 1 else float("%.6g" % x)


def observe(market, symbol, rows, day_of, step_min=5):
    """Setups that complete on the LAST row. rows = (t_utc, o, h, l, c, v), oldest first, closed candles only."""
    if len(rows) < 35:
        return []
    out = []
    i = len(rows) - 1
    bar_end = (rows[i][0].timestamp() + step_min * 60)
    bar_end = datetime.fromtimestamp(bar_end, timezone.utc).isoformat()
    price = rows[i][4]
    ctx = None
    try:
        ctx = PB.Context(rows, day_of)
        found = PB.find_setups(ctx, i) + PB.zone_setups(ctx, i)
    except Exception:
        found = []
    done = set()
    for s in found:
        if s["setup"] in done:
            continue
        if s["setup"] in PB.SETUPS and not s.get("struct_before"):
            continue   # the playbook's order: structure (a BOS/CHoCH before the sweep) comes before the candle
        done.add(s["setup"])
        stop = PB.stop_for(s, 0.1)
        risk = abs(s["entry"] - stop)
        tgt = s["entry"] + 2 * risk if s["side"] == "long" else s["entry"] - 2 * risk
        out.append({"setup": s["setup"], "side": s["side"], "stop": _round(stop), "target_2r": _round(tgt),
                    "details": {"level": s.get("level_name"), "level_px": _round(s.get("level")),
                                "confirmed_on_candle": s.get("confirm_at"), "structure_before": s.get("struct_before"),
                                "body_pct": round(s.get("body_pct") or 0, 3)}})
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
            tgt = s["entry"] + 2 * risk if not short else s["entry"] - 2 * risk
            out.append({"setup": "abcd_short" if short else "abcd_long", "side": s["side"], "stop": _round(stop),
                        "target_2r": _round(tgt),
                        "details": {"A_at": rows[s["a"]][0].isoformat(), "B_level": _round(s["b_level"]),
                                    "C_high": _round(s["c_high"] if not short else s["c_low"]),
                                    "C_low": _round(s["c_low"] if not short else s["c_high"]),
                                    "D_candles_after_C": s["d_offset"], "reclaimed": s["reclaimed"]}})
    for o in out:
        o.update({"market": market, "symbol": symbol, "bar_end": bar_end, "price": _round(price)})
    return out


def _grid(rows, step_min=5):
    """Drop the live tick off the candle grid."""
    return [r for r in rows if not r[0].minute % step_min and not r[0].second]


def earlier_days(market, symbols, today_key, day_of, fetch_many_5d):
    """Earlier days' candles for each symbol, fetched ONCE a day in one parallel batch (fetch_many_5d(symbols) ->
    {sym: chart}). Returns {sym: [rows before today]}."""
    need = [s for s in symbols if (_history.get((market, s)) or (None,))[0] != today_key]
    if need:
        try:
            got = fetch_many_5d(need) or {}
        except Exception:
            got = {}
        for s in need:
            rows = _grid(rows_of(got.get(s) or {}))
            _history[(market, s)] = (today_key, [r for r in rows if day_of(r[0]) != today_key])
    return {s: (_history.get((market, s)) or (None, []))[1] for s in symbols}



NAMES = {"abcd_long": "A-B-C-D long", "abcd_short": "A-B-C-D short", "doji_long": "playbook doji long",
         "doji_short": "playbook doji short", "star_long": "playbook bottom star", "hammer_short": "playbook top hammer",
         "fvg_long": "FVG retest long", "fvg_short": "FVG retest short", "ob_long": "order block long",
         "ob_short": "order block short"}
_ACC = {"CRYPTO": "CRYPTO", "NSE": "INDIA", "BSE": "INDIA", "US": "US"}


def agents(o):
    """Run one Scanner v2 setup through the agents (no broker). Returns the decision record."""
    import paper as P
    from datetime import timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    m, sym, name = o["market"], o["symbol"], NAMES.get(o["setup"], o["setup"])
    rec = {"time": datetime.now(ist).isoformat(), "symbol": "%s:%s" % (m, sym), "setup": "v2:" + o["setup"],
           "scanner": "v2", "steps": {}, "result": None}
    st = rec["steps"]
    st["1_scanner"] = {"scanner": "v2", "setup": o["setup"], "setup_name": name, "side": o["side"],
                       "bar_end": o["bar_end"], "price": o["price"], **(o.get("details") or {})}

    def done(result, why):
        rec["result"], rec["why"] = result, why
        st["10_analyst"] = "n/a"
        st["11_pelosi"] = "n/a"
        return rec

    if m == "CRYPTO":
        try:
            import auto_crypto
            st["2_news"] = auto_crypto.headlines(sym)
        except Exception as e:
            st["2_news"] = "unavailable: %s" % e
    else:
        st["2_news"] = "not fetched for Scanner v2 records (hundreds a day on stocks)"
    entry, stop, target = o["price"], o.get("stop"), o.get("target_2r")
    short = o["side"] == "short"
    st["3_entry"] = {"side": o["side"], "price_now": entry, "note": "entry = the close of the candle that completed the setup"}
    risk = (stop - entry) if short else (entry - stop) if stop is not None else 0
    if not stop or risk <= 0:
        return done("skipped", "price %s is already past the stop %s" % (entry, stop))
    try:
        cfg = P.load_config()
        acc = cfg["accounts"][_ACC.get(m, "US")]
    except Exception as e:
        return done("skipped", "paper config unavailable: %s" % e)
    units = min(acc["max_loss_per_trade"] / risk, acc["capital"] * acc["max_position_pct"] / 100 / entry)
    qty = units if m == "CRYPTO" else int(units)
    if m in ("NSE", "BSE"):
        if qty >= 1:
            o_, c_ = ("sell", "buy") if short else ("buy", "sell")
            cost = (P.charges(cfg, "NSE", sym, o_, qty * entry) + P.charges(cfg, "NSE", sym, c_, qty * target)) / (qty * risk)
        else:
            cost = None
    else:
        cost = (entry + target) * float(acc.get("fee_pct", 0) or 0) / 100 / risk
    st["4_exit"] = {"entry": entry, "stop": stop, "target": target, "r_multiple": 2.0,
                    "stop_pct": round(risk / entry * 100, 3), "fee_r": round(cost, 3) if cost is not None else None}
    st["5_timemachine"] = "n/a for Scanner v2 (these setups are backtested instead: research_smcp / research_abcd)"
    if qty <= 0 or (m != "CRYPTO" and qty < 1):
        return done("skipped", "0 units fit: the stop is %s away and the max loss is %s" % (round(risk, 6), acc["max_loss_per_trade"]))
    if cost is not None and cost > 0.25:
        return done("skipped", "fees eat %.2fR of the trade (max 0.25R)" % cost)
    st["6-8_budget_risk_broker"] = {"verdict": "pass, NOT sent to the broker", "qty": round(qty, 6) if m == "CRYPTO" else qty,
                                    "entry": entry, "stop": stop, "target": target,
                                    "max_loss": round(risk * qty, 2)}
    st["9_alerts"] = "no trade, nothing to watch"
    return done("LOG ONLY", "Scanner v2 %s: passed the agents; the broker records it only (this rule failed its backtest)" % name)

def record(state, found, log=None):
    """Append new observations to observations.jsonl and the newest to state["observations"]."""
    now = datetime.now(timezone.utc).isoformat()
    fresh = []
    for o in found:
        k = (o["market"], o["symbol"], o["setup"], o["bar_end"])
        if k in _seen:
            continue
        _seen.add(k)
        fresh.append(dict(o, time=now))
    if len(_seen) > 50000:
        _seen.clear()
    if not fresh:
        return []
    os.makedirs(LIVE_DIR, exist_ok=True)
    with open(OBS_FILE, "a", encoding="utf-8") as fh:
        for o in fresh:
            fh.write(json.dumps(o) + "\n")
    with open(DECISIONS, "a", encoding="utf-8") as fh:   # hand each setup to the agents
        for o in fresh:
            try:
                rec = agents(o)
            except Exception as e:
                rec = {"time": o["time"], "symbol": "%s:%s" % (o["market"], o["symbol"]), "setup": "v2:" + o["setup"],
                       "scanner": "v2", "steps": {"1_scanner": o}, "result": "skipped", "why": "agents failed: %s" % e}
            o["agents"] = "%s: %s" % (rec.get("result"), rec.get("why"))
            fh.write(json.dumps(rec) + "\n")
    obs = state.setdefault("scanner_v2", [])
    obs.extend(fresh)
    del obs[:-MAX_STATE]
    if log:
        by = {}
        for o in fresh:
            by.setdefault(o["market"], []).append("%s %s" % (o["symbol"], o["setup"]))
        for m, items in by.items():
            log("SCANNER v2 %s: %s%s" % (m, ", ".join(items[:12]), " ..." if len(items) > 12 else ""))
    return fresh


# ------------------------------------------------------------------ per-market entry points (called by live.py)

def crypto(state, data, step_min, cutoff, log=None):
    found = []
    for sym, d in (data or {}).items():
        rows = rows_of(d)
        rows = [r for r in rows if not r[0].minute % step_min and r[0].timestamp() + step_min * 60 <= cutoff.timestamp()]
        found += observe("CRYPTO", sym, rows, lambda t: t.date(), step_min)
    return record(state, found, log)


def nse(state, market, data, cutoff, suffix, fetch_many, ist, workers=8, log=None):
    """data = the ORB scan's 1-day 5m charts (cutoff = end of the last complete candle); earlier days come from one
    5-day fetch per symbol per day."""
    from datetime import timedelta
    today = cutoff.astimezone(ist).date()
    day_of = lambda t: t.astimezone(ist).date()
    data = data or {}
    hist = earlier_days(market, list(data), today, day_of,
                        lambda syms: fetch_many(syms, "5d", "5m", workers, suffix, True)[0])
    found = []
    for sym, d in data.items():
        rows = _grid(rows_of(d, closed_before=cutoff - timedelta(minutes=5) + timedelta(seconds=1)))
        rows = hist.get(sym, []) + [r for r in rows if day_of(r[0]) == today]
        found += observe(market, sym, rows, day_of, 5)
    return record(state, found, log)


US_STATE = {"last_bar": None}
US_WATCH = ("AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO JPM V MA UNH HD PG COST JNJ XOM CVX ABBV MRK PEP KO WMT BAC "
            "WFC CSCO ORCL CRM ADBE AMD INTC QCOM TXN AMAT MU NFLX DIS NKE MCD SBUX MAR HLT BKNG ABNB UBER LYFT "
            "CAT DE BA GE HON LMT RTX UPS FDX GS MS C AXP BLK SCHW PYPL SQ SHOP COIN PLTR SNOW CRWD PANW NOW "
            "INTU ISRG LLY PFE TMO DHR AMGN GILD CVS CI T VZ TMUS CMCSA CHTR SPGI ICE CME MMM DOW LIN F GM RIVN "
            "SPY QQQ").split()


def us(state, symbols, fetch_many, log=None):
    """While the US session is open: on each new 5m candle, fetch today's candles for `symbols`, join the earlier
    days (once a day) and observe."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    now = datetime.now(timezone.utc)
    lt = now.astimezone(et)
    if lt.weekday() >= 5 or not ((9, 35) <= (lt.hour, lt.minute) < (16, 5)):
        return []
    last = (now - timedelta(minutes=1)).replace(second=0, microsecond=0)
    last = last - timedelta(minutes=last.minute % 5)          # end of the last closed 5m candle
    if US_STATE["last_bar"] == last.isoformat():
        return []
    US_STATE["last_bar"] = last.isoformat()
    today = lt.date()
    day_of = lambda t: t.astimezone(et).date()
    session = lambda rows: [r for r in rows if (9, 30) <= (r[0].astimezone(et).hour, r[0].astimezone(et).minute) < (16, 0)]
    hist = earlier_days("US", symbols, today, day_of, lambda syms: fetch_many(syms, "5d", "5m", 8, "", True)[0])
    data, _ = fetch_many(symbols, "1d", "5m", 8, "", True)
    found = []
    for sym, d in data.items():
        rows = session(_grid(rows_of(d, closed_before=last - timedelta(minutes=5) + timedelta(seconds=1))))
        rows = session(hist.get(sym, [])) + [r for r in rows if day_of(r[0]) == today]
        found += observe("US", sym, rows, day_of, 5)
    return record(state, found, log)
