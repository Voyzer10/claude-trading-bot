"""
Operations API for the dashboard when the bot runs on your own machine (PC or VPS): everything you would
otherwise do by editing files or double-clicking .bat files. Mounted by api/index.py under /api/py/ops.

The runner (live.py) is the only process that writes the paper ledger. Actions that touch positions (close,
close all), "scan now" and "restart" are queued in trader/live/commands.jsonl; the runner picks them up within
~5 seconds and writes the result to commands_done.jsonl. Settings are plain files the runner re-reads every
cycle: trader/live/auto_config.json (crypto rules), trader/paper/config.json (risk limits),
trader/universe_crypto.txt (coins), trader/alerts.json (Telegram).

Every change made here is written to the runner log as "Dashboard: ..." so there is a record of who changed what.
The underscore in the file name keeps Vercel from treating it as a separate function.
"""
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "trader")
LIVE = os.path.join(T, "live")
PAPER_CFG = os.path.join(T, "paper", "config.json")
LEDGER = os.path.join(T, "paper", "ledger.json")
RULES = os.path.join(LIVE, "auto_config.json")
UNIVERSE = os.path.join(T, "universe_crypto.txt")
ALERTS = os.path.join(T, "alerts.json")
PREFS = os.path.join(T, "dashboard_prefs.json")
COMMANDS = os.path.join(LIVE, "commands.jsonl")
COMMANDS_DONE = os.path.join(LIVE, "commands_done.jsonl")
LOG = os.path.join(LIVE, "log.txt")
JOBS = os.path.join(T, "research", "jobs")
IST = timezone(timedelta(hours=5, minutes=30))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

router = APIRouter(prefix="/api/py/ops")

# What the dashboard may change, with limits. Anything else in the files is left alone.
RULE_FIELDS = {
    "enabled_setups": {"type": "setups", "choices": ["range_breakout_4h", "range_breakdown_4h"]},
    "stop": {"type": "choice", "choices": ["range-mid", "range-low"]},
    "target_r": {"type": "float", "min": 1.0, "max": 5.0},
    "max_chase_r": {"type": "float", "min": 0.0, "max": 2.0},
    "min_stop_pct": {"type": "float", "min": 0.0, "max": 5.0},
    "min_vol_x": {"type": "float", "min": 0.0, "max": 10.0},
    "btc_regime": {"type": "bool"},
    "max_fee_r": {"type": "float", "min": 0.05, "max": 1.0},
    "max_hold_hours": {"type": "float", "min": 1, "max": 48},
}
RISK_FIELDS = {
    "max_loss_per_trade": {"type": "float", "min": 0.01},
    "max_loss_per_trade_fno": {"type": "float", "min": 0.01, "accounts": ["INDIA"]},
    "daily_loss_limit": {"type": "float", "min": 0.01},
    "max_trades_per_day": {"type": "int", "min": 1, "max": 50},
    "max_position_pct": {"type": "float", "min": 1, "max": 100},
}
PREF_FIELDS = {"usd_inr": {"type": "float", "min": 50, "max": 200},
               "daily_goal_inr": {"type": "float", "min": 0, "max": 1e7}}
PREF_DEFAULT = {"usd_inr": 88.0, "daily_goal_inr": 500.0}
BACKTEST_MODES = ["crypto", "crypto-short", "crypto-mr", "nse", "fno"]


# ------------------------------------------------------------------ small helpers

def _now():
    return datetime.now(IST)


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(tmp, path)


def audit(msg):
    """One line in the runner log, same format as live.py's."""
    os.makedirs(LIVE, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write("%s  Dashboard: %s\n" % (_now().strftime("%Y-%m-%d %H:%M:%S"), msg))


def _coerce(name, spec, v):
    t = spec["type"]
    try:
        if t == "bool":
            if not isinstance(v, bool):
                raise ValueError
            return v
        if t == "choice":
            if v not in spec["choices"]:
                raise ValueError
            return v
        if t == "setups":
            if not isinstance(v, list) or not v or any(x not in spec["choices"] for x in v):
                raise ValueError
            return list(dict.fromkeys(v))
        x = int(v) if t == "int" else float(v)
        if x != x:  # NaN
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(400, "%s: invalid value %r" % (name, v))
    if "min" in spec and x < spec["min"] or "max" in spec and x > spec["max"]:
        raise HTTPException(400, "%s must be between %s and %s" % (name, spec.get("min", "-"), spec.get("max", "-")))
    return x


def _rule_defaults():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        import auto_crypto
        return dict(auto_crypto.DEFAULTS)
    except Exception:
        return {}


def _paper_defaults():
    try:
        import paper
        return paper.DEFAULT_CONFIG
    except Exception:
        return {"accounts": {}}


def _paper_cfg():
    cfg = _read_json(PAPER_CFG, None)
    d = _paper_defaults()
    if cfg is None:
        cfg = json.loads(json.dumps(d))
    for name, acc in d.get("accounts", {}).items():
        merged = dict(acc)
        merged.update((cfg.get("accounts") or {}).get(name) or {})
        cfg.setdefault("accounts", {})[name] = merged
    return cfg


def _mask(tok):
    return ("•" * 8 + tok[-4:]) if tok else ""


# ------------------------------------------------------------------ settings

@router.get("/settings")
def settings_get():
    defaults = _rule_defaults()
    rules = dict(defaults)
    rules.update(_read_json(RULES, {}))
    cfg = _paper_cfg()
    risk = {name: {k: acc.get(k) for k in list(RISK_FIELDS) + ["capital"] if k in acc}
            for name, acc in cfg["accounts"].items()}
    try:
        with open(UNIVERSE, encoding="utf-8") as fh:
            coins = [x.strip() for x in fh if x.strip() and not x.startswith("#")]
    except OSError:
        try:
            import scan_crypto
            coins = list(scan_crypto.TOP)
        except Exception:
            coins = []
    al = _read_json(ALERTS, {})
    prefs = dict(PREF_DEFAULT)
    prefs.update(_read_json(PREFS, {}))
    return {"rules": {k: rules.get(k) for k in RULE_FIELDS}, "rule_defaults": {k: defaults.get(k) for k in RULE_FIELDS},
            "rule_fields": RULE_FIELDS, "rules_version": rules.get("rules_version"),
            "risk": risk, "risk_fields": RISK_FIELDS, "coins": coins, "prefs": prefs,
            "alerts": {"enabled": bool(al.get("enabled")), "token_set": bool(al.get("telegram_token")),
                       "token_hint": _mask(al.get("telegram_token") or ""),
                       "chat_id": al.get("telegram_chat_id") or "",
                       "on": {"trades": True, "errors": True, "runner": True, "daily": True, **(al.get("on") or {})}}}


@router.post("/settings/rules")
async def settings_rules(request: Request):
    body = await request.json()
    changes = body.get("changes") or {}
    if not changes:
        raise HTTPException(400, "nothing to change")
    defaults = _rule_defaults()
    cur = dict(defaults)
    cur.update(_read_json(RULES, {}))
    diffs = []
    for k, v in changes.items():
        if k not in RULE_FIELDS:
            raise HTTPException(400, "%s cannot be changed here" % k)
        nv = _coerce(k, RULE_FIELDS[k], v)
        if cur.get(k) != nv:
            diffs.append("%s %s -> %s" % (k, cur.get(k), nv))
            cur[k] = nv
    if not diffs:
        return {"ok": True, "changed": []}
    cur["rules_version"] = defaults.get("rules_version", cur.get("rules_version"))
    cur["_edited"] = "changed from the dashboard %s" % _now().strftime("%Y-%m-%d %H:%M")
    _write_json(RULES, cur)
    audit("crypto rules: " + "; ".join(diffs) + " (applies on the next scan)")
    return {"ok": True, "changed": diffs}


@router.post("/settings/rules/reset")
def settings_rules_reset():
    d = _rule_defaults()
    if not d:
        raise HTTPException(500, "could not load the default rules (auto_crypto.py)")
    _write_json(RULES, d)
    audit("crypto rules reset to the backtested defaults (rules_version %s)" % d.get("rules_version"))
    return {"ok": True}


@router.post("/settings/risk")
async def settings_risk(request: Request):
    body = await request.json()
    acct, changes = body.get("account"), body.get("changes") or {}
    cfg = _paper_cfg()
    if acct not in cfg["accounts"]:
        raise HTTPException(400, "unknown account %r" % acct)
    acc = cfg["accounts"][acct]
    diffs = []
    for k, v in changes.items():
        spec = RISK_FIELDS.get(k)
        if not spec or acct not in spec.get("accounts", [acct]):
            raise HTTPException(400, "%s cannot be changed for %s" % (k, acct))
        nv = _coerce(k, spec, v)
        if k.startswith("max_loss") or k == "daily_loss_limit":
            if nv > float(acc.get("capital", 0)) * 0.5:
                raise HTTPException(400, "%s %s is more than half the %s capital" % (k, nv, acct))
        if acc.get(k) != nv:
            diffs.append("%s %s -> %s" % (k, acc.get(k), nv))
            acc[k] = nv
    if diffs:
        _write_json(PAPER_CFG, cfg)
        audit("%s risk limits: %s" % (acct, "; ".join(diffs)))
    return {"ok": True, "changed": diffs}


@router.post("/settings/coins")
async def settings_coins(request: Request):
    body = await request.json()
    coins = [str(x).strip().upper().replace("-USD", "") for x in body.get("coins") or [] if str(x).strip()]
    coins = list(dict.fromkeys(coins))
    bad = [c for c in coins if not re.fullmatch(r"[A-Z0-9]{2,12}", c)]
    if bad:
        raise HTTPException(400, "not a coin symbol: %s" % ", ".join(bad[:5]))
    if not 1 <= len(coins) <= 60:
        raise HTTPException(400, "keep between 1 and 60 coins (each one is fetched every 15 minutes)")
    os.makedirs(T, exist_ok=True)
    with open(UNIVERSE, "w", encoding="utf-8") as fh:
        fh.write("# crypto coins the runner watches (edited from the dashboard)\n" + "\n".join(coins) + "\n")
    audit("crypto coins set to %d: %s" % (len(coins), " ".join(coins)))
    return {"ok": True, "coins": coins}


@router.post("/settings/prefs")
async def settings_prefs(request: Request):
    body = await request.json()
    prefs = dict(PREF_DEFAULT)
    prefs.update(_read_json(PREFS, {}))
    for k, v in body.items():
        if k in PREF_FIELDS:
            prefs[k] = _coerce(k, PREF_FIELDS[k], v)
    _write_json(PREFS, prefs)
    return {"ok": True, "prefs": prefs}


# ------------------------------------------------------------------ alerts

@router.post("/alerts")
async def alerts_set(request: Request):
    body = await request.json()
    al = _read_json(ALERTS, {})
    if "telegram_token" in body and body["telegram_token"] and not str(body["telegram_token"]).startswith("•"):
        tok = str(body["telegram_token"]).strip()
        if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{20,}", tok):
            raise HTTPException(400, "that does not look like a bot token from @BotFather (123456:ABC...)")
        al["telegram_token"] = tok
    if "chat_id" in body:
        cid = str(body["chat_id"]).strip()
        if cid and not re.fullmatch(r"-?\d{3,20}", cid):
            raise HTTPException(400, "the chat id is a number")
        al["telegram_chat_id"] = cid
    if "enabled" in body:
        al["enabled"] = bool(body["enabled"])
    if isinstance(body.get("on"), dict):
        on = al.get("on") or {}
        on.update({k: bool(v) for k, v in body["on"].items() if k in ("trades", "errors", "runner", "daily")})
        al["on"] = on
    if al.get("enabled") and not (al.get("telegram_token") and al.get("telegram_chat_id")):
        raise HTTPException(400, "add the bot token and chat id before turning alerts on")
    _write_json(ALERTS, al)
    audit("alerts %s" % ("on" if al.get("enabled") else "off"))
    return {"ok": True}


@router.post("/alerts/test")
def alerts_test():
    import alerts
    al = _read_json(ALERTS, {})
    if not (al.get("telegram_token") and al.get("telegram_chat_id")):
        raise HTTPException(400, "save the bot token and chat id first")
    ok, detail = alerts.telegram(al["telegram_token"], al["telegram_chat_id"],
                                 "Test from your trader dashboard: alerts work.")
    return {"ok": ok, "detail": detail}


@router.post("/alerts/find-chat")
async def alerts_find_chat(request: Request):
    import alerts
    body = await request.json()
    tok = str(body.get("telegram_token") or "").strip()
    if not tok or tok.startswith("•"):
        tok = _read_json(ALERTS, {}).get("telegram_token") or ""
    if not tok:
        raise HTTPException(400, "paste the bot token first")
    cid, who = alerts.find_chat_id(tok)
    if not cid:
        raise HTTPException(404, who)
    return {"chat_id": cid, "name": who}


# ------------------------------------------------------------------ runner commands

@router.post("/command")
async def command(request: Request):
    body = await request.json()
    act = body.get("action")
    if act not in ("close", "close_all", "run_now", "restart"):
        raise HTTPException(400, "unknown action")
    if act == "close" and not body.get("key"):
        raise HTTPException(400, "which position? (key)")
    cmd = {"id": uuid.uuid4().hex[:10], "action": act, "key": body.get("key"), "asked_at": _now().isoformat()}
    os.makedirs(LIVE, exist_ok=True)
    with open(COMMANDS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(cmd) + "\n")
    audit("asked the runner: %s %s" % (act, cmd["key"] or ""))
    return {"ok": True, "id": cmd["id"]}


@router.get("/commands")
def commands():
    pending = []
    try:
        with open(COMMANDS, encoding="utf-8") as fh:
            pending = [json.loads(x) for x in fh if x.strip()]
    except OSError:
        pass
    done = []
    try:
        with open(COMMANDS_DONE, encoding="utf-8") as fh:
            done = [json.loads(x) for x in fh.readlines()[-20:] if x.strip()]
    except OSError:
        pass
    return {"pending": pending, "done": list(reversed(done))}


# ------------------------------------------------------------------ system and data health

def _proc_alive(pid):
    if not pid:
        return None
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except ImportError:
        if os.name == "posix":
            return os.path.exists("/proc/%d" % int(pid))
        return None  # unknown without psutil on Windows (never os.kill there: it terminates the process)


@router.get("/system")
def system():
    out = {"host": os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME"),
           "platform": sys.platform, "python": sys.version.split()[0], "root": ROOT,
           "service_mode": bool(os.environ.get("TRADER_SERVICE"))}
    du = shutil.disk_usage(ROOT)
    out["disk"] = {"total_gb": round(du.total / 1e9, 1), "used_gb": round(du.used / 1e9, 1),
                   "free_gb": round(du.free / 1e9, 1), "pct": round(du.used / du.total * 100, 1)}
    try:
        import psutil
        vm = psutil.virtual_memory()
        out["cpu_pct"] = psutil.cpu_percent(interval=0.3)
        out["cpus"] = psutil.cpu_count()
        out["mem"] = {"total_gb": round(vm.total / 1e9, 2), "used_gb": round((vm.total - vm.available) / 1e9, 2),
                      "pct": vm.percent}
        out["boot_time"] = datetime.fromtimestamp(psutil.boot_time(), IST).isoformat()
    except ImportError:
        out["note"] = "install psutil for CPU and memory (pip install psutil)"
        if hasattr(os, "getloadavg"):
            out["load"] = [round(x, 2) for x in os.getloadavg()]
    state = _read_json(os.path.join(LIVE, "state.json"), {})
    pid = state.get("pid")
    out["runner"] = {"pid": pid, "alive": _proc_alive(pid), "status": state.get("status"),
                     "updated": state.get("updated")}
    files = {}
    for name in ("log.txt", "decisions.jsonl", "state.json"):
        p = os.path.join(LIVE, name)
        if os.path.exists(p):
            files["live/" + name] = os.path.getsize(p)
    if os.path.exists(LEDGER):
        files["paper/ledger.json"] = os.path.getsize(LEDGER)
    out["files"] = files
    return out


def _probe(name, url, kind):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
        ms = int((time.time() - t0) * 1000)
        doc = json.loads(raw)
        if kind == "yahoo":
            res = (doc.get("chart") or {}).get("result") or []
            ts = (res[0].get("timestamp") or []) if res else []
            if not ts:
                return {"name": name, "ok": False, "ms": ms, "detail": "answered but no candles"}
            age = int(time.time() - ts[-1])
            return {"name": name, "ok": True, "ms": ms, "detail": "%d candles, last %d min ago" % (len(ts), age // 60)}
        rows = doc if isinstance(doc, list) else []
        if not rows:
            return {"name": name, "ok": False, "ms": ms, "detail": "answered but no candles"}
        return {"name": name, "ok": True, "ms": ms,
                "detail": "%d candles, last %d min ago" % (len(rows), int(time.time() - rows[0][0]) // 60)}
    except urllib.error.HTTPError as e:
        return {"name": name, "ok": False, "ms": int((time.time() - t0) * 1000),
                "detail": "HTTP %s %s (blocked or rate-limited?)" % (e.code, e.reason)}
    except Exception as e:
        return {"name": name, "ok": False, "ms": int((time.time() - t0) * 1000), "detail": str(e)[:200]}


@router.post("/datacheck")
def datacheck():
    """Can this machine get market data? The first thing to check on a new VPS: Yahoo blocks some datacenters."""
    y = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=15m&range=1d"
    probes = [("Yahoo crypto (BTC-USD)", y % "BTC-USD", "yahoo"),
              ("Yahoo NSE (RELIANCE.NS)", y % "RELIANCE.NS", "yahoo"),
              ("Yahoo US (AAPL)", y % "AAPL", "yahoo"),
              ("Yahoo index (^NSEI)", y % "%5ENSEI", "yahoo"),
              ("Coinbase crypto fallback (BTC-USD)",
               "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=900", "coinbase")]
    with ThreadPoolExecutor(5) as ex:
        res = list(ex.map(lambda p: _probe(*p), probes))
    audit("data check: " + ", ".join("%s %s" % (r["name"].split(" (")[0], "ok" if r["ok"] else "FAILED") for r in res))
    return {"checked_at": _now().isoformat(), "results": res}


# ------------------------------------------------------------------ performance

def _acct(m):
    return "INDIA" if m in ("NSE", "BSE", "NFO") else m


@router.get("/performance")
def performance():
    led = _read_json(LEDGER, {"accounts": {}, "open": [], "closed": []})
    prefs = dict(PREF_DEFAULT)
    prefs.update(_read_json(PREFS, {}))
    fx = {"INDIA": 1.0, "US": prefs["usd_inr"], "CRYPTO": prefs["usd_inr"]}
    today = _now().date()
    closed = led.get("closed") or []
    by_day = {}
    accounts = {}
    for c in closed:
        a = _acct(c.get("market"))
        d = c.get("exit_date") or (c.get("exit_time") or "")[:10]
        pnl = float(c.get("pnl") or 0)
        acc = accounts.setdefault(a, {"trades": 0, "wins": 0, "pnl": 0.0, "r_sum": 0.0, "today": 0.0, "d7": 0.0,
                                      "d30": 0.0, "best": None, "worst": None})
        acc["trades"] += 1
        acc["wins"] += pnl > 0
        acc["pnl"] += pnl
        acc["r_sum"] += float(c.get("r") or 0)
        try:
            age = (today - datetime.fromisoformat(d).date()).days
        except ValueError:
            age = 999
        acc["today"] += pnl if age == 0 else 0
        acc["d7"] += pnl if age < 7 else 0
        acc["d30"] += pnl if age < 30 else 0
        acc["best"] = pnl if acc["best"] is None else max(acc["best"], pnl)
        acc["worst"] = pnl if acc["worst"] is None else min(acc["worst"], pnl)
        by_day[d] = by_day.get(d, 0.0) + pnl * fx.get(a, 1.0)
    for a, acc in accounts.items():
        acc["win_rate"] = round(acc["wins"] / acc["trades"] * 100, 1) if acc["trades"] else None
        acc["avg_r"] = round(acc["r_sum"] / acc["trades"], 2) if acc["trades"] else None
        for k in ("pnl", "today", "d7", "d30", "best", "worst"):
            if acc[k] is not None:
                acc[k] = round(acc[k], 2)
        del acc["r_sum"]
    days = sorted(by_day)
    eq, run = [], 0.0
    for d in days:
        run += by_day[d]
        eq.append({"day": d, "pnl_inr": round(by_day[d], 2), "cum_inr": round(run, 2)})
    month = today.strftime("%Y-%m")
    month_days = [x for x in eq if x["day"].startswith(month)]
    goal = prefs["daily_goal_inr"]
    tot = lambda key: round(sum(accounts[a][key] * fx.get(a, 1.0) for a in accounts), 2)
    return {"prefs": prefs, "accounts": accounts, "daily": eq[-60:],
            "inr": {"today": tot("today"), "d7": tot("d7"), "d30": tot("d30"), "all": tot("pnl")},
            "month": {"days_traded": len(month_days), "green_days": sum(1 for x in month_days if x["pnl_inr"] > 0),
                      "red_days": sum(1 for x in month_days if x["pnl_inr"] < 0),
                      "pnl_inr": round(sum(x["pnl_inr"] for x in month_days), 2),
                      "goal_inr": round(goal * today.day, 2)},
            "open_positions": len(led.get("open") or []), "total_trades": len(closed)}


# ------------------------------------------------------------------ backtests

_jobs_lock = threading.Lock()


def _job_path(jid, ext):
    return os.path.join(JOBS, "%s.%s" % (jid, ext))


def _job_list():
    os.makedirs(JOBS, exist_ok=True)
    out = []
    for f in os.listdir(JOBS):
        if f.endswith(".json"):
            j = _read_json(os.path.join(JOBS, f), None)
            if j:
                out.append(j)
    out.sort(key=lambda j: j.get("started", ""), reverse=True)
    return out


def _watch(jid, proc, started):
    code = proc.wait()
    meta = _read_json(_job_path(jid, "json"), {})
    meta.update({"status": "done" if code == 0 else "failed", "exit_code": code, "ended": _now().isoformat(),
                 "seconds": int(time.time() - started)})
    _write_json(_job_path(jid, "json"), meta)


_running = {}


@router.post("/backtest")
async def backtest_start(request: Request):
    body = await request.json()
    mode = body.get("mode")
    if mode not in BACKTEST_MODES:
        raise HTTPException(400, "mode must be one of %s" % ", ".join(BACKTEST_MODES))
    with _jobs_lock:
        for jid, p in list(_running.items()):
            if p.poll() is None:
                raise HTTPException(409, "a backtest is already running; wait for it to finish")
            _running.pop(jid)
        jid = _now().strftime("%Y%m%d-%H%M%S") + "-" + mode
        os.makedirs(JOBS, exist_ok=True)
        args = [sys.executable, "-u", "research.py", mode]
        logf = open(_job_path(jid, "log"), "w", encoding="utf-8")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(args, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)
        logf.close()
        _write_json(_job_path(jid, "json"), {"id": jid, "mode": mode, "status": "running", "pid": proc.pid,
                                             "started": _now().isoformat()})
        _running[jid] = proc
        threading.Thread(target=_watch, args=(jid, proc, time.time()), daemon=True).start()
    audit("backtest started: research.py %s" % mode)
    return {"ok": True, "id": jid}


@router.get("/backtest")
def backtest_list():
    jobs = _job_list()
    for j in jobs:  # a job left "running" by an API restart cannot be watched any more
        if j.get("status") == "running" and j["id"] not in _running:
            j["status"] = "unknown (dashboard API restarted while it ran)"
    return {"jobs": jobs[:20], "modes": BACKTEST_MODES}


@router.get("/backtest/{jid}")
def backtest_get(jid: str):
    if not re.fullmatch(r"[0-9A-Za-z_.-]+", jid):
        raise HTTPException(400, "bad id")
    meta = _read_json(_job_path(jid, "json"), None)
    if meta is None:
        raise HTTPException(404, "no such backtest")
    try:
        with open(_job_path(jid, "log"), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        text = ""
    return {"job": meta, "output": text[-60000:]}


# ------------------------------------------------------------------ downloads

DOWNLOADS = {"ledger.json": LEDGER, "log.txt": LOG, "decisions.jsonl": os.path.join(LIVE, "decisions.jsonl"),
             "auto_config.json": RULES, "paper_config.json": PAPER_CFG}


@router.get("/download/{name}")
def download(name: str):
    if name == "trades.csv":
        led = _read_json(LEDGER, {"closed": []})
        cols = ["exit_date", "market", "symbol", "side", "qty", "entry", "exit", "stop", "target", "pnl", "r",
                "reason", "entry_time", "exit_time"]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for c in led.get("closed") or []:
            w.writerow([c.get(k, "long" if k == "side" else "") for k in cols])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=paper_trades.csv"})
    path = DOWNLOADS.get(name)
    if not path:
        raise HTTPException(404, "unknown file")
    if not os.path.exists(path):
        raise HTTPException(404, "%s does not exist yet" % name)
    return FileResponse(path, filename=name)
