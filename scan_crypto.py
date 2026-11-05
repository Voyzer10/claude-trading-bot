#!/usr/bin/env python3
"""
scan_crypto.py - crypto chart scanner (24/7 market, Yahoo -USD pairs).

Crypto has no opening bell, so instead of an opening range it uses:
  range_breakout_4h  the last completed 15-minute candle CLOSED above the high of the
                     4 hours (16 candles) before it
  oversold_15m       RSI 14 on 15-minute closes under 30
  daily setups       breakout_20d, bull_flag, reclaim_ma20, oversold, oversold_bounce
                     (same rules as the stock scanner, on daily closes; today's UTC
                     candle is still forming, so it is left out)

    python scan_crypto.py                  # intraday scan of trader/universe_crypto.txt (or the built-in top 20)
    python scan_crypto.py daily
    python scan_crypto.py --symbols BTC,ETH,SOL

A hit is a chart that matched a rule, not a buy. Never places an order.
Data: Yahoo Finance, free and unofficial, can lag. Standard-library Python 3.8+.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import scan_nse as S

UNIVERSE_FILE = os.path.join("trader", "universe_crypto.txt")
SUFFIX = "-USD"
# Plain Yahoo tickers only (some coins use odd Yahoo IDs, e.g. TON11419-USD; add those by hand).
TOP = ("BTC ETH XRP BNB SOL DOGE ADA TRX LINK AVAX XLM BCH LTC HBAR DOT SHIB "
       "ETC ATOM FIL NEAR").split()
BAR_MIN = 15
RANGE_BARS = 16  # 4 hours of 15-minute candles


def set_timeframe(tf):
    """'15m' (backtested, default) or '5m' (auto_config timeframe). The 4h range stays 4 hours."""
    global BAR_MIN, RANGE_BARS
    BAR_MIN = 5 if str(tf).strip().lower() in ("5", "5m") else 15
    RANGE_BARS = 240 // BAR_MIN
    return BAR_MIN


COINBASE = "https://api.exchange.coinbase.com"
_GRAN = {"5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
_RANGE_DAYS = {"2d": 2, "5d": 5, "30d": 30, "60d": 60, "3mo": 92}


def coinbase_chart(sym, rng, interval, suffix=SUFFIX):
    """Coinbase Exchange public candles in the same shape as scan_nse.yahoo_chart. Coins Coinbase does not
    list (BNB, TRX...) raise. Volume is Coinbase's own, not the whole market's: ratios still compare."""
    import json
    import urllib.request
    gran = _GRAN[interval]
    days = _RANGE_DAYS.get(rng) or int(str(rng).rstrip("d"))
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    rows = {}
    step = timedelta(seconds=gran * 300)  # 300 candles a request
    t = start
    while t < end:
        t2 = min(end, t + step)
        url = "%s/products/%s-USD/candles?granularity=%d&start=%s&end=%s" % (
            COINBASE, sym, gran, t.strftime("%Y-%m-%dT%H:%M:%SZ"), t2.strftime("%Y-%m-%dT%H:%M:%SZ"))
        req = urllib.request.Request(url, headers={"User-Agent": "trader-bot", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            for ts, lo, hi, op, cl, vol in json.loads(r.read()):
                rows[int(ts)] = (op, hi, lo, cl, vol)
        t = t2
    if not rows:
        return None
    ks = sorted(rows)
    return {"t": ks, "o": [rows[k][0] for k in ks], "h": [rows[k][1] for k in ks], "l": [rows[k][2] for k in ks],
            "c": [rows[k][3] for k in ks], "v": [rows[k][4] for k in ks], "meta": {"source": "coinbase"}}


def crypto_chart(sym, rng, interval, suffix=SUFFIX):
    """Yahoo first (what the backtests used); Coinbase when Yahoo fails or blocks (cloud servers)."""
    try:
        d = S.yahoo_chart(sym, rng, interval, suffix)
        if d and d["t"]:
            return d
    except Exception:
        pass
    return coinbase_chart(sym, rng, interval, suffix)


def universe():
    if os.path.exists(UNIVERSE_FILE):
        with open(UNIVERSE_FILE, encoding="utf-8") as fh:
            syms = [ln.split("|")[0].strip().upper().replace("-USD", "") for ln in fh
                    if ln.strip() and not ln.lstrip().startswith("#")]
        if syms:
            return S.dedup(syms), UNIVERSE_FILE
    return list(TOP), "built-in top 20"


# Decide about a candle ~1 minute after it closes (research.py crypto-live, 2 Nov 2026: entering 5 minutes late
# cost about 40% of the edge: +0.16R vs +0.27R per trade over 60 days). Yahoo often fills the just-closed
# candle's volume a few minutes late; for breakout candles whose volume is not in yet, intraday_scan asks
# Coinbase, then retries Yahoo a few times (see fill_volume) instead of delaying every scan.
SETTLE_MIN = 1
VOLUME_RETRIES = 3          # extra Yahoo tries, 45 s apart, only for breakout candles still missing volume
VOLUME_RETRY_SECONDS = 45


def last_bar_close(now_utc):
    """End time of the last 15-minute candle that closed at least SETTLE_MIN minutes ago."""
    t = (now_utc - timedelta(minutes=SETTLE_MIN)).replace(second=0, microsecond=0)
    return t - timedelta(minutes=t.minute % BAR_MIN)


def intraday_one(d, cutoff):
    bars = []
    for t, o, h, l, c, v in zip(d["t"], d.get("o") or d["c"], d["h"], d["l"], d["c"], d["v"]):
        start = datetime.fromtimestamp(t, timezone.utc)
        if start.minute % BAR_MIN or start.second:
            continue  # the live tick, off the 15-minute grid
        if start + timedelta(minutes=BAR_MIN) > cutoff:
            continue  # still forming
        bars.append((start, h, l, c, v, o))
    if len(bars) < RANGE_BARS + 2:
        return None
    last = bars[-1]
    if cutoff - (last[0] + timedelta(minutes=BAR_MIN)) > timedelta(minutes=BAR_MIN * 2):
        return None  # stale chart: candles stopped coming
    rng = bars[-1 - RANGE_BARS:-1]
    hi = max(b[1] for b in rng)
    lo = min(b[2] for b in rng)
    avg_v = sum(b[4] for b in rng) / len(rng)
    closes = [b[3] for b in bars]
    _, rsi = S.rsi14(closes)
    # "fresh": the previous candle was still inside ITS 4h range, so this candle is the cross itself
    # (the backtest only trades the cross, not every candle of a run that stays above the high)
    prev, prng = bars[-2], bars[-2 - RANGE_BARS:-2]
    fresh = {"range_breakout_4h": prev[3] <= max(b[1] for b in prng),
             "range_breakdown_4h": prev[3] >= min(b[2] for b in prng)}
    tags = []
    if last[3] > hi:
        tags.append("range_breakout_4h")
    if last[3] < lo:
        tags.append("range_breakdown_4h")
    if rsi is not None and rsi < 30:
        tags.append("oversold_15m")
    # Smart Money "liquidity sweep and reclaim" of the 4h range (smc.py), on the candle that just closed
    import smc
    sw = smc.sweep_at([(b[5] if b[5] is not None else b[3], b[1], b[2], b[3], b[4] or 0) for b in bars], len(bars) - 1)
    if sw:
        tags.append("smc_sweep_long" if sw["side"] == "long" else "smc_sweep_short")
        fresh["smc_sweep_long"] = fresh["smc_sweep_short"] = True
    # the user's SMC Trading Playbook (smc_playbook.py): sweep of PDH/PDL/CDH/CDL/swing -> doji / top hammer /
    # bottom star at the level -> this candle is candle 1 or 2 and CLOSED beyond the trigger extreme. Plus the
    # rulebook's FVG / order-block first retests (smcp_fvg_*, smcp_ob_*). The agent
    # (auto_crypto.run_smcp) applies the smcp_* settings (candle 1 only, structure, doji size, stop, target).
    pb = []
    try:
        import smc_playbook as PB
        rows = [(b[0], b[5] if b[5] is not None else b[3], b[1], b[2], b[3], b[4] or 0) for b in bars]
        ctx = PB.Context(rows, lambda t: t.date())
        i = len(rows) - 1
        for x in (PB.find_setups(ctx, i, doji_pct=0.15, near_atr=0.5, struct_lookback=48, max_confirm=2)
                  + PB.zone_setups(ctx, i)):
            if any(y["setup"] == x["setup"] for y in pb):
                continue   # the same setup from candle 1 and candle 2: keep the candle-1 one
            x = dict(x, internal_target=PB.target_for(ctx, i, x, "internal", x["entry"]),
                     external_target=PB.target_for(ctx, i, x, "external", x["entry"]))
            pb.append(x)
            tags.append("smcp_" + x["setup"])
            fresh["smcp_" + x["setup"]] = True
    except Exception:
        pb = []
    # The Scanner (v3, or v2 after a rollback in Settings): the owner's setups (v3 sweep reversal, A-B-C-D, playbook
    # with structure, FVG / order block) on this candle. The agents
    # record them (auto_crypto.process); a playbook setup ticked in enabled_setups is also traded via the hits above.
    try:
        import smc_playbook as PB2
        rows2 = [(b[0], b[5] if b[5] is not None else b[3], b[1], b[2], b[3], b[4] or 0) for b in bars]
        own = PB2.owner_setups(rows2, lambda t: t.date(), version=PB2.scanner_version("CRYPTO"))
    except Exception:
        own = []
    return {"price": last[3], "bar_end": (last[0] + timedelta(minutes=BAR_MIN)).isoformat(),
            "range_high": hi, "range_low": lo, "pct_vs_high": round((last[3] / hi - 1) * 100, 2),
            "rsi_15m": round(rsi, 1) if rsi is not None else None,
            "vol_ratio": (round(last[4] / avg_v, 2) if avg_v and last[4] else None), "tags": tags, "fresh": fresh,
            "smc": sw, "smcp": {"smcp_" + x["setup"]: x for x in pb}, "setups": own}


def sig(x):
    """Round a crypto price sensibly (BTC in dollars, SHIB in millionths)."""
    if x >= 100:
        return round(x, 2)
    if x >= 1:
        return round(x, 4)
    return float("%.6g" % x)


def fill_volume(sym, r, cutoff):
    """The breakout candle's volume ratio when Yahoo has not filled it yet: Coinbase first (coins it lists),
    then a few short Yahoo retries. Returns (vol_ratio or None, source)."""
    try:
        d = coinbase_chart(sym, "2d", "%dm" % BAR_MIN)
        r2 = intraday_one(d, cutoff) if d else None
        if r2 and r2["bar_end"] == r["bar_end"] and r2["vol_ratio"]:
            return r2["vol_ratio"], "coinbase"
    except Exception:
        pass
    import time
    for _ in range(VOLUME_RETRIES):
        time.sleep(VOLUME_RETRY_SECONDS)
        try:
            d = S.yahoo_chart(sym, "2d", "%dm" % BAR_MIN, SUFFIX)
            r2 = intraday_one(d, cutoff) if d else None
            if r2 and r2["bar_end"] == r["bar_end"] and r2["vol_ratio"]:
                return r2["vol_ratio"], "yahoo (retry)"
        except Exception:
            pass
    return None, "not reported"


def intraday_scan(symbols, now_utc, workers=6, quiet=False):
    # 5 days: the playbook's liquidity map needs yesterday's full high / low and 2 days of swing points
    data, failed = S.fetch_many(symbols, "5d", "%dm" % BAR_MIN, workers, SUFFIX, quiet, fetcher=crypto_chart)
    cutoff = last_bar_close(now_utc)
    hits, usable, coins, usable_res = [], 0, {}, []
    for s, d in data.items():
        r = intraday_one(d, cutoff)
        if r is None:
            coins[s] = {"usable": False}
            continue
        usable_res.append((s, r))
        if r["vol_ratio"] is None and any(t in ("range_breakout_4h", "range_breakdown_4h") for t in r["tags"]):
            r["vol_ratio"], r["vol_source"] = fill_volume(s, r, cutoff)
        usable += 1
        coins[s] = {"usable": True, "price": sig(r["price"]), "range_high": sig(r["range_high"]),
                    "range_low": sig(r["range_low"]), "pct_vs_high": r["pct_vs_high"],
                    "pct_vs_low": round((r["price"] / r["range_low"] - 1) * 100, 2) if r["range_low"] else None,
                    "rsi_15m": r["rsi_15m"], "vol_ratio": r["vol_ratio"], "tags": r["tags"]}
        for tag in r["tags"]:
            hits.append({"symbol": s, "market": "CRYPTO", "setup": tag, "price": sig(r["price"]),
                         "range_high": sig(r["range_high"]), "range_low": sig(r["range_low"]),
                         "pct_vs_high": r["pct_vs_high"], "rsi_15m": r["rsi_15m"],
                         "vol_ratio": r["vol_ratio"], "bar_end": r["bar_end"],
                         "fresh": r.get("fresh", {}).get(tag, True),
                         **({"smc": r["smc"]} if tag.startswith("smc_sweep") and r.get("smc") else {}),
                         **({"smcp": r["smcp"][tag]} if tag in r.get("smcp", {}) else {})})
    hits.sort(key=lambda h: (h["setup"], -h["pct_vs_high"]))
    setups = [dict(x, symbol=s, market="CRYPTO", bar_end=r["bar_end"]) for s, r in usable_res for x in r.get("setups", [])]
    return {"mode": "intraday", "market": "CRYPTO", "as_of": cutoff.isoformat(), "universe": len(symbols),
            "scanned": len(data), "failed": len(failed), "failed_symbols": failed, "usable": usable,
            "hits": hits, "coins": coins, "setups": setups}


def daily_scan(symbols, now_utc, workers=6, quiet=False):
    data, failed = S.fetch_many(symbols, "3mo", "1d", workers, SUFFIX, quiet, fetcher=crypto_chart)
    hits, last_day = [], None
    for s, d in data.items():
        rows = list(zip(d["t"], d["c"]))
        if rows and datetime.fromtimestamp(rows[-1][0], timezone.utc).date() == now_utc.date():
            rows = rows[:-1]  # today's UTC candle is still forming
        if len(rows) < 21:
            continue
        closes = [r[1] for r in rows]
        d0 = datetime.fromtimestamp(rows[-1][0], timezone.utc).date()
        last_day = max(last_day, d0) if last_day else d0
        for tag in S.daily_setups(closes):
            hits.append({"symbol": s, "market": "CRYPTO", "setup": tag, "price": sig(closes[-1])})
    return {"mode": "daily", "market": "CRYPTO", "as_of": now_utc.isoformat(),
            "closes_through": last_day.isoformat() if last_day else None, "universe": len(symbols),
            "scanned": len(data), "failed": len(failed), "hits": hits}


def main(argv=None):
    p = argparse.ArgumentParser(description="Crypto chart scanner (Yahoo -USD). Not financial advice.")
    p.add_argument("cmd", nargs="?", default="intraday", choices=["intraday", "daily"])
    p.add_argument("--symbols")
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args(argv)
    syms = ([s.strip().upper().replace("-USD", "") for s in a.symbols.split(",") if s.strip()]
            if a.symbols else universe()[0])
    now = datetime.now(timezone.utc)
    try:
        if a.cmd == "daily":
            res = daily_scan(syms, now, a.workers)
            print("Crypto daily scan, closes through %s UTC: %d of %d charts."
                  % (res["closes_through"], res["scanned"], len(syms)))
        else:
            res = intraday_scan(syms, now, a.workers)
            print("Crypto 15-minute scan, candle ending %s IST: %d of %d charts, %d usable."
                  % (datetime.fromisoformat(res["as_of"]).astimezone(S.IST).strftime("%H:%M"),
                     res["scanned"], len(syms), res["usable"]))
    except S.ScanError as e:
        print("scan_crypto.py: %s" % e)
        return 1
    for h in res["hits"]:
        extra = (" range %s-%s  %+.2f%% vs 4h high  RSI %s  vol x%s"
                 % (h["range_low"], h["range_high"], h["pct_vs_high"], h["rsi_15m"], h["vol_ratio"])
                 if "pct_vs_high" in h else "")
        print("  %-18s %-6s $%s%s" % (h["setup"], h["symbol"], h["price"], extra))
    if not res["hits"]:
        print("No setups.")
    print("Matched a rule, not a buy.")
    return 0 if res["hits"] else 1


if __name__ == "__main__":
    sys.exit(main())
