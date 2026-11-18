#!/usr/bin/env python3
"""Live prices for open positions never freeze (owner's report, 5 Nov 2026: US quotes stayed the same for 15+
minutes while crypto moved). Offline: Yahoo answers are faked.

    python tests/test_quotes.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def chart(meta_price, meta_age_min, bars):
    """A Yahoo chart answer: meta price at now - meta_age_min, and 1-minute closes [(minutes ago, close)]."""
    now = datetime.now(timezone.utc).timestamp()
    return {"chart": {"result": [{"meta": {"regularMarketPrice": meta_price,
                                           "regularMarketTime": int(now - meta_age_min * 60)},
                                  "timestamp": [int(now - a * 60) for a, _ in bars],
                                  "indicators": {"quote": [{"close": [c for _, c in bars]}]}}]}}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        seen = []
        answer = {}

        def fake_urlopen(req, timeout=0):
            seen.append(req.full_url)
            return Resp(json.dumps(answer["doc"]).encode())
        P.urllib.request.urlopen = fake_urlopen

        answer["doc"] = chart(343.47, 20, [(5, 344.9), (2, 345.6)])
        price, qt = P.fetch_price("CRYPTO", "TST")
        check("1. meta price 20 min old, a 1-minute close 2 min old -> the newer one (345.6)", price == 345.6, (price, qt))
        check("   every request is unique (cache-buster), so no cache can return an old answer",
              "&_=" in seen[-1], seen[-1])

        answer["doc"] = chart(100.5, 0.2, [(3, 99.0)])
        check("2. meta price fresher than the last candle -> meta (100.5)", P.fetch_price("CRYPTO", "TST")[0] == 100.5)

        # an open US session where the 1-minute answer is stale: the 5-minute chart (what the scanner uses) wins
        answer["doc"] = chart(343.47, 25, [(25, 343.47)])
        P.session = lambda m, now: "open"
        import scan_nse as SN
        now = datetime.now(timezone.utc).timestamp()
        SN.yahoo_chart = lambda sym, rng, iv, suffix="": {"t": [int(now - 600), int(now - 300)], "c": [346.0, 347.25],
                                                          "o": [], "h": [], "l": [], "v": [], "meta": {}}
        price, qt = P.fetch_price("US", "TSLA")
        check("3. US open, quote 25 min old -> fresh 5-minute close 347.25", price == 347.25, (price, qt))
        P.session = lambda m, now: "closed"
        price, _ = P.fetch_price("US", "TSLA")
        check("4. market closed: the last quote stands (no fallback)", price == 343.47, price)

        # Yahoo AND its 5-minute chart frozen (what the VPS saw: 87 min old): Nasdaq / Stooq backups decide
        SN.yahoo_chart = lambda sym, rng, iv, suffix="": {"t": [int(now - 87 * 60)], "c": [343.47], "o": [], "h": [],
                                                          "l": [], "v": [], "meta": {}}
        et_now = datetime.now(timezone.utc) + P.us_offset(datetime.now(timezone.utc))
        nas_ts = (et_now - timedelta(minutes=1)).strftime("%b %d, %Y %I:%M %p").replace(" 0", " ") + " ET"
        nasdaq_doc = {"data": {"symbol": "TSLA", "primaryData": {"lastSalePrice": "$351.12", "lastTradeTimestamp": nas_ts}}}
        q = P._nasdaq_quote("TSLA", opener=lambda req, timeout=0: Resp(json.dumps(nasdaq_doc).encode()))
        check("5. Nasdaq quote parsed: price and an ET trade time turned into UTC (about 1 min ago)",
              q and q[0] == 351.12 and abs((datetime.now(timezone.utc) - q[1]).total_seconds() - 60) < 120, (q, nas_ts))
        from zoneinfo import ZoneInfo
        pl = datetime.now(ZoneInfo("Europe/Warsaw")) - timedelta(minutes=3)
        csv_txt = "Symbol,Date,Time,Close\nTSLA.US,%s,%s,350.80\n" % (pl.strftime("%Y-%m-%d"), pl.strftime("%H:%M:%S"))
        sq = P._stooq_quote("TSLA", opener=lambda req, timeout=0: Resp(csv_txt.encode()))
        check("6. Stooq quote parsed (Polish time -> UTC, about 3 min ago)",
              sq and sq[0] == 350.8 and abs((datetime.now(timezone.utc) - sq[1]).total_seconds() - 180) < 120, sq)
        nodate = {"data": {"primaryData": {"lastSalePrice": "$341.03", "lastTradeTimestamp": "N/A"}}}
        real_nq, real_sq = P._nasdaq_quote, P._stooq_quote
        P._nasdaq_quote = lambda t, opener=None: real_nq(t, opener=lambda req, timeout=0: Resp(json.dumps(nodate).encode()))
        P._stooq_quote = lambda t, opener=None: real_sq(t, opener=lambda req, timeout=0: Resp(b"<meta charset=utf-8>Stooq page does not exist"))
        bq = P.us_backup_quote("TSLA")
        check("   Nasdaq price without a readable time still counts (as now); Stooq's error page is ignored",
              bq and bq[0] == 341.03, bq)
        P._nasdaq_quote = lambda t, opener=None: q
        P._stooq_quote = lambda t, opener=None: sq
        P.session = lambda m, now: "open"
        answer["doc"] = chart(343.47, 87, [(87, 343.47)])
        price, qt = P.fetch_price("US", "TSLA")
        check("7. Yahoo frozen 87 min, US open -> the newest backup (Nasdaq 351.12)", price == 351.12, (price, qt))
        P.urllib.request.urlopen = lambda req, timeout=0: (_ for _ in ()).throw(OSError("yahoo down"))
        check("8. Yahoo down -> backup quote", P.fetch_price("US", "TSLA")[0] == 351.12)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
