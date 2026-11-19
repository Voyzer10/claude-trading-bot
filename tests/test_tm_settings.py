#!/usr/bin/env python3
"""Settings > Trade Manager (owner, 13 Nov 2026): ONE set per market account, for every scanner (v2 / v3 / v4 / v5 /
rules). Breakeven, trailing, profit lock, reversal and no-follow-through exits; the backtest engine, the paper
account and the dashboard share the settings. Includes the one-time fold of the old two sets. Offline.

    python tests/test_tm_settings.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import timedelta

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
    V4.DEFAULTS.update(structure_bos=False)   # mechanics on hand-built / random charts (the 20 Nov BOS is in test_v4_sweep_target)
    d = dict(V4.DEFAULTS)
    check("1. defaults = the owner's rule: +1R -> entry, +2R -> +1R, +3R -> +2R; no lock / reversal / stale exit",
          [V4.trail_lock_r(g, d) for g in (0.9, 1.0, 1.99, 2.0, 3.4)] == [None, 0.0, 0.0, 1.0, 2.0]
          and not d["tm_lock_at"] and not d["tm_reversal"] and not d["tm_stale_min"])
    p = dict(d, tm_be_r=0.5, tm_trail_step=0.5, tm_trail_gap=1.0)
    check("   tighter: entry at +0.5R, then every 0.5R the stop sits 1R behind (+1.5R -> +0.5R)",
          [V4.trail_lock_r(g, p) for g in (0.4, 0.5, 1.0, 1.5, 2.0)] == [None, 0.0, 0.0, 0.5, 1.0])
    check("   tm_be_r 0: no breakeven move; trailing off: only the breakeven; Trade Manager off: nothing",
          V4.trail_lock_r(1.2, dict(d, tm_be_r=0)) is None and V4.trail_lock_r(2.0, dict(d, tm_be_r=0)) == 1.0
          and V4.trail_lock_r(3.0, dict(d, tm_trail=False)) == 0.0 and V4.trail_lock_r(3.0, dict(d, trade_manager=False)) is None)
    check("   profit lock: 80% of a 2R way keeps half (+1R); off at 0", V4.lock_stop_r(1.6, 2.0, dict(d, tm_lock_at=0.8)) == 1.0
          and V4.lock_stop_r(1.5, 2.0, dict(d, tm_lock_at=0.8)) is None and V4.lock_stop_r(1.9, 2.0, d) is None)

    # 2. the engine (backtest) runs every part
    import test_scanner_v4 as TV
    up2 = (100.1, 100.1 + 2.1 * 0.7, 100.05, 100.6)         # > +2R (risk ~0.68) then falls back
    down = (101.4, 101.45, 99.0, 99.1)                      # opens above every stop, then falls through them
    rows = TV.build([TV.SWEEP, TV.INV, TV.TRIG, up2, down])
    first = lambda **kw: [t for t in V4.sequence(rows, TV.DAY, **kw) if t["side"] == "long"][0]   # noqa: E731
    t_def, t_off, t_gap2 = first(), first(trade_manager=False), first(tm_trail_gap=2.0)
    t_lock = first(tm_trail=False, tm_lock_at=0.5, tm_lock_keep=0.25)
    risk = t_def["entry"] - t_def["stop"]
    way = t_def["target"] - t_def["entry"]
    check("2. backtest: default trail -> +1R; off -> full stop; gap 2 -> entry; lock at 50% of the way keeps 25%",
          t_def["exit_reason"] == "trailing stop" and abs(t_def["exit"] - (t_def["entry"] + risk)) < 1e-6
          and t_off["exit_reason"] == "stop" and t_gap2["exit_reason"] == "breakeven stop"
          and t_lock["exit_reason"] == "profit lock stop" and abs(t_lock["exit"] - (t_lock["entry"] + 0.25 * way)) < 1e-6,
          [(t["exit_reason"], round(t["exit"], 3)) for t in (t_def, t_off, t_gap2, t_lock)])
    flat = (100.15, 100.3, 100.0, 100.12)                   # goes nowhere
    rows_s = TV.build([TV.SWEEP, TV.INV, TV.TRIG] + [flat] * 16)
    ts = [t for t in V4.sequence(rows_s, TV.DAY, tm_stale_min=60) if t["side"] == "long"]
    t0 = [t for t in V4.sequence(rows_s, TV.DAY) if t["side"] == "long"]
    check("   no-follow-through: 60 min of 5m candles going nowhere -> closed; off (0) -> not",
          ts and ts[0]["exit_reason"] == "trade manager: no follow-through"
          and (rows_s[ts[0]["exit_i"]][0] - rows_s[ts[0]["i"]][0]) >= timedelta(minutes=60)
          and (not t0 or t0[0]["exit_reason"] != "trade manager: no follow-through"), (ts[:1], t0[:1]))
    rev = [(100.6, 102.1, 100.55, 102.0), (102.05, 102.08, 100.5, 100.55)]   # +1.27R, then an engulfing at the top
    rows_r = TV.build([TV.SWEEP, TV.INV, TV.TRIG] + rev + [(100.55, 100.6, 100.5, 100.55)] * 3)
    tr = [t for t in V4.sequence(rows_r, TV.DAY, tm_reversal=True, tm_trail=False, tm_be_r=0) if t["side"] == "long"]
    check("   reversal: an engulfing candle near the best price after +1R -> out at its close",
          tr and tr[0]["exit_reason"] == "trade manager: reversal" and abs(tr[0]["exit"] - 100.55) < 1e-6, tr[:1])

    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        # 3. the one-time fold of an old config (two Trade Managers) into one set per account
        old_cfg = {"accounts": {
            "US": dict(P.DEFAULT_CONFIG["accounts"]["US"], scanner_version="v4", tm_lock_at=0.8, tm_reversal=True,
                       tm_stale_min=60, v4_trail=True, v4_be_r=0.5, v4_trail_step=1.0, v4_trail_gap=1.0),
            "CRYPTO": dict(P.DEFAULT_CONFIG["accounts"]["CRYPTO"], scanner_version="v3", tm_lock_at=0.8,
                           tm_reversal=True, tm_stale_min=240, v4_trail=True, v4_be_r=1.0)}}
        for a in old_cfg["accounts"].values():
            for k in ("tm_trail", "tm_trail_step", "tm_trail_gap"):
                a.pop(k, None)
        os.makedirs(os.path.dirname(P.CONFIG), exist_ok=True)
        json.dump(old_cfg, open(P.CONFIG, "w"))
        cfg = P.load_config()
        us, cr = cfg["accounts"]["US"], cfg["accounts"]["CRYPTO"]
        check("3. fold: a v4 account keeps what its trades ran (v4 trailing, breakeven 0.5R; lock / reversal / stale off)",
              us["tm_trail"] is True and us["tm_be_r"] == 0.5 and us["tm_lock_at"] == 0 and us["tm_reversal"] is False
              and us["tm_stale_min"] == 0 and "v4_trail" not in us, us)
        check("   a v3 account keeps its exits (lock 0.8, reversal, 240 min) and no trailing",
              cr["tm_trail"] is False and cr["tm_lock_at"] == 0.8 and cr["tm_reversal"] is True and cr["tm_stale_min"] == 240,
              cr)
        cr["tm_trail"] = True
        json.dump(cfg, open(P.CONFIG, "w"))
        check("   once only: a later change stays", P.load_config()["accounts"]["CRYPTO"]["tm_trail"] is True)
        check("   every account has the full set", all(all(k in a for k in V4.TM_KEYS) for a in P.load_config()["accounts"].values()))

        # 4. paper: one helper, the same for every scanner
        tm = P.tm_cfg(dict(us, tm_be_r=1.0))

        def pos(**kw):
            return dict({"key": "US:X", "market": "US", "entry": 100.0, "stop": 99.0, "risk_stop": 99.0, "side": "long"}, **kw)
        a = pos(scanner="v4"); P.tm_trail(a, 102.2, False, None, tm)
        b = pos(scanner="v2"); P.tm_trail(b, 102.2, False, None, tm)
        c = pos(); P.tm_trail(c, 101.6, False, None, dict(tm, tm_be_r=0.5, tm_trail_step=0.5))
        s = {"key": "US:Y", "market": "US", "entry": 100.0, "stop": 101.0, "risk_stop": 101.0, "side": "short"}
        P.tm_trail(s, 97.9, True, None, tm)
        check("4. paper: +2.2R -> stop +1R for a v4 AND a v2 trade; step 0.5 at +1.6R -> +0.5R; a short mirrors",
              a["stop"] == 101.0 and b["stop"] == 101.0 and c["stop"] == 100.5 and s["stop"] == 99.0,
              (a["stop"], b["stop"], c["stop"], s["stop"]))
        check("   Trade Manager off -> no settings at all", P.tm_cfg(dict(us, trade_manager=False)) is None)

        # 5. the backtest reads the saved settings
        cfg = P.load_config()
        cfg["accounts"]["US"].update(tm_trail_gap=2.0, tm_be_r=0.5, tm_lock_at=0.8, tm_stale_min=90)
        json.dump(cfg, open(P.CONFIG, "w"))
        import research_scanner_v4 as R
        st = R.trail_settings("US")
        check("5. backtest uses the account's saved Trade Manager", st["tm_trail_gap"] == 2.0 and st["tm_be_r"] == 0.5
              and st["tm_lock_at"] == 0.8 and st["tm_stale_min"] == 90, st)
        txt = R.trail_text(st)
        check("   and says so in the report", txt.startswith("+0.5R -> entry; then every 1R the stop sits 2R")
              and "profit lock at 80%" in txt and "no-follow-through exit after 90 min" in txt, txt)

        # 6. the dashboard saves them (validated)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import api._ops as O
        O.PAPER_CFG = P.CONFIG
        app = FastAPI()
        app.include_router(O.router)
        cl = TestClient(app)
        r = cl.post("/api/py/ops/settings/risk", json={"account": "CRYPTO", "changes": {"tm_trail_step": 0.5, "tm_be_r": 0,
                                                                                        "tm_lock_at": 0}})
        saved = json.load(open(P.CONFIG))["accounts"]["CRYPTO"]
        check("6. Settings saves the Trade Manager per account (0 = that part off)", r.status_code == 200
              and saved["tm_trail_step"] == 0.5 and saved["tm_be_r"] == 0 and saved["tm_lock_at"] == 0
              and json.load(open(P.CONFIG))["accounts"]["US"]["tm_trail_step"] == 1.0, (r.status_code, r.text[:200]))
        bad = cl.post("/api/py/ops/settings/risk", json={"account": "US", "changes": {"tm_trail_gap": 0}})
        check("   a trailing gap of 0 (stop at the best price) is refused", bad.status_code == 400, bad.text[:200])
        check("   the old v4-only keys are gone from Settings", "v4_trail" not in O.RISK_FIELDS and "v4_be_r" not in O.RISK_FIELDS)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)
