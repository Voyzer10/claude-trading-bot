#!/usr/bin/env python3
"""
coindcx.py - CoinDCX USDT markets as a PUBLIC price source for the crypto paper account. Data only.

No API key, by design (owner, 11 Nov 2026: "no real money trading"). CoinDCX has no read-only API keys (its docs:
"No, we currently don't have Read Only APIs"): any key could trade. Market data needs no key, so this module never
reads, stores or sends one, and every request goes through _get(), which only allows the public GET endpoints in
ALLOWED. Nothing here can place, modify or cancel an order; tests/test_coindcx.py checks it.

What it does
  current_prices()          every CoinDCX market's last price in one call (api.coindcx.com/exchange/ticker)
  market_of("PEPE", m)      ("PEPEUSDT", 1), or ("1000PEPEUSDT", 1000) when only the 1000x market exists
  prices(["BTC", ...])      {"BTC": (price, time)} per coin, from its USDT market, in the coin's own units
  tick_price("BTC")         (price, time) from coindcx_ticker.py's file if it wrote in the last 5 seconds
  instruments() / pair_of() / candles()   USDT futures pairs and candles (public.coindcx.com; see below)

Prices are CoinDCX USDT spot prices: the futures price host (public.coindcx.com) answers 403 Forbidden from the
VPS (checked 11 Nov 2026, also with a browser user agent), while api.coindcx.com answers. USDT spot and USDT
perpetual prices differ by a few hundredths of a percent, as do the USD spot prices the crypto backtests used
(Yahoo / Coinbase). 1-minute candles for stop / target checks stay on Yahoo / Coinbase for the same reason.

    python coindcx.py prices BTC ETH PEPE
    python coindcx.py candles BTC 15
    python coindcx.py check          (prices and the CoinDCX market each coin maps to)
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

UA = "Mozilla/5.0 (trader-bot; public market data)"
LIVE_DIR = os.path.join("trader", "live")
TICKS_FILE = os.path.join(LIVE_DIR, "crypto_ticks.json")
INSTR_FILE = os.path.join(LIVE_DIR, "coindcx_instruments.json")

# the only requests this module may send: (host, path regex), GET, no credentials. Nothing that trades is here.
ALLOWED = [
    ("api.coindcx.com", r"/exchange/ticker"),
    ("public.coindcx.com", r"/market_data/v3/current_prices/futures/rt"),
    ("public.coindcx.com", r"/market_data/candlesticks"),
    ("api.coindcx.com", r"/exchange/v1/derivatives/futures/data/active_instruments"),
]
TICKER_URL = "https://api.coindcx.com/exchange/ticker"
RT_URL = "https://public.coindcx.com/market_data/v3/current_prices/futures/rt"
CANDLES_URL = "https://public.coindcx.com/market_data/candlesticks"
INSTR_URL = ("https://api.coindcx.com/exchange/v1/derivatives/futures/data/active_instruments"
             "?margin_currency_short_name[]=USDT")
MULTS = (1, 1000, 1000000)        # Binance-style contract names: 1000PEPE, 1000000MOG
RESOLUTION = {1: "1", 5: "5", 60: "60", 1440: "1D"}


class CoinDCXError(Exception):
    pass


class CoinDCXBlocked(CoinDCXError):
    """A request outside ALLOWED (anything private or trading). Never sent."""


def allowed(url, method="GET"):
    u = urllib.parse.urlsplit(url)
    return (method == "GET" and u.scheme == "https"
            and any(u.hostname == h and re.fullmatch(p, u.path) for h, p in ALLOWED))


def _get(url, method="GET", timeout=8):
    if not allowed(url, method):
        raise CoinDCXBlocked("refused: %s %s is not a public market-data endpoint" % (method, url.split("?")[0]))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except CoinDCXError:
        raise
    except Exception as e:
        raise CoinDCXError("CoinDCX %s: %s" % (urllib.parse.urlsplit(url).path, e))


# ------------------------------------------------------------------ instruments

_INSTR = {"at": 0.0, "pairs": None}


def instruments(max_age=6 * 3600):
    """The active USDT futures pairs, from memory, the daily file, or CoinDCX."""
    now = time.time()
    if _INSTR["pairs"] is not None and now - _INSTR["at"] < max_age:
        return _INSTR["pairs"]
    try:
        with open(INSTR_FILE, encoding="utf-8") as fh:
            doc = json.load(fh)
        if now - float(doc.get("at", 0)) < max_age and doc.get("pairs"):
            _INSTR.update(at=float(doc["at"]), pairs=set(doc["pairs"]))
            return _INSTR["pairs"]
    except (FileNotFoundError, ValueError, TypeError):
        pass
    got = _get(INSTR_URL)
    pairs = {p for p in got if isinstance(p, str)} if isinstance(got, list) else set()
    if not pairs:
        raise CoinDCXError("CoinDCX returned no futures instruments")
    _INSTR.update(at=now, pairs=pairs)
    try:
        os.makedirs(LIVE_DIR, exist_ok=True)
        tmp = INSTR_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"at": now, "pairs": sorted(pairs)}, fh)
        os.replace(tmp, INSTR_FILE)
    except OSError:
        pass
    return pairs


def pair_of(sym, pairs=None):
    """("B-BTC_USDT", 1) for "BTC"; ("B-1000PEPE_USDT", 1000) for "PEPE"; None if CoinDCX has no USDT future."""
    pairs = instruments() if pairs is None else pairs
    s = sym.upper().replace("-USD", "").replace("USDT", "")
    for m in MULTS:
        name = "B-%s%s_USDT" % ("" if m == 1 else m, s)
        if name in pairs:
            return name, m
    return None


# ------------------------------------------------------------------ prices

def _num(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def last_price(d):
    """The last traded price of one entry of current_prices()."""
    return _num(d.get("last_price")) or _num(d.get("ls")) or _num(d.get("mp"))


def current_prices():
    """({market: entry}, time) for every CoinDCX market, one request (the public ticker). Entry keys: last_price,
    high, low, volume, change_24_hour (%), bid, ask, timestamp."""
    rows = _get(TICKER_URL)
    out, ts = {}, 0
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("market"):
            out[r["market"]] = r
            try:
                ts = max(ts, float(r.get("timestamp") or 0))
            except (TypeError, ValueError):
                pass
    if not out:
        raise CoinDCXError("CoinDCX ticker returned no markets")
    ts = ts / 1000 if ts > 1e12 else ts
    return out, datetime.fromtimestamp(ts or time.time(), timezone.utc)


def market_of(sym, markets):
    """("BTCUSDT", 1) for "BTC"; ("1000PEPEUSDT", 1000) when only the 1000x market exists; None if no USDT market."""
    s = sym.upper().replace("-USD", "").replace("USDT", "")
    for m in MULTS:
        name = "%s%sUSDT" % ("" if m == 1 else m, s)
        if name in markets:
            return name, m
    return None


def prices(symbols, rt=None):
    """{"BTC": (price, time)} for the coins CoinDCX has a USDT market for, in the coin's own units."""
    allp, t = rt if rt is not None else current_prices()
    out = {}
    for s in symbols:
        mo = market_of(s, allp)
        px = last_price(allp[mo[0]]) if mo else None
        if px:
            out[s.upper()] = (px / mo[1], t)
    return out


def price(sym):
    """(price, time) for one coin, or None (no USDT market on CoinDCX, or no answer)."""
    try:
        return prices([sym]).get(sym.upper())
    except CoinDCXError:
        return None


# ------------------------------------------------------------------ candles

def _raw_candles(pair, res, start, end):
    url = "%s?%s" % (CANDLES_URL, urllib.parse.urlencode(
        {"pair": pair, "from": int(start.timestamp()), "to": int(end.timestamp()), "resolution": res, "pcode": "f"}))
    doc = _get(url, timeout=10)
    rows = (doc or {}).get("data") or []
    out = []
    for r in rows:
        try:
            ts = float(r["time"])
            ts = ts / 1000 if ts > 1e12 else ts
            out.append((datetime.fromtimestamp(ts, timezone.utc), float(r["open"]), float(r["high"]),
                        float(r["low"]), float(r["close"]), float(r.get("volume") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(dict((x[0], x) for x in out).values())


def _group(rows, minutes):
    """Candles of `minutes` (15, 30 ...) from smaller ones, on the clock grid (00, 15, 30, 45)."""
    out, cur = [], None
    for t, o, h, l, c, v in rows:
        start = t - timedelta(minutes=t.minute % minutes, seconds=t.second, microseconds=t.microsecond)
        if cur and cur[0] == start:
            cur = [start, cur[1], max(cur[2], h), min(cur[3], l), c, cur[5] + v]
            out[-1] = tuple(cur)
        else:
            cur = [start, o, h, l, c, v]
            out.append(tuple(cur))
    return out


def candles(sym, minutes, start, end):
    """[(utc open time, o, h, l, c, volume)] for one coin's USDT future, oldest first, prices in the coin's units.
    minutes: 1, 5, 15 (built from 5), 60 or 1440. [] if CoinDCX has no future for the coin."""
    po = pair_of(sym)
    if not po:
        return []
    pair, mult = po
    if minutes in RESOLUTION:
        rows = _raw_candles(pair, RESOLUTION[minutes], start, end)
    elif minutes % 5 == 0 and minutes < 60:
        rows = _group(_raw_candles(pair, "5", start, end), minutes)
    else:
        raise CoinDCXError("no %d-minute candles" % minutes)
    return [(t, o / mult, h / mult, l / mult, c / mult, v) for t, o, h, l, c, v in rows]


# ------------------------------------------------------------------ the ticker's file

def read_ticks(max_age=5.0):
    """{"CRYPTO:BTC": {"ltp", "t", ...}} from coindcx_ticker.py, if it wrote in the last `max_age` seconds."""
    try:
        with open(TICKS_FILE, encoding="utf-8") as fh:
            doc = json.load(fh)
        if time.time() - float(doc.get("written", 0)) > max_age:
            return {}
        return doc.get("ticks") or {}
    except (FileNotFoundError, ValueError, TypeError):
        return {}


def tick_price(sym, max_age=5.0):
    """(price, time) for a coin from the live file, or None."""
    t = read_ticks(max_age).get("CRYPTO:" + sym.upper())
    if not t or t.get("ltp") is None:
        return None
    return float(t["ltp"]), datetime.fromtimestamp(float(t.get("t") or time.time()), timezone.utc)


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if a and a[0] == "prices":
        for s, (p, t) in sorted(prices(a[1:] or ["BTC", "ETH"]).items()):
            print("%-8s %14s  %s" % (s, ("%.8g" % p), t.isoformat()))
    elif a and a[0] == "check":
        allp, t = current_prices()
        for s in a[1:] or ["BTC", "ETH", "SOL", "PEPE"]:
            mo = market_of(s, allp)
            c = prices([s], (allp, t)).get(s.upper())
            print("%-6s market %-14s price %s" % (s, mo[0] if mo else "none", "%.8g" % c[0] if c else "none"))
    elif a and a[0] == "candles":
        sym, m = a[1], int(a[2]) if len(a) > 2 else 15
        end = datetime.now(timezone.utc)
        for r in candles(sym, m, end - timedelta(minutes=m * 8), end)[-6:]:
            print(r[0].isoformat(), *("%.8g" % x for x in r[1:]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
