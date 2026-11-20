"""Parity prep: the same historical candles and the same Scanner v4 setup candidates for both code versions.
python prep.py REPO LONGDIR OUT.pkl"""
import json, os, pickle, sys, time
from datetime import datetime, timedelta, timezone
repo, longdir, out = sys.argv[1:4]
sys.path.insert(0, repo)
import smc_playbook as S
import scanner_v4 as V4
UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
def et_of(t):
    y = t.year
    mar = datetime(y, 3, 8, 7, tzinfo=UTC); mar += timedelta(days=(6 - mar.weekday()) % 7)
    nov = datetime(y, 11, 1, 6, tzinfo=UTC); nov += timedelta(days=(6 - nov.weekday()) % 7)
    return t + timedelta(hours=-4 if mar <= t < nov else -5)
MK = {"CRYPTO": (["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE"], "-USD", None, lambda t: t.date(), False),
      "US": (["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"], "", ((9, 30), (16, 0)), lambda t: et_of(t).date(), True),
      "NSE": (["RELIANCE", "HDFCBANK", "INFY", "TCS", "SBIN", "TATASTEEL"], ".NS", ((9, 15), (15, 30)),
              lambda t: t.astimezone(IST).date(), True)}
N = int(os.environ.get("PARITY_ROWS", "1500"))
data = {}
for m, (syms, suf, sess, day_of, intraday) in MK.items():
    for s in syms:
        d = json.load(open(os.path.join(longdir, s + suf + "_5m.json")))
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]) if None not in (o, h, l, c)]
        if sess:
            loc = (lambda t: et_of(t)) if m == "US" else (lambda t: t.astimezone(IST))
            rows = [r for r in rows if sess[0] <= (loc(r[0]).hour, loc(r[0]).minute) < sess[1]]
        rows = rows[-N:]
        t0 = time.time()
        idx = sorted({t["i"] for t in V4.sequence(rows, day_of, intraday=intraday)})
        cands = []
        for i in idx:
            for c in S.v4_setups(rows[:i + 1], day_of, i, intraday=intraday):
                cands.append({"i": i, "s": c})
        data[(m, s)] = {"rows": rows, "cands": cands}
        print(m, s, len(rows), "candidates", len(cands), "%.0fs" % (time.time() - t0), flush=True)
pickle.dump(data, open(out, "wb"))
