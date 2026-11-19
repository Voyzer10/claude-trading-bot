#!/usr/bin/env python3
"""Round 2 of the rules work (owner, 19 Nov 2026): which ENTRY features separate the Scanner v4 trades that work.

Runs the live v4 rules once per chart on the long broker history (research_data.py, trader/research/long/), records
each primary trade with its entry features and its R BEFORE costs, and prints, per feature bucket, out-of-sample:
trades, TP hit %, SL hit % and avg R. A filter is worth testing when its bucket is clearly better on BOTH halves.

    python research_features.py nse|us|crypto [--csv out.csv]
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import scanner_v4 as V4

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
LONG = os.path.join("trader", "research", "long")


def et_of(t):
    """US Eastern time, with daylight saving (2nd Sunday of March .. 1st Sunday of November, 2:00)."""
    y = t.year
    mar = datetime(y, 3, 8, 7, tzinfo=UTC)
    mar += timedelta(days=(6 - mar.weekday()) % 7)
    nov = datetime(y, 11, 1, 6, tzinfo=UTC)
    nov += timedelta(days=(6 - nov.weekday()) % 7)
    return t + timedelta(hours=-4 if mar <= t < nov else -5)


MARKETS = {
    "nse": {"suffix": ".NS", "local": lambda t: t.astimezone(IST), "intraday": True, "open": (9, 15)},
    "us": {"suffix": "", "local": lambda t: et_of(t).replace(tzinfo=None), "intraday": True, "open": (9, 30)},
    "crypto": {"suffix": "-USD", "local": lambda t: t, "intraday": False, "open": (0, 0)},
}


def load(market):
    m = MARKETS[market]
    out = {}
    for f in sorted(os.listdir(LONG)):
        if not f.endswith("_5m.json"):
            continue
        name = f[:-8]
        if market == "crypto" and not name.endswith("-USD"):
            continue
        if market == "nse" and not name.endswith(".NS"):
            continue
        if market == "us" and (name.endswith(".NS") or name.endswith("-USD")):
            continue
        with open(os.path.join(LONG, f), encoding="utf-8") as fh:
            d = json.load(fh)
        rows = [(datetime.fromtimestamp(t, UTC), o, h, l, c, v or 0) for t, o, h, l, c, v in
                zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"]) if None not in (o, h, l, c)]
        if market != "crypto":                   # regular session only
            lo = m["local"]
            op = m["open"]
            close = (15, 30) if market == "nse" else (16, 0)
            rows = [r for r in rows if op <= (lo(r[0]).hour, lo(r[0]).minute) < close]
        if len(rows) > 500:
            out[name.replace(m["suffix"], "") if m["suffix"] else name] = rows
    return out


def ema(xs, n):
    k, out, e = 2.0 / (n + 1), [], None
    for x in xs:
        e = x if e is None else e + k * (x - e)
        out.append(e)
    return out


def features(rows, t, local, open_hm):
    """Entry features of one trade (side-aware: +1 = with the trade)."""
    i, sg = t["i"], (1 if t["side"] == "long" else -1)
    c = [r[4] for r in rows]
    a = t.get("atr") or 0
    risk = abs(t["entry"] - t["stop"])
    lt = local(rows[i][0])
    f = {"side": t["side"], "pattern": t.get("signal_pattern") or "?", "level": t.get("level_name") or "?",
         "hour": lt.hour, "min_from_open": (lt.hour - open_hm[0]) * 60 + lt.minute - open_hm[1],
         "weekday": lt.weekday(), "risk_pct": 100.0 * risk / t["entry"], "risk_atr": risk / a if a else 0,
         "plan_rr": abs(t["target"] - t["entry"]) / risk if risk else 0}
    b, sw, s = t.get("bos"), t.get("sweep"), t.get("signal")
    if b is not None:
        o_, h_, l_, c_ = rows[b][1:5]
        f["bos_body_atr"] = abs(c_ - o_) / a if a else 0
        vols = [r[5] for r in rows[max(0, b - 20):b]]
        f["bos_vol_x"] = rows[b][5] / (sum(vols) / len(vols)) if vols and sum(vols) else 0
        f["bos_age"] = i - b
    if sw is not None and s is not None:
        f["sweep_to_signal"] = s - sw
        o_, h_, l_, c_ = rows[sw][1:5]
        rng = (h_ - l_) or 1e-9
        # how much of the sweep candle closed back toward the trade (1 = closed at the far end: a full rejection)
        f["sweep_reject"] = ((c_ - l_) / rng) if sg > 0 else ((h_ - c_) / rng)
    for n, key in ((50, "ema50"), (200, "ema200"), (600, "ema600")):
        f[key] = sg * (c[i] - EMA_CACHE[key][i]) / (a or 1)     # distance from the EMA, in ATRs, with the trade = +
    f["trend_200_600"] = sg * (1 if EMA_CACHE["ema200"][i] > EMA_CACHE["ema600"][i] else -1)
    day0 = max(0, i - 78)
    f["day_move_atr"] = sg * (c[i] - c[day0]) / (a or 1)
    return f


EMA_CACHE = {}


def run(market):
    m = MARKETS[market]
    data = load(market)
    tm = {}
    try:
        import paper as P
        acc = {"nse": "INDIA", "us": "US", "crypto": "CRYPTO"}[market]
        tm = V4.tm_settings(P.load_config()["accounts"].get(acc, {}))
    except Exception:
        pass
    day_of = (lambda t: m["local"](t).date())
    out = []
    for sym, rows in data.items():
        c = [r[4] for r in rows]
        EMA_CACHE.update(ema50=ema(c, 50), ema200=ema(c, 200), ema600=ema(c, 600))
        try:
            seq = V4.sequence(rows, day_of, intraday=m["intraday"], max_hold=None, **tm)
        except Exception as e:
            print("  %s: %s" % (sym, e), file=sys.stderr)
            continue
        for t in seq:
            if t.get("exit") is None or t["kind"] != "primary":
                continue
            sg = 1 if t["side"] == "long" else -1
            risk = (t["entry"] - t["stop"]) * sg
            if risk <= 0:
                continue
            e = {"sym": sym, "day": day_of(rows[t["i"]][0]).isoformat(), "r": (t["exit"] - t["entry"]) * sg / risk,
                 "exit": t["exit_reason"]}
            e.update(features(rows, t, m["local"], m["open"]))
            out.append(e)
        print("  %-10s %4d trades" % (sym, sum(1 for x in out if x["sym"] == sym)), file=sys.stderr, flush=True)
    return out


BUCKETS = {
    "side": None, "pattern": None, "level": None, "weekday": None, "trend_200_600": None,
    "hour": None,
    "min_from_open": [15, 30, 60, 120, 240, 10 ** 6],
    "risk_pct": [0.15, 0.25, 0.4, 0.6, 1.0, 10 ** 6],
    "risk_atr": [0.5, 1.0, 1.5, 2.5, 10 ** 6],
    "plan_rr": [1.0, 1.5, 2.0, 3.0, 10 ** 6],
    "bos_body_atr": [0.3, 0.6, 1.0, 1.5, 10 ** 6],
    "bos_vol_x": [0.8, 1.2, 2.0, 10 ** 6],
    "bos_age": [12, 36, 78, 156, 10 ** 6],
    "sweep_to_signal": [0, 1, 3, 6, 12, 10 ** 6],
    "sweep_reject": [0.2, 0.4, 0.6, 0.8, 1.01],
    "ema50": [-2, -0.5, 0, 0.5, 2, 10 ** 6],
    "ema200": [-3, -1, 0, 1, 3, 10 ** 6],
    "ema600": [-5, -2, 0, 2, 5, 10 ** 6],
    "day_move_atr": [-6, -2, 0, 2, 6, 10 ** 6],
}


def bucket(v, edges):
    if edges is None:
        return v
    lo = "-inf"
    for e in edges:
        if v < e:
            return "%s..%s" % (lo, e if e < 10 ** 5 else "inf")
        lo = e
    return ">=%s" % lo


def report(evs, title):
    days = sorted({e["day"] for e in evs})
    split = days[int(len(days) * 0.7)]
    lines = ["%s: %d primary trades, %s..%s; in-sample before %s, out-of-sample from it. R BEFORE costs." % (
        title, len(evs), days[0], days[-1], split), ""]
    base_in = [e["r"] for e in evs if e["day"] < split]
    base_out = [e["r"] for e in evs if e["day"] >= split]
    lines.append("ALL: in %d tr avg %+.3fR | out %d tr avg %+.3fR" % (
        len(base_in), sum(base_in) / max(1, len(base_in)), len(base_out), sum(base_out) / max(1, len(base_out))))
    for feat, edges in BUCKETS.items():
        g = {}
        for e in evs:
            if feat not in e:
                continue
            k = bucket(e[feat], edges)
            g.setdefault(k, {"in": [], "out": [], "tp": 0, "sl": 0})
            g[k]["in" if e["day"] < split else "out"].append(e["r"])
            if e["day"] >= split:
                g[k]["tp"] += e["exit"] == "target"
                g[k]["sl"] += e["exit"] in ("stop", "stop (gapped past it)")
        lines += ["", "%s:" % feat, "  %-16s %6s %8s | %6s %6s %6s %8s" % ("bucket", "in tr", "in avg", "out tr",
                                                                          "TP", "SL", "out avg")]
        for k in sorted(g, key=lambda x: (str(type(x)), x if not isinstance(x, str) else
                                          float(x.split("..")[0].replace("-inf", "-1e9").replace(">=", "")) if
                                          (".." in x or x.startswith(">=")) else 0, str(x))):
            v = g[k]
            ni, no = len(v["in"]), len(v["out"])
            if ni + no < 50:
                continue
            ai = sum(v["in"]) / ni if ni else 0
            ao = sum(v["out"]) / no if no else 0
            mark = "  <== both halves >= +0.10R" if ai >= 0.10 and ao >= 0.10 and ni >= 100 and no >= 50 else ""
            lines.append("  %-16s %6d %+7.3fR | %6d %5.0f%% %5.0f%% %+7.3fR%s" % (
                str(k), ni, ai, no, 100.0 * v["tp"] / max(1, no), 100.0 * v["sl"] / max(1, no), ao, mark))
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("market", choices=list(MARKETS))
    p.add_argument("--csv")
    a = p.parse_args(argv)
    evs = run(a.market)
    if a.csv:
        keys = sorted({k for e in evs for k in e})
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(evs)
    print(report(evs, a.market))


if __name__ == "__main__":
    main()
