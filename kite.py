#!/usr/bin/env python3
"""
kite.py - Zerodha Kite Connect as a DATA source for the Indian market (NSE / NFO). Read only: it can NOT place,
modify or cancel an order. Paper trading stays in paper.py.

What it does
  login_url() / exchange(request_token)   the daily login (Kite tokens expire every morning at ~6:00 IST)
  ltp(keys)                               live prices for paper keys ("NSE:RELIANCE", "NFO:NIFTY-20261117-25500-CE")
  minutes(key, start, end)                1-minute candles (intrabar stop / target checks)
  resolve(key)                            paper key -> Kite instrument (token, tradingsymbol, lot size, expiry)

Safety: every request goes through _call(), which only allows the read-only endpoints in ALLOWED (plus the login
exchange). Orders, GTT, positions conversion, mutual funds: refused before anything is sent, whatever the caller
asks. tests/test_kite.py checks this.

Keys: KITE_API_KEY and KITE_API_SECRET from the environment (/etc/trader/trader.env on the VPS). Never in the
repo, the logs or the dashboard. The day's access token is kept in trader/live/kite_session.json (mode 600).

    python kite.py status
    python kite.py ltp NSE:RELIANCE NSE:NIFTY50 NFO:NIFTY-20261117-25500-CE
"""
import csv
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
API = "https://api.kite.trade"
LOGIN = "https://kite.zerodha.com/connect/login?v=3&api_key=%s"
LIVE_DIR = os.path.join("trader", "live")
SESSION_FILE = os.path.join(LIVE_DIR, "kite_session.json")
INSTR_DIR = os.path.join(LIVE_DIR, "kite_instruments")

# the only endpoints this module may call (method, path regex). Nothing that trades is here.
ALLOWED = [
    ("GET", r"/quote"),
    ("GET", r"/quote/ltp"),
    ("GET", r"/quote/ohlc"),
    ("GET", r"/instruments/(NSE|NFO|BSE|BFO)"),
    ("GET", r"/instruments/historical/\d+/(minute|3minute|5minute|15minute|60minute|day)"),
    ("GET", r"/user/profile"),
    ("POST", r"/session/token"),          # the daily login: request_token -> access_token
]

# paper names for the indices -> Kite (exchange, tradingsymbol)
INDEX = {"NIFTY50": ("NSE", "NIFTY 50"), "NIFTY": ("NSE", "NIFTY 50"), "BANKNIFTY": ("NSE", "NIFTY BANK"),
         "NIFTYBANK": ("NSE", "NIFTY BANK"), "FINNIFTY": ("NSE", "NIFTY FIN SERVICE"),
         "INDIAVIX": ("NSE", "INDIA VIX"), "NIFTYENERGY": ("NSE", "NIFTY ENERGY"),
         "NIFTYFIN": ("NSE", "NIFTY FIN SERVICE"), "NIFTYFMCG": ("NSE", "NIFTY FMCG"),
         "NIFTYINFRA": ("NSE", "NIFTY INFRA"), "NIFTYREALTY": ("NSE", "NIFTY REALTY"),
         "NIFTYAUTO": ("NSE", "NIFTY AUTO"), "NIFTYIT": ("NSE", "NIFTY IT"), "NIFTYMETAL": ("NSE", "NIFTY METAL"),
         "NIFTYPHARMA": ("NSE", "NIFTY PHARMA"), "NIFTYPSE": ("NSE", "NIFTY PSE")}

# the index watch list: always streamed by kite_ticker.py and shown live on the dashboard (owner, 10 Nov 2026:
# Bank Nifty and the CNX sector indices; NSE renamed "CNX ..." to "NIFTY ...")
WATCH_INDICES = [("NSE:NIFTY50", "Nifty 50"), ("NSE:BANKNIFTY", "Bank Nifty"), ("NSE:INDIAVIX", "India VIX"),
                 ("NSE:NIFTYENERGY", "Energy"), ("NSE:NIFTYFIN", "Finance"), ("NSE:NIFTYFMCG", "FMCG"),
                 ("NSE:NIFTYINFRA", "Infra"), ("NSE:NIFTYREALTY", "Realty"), ("NSE:NIFTYAUTO", "Auto"),
                 ("NSE:NIFTYIT", "IT"), ("NSE:NIFTYMETAL", "Metal"), ("NSE:NIFTYPHARMA", "Pharma"),
                 ("NSE:NIFTYPSE", "PSE")]


class KiteError(Exception):
    pass


class KiteBlocked(KiteError):
    """A request outside ALLOWED (an order, say). Never sent."""


class KiteAuth(KiteError):
    """No valid session today: log in from the dashboard (Control: Connect Zerodha)."""


# ------------------------------------------------------------------ keys and session

def keys():
    return os.environ.get("KITE_API_KEY", "").strip(), os.environ.get("KITE_API_SECRET", "").strip()


def configured():
    k, s = keys()
    return bool(k and s)


def login_url():
    k, _ = keys()
    if not k:
        raise KiteError("KITE_API_KEY is not set (add it to /etc/trader/trader.env)")
    return LOGIN % urllib.parse.quote(k)


def _expiry_after(login_utc):
    """Kite access tokens die at ~6:00 IST the next morning (or this morning's 6:00 if logged in before it)."""
    loc = login_utc.astimezone(IST)
    six = loc.replace(hour=6, minute=0, second=0, microsecond=0)
    if loc >= six:
        six += timedelta(days=1)
    return six.astimezone(timezone.utc)


def load_session():
    try:
        with open(SESSION_FILE, encoding="utf-8") as fh:
            s = json.load(fh)
    except (FileNotFoundError, ValueError):
        return None
    try:
        if datetime.now(timezone.utc) >= datetime.fromisoformat(s["expires"]):
            return None
    except (KeyError, ValueError):
        return None
    return s if s.get("access_token") else None


def _save_session(s):
    os.makedirs(LIVE_DIR, exist_ok=True)
    tmp = SESSION_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(s, fh)
    os.replace(tmp, SESSION_FILE)


def forget_session():
    try:
        os.remove(SESSION_FILE)
    except FileNotFoundError:
        pass


def connected():
    return configured() and load_session() is not None


def status():
    """For the dashboard: never includes a key or a token."""
    s = load_session()
    return {"configured": configured(), "connected": s is not None,
            "user": (s or {}).get("user_id"), "since": (s or {}).get("login_time"),
            "expires": (s or {}).get("expires"), "orders": "blocked (data only)"}


# ------------------------------------------------------------------ requests

_LIMITS = {"quote": 1.0, "historical": 0.34, "other": 0.34}   # Kite: quote 1/s, historical 3/s
_last = {}
_lock = threading.Lock()


def _allowed(method, path):
    return any(method == m and re.fullmatch(rx, path) for m, rx in ALLOWED)


def _call(method, path, params=None, data=None, auth=True, timeout=10, raw=False):
    if not _allowed(method, path):
        raise KiteBlocked("blocked: %s %s is not a read-only data endpoint (this bot never sends orders)"
                          % (method, path))
    k, _ = keys()
    headers = {"X-Kite-Version": "3", "User-Agent": "trader-bot"}
    if auth:
        s = load_session()
        if not s or not k:
            raise KiteAuth("Zerodha is not connected today (dashboard: Control > Connect Zerodha)")
        headers["Authorization"] = "token %s:%s" % (k, s["access_token"])
    bucket = "quote" if path.startswith("/quote") else "historical" if "historical" in path else "other"
    with _lock:
        wait = _last.get(bucket, 0) + _LIMITS[bucket] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[bucket] = time.monotonic()
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read())
        except Exception:
            doc = {}
        if doc.get("error_type") == "TokenException":
            forget_session()
            raise KiteAuth("Zerodha session expired: connect again from the dashboard")
        raise KiteError("Kite %s %s: %s %s" % (method, path, e.code, doc.get("message") or e.reason))
    except Exception as e:
        raise KiteError("Kite %s %s: %s" % (method, path, e))
    if raw:
        return payload.decode("utf-8")
    doc = json.loads(payload)
    if doc.get("status") != "success":
        raise KiteError("Kite %s: %s" % (path, doc.get("message")))
    return doc.get("data")


def exchange(request_token):
    """The redirect after the Zerodha login brings a request_token: swap it for today's access token."""
    k, sec = keys()
    if not (k and sec):
        raise KiteError("KITE_API_KEY / KITE_API_SECRET are not set on the server")
    if not re.fullmatch(r"[A-Za-z0-9]{8,64}", request_token or ""):
        raise KiteError("bad request_token")
    checksum = hashlib.sha256((k + request_token + sec).encode()).hexdigest()
    d = _call("POST", "/session/token", data={"api_key": k, "request_token": request_token, "checksum": checksum},
              auth=False)
    now = datetime.now(timezone.utc)
    _save_session({"access_token": d["access_token"], "user_id": d.get("user_id"),
                   "login_time": now.isoformat(), "expires": _expiry_after(now).isoformat()})
    return status()


# ------------------------------------------------------------------ instruments

_INSTR = {}   # exchange -> (date, rows)


def instruments(exch):
    """Kite's instrument dump for one exchange, cached on disk once a day."""
    today = datetime.now(IST).date().isoformat()
    if _INSTR.get(exch, (None,))[0] == today:
        return _INSTR[exch][1]
    path = os.path.join(INSTR_DIR, "%s-%s.csv" % (exch, today))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = _call("GET", "/instruments/%s" % exch, raw=True, timeout=60)
        os.makedirs(INSTR_DIR, exist_ok=True)
        for old in os.listdir(INSTR_DIR):
            if old.startswith(exch + "-"):
                os.remove(os.path.join(INSTR_DIR, old))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    rows = list(csv.DictReader(io.StringIO(text)))
    _INSTR[exch] = (today, rows)
    return rows


def _fno_parse(name):
    """Paper F&O names: UNDERLYING-YYYYMMDD-STRIKE-CE|PE or UNDERLYING-FUT-YYYYMMDD (index or stock)."""
    u = name.upper()
    p = u.rsplit("-", 2) if re.search(r"-FUT-\d{8}$", u) else u.rsplit("-", 3)   # BAJAJ-AUTO-FUT-..., M&M-...
    if len(p) == 3 and p[1] == "FUT":
        return {"name": p[0], "type": "FUT", "expiry": datetime.strptime(p[2], "%Y%m%d").date()}
    if len(p) == 4 and p[3] in ("CE", "PE"):
        return {"name": p[0], "type": p[3], "expiry": datetime.strptime(p[1], "%Y%m%d").date(),
                "strike": float(p[2])}
    raise KiteError("not an F&O name: %s" % name)


_RESOLVED = {}


def resolve(key):
    """Paper key -> {"exchange", "tradingsymbol", "token", "lot", "expiry", "kite"} or KiteError."""
    if key in _RESOLVED:
        return _RESOLVED[key]
    m, t = key.split(":", 1)
    if m in ("NSE", "BSE"):
        ex, sym = INDEX.get(t.upper().replace(" ", ""), (m, t.upper()))
        row = next((r for r in instruments(ex) if r["tradingsymbol"] == sym), None)
        if not row:
            raise KiteError("%s not found on Kite %s" % (t, ex))
    elif m == "NFO":
        ins = _fno_parse(t)
        name = {"NIFTY50": "NIFTY"}.get(ins["name"], ins["name"])
        want = ins["expiry"].isoformat()
        row = None
        for r in instruments("NFO"):
            if r["name"] != name or r["expiry"] != want or r["instrument_type"] != ins["type"]:
                continue
            if ins["type"] != "FUT" and abs(float(r["strike"] or 0) - ins["strike"]) > 1e-6:
                continue
            row = r
            break
        if not row:
            raise KiteError("%s: no such contract on Kite NFO (expiry / strike?)" % t)
        ex = "NFO"
    else:
        raise KiteError("Kite covers the Indian market only, not %s" % m)
    out = {"exchange": ex, "tradingsymbol": row["tradingsymbol"], "token": int(row["instrument_token"]),
           "lot": int(float(row.get("lot_size") or 1)), "expiry": row.get("expiry") or None,
           "kite": "%s:%s" % (ex, row["tradingsymbol"])}
    _RESOLVED[key] = out
    return out


def fno_chain(name, expiry=None):
    """Option and future contracts of one underlying (index or stock): [{type, strike, expiry, tradingsymbol,
    token, lot}], nearest expiry first."""
    name = {"NIFTY50": "NIFTY"}.get(name.upper(), name.upper())
    rows = [r for r in instruments("NFO") if r["name"] == name]
    if expiry:
        rows = [r for r in rows if r["expiry"] == (expiry if isinstance(expiry, str) else expiry.isoformat())]
    out = [{"type": r["instrument_type"], "strike": float(r["strike"] or 0), "expiry": r["expiry"],
            "tradingsymbol": r["tradingsymbol"], "token": int(r["instrument_token"]),
            "lot": int(float(r["lot_size"] or 1))} for r in rows]
    return sorted(out, key=lambda r: (r["expiry"], r["type"], r["strike"]))


def fno_underlyings():
    """Every underlying with F&O on NSE (indices and stocks)."""
    return sorted({r["name"] for r in instruments("NFO") if r["name"]})


def paper_name(c, underlying):
    """A Kite contract (fno_chain row) -> the paper key's name part."""
    exp = c["expiry"].replace("-", "")
    if c["type"] == "FUT":
        return "%s-FUT-%s" % (underlying, exp)
    k = c["strike"]
    return "%s-%s-%s-%s" % (underlying, exp, int(k) if k == int(k) else k, c["type"])


# ------------------------------------------------------------------ data

def _kite_time(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST).astimezone(timezone.utc)
    except ValueError:
        return None


def quotes(paper_keys):
    """{paper key: (price, quote_time_utc, extra)} for the ones Kite knows. One request for up to 500."""
    want, out = {}, {}
    for k in paper_keys:
        try:
            want[resolve(k)["kite"]] = k
        except KiteError:
            continue
    names = list(want)
    for i in range(0, len(names), 500):
        d = _call("GET", "/quote", params={"i": names[i:i + 500]}) or {}
        now = datetime.now(timezone.utc)
        for kn, q in d.items():
            if kn in want and q.get("last_price") is not None:
                qt = _kite_time(q.get("last_trade_time")) or _kite_time(q.get("timestamp")) or now
                out[want[kn]] = (float(q["last_price"]), min(qt, now),
                                 {"ohlc": q.get("ohlc"), "volume": q.get("volume"), "oi": q.get("oi")})
    return out


def ltp(key):
    q = quotes([key])
    if key not in q:
        raise KiteError("no Kite quote for %s" % key)
    return q[key][0], q[key][1]


def candles(key, start, end=None, interval="minute"):
    """[(utc, o, h, l, c, volume)] from Kite's historical API, oldest first."""
    ins = resolve(key)
    end = end or datetime.now(timezone.utc)
    fmt = "%Y-%m-%d %H:%M:%S"
    d = _call("GET", "/instruments/historical/%d/%s" % (ins["token"], interval),
              params={"from": start.astimezone(IST).strftime(fmt), "to": end.astimezone(IST).strftime(fmt)})
    return [(datetime.fromisoformat(c[0]).astimezone(timezone.utc), float(c[1]), float(c[2]), float(c[3]),
             float(c[4]), float(c[5] if len(c) > 5 else 0)) for c in (d or {}).get("candles") or []]


def minutes(key, start, end=None, interval="minute"):
    """[(utc, o, h, l, c)] 1-minute candles from `start` (utc) to `end` (default now), oldest first."""
    ins = resolve(key)
    end = end or datetime.now(timezone.utc)
    fmt = "%Y-%m-%d %H:%M:%S"
    d = _call("GET", "/instruments/historical/%d/%s" % (ins["token"], interval),
              params={"from": start.astimezone(IST).strftime(fmt), "to": end.astimezone(IST).strftime(fmt)})
    out = []
    for c in (d or {}).get("candles") or []:
        ts = datetime.fromisoformat(c[0]).astimezone(timezone.utc)
        out.append((ts, float(c[1]), float(c[2]), float(c[3]), float(c[4])))
    return out


# ------------------------------------------------------------------ ticks written by kite_ticker.py

TICKS_FILE = os.path.join(LIVE_DIR, "ticks.json")


def read_ticks(max_age=5.0):
    """{paper key: {"ltp", "t", ...}} from the ticker service, if it wrote in the last `max_age` seconds."""
    try:
        with open(TICKS_FILE, encoding="utf-8") as fh:
            doc = json.load(fh)
        if time.time() - float(doc.get("written", 0)) > max_age:
            return {}
        return doc.get("ticks") or {}
    except (FileNotFoundError, ValueError, TypeError):
        return {}


def tick_price(key, max_age=5.0):
    """(price, time) from the live tick stream, or None."""
    t = read_ticks(max_age).get(key)
    if not t or t.get("ltp") is None:
        return None
    return float(t["ltp"]), datetime.fromtimestamp(float(t.get("t") or time.time()), timezone.utc)


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if not a or a[0] == "status":
        print(json.dumps(status(), indent=2))
    elif a[0] == "ltp":
        for k, (p, qt, _) in quotes(a[1:]).items():
            print("%-40s %12.2f  %s" % (k, p, qt.astimezone(IST).strftime("%H:%M:%S")))
    elif a[0] == "resolve":
        for k in a[1:]:
            print(k, resolve(k))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
