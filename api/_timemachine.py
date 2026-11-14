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
