#!/usr/bin/env python3
"""Scanner v6 as a V4 Scanner version (owner, 25 Nov 2026: a Settings option to switch an account's Scanner to V6).
Offline; the price path is the SYNTHETIC Module E test path (tests/v6_runtime/fixtures/synth_nyse_5m.csv).

    python tests/test_scanner_v6_option.py
"""
import csv
import os
import shutil
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import scanner_v6_bridge as V6B  # noqa: E402
import smc_playbook as PB  # noqa: E402

FAILS = []
DAY = lambda x: x.date()  # noqa: E731


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def rows():
    with open(os.path.join(ROOT, "tests", "v6_runtime", "fixtures", "synth_nyse_5m.csv")) as fh:
        return [(datetime.fromisoformat(r[0].replace("Z", "+00:00")),) + tuple(float(x) for x in r[1:])
                for r in list(csv.reader(fh))[1:]]


if __name__ == "__main__":
    R = rows()
    check("1. v6 is a Scanner version (Settings choice), setups are v6_ and trade only their own version",
          "v6" in PB.SCANNER_VERSIONS and "v6" in PB.OWN_ONLY and PB.setup_version("v6_smc_long") == "v6"
          and PB.setup_version("v5_level_long") == "v5")
    import api._ops as OPS
    check("   Settings > Risk limits offers v6 and its two price settings",
          "v6" in OPS.RISK_FIELDS["scanner_version"]["choices"] and "v6_sl_buffer_ticks" in OPS.RISK_FIELDS
          and OPS.RISK_FIELDS["v6_setups"]["choices"] == PB.V6_SETUPS)
    found = {}
    for i in range(len(R)):
        for s in PB.owner_setups(R[:i + 1], DAY, version="v6", market="US"):
            found[i] = s
    check("2. the V6 sequence is replayed candle by candle: a long confirmed on candle 50, a short on candle 71",
          sorted(found) == [50, 71] and found[50]["setup"] == "v6_smc_long" and found[71]["setup"] == "v6_smc_short",
          {k: v["setup"] for k, v in found.items()})
    lg = found.get(50, {})
    check("3. V6's own stop and target: 2 ticks beyond the sweep low 115.28, 1 tick before the 119.70 pool",
          (lg.get("price"), lg.get("stop"), lg.get("target")) == (116.45, 115.26, 119.69) and lg.get("scanner") == "v6", lg)
    det = lg.get("details") or {}
    check("   the strategy chain is in the record (CHoCH, BOS, sweep, pattern, confirmation)",
          det.get("choch") and det.get("bos") and det.get("sweep_at") and det.get("pattern") and det.get("confirmed_at"), det)
    check("4. no look-ahead: a setup is only reported on its confirmation candle, from candles 0..i only",
          not PB.owner_setups(R[:50], DAY, version="v6", market="US")
          and PB.owner_setups(R[:51], DAY, version="v6", market="US")[0]["price"] == 116.45
          and V6B.setups(R[:51], 49, "US") == [])
    for v in ("v2", "v3", "v4", "v5"):
        check("   Scanner %s never returns v6 setups" % v,
              not [g for g in PB.owner_setups(R[:51], DAY, version=v, market="US") if g["setup"].startswith("v6_")])
    check("5. price grid: NSE 0.05, US 0.01, crypto from the chart's own decimals",
          str(V6B.tick_for("NSE", R)) == "0.05" and str(V6B.tick_for("US", R)) == "0.01"
          and str(V6B.tick_for("CRYPTO", [(None, 0.14602, 0.1461, 0.1459, 0.146)])) == "0.00001")
    check("   settings change the stop / target ticks",
          V6B.setups(R[:51], 50, "US", sl_buffer_ticks=0, tp_offset_ticks=0)[0]["stop"] == 115.28)

    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        cfg = P.load_config()
        check("6. every account keeps its Scanner version (v6 is added, not switched on)",
              all(a.get("scanner_version") != "v6" for a in cfg["accounts"].values())
              and all(a.get("v6_setups") == PB.V6_SETUPS for a in cfg["accounts"].values()))
        cfg["accounts"]["US"].update({"scanner_version": "v6", "trade_setups": False})
        P.save_json(P.CONFIG, cfg)
        check("7. the switch accepts v6 and it is 'own setups only' (older rules off)",
              PB.scanner_version("US") == "v6" and PB.v4_only("US") == "v6"
              and PB.v6_params("US") == {"sl_buffer_ticks": 2, "tp_offset_ticks": 1})
        rec = P.setup_decision("US", "TST", dict(lg), news=[])
        v4rec = P.setup_decision("US", "TST", {"setup": "v4_primary_long", "name": "v4 primary long", "side": "long",
                                               "price": 100.0, "stop": 99.0, "target": 103.0})
        check("   a v6 account takes the v6 setup through the V4 agents and skips a v4 one",
              rec["result"] == "LOG ONLY" and rec["steps"]["1_scanner"]["scanner"] == "v6"
              and v4rec["result"] == "skipped" and "Scanner v6" in v4rec["why"], (rec.get("result"), rec.get("why"), v4rec))
        cfg = P.load_config()
        cfg["accounts"]["US"]["v6_setups"] = ["v6_smc_short"]
        P.save_json(P.CONFIG, cfg)
        r2 = P.setup_decision("US", "TST", dict(lg), news=[])
        check("   an unticked v6 setup is skipped with the reason", r2["result"] == "skipped" and "unticked" in r2["why"], r2)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
