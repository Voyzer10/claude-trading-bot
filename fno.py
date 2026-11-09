#!/usr/bin/env python3
"""
fno.py - Nifty 50 / Bank Nifty index F&O helpers for PAPER trading.

Instrument names (paper.py market "NFO"):
    NIFTY-FUT-20261124            index future, expiry date
    NIFTY-20261103-22800-CE       option: index, expiry, strike, CE/PE
    BANKNIFTY-20261124-48000-PE

Prices, in order of preference:
  1. NSE's public option chain (nseindia.com), the last traded price, when it answers
  2. a Black-Scholes model from the index level and India VIX (Yahoo), clearly marked "model"
Futures use fair value (spot x e^(r t)). A model price is an estimate, not a market quote:
real premiums carry their own implied volatility, skew and bid/ask spread.

Rules as of Oct 2026 (verify on nseindia.com; change them in FNO below if they change):
  lot size  Nifty 65, Bank Nifty 30 (from the Jan 2026 expiries)
  expiry    Nifty weekly on Tuesday; Bank Nifty monthly only, the last Tuesday of the month
  Holidays are not known here: an expiry on a holiday moves to the previous trading day on NSE.

    python fno.py spot                    # Nifty, Bank Nifty, India VIX
    python fno.py chain NIFTY             # ATM +/- 5 strikes for the next expiry, with source
    python fno.py quote NIFTY-20261103-22800-CE
"""
import http.cookiejar
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

FNO = {
    "NIFTY":     {"yahoo": "^NSEI",    "lot": 65, "step": 50,  "weekly": True,  "iv_mult": 1.00, "nse": "NIFTY"},
    "BANKNIFTY": {"yahoo": "^NSEBANK", "lot": 30, "step": 100, "weekly": False, "iv_mult": 1.25, "nse": "BANKNIFTY"},
}
VIX = "^INDIAVIX"
RATE = 0.065          # risk-free-ish rate for the model
EXPIRY_WEEKDAY = 1    # Tuesday
CLOSE_IST = (15, 30)


class FnoError(Exception):
    pass


# ------------------------------------------------------------------ data

KITE_SYM = {"^NSEI": "NSE:NIFTY50", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX"}


def _kite():
    """kite.py when Zerodha is connected today: live index levels, real option / future prices, real expiries
    and lot sizes. Data only. None otherwise (then Yahoo, NSE's chain and the model, as before)."""
    try:
        import kite
        return kite if kite.connected() else None
    except Exception:
        return None


def _get(url, timeout=12, opener=None, headers=None):
    req = urllib.request.Request(url, headers=dict({"User-Agent": UA, "Accept": "*/*"}, **(headers or {})))
    op = opener or urllib.request.build_opener()
    with op.open(req, timeout=timeout) as r:
        return r.read()


def yahoo_last(sym):
    """(price, quote_time_utc, previous_close) for an index symbol like ^NSEI."""
    k = _kite()
    if k and sym in KITE_SYM:
        try:
            q = k.quotes([KITE_SYM[sym]])[KITE_SYM[sym]]
            tick = k.tick_price(KITE_SYM[sym])
            p, qt = tick if tick else (q[0], q[1])
            return float(p), qt, ((q[2] or {}).get("ohlc") or {}).get("close")
        except Exception:
            pass
    url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1m" % urllib.parse.quote(sym, safe="")
    doc = json.loads(_get(url))
    res = (doc.get("chart") or {}).get("result") or []
    if not res:
        raise FnoError("Yahoo has no data for %s" % sym)
    meta = res[0].get("meta") or {}
    p = meta.get("regularMarketPrice")
    if p is None:
        raise FnoError("no price for %s" % sym)
    ts = meta.get("regularMarketTime")
    return float(p), (datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.now(timezone.utc)), meta.get("chartPreviousClose")


def yahoo_bars(sym, rng="1d", interval="5m"):
    """Bars as dict t,o,h,l,c,v (nulls dropped)."""
    k = _kite()
    iv = {"1m": "minute", "5m": "5minute", "15m": "15minute", "60m": "60minute", "1h": "60minute", "1d": "day"}
    if k and sym in KITE_SYM and interval in iv:
        try:
            days = int(rng[:-1]) if rng.endswith("d") else 1
            now = datetime.now(timezone.utc)
            start = (now.astimezone(IST) - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0)
            rows = k.candles(KITE_SYM[sym], start.astimezone(timezone.utc), now, iv[interval])
            if rows:
                return {"t": [int(r[0].timestamp()) for r in rows], "o": [r[1] for r in rows],
                        "h": [r[2] for r in rows], "l": [r[3] for r in rows], "c": [r[4] for r in rows],
                        "v": [r[5] for r in rows]}
        except Exception:
            pass
    url = ("https://query2.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s&includePrePost=false"
           % (urllib.parse.quote(sym, safe=""), rng, interval))
    doc = json.loads(_get(url, timeout=20))
    res = (doc.get("chart") or {}).get("result") or []
    if not res:
        raise FnoError("Yahoo has no bars for %s" % sym)
    r = res[0]
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    out = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    for i, t in enumerate(ts):
        vals = [(q.get(k) or [None] * len(ts))[i] for k in ("open", "high", "low", "close", "volume")]
        if any(x is None for x in vals[:4]):
            continue
        out["t"].append(t)
        for k, x in zip("ohlcv", vals):
            out[k].append(x or 0)
    return out


_chain_cache = {}


def nse_chain(index):
    """NSE's option chain JSON for an index, cached 60 s. Raises FnoError if NSE does not answer."""
    hit = _chain_cache.get(index)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    hdr = {"Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/option-chain"}
    try:
        _get("https://www.nseindia.com/option-chain", opener=op, headers=hdr)
        raw = _get("https://www.nseindia.com/api/option-chain-indices?symbol=%s" % FNO[index]["nse"], opener=op,
                   headers=dict(hdr, Accept="application/json"))
        doc = json.loads(raw)
        if not (doc.get("records") or {}).get("data"):
            raise FnoError("empty chain")
    except FnoError:
        raise
    except Exception as e:
        raise FnoError("NSE option chain unavailable: %s" % e)
    _chain_cache[index] = (time.time(), doc)
    return doc


# ------------------------------------------------------------------ expiry

def last_weekday_of_month(y, m, wd):
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() != wd:
        d -= timedelta(days=1)
    return d


def next_expiry(index, today, min_days=0):
    """Next option expiry on/after today+min_days (Nifty weekly Tuesday, Bank Nifty monthly last Tuesday). With
    Zerodha connected: the exchange's real expiry dates (holiday shifts included), for indices and stocks."""
    start = today + timedelta(days=min_days)
    k = _kite()
    if k:
        try:
            exps = sorted({c["expiry"] for c in k.fno_chain(index) if c["type"] in ("CE", "PE")})
            nxt = [e for e in exps if e >= start.isoformat()]
            if nxt:
                return date.fromisoformat(nxt[0])
        except Exception:
            pass
    if FNO[index]["weekly"]:
        d = start
        while d.weekday() != EXPIRY_WEEKDAY:
            d += timedelta(days=1)
        return d
    y, m = start.year, start.month
    for _ in range(3):
        d = last_weekday_of_month(y, m, EXPIRY_WEEKDAY)
        if d >= start:
            return d
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    raise FnoError("no expiry found")


def futures_expiry(index, today):
    """Index futures are monthly: the last Tuesday of the month (Zerodha connected: the real date)."""
    k = _kite()
    if k:
        try:
            exps = sorted({c["expiry"] for c in k.fno_chain(index) if c["type"] == "FUT"})
            nxt = [e for e in exps if e >= today.isoformat()]
            if nxt:
                return date.fromisoformat(nxt[0])
        except Exception:
            pass
    y, m = today.year, today.month
    for _ in range(3):
        d = last_weekday_of_month(y, m, EXPIRY_WEEKDAY)
        if d >= today:
            return d
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    raise FnoError("no futures expiry found")


def years_to(expiry, now_utc):
    end = datetime(expiry.year, expiry.month, expiry.day, CLOSE_IST[0], CLOSE_IST[1], tzinfo=IST)
    return max((end - now_utc).total_seconds(), 60) / (365.0 * 86400)


# ------------------------------------------------------------------ model

def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(spot, strike, t, vol, kind, r=RATE):
    """Black-Scholes price and delta for a European option (kind CE or PE)."""
    if t <= 0 or vol <= 0:
        intrinsic = max(spot - strike, 0) if kind == "CE" else max(strike - spot, 0)
        return intrinsic, (1.0 if kind == "CE" and spot > strike else 0.0)
    d1 = (math.log(spot / strike) + (r + vol * vol / 2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    if kind == "CE":
        return spot * _ncdf(d1) - strike * math.exp(-r * t) * _ncdf(d2), _ncdf(d1)
    return strike * math.exp(-r * t) * _ncdf(-d2) - spot * _ncdf(-d1), _ncdf(d1) - 1


def atm_strike(index, spot, expiry=None):
    """The strike nearest the spot: from Zerodha's real strike list when connected (stocks too)."""
    k = _kite()
    if k:
        try:
            ks = sorted({c["strike"] for c in k.fno_chain(index, expiry) if c["type"] == "CE"})
            if ks:
                best = min(ks, key=lambda x: abs(x - spot))
                return int(best) if best == int(best) else best
        except Exception:
            pass
    if index not in FNO:
        raise FnoError("%s: strike list needs Zerodha connected" % index)
    step = FNO[index]["step"]
    return int(round(spot / step) * step)


# ------------------------------------------------------------------ instruments

def make_option(index, expiry, strike, kind):
    k = int(strike) if float(strike) == int(strike) else strike
    return "%s-%s-%s-%s" % (index, expiry.strftime("%Y%m%d"), k, kind)


def make_future(index, expiry):
    return "%s-FUT-%s" % (index, expiry.strftime("%Y%m%d"))


def parse(name):
    p = name.upper().split("-")
    if len(p) == 3 and p[1] == "FUT":
        return {"index": p[0], "type": "FUT", "expiry": datetime.strptime(p[2], "%Y%m%d").date()}
    if len(p) == 4 and p[3] in ("CE", "PE"):
        k = float(p[2])
        return {"index": p[0], "type": p[3], "expiry": datetime.strptime(p[1], "%Y%m%d").date(),
                "strike": int(k) if k == int(k) else k}
    raise FnoError("not an F&O instrument name: %s (e.g. NIFTY-20261103-22800-CE or NIFTY-FUT-20261124)" % name)


def lot_size(name):
    k = _kite()
    if k:
        try:
            return k.resolve("NFO:" + name.upper())["lot"]
        except Exception:
            pass
    ix = parse(name)["index"]
    if ix not in FNO:
        raise FnoError("%s: the lot size needs Zerodha connected" % ix)
    return FNO[ix]["lot"]


def quote(name, now_utc=None, prefer_nse=True):
    """(price, quote_time_utc, source, extra) for an instrument."""
    now_utc = now_utc or datetime.now(timezone.utc)
    ins = parse(name)
    k = _kite()
    if k:                                    # Zerodha: the contract's real traded price
        try:
            key = "NFO:" + name.upper()
            q = k.quotes([key]).get(key)
            if q:
                tick = k.tick_price(key)
                p, qt = tick if tick else (q[0], q[1])
                extra = {"oi": (q[2] or {}).get("oi"), "volume": (q[2] or {}).get("volume")}
                if ins["index"] in FNO and ins["type"] != "FUT":
                    try:
                        extra["delta"] = round(delta(name, now_utc), 3)
                    except Exception:
                        pass
                return float(p), qt, "Zerodha live", extra
        except Exception:
            pass
    if ins["index"] not in FNO:
        raise FnoError("%s: stock F&O prices need Zerodha connected" % ins["index"])
    spot, qt, _ = yahoo_last(FNO[ins["index"]]["yahoo"])
    t = years_to(ins["expiry"], now_utc)
    if ins["type"] == "FUT":
        return round(spot * math.exp(RATE * t), 2), qt, "model (fair value from spot)", {"spot": spot}
    if prefer_nse:
        try:
            doc = nse_chain(ins["index"])
            want = ins["expiry"].strftime("%d-%b-%Y")
            for row in doc["records"]["data"]:
                if row.get("strikePrice") == ins["strike"] and row.get("expiryDate") == want and ins["type"] in row:
                    leg = row[ins["type"]]
                    ltp = leg.get("lastPrice")
                    if ltp:
                        return float(ltp), now_utc, "NSE option chain", {"spot": spot, "iv": leg.get("impliedVolatility"),
                                                                       "oi": leg.get("openInterest")}
        except FnoError:
            pass
    vix, _, _ = yahoo_last(VIX)
    vol = vix / 100 * FNO[ins["index"]]["iv_mult"]
    price, delta = bs(spot, ins["strike"], t, vol, ins["type"])
    return round(max(price, 0.05), 2), qt, "model (Black-Scholes, India VIX %.2f)" % vix, {
        "spot": spot, "vol": round(vol, 4), "delta": round(delta, 3), "years": round(t, 5)}


def delta(name, now_utc=None):
    """Model delta (used to turn an index stop into a premium stop)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    ins = parse(name)
    if ins["type"] == "FUT":
        return 1.0
    spot, _, _ = yahoo_last(FNO[ins["index"]]["yahoo"])
    vix, _, _ = yahoo_last(VIX)
    return bs(spot, ins["strike"], years_to(ins["expiry"], now_utc), vix / 100 * FNO[ins["index"]]["iv_mult"], ins["type"])[1]


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if not a:
        print(__doc__)
        return 1
    try:
        if a[0] == "spot":
            for name, sym in (("NIFTY", "^NSEI"), ("BANKNIFTY", "^NSEBANK"), ("INDIA VIX", VIX)):
                p, qt, pc = yahoo_last(sym)
                print("%-10s %10.2f  (%+.2f%% vs prev close)  %s IST" % (name, p, (p / pc - 1) * 100 if pc else 0,
                                                                         qt.astimezone(IST).strftime("%H:%M")))
        elif a[0] == "chain":
            idx = a[1].upper()
            now = datetime.now(timezone.utc)
            exp = next_expiry(idx, now.astimezone(IST).date())
            spot = yahoo_last(FNO[idx]["yahoo"])[0]
            atm = atm_strike(idx, spot)
            print("%s spot %.2f, expiry %s, lot %d" % (idx, spot, exp, FNO[idx]["lot"]))
            for k in range(atm - 5 * FNO[idx]["step"], atm + 6 * FNO[idx]["step"], FNO[idx]["step"]):
                ce = quote(make_option(idx, exp, k, "CE"), now)
                pe = quote(make_option(idx, exp, k, "PE"), now)
                print("  %6d  CE %8.2f   PE %8.2f   %s" % (k, ce[0], pe[0], ce[2]))
        elif a[0] == "quote":
            p, qt, src, extra = quote(a[1])
            print("%s  %.2f  (%s)  %s" % (a[1], p, src, extra))
        else:
            print(__doc__)
            return 1
    except FnoError as e:
        print("fno.py: %s" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
