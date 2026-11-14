#!/usr/bin/env python3
"""
timemachine_v4.py - the time machine for Scanner v4 setups (owner, 14 Nov 2026: "Logs + visual + v4 pe chalu").
Information only: it is recorded with every v4 decision (step 5) and shown on the dashboard; it never blocks or
opens a trade.

For one setup (entry, stop, target, side) on one chart, from that chart's own 5-minute candles (the ones the
scanner just read, usually the last 60 days):

  history  the same v4 rules over those candles (scanner_v4.sequence, the account's Trade Manager): how many
           trades this chart gave, how many won, the average R. "Has this rule worked on this chart?"
  replay   PATHS possible rests of the session, each built by drawing real past candles of this chart at random
           (their high / low / close as moves from the previous close) and stringing them together from the
           entry price; for each path: did the target come first, the stop first (a candle touching both counts
           as the stop, the worse case), or neither by the session's end (then R at the last close).
           "From here, how often does price reach the target before the stop?"

  run(rows, day_of, intraday, side, entry, stop, target, tm=None) -> dict (see the bottom of run)
"""
import random
from collections import Counter
from statistics import median

PATHS = 1000
CRYPTO_BARS = 48          # a 24h market has no session end: follow the next 4 hours
MIN_ROWS = 300
_HIST = {}                # (chart, last candle time) -> history (one sequence() per chart per candle)


def _moves(rows):
    """Each candle as (high, low, close) moves relative to the previous close."""
    out = []
    for k in range(1, len(rows)):
        pc = rows[k - 1][4]
        if pc and pc > 0:
            _, o, h, l, c = rows[k][:5]
            out.append((h / pc - 1, l / pc - 1, c / pc - 1))
    return out


def bars_left(rows, day_of, intraday):
    """Candles until the session ends (intraday) or CRYPTO_BARS (24h markets)."""
    if not intraday:
        return CRYPTO_BARS
    per_day = Counter(day_of(r[0]) for r in rows)
    today = day_of(rows[-1][0])
    full = [n for d, n in per_day.items() if d != today]
    typical = int(median(full)) if full else 75
    return max(3, typical - per_day[today])


def replay(rows, side, entry, stop, target, bars, paths=PATHS, seed=None):
    moves = _moves(rows)
    risk = abs(entry - stop)
    if not moves or risk <= 0:
        return None
    rnd = random.Random(seed)
    sh = side == "short"
    tgt_n = stop_n = 0
    rs = []
    for _ in range(paths):
        p = entry
        out = None
        for _ in range(bars):
            dh, dl, dc = moves[rnd.randrange(len(moves))]
            h, l, c = p * (1 + dh), p * (1 + dl), p * (1 + dc)
            if (h >= stop) if sh else (l <= stop):
                out = -1.0
                stop_n += 1
                break
            if target is not None and ((l <= target) if sh else (h >= target)):
                out = abs(target - entry) / risk
                tgt_n += 1
                break
            p = c
        if out is None:
            out = ((entry - p) if sh else (p - entry)) / risk
        rs.append(out)
    n = float(paths)
    return {"paths": paths, "bars": bars, "p_target": round(tgt_n / n, 3), "p_stop": round(stop_n / n, 3),
            "p_neither": round(1 - (tgt_n + stop_n) / n, 3), "avg_r": round(sum(rs) / n, 3)}


def history(rows, day_of, intraday, tm=None, chart=None):
    """The v4 rules over this chart's candles: trades, wins, average R (closed trades only)."""
    import scanner_v4 as V4
    key = (chart, rows[-1][0]) if chart else None
    if key and key in _HIST:
        return _HIST[key]
    try:
        seq = V4.sequence(rows, day_of, intraday=intraday, **(tm or {}))
    except Exception as e:
        return {"error": str(e)[:120]}
    done = [t for t in seq if t.get("exit_i") is not None and t["exit_i"] < len(rows) - 1 and t.get("risk")]
    rs = [((t["exit"] - t["entry"]) * (1 if t["side"] == "long" else -1)) / t["risk"] for t in done]
    out = {"trades": len(rs), "days": len({day_of(r[0]) for r in rows}),
           "win_rate": round(sum(1 for r in rs if r > 0.05) / len(rs), 3) if rs else None,
           "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
           "target_hits": sum(1 for t in done if str(t.get("exit_reason", "")).startswith("target"))}
    if key:
        if len(_HIST) > 500:
            _HIST.clear()
        _HIST[key] = out
    return out


def verdict(rep, hist):
    if not rep:
        return "no replay (too few candles)"
    hit = rep["p_target"] + rep["p_stop"]
    first = ("target first in %.0f%% of the paths that reached one side" % (100 * rep["p_target"] / hit)) if hit else \
        "no path reached the stop or the target"
    lean = "leans to the target" if rep["avg_r"] > 0.1 else "leans to the stop" if rep["avg_r"] < -0.1 else "a coin flip"
    h = ""
    if hist and hist.get("trades"):
        h = "; this chart's last %d days: %d v4 trades, %.0f%% won, %+.2fR a trade" % (
            hist["days"], hist["trades"], 100 * (hist["win_rate"] or 0), hist["avg_r"] or 0)
    return "%s: %s, %+.2fR a path%s" % (lean, first, rep["avg_r"], h)


def run(rows, day_of, intraday, side, entry, stop, target, tm=None, chart=None, paths=PATHS, seed=None):
    """{"replay": {...}, "history": {...}, "verdict": str, "gate": "info only"} or None (too few candles)."""
    if not rows or len(rows) < MIN_ROWS:
        return None
    bars = bars_left(rows, day_of, intraday)
    rep = replay(rows, side, float(entry), float(stop), float(target) if target is not None else None, bars, paths, seed)
    hist = history(rows, day_of, intraday, tm, chart)
    return {"replay": rep, "history": hist, "verdict": verdict(rep, hist), "gate": "info only (never blocks a v4 trade)",
            "candles": len(rows)}
