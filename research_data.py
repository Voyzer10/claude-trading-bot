#!/usr/bin/env python3
"""Long 5-minute history for the backtests, from the brokers (owner, 19 Nov 2026). Run it on your own computer.

    python research_data.py kite-login            once a day before `nse` (Zerodha tokens expire ~6:00 IST)
    python research_data.py nse    [--days 365]   Nifty 50 stocks, Zerodha Kite historical API (needs the add-on)
    python research_data.py crypto [--days 180]   CoinDCX futures candles (public, no key); Binance if CoinDCX is empty
    python research_data.py us     [--days 365]   US liquid list, Alpaca market data (paper key, IEX feed)
    python research_data.py status                what is downloaded

Keys come from the environment or a `.env` file next to this script (KITE_API_KEY, KITE_API_SECRET,
ALPACA_KEY_ID, ALPACA_SECRET_KEY); they are never printed. Files go to trader/research/long/ in the backtest's
cache format; `python research.py nse-sv4 --long` (or us-sv4 / crypto-sv4-5m) then backtests on them.
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
LONG = os.path.join("trader", "research", "long")
UTC = timezone.utc


def load_env(path=None):
    """KEY=VALUE lines of .env into os.environ (an existing variable wins). Values are never printed."""
    path = path or os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return 0
    n = 0
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
                n += 1
    return n


def save(sym, suffix, rows, interval="5m"):
    """rows [(epoch s, o, h, l, c, v)] -> trader/research/long/<sym><suffix>_<interval>.json (sorted, deduped)."""
    rows = sorted({int(r[0]): r for r in rows}.values(), key=lambda r: r[0])
    os.makedirs(LONG, exist_ok=True)
    path = os.path.join(LONG, "%s%s_%s.json" % (sym.replace("^", "_"), suffix, interval))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"t": [int(r[0]) for r in rows], "o": [r[1] for r in rows], "h": [r[2] for r in rows],
                   "l": [r[3] for r in rows], "c": [r[4] for r in rows], "v": [r[5] for r in rows]}, fh)
    return path, len(rows)


def get_json(url, headers=None, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=dict({"User-Agent": "trader-research"}, **(headers or {})))
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(1.5 * (k + 1))


# ------------------------------------------------------------------ Zerodha (India)

def kite_login():
    import kite as K
    if not K.configured():
        sys.exit("KITE_API_KEY / KITE_API_SECRET are not set (environment or .env)")
    print("1. Open this link and log in to Zerodha:\n   %s" % K.login_url())
    print("2. After the login the browser goes to your redirect URL (the page may not open: that is fine);")
    print("   paste that whole URL, or just its request_token value. A token works once, within a few minutes.")
    tok = input("request_token (or the whole URL): ").strip()
    if "request_token=" in tok:          # the whole redirect URL was pasted: take just the token
        tok = urllib.parse.parse_qs(urllib.parse.urlsplit(tok).query).get("request_token", [""])[0]
    K.exchange(tok)
    print("Kite session saved (valid until ~6:00 IST tomorrow).")


def nse(days, syms):
    import kite as K
    if not K.load_session():
        sys.exit("No Kite session today: run  python research_data.py kite-login  first")
    end = datetime.now(UTC)
    ok = 0
    for i, s in enumerate(syms, 1):
        rows, t = [], end - timedelta(days=days)
        try:
            while t < end:                       # Kite: at most 100 days of 5-minute candles per request
                t2 = min(end, t + timedelta(days=95))
                rows += [(int(c[0].timestamp()), c[1], c[2], c[3], c[4], c[5])
                         for c in K.candles("NSE:" + s, t, t2, interval="5minute")]
                t = t2
            path, n = save(s, ".NS", rows)
            ok += n > 0
            print("%3d/%d %-12s %6d candles" % (i, len(syms), s, n), flush=True)
        except Exception as e:
            print("%3d/%d %-12s failed: %s" % (i, len(syms), s, str(e)[:120]), flush=True)
            if "permission" in str(e).lower() or "historical" in str(e).lower() and i == 1:
                print("   (the Kite historical API needs Zerodha's paid add-on on this app)")
    print("NSE: %d of %d symbols saved in %s" % (ok, len(syms), LONG))


# ------------------------------------------------------------------ CoinDCX / Binance (crypto)

def coindcx(sym, start, end):
    """CoinDCX futures 5-minute candles B-<SYM>_USDT, a day per request."""
    rows, t = [], start
    while t < end:
        t2 = min(end, t + timedelta(days=1))
        q = urllib.parse.urlencode({"pair": "B-%s_USDT" % sym, "from": int(t.timestamp()), "to": int(t2.timestamp()),
                                    "resolution": "5", "pcode": "f"})
        d = get_json("https://public.coindcx.com/market_data/candlesticks?" + q) or {}
        for c in d.get("data") or []:
            rows.append((int(c["time"]) // 1000, float(c["open"]), float(c["high"]), float(c["low"]),
                         float(c["close"]), float(c.get("volume") or 0)))
        t = t2
        time.sleep(0.15)
    return rows


def binance(sym, start, end):
    """Binance spot 5-minute klines <SYM>USDT (public), 1,000 per request."""
    rows, t = [], int(start.timestamp() * 1000)
    stop = int(end.timestamp() * 1000)
    while t < stop:
        q = urllib.parse.urlencode({"symbol": "%sUSDT" % sym, "interval": "5m", "startTime": t, "limit": 1000})
        k = get_json("https://api.binance.com/api/v3/klines?" + q) or []
        if not k:
            break
        rows += [(int(x[0]) // 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])) for x in k]
        t = int(k[-1][0]) + 300000
        time.sleep(0.1)
    return rows


def crypto(days, syms):
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)
    for i, s in enumerate(syms, 1):
        src, rows = "CoinDCX", []
        try:
            rows = coindcx(s, start, end)
        except Exception as e:
            print("   CoinDCX %s: %s" % (s, str(e)[:100]))
        if len(rows) < days * 200:              # thin or empty: Binance spot instead
            try:
                rows, src = binance(s, start, end), "Binance"
            except Exception as e:
                print("   Binance %s: %s" % (s, str(e)[:100]))
        path, n = save(s, "-USD", rows)
        print("%3d/%d %-6s %6d candles (%s)" % (i, len(syms), s, n, src), flush=True)


# ------------------------------------------------------------------ Alpaca (US)

def us(days, syms):
    import alpaca as A
    if not A.configured():
        sys.exit("ALPACA_KEY_ID / ALPACA_SECRET_KEY are not set (environment or .env)")
    end = datetime.now(UTC) - timedelta(minutes=20)
    start = end - timedelta(days=days)
    for i, s in enumerate(syms, 1):
        rows, token = [], None
        try:
            while True:
                p = {"symbols": s, "timeframe": "5Min", "feed": A.FEED, "limit": 10000, "adjustment": "split",
                     "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": end.strftime("%Y-%m-%dT%H:%M:%SZ")}
                if token:
                    p["page_token"] = token
                d = A._get("/v2/stocks/bars", p, timeout=20) or {}
                for b in (d.get("bars") or {}).get(s) or []:
                    t = int(datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp())
                    rows.append((t, b["o"], b["h"], b["l"], b["c"], b.get("v", 0)))
                token = d.get("next_page_token")
                if not token:
                    break
            path, n = save(s, "", rows)
            print("%3d/%d %-6s %6d candles" % (i, len(syms), s, n), flush=True)
        except Exception as e:
            print("%3d/%d %-6s failed: %s" % (i, len(syms), s, str(e)[:120]), flush=True)


def status():
    if not os.path.isdir(LONG):
        print("nothing yet in", LONG)
        return
    for f in sorted(os.listdir(LONG)):
        with open(os.path.join(LONG, f), encoding="utf-8") as fh:
            d = json.load(fh)
        t = d["t"]
        if t:
            print("%-26s %7d  %s .. %s" % (f, len(t), datetime.fromtimestamp(t[0], UTC).date(),
                                           datetime.fromtimestamp(t[-1], UTC).date()))


def main(argv=None):
    os.chdir(ROOT)
    load_env()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", choices=["kite-login", "nse", "crypto", "us", "status"])
    p.add_argument("--days", type=int, default=0)
    p.add_argument("--symbols", default="", help="space-separated list instead of the default one")
    a = p.parse_args(argv)
    syms = a.symbols.upper().split() if a.symbols else None
    if a.what == "kite-login":
        return kite_login()
    if a.what == "status":
        return status()
    if a.what == "nse":
        import scan_nse as S
        return nse(a.days or 365, syms or S.NIFTY50)
    if a.what == "crypto":
        import crypto_ticker as CT
        coins = syms or (CT.DEFAULT_COINS + "BNB TRX NEAR ATOM UNI AAVE SUI APT ARB OP INJ TIA SEI FET RENDER HBAR "
                                            "FIL ETC BCH XLM ONDO PYTH WIF JUP ENA CRV".split())
        return crypto(a.days or 180, coins)
    if a.what == "us":
        import research_abcd
        return us(a.days or 365, syms or list(research_abcd.US_LIQUID))


if __name__ == "__main__":
    main()
