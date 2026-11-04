#!/usr/bin/env python3
"""
scan_nse.py - NSE / BSE chart scanner (an Indian-market take on trader-scanner).

A scan is a list of charts that match a rule, not a list of stocks to buy.
Free, unofficial Yahoo Finance data (.NS / .BO symbols), 5-minute bars, can lag.

    python scan_nse.py universe                 # Nifty 500 list -> trader/universe_nse.txt
    python scan_nse.py orb                      # NSE opening-range breakouts so far (after 9:35 IST)
    python scan_nse.py orb --market BSE         # BSE (trader/universe_bse.txt, else Sensex 30)
    python scan_nse.py orb --at 10:00           # cut the clock at 10:00 IST
    python scan_nse.py daily                    # setups on daily closes
    python scan_nse.py orb --symbols RELIANCE,TCS,INFY
    python scan_nse.py orb --nifty50            # the built-in Nifty 50 list (fast)

For a hands-off live feed, run live.py instead: it calls these scans on a loop.

Writes trader/watchlist.json (mode, as_of, scanned, failed, hits[]) in the same
shape as trader-scanner, so hits[].symbol can be handed on.
Standard-library Python 3.8+. Nothing to pip install. Never places an order.
"""
import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))  # India has no DST
OPEN = (9, 15)
CLOSE = (15, 30)
OUT_DIR = "trader"
SUFFIX = {"NSE": ".NS", "BSE": ".BO"}
UNIVERSE_FILES = {"NSE": os.path.join(OUT_DIR, "universe_nse.txt"),
                  "BSE": os.path.join(OUT_DIR, "universe_bse.txt")}
UNIVERSE_FILE = UNIVERSE_FILES["NSE"]
WATCHLIST_FILE = os.path.join(OUT_DIR, "watchlist.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
NIFTY500_URLS = [
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
]
# Fallback lists only. Index membership changes; check niftyindices.com / bseindia.com.
NIFTY50 = (
    "ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE "
    "BAJAJFINSV BEL BHARTIARTL CIPLA COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM "
    "HCLTECH HDFCBANK HDFCLIFE HINDALCO HINDUNILVR ICICIBANK INDIGO INFY ITC "
    "JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI MAXHEALTH NESTLEIND NTPC ONGC "
    "POWERGRID RELIANCE SBILIFE SBIN SHRIRAMFIN SUNPHARMA TATACONSUM TMPV "
    "TATASTEEL TCS TECHM TITAN TRENT ULTRACEMCO WIPRO"
).split()
SENSEX30 = (
    "ADANIPORTS ASIANPAINT AXISBANK BAJAJFINSV BAJFINANCE BEL BHARTIARTL ETERNAL "
    "HCLTECH HDFCBANK HINDUNILVR ICICIBANK INFY ITC KOTAKBANK LT M&M MARUTI NTPC "
    "POWERGRID RELIANCE SBIN SUNPHARMA TATASTEEL TCS TECHM TITAN TMPV TRENT ULTRACEMCO"
).split()


class ScanError(Exception):
    pass


# ---------------------------------------------------------------- network

def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def yahoo_chart(symbol, rng, interval, suffix=".NS"):
    """Return dict with t, o, h, l, c, v lists (nulls dropped) and meta, or None."""
    ysym = urllib.parse.quote(symbol + suffix, safe="")
    last_err = None
    for host in ("query2", "query1"):
        url = ("https://%s.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s"
               "&includePrePost=false" % (host, ysym, rng, interval))
        for attempt in range(2):
            try:
                doc = json.loads(http_get(url))
                res = (doc.get("chart") or {}).get("result") or []
                if not res:
                    return None
                r = res[0]
                ts = r.get("timestamp") or []
                q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
                out = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": [],
                       "meta": r.get("meta") or {}}
                for i, t in enumerate(ts):
                    vals = [(q.get(k) or [None] * len(ts))[i] for k in
                            ("open", "high", "low", "close", "volume")]
                    if any(x is None for x in vals[:4]):
                        continue
                    out["t"].append(t)
                    for k, x in zip("ohlcv", vals):
                        out[k].append(x or 0)
                return out
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 429 and attempt == 0:
                    time.sleep(5)
                    continue
                if e.code == 404:
                    return None
                break
            except Exception as e:  # network hiccup: try the other host
                last_err = e
                break
    raise ScanError(str(last_err))


def fetch_many(symbols, rng, interval, workers, suffix=".NS", quiet=False, fetcher=None):
    data, failed = {}, []
    fetcher = fetcher or yahoo_chart
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetcher, s, rng, interval, suffix): s for s in symbols}
        done = 0
        for f in as_completed(futs):
            s = futs[f]
            done += 1
            try:
                d = f.result()
                if d and d["t"]:
                    data[s] = d
                else:
                    failed.append(s)
            except Exception:
                failed.append(s)
            if not quiet and done % 50 == 0:
                print("  ...%d of %d" % (done, len(symbols)), file=sys.stderr)
    return data, failed


# ---------------------------------------------------------------- universe

def download_nifty500():
    last = None
    for url in NIFTY500_URLS:
        try:
            text = http_get(url).decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text)))
            syms = [(r["Symbol"].strip(), r.get("Company Name", "").strip())
                    for r in rows if r.get("Symbol") and r.get("Series", "EQ").strip() == "EQ"]
            if len(syms) > 100:
                os.makedirs(OUT_DIR, exist_ok=True)
                with open(UNIVERSE_FILES["NSE"], "w", encoding="utf-8") as fh:
                    for s, n in syms:
                        fh.write("%s|%s\n" % (s, n))
                return len(syms), url
        except Exception as e:
            last = e
    raise ScanError("could not download the Nifty 500 list (%s)" % last)


def cmd_universe(a):
    try:
        n, url = download_nifty500()
        print("Wrote %s: %d Nifty 500 symbols (from %s)." % (UNIVERSE_FILES["NSE"], n, url))
        return 0
    except ScanError as e:
        print("%s. Use --nifty50 or --symbols instead." % e)
        return 1


def universe_for(market):
    """The symbol list for a market: its universe file, else the built-in fallback."""
    path = UNIVERSE_FILES[market]
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            syms = [ln.split("|")[0].strip().upper() for ln in fh
                    if ln.strip() and not ln.lstrip().startswith("#")]
        if syms:
            return syms, path
    return (list(NIFTY50), "built-in Nifty 50") if market == "NSE" else (list(SENSEX30), "built-in Sensex 30")


def dedup(syms):
    seen, out = set(), []
    for s in syms:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def read_symbols(a):
    if a.symbols:
        syms = [s.strip().upper().replace(".NS", "").replace(".BO", "")
                for s in a.symbols.replace(" ", ",").split(",") if s.strip()]
    elif a.nifty50:
        syms = list(NIFTY50)
    else:
        syms, src = universe_for(a.market)
        if src.startswith("built-in"):
            print("Using the %s list (no %s yet)." % (src, UNIVERSE_FILES[a.market]), file=sys.stderr)
    out = dedup(syms)
    return out[:a.limit] if a.limit else out


# ---------------------------------------------------------------- time

def at(day, hm):
    return datetime(day.year, day.month, day.day, hm[0], hm[1], tzinfo=IST)


def fmt(dt):
    return dt.strftime("%I:%M %p").lstrip("0")


def is_session(now):
    return now.weekday() < 5 and at(now, OPEN) <= now < at(now, CLOSE)


# ---------------------------------------------------------------- ORB

def orb_one(d, day, cutoff, or_minutes, side="long"):
    """Opening-range breakout (close above the range high) or, with side "short"/"both", breakdown (close
    below the range low) on today's 5-minute bars. Returns hit dict, 'none', or None (unusable)."""
    o_start = at(day, OPEN)
    o_end = o_start + timedelta(minutes=or_minutes)
    bars = []
    for t, h, l, c, v in zip(d["t"], d["h"], d["l"], d["c"], d["v"]):
        start = datetime.fromtimestamp(t, IST)
        if start.date() != day.date() or (start.minute % 5) or start.second:
            continue  # other day, or the live tick off the 5-minute grid
        end = start + timedelta(minutes=5)
        if start < o_start or end > cutoff:
            continue  # not complete by the cutoff
        bars.append((start, end, h, l, c, v))
    need = int((cutoff - o_start).total_seconds() // 300)
    if len(bars) < need or need * 5 <= or_minutes:
        return None  # a missing bar: halt or thin stock
    rng = [b for b in bars if b[0] < o_end]
    after = [b for b in bars if b[0] >= o_end]
    if not rng:
        return None
    hi = max(b[2] for b in rng)
    lo = min(b[3] for b in rng)
    vol = sum(b[5] for b in bars)
    rng_vol = sum(b[5] for b in rng) / len(rng)
    first_open = None
    for t, o in zip(d["t"], d["o"]):
        st = datetime.fromtimestamp(t, IST)
        if st.date() == day.date() and st >= o_start:
            first_open = o
            break
    for i, b in enumerate(after):
        up = side in ("long", "both") and b[4] > hi
        down = side in ("short", "both") and b[4] < lo
        if up or down:
            # volume vs the bars just before the breakout (the 9:15 bars are the day's loudest, so
            # comparing an 11:00 bar to them rejects almost everything)
            prior = (rng + after[:i])[-6:]
            base = sum(x[5] for x in prior) / len(prior) if prior else 0
            return {"time": b[1].strftime("%H:%M"), "price": round(b[4], 2),
                    "vol_x_recent": round(b[5] / base, 2) if base else None,
                    "range_high": round(hi, 2), "range_low": round(lo, 2),
                    "pct_over": round((b[4] / hi - 1) * 100, 2) if up else round((b[4] / lo - 1) * 100, 2),
                    "side": "long" if up else "short",
                    "last": round(bars[-1][4], 2), "turnover": bars[-1][4] * vol,
                    "vol_x": round(b[5] / rng_vol, 2) if rng_vol else None,
                    "day_open": round(first_open, 2) if first_open else None}
    return "none"


def orb_cutoff(now, at_hm=None):
    cutoff = at(now, at_hm) if at_hm else now
    cutoff = cutoff.replace(minute=cutoff.minute - cutoff.minute % 5, second=0, microsecond=0)
    return min(cutoff, at(now, CLOSE))


def orb_ready(cutoff, or_minutes):
    return cutoff.weekday() < 5 and cutoff >= at(cutoff, OPEN) + timedelta(minutes=or_minutes + 5)


def orb_scan(symbols, market, now, cutoff, or_minutes=15, min_price=20.0, workers=8, quiet=False, side="long"):
    """Fetch and scan. Returns a dict (never prints)."""
    data, failed = fetch_many(symbols, "1d", "5m", workers, SUFFIX[market], quiet)
    hits, usable = [], 0
    for s, d in data.items():
        r = orb_one(d, now, cutoff, or_minutes, side)
        if r is None:
            continue
        usable += 1
        if r != "none" and r["price"] >= min_price:
            pc = (d.get("meta") or {}).get("chartPreviousClose") or (d.get("meta") or {}).get("previousClose")
            short = r.get("side") == "short"
            ref = r["range_low"] if short else r["range_high"]
            r.update({"symbol": s, "market": market, "setup": "orb_short" if short else "orb", "prev_close": pc,
                      "gap_pct": round((r["day_open"] / pc - 1) * 100, 2) if pc and r.get("day_open") else None,
                      "holding": r["last"] < r["range_low"] if short else r["last"] > r["range_high"],
                      "pct_now": round((r["last"] / ref - 1) * 100, 2)})
            hits.append(r)
    hits.sort(key=lambda h: h["time"])
    return {"mode": "orb", "market": market, "as_of": cutoff.isoformat(), "universe": len(symbols),
            "scanned": len(data), "failed": len(failed), "usable": usable, "hits": hits,
            "_data": data}   # _data: the charts, for scanner_v2.py; live.py pops it before saving


def cmd_orb(a):
    now = now_ist(a)
    hm = tuple(map(int, a.at.split(":"))) if a.at else None
    cutoff = orb_cutoff(now, hm)
    if now.weekday() >= 5:
        print("NSE/BSE are closed today (weekend). Nothing written.")
        return 1
    if not orb_ready(cutoff, a.or_minutes):
        print("Too early: the %d-minute opening range plus one bar completes at %s IST. Nothing written."
              % (a.or_minutes, fmt(at(now, OPEN) + timedelta(minutes=a.or_minutes + 5))))
        return 1
    syms = read_symbols(a)
    print("Fetching today's 5-minute bars for %d %s symbols (Yahoo, %d at a time)..."
          % (len(syms), a.market, a.workers), file=sys.stderr)
    res = orb_scan(syms, a.market, now, cutoff, a.or_minutes, a.min_price, a.workers)
    res.pop("_data", None)
    if res["usable"] == 0 and res["scanned"]:
        print("Fetched %d charts but none had every bar from 9:15 to %s IST today "
              "(holiday, or Yahoo lagging). Nothing written." % (res["scanned"], fmt(cutoff)))
        return 1
    hits = res["hits"]
    print("%s ORB scan, %s, cut at %s IST (Yahoo 5-minute bars, unofficial, can lag)."
          % (a.market, now.strftime("%a %Y-%m-%d"), fmt(cutoff)))
    print("Fetched %d of %d charts (%d failed or had no data); %d usable."
          % (res["scanned"], len(syms), res["failed"], res["usable"]))
    print("%d of %d charts closed above their %d-minute opening-range high by %s IST:"
          % (len(hits), res["usable"], a.or_minutes, fmt(cutoff)))
    for h in hits[:a.show]:
        print("  %5s  %-12s Rs %9.2f  range %.2f to %.2f  +%.2f%% over  (last Rs %.2f, %s)"
              % (h["time"], h["symbol"], h["price"], h["range_low"], h["range_high"],
                 h["pct_over"], h["last"], "holding" if h["holding"] else "back inside"))
    if len(hits) > a.show:
        print("  ... and %d more (see %s)" % (len(hits) - a.show, WATCHLIST_FILE))
    print("A later hit is closer to the price now. Matched a rule, not a buy.")
    write(a, res)
    return 0 if hits else 1


# ---------------------------------------------------------------- daily

def rsi14(closes):
    if len(closes) < 16:
        return None, None
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    ag = sum(gains[:14]) / 14
    al = sum(losses[:14]) / 14
    vals = []
    for g, l in zip(gains[14:], losses[14:]):
        ag = (ag * 13 + g) / 14
        al = (al * 13 + l) / 14
        vals.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    if len(vals) < 2:
        return None, None
    return vals[-2], vals[-1]


def daily_setups(closes):
    tags = []
    if len(closes) >= 21 and closes[-1] > max(closes[-21:-1]):
        tags.append("breakout_20d")
    if len(closes) >= 16:
        base, flag = closes[-16], closes[-6]
        last5 = closes[-5:]
        if base > 0 and flag / base - 1 > 0.10 and (max(last5) / min(last5) - 1) <= 0.05:
            tags.append("bull_flag")
    if len(closes) >= 22:
        ma_prev = sum(closes[-22:-2]) / 20
        ma_now = sum(closes[-21:-1]) / 20
        if closes[-2] < ma_prev and closes[-1] > ma_now:
            tags.append("reclaim_ma20")
    r_prev, r_now = rsi14(closes)
    if r_now is not None and r_now < 30:
        tags.append("oversold")
    if r_prev is not None and r_prev < 30 and closes[-1] > closes[-2]:
        tags.append("oversold_bounce")
    return tags


def daily_scan(symbols, market, now, min_price=20.0, min_volume=100000, workers=8, quiet=False):
    """Fetch and scan daily closes. Returns a dict (never prints)."""
    data, failed = fetch_many(symbols, "3mo", "1d", workers, SUFFIX[market], quiet)
    in_session = is_session(now)
    hits, liquid, last_day = [], 0, None
    for s, d in data.items():
        rows = list(zip(d["t"], d["c"], d["v"]))
        if in_session and rows and datetime.fromtimestamp(rows[-1][0], IST).date() == now.date():
            rows = rows[:-1]  # today's bar is not final until 15:30
        if len(rows) < 21:
            continue
        closes = [r[1] for r in rows]
        price, vol = closes[-1], rows[-1][2]
        if price < min_price or vol < min_volume:
            continue
        liquid += 1
        d0 = datetime.fromtimestamp(rows[-1][0], IST).date()
        last_day = max(last_day, d0) if last_day else d0
        for tag in daily_setups(closes):
            hits.append({"symbol": s, "market": market, "setup": tag, "price": round(price, 2),
                         "volume": vol, "turnover": price * vol})
    hits.sort(key=lambda h: -h["turnover"])
    return {"mode": "daily", "market": market, "as_of": now.isoformat(),
            "closes_through": last_day.isoformat() if last_day else None, "universe": len(symbols),
            "scanned": len(data), "failed": len(failed), "liquid": liquid, "hits": hits}


def cmd_daily(a):
    now = now_ist(a)
    syms = read_symbols(a)
    print("Fetching 3 months of daily bars for %d %s symbols..." % (len(syms), a.market), file=sys.stderr)
    res = daily_scan(syms, a.market, now, a.min_price, a.min_volume, a.workers)
    print("%s daily scan, %s IST, closes through %s (Yahoo daily bars, unofficial)."
          % (a.market, now.strftime("%a %Y-%m-%d %H:%M"), res["closes_through"] or "nothing"))
    if is_session(now):
        print("The market is open: today's bar is left out until 15:30, so this uses yesterday's close.")
    print("Fetched %d of %d charts (%d failed or had no data). %d passed the liquidity filter "
          "(Rs %g+ and %s+ shares)." % (res["scanned"], len(syms), res["failed"], res["liquid"],
                                        a.min_price, format(a.min_volume, ",")))
    by = {}
    for h in res["hits"]:
        by.setdefault(h["setup"], []).append(h["symbol"])
    for tag in ("breakout_20d", "bull_flag", "reclaim_ma20", "oversold", "oversold_bounce"):
        if tag in by:
            names = by[tag]
            print("  %-16s %3d  %s%s" % (tag, len(names), ", ".join(names[:12]),
                                         " ..." if len(names) > 12 else ""))
    if not res["hits"]:
        print("No setups.")
    print("Matched a rule, not a buy.")
    write(a, res)
    return 0 if res["hits"] else 1


# ---------------------------------------------------------------- output

def now_ist(a):
    if getattr(a, "now", None):
        return datetime.strptime(a.now, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
    return datetime.now(IST)


def write(a, res):
    if a.no_write:
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=2)
    print("Wrote %s (%s %s, %d hits)." % (WATCHLIST_FILE, res["market"], res["mode"], len(res["hits"])))


def main(argv=None):
    p = argparse.ArgumentParser(description="NSE/BSE chart scanner (Yahoo data). Not financial advice.")
    p.add_argument("cmd", choices=["universe", "orb", "daily"])
    p.add_argument("--market", choices=["NSE", "BSE"], default="NSE")
    p.add_argument("--symbols", help="comma list, e.g. RELIANCE,TCS,INFY")
    p.add_argument("--nifty50", action="store_true", help="use the built-in Nifty 50 list")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--at", help="ORB cutoff HH:MM IST")
    p.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" IST')
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--min-price", type=float, default=20.0)
    p.add_argument("--min-volume", type=int, default=100000, help="daily scan only")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--show", type=int, default=40)
    p.add_argument("--no-write", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.cmd == "universe":
            return cmd_universe(a)
        return cmd_orb(a) if a.cmd == "orb" else cmd_daily(a)
    except ScanError as e:
        print("scan_nse.py: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
