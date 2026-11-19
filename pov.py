#!/usr/bin/env python3
"""
pov.py - the bigger picture for each chart (owner, 12 Nov 2026): the full Scanner v4 setup read on the 1-hour,
4-hour, daily, weekly and monthly candles. The direction of the LAST complete v4 setup on a timeframe is its POV:
a BUY setup = bullish, a SELL setup = bearish. Shown on the dashboard only; it never blocks or opens a trade.

On these higher timeframes v4 keeps every setup until traded (no intraday day rule) - the owner's long / short
term reading.

Charts: the dashboard's watch lists (Nifty 50, Nifty / Bank Nifty, the US list, the crypto universe) and every open
paper position. 1h / 4h are refreshed every hour (60 days of 1-hour candles; 4h built from them), 1D / 1W / 1M
once a day (5 years of daily candles; weeks and months built from them). Data: Yahoo (Coinbase for crypto when
Yahoo refuses). Writes trader/live/pov.json.

Service: deploy/trader-pov.service.   By hand:  python pov.py once   (python pov.py = the hourly loop)
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import scanner_v4 as V4

TFS = ("1h", "4h", "1D", "1W", "1M")
POV_FILE = os.path.join("trader", "live", "pov.json")
LEDGER = os.path.join("trader", "paper", "ledger.json")
IST = timezone(timedelta(hours=5, minutes=30))
INDEX_YAHOO = {"NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK"}
MIN_CANDLES = 40


def log(msg):
    print("%s %s" % (datetime.now(timezone.utc).strftime("%H:%M:%S"), msg), flush=True)


def rows_of(d):
    if not d or not d.get("t"):
        return []
    return [(datetime.fromtimestamp(t, timezone.utc), o, h, l, c, v or 0)
            for t, o, h, l, c, v in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"])]


def group(rows, key):
    """Bigger candles from smaller ones: consecutive rows with the same key(row, index in its day) form one."""
    out, cur, k_prev = [], None, None
    day_of, n_in_day, last_day = None, 0, None
    for r in rows:
        d = r[0].date()
        n_in_day = n_in_day + 1 if d == last_day else 0
        last_day = d
        k = key(r, n_in_day)
        if cur is not None and k == k_prev:
            cur = [cur[0], cur[1], max(cur[2], r[2]), min(cur[3], r[3]), r[4], cur[5] + r[5]]
            out[-1] = tuple(cur)
        else:
            cur = [r[0], r[1], r[2], r[3], r[4], r[5]]
            out.append(tuple(cur))
        k_prev = k
    return out


def frames(hourly, daily):
    """{tf: rows} for the five timeframes."""
    return {"1h": hourly,
            "4h": group(hourly, lambda r, n: (r[0].date(), n // 4)),
            "1D": daily,
            "1W": group(daily, lambda r, n: r[0].isocalendar()[:2]),
            "1M": group(daily, lambda r, n: (r[0].year, r[0].month))}


def pov_of(rows):
    """{"pov": "bullish" / "bearish", "at": signal time, "setup": primary / secondary} of the last complete v4 setup,
    {"pov": None, "why": ...} when there is none."""
    if len(rows) < MIN_CANDLES:
        return {"pov": None, "why": "not enough history (%d candles)" % len(rows)}
    try:
        # higher timeframes: no day rule (owner: the old no-cancel rules on 1h / 4h / D / W / M); the 2-candle swings
        # and gap BOS of before 19 Nov (the display stays as it was; the 19 Nov BOS rules are for the 5-minute trades)
        seq = V4.sequence(rows, lambda t: t.date(), intraday=False, day_carry=False, swing_k=2, bos_gap_skip=False)
    except Exception as e:
        return {"pov": None, "why": "error: %s" % e}
    if not seq:
        return {"pov": None, "why": "no complete v4 setup yet"}
    last = max(seq, key=lambda t: t["i"])
    return {"pov": "bullish" if last["side"] == "long" else "bearish",
            "at": rows[last["i"]][0].isoformat(), "setup": last["kind"]}


def charts():
    """[(dashboard key, market, symbol)] to read."""
    out = [("NSE:NIFTY50", "INDEX", "NIFTY50"), ("NSE:BANKNIFTY", "INDEX", "BANKNIFTY")]
    try:
        import scan_nse
        out += [("NSE:" + s, "NSE", s) for s in scan_nse.NIFTY50]
    except Exception:
        pass
    try:
        import auto_us
        out += [("US:" + s, "US", s) for s in auto_us.US_WATCH]
    except Exception:
        pass
    try:
        import scan_crypto
        out += [("CRYPTO:" + s, "CRYPTO", s) for s in scan_crypto.universe()]
    except Exception:
        pass
    try:
        with open(LEDGER, encoding="utf-8") as fh:
            led = json.load(fh)
        for p in led.get("open") or []:
            if p.get("market") in ("NSE", "US", "CRYPTO"):
                out.append(("%s:%s" % (p["market"], p["symbol"]), p["market"], p["symbol"]))
            if p.get("v4_chart") == "NSE:BANKNIFTY":
                out.append(("NSE:BANKNIFTY", "INDEX", "BANKNIFTY"))
    except (FileNotFoundError, ValueError, KeyError):
        pass
    seen, uniq = set(), []
    for c in out:
        if c[0] not in seen:
            seen.add(c[0])
            uniq.append(c)
    return uniq


def fetch(market, sym, rng, interval):
    import scan_nse as S
    if market == "CRYPTO":
        import scan_crypto as C
        return rows_of(C.crypto_chart(sym, rng, interval))
    if market == "INDEX":
        return rows_of(S.yahoo_chart(INDEX_YAHOO[sym], rng, interval, ""))
    return rows_of(S.yahoo_chart(sym, rng, interval, ".NS" if market == "NSE" else ""))


def read_one(chart, daily_cache, refresh_daily):
    key, market, sym = chart
    hourly = fetch(market, sym, "60d", "60m")
    if refresh_daily or key not in daily_cache:
        daily_cache[key] = fetch(market, sym, "5y", "1d")
    fr = frames(hourly, daily_cache.get(key) or [])
    return key, {tf: pov_of(fr[tf]) for tf in TFS}


def run_once(daily_cache, refresh_daily, workers=4):
    out, failed = {}, 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in [ex.submit(read_one, c, daily_cache, refresh_daily) for c in charts()]:
            try:
                k, v = fut.result()
                out[k] = v
            except Exception:
                failed += 1
    doc = {"written": time.time(), "tfs": list(TFS), "charts": out,
           "note": "the direction of the last complete Scanner v4 setup on each timeframe; display only"}
    os.makedirs(os.path.dirname(POV_FILE), exist_ok=True)
    tmp = POV_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    os.replace(tmp, POV_FILE)
    return len(out), failed


def loop():
    daily_cache, day = {}, None
    while True:
        t0 = time.time()
        today = datetime.now(IST).date()
        try:
            n, failed = run_once(daily_cache, refresh_daily=(today != day))
            day = today
            log("POV written for %d charts (%d failed)" % (n, failed))
        except Exception as e:
            log("POV failed: %s" % e)
        nxt = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(minute=3, second=0, microsecond=0)
        time.sleep(max(60.0, (nxt - datetime.now(timezone.utc)).total_seconds()))


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)) if len(sys.argv) < 3 else sys.argv[2])
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        print("charts written: %d, failed: %d" % run_once({}, True))
    else:
        log("POV job starting (display only; never trades)")
        loop()
