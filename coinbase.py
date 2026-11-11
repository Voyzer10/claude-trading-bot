#!/usr/bin/env python3
"""
coinbase.py - Coinbase Exchange as a PUBLIC live price source for the crypto paper account. Data only.

Why Coinbase (owner, 11 Nov 2026): CoinDCX blocks the VPS (every public CoinDCX endpoint answered 403 Forbidden
from its IP, whatever the client), while Coinbase's public market data answers, needs no key and allows scripts.
Its USD spot prices are also what the crypto backtests were built on (Yahoo / Coinbase), so live prices and the
backtests now read the same market. Fees stay the CoinDCX USDT futures model (paper.py fee_pct).

No API key, by design: this module never reads, stores or sends one. Every REST request goes through _get(),
which only allows the public GET endpoints in ALLOWED; the live feed (crypto_ticker.py) only subscribes to the
public "ticker" channel. Nothing here can place, modify or cancel an order; tests/test_crypto_live.py checks it.

  products()           the online USD products ("BTC-USD", ...), cached for 6 hours
  product_of("BTC")    "BTC-USD", or None when Coinbase does not list the coin
  price("BTC")         (price, time) from one REST ticker request, or None
  tick_price("BTC")    (price, time) from crypto_ticker.py's file, if it wrote in the last 5 seconds

    python coinbase.py check BTC ETH SOL PEPE
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = "trader-bot (paper trading; public market data)"
REST = "https://api.exchange.coinbase.com"
WS_URL = "wss://ws-feed.exchange.coinbase.com"
LIVE_DIR = os.path.join("trader", "live")
TICKS_FILE = os.path.join(LIVE_DIR, "crypto_ticks.json")

# the only REST requests this module may send: GET, these paths, no credentials. Nothing that trades is here.
ALLOWED = [r"/products", r"/products/[A-Z0-9]+-USD/ticker", r"/products/[A-Z0-9]+-USD/candles"]


class CoinbaseError(Exception):
    pass


class CoinbaseBlocked(CoinbaseError):
    """A request outside ALLOWED (orders, accounts, anything private). Never sent."""


def allowed(url, method="GET"):
    u = urllib.parse.urlsplit(url)
    return (method == "GET" and u.scheme == "https" and u.hostname == "api.exchange.coinbase.com"
            and any(re.fullmatch(p, u.path) for p in ALLOWED))


def _get(url, method="GET", timeout=8):
    if not allowed(url, method):
        raise CoinbaseBlocked("refused: %s %s is not a public market-data endpoint" % (method, url.split("?")[0]))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        raise CoinbaseError("Coinbase %s: %s" % (urllib.parse.urlsplit(url).path, e))


_PRODUCTS = {"at": 0.0, "ids": None}


def products(max_age=6 * 3600):
    """The online USD products' ids ("BTC-USD", ...)."""
    now = time.time()
    if _PRODUCTS["ids"] is not None and now - _PRODUCTS["at"] < max_age:
        return _PRODUCTS["ids"]
    got = _get(REST + "/products")
    ids = {p["id"] for p in got if isinstance(p, dict) and str(p.get("id", "")).endswith("-USD")
           and p.get("status", "online") == "online" and not p.get("trading_disabled")} if isinstance(got, list) else set()
    if not ids:
        raise CoinbaseError("Coinbase returned no USD products")
    _PRODUCTS.update(at=now, ids=ids)
    return ids


def product_of(sym, ids=None):
    pid = "%s-USD" % sym.upper().replace("-USD", "")
    return pid if pid in (products() if ids is None else ids) else None


def price(sym):
    """(price, time) from Coinbase's public ticker for one coin, or None."""
    try:
        pid = product_of(sym)
        if not pid:
            return None
        d = _get("%s/products/%s/ticker" % (REST, pid))
        px = float(d.get("price") or 0)
        if px <= 0:
            return None
        t = d.get("time")
        when = datetime.fromisoformat(t.replace("Z", "+00:00")) if t else datetime.now(timezone.utc)
        return px, when
    except (CoinbaseError, TypeError, ValueError):
        return None


def read_ticks(max_age=5.0):
    """{"CRYPTO:BTC": {"ltp", "t", ...}} from crypto_ticker.py, if it wrote in the last `max_age` seconds."""
    try:
        with open(TICKS_FILE, encoding="utf-8") as fh:
            doc = json.load(fh)
        if time.time() - float(doc.get("written", 0)) > max_age:
            return {}
        return doc.get("ticks") or {}
    except (FileNotFoundError, ValueError, TypeError):
        return {}


def tick_price(sym, max_age=5.0):
    t = read_ticks(max_age).get("CRYPTO:" + sym.upper())
    if not t or t.get("ltp") is None:
        return None
    return float(t["ltp"]), datetime.fromtimestamp(float(t.get("t") or time.time()), timezone.utc)


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if a and a[0] == "check":
        for s in a[1:] or ["BTC", "ETH", "SOL", "PEPE"]:
            pid, q = product_of(s), price(s)
            print("%-6s product %-11s price %s" % (s, pid or "none", "%.8g" % q[0] if q else "none"))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
