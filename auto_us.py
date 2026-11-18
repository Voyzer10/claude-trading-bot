#!/usr/bin/env python3
"""
auto_us.py - the US agent pack, run automatically on live US breakouts, with PAPER trades only
(paper.py's US account; nothing is sent to a broker).

live.py --markets US --auto-paper calls process() every cycle. During 9:50 AM - 3:30 PM ET, every
`scan_every_min` minutes it starts the pack's scanner over the whole US universe IN THE BACKGROUND (a scan
takes minutes; the runner keeps checking stops meanwhile) and picks up the result on a later cycle. Each NEW,
FRESH breakout (triggered within `fresh_minutes`) then goes through the pack's scripts in us\\:

  1 scanner      trader-scanner/scan.py orb
  2 news         trader-news/news.py           (recorded, never acted on)
  3 entry        trader-entry/entry.py check   (must still say TRIGGERED, today)
  4 exit         trader-exit/exit.py plan      (stop at the range midpoint, 2R target)
  5 timemachine  trader-timemachine/timemachine.py run   (skips a negative edge)
  6-8            ..\\paper.py buy US:TICKER: sizes to the US account's max loss and checks every limit
                 against the real paper ledger, then fills on paper; your --auto-paper is the yes
  9 alerts       live.py's paper check closes stops, targets and the 3:55 PM ET flat-by

Rules: trader/live/auto_us_config.json (made on first run). Decisions: trader/live/decisions.jsonl.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import paper as P

ROOT = os.path.dirname(os.path.abspath(__file__))
US = os.path.join(ROOT, "us")
LIVE_DIR = os.path.join("trader", "live")
CFG_FILE = os.path.join(LIVE_DIR, "auto_us_config.json")
DECISIONS = os.path.join(LIVE_DIR, "decisions.jsonl")
SCAN_LOG = os.path.join(US, "trader", "scan.log")
PY = sys.executable
SCAN_TIMEOUT = timedelta(minutes=15)

DEFAULTS = {
    "_note": "Auto PAPER trading rules for US stocks. Paper money only.",
    "scan_every_min": 10,
    "max_confirm": 200,          # scanner stage 2: the N most traded candidates get real highs/lows
    "fresh_minutes": 15,         # only breakouts that triggered this recently
    "max_new_per_cycle": 5,
    "target": "2R",
    "min_stop_pct": 0.3,         # skip stops tighter than this % of the entry
    "min_mc_avg_r": 0.0,         # time machine replays must average at least this
    "min_history_trades": 10,
    "min_history_avg_r": 0.0,
}

_scan = {}  # the background scanner: {"proc", "kind", "started"}


def load_cfg():
    os.makedirs(LIVE_DIR, exist_ok=True)
    if not os.path.exists(CFG_FILE):
        with open(CFG_FILE, "w", encoding="utf-8") as fh:
            json.dump(DEFAULTS, fh, indent=2)
    cfg = dict(DEFAULTS)
    with open(CFG_FILE, encoding="utf-8") as fh:
        cfg.update(json.load(fh))
    return cfg


def et_now(utc):
    return P.local_now("US", utc)


def sh(args, cwd=US, timeout=180):
    r = subprocess.run([PY] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def us_json(rel):
    try:
        with open(os.path.join(US, rel), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def tail(text, n=6):
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-n:]


def record(rec):
    with open(DECISIONS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def parse_at(at, day):
    t = datetime.strptime(at.strip(), "%I:%M %p")
    return day.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)


def run_one(tk, hit, cfg, log, auto, today):
    rec = {"time": datetime.now(P.IST).isoformat(), "symbol": "US:" + tk, "setup": "orb", "steps": {}, "result": None}
    st = rec["steps"]
    st["1_scanner"] = hit

    def done(result, why):
        rec["result"], rec["why"] = result, why
        record(rec)
        log("AUTO US %s: %s (%s)" % (tk, result, why))
        return rec

    _, out = sh([os.path.join("trader-news", "news.py"), "--tickers", tk, "--hours", "12", "--no-sec", "--all"])
    st["2_news"] = tail(out, 8)

    rc, out = sh([os.path.join("trader-entry", "entry.py"), "check", tk, "--setup", "orb", "--write"])
    e = us_json(os.path.join("trader", "entry.json")) or {}
    st["3_entry"] = {"status": e.get("status"), "time": e.get("time"), "price": e.get("price"), "level": e.get("level")}
    if e.get("symbol") != tk or e.get("date") != today:  # entry.py failed and left an older file behind
        return done("skipped", "entry check did not run: %s" % " ".join(tail(out, 2)))
    if e.get("status") != "triggered":
        return done("skipped", "entry says %s" % e.get("status"))

    rc, out = sh([os.path.join("trader-exit", "exit.py"), "plan", "--stop", "or-mid", "--target", cfg["target"], "--write"])
    plan = us_json(os.path.join("trader", "plan.json")) or {}
    if plan.get("symbol") != tk or plan.get("date") != e.get("date"):
        return done("skipped", "exit planner refused: %s" % " ".join(tail(out, 2)))
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    stop_pct = (entry - stop) / entry * 100
    st["4_exit"] = {"entry": entry, "stop": stop, "target": target, "stop_pct": round(stop_pct, 2)}
    if stop_pct < cfg["min_stop_pct"]:
        return done("skipped", "stop too tight: %.2f%% (min %.2f%%)" % (stop_pct, cfg["min_stop_pct"]))

    rc, out = sh([os.path.join("trader-timemachine", "timemachine.py"), "run", "--write"], timeout=300)
    tm = us_json(os.path.join("trader", "timemachine.json")) or {}
    mc, hist = tm.get("mc") or {}, tm.get("history") or {}
    st["5_timemachine"] = {"p_target": mc.get("p_target"), "p_stop": mc.get("p_stop"), "p_neither": mc.get("p_neither"),
                           "avg_R": mc.get("avg_R"), "history_triggered": hist.get("triggered"),
                           "history_avg_R": hist.get("avg_R"), "verdict": tm.get("verdict")}
    if rc != 0 or (tm.get("plan") or {}).get("symbol") != tk or mc.get("avg_R") is None:
        return done("skipped", "time machine could not run: %s" % " ".join(tail(out, 2)))
    if mc["avg_R"] < cfg["min_mc_avg_r"]:
        return done("skipped", "time machine: replays average %+.2fR" % mc["avg_R"])
    if (hist.get("triggered") or 0) >= cfg["min_history_trades"] and (hist.get("avg_R") or 0) < cfg["min_history_avg_r"]:
        return done("skipped", "time machine: this rule averaged %+.2fR over %d past fires" % (hist["avg_R"], hist["triggered"]))

    if not auto:
        return done("ready", "all checks passed; auto paper is off")
    rc, out = sh([os.path.join(ROOT, "paper.py"), "buy", "US:" + tk, "--stop", str(stop), "--target", str(target),
                  "--note", "auto_us: orb"], cwd=ROOT)
    st["6-8_budget_risk_broker"] = tail(out, 4)
    if rc != 0:
        return done("blocked", "paper.py: %s" % " ".join(tail(out, 1)))
    st["9_alerts"] = "live.py checks stop %s / target %s every cycle; flat by 3:55 PM ET" % (stop, target)
    return done("PAPER BUY", "stop %s, target %s; replays %+.2fR, history %s" % (
        stop, target, mc["avg_R"],
        ("%s fires %+.2fR" % (hist.get("triggered"), hist.get("avg_R"))) if hist.get("triggered") else "n/a"))


def start_scan(kind, args):
    """Run one scanner command in the background; its output goes to us/trader/scan.log."""
    os.makedirs(os.path.dirname(SCAN_LOG), exist_ok=True)
    with open(SCAN_LOG, "w", encoding="utf-8") as fh:
        proc = subprocess.Popen([PY, os.path.join("trader-scanner", "scan.py")] + args, cwd=US,
                                stdout=fh, stderr=subprocess.STDOUT)
    _scan.update({"proc": proc, "kind": kind, "started": datetime.now(timezone.utc)})


def finished_scan(log):
    """None while a scan runs (or none ran); else the finished scan's kind. Kills a scan that hangs."""
    proc = _scan.get("proc")
    if proc is None:
        return None
    if proc.poll() is None:
        if datetime.now(timezone.utc) - _scan["started"] < SCAN_TIMEOUT:
            return None
        proc.kill()
        log("US scan timed out after %d min and was stopped" % (SCAN_TIMEOUT.total_seconds() // 60))
    kind = _scan["kind"]
    _scan.clear()
    return kind


def process(state, log, auto=True):
    cfg = load_cfg()
    utc = datetime.now(timezone.utc)
    et = et_now(utc)
    today = et.date().isoformat()
    ms = state.setdefault("markets", {}).setdefault("US", {})
    if P.session("US", utc) != "open":
        ms["status"] = "closed"
        return
    start = et.replace(hour=9, minute=50, second=0, microsecond=0)
    stop = et.replace(hour=15, minute=30, second=0, microsecond=0)
    if not (start <= et < stop):
        ms["status"] = "open, outside the 9:50-15:30 ET entry window"
        return
    if _scan.get("proc") is not None:
        kind = finished_scan(log)
        if kind is None:
            ms["status"] = "scanning (started %s ET)" % P.local_now("US", _scan["started"]).strftime("%H:%M")
            return
        if kind == "orb":
            take_hits(state, ms, cfg, log, auto, et, today)
            return
    last = ms.get("last_scan_utc")
    if last and utc - datetime.fromisoformat(last) < timedelta(minutes=cfg["scan_every_min"]):
        return
    if not os.path.exists(os.path.join(US, "trader", "universe.txt")):
        log("US: building the stock list first (once)")
        start_scan("universe", ["universe"])
        return
    log("US scan started in the background (whole universe, a few minutes)")
    start_scan("orb", ["orb", "--max-confirm", str(cfg["max_confirm"])])
    ms["last_scan_utc"] = utc.isoformat()
    ms["status"] = "scanning"


def take_hits(state, ms, cfg, log, auto, et, today):
    """Run the agents on the fresh hits of the scan that just finished."""
    wl = us_json(os.path.join("trader", "watchlist.json")) or {}
    summary = tail(_read(SCAN_LOG), 1)
    if not str(wl.get("as_of") or "").startswith(today):  # no scan today (holiday, error): an older file
        ms["status"] = "scan wrote nothing today: %s" % " ".join(summary)
        log("US scan gave no result for today: %s" % " ".join(tail(_read(SCAN_LOG), 2)))
        return
    hits = wl.get("hits", [])
    seen = ms.get("seen") if ms.get("seen_date") == today else {}
    fresh, new = [], []
    for h in hits:
        if h["symbol"] in seen:
            continue
        new.append(h["symbol"])
        try:
            age = et - parse_at(h["at"], et)
        except Exception:
            seen[h["symbol"]] = h.get("at")
            continue
        if age <= timedelta(minutes=cfg["fresh_minutes"]):
            fresh.append(h)       # marked seen only once it is actually run below
        else:
            seen[h["symbol"]] = h.get("at")  # stale: never run
    ms.update({"seen": seen, "seen_date": today, "as_of": wl.get("as_of"), "hits": len(hits),
               "status": "scanned", "summary": summary})
    log("US ORB @%s: %d hits, %d new, %d fresh (<= %d min)%s" % (
        wl.get("as_of"), len(hits), len(new), len(fresh), cfg["fresh_minutes"],
        ("; FRESH: " + ", ".join(h["symbol"] for h in fresh[:15])) if fresh else ""))
    fresh.sort(key=lambda h: (-h.get("bar_index", 0), h["symbol"]))
    out_recs = []
    for h in fresh[:cfg["max_new_per_cycle"]]:
        seen[h["symbol"]] = h.get("at")
        try:
            out_recs.append(run_one(h["symbol"], h, cfg, log, auto, today))
        except Exception as ex:
            log("AUTO US %s failed: %s" % (h["symbol"], ex))
    auto_st = state.setdefault("auto", {"recent": []})
    auto_st["recent"] = (auto_st.get("recent", []) + [{"time": r["time"], "symbol": r["symbol"], "result": r["result"],
                                                       "why": r["why"]} for r in out_recs])[-20:]


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""
