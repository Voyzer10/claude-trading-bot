#!/usr/bin/env python3
"""research_cohortb_v4 (21 Nov 2026): the cohort-B profitability dataset and its statistics. Offline.

    python tests/test_cohortb.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import research_cohortb_v4 as CB  # noqa: E402
import research_costs as RC  # noqa: E402
import research_sweep_quality_v4 as SQ  # noqa: E402
import scanner_v4 as V4  # noqa: E402
from test_choch_lifecycle import rows_of, reflect  # noqa: E402
from test_entry_models import RETEST  # noqa: E402

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


if __name__ == "__main__":
    s = CB.spearman([1, 2, 3, 4, 5, 6], [2, 4, 6, 8, 10, 12])
    check("spearman: a monotone pair -> rho ~ 1", s and s[0] > 0.999, s)
    s = CB.spearman([1, 2, 3, 4, 5, 6], [6, 5, 4, 3, 2, 1])
    check("spearman: reversed -> rho ~ -1", s and s[0] < -0.999, s)
    e = CB.is_edges([0, 0, 0, 0, 0, 1, 2, 3])
    check("IS quartile edges keep the many zeros in bin 0 (value == edge -> lower bin)",
          CB.bin_of(e, 0) == 0 and CB.bin_of(e, 3) == len(e) and CB.bin_of(e, 99) == len(e), e)
    check("binary features: one edge 0.5 -> bins 0 / 1", CB.is_edges([0, 1, 1], True) == [0.5]
          and CB.bin_of([0.5], 0) == 0 and CB.bin_of([0.5], 1) == 1)
    q = CB.bh([0.01, 0.04, 0.03, 0.5])
    check("Benjamini-Hochberg q-values", [round(x, 4) for x in q] == [0.04, 0.0533, 0.0533, 0.5], q)
    # the dataset on a hand-built chart (crypto market key: no session, the harness cost)
    for tag in ("bull", "bear"):
        cands = RETEST
        rows = rows_of(cands)
        if tag == "bear":
            rows = reflect(rows)
        sym, out, checks = CB.chart(("crypto", "TEST", rows, {}, 3))
        check("%s: one closed E1 trade -> one dataset row; the prefix re-run gives identical features" % tag,
              len(out) == 1 and checks == [True], (out, checks))
        if out:
            r = out[0]
            sw = []
            V4.sequence(rows, lambda t: t.date(), intraday=False, sweep_rule="internal", sweep_max_bars=12,
                        sweep_pen_atr=0.25, entry_max_bars=12, _sweeps=sw)
            sd, st, j0 = sw[0]
            f = SQ.features(sd, st, j0, tag == "bear")
            check("%s: features = research_sweep_quality_v4.features at the sweep candle; net = gross - cost once" % tag,
                  all(r["f"][k] == f[k] for k in CB.FEATS) and abs(r["net"] - (r["gross"] - r["cost"])) < 1e-12
                  and r["side"] == ("short" if tag == "bear" else "long") and r["sweep"] == 55 and r["decide"] == 57,
                  r)
    print("\n%d failed" % len(FAILS) if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)
