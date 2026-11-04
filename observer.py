#!/usr/bin/env python3
"""
observer.py - watches EVERY market for the owner's setups and RECORDS them. It never trades.

The setups (all from the owner's PDFs):
  abcd_long / abcd_short             the owner's own A-B-C-D entry (abcd.py)
  doji_long, doji_short, star_long,  the SMC Trading Playbook (smc_playbook.py)
  hammer_short
  fvg_long / fvg_short, ob_long /    the rulebook's FVG and order-block first retests (smc_playbook.py)
  ob_short

Each scan, on the candle that just closed, every setup that completes is written to
trader/live/observations.jsonl (one JSON line: time, market, symbol, setup, side, candle end, price, the stop and
2R level the setup implies, and its A/B/C or sweep details) and the newest 60 go into state["observations"] for the
dashboard. Purpose: forward-test the owner's rules on live markets and compare them with what he sees on his own
charts, without risking paper money on rules that failed their backtests.

Markets: CRYPTO (the scanner's 15m/5m candles), NSE (5m, the ORB scan's candles + earlier days fetched once a day),
US (5m, a fixed list of ~95 liquid stocks, fetched by observer itself while the US session is open).
"""
import json
import os
from datetime import datetime, timezone

import abcd as A
import smc_playbook as PB

LIVE_DIR = os.path.join("trader", "live")
OBS_FILE = os.path.join(LIVE_DIR, "observations.jsonl")
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
    obs = state.setdefault("observations", [])
    obs.extend(fresh)
    del obs[:-MAX_STATE]
    if log:
        by = {}
        for o in fresh:
            by.setdefault(o["market"], []).append("%s %s" % (o["symbol"], o["setup"]))
        for m, items in by.items():
            log("OBSERVE %s (no trade): %s%s" % (m, ", ".join(items[:12]), " ..." if len(items) > 12 else ""))
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
