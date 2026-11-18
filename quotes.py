#!/usr/bin/env python3
"""
quotes.py - the live prices paper.py trades and checks against: (price, quote time UTC) and 1-minute candles per
market. Indian market: Zerodha (kite.py) when connected; US: Alpaca IEX, then Yahoo, then Nasdaq / Stooq when Yahoo is
stale; crypto: Coinbase, then Yahoo; F&O: fno.py; US options: us_options.py. Split out of paper.py on 18 Nov 2026;
paper.py re-exports every name here (P.fetch_price etc.), and this file reads paper's markets and session through
paper.<name>, so a test that swaps paper.session or paper.fetch_price still reaches this code.
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


def kite_mod():
    """kite.py when Zerodha is connected today (Indian market data), else None. Data only: it cannot trade."""
    try:
        import kite
        return kite if kite.connected() else None
    except Exception:
        return None


def kite_price(m, t):
    """(price, time) for NSE / BSE / NFO from Zerodha: the live tick stream first, then a Kite quote. None if
    Zerodha is not connected or does not know the instrument."""
    if m not in ("NSE", "BSE", "NFO"):
        return None
    k = kite_mod()
    if not k:
        return None
    tick = k.tick_price(P.key(m, t))
    if tick:
        return tick
    try:
        return k.ltp(P.key(m, t))
    except Exception:
        return None


def _newest_quote(res):
    """(price, time) from one Yahoo chart result: the newer of meta.regularMarketPrice (at regularMarketTime) and
    the last 1-minute close (at its candle's end). None if neither exists."""
    meta = res.get("meta") or {}
    cands = []
    if meta.get("regularMarketPrice") is not None:
        ts = meta.get("regularMarketTime")
        cands.append((datetime.fromtimestamp(ts, timezone.utc) if ts else None, float(meta["regularMarketPrice"])))
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    for ts, c in reversed(list(zip(res.get("timestamp") or [], q.get("close") or []))):
        if c is not None and ts is not None:
            cands.append((datetime.fromtimestamp(ts, timezone.utc) + timedelta(minutes=1), float(c)))
            break
    if not cands:
        return None
    now = datetime.now(timezone.utc)
    dated = [(min(t, now), p) for t, p in cands if t is not None]
    if dated:
        t, p = max(dated, key=lambda x: x[0])
        return p, t
    return cands[0][1], now


_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                        "dec"), 1)}


def _nasdaq_quote(t, opener=None):
    """(price, trade time UTC) from Nasdaq's public quote API (last sale; no key), or None. Tries stock, then ETF."""
    import re
    opener = opener or urllib.request.urlopen
    for cls in ("stocks", "etf"):
        url = "https://api.nasdaq.com/api/quote/%s/info?assetclass=%s" % (urllib.parse.quote(t), cls)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": P.UA, "Accept": "application/json, text/plain, */*",
                                                       "Origin": "https://www.nasdaq.com",
                                                       "Referer": "https://www.nasdaq.com/"})
            with opener(req, timeout=8) as r:
                doc = json.loads(r.read())
            pd = ((doc or {}).get("data") or {}).get("primaryData") or {}
            px = str(pd.get("lastSalePrice") or "").replace("$", "").replace(",", "").strip()
            if not px:
                continue
            ts = str(pd.get("lastTradeTimestamp") or "")
            mt = re.search(r"([A-Za-z]{3})\w*\.? (\d{1,2}), (\d{4}),? (\d{1,2}):(\d{2}) ?([AP]M)", ts)
            if not mt:
                return float(px), None
            mon, day, yr, hh, mm, ap = mt.groups()
            h = int(hh) % 12 + (12 if ap.upper() == "PM" else 0)
            local = datetime(int(yr), _MONTHS[mon.lower()], int(day), h, int(mm), tzinfo=timezone.utc)
            utc = local - P.us_offset(local + timedelta(hours=5))     # ET -> UTC
            return float(px), utc
        except Exception:
            continue
    return None


def _stooq_quote(t, opener=None):
    """(price, time UTC) from Stooq's CSV quote (no key), or None. Stooq times are Polish local time."""
    opener = opener or urllib.request.urlopen
    url = "https://stooq.com/q/l/?s=%s.us&f=sd2t2c&h&e=csv" % urllib.parse.quote(t.lower())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": P.UA})
        with opener(req, timeout=8) as r:
            lines = r.read().decode("utf-8", "replace").strip().splitlines()
        sym, d, tm, close = lines[1].split(",")[:4]
        if close in ("N/D", ""):
            return None
        try:
            from zoneinfo import ZoneInfo
            local = datetime.fromisoformat("%sT%s" % (d, tm)).replace(tzinfo=ZoneInfo("Europe/Warsaw"))
            return float(close), local.astimezone(timezone.utc)
        except Exception:
            return float(close), None
    except Exception:
        return None


def us_backup_quote(t):
    """The newest of the backup US quotes: (price, time UTC) or None. Nasdaq's last sale is real time, so a Nasdaq
    price whose trade time cannot be read counts as now (checked from the VPS, 6 Nov 2026: Nasdaq answers, Stooq
    does not)."""
    now = datetime.now(timezone.utc)
    n = _nasdaq_quote(t)
    got = [(n[0], n[1] or now)] if n else []
    st = _stooq_quote(t)
    if st and st[1] is not None:
        got.append(st)
    return max(got, key=lambda q: q[1]) if got else None


def crypto_live_price(t, rest=True):
    """(price, time) for a coin from Coinbase (public data, no key): the live ticker's file (crypto_ticker.py)
    first, then one REST request. None when Coinbase does not list the coin or does not answer (Yahoo then)."""
    try:
        import coinbase
    except Exception:
        return None
    q = coinbase.tick_price(t)
    if q:
        return q
    return coinbase.price(t) if rest else None


def us_live_price(t, rest=True):
    """(price, time) for a US stock from Alpaca's IEX feed (paper key, data only): the live ticker's file
    (us_ticker.py) first, then one REST request. None without Alpaca keys or an IEX price (Yahoo then)."""
    try:
        import alpaca
    except Exception:
        return None
    q = alpaca.tick_price(t)
    if q:
        return q
    return alpaca.price(t) if (rest and alpaca.configured()) else None


def fetch_price(m, t):
    """Return (price, quote_time_utc). Raises PaperError."""
    kq = kite_price(m, t)                # Indian market: Zerodha (live) when connected
    if kq:
        return float(kq[0]), kq[1]
    if m == "US":
        uq = us_live_price(t)            # US: Alpaca IEX, live (owner, 11 Nov 2026)
        if uq:
            return float(uq[0]), uq[1]
    if m == "CRYPTO":
        cq = crypto_live_price(t)        # crypto: Coinbase live (CoinDCX blocks the VPS; 11 Nov 2026)
        if cq:
            return float(cq[0]), cq[1]
    if m == "USOPT":                     # Alpaca options data, indicative feed (paper key, data only)
        import us_options
        try:
            q = us_options.price(t)
        except Exception as e:
            raise P.PaperError("could not price %s: %s" % (t, str(e)[:200]))
        if not q:
            raise P.PaperError("no Alpaca option price for %s (paper key set? market open?)" % t)
        return q
    if m == "NFO":
        import fno
        try:
            p, qt, src, extra = fno.quote(t)
            return p, qt
        except fno.FnoError as e:
            raise P.PaperError(str(e))
        except Exception as e:
            raise P.PaperError("could not price %s: %s" % (t, e))
    ysym = urllib.parse.quote(P.yahoo_symbol(m, t), safe="")
    last, best = None, None
    for host in ("query2", "query1"):
        # _=<now> makes every request unique, so no cache between us and Yahoo can hand back an old answer
        url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1m&includePrePost=false&_=%d" % (
            host, ysym, int(time.time()))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": P.UA, "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=8) as r:
                doc = json.loads(r.read())
            res = (doc.get("chart") or {}).get("result") or []
            if not res:
                raise P.PaperError("Yahoo has no data for %s" % P.yahoo_symbol(m, t))
            best = _newest_quote(res[0])
            if best is None:
                raise P.PaperError("no price for %s" % P.yahoo_symbol(m, t))
            break
        except P.PaperError:
            raise
        except Exception as e:
            last = e
    if best is not None:
        price, qt = best
        # 5 Nov 2026: US quotes stayed frozen for 15+ minutes while the market was open (crypto was fine). If the
        # 1-minute answer is stale in an open session, ask for the 5-minute chart the scanner uses (it was fresh).
        now = datetime.now(timezone.utc)
        if m in ("US", "NSE", "BSE") and P.session(m, now) == "open" and now - qt > timedelta(minutes=10):
            try:
                import scan_nse as SN
                d = SN.yahoo_chart(t, "1d", "5m", suffix=P.MARKETS[m]["suffix"])
                if d and d["t"]:
                    t5 = datetime.fromtimestamp(d["t"][-1], timezone.utc) + timedelta(minutes=5)
                    if t5 > qt:
                        price, qt = float(d["c"][-1]), min(t5, now)
            except Exception:
                pass
        # still stale (5-6 Nov 2026: Yahoo served US quotes frozen 87 min from the VPS): Nasdaq / Stooq
        if m == "US" and P.session(m, now) == "open" and now - qt > timedelta(minutes=10):
            b = us_backup_quote(t)
            if b and b[1] > qt:
                price, qt = b[0], min(b[1], now)
        return float(price), qt
    if m == "US":      # Yahoo failed outright: the backup sources
        b = us_backup_quote(t)
        if b:
            return float(b[0]), min(b[1], datetime.now(timezone.utc))
    if m == "CRYPTO":  # cloud servers are sometimes refused by Yahoo: Coinbase's public ticker as a fallback
        try:
            req = urllib.request.Request("https://api.exchange.coinbase.com/products/%s-USD/ticker" % t,
                                         headers={"User-Agent": "trader-bot", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                doc = json.loads(r.read())
            return float(doc["price"]), datetime.now(timezone.utc)
        except Exception as e:
            last = "%s; coinbase: %s" % (last, e)
    raise P.PaperError("could not fetch %s: %s" % (P.yahoo_symbol(m, t), last))


def fetch_minutes(m, t, days=1):
    """1-minute candles [(utc, o, h, l, c)] of the last `days` days (1..7), oldest first, or [] (F&O, or no data).
    Used by check_once to see what happened BETWEEN two checks: a stop or target touched and left again in the
    minutes in between."""
    k = kite_mod() if m in ("NSE", "BSE", "NFO") else None
    if k:
        try:
            now = datetime.now(timezone.utc)
            out = k.minutes(P.key(m, t), now - timedelta(days=max(1, min(7, int(days)))), now)
            if out:
                return out
        except Exception:
            pass
    if m in ("NFO", "USOPT"):           # no 1-minute option candles: the checks use the live premium
        return []
    if m == "US":                        # Alpaca IEX 1-minute bars (paper key, data only)
        try:
            import alpaca
            if alpaca.configured():
                now = datetime.now(timezone.utc)
                out = alpaca.minutes(t, now - timedelta(days=max(1, min(7, int(days)))), now)
                if out:
                    return out
        except Exception:
            pass
    ysym = urllib.parse.quote(P.yahoo_symbol(m, t), safe="")
    rng = "%dd" % max(1, min(7, int(days)))
    for host in ("query2", "query1"):
        url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1m" % (host, ysym, rng)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": P.UA})
            with urllib.request.urlopen(req, timeout=8) as r:
                doc = json.loads(r.read())
            res = ((doc.get("chart") or {}).get("result") or [None])[0]
            if not res:
                return []
            q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
            out = []
            for ts, o, h, l, c in zip(res.get("timestamp") or [], q.get("open") or [], q.get("high") or [],
                                      q.get("low") or [], q.get("close") or []):
                if None not in (ts, o, h, l, c):
                    out.append((datetime.fromtimestamp(ts, timezone.utc), float(o), float(h), float(l), float(c)))
            if out:
                return out
        except Exception:
            continue
    if m == "CRYPTO":  # Coinbase public 1-minute candles: [time, low, high, open, close, volume], newest first
        try:
            req = urllib.request.Request("https://api.exchange.coinbase.com/products/%s-USD/candles?granularity=60" % t,
                                         headers={"User-Agent": "trader-bot", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                rows = json.loads(r.read())
            return sorted((datetime.fromtimestamp(x[0], timezone.utc), float(x[3]), float(x[2]), float(x[1]), float(x[4]))
                          for x in rows)
        except Exception:
            return []
    return []


import paper as P  # noqa: E402  (last: paper imports this module's names at its end)
