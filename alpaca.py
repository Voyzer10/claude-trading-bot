#!/usr/bin/env python3
"""
alpaca.py - Alpaca Market Data as the live price source for the US paper account. Data only.

The keys (ALPACA_KEY_ID, ALPACA_SECRET_KEY) come from the environment (/etc/trader/trader.env on the VPS), never
from the repo, the logs or the dashboard. Only a PAPER key is accepted (its id starts with "PK"): a live-account
key is refused before anything is sent. And every request goes through _get(), which only allows the market-data
host and its stock data paths in ALLOWED: the trading API (api.alpaca.markets, paper-api.alpaca.markets: orders,
positions, account) can not be reached from here. tests/test_alpaca.py checks both.

Free (Basic) plan: IEX exchange prices in real time, 200 requests a minute. us_ticker.py asks for every watched
symbol's snapshot in one request every 2 seconds (30 a minute).

  configured()               keys present and a paper key
  snapshots(["AAPL", ...])   {"AAPL": {"price", "t", "prev_close", "chg_pct"}} in one request
  price("AAPL")              (price, time) of the latest IEX trade, or None
  minutes("AAPL", a, b)      [(utc, o, h, l, c)] 1-minute IEX bars
  tick_price("AAPL")         (price, time) from us_ticker.py's file, if it wrote in the last 10 seconds

    python alpaca.py check AAPL MSFT TSLA
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DATA = "https://data.alpaca.markets"
LIVE_DIR = os.path.join("trader", "live")
TICKS_FILE = os.path.join(LIVE_DIR, "us_ticks.json")
FEED = "iex"

# the only requests this module may send: GET to the market-data host, these paths. Nothing that trades is here.
ALLOWED = [r"/v2/stocks/snapshots", r"/v2/stocks/trades/latest", r"/v2/stocks/bars",
           # options market data (owner, 13 Nov 2026: US F&O on QQQ / SPY, paper): the chain of one underlying, and
           # snapshots of given contracts. The free plan gets the "indicative" feed (quotes modified, trades delayed).
           r"/v1beta1/options/snapshots/[A-Z]{1,6}", r"/v1beta1/options/snapshots"]
OPTIONS_FEED = "indicative"


class AlpacaError(Exception):
    pass


class AlpacaBlocked(AlpacaError):
    """A request outside ALLOWED (trading, account), or a non-paper key. Never sent."""


def keys():
    return os.environ.get("ALPACA_KEY_ID", "").strip(), os.environ.get("ALPACA_SECRET_KEY", "").strip()


def configured():
    k, s = keys()
    return bool(k and s and k.startswith("PK"))


def allowed(url, method="GET"):
    u = urllib.parse.urlsplit(url)
    return (method == "GET" and u.scheme == "https" and u.hostname == "data.alpaca.markets"
            and any(re.fullmatch(p, u.path) for p in ALLOWED))


def _get(path, params, timeout=8):
    url = "%s%s?%s" % (DATA, path, urllib.parse.urlencode(params))
    if not allowed(url):
        raise AlpacaBlocked("refused: GET %s is not a market-data endpoint" % path)
    k, s = keys()
    if not (k and s):
        raise AlpacaError("no Alpaca keys (ALPACA_KEY_ID / ALPACA_SECRET_KEY in /etc/trader/trader.env)")
    if not k.startswith("PK"):
        raise AlpacaBlocked("refused: only an Alpaca PAPER key (id starting with PK) is used")
    req = urllib.request.Request(url, headers={"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s,
                                               "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        raise AlpacaError("Alpaca %s: %s" % (path, str(e).replace(s, "***")))


def _iso(t):
    """Alpaca timestamps (RFC 3339, nanoseconds, Z) -> aware datetime."""
    if not t:
        return datetime.now(timezone.utc)
    s = str(t).replace("Z", "+00:00")
    m = re.match(r"(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", s)
    if m:
        frac = (m.group(2) or "")[:7]
        s = m.group(1) + frac + (m.group(3) or "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(timezone.utc)


def snapshots(symbols):
    """{"AAPL": {"price", "t" (epoch s), "prev_close", "chg_pct", "high", "low"}} for the symbols IEX has, one request."""
    syms = [s.upper() for s in symbols if s]
    if not syms:
        return {}
    doc = _get("/v2/stocks/snapshots", {"symbols": ",".join(syms), "feed": FEED})
    out = {}
    for s, d in (doc or {}).items():
        if not isinstance(d, dict):
            continue
        tr = d.get("latestTrade") or {}
        px = tr.get("p")
        if not px or px <= 0:
            continue
        rec = {"price": float(px), "t": _iso(tr.get("t")).timestamp()}
        prev = (d.get("prevDailyBar") or {}).get("c")
        if prev:
            rec["prev_close"] = float(prev)
            rec["chg_pct"] = round((float(px) - float(prev)) / float(prev) * 100, 3)
        day = d.get("dailyBar") or {}
        if day.get("h"):
            rec["high"], rec["low"] = float(day["h"]), float(day["l"])
        out[s.upper()] = rec
    return out


def _opt_rec(sym, d):
    """One options snapshot -> {"symbol", "bid", "ask", "mid", "last", "t", "iv", "delta"} (None fields when absent)."""
    q, tr, g = d.get("latestQuote") or {}, d.get("latestTrade") or {}, d.get("greeks") or {}
    bid, ask = q.get("bp"), q.get("ap")
    mid = round((float(bid) + float(ask)) / 2, 4) if bid and ask and float(ask) >= float(bid) > 0 else None
    t = q.get("t") or tr.get("t")
    return {"symbol": sym, "bid": bid, "ask": ask, "mid": mid, "last": tr.get("p"), "t": _iso(t).timestamp() if t else None,
            "iv": d.get("impliedVolatility"), "delta": g.get("delta")}


def option_chain(underlying, kind=None, exp_gte=None, exp_lte=None, strike_gte=None, strike_lte=None, pages=5):
    """[contract snapshot] for one underlying's options (kind "call" / "put"; dates YYYY-MM-DD), indicative feed."""
    params = {"feed": OPTIONS_FEED, "limit": 1000}
    for k, v in (("type", kind), ("expiration_date_gte", exp_gte), ("expiration_date_lte", exp_lte),
                 ("strike_price_gte", strike_gte), ("strike_price_lte", strike_lte)):
        if v is not None:
            params[k] = v
    out, token = [], None
    for _ in range(pages):
        if token:
            params["page_token"] = token
        doc = _get("/v1beta1/options/snapshots/%s" % underlying.upper(), params) or {}
        for sym, d in (doc.get("snapshots") or {}).items():
            if isinstance(d, dict):
                out.append(_opt_rec(sym, d))
        token = doc.get("next_page_token")
        if not token:
            break
    return out


def option_snapshots(symbols):
    """{occ symbol: contract snapshot} for given contracts (one request), indicative feed."""
    syms = [s.upper() for s in symbols if s]
    if not syms:
        return {}
    doc = _get("/v1beta1/options/snapshots", {"symbols": ",".join(syms), "feed": OPTIONS_FEED}) or {}
    return {s: _opt_rec(s, d) for s, d in (doc.get("snapshots") or {}).items() if isinstance(d, dict)}


def price(sym):
    """(price, time) of the latest IEX trade for one symbol, or None."""
    try:
        doc = _get("/v2/stocks/trades/latest", {"symbols": sym.upper(), "feed": FEED})
        tr = ((doc or {}).get("trades") or {}).get(sym.upper()) or {}
        px = float(tr.get("p") or 0)
        return (px, _iso(tr.get("t"))) if px > 0 else None
    except (AlpacaError, TypeError, ValueError):
        return None


def minutes(sym, start, end):
    """[(utc, o, h, l, c)] 1-minute IEX bars between start and end, oldest first."""
    out, token = [], None
    for _ in range(5):
        params = {"symbols": sym.upper(), "timeframe": "1Min", "feed": FEED, "limit": 10000,
                  "start": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "end": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if token:
            params["page_token"] = token
        doc = _get("/v2/stocks/bars", params, timeout=10)
        for b in ((doc or {}).get("bars") or {}).get(sym.upper()) or []:
            try:
                out.append((_iso(b["t"]), float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"])))
            except (KeyError, TypeError, ValueError):
                continue
        token = (doc or {}).get("next_page_token")
        if not token:
            break
    return sorted(out)


def read_ticks(max_age=10.0):
    try:
        with open(TICKS_FILE, encoding="utf-8") as fh:
            doc = json.load(fh)
        if time.time() - float(doc.get("written", 0)) > max_age:
            return {}
        return doc.get("ticks") or {}
    except (FileNotFoundError, ValueError, TypeError):
        return {}


def tick_price(sym, max_age=10.0):
    t = read_ticks(max_age).get("US:" + sym.upper())
    if not t or t.get("ltp") is None:
        return None
    return float(t["ltp"]), datetime.fromtimestamp(float(t.get("t") or time.time()), timezone.utc)


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if a and a[0] == "check":
        k, _ = keys()
        print("keys: %s" % ("paper key set" if configured() else "missing" if not k else "NOT a paper key (refused)"))
        if configured():
            snaps = snapshots(a[1:] or ["AAPL", "MSFT", "TSLA"])
            for s in a[1:] or ["AAPL", "MSFT", "TSLA"]:
                d = snaps.get(s.upper())
                print("%-6s %s" % (s.upper(), "price %.2f  (%s)  change %+.2f%%" % (
                    d["price"], datetime.fromtimestamp(d["t"], timezone.utc).isoformat(timespec="seconds"),
                    d.get("chg_pct") or 0) if d else "no IEX price"))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
