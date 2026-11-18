#!/usr/bin/env python3
"""
dashboard_push.py - builds a snapshot of the bot's state for the dashboard.

live.py calls push(state) after every cycle; it writes trader/live/dashboard_snapshot.json, which the
dashboard API reads. The snapshot holds: runner status and uptime, every crypto coin watched and its
latest scan, the other markets' modes, the agents' decisions with their skip reasons, the paper ledger,
the live rules and the last log lines.

    python dashboard_push.py          # build and write the snapshot once
"""
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
LIVE = os.path.join("trader", "live")
STATE = os.path.join(LIVE, "state.json")
LOG = os.path.join(LIVE, "log.txt")
DECISIONS = os.path.join(LIVE, "decisions.jsonl")
LEDGER = os.path.join("trader", "paper", "ledger.json")
LOCAL_COPY = os.path.join(LIVE, "dashboard_snapshot.json")
UNIVERSE_CRYPTO = os.path.join("trader", "universe_crypto.txt")
RULE_FILES = {"crypto": "auto_config.json", "nse": "auto_nse_config.json", "fno": "auto_fno_config.json",
              "us": "auto_us_config.json"}
LOG_LINES = 400
DECISION_ROWS = 250
_warned = {"push": False}


def _json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _tail(path, n):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.readlines()[-n:]
    except Exception:
        return []


# ------------------------------------------------------------------ reasons

CATEGORIES = [
    ("volume not reported", "Volume not reported yet"),
    ("breakout volume", "Low volume"),
    ("stop too tight", "Stop too tight"),
    ("fell back", "Reversed"), ("moved back inside", "Reversed"), ("reversed", "Reversed"),
    ("chasing", "Chasing"),
    ("btc regime", "BTC regime"),
    ("market regime", "Market regime"),
    ("time machine", "Time machine"),
    ("fees eat", "Fees too high"),
    ("opened ", "Opening gap"),
    ("older than", "Stale signal"),
    ("auto_buy is off", "Log only"),
    ("lots fit", "Too big for budget"), ("units fit", "Too big for budget"),
    ("daily loss limit", "Daily loss limit"), ("max ", "Trade limit"),
    ("no live price", "No price"),
]


def category(result, why):
    if result in ("PAPER BUY", "PAPER SHORT"):
        return "Traded"
    if result == "LOG ONLY":
        return "Log only"
    w = (why or "").lower()
    for key, name in CATEGORIES:
        if key in w:
            return name
    return "Other"


# ------------------------------------------------------------------ runner uptime

LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  (.*)$")


def uptime(lines, gap_minutes=20):
    """Run segments from the log: a new segment on every 'live.py started' or a silence > gap_minutes."""
    segs, start, prev, started_at = [], None, None, None
    for ln in lines:
        m = LINE.match(ln.rstrip("\n"))
        if not m:
            continue
        t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
        msg = m.group(2)
        if start is None:
            start = t
        elif "live.py started" in msg or (t - prev) > timedelta(minutes=gap_minutes):
            segs.append((start, prev))
            start = t
        if "live.py started" in msg:
            started_at = t
        prev = t
    if start is not None:
        segs.append((start, prev))
    return segs, started_at


def kind_of(msg):
    if msg.startswith("Dashboard:") or msg.startswith("Automation:"):
        return "dashboard"
    if msg.startswith("AUTO "):
        if "PAPER BUY" in msg or "PAPER SHORT" in msg:
            return "trade"
        return "decision"
    if "CLOSED" in msg or "BREAKEVEN" in msg:
        return "trade"
    if "failed" in msg or "error" in msg.lower():
        return "error"
    if "live.py started" in msg or "stopped" in msg or "restarting" in msg:
        return "runner"
    return "scan"


# ------------------------------------------------------------------ snapshot

def build(state=None):
    state = state if state is not None else _json(STATE, {}) or {}
    now = datetime.now(IST)
    log_lines = _tail(LOG, 6000)
    segs, started_at = uptime(log_lines)
    day_ago = now - timedelta(hours=24)
    up24 = sum(max(0.0, (min(b, now) - max(a, day_ago)).total_seconds()) for a, b in segs if b >= day_ago) / 3600

    logs = []
    for ln in log_lines[-LOG_LINES:]:
        m = LINE.match(ln.rstrip("\n"))
        if m:
            logs.append({"t": m.group(1), "text": m.group(2), "kind": kind_of(m.group(2))})

    markets = state.get("markets") or {}
    cm = markets.get("CRYPTO") or {}
    intr, daily = cm.get("intraday") or {}, cm.get("daily") or {}
    try:
        with open(UNIVERSE_CRYPTO, encoding="utf-8") as fh:
            universe = [ln.split("|")[0].strip().upper() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    except Exception:
        universe = sorted((intr.get("coins") or {}).keys())
    daily_by = {}
    for h in daily.get("hits", []):
        daily_by.setdefault(h["symbol"], []).append(h["setup"])
    seen = cm.get("seen") or {}
    coins = []
    for sym in universe:
        c = (intr.get("coins") or {}).get(sym) or {}
        tags = c.get("tags") or [h["setup"] for h in intr.get("hits", []) if h["symbol"] == sym]
        state_ = ("breakout" if "range_breakout_4h" in tags else "breakdown" if "range_breakdown_4h" in tags
                  else "oversold" if "oversold_15m" in tags else ("no data" if c.get("usable") is False else "quiet"))
        coins.append({"symbol": sym, "state": state_, "price": c.get("price"), "pct_vs_high": c.get("pct_vs_high"),
                      "pct_vs_low": c.get("pct_vs_low"), "rsi_15m": c.get("rsi_15m"), "vol_ratio": c.get("vol_ratio"),
                      "range_high": c.get("range_high"), "range_low": c.get("range_low"),
                      "daily": daily_by.get(sym, []),
                      "seen_today": sorted(k.split("/", 1)[1] for k in seen if k.split("/", 1)[0] == sym)})

    decisions = []
    for ln in _tail(DECISIONS, 4000):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        st = r.get("steps") or {}
        ex = st.get("4_exit") if isinstance(st.get("4_exit"), dict) else {}
        sc = st.get("1_scanner") if isinstance(st.get("1_scanner"), dict) else {}
        en = st.get("3_entry") if isinstance(st.get("3_entry"), dict) else {}
        decisions.append({"time": r.get("time"), "symbol": r.get("symbol"), "market": (r.get("symbol") or ":").split(":")[0],
                          "setup": r.get("setup"), "result": r.get("result"), "why": r.get("why"),
                          "category": category(r.get("result"), r.get("why")),
                          "price": en.get("price_now") or ex.get("entry") or sc.get("price"),
                          "stop": ex.get("stop"), "target": ex.get("target"), "stop_pct": ex.get("stop_pct"),
                          "vol": sc.get("vol_ratio") if sc.get("vol_ratio") is not None else sc.get("vol_x_recent")})
    today = now.date().isoformat()
    # the current run: from the last start line or the last silence > 20 min
    run_start = segs[-1][0] if segs else started_at
    since = run_start.isoformat() if run_start else None
    reasons = {
        "since_restart": Counter(d["category"] for d in decisions if since and (d["time"] or "") >= since),
        "today": Counter(d["category"] for d in decisions if (d["time"] or "").startswith(today)),
        "all": Counter(d["category"] for d in decisions),
    }
    counts = Counter(d["result"] for d in decisions)

    led = _json(LEDGER, {}) or {}
    rules = {k: _json(os.path.join(LIVE, f), {}) for k, f in RULE_FILES.items()}
    nse, fno, us = markets.get("NSE") or {}, markets.get("FNO") or {}, markets.get("US") or {}
    snap = {
        "version": 1,
        "generated_at": now.isoformat(),
        "runner": {"mode": "vps" if os.environ.get("TRADER_SERVICE") else "pc", "status": state.get("status"), "updated": state.get("updated"), "next_run": state.get("next_run"),
                   "markets": state.get("markets_scanned"), "pid": state.get("pid"),
                   "started_at": since, "errors": state.get("errors") or [],
                   "uptime_24h_hours": round(up24, 2),
                   "segments": [{"start": a.isoformat(), "end": b.isoformat()} for a, b in segs[-30:]]},
        "crypto": {"universe": universe, "coins": coins, "scan_as_of": intr.get("as_of"),
                   "usable": intr.get("usable"), "scanned": intr.get("scanned"), "failed": intr.get("failed"),
                   "daily_closes_through": daily.get("closes_through")},
        "markets": {
            "CRYPTO": {"mode": "auto paper" if "range_breakout_4h" in (rules["crypto"] or {}).get("enabled_setups", ["range_breakout_4h"]) else "off",
                       "shorts": "range_breakdown_4h" in (rules["crypto"] or {}).get("enabled_setups", [])},
            "US": {"mode": "auto paper", "status": us.get("status"), "as_of": us.get("as_of"), "hits": us.get("hits")},
            "NSE": {"mode": "auto paper" if (rules["nse"] or {}).get("auto_buy") else "log only",
                    "regime": nse.get("regime"), "orb_as_of": (nse.get("orb") or {}).get("as_of"),
                    "orb_hits": len((nse.get("orb") or {}).get("hits", [])),
                    "universe": (nse.get("orb") or nse.get("daily") or {}).get("universe")},
            "FNO": {"mode": "auto paper" if (rules["fno"] or {}).get("auto_buy") else "log only",
                    "status": fno.get("status"), "NIFTY": fno.get("NIFTY"), "BANKNIFTY": fno.get("BANKNIFTY")},
        },
        "rules": rules,
        "decisions": decisions[-DECISION_ROWS:],
        "skip_reasons": {k: dict(v) for k, v in reasons.items()},
        "counts": {"decisions_total": len(decisions), "traded": counts.get("PAPER BUY", 0) + counts.get("PAPER SHORT", 0),
                   "skipped": counts.get("skipped", 0), "blocked": counts.get("blocked", 0),
                   "log_only": counts.get("LOG ONLY", 0)},
        "ledger": {"accounts": led.get("accounts") or {}, "open": led.get("open") or [],
                   "closed": (led.get("closed") or [])[-100:]},
        "logs": logs,
    }
    return snap


def push(state=None):
    """Write the snapshot. Write-then-rename, so the dashboard API never reads a half-written file."""
    body = json.dumps(build(state), default=str)
    os.makedirs(LIVE, exist_ok=True)
    tmp = LOCAL_COPY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.replace(tmp, LOCAL_COPY)
    return {"bytes": len(body)}


if __name__ == "__main__":
    print("Wrote %s (%d bytes)." % (LOCAL_COPY, push()["bytes"]))
