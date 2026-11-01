"""
alerts.py - phone alerts through a Telegram bot, so you hear about trades and problems without opening the
dashboard. Configured from the dashboard (Alerts section); stored in trader/alerts.json:

    {"enabled": true, "telegram_token": "123:ABC...", "telegram_chat_id": "123456",
     "on": {"trades": true, "errors": true, "runner": true, "daily": true}}

Setup: in Telegram open @BotFather -> /newbot -> copy the token. Send any message to your new bot, then the
dashboard's "Find my chat id" fills in the chat id.

The runner calls notify_cycle() after every cycle: it compares the paper ledger with the previous cycle and
sends one message per opened or closed trade, new errors (each at most once an hour) and a daily summary.
Alerts never stop the runner: every failure is swallowed.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

CFG = os.path.join("trader", "alerts.json")
STATE = os.path.join("trader", "live", "alerts_state.json")
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT = {"enabled": False, "telegram_token": "", "telegram_chat_id": "",
           "on": {"trades": True, "errors": True, "runner": True, "daily": True}}


def load_cfg(path=CFG):
    c = json.loads(json.dumps(DEFAULT))
    try:
        with open(path, encoding="utf-8") as fh:
            got = json.load(fh)
        c.update({k: v for k, v in got.items() if k != "on"})
        c["on"].update(got.get("on") or {})
    except Exception:
        pass
    return c


def telegram(token, chat_id, text, timeout=10):
    """Send one message. Returns (ok, detail)."""
    url = "https://api.telegram.org/bot%s/sendMessage" % token
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:4000],
                                   "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST"), timeout=timeout) as r:
            out = json.loads(r.read() or b"{}")
        return bool(out.get("ok")), out.get("description") or "sent"
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read()).get("description") or str(e)
        except Exception:
            return False, str(e)
    except Exception as e:
        return False, str(e)


def find_chat_id(token, timeout=10):
    """The chat id of the last person who messaged the bot (getUpdates)."""
    try:
        with urllib.request.urlopen("https://api.telegram.org/bot%s/getUpdates" % token, timeout=timeout) as r:
            out = json.loads(r.read() or b"{}")
    except Exception as e:
        return None, str(e)
    for u in reversed(out.get("result") or []):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            return str(chat["id"]), chat.get("first_name") or chat.get("title") or ""
    return None, "no messages yet: send any message to your bot in Telegram, then try again"


def send(kind, text, cfg=None):
    cfg = cfg or load_cfg()
    if not cfg.get("enabled") or not cfg.get("telegram_token") or not cfg.get("telegram_chat_id"):
        return False
    if not (cfg.get("on") or {}).get(kind, True):
        return False
    return telegram(cfg["telegram_token"], cfg["telegram_chat_id"], text)[0]


def _load_state():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(st, fh)
    except Exception:
        pass


def _cur(m):
    return "Rs " if m in ("NSE", "BSE", "NFO") else "$"


def notify_cycle(state, ledger_path=os.path.join("trader", "paper", "ledger.json")):
    """Called by live.py after every cycle. Never raises."""
    try:
        cfg = load_cfg()
        if not cfg.get("enabled"):
            return
        st = _load_state()
        try:
            with open(ledger_path, encoding="utf-8") as fh:
                led = json.load(fh)
        except Exception:
            led = {"open": [], "closed": []}
        open_keys = {p["key"]: p for p in led.get("open") or []}
        closed = led.get("closed") or []
        first = "open_keys" not in st
        if not first:
            for k, p in open_keys.items():
                if k not in st["open_keys"]:
                    send("trades", "OPENED %s %s\nentry %s  stop %s  target %s\nqty %s (paper)"
                         % (p.get("side", "long").upper(), k, p.get("entry"), p.get("stop"), p.get("target"),
                            p.get("qty")), cfg)
            for c in closed[st.get("closed_n", len(closed)):]:
                send("trades", "CLOSED %s (%s)\n%s -> %s\nP&L %s%.2f = %+.2fR (paper)"
                     % (c.get("key"), c.get("reason"), c.get("entry"), c.get("exit"), _cur(c.get("market")),
                        c.get("pnl") or 0, c.get("r") or 0), cfg)
        st["open_keys"] = list(open_keys)
        st["closed_n"] = len(closed)
        # errors, each distinct one at most once an hour
        sent = st.get("errors_sent") or {}
        now = time.time()
        for e in state.get("errors") or []:
            key = str(e)[:200]
            if now - sent.get(key, 0) > 3600:
                send("errors", "Runner error: %s" % key, cfg)
                sent[key] = now
        st["errors_sent"] = {k: v for k, v in sent.items() if now - v < 86400}
        # daily summary once, after 23:30 IST
        ist = datetime.now(IST)
        today = ist.date().isoformat()
        if ist.hour == 23 and ist.minute >= 30 and st.get("daily_sent") != today:
            todays = [c for c in closed if c.get("exit_date") == today]
            by = {}
            for c in todays:
                acc = "INDIA" if c.get("market") in ("NSE", "BSE", "NFO") else c.get("market")
                by.setdefault(acc, [0, 0.0])
                by[acc][0] += 1
                by[acc][1] += c.get("pnl") or 0
            lines = ["Daily summary %s (paper)" % today, "open positions: %d" % len(open_keys)]
            lines += ["%s: %d trades, P&L %s%.2f" % (a, n, _cur("NSE" if a == "INDIA" else a), p)
                      for a, (n, p) in sorted(by.items())] or ["no trades closed today"]
            send("daily", "\n".join(lines), cfg)
            st["daily_sent"] = today
        _save_state(st)
    except Exception:
        pass
