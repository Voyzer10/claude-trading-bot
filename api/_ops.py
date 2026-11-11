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
    "enabled_setups": {"type": "setups", "choices": ["range_breakout_4h", "range_breakdown_4h", "smc_sweep_long",
                                                     "smc_sweep_short", "smcp_doji_long", "smcp_doji_short",
                                                     "smcp_star_long", "smcp_hammer_short", "smcp_fvg_long",
                                                     "smcp_fvg_short", "smcp_ob_long", "smcp_ob_short"]},
    "stop": {"type": "choice", "choices": ["atr", "range-mid", "range-low"]},
    "stop_atr_k": {"type": "float", "min": 0.5, "max": 4.0},
    "exit": {"type": "choice", "choices": ["trail", "target"]},
    "trail_atr_k": {"type": "float", "min": 0.5, "max": 5.0},
    "target_r": {"type": "float", "min": 1.0, "max": 5.0},
    "max_chase_r": {"type": "float", "min": 0.0, "max": 2.0},
    "min_stop_pct": {"type": "float", "min": 0.0, "max": 5.0},
    "min_vol_x": {"type": "float", "min": 0.0, "max": 10.0},
    "btc_regime": {"type": "bool"},
    "max_fee_r": {"type": "float", "min": 0.05, "max": 1.0},
    "max_hold_hours": {"type": "float", "min": 1, "max": 48},
    "timeframe": {"type": "choice", "choices": ["15m", "5m"]},
    "short_exit": {"type": "choice", "choices": ["2R", "trail"]},
    "short_trend": {"type": "choice", "choices": ["off", "ema", "ema+slope"]},
    "short_max_range_pct": {"type": "float", "min": 0.0, "max": 10.0},
    "short_min_vol_x": {"type": "float", "min": 0.0, "max": 10.0},
    "short_skip_thin_hours": {"type": "bool"},
    "smc_variant": {"type": "choice", "choices": ["any", "wick", "2bar"]},
    "smc_stop": {"type": "choice", "choices": ["sweep", "atr1.5"]},
    "smc_exit": {"type": "choice", "choices": ["2R", "mid", "trail"]},
    "smc_min_vol_x": {"type": "float", "min": 0.0, "max": 10.0},
    "smc_regime": {"type": "bool"},
    "smcp_confirm": {"type": "int", "min": 1, "max": 2},
    "smcp_struct": {"type": "choice", "choices": ["before", "any", "none"]},
    "smcp_doji_pct": {"type": "float", "min": 0.05, "max": 0.3},
    "smcp_buffer_atr": {"type": "float", "min": 0.0, "max": 1.0},
    "smcp_target": {"type": "choice", "choices": ["internal", "external", "2R", "trail"]},
    "smcp_min_rr": {"type": "float", "min": 0.5, "max": 5.0},
    "smcp_regime": {"type": "bool"},
    "smcp_skip_thin_hours": {"type": "bool"},
    "smcp_liq": {"type": "choice", "choices": ["base", "all", "strong"]},
    "smcp_min_disp": {"type": "float", "min": 0.0, "max": 3.0},
}
# the other markets' strategy rules (Settings > Strategy rules, one tab per market): the agent's own config file
_T = {"type": "time"}
MARKET_RULES = {
    "NSE": {"file": "auto_nse_config.json", "module": "auto_nse", "account": "INDIA", "fields": {
        "entry_start": _T, "entry_end": _T, "fresh_minutes": {"type": "int", "min": 1, "max": 60},
        "stop": {"type": "choice", "choices": ["range-mid", "range-low"]},
        "target_r": {"type": "float", "min": 1.0, "max": 5.0}, "min_stop_pct": {"type": "float", "min": 0.0, "max": 5.0},
        "max_chase_r": {"type": "float", "min": 0.0, "max": 2.0}, "min_vol_x": {"type": "float", "min": 0.0, "max": 10.0},
        "max_gap_pct": {"type": "float", "min": 0.0, "max": 20.0}, "regime_filter": {"type": "bool"},
        "allow_short": {"type": "bool"}, "min_sim_avg_r": {"type": "float", "min": -1.0, "max": 2.0},
        "min_history_trades": {"type": "int", "min": 0, "max": 100},
        "min_history_avg_r": {"type": "float", "min": -1.0, "max": 2.0},
        "max_new_per_cycle": {"type": "int", "min": 1, "max": 20}}},
    "US": {"file": "auto_us_config.json", "module": "auto_us", "account": "US", "fields": {
        "scan_every_min": {"type": "int", "min": 5, "max": 60}, "or_minutes": {"type": "int", "min": 5, "max": 60},
        "fresh_minutes": {"type": "int", "min": 1, "max": 60}, "max_new_per_cycle": {"type": "int", "min": 1, "max": 20},
        "min_stop_pct": {"type": "float", "min": 0.0, "max": 5.0}, "max_chase_r": {"type": "float", "min": 0.0, "max": 2.0},
        "allow_short": {"type": "bool"}, "short_regime": {"type": "bool"},
        "min_mc_avg_r": {"type": "float", "min": -1.0, "max": 2.0},
        "min_history_trades": {"type": "int", "min": 0, "max": 100},
        "min_history_avg_r": {"type": "float", "min": -1.0, "max": 2.0}}},
    "FNO": {"file": "auto_fno_config.json", "module": "auto_fno", "account": "INDIA", "fields": {
        "indices": {"type": "setups", "choices": ["NIFTY", "BANKNIFTY"]},
        "instruments": {"type": "setups", "choices": ["options", "futures"]},
        "entry_start": _T, "entry_end": _T, "fresh_minutes": {"type": "int", "min": 1, "max": 60},
        "target_r": {"type": "float", "min": 1.0, "max": 5.0}, "max_chase_r": {"type": "float", "min": 0.0, "max": 2.0},
        "min_days_to_expiry": {"type": "int", "min": 0, "max": 10},
        "theta_haircut_r": {"type": "float", "min": 0.0, "max": 1.0},
        "min_sim_avg_r": {"type": "float", "min": -1.0, "max": 2.0},
        "min_history_trades": {"type": "int", "min": 0, "max": 100},
        "min_history_avg_r": {"type": "float", "min": -1.0, "max": 2.0}}},
}

RISK_FIELDS = {
    "capital": {"type": "float", "min": 100},
    "risk_limits": {"type": "bool"},
    "trade_setups": {"type": "bool"},
    "scanner_version": {"type": "choice", "choices": ["v5", "v4", "v3", "v2", "rules"]},
    "v5_setups": {"type": "setups", "allow_empty": True, "choices": ["v5_level_long", "v5_level_short"]},
    "v5_constant": {"type": "float", "min": 0.01, "max": 0.95},
    "v5_move": {"type": "choice", "choices": ["swing", "day"]},
    "v5_target": {"type": "choice", "choices": ["leg", "2R"]},
    "v4_setups": {"type": "setups", "allow_empty": True,
                  "choices": ["v4_primary_long", "v4_primary_short", "v4_secondary_long", "v4_secondary_short"]},
    "trade_manager": {"type": "bool"},
    "fno_stock_options": {"type": "bool"},
    "tm_be_r": {"type": "float", "min": 0.3, "max": 5},
    "tm_lock_at": {"type": "float", "min": 0.3, "max": 0.99},
    "tm_lock_keep": {"type": "float", "min": 0.1, "max": 0.95},
    "tm_reversal": {"type": "bool"},
    "tm_rev_min_r": {"type": "float", "min": 0.3, "max": 5},
    "tm_stale_min": {"type": "float", "min": 0, "max": 1440},
    "tm_candle_min": {"type": "int", "min": 1, "max": 60},
    "cooldown_losses": {"type": "int", "min": 0, "max": 20},
    "cooldown_minutes": {"type": "float", "min": 0, "max": 1440},
    "weekly_loss_x": {"type": "float", "min": 0, "max": 10},
    "max_same_side": {"type": "int", "min": 0, "max": 20, "accounts": ["CRYPTO"]},
    "max_loss_per_trade": {"type": "float", "min": 0.01},
    "max_loss_per_trade_fno": {"type": "float", "min": 0.01, "accounts": ["INDIA"]},
    "daily_loss_limit": {"type": "float", "min": 0.01},
    "max_trades_per_day": {"type": "int", "min": 1, "max": 50},
    "max_position_pct": {"type": "float", "min": 1, "max": 100},
    "fee_pct": {"type": "float", "min": 0.0, "max": 1.0, "accounts": ["CRYPTO"]},
}
PREF_FIELDS = {"usd_inr": {"type": "float", "min": 50, "max": 200},
               "daily_goal_inr": {"type": "float", "min": 0, "max": 1e7}}
PREF_DEFAULT = {"usd_inr": 88.0, "daily_goal_inr": 500.0}
BACKTEST_MODES = ["crypto-sv5", "crypto-sv5-5m", "us-sv5", "nse-sv5", "gold-sv5", "fno-sv4", "us-tm", "nse-tm", "crypto-tm", "crypto-tm-5m", "crypto-sv4", "crypto-sv4-5m", "us-sv4", "nse-sv4", "crypto-v3", "crypto-v3-5m", "us-v3", "nse-v3", "us-orb", "crypto-abcd", "crypto-abcd-5m", "us-abcd", "nse-abcd", "crypto-smcp", "crypto-smcp-5m", "nse-smcp", "crypto-v4", "crypto-v4-short", "crypto-v4-5m", "crypto-smc", "nse-v2", "crypto-live", "crypto", "crypto-5m", "crypto-short", "crypto-mr", "nse", "fno"]


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
        if t == "time":
            h, m = str(v).split(":")
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59) or len(m) != 2:
                raise ValueError
            return "%02d:%s" % (int(h), m)
        if t == "setups":
            if not isinstance(v, list) or (not v and not spec.get("allow_empty")) or \
                    any(x not in spec["choices"] for x in v):
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
    markets = {}
    for m, spec in MARKET_RULES.items():
        d = _market_defaults(m)
        cur = dict(d)
        cur.update(_read_json(os.path.join(LIVE, spec["file"]), {}))
        markets[m] = {"rules": {k: cur.get(k) for k in spec["fields"]}, "defaults": {k: d.get(k) for k in spec["fields"]},
                      "fields": spec["fields"], "account": spec["account"]}
    return {"markets": markets,
            "rules": {k: rules.get(k) for k in RULE_FIELDS}, "rule_defaults": {k: defaults.get(k) for k in RULE_FIELDS},
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


def _market_defaults(m):
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        return dict(__import__(MARKET_RULES[m]["module"]).DEFAULTS)
    except Exception:
        return {}


@router.post("/settings/market-rules")
async def settings_market_rules(request: Request):
    """NSE / US / FNO strategy rules: written to that agent's own config (it reads it every cycle)."""
    body = await request.json()
    m, changes = body.get("market"), body.get("changes") or {}
    if m not in MARKET_RULES:
        raise HTTPException(400, "unknown market %r" % m)
    spec = MARKET_RULES[m]
    path = os.path.join(LIVE, spec["file"])
    saved = _read_json(path, None)
    cur = dict(_market_defaults(m))
    cur.update(saved or {})
    diffs = []
    for k, v in changes.items():
        if k not in spec["fields"]:
            raise HTTPException(400, "%s cannot be changed here" % k)
        nv = _coerce(k, spec["fields"][k], v)
        if cur.get(k) != nv:
            diffs.append("%s %s -> %s" % (k, cur.get(k), nv))
            cur[k] = nv
    if not diffs:
        return {"ok": True, "changed": []}
    if "entry_start" in cur and "entry_end" in cur and cur["entry_start"] >= cur["entry_end"]:
        raise HTTPException(400, "the entry window must start before it ends")
    cur["_edited"] = "changed from the dashboard %s" % _now().strftime("%Y-%m-%d %H:%M")
    _write_json(path, cur)
    audit("%s rules: %s (applies on the next cycle)" % (m, "; ".join(diffs)))
    return {"ok": True, "changed": diffs}


@router.post("/settings/market-rules/reset")
async def settings_market_rules_reset(request: Request):
    m = (await request.json()).get("market")
    if m not in MARKET_RULES:
        raise HTTPException(400, "unknown market %r" % m)
    d = _market_defaults(m)
    if not d:
        raise HTTPException(500, "could not load the default rules")
    path = os.path.join(LIVE, MARKET_RULES[m]["file"])
    keep = {k: v for k, v in _read_json(path, {}).items() if k not in MARKET_RULES[m]["fields"]}
    _write_json(path, dict(d, **keep))     # keeps the on/off switches (auto_buy ...) set elsewhere
    audit("%s rules reset to the defaults" % m)
    return {"ok": True}


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


_ACCT = {"NSE": "INDIA", "BSE": "INDIA", "NFO": "INDIA"}


def _csv(rows, cols):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow(["" if r.get(k) is None else r.get(k) for k in cols])
    return buf.getvalue()


def _setup_of(t):
    """The setup behind a trade: its own setup_name (from 5 Nov 2026), else the agent's note."""
    if isinstance(t, dict):
        if t.get("setup_name") or t.get("setup"):
            return t.get("setup_name") or t.get("setup")
        note = t.get("note")
    else:
        note = t
    n = re.sub(r"^(auto(_nse|_us|_fno)?|scanner v\d)\s*:\s*", "", (note or "").strip(), flags=re.I)
    return n.replace("_", " ") or "manual"


def _scanner_of(t):
    if t.get("scanner"):
        return t["scanner"]
    m = re.match(r"scanner (v\d)", t.get("note") or "", re.I)
    return m.group(1).lower() if m else ("rules" if (t.get("note") or "").startswith("auto") else "manual")


def _minutes(a, b):
    try:
        return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60, 1)
    except (TypeError, ValueError):
        return None


def _trade_row(c, closed=True):
    entry, rs = c.get("entry"), c.get("risk_stop", c.get("stop"))
    risk_pu = abs(entry - rs) if entry is not None and rs is not None else None
    row = dict(c)
    row.update({"account": _ACCT.get(c.get("market"), c.get("market")), "side": c.get("side") or "long",
                "setup_name": _setup_of(c), "scanner": _scanner_of(c),
                "risk_per_unit": round(risk_pu, 6) if risk_pu is not None else None,
                "risk_money": round(risk_pu * c.get("qty", 0), 2) if risk_pu is not None else None,
                "planned_rr": round(abs(c.get("target", entry) - entry) / risk_pu, 2) if risk_pu else None,
                "fees": round((c.get("entry_fee") or 0) + (c.get("exit_fee") or 0), 4)})
    if closed:
        row.update({"exit_reason": c.get("reason"), "result": "win" if (c.get("pnl") or 0) > 0 else "loss",
                    "held_minutes": _minutes(c.get("entry_time"), c.get("exit_time"))})
    return row


TRADE_COLS = ["exit_date", "account", "market", "symbol", "side", "setup_name", "scanner", "liquidity", "entry_reason",
              "qty", "entry", "stop", "risk_stop", "target", "planned_rr", "exit", "exit_reason", "result", "pnl", "r",
              "mfe_r", "mae_r", "risk_money", "fees", "entry_time", "exit_time", "held_minutes", "breakeven", "locked",
              "trailing", "setup", "note"]
OPEN_COLS = ["account", "market", "symbol", "side", "setup_name", "scanner", "liquidity", "entry_reason", "qty", "entry",
             "stop", "risk_stop", "target", "planned_rr", "mfe_r", "mae_r", "risk_money", "entry_time", "breakeven",
             "locked", "trailing", "covered_until", "setup", "note"]
DECISION_COLS = ["time", "market", "symbol", "setup", "setup_name", "scanner", "liquidity", "result", "stopped_at_agent",
                 "category", "why", "price", "stop", "target", "stop_pct", "r_multiple", "fee_r", "vol", "own_setup"]


def _trades_csv(led):
    return _csv([_trade_row(c) for c in led.get("closed") or []], TRADE_COLS)


def _decision_rows():
    try:
        import dashboard_push as D
        cat = D.category
    except Exception:
        cat = lambda res, why: res or "?"
    out = []
    try:
        with open(os.path.join(LIVE, "decisions.jsonl"), encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                st = r.get("steps") or {}
                sc = st.get("1_scanner") if isinstance(st.get("1_scanner"), dict) else {}
                ex = st.get("4_exit") if isinstance(st.get("4_exit"), dict) else {}
                en = st.get("3_entry") if isinstance(st.get("3_entry"), dict) else {}
                n = _stopped_at(r)
                out.append({"time": r.get("time"), "market": (r.get("symbol") or ":").split(":")[0],
                            "symbol": r.get("symbol"), "setup": r.get("setup"),
                            "setup_name": sc.get("setup_name") or _setup_label(r), "scanner": sc.get("scanner"),
                            "liquidity": sc.get("liquidity") or (
                                "swept %s %s" % (sc.get("liquidity_swept") or "level", sc.get("level"))
                                if sc.get("level") is not None else None),
                            "result": r.get("result"),
                            "stopped_at_agent": "" if n is None else "%d %s" % (n, dict((a[0], a[2]) for a in AGENTS).get(n, "")),
                            "category": cat(r.get("result"), r.get("why")), "why": r.get("why"),
                            "price": en.get("price_now") or ex.get("entry") or sc.get("price") or sc.get("close"),
                            "stop": ex.get("stop"), "target": ex.get("target"), "stop_pct": ex.get("stop_pct"),
                            "r_multiple": ex.get("r_multiple"), "fee_r": ex.get("fee_r"),
                            "vol": sc.get("vol_ratio") if sc.get("vol_ratio") is not None else sc.get("vol_x_recent"),
                            "own_setup": "yes" if (r.get("scanner_v2") or r.get("record_only")) else ""})
    except OSError:
        pass
    return out


def _agg(trades):
    x = {"trades": len(trades), "wins": sum(1 for c in trades if (c.get("pnl") or 0) > 0)}
    x["win_rate"] = round(x["wins"] / x["trades"], 3) if trades else None
    x["pnl"] = round(sum(c.get("pnl") or 0 for c in trades), 2)
    x["total_r"] = round(sum(c.get("r") or 0 for c in trades), 2)
    x["avg_r"] = round(x["total_r"] / len(trades), 3) if trades else None
    x["best_r"] = max((c.get("r") or 0 for c in trades), default=None)
    x["worst_r"] = min((c.get("r") or 0 for c in trades), default=None)
    return x


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def _group(trades, key):
    g = {}
    for c in trades:
        g.setdefault(key(c), []).append(c)
    return {k: _agg(v) for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))}


def _daily_rows(trades):
    rows = []
    for (day, acct), v in sorted(_group(trades, lambda c: (c.get("exit_date"), _ACCT.get(c.get("market"), c.get("market")))).items(),
                                 key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        rows.append(dict(v, day=day, account=acct))
    return rows


def _summary(led, decisions=None):
    """Totals for the analyst: closed trades by setup / scanner version / market / side / exit reason / day, open
    positions, accounts, and every decision by result, reason, agent that stopped it and day."""
    closed = led.get("closed") or []
    decisions = decisions if decisions is not None else _decision_rows()
    dec = {"by_result": {}, "by_reason": {}, "by_stopped_at_agent": {}, "by_setup_and_result": {}, "by_day": {}}
    for d in decisions:
        res, day = d.get("result") or "?", (d.get("time") or "")[:10]
        for k, v in (("by_result", res), ("by_reason", "%s | %s" % (d["market"], d["category"])),
                     ("by_stopped_at_agent", d["stopped_at_agent"] or "traded"),
                     ("by_setup_and_result", "%s | %s" % (d.get("setup_name") or d.get("setup"), res))):
            dec[k][v] = dec[k].get(v, 0) + 1
        dd = dec["by_day"].setdefault(day, {})
        dd[res] = dd.get(res, 0) + 1
    return {"closed_all": _agg(closed),
            "closed_by_setup": _group(closed, _setup_of),
            "closed_by_scanner_version": _group(closed, _scanner_of),
            "closed_by_market_setup_side": _group(closed, lambda c: "%s | %s | %s" % (
                c.get("market"), _setup_of(c), c.get("side") or "long")),
            "closed_by_exit_reason": _group(closed, lambda c: c.get("reason") or "?"),
            # the owner's goal 2 (minimize losses): losers that had been at least +1R in profit first, and how far
            # the winners / losers went on average (mfe / mae, recorded from 7 Nov 2026)
            "losers_that_were_winning": {
                "count": sum(1 for c in closed if (c.get("pnl") or 0) < 0 and (c.get("mfe_r") or 0) >= 1),
                "of_losers_with_mfe": sum(1 for c in closed if (c.get("pnl") or 0) < 0 and c.get("mfe_r") is not None)},
            "avg_mfe_r_winners": _avg([c.get("mfe_r") for c in closed if (c.get("pnl") or 0) > 0]),
            "avg_mae_r_winners": _avg([c.get("mae_r") for c in closed if (c.get("pnl") or 0) > 0]),
            "avg_mfe_r_losers": _avg([c.get("mfe_r") for c in closed if (c.get("pnl") or 0) <= 0]),
            "closed_by_day": _group(closed, lambda c: c.get("exit_date") or "?"),
            "open_positions": len(led.get("open") or []), "accounts": led.get("accounts"), "decisions": dec}


@router.get("/download/{name}")
def download(name: str):
    if name == "all.zip":
        return _download_all()
    if name == "trades.csv":
        led = _read_json(LEDGER, {"closed": []})
        return Response(_trades_csv(led), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=paper_trades.csv"})
    path = DOWNLOADS.get(name)
    if not path:
        raise HTTPException(404, "unknown file")
    if not os.path.exists(path):
        raise HTTPException(404, "%s does not exist yet" % name)
    return FileResponse(path, filename=name)


# Files that never go into the export: secrets (Telegram token, the day's Zerodha access token) and bulky caches.
_EXPORT_SKIP = {"alerts.json", "kite_session.json", "kite_session.json.tmp"}


def _download_all():
    """Everything the bot knows, in one zip, for review: ledger, trades, decisions, logs, rules, state,
    coin profiles, backtest reports. No secrets: alerts.json (Telegram token) and kite_session.json (Zerodha access
    token) are left out, and the dashboard
    password lives outside the app folder (/etc/trader/trader.env) and is never read here."""
    import zipfile
    now = _now()
    led = _read_json(LEDGER, {"accounts": {}, "open": [], "closed": []})
    mem = io.BytesIO()
    added = []
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        def add_file(path, arc):
            if os.path.isfile(path) and os.path.basename(path) not in _EXPORT_SKIP:
                z.write(path, arc)
                added.append((arc, os.path.getsize(path)))

        for name in sorted(os.listdir(LIVE)) if os.path.isdir(LIVE) else []:
            if name.endswith((".json", ".jsonl", ".txt")) and not name.endswith(".tmp"):
                add_file(os.path.join(LIVE, name), "live/" + name)
            elif ".bak" in name:
                add_file(os.path.join(LIVE, name), "live/" + name)
        add_file(LEDGER, "paper/ledger.json")
        add_file(PAPER_CFG, "paper/config.json")
        add_file(UNIVERSE, "universe_crypto.txt")
        add_file(PREFS, "dashboard_prefs.json")
        rdir = os.path.join(T, "research")
        if os.path.isdir(rdir):
            for name in sorted(os.listdir(rdir)):
                if name.startswith("report_") and name.endswith(".txt"):
                    add_file(os.path.join(rdir, name), "research/" + name)
        if os.path.isdir(JOBS):
            for name in sorted(os.listdir(JOBS)):
                if name.endswith((".log", ".json")):
                    add_file(os.path.join(JOBS, name), "research/jobs/" + name)
        decisions = _decision_rows()
        closed = led.get("closed") or []
        z.writestr("trades.csv", _trades_csv(led))
        z.writestr("open_positions.csv", _csv([_trade_row(p, closed=False) for p in led.get("open") or []], OPEN_COLS))
        z.writestr("decisions.csv", _csv(decisions, DECISION_COLS))
        z.writestr("daily_summary.csv", _csv(_daily_rows(closed), ["day", "account", "trades", "wins", "win_rate",
                                                                   "pnl", "total_r", "avg_r", "best_r", "worst_r"]))
        summary = _summary(led, decisions)
        z.writestr("summary.json", json.dumps(summary, indent=1, default=str))
        made = ["trades.csv", "open_positions.csv", "decisions.csv", "daily_summary.csv", "summary.json"]
        state = _read_json(os.path.join(LIVE, "state.json"), {})
        readme = [
            "Trader bot export, %s IST" % now.strftime("%Y-%m-%d %H:%M"),
            "Host %s. Paper trading only. Runner status: %s." % (
                os.uname().nodename if hasattr(os, "uname") else "?", state.get("status")),
            "",
            "Scanner version per account: %s." % ", ".join(
                "%s %s" % (k, (v or {}).get("scanner_version", "v3")) for k, v in
                (_paper_cfg().get("accounts") or {}).items()),
            "",
            "trades.csv          every closed paper trade, one row each (mfe_r / mae_r: how far it went for /",
            "                    against it in R, recorded by the Trade Manager from 7 Nov 2026):",
            "                    setup_name / scanner (v3, v2, rules = the 4h breakout / ORB / SMC rules, manual),",
            "                    liquidity (the level swept or the zone retested), entry_reason, planned_rr,",
            "                    exit_reason, result, pnl, r, risk_money, fees, held_minutes",
            "open_positions.csv  open paper trades with the same setup / liquidity / risk columns",
            "decisions.csv       every candidate from decisions.jsonl flattened: setup, liquidity, result, the agent",
            "                    that stopped it (stopped_at_agent), reason, price / stop / target, R multiple, fee R",
            "daily_summary.csv   per day and account: trades, wins, win rate, P&L, total / average / best / worst R",
            "summary.json        totals: closed trades by setup, scanner version, market | setup | side, exit reason",
            "                    and day; decisions by result, reason, stopping agent, setup and day",
            "paper/          ledger.json (accounts, open and closed trades), config.json (risk limits, fees)",
            "live/           decisions.jsonl (every candidate and why), log.txt (runner log), state.json,",
            "                auto_*config.json (rules per market), coin_profiles.json, control.json, backups",
            "research/       backtest reports and job logs",
            "",
            "Left out on purpose: alerts.json (Telegram token); the dashboard password is not in the app folder.",
            "",
            "Files:",
        ] + ["  %-48s %10s bytes" % (a, "{:,}".format(s)) for a, s in added]
        z.writestr("README.txt", "\n".join(readme) + "\n")
    audit("export: all data downloaded (%d files)" % (len(added) + len(made) + 1))
    fname = "trader-export-%s.zip" % now.strftime("%Y%m%d-%H%M")
    return Response(mem.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=%s" % fname})


# ------------------------------------------------------------------ agents (the day-trader skill pipeline)
# The 11 agents of the day-trader skill run inside the runner as steps of one pipeline (auto_crypto.py and its
# NSE/F&O/US twins). Each candidate goes through them in order and stops at the first that says no; every
# verdict lands in trader/live/decisions.jsonl. This endpoint turns that file, the runner state and the open
# paper positions into "which agent is working, and on what".

AGENTS = [
    (1, "scanner", "Scanner v3", "trader-scanner"),
    (2, "news", "News", "trader-news"),
    (3, "entry", "Entry", "trader-entry"),
    (4, "exit", "Exit", "trader-exit"),
    (5, "timemachine", "Time machine", "trader-timemachine"),
    (6, "budget", "Budget", "trader-budget"),
    (7, "risk", "Risk", "trader-risk"),
    (8, "broker", "Broker (paper)", "trader-broker"),
    (9, "trade_manager", "Trade Manager", "trader-alerts"),
    (10, "analyst", "Analyst", "trader-analyst"),
    (11, "pelosi", "Pelosi tracker", "trader-pelosi"),
]
# which agent said no, by the words of its reason (first match wins)
_STOP_WORDS = [
    ("time machine", 5),
    ("playbook: target only", 4), ("liquidity left", 4), ("playbook:", 3), ("setup cancelled", 3),
    ("4h range", 3), ("downtrend", 3), ("tight ranges", 3),
    ("fees eat", 4), ("stop too tight", 4), ("atr stop", 4),
    ("past the stop", 3), ("thin hours", 3), ("chasing", 3), ("moved back", 3), ("fell back", 3),
    ("reversed", 3), ("no live price", 3),
    ("volume", 3), ("regime", 3), ("triggered", 3), ("opened ", 3), ("older than", 3),
    ("lots fit", 6), ("units fit", 6), ("budget", 6),
    ("risk", 7), ("daily loss limit", 7), ("weekly loss limit", 7), ("cooldown", 7), ("max ", 7), ("block", 7),
]
_MKT = {"CRYPTO": "CRYPTO", "NSE": "NSE", "BSE": "NSE", "NFO": "FNO", "US": "US"}


def _tail_lines(path, max_bytes=3_000_000):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = raw.splitlines()
    return lines[1:] if size > max_bytes else lines


def _step_no(key):
    m = re.match(r"(\d+)", key)
    return int(m.group(1)) if m else 0


def _stopped_at(rec):
    """None if the candidate was traded, else the number of the agent that stopped it."""
    res = (rec.get("result") or "").upper()
    if res.startswith("PAPER"):
        return None
    if res == "LOG ONLY":   # passed every agent; the broker only recorded it
        return 8
    if res == "BLOCKED":
        return 7
    why = (rec.get("why") or "").lower()
    for word, n in _STOP_WORDS:
        if word in why:
            return n
    done = [_step_no(k) for k in (rec.get("steps") or {}) if 0 < _step_no(k) < 10]
    return min(max(done or [1]) + 1, 8)


def _fmt(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    return ("%.6g" % x) if abs(x) < 1000 else ("%.2f" % x)


def _step_detail(n, rec):
    """One line on what agent n found for this candidate (when it said yes)."""
    st = rec.get("steps") or {}
    sym = (rec.get("symbol") or "").split(":")[-1]
    get = lambda pre: next((v for k, v in st.items() if k.startswith(pre)), None)
    s = get("%d_" % n) if n not in (6, 7, 8) else (get("6-8") or get("%d_" % n))
    if n == 1 and isinstance(s, dict) and s.get("scanner") in ("v2", "v3"):
        return "%s: %s at %s" % (sym, s.get("setup_name") or s.get("setup"), _fmt(s.get("price")))
    if n == 1 and isinstance(s, dict):
        px = s.get("close") or s.get("price")
        vol = s.get("vol_ratio")
        return "%s broke out%s%s" % (sym, " at %s" % _fmt(px) if px is not None else "", " (volume %sx)" % vol if vol else "")
    if n == 2:
        if isinstance(s, list) and s:
            first = s[0].get("title") if isinstance(s[0], dict) else str(s[0])
            return "%s: %d headlines, latest \"%s\"" % (sym, len(s), (first or "")[:90])
        return "%s: %s" % (sym, s if isinstance(s, str) else "no headlines")
    if n == 3 and isinstance(s, dict):
        ch = s.get("chase_r")
        return "%s at %s, %s" % (sym, _fmt(s.get("price_now") or s.get("index_now") or s.get("price")),
                                 "%sR past the trigger" % ch if ch is not None else "timing ok")
    if n == 4 and isinstance(s, dict):
        fee = s.get("fee_r", s.get("charges_r"))
        return "%s stop %s (%s%% away)%s" % (sym, _fmt(s.get("stop") or s.get("index_stop")), s.get("stop_pct", "?"),
                                            ", fees %sR" % fee if fee is not None else "")
    if n == 5 and isinstance(s, dict):
        sim = s.get("sim") or s.get("replay") or {}
        hist = s.get("history") or {}
        out = "%s replays avg %+.2fR" % (sym, sim.get("avg_r", 0)) if isinstance(sim, dict) and "avg_r" in sim else sym
        if isinstance(hist, dict) and hist.get("fired"):
            out += ", rule fired %d times avg %+.2fR" % (hist["fired"], hist.get("avg_r", 0))
        return out + " (recorded, not a gate)"
    if n in (6, 7, 8) and isinstance(s, dict):
        return "%s: %s, qty %s, max loss %s" % (sym, s.get("verdict", "pass"), _fmt(s.get("qty")), _fmt(s.get("max_loss")))
    if n == 9 and s:
        return "%s: %s" % (sym, s if isinstance(s, str) else "watching")
    return "%s passed" % sym


_SETUP_NAMES = {"range_breakout_4h": "4h breakout", "range_breakdown_4h": "4h breakdown", "orb": "ORB",
                "orb_short": "ORB short", "smc_sweep_long": "SMC sweep long", "smc_sweep_short": "SMC sweep short"}


def _setup_label(rec):
    """The setup name shown with a candidate: the Scanner's own name (v2 / v3 / v4), else a short name of the rule."""
    s1 = (rec.get("steps") or {}).get("1_scanner")
    if isinstance(s1, dict) and s1.get("setup_name"):
        return s1["setup_name"]
    setup = rec.get("setup") or ""
    if setup.startswith(("v3_", "v4_", "v5_")):
        return "%s %s" % (setup[:2], setup[3:].replace("_", " "))
    if setup.startswith("smcp_"):
        return "Playbook %s" % setup[5:].replace("_", " ")
    return _SETUP_NAMES.get(setup, setup.replace("_", " "))


def _iso_age(iso, now):
    try:
        return (now - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return None


@router.get("/setups")
def setups(limit: int = 300):
    """The owner's setups found by the Scanner (v2) on every market and taken through the agents (paper traded while
    testing, or recorded when an account's trade_setups is off): newest first + today's counts by market."""
    rows = []
    for ln in _tail_lines(os.path.join(LIVE, "decisions.jsonl")):
        if '"scanner_v2"' not in ln and '"record_only"' not in ln:
            continue
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        s1 = (r.get("steps") or {}).get("1_scanner") or {}
        ex = (r.get("steps") or {}).get("4_exit") or {}
        mkt, _, sym = (r.get("symbol") or "").partition(":")
        rows.append({"time": r.get("time"), "market": mkt, "symbol": sym, "setup": r.get("setup"),
                     "name": s1.get("setup_name") or r.get("setup"), "side": s1.get("side"), "bar_end": s1.get("bar_end"),
                     "price": s1.get("price"), "stop": ex.get("stop"), "target_2r": ex.get("target"),
                     "result": r.get("result"), "why": r.get("why"),
                     "details": {k: v for k, v in s1.items() if k not in ("scanner", "setup", "setup_name", "side",
                                                                          "bar_end", "price")}})
    today = _now().astimezone(IST).date().isoformat()
    counts = {}
    for r in rows:
        if (r.get("time") or "")[:10] == today:
            counts[r["market"]] = counts.get(r["market"], 0) + 1
    rows.reverse()
    return {"generated_at": _now().isoformat(), "today": counts, "latest": rows[:max(1, min(limit, 1000))]}


def _tm_state(p):
    if p.get("pdf_only"):
        return "v4: PDF exits only"
    if p.get("trail_k"):
        return "trailing" if p.get("trailing") else "trailing exit"
    return "profit locked" if p.get("locked") else "breakeven" if p.get("breakeven") else "watching"


def _tm_status(led, openpos, now):
    """The Trade Manager agent's card: what it is watching now and what it did today."""
    today = now.astimezone(IST).date()

    def day_of(x):
        try:
            return datetime.fromisoformat(x.get("t") or "").astimezone(IST).date()
        except ValueError:
            return None
    acts = [dict(x, symbol=p.get("symbol")) for p in (led.get("open") or []) + (led.get("closed") or [])
            for x in (p.get("tm_log") or []) if day_of(x) == today]
    acts.sort(key=lambda x: x["t"])
    count = {"breakeven": 0, "profit lock": 0, "exit": 0}
    for x in acts:
        for k in count:
            if x["text"].startswith(k) or (k == "exit" and "hit at" in x["text"]):
                count[k] += 1
                break
    watch = [{"symbol": p.get("symbol"), "market": p.get("market"), "side": p.get("side") or "long",
              "state": _tm_state(p), "best_r": p.get("mfe_r"), "stop": p.get("stop")} for p in openpos]
    out = {"tm": {"watching": watch, "today": count, "last": acts[-5:][::-1]}}
    if openpos:
        bits = ", ".join("%s %s%s" % (w["symbol"], w["state"], " (best +%.1fR)" % w["best_r"] if w["best_r"] else "")
                         for w in watch[:5])
        out.update(status="active", now="Watching %d open trade%s: %s%s. Today: %d breakeven, %d profit locks, %d exits." % (
            len(openpos), "" if len(openpos) == 1 else "s", bits, " ..." if len(watch) > 5 else "",
            count["breakeven"], count["profit lock"], count["exit"]))
    else:
        out.update(status="standby", now="No open trade to manage. Today: %d breakeven, %d profit locks, %d exits." % (
            count["breakeven"], count["profit lock"], count["exit"]))
    return out


@router.get("/agents")
def agents():
    now = _now()
    state = _read_json(os.path.join(LIVE, "state.json"), {})
    cfg = _rule_defaults()
    cfg.update(_read_json(RULES, {}))
    led = _read_json(LEDGER, {"open": []})
    alive = _proc_alive(state.get("pid"))
    upd_age = _iso_age(state.get("updated"), now)
    running = alive if alive is not None else (upd_age is not None and upd_age < 15 * 60)
    status_txt = state.get("status") or ""
    if status_txt.startswith("stopped"):
        running = False
    markets = state.get("markets_scanned") or state.get("markets_started") or []

    recs = []
    for ln in _tail_lines(os.path.join(LIVE, "decisions.jsonl")):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("time"):
            r["_stop"] = _stopped_at(r)
            recs.append(r)
    today = now.date().isoformat()
    todays = [r for r in recs if r["time"][:10] == today]

    def reached(r, n):
        s = r["_stop"]
        return n <= 9 if s is None else n <= s

    # thin hours right now?
    utc_h = now.astimezone(timezone.utc).hour
    thin = utc_h in (cfg.get("skip_hours_utc") or [])
    thin_end = None
    if thin:
        h = utc_h
        while h in cfg["skip_hours_utc"] and h < 24:
            h += 1
        end = now.astimezone(timezone.utc).replace(hour=h % 24, minute=0, second=0, microsecond=0)
        thin_end = end.astimezone(IST).strftime("%H:%M")

    # what the scanner is looking at
    scans = []
    for m in markets:
        ms = (state.get("markets") or {}).get(m) or {}
        res = ms.get("intraday") if m == "CRYPTO" else ms.get("orb")
        if not res:
            continue
        hits = res.get("hits") or []
        scans.append({"market": m, "as_of": res.get("as_of"), "scanned": res.get("scanned"), "usable": res.get("usable"),
                      "hits": len(hits) if m != "CRYPTO" else sum(1 for h in hits if h.get("setup") == "range_breakout_4h"),
                      "new": sum(1 for h in hits if h.get("new")), "tf": ms.get("timeframe", 15)})

    openpos = led.get("open") or []
    stop_k = cfg.get("stop_atr_k", 1.5)
    jobs = {
        1: "Every market, on each candle that closes. The rules that trade: a crypto coin's fresh close above its "
           "4-hour high (below its low for shorts), NSE / US opening-range breaks (these run ONLY when Scanner version is 'rules'). "
           "Your setups, one scanner version per account (Settings: Scanner version), never mixed. v5 = the 0.146 "
           "level: after a move, the level C x range short of its extreme (C = 0.146), touched and closed back on the "
           "right side, stop beyond the extreme, target the other end of the move. v4 = your revised v4 PDF (11 Nov) only: a primary trade (BOS, a "
           "sweep of an old low / high that is reclaimed, a doji or inverted hammer at a low (BUY) / a doji or hammer at a "
           "high (SELL), a break-and-close of the signal candle, entry at the next open), then - only after it closed - one OB / FVG secondary (the zone tapped, then a "
           "break-and-close). v4 skips trades against the 1-hour trend, BOS out of chop or on a weak candle, and "
           "entries with an opposing zone within 1R. v3 = your 5 Nov workflow only: sweep reversal (BOS, a close "
           "below / above the swept swing, doji or (inverted) hammer, a close past the trigger within 2 candles) and its "
           "FVG / order-block retest. v2 = A-B-C-D, the SMC playbook's doji / bottom star / top hammer and FVG / "
           "order-block retests. They go through the same agents and, while paper testing, the broker paper trades "
           "them; every trade records its setup and the liquidity it used.",
        2: "Pulls the coin's latest headlines for the record. It never blocks or makes a trade.",
        3: "Is the timing right? Skips thin hours (%s), a price back inside the range, volume under %sx the 4h "
           "average%s%s." % ("%s:00-%s:00 UTC" % (cfg["skip_hours_utc"][0], cfg["skip_hours_utc"][-1] + 1)
                             if cfg.get("skip_hours_utc") else "none", cfg.get("min_vol_x", 0),
                             ", BTC below its 4h midpoint" if cfg.get("btc_regime") else "",
                             ", a chase past %sR" % cfg["max_chase_r"] if cfg.get("max_chase_r") else ""),
        4: "Sets the stop (%s) and the exit (%s); skips if fees would eat more than %sR. Then the Trade Manager "
           "watches every open trade with a fixed target: stop to the entry at +1R, profit locked once 80%% of the "
           "way to the target is covered, out on a reversal candle near the high, out when a trade goes nowhere "
           "(Settings: Trade Manager)."
           % ("%s x ATR under the entry" % stop_k if cfg.get("stop") == "atr" else cfg.get("stop"),
              "trailing" if cfg.get("exit") == "trail" else "%sR target" % cfg.get("target_r"), cfg.get("max_fee_r")),
        5: "Replays the trade %s times on the coin's last %s days and counts past fires of the rule. Recorded only: "
           "it is not a gate." % (cfg.get("sim_paths"), cfg.get("history_days")),
        6: "Sizes the position so the loss at the stop fits your max loss per trade.",
        7: "Checks the daily loss limit, trades per day and the position cap before anything is bought.",
        8: "Fills the order on paper at the live price. No real broker is connected yet.",
        9: "Thinks about every open trade each check and reacts: stop to the entry at +1R, half the move locked once "
           "80%% of the way to the target is covered, out on a reversal candle near the high, out when a trade goes "
           "nowhere (60 min; crypto 4h). Crypto trailing exits keep their own break-even at +%sR and the %sh time "
           "stop. Every action is in the runner log (TRADE MANAGER: ...). Settings: Trade Manager."
           % (cfg.get("trail_arm_r", 1), cfg.get("max_hold_hours")),
        10: "Reads SEC filings for US stocks. Not used for crypto.",
        11: "Tracks US Congress stock trades. Not used for crypto.",
    }

    out = []
    try:
        _accs = _paper_cfg().get("accounts", {})
    except Exception:
        _accs = {}
    vers = {acc: (_accs.get(acc, {}).get("scanner_version") or "v3") for acc in ("CRYPTO", "INDIA", "US")}
    for n, key, name, skill in AGENTS:
        if n == 1:   # the Scanner's version per account (Settings > Risk limits; v2 = the rollback)
            u = sorted(set(vers.values()))
            name = "Scanner %s" % u[0] if len(u) == 1 else "Scanner (%s)" % ", ".join(
                "%s %s" % (k, v) for k, v in vers.items())
        a = {"n": n, "key": key, "name": name, "skill": skill, "job": jobs[n]}
        if n >= 10:
            a.update(status="n/a", now="Not part of the crypto pipeline" +
                     ("; for US stocks it runs by hand (us_flow.py)" if "US" in markets else "."))
            out.append(a)
            continue
        mine = [r for r in recs if reached(r, n)]
        tday = [r for r in todays if reached(r, n)]
        stopped = sum(1 for r in tday if r["_stop"] == n)
        a["today"] = {"checked": len(tday), "passed": len(tday) - stopped, "stopped": stopped}
        if mine:
            r = mine[-1]
            sym = (r.get("symbol") or "").split(":")[-1]
            a["last"] = {"time": r["time"], "symbol": sym, "market": _MKT.get((r.get("symbol") or "").split(":")[0], ""),
                         "verdict": "stopped" if r["_stop"] == n else ("traded" if n >= 8 else "passed"),
                         "text": ("%s: %s" % (sym, r.get("why")) if r["_stop"] == n else _step_detail(n, r))}
        # status now
        busy = bool(mine) and (_iso_age(mine[-1]["time"], now) or 1e9) < 180
        if not running:
            a.update(status="off", now="Runner is not running.")
        elif n == 1:
            def line(sc):
                at = datetime.fromisoformat(sc["as_of"]).astimezone(IST).strftime("%H:%M") if sc.get("as_of") else "?"
                if sc["market"] == "CRYPTO":
                    return "Crypto %sm candle %s: %s of %s coins usable, %d above the 4h high, %d new" % (
                        sc["tf"], at, sc["usable"], sc["scanned"], sc["hits"], sc["new"])
                return "%s opening range %s: %s of %s stocks usable, %d broke out, %d new" % (
                    sc["market"], at, sc["usable"], sc["scanned"], sc["hits"], sc["new"])
            v2 = [r for r in todays if r.get("scanner_v2") or r.get("record_only")]
            v2_line = ("your setups: %d today, last %s %s" % (
                len(v2), (v2[-1].get("symbol") or "").split(":")[-1], _setup_label(v2[-1]))
                if v2 else "your setups: none yet today")
            a.update(status="active", now="; ".join([line(sc) for sc in scans] + [v2_line]) if scans
                     else "Waiting for the next candle to close. " + v2_line)
            a["scans"] = scans
            a["v2_today"] = len(v2)
        elif n == 9:
            a.update(_tm_status(led, openpos, now))
        elif busy:
            a.update(status="working", now="Just checked %s." % mine[-1].get("symbol", "").split(":")[-1])
        elif n == 3 and thin and "CRYPTO" in markets:
            a.update(status="paused", now="Thin hours: crypto breakouts are skipped until %s IST." % thin_end)
        else:
            a.update(status="standby", now="Waiting for a candidate from the agent before it.")
        out.append(a)

    flow = []
    for r in recs[-15:][::-1]:
        s = r["_stop"]
        flow.append({"time": r["time"], "symbol": (r.get("symbol") or "").split(":")[-1], "setup": _setup_label(r),
                     "own": bool(r.get("scanner_v2") or r.get("record_only")),
                     "market": _MKT.get((r.get("symbol") or "").split(":")[0], ""), "result": r.get("result"),
                     "why": r.get("why"), "stopped_at": s,
                     "chain": ["pass" if (s is None or i < s) else
                               ("rec" if r.get("result") == "LOG ONLY" else "stop") if i == s else "none"
                               for i in range(1, 10)]})
    return {"generated_at": now.isoformat(), "running": running, "runner_status": status_txt,
            "next_run": state.get("next_run"), "markets": markets, "thin_hours_now": thin, "thin_until": thin_end,
            "agents": out, "flow": flow,
            "today": {"candidates": len(todays), "traded": sum(1 for r in todays if r["_stop"] is None)}}


# ------------------------------------------------------------------ India paper buys (forward test switch)
# NSE stocks (auto_nse.py) and Nifty/Bank Nifty F&O (auto_fno.py) are evaluated by the agents either way. With
# auto_buy off a candidate that passes every agent is only logged ("LOG ONLY"); with it on it is bought on paper.
# The code default stays off (the 31 Oct backtests found no edge after charges); this switch is a forward test.
AUTOBUY = {"NSE": ("auto_nse", os.path.join(LIVE, "auto_nse_config.json"), "auto_buy"),
           "FNO": ("auto_fno", os.path.join(LIVE, "auto_fno_config.json"), "auto_buy"),
           "US_SHORT": ("auto_us", os.path.join(LIVE, "auto_us_config.json"), "allow_short"),
           "NSE_SHORT": ("auto_nse", os.path.join(LIVE, "auto_nse_config.json"), "allow_short")}


def _autobuy_cfg(m):
    mod, path, _ = AUTOBUY[m]
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        cfg = dict(__import__(mod).DEFAULTS)
    except Exception:
        cfg = {}
    cfg.update(_read_json(path, {}))
    return cfg, path


@router.get("/autobuy")
def autobuy_get():
    out = {}
    for m in AUTOBUY:
        cfg, _ = _autobuy_cfg(m)
        out[m] = {"on": bool(cfg.get(AUTOBUY[m][2])), "entry_start": cfg.get("entry_start"), "entry_end": cfg.get("entry_end")}
    return out


@router.post("/autobuy")
async def autobuy_set(request: Request):
    body = await request.json()
    m, on = body.get("market"), bool(body.get("on"))
    if m not in AUTOBUY:
        raise HTTPException(400, "market must be NSE, FNO, US_SHORT or NSE_SHORT")
    cfg, path = _autobuy_cfg(m)
    k = AUTOBUY[m][2]
    if bool(cfg.get(k)) != on:
        cfg[k] = on
        cfg["_edited"] = "%s %s from the dashboard %s" % (k, "on" if on else "off", _now().strftime("%Y-%m-%d %H:%M"))
        _write_json(path, cfg)
        if m in ("US_SHORT", "NSE_SHORT"):
            audit("%s shorts %s (opening-range breakdowns, paper; not backtested)" % (m[:-6], "ON" if on else "off"))
            return {"ok": True, "market": m, "on": on}
        audit("%s paper buys %s%s" % (m, "ON (forward test: the backtest found no edge after charges)" if on else "off",
                                      "" if not on else "; entries %s-%s IST" % (cfg.get("entry_start"), cfg.get("entry_end"))))
    return {"ok": True, "market": m, "on": on}
