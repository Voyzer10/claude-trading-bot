#!/usr/bin/env python3
"""Round 3 of the rules work (owner, 19 Nov 2026): the same Scanner v4 rules on bigger candles (15m, 1h).

On 5-minute candles the stops are small, so costs take ~0.2-0.3R a trade and many BOS / sweeps are noise. This
builds 15-minute and 1-hour candles from the long broker history (research_data.py), runs the live v4 rules and the
account's Trade Manager on them, and prints the rules table: trades, TP / SL hit, avg R before costs (in- and
out-of-sample) and an approximate R after costs.

    python research_tf.py nse|us|crypto [--tf 5,15,60]

Costs (approximate, a round trip, % of the price): NSE intraday 0.06, US 0.02 (spread / slippage), crypto 0.118.
"""
import argparse
from datetime import datetime, timedelta, timezone

import research_costs as RC
import research_features as F
import scanner_v4 as V4

COST_PCT = {"nse": 0.06, "us": 0.02, "crypto": 0.118}
SPLIT = {"nse": "2026-08-04", "us": "2026-08-04", "crypto": "2026-09-26"}
PASS_R = 0.15


def resample(rows, minutes, local, open_hm):
    """5-minute rows -> `minutes` candles, anchored at the session open (local time) so a bar never spans two days."""
    if minutes == 5:
        return rows
    out, key, cur = [], None, None
    for t, o, h, l, c, v in rows:
        lt = local(t)
        m = (lt.hour * 60 + lt.minute) - (open_hm[0] * 60 + open_hm[1])
        k = (lt.date(), m // minutes)
        if k != key:
            if cur:
                out.append(tuple(cur))
            key, cur = k, [t, o, h, l, c, v]
        else:
            cur[2], cur[3], cur[4], cur[5] = max(cur[2], h), min(cur[3], l), c, cur[5] + v
    if cur:
        out.append(tuple(cur))
    return out


def run(market, minutes):
    m = F.MARKETS[market]
    data = F.load(market)
    tm = {}
    try:
        import paper as P
        tm = V4.tm_settings(P.load_config()["accounts"].get({"nse": "INDIA", "us": "US", "crypto": "CRYPTO"}[market], {}))
    except Exception:
        pass
    day_of = (lambda t: m["local"](t).date())
    evs = []
    for sym, rows in data.items():
        bars = resample(rows, minutes, m["local"], m["open"])
        if len(bars) < 300:
            continue
        try:
            seq = V4.sequence(bars, day_of, intraday=m["intraday"], max_hold=None, **tm)
        except Exception:
            continue
        for t in seq:
            if t.get("exit") is None or t["kind"] != "primary":
                continue
            sg = 1 if t["side"] == "long" else -1
            risk = (t["entry"] - t["stop"]) * sg
            if risk <= 0:
                continue
            g = (t["exit"] - t["entry"]) * sg / risk
            cost = RC.cost_r(market, sym, t["side"], t["entry"], t["exit"], t["stop"])   # research_costs (21 Nov)
            evs.append({"day": day_of(bars[t["i"]][0]).isoformat(), "r": g, "net": None if cost is None else g - cost,
                        "exit": t["exit_reason"],
                        "risk_pct": 100 * risk / t["entry"]})
    return evs


def row(name, evs, split):
    ins = [e for e in evs if e["day"] < split]
    out = [e for e in evs if e["day"] >= split]
    if not out:
        return "  %-10s no trades" % name
    n = len(out)
    tp = sum(1 for e in out if e["exit"] == "target")
    sl = sum(1 for e in out if e["exit"] in ("stop", "stop (gapped past it)"))
    g = sum(e["r"] for e in out) / n
    gi = sum(e["r"] for e in ins) / len(ins) if ins else 0
    nn = [e["net"] for e in out if e["net"] is not None]          # NSE: trades the INDIA sizing cannot size: no net
    net = sum(nn) / len(nn) if nn else float("nan")
    stop = sorted(e["risk_pct"] for e in out)[n // 2]
    return "  %-10s %6d %6.0f%% %6.0f%% %+7.2fR %+8.2fR %+8.2fR %7.2f%%%s" % (
        name, n, 100.0 * tp / n, 100.0 * sl / n, g, gi, net, stop,
        "  PASS" if g >= PASS_R and gi >= PASS_R and n >= 300 else "")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("market", choices=list(F.MARKETS))
    p.add_argument("--tf", default="5,15,60")
    a = p.parse_args(argv)
    split = SPLIT[a.market]
    print("%s: Scanner v4 (live defaults) on bigger candles; out-of-sample from %s; costs: research_costs (%s)" % (
        a.market, split, {"nse": "paper.charges, INDIA sizing", "us": "fee_pct + 0.02%/side", "crypto": "%.3f%% round "
                          "trip, unverified" % COST_PCT["crypto"]}[a.market]))
    print("  %-10s %6s %7s %7s %8s %9s %9s %8s" % ("candles", "trades", "TP hit", "SL hit", "avg R", "in-sample",
                                                  "after c.", "med stop"))
    for tf in [int(x) for x in a.tf.split(",")]:
        print(row("%dm" % tf if tf < 60 else "%dh" % (tf // 60), run(a.market, tf), split), flush=True)


if __name__ == "__main__":
    main()
