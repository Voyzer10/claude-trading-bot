#!/usr/bin/env python3
"""
tm_test.py - does the time machine's HISTORY gate help? Shared by research_v4.py (crypto) and research_nse2.py (NSE).

The live time machine looks back at "every past time the same rule fired on this coin / stock" and skips the trade
when that record is bad (NSE: average under +0.10R over 10+ past fires; crypto: recorded only, not a gate). Here
every backtest trade gets the same view of ITS OWN past: the same rule's results on the same symbol, on earlier
days only, within a lookback window. Then each gate setting splits the trades into "kept" and "removed".

A useful gate removes trades that, on average, LOSE (removed avg < kept avg, and removed avg < 0) out-of-sample.
A gate whose removed trades did as well as the kept ones only throws trades away.

The replay half of the time machine (2,000 random re-runs of the rest of the day) is not modelled: running it for
thousands of past trades would take hours.
"""
from datetime import date

LOOKBACKS = (20, 40, 60)
# (label, lookback days, minimum average R, minimum past fires to judge)
GATES = [
    ("history >= 0R, 20 days, 5+ fires", 20, 0.0, 5),
    ("history >= +0.10R, 20 days, 5+ fires", 20, 0.10, 5),
    ("history >= 0R, 40 days, 5+ fires", 40, 0.0, 5),
    ("history >= +0.10R, 40 days, 5+ fires", 40, 0.10, 5),
    ("history >= +0.10R, 60 days, 10+ fires (like live NSE)", 60, 0.10, 10),
    ("history >= -0.10R, 40 days, 5+ fires", 40, -0.10, 5),
]


def add_history(events, lookbacks=LOOKBACKS):
    """ev["hist"][(key, L)] = (fires, avg R) of the same outcome key on the same symbol (and range length, if
    any) over the L days before the event's day (earlier days only). Events need "sym", "day" (ISO), "out"."""
    by = {}
    for ev in events:
        by.setdefault((ev["sym"], ev.get("range")), []).append(ev)
    for evs in by.values():
        evs.sort(key=lambda e: e["day"])
        ords = [date.fromisoformat(e["day"]).toordinal() for e in evs]
        keys = {k for e in evs for k in e["out"]}
        for ev in evs:
            ev["hist"] = {}
        for key in keys:
            for L in lookbacks:
                lo = hi = 0          # window [lo, hi) = earlier events within L days
                tot, cnt = 0.0, 0
                for i, ev in enumerate(evs):
                    d0 = ords[i]
                    while hi < i and ords[hi] < d0:          # add events of earlier days
                        if key in evs[hi]["out"]:
                            tot += evs[hi]["out"][key]
                            cnt += 1
                        hi += 1
                    while lo < hi and ords[lo] < d0 - L:     # drop events older than the window
                        if key in evs[lo]["out"]:
                            tot -= evs[lo]["out"][key]
                            cnt -= 1
                        lo += 1
                    ev["hist"][(key, L)] = (cnt, tot / cnt if cnt else None)
    return events


def _split(events, f, key, keep, gate):
    _, L, min_avg, min_n = gate
    kept, removed = [], []
    for ev in events:
        if not keep(ev, f):
            continue
        n, avg = ev.get("hist", {}).get((key, L), (0, None))
        (removed if n >= min_n and avg is not None and avg < min_avg else kept).append(ev)
    return kept, removed


def _stats(evs, key, split, stats):
    ins, oos = {}, {}
    for ev in evs:
        (ins if ev["day"] < split else oos).setdefault(ev["day"], []).append(ev["out"][key])
    return stats(ins), stats(oos)


def _fmt(x):
    if not x.get("trades"):
        return "   0 tr"
    return "%4d tr avg %+.2fR total %+6.1fR" % (x["trades"], x["avg_r"], x["total_r"])


def section(events, f, key, keep, split, stats, name):
    """Report lines: the rule f with no history gate, then each gate (kept vs removed, in- and out-of-sample)."""
    lines = ["TIME MACHINE TEST on %s (history gate; the trades it REMOVES should be the losers):" % name]
    ins, oos = _stats([e for e in events if keep(e, f)], key, split, stats)
    lines.append("  %-52s in %s | OUT %s" % ("no gate (every trade)", _fmt(ins), _fmt(oos)))
    for gate in GATES:
        kept, removed = _split(events, f, key, keep, gate)
        ki, ko = _stats(kept, key, split, stats)
        ri, ro = _stats(removed, key, split, stats)
        verdict = ""
        if ro.get("trades", 0) >= 5 and ko.get("trades"):
            if ro["avg_r"] < 0 and ro["avg_r"] < ko["avg_r"] - 0.05:
                verdict = "  <- removes losers (helps)"
            elif ro["avg_r"] < ko["avg_r"] - 0.10:
                verdict = "  <- removes weaker trades (still positive: costs total R)"
            elif ro["avg_r"] > ko["avg_r"] + 0.05:
                verdict = "  <- removes winners (hurts)"
            else:
                verdict = "  <- no clear effect"
        lines.append("  %-52s kept in %s | OUT %s" % (gate[0], _fmt(ki), _fmt(ko)))
        lines.append("  %-52s  removed  %s |     %s%s" % ("", _fmt(ri), _fmt(ro), verdict))
    return lines
