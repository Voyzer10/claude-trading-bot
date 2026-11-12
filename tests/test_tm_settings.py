#!/usr/bin/env python3
"""Settings > Trade Manager (owner, 13 Nov 2026): the v4 trailing stop per account (v4_trail, v4_be_r, v4_trail_step,
v4_trail_gap). The engine, the paper account and the backtest share one rule (scanner_v4.trail_lock_r). Offline.

    python tests/test_tm_settings.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


if __name__ == "__main__":
    import scanner_v4 as V4
    d = dict(V4.DEFAULTS)
    check("1. defaults = the owner's 11 Nov rule: +1R -> entry, +2R -> +1R, +3R -> +2R; nothing below +1R",
          [V4.trail_lock_r(g, d) for g in (0.9, 1.0, 1.99, 2.0, 3.4)] == [None, 0.0, 0.0, 1.0, 2.0])
    p = dict(d, v4_be_r=0.5, v4_trail_step=0.5, v4_trail_gap=1.0)
    check("   tighter: entry at +0.5R, then every 0.5R the stop sits 1R behind (+1.5R -> +0.5R)",
          [V4.trail_lock_r(g, p) for g in (0.4, 0.5, 1.0, 1.5, 2.0)] == [None, 0.0, 0.0, 0.5, 1.0])
    check("   v4_be_r 0: no breakeven move, only the trail", V4.trail_lock_r(1.2, dict(d, v4_be_r=0)) is None
          and V4.trail_lock_r(2.0, dict(d, v4_be_r=0)) == 1.0)

    # 2. the engine (backtest) follows the settings
    import test_scanner_v4 as TV
    up2 = (100.1, 100.1 + 2.1 * 0.7, 100.05, 100.6)        # reaches > +2R (risk ~0.7) then falls back
    down = (101.4, 101.45, 99.0, 99.1)                    # opens above every stop, then falls through them
    rows = TV.build([TV.SWEEP, TV.INV, TV.TRIG, up2, down])
    t_def = [t for t in V4.sequence(rows, TV.DAY) if t["side"] == "long"][0]
    t_off = [t for t in V4.sequence(rows, TV.DAY, trail=False) if t["side"] == "long"][0]
    t_be = [t for t in V4.sequence(rows, TV.DAY, v4_trail_gap=2.0) if t["side"] == "long"][0]
    risk = t_def["entry"] - t_def["stop"]
    check("2. backtest: default trail locks +1R after +2R; off = the full stop; gap 2 = only the entry",
          t_def["exit_reason"] == "trailing stop" and abs(t_def["exit"] - (t_def["entry"] + risk)) < 1e-6
          and t_off["exit_reason"] == "stop" and t_be["exit_reason"] == "breakeven stop"
          and abs(t_be["exit"] - t_be["entry"]) < 1e-6, (t_def, t_off, t_be))

    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        cfg = P.load_config()
        check("3. every account has the v4 Trade Manager settings, on the owner's defaults",
              all(cfg["accounts"][a].get("v4_trail") is True and cfg["accounts"][a]["v4_be_r"] == 1.0
                  and cfg["accounts"][a]["v4_trail_step"] == 1.0 and cfg["accounts"][a]["v4_trail_gap"] == 1.0
                  for a in ("INDIA", "FNO", "US", "CRYPTO")), {a: cfg["accounts"][a].get("v4_trail") for a in cfg["accounts"]})

        def pos():
            return {"key": "US:X", "market": "US", "entry": 100.0, "stop": 99.0, "risk_stop": 99.0, "side": "long"}
        a = pos(); P.v4_trail(a, 102.2, False, acc=cfg["accounts"]["US"])
        b = pos(); P.v4_trail(b, 102.2, False, acc=dict(cfg["accounts"]["US"], v4_trail=False))
        c = pos(); P.v4_trail(c, 101.6, False, acc=dict(cfg["accounts"]["US"], v4_be_r=0.5, v4_trail_step=0.5))
        s = {"key": "US:Y", "market": "US", "entry": 100.0, "stop": 101.0, "risk_stop": 101.0, "side": "short"}
        P.v4_trail(s, 97.9, True, acc=cfg["accounts"]["US"])
        check("4. paper: +2.2R -> stop +1R (101); off -> unchanged; step 0.5 at +1.6R -> +0.5R; a short mirrors",
              a["stop"] == 101.0 and a.get("trailing") and b["stop"] == 99.0 and c["stop"] == 100.5
              and s["stop"] == 99.0, (a["stop"], b["stop"], c["stop"], s["stop"]))

        # 5. the backtest reads the saved settings
        cfg["accounts"]["US"].update(v4_trail_gap=2.0, v4_be_r=0.5)
        json.dump(cfg, open(P.CONFIG, "w"))
        import research_scanner_v4 as R
        st = R.trail_settings("US")
        check("5. backtest uses the account's saved values", st == {"trail": True, "v4_be_r": 0.5, "v4_trail_step": 1.0,
                                                                   "v4_trail_gap": 2.0}, st)
        check("   and says so in the report", R.trail_text(st).startswith("+0.5R -> entry; then every 1R the stop sits 2R"),
              R.trail_text(st))

        # 6. the dashboard saves them (validated)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import api._ops as O
        O.PAPER_CFG = P.CONFIG
        app = FastAPI()
        app.include_router(O.router)
        cl = TestClient(app)
        r = cl.post("/api/py/ops/settings/risk", json={"account": "CRYPTO", "changes": {"v4_trail_step": 0.5, "v4_be_r": 0}})
        saved = json.load(open(P.CONFIG))["accounts"]["CRYPTO"]
        check("6. Settings saves the v4 Trade Manager per account", r.status_code == 200 and saved["v4_trail_step"] == 0.5
              and saved["v4_be_r"] == 0 and json.load(open(P.CONFIG))["accounts"]["US"]["v4_trail_step"] == 1.0,
              (r.status_code, r.text[:200]))
        bad = cl.post("/api/py/ops/settings/risk", json={"account": "US", "changes": {"v4_trail_gap": 0}})
        check("   a gap of 0 (stop at the best price) is refused", bad.status_code == 400, bad.text[:200])
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)
