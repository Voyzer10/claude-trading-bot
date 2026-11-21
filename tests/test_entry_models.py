#!/usr/bin/env python3
"""research_entry_v4 (21 Nov 2026): three entry models on the SAME published internal-sweep setup, bull and mirrored
bear. E1 = the scanner's own confirmation (signal candle after the sweep, break and close, next-open fill); E2 = the
first candle closing in the setup's direction above the sweep candle's high; E3 = a limit at E1's broken level.
Shared: cancel on a close beyond the protected swing / CHoCH / newer BOS / session end; the scanner's stop and target
rules; no look-ahead. Offline.

    python tests/test_entry_models.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import scanner_v4 as V4  # noqa: E402
import research_entry_v4 as E  # noqa: E402
from test_choch_lifecycle import rows_of, reflect  # noqa: E402
from test_v4_internal_sweep import CH  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


V = CH["valid"][:58]                     # BOS 47, sweep 55 (high 104.9), doji 56 (high 104.2), break 57 (close 104.5)
RETEST = V + [(104.5, 104.6, 104.1, 104.4), (104.4, 105.3, 104.35, 105.2), (105.2, 105.4, 105.0, 105.3),
              (105.3, 105.5, 103.0, 103.1)]
# after the break: no candle trades back to 104.2 for 12 candles, then a stop-out
NO_RETEST = V + [(104.5, 104.8, 104.3, 104.7)] * 13 + [(104.7, 104.8, 103.0, 103.1)]
# after the break, 58 OPENS at 101.0 (a gap through the stop and the protected HL): no fill at the limit
GAP = V + [(101.0, 101.2, 100.8, 101.1), (101.1, 101.3, 100.9, 101.2)]
# after the break, price runs above the leg top 106.2 (a newer BOS at 59) without revisiting 104.2
NEWBOS = V + [(104.5, 105.2, 104.4, 105.1), (105.1, 106.6, 105.0, 106.5), (106.5, 106.7, 106.3, 106.6)]


def models(cands, tag):
    rows = rows_of(cands)
    if tag == "bear":
        rows = reflect(rows)
    sw = []
    seq = V4.sequence(rows, lambda t: t.date(), intraday=False, sweep_rule="internal", _sweeps=sw)
    return rows, sw, seq


def suite(tag):
    T = "%s:" % tag
    rows, sw, seq = models(RETEST, tag)
    check("%s the scanner publishes one swept setup (BOS 47, sweep 55)" % T,
          [(st["bos"], j0) for _sd, st, j0 in sw] == [(47, 55)], [(st["bos"], j0) for _sd, st, j0 in sw])
    sd, st, j0 = sw[0]
    r = E.setup_trades(sd, st, j0, False)
    e1, e2, e3 = (r[m]["trade"] for m in E.MODELS)
    eng = [t for t in seq if t["kind"] == "primary"]
    check("%s E1 = the scanner's own decision: candle 57, fill at 58's open, same stop and target as the engine" % T,
          e1 and eng and e1["decide"] == eng[0]["i"] == 57 and e1["fill"] == 58
          and abs(e1["entry"] - rows[58][1] * (1 if tag == "bull" else -1)) < 1e-9
          and abs(e1["stop"] - (eng[0]["stop"] * (1 if tag == "bull" else -1))) < 1e-9
          and abs(e1["target"] - (eng[0]["target"] * (1 if tag == "bull" else -1))) < 1e-9, (e1, eng[:1]))
    check("%s E2: the first candle closing up and above the sweep high 104.9 is 59 (57 closes 104.5 below it); "
          "fill at 60's open" % T, e2 and e2["decide"] == 59 and e2["fill"] == 60, e2)
    check("%s E3: a limit at the broken doji high 104.2 fills on 58 (low 104.1) at 104.2, with E1's stop" % T,
          e3 and e3["fill"] == 58 and abs(e3["entry"] - (104.2 if tag == "bull" else -(210 - 104.2))) < 1e-9
          and abs(e3["stop"] - e1["stop"]) < 1e-9, e3)
    check("%s no model decides before the sweep's next candle or on the CHoCH / sweep candle" % T,
          all(t["decide"] > j0 for t in (e1, e2, e3) if t))
    check("%s same target methodology for all three (opposite-BOS / big-swing target)" % T,
          len({round(t["target"], 9) for t in (e1, e2, e3)}) == 1, [t["target"] for t in (e1, e2, e3)])
    # no retest -> missed
    rows, sw, _ = models(NO_RETEST, tag)
    r = E.setup_trades(*sw[0], False)
    check("%s E3 missed when price never revisits the level within 12 candles; E1 still trades" % T,
          r["E3 retest"]["trade"] is None and r["E3 retest"]["why"].startswith("no retest within 12")
          and r["E1 control"]["trade"] is not None, {k: v["why"] for k, v in r.items()})
    # (a close beyond the protected HL must trade through the higher limit level first, so for E3 the structural
    # cancels that can come first are a gap through the stop and a newer BOS)
    rows, sw, _ = models(GAP, tag)
    r = E.setup_trades(*sw[0], False)
    check("%s E3 not filled: the next candle opens through the stop and the protected HL" % T,
          r["E3 retest"]["trade"] is None and r["E3 retest"]["why"] == "gapped through the stop before a fill",
          r["E3 retest"]["why"])
    rows, sw, _ = models(NEWBOS, tag)
    r = E.setup_trades(*sw[0], False)
    check("%s E3 cancelled: a newer BOS (59) before any retest" % T,
          r["E3 retest"]["trade"] is None and r["E3 retest"]["why"] == "superseded by a newer BOS before a retest",
          r["E3 retest"]["why"])
    # no look-ahead: decisions on a prefix that ends right after the decision candle are the same
    rows, sw, _ = models(RETEST, tag)
    full = E.setup_trades(*sw[0], False)
    for name, cut in (("E1 control", 58), ("E2 strong", 60)):
        rows2, sw2, _ = models(RETEST[:cut + 1], tag)
        pre = E.setup_trades(*sw2[0], False)
        a, b = full[name]["trade"], pre[name]["trade"]
        check("%s no look-ahead (%s): the same decision, fill and stop on the prefix to candle %d" % (T, name, cut),
              a and (b is None or (b["decide"], b["fill"], round(b["stop"], 9)) == (a["decide"], a["fill"], round(a["stop"], 9)))
              and (b is not None or pre[name]["why"] == "still open at the end of the data"),
              (a and (a["decide"], a["fill"]), pre[name]["why"]))


if __name__ == "__main__":
    suite("bull")
    suite("bear")
    print("\n%d failed" % len(FAILS) if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
