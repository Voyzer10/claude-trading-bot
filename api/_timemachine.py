"""
api/_timemachine.py - the time machine's runs, for the dashboard (owner, 14 Nov 2026: "time machine k logs dekhne
h ... kb aur kese kaam karta visualize ho jae").

  GET /api/py/timemachine?limit=200
      {"runs": [{time, symbol, setup, side, result, why, entry, stop, target, engine, gate, p_target, p_stop,
                 p_neither, avg_r, paths, bars, hist_trades, hist_win, hist_avg_r, hist_days, verdict}],
       "counts": {engine: n}, "last_run": time, "scanned": n}

Every decision record (trader/live/decisions.jsonl) keeps its step 5. Four kinds of time machine wrote it:
  v4        timemachine_v4.py (14 Nov on): info only, never blocks a v4 trade
  us-pack   the US pack's trader-timemachine (ORB longs): a gate, skips a negative edge
  india     tm_india (NSE / F&O breakouts): a gate
  crypto    auto_crypto's replays (crypto rules longs): a gate
They are normalised to one shape here; anything else stays in "raw".
"""
import json
import os
from collections import Counter

from fastapi import APIRouter

router = APIRouter()
DECISIONS = os.path.join("trader", "live", "decisions.jsonl")   # relative, like paper.py (the API runs in /opt/trader)


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def normalise(tm):
    """One step-5 dict -> the common fields (None where that engine did not report it)."""
    out = {"engine": "other", "gate": None, "p_target": None, "p_stop": None, "p_neither": None, "avg_r": None,
           "paths": None, "bars": None, "hist_trades": None, "hist_win": None, "hist_avg_r": None, "hist_days": None,
           "verdict": tm.get("verdict") if isinstance(tm.get("verdict"), str) else None}
    if isinstance(tm.get("replay"), dict) and "gate" in tm:                  # v4 (timemachine_v4.py)
        r, h = tm.get("replay") or {}, tm.get("history") or {}
        out.update(engine="v4", gate="info only", p_target=r.get("p_target"), p_stop=r.get("p_stop"),
                   p_neither=r.get("p_neither"), avg_r=r.get("avg_r"), paths=r.get("paths"), bars=r.get("bars"),
                   hist_trades=h.get("trades"), hist_win=h.get("win_rate"), hist_avg_r=h.get("avg_r"), hist_days=h.get("days"))
    elif "p_target" in tm and "avg_R" in tm:                                 # the US pack
        out.update(engine="us-pack", gate="gate", p_target=tm.get("p_target"), p_stop=tm.get("p_stop"),
                   p_neither=tm.get("p_neither"), avg_r=tm.get("avg_R"), hist_trades=tm.get("history_triggered"),
                   hist_avg_r=tm.get("history_avg_R"))
    elif "replay" in tm or ("history" in tm and "sim" not in tm):           # tm_india
        r, h = tm.get("replay") or {}, tm.get("history") or {}
        out.update(engine="india", gate="gate", p_target=r.get("target_first"), p_stop=r.get("stop_first"),
                   p_neither=r.get("neither"), avg_r=r.get("avg_r"), paths=r.get("paths"), bars=r.get("bars_left"),
                   hist_trades=h.get("fired") if isinstance(h, dict) else None,
                   hist_avg_r=(h.get("avg_r") if isinstance(h, dict) else None),
                   hist_win=(h.get("win_rate") if isinstance(h, dict) else None))
    elif "sim" in tm:                                                        # crypto rules
        r, h = tm.get("sim") or {}, tm.get("history") or {}
        out.update(engine="crypto", gate="gate", p_target=r.get("target_first"), p_stop=r.get("stop_first"),
                   p_neither=r.get("neither"), avg_r=r.get("avg_r"), paths=r.get("paths"), bars=r.get("bars"),
                   hist_trades=(h.get("fired") or h.get("trades")) if isinstance(h, dict) else None,
                   hist_avg_r=h.get("avg_r") if isinstance(h, dict) else None)
    for k in ("p_target", "p_stop", "p_neither", "avg_r", "hist_win", "hist_avg_r"):
        out[k] = _f(out[k])
    return out


def runs(limit=200, path=None):
    path = path or DECISIONS
    out, counts, scanned = [], Counter(), 0
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        lines = []
    for ln in reversed(lines):
        scanned += 1
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        st = (r.get("steps") or {}) if isinstance(r, dict) else {}
        tm = st.get("5_timemachine")
        if not isinstance(tm, dict):
            continue
        n = normalise(tm)
        counts[n["engine"]] += 1
        if len(out) >= limit:
            continue
        sc, ex = st.get("1_scanner") or {}, st.get("4_exit") or {}
        out.append(dict(n, time=r.get("time"), symbol=r.get("symbol"), setup=sc.get("setup_name") or r.get("setup"),
                        side=sc.get("side"), result=r.get("result"), why=r.get("why"),
                        entry=ex.get("entry", ex.get("stock_entry")), stop=ex.get("stop", ex.get("stock_stop")),
                        target=ex.get("target", ex.get("stock_target"))))
    return {"runs": out, "counts": dict(counts), "last_run": out[0]["time"] if out else None, "scanned": scanned}


@router.get("/api/py/timemachine")
def timemachine(limit: int = 200):
    return runs(max(1, min(int(limit), 1000)))


# ---------------------------------------------------------------------------------------------- one run on a chart

def _day_fn(market):
    from datetime import timezone as _tz
    from zoneinfo import ZoneInfo
    if market == "CRYPTO":
        return (lambda t: t.astimezone(_tz.utc).date()), False
    zone = ZoneInfo("America/New_York") if market == "US" else ZoneInfo("Asia/Kolkata")
    return (lambda t: t.astimezone(zone).date()), True


def _history_rows(market, sym, upto):
    """60 days of 5-minute candles of the chart, only those that had CLOSED by `upto` (no look-ahead)."""
    from datetime import datetime, timezone as _tz
    import scan_nse as S
    try:
        from api._chart import INDEX_YAHOO
    except ImportError:
        from _chart import INDEX_YAHOO
    if market == "CRYPTO":
        import scan_crypto as C
        d = C.crypto_chart(sym, "60d", "5m")
    elif market == "INDEX":
        d = S.yahoo_chart(INDEX_YAHOO.get(sym, sym), "60d", "5m", "")
    else:
        d = S.yahoo_chart(sym, "60d", "5m", ".NS" if market == "NSE" else ".BO" if market == "BSE" else "")
    if not d or not d.get("t"):
        return []
    rows = [(datetime.fromtimestamp(int(t), _tz.utc), o, h, l, c) for t, o, h, l, c in
            zip(d["t"], d["o"], d["h"], d["l"], d["c"]) if None not in (o, h, l, c)]
    return [r for r in rows if r[0].timestamp() + 300 <= upto]


ENGINE_WORDS = {"v4": "Scanner v4's time machine: information only, it never blocks a v4 trade",
                "us-pack": "the US ORB time machine: a gate, a negative edge skipped the trade",
                "india": "the India breakout time machine: a gate, a negative edge skipped the trade",
                "crypto": "the crypto rules' time machine: a gate, a negative edge skipped the trade",
                "other": "an older time machine"}


@router.get("/api/py/chart/timemachine")
def chart_timemachine(time: str, symbol: str, show: int = 60):
    """One time machine run on its chart: the real candles, the levels, and `show` of the replayed paths drawn from
    the decision candle on, redrawn with the same method (and the run's seed, when it saved one) on the chart's own
    candles up to that moment."""
    from datetime import datetime, timezone as _tz
    from fastapi import HTTPException
    try:
        from api import _chart as CH
    except ImportError:
        import _chart as CH
    import timemachine_v4 as TM
    rec = next((r for r in reversed(CH._decisions()) if r.get("time") == time and r.get("symbol") == symbol), None)
    if not rec:
        raise HTTPException(404, "no decision %s at %s" % (symbol, time))
    st = rec.get("steps") or {}
    tm = st.get("5_timemachine")
    if not isinstance(tm, dict):
        raise HTTPException(404, "the time machine did not run for this decision")
    n = normalise(tm)
    sc, ex = st.get("1_scanner") or {}, st.get("4_exit") or {}
    side = sc.get("side") or "long"
    entry = _f(ex.get("stock_entry", ex.get("entry")))
    stop = _f(ex.get("stock_stop", ex.get("stop")))
    target = _f(ex.get("stock_target", ex.get("target")))
    if entry is None:
        entry = _f(sc.get("price"))
    if entry is None or stop is None or entry == stop:
        raise HTTPException(422, "no entry / stop recorded for this decision")
    entry, stop = float("%.6g" % entry), float("%.6g" % stop)
    target = float("%.6g" % target) if target is not None else None
    market, sym = symbol.split(":", 1) if ":" in symbol else ("US", symbol)
    m2, s2, chart, _box = CH.chart_of({"key": symbol, "market": market, "symbol": sym})
    bar = CH._ts(sc.get("bar_end")) or CH._ts(rec["time"])
    try:
        hist = _history_rows(m2, s2, bar + 300)
        cs = CH.candles(m2, s2, datetime.fromtimestamp(bar, _tz.utc))
    except Exception as e:
        raise HTTPException(502, "candles for %s: %s" % (chart, str(e)[:200]))
    day_of, intraday = _day_fn(market if m2 != "INDEX" else "NSE")
    show = max(0, min(int(show), 200))
    redraw, bars = None, None
    if len(hist) >= 50:
        bars = n["bars"] or TM.bars_left(hist, day_of, intraday)
        seed = tm.get("seed")
        if seed is None:      # an older run saved no seed: a fixed one per run, so the chart is the same every time
            import zlib
            seed = zlib.crc32(("%s|%s" % (symbol, time)).encode())
        redraw = TM.replay(hist, side, entry, stop, target, int(bars), TM.PATHS, seed, keep=show)
    start = (hist[-1][0].timestamp() if hist else bar) + 300     # the replays start after the last closed candle
    marks, _ = CH.setup_markers(rec)
    marks.append({"t": bar, "kind": "entry" if str(rec.get("result", "")).startswith("PAPER") else "skip",
                  "text": "time machine ran"})
    risk = abs(entry - stop)
    lines = ["Ran: %s." % ENGINE_WORDS.get(n["engine"], n["engine"])]
    if n["p_target"] is not None:
        lines.append("Recorded then: target first %.0f%%, stop first %.0f%%, neither by the end %.0f%%, average %+.2fR "
                     "a path%s." % (100 * n["p_target"], 100 * (n["p_stop"] or 0), 100 * (n["p_neither"] or 0),
                                    n["avg_r"] or 0, " (%s paths x %s candles)" % (n["paths"], n["bars"]) if n["paths"] else ""))
    if n["hist_trades"] is not None:
        lines.append("History on this chart: %s trades%s, %s a trade." % (
            n["hist_trades"], ", %.0f%% won" % (100 * n["hist_win"]) if n["hist_win"] is not None else "",
            "%+.2fR" % n["hist_avg_r"] if n["hist_avg_r"] is not None else "?"))
    if redraw:
        lines.append("On the chart: %d of %d replays redrawn from %d candles before the decision (green = target "
                     "first, red = stop first, grey = neither); their odds are under the chart." % (
                         len(redraw.get("samples", [])), redraw["paths"], len(hist)))
    else:
        lines.append("Could not redraw the replays: too few candles before the decision came back.")
    if rec.get("why"):
        lines.append("Decision: %s: %s" % (rec.get("result"), rec["why"]))
    if n["verdict"]:
        lines.append("Verdict then: %s" % n["verdict"])
    w = CH.walk(cs, bar + 1, side, entry, stop, target, until=bar + 24 * 3600) if cs else None
    if w:
        how, at, r, best, _bt = w
        lines.append("What really happened: %s" % (
            "the target came first at %s (%+.2fR)" % (CH._hm(at), r) if how == "target" else
            "the stop came first at %s (-1R)" % CH._hm(at) if how == "stop" else
            "neither yet, %+.2fR at the last candle" % r))
        marks.append({"t": at, "kind": "win" if how == "target" else "loss" if how == "stop" else "exit",
                      "text": "really: target" if how == "target" else "really: stop" if how == "stop" else "now"})
    res = str(rec.get("result") or "")
    out = CH._base({"key": symbol, "market": market, "symbol": sym}, m2, s2, chart, True, cs, False)
    out["markers"] = sorted(marks, key=lambda m: m["t"])
    out["verdict"] = {"tone": "good" if (n["avg_r"] or 0) > 0.1 else "bad" if (n["avg_r"] or 0) < -0.1 else "flat",
                      "title": "Time machine: %s %s %s" % (symbol, side, sc.get("setup_name") or rec.get("setup") or ""),
                      "lines": lines}
    out["pos"] = {"key": symbol, "market": market, "symbol": sym, "side": side, "entry": entry, "stop": stop,
                  "risk_stop": stop, "target": target, "entry_time": datetime.fromtimestamp(bar, _tz.utc).isoformat(),
                  "setup_name": sc.get("setup_name") or rec.get("setup"), "reason": res, "planned": True,
                  "rr": round(abs(target - entry) / risk, 2) if target is not None and risk else None}
    out["replay"] = {"start": int(start), "step": 300, "bars": bars,
                     "paths": [{"end": p["end"], "r": p["r"], "c": p["c"]} for p in (redraw or {}).get("samples", [])],
                     "r_hist": (redraw or {}).get("r_hist"),
                     "stats": {k: (redraw or {}).get(k) for k in ("paths", "p_target", "p_stop", "p_neither", "avg_r")}}
    out["note"] = ("The exact 1,000 paths are not stored; they are redrawn here with the same method%s, so the odds can "
                   "differ a little from the recorded ones (the 60-day window of candles has moved since)." % (
                       " and the run's seed" if tm.get("seed") is not None else ""))
    return out
