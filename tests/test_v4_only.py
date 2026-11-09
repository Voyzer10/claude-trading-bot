#!/usr/bin/env python3
"""Scanner v4 = ONLY v4 (owner, 10 Nov 2026): an account on v4 does not trade the older rules (crypto 4h breakout /
SMC / playbook / rulebook hits, NSE / US / index F&O opening-range breakouts); unticked v4 setups are skipped; the
Settings endpoints for every market. Offline.

    python tests/test_v4_only.py
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


def set_version(P, acct, v, **kw):
    cfg = P.load_config()
    cfg["accounts"][acct]["scanner_version"] = v
    cfg["accounts"][acct].update(kw)
    P.save_json(P.CONFIG, cfg)


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        import auto_crypto as AC
        import auto_nse as AN
        import auto_us as AU
        import auto_fno as AF
        P.load_config()
        logs, ran = [], []
        log = logs.append

        # crypto: a ticked rules setup (playbook bottom star) fires
        AC.run_one = lambda h, cfg, lg: ran.append(h["setup"]) or {"time": "t", "symbol": h["symbol"],
                                                                    "result": "PAPER BUY", "why": "x"}
        AC.headlines = lambda s: []
        cfg = AC.load_cfg()
        cfg["enabled_setups"] = ["smcp_star_long", "range_breakout_4h"]
        P.save_json(AC.AUTO_CONFIG, cfg)
        res = {"hits": [{"symbol": "SOL", "setup": "smcp_star_long", "new": True, "price": 1},
                        {"symbol": "ETH", "setup": "range_breakout_4h", "new": True, "price": 1}], "setups": []}
        set_version(P, "CRYPTO", "rules")
        AC.process({}, res, log)
        check("1. crypto on 'rules': the ticked rules setups trade (the older rules are still selectable)",
              sorted(ran) == ["range_breakout_4h", "smcp_star_long"], ran)
        ran.clear()
        logs.clear()
        set_version(P, "CRYPTO", "v3")
        AC.process({}, res, log)
        check("   crypto on v3: only v3's own rules - the same hits are NOT traded (owner, 10 Nov)",
              ran == [] and any("Scanner v3 only" in x for x in logs), (ran, logs))
        ran.clear()
        logs.clear()
        set_version(P, "CRYPTO", "v4")
        AC.process({}, res, log)
        check("   crypto on v4: the same hits are NOT traded", ran == [], ran)
        check("   ... and the log says why (Scanner v4 only, which setups)",
              any("Scanner v4 only: 2 rules-setup hits ignored" in x and "smcp_star_long" in x for x in logs), logs)

        # v4 setups: ticked ones go through the agents, unticked are skipped
        set_version(P, "CRYPTO", "v4", v4_setups=["v4_primary_long"], trade_setups=False)
        a = P.setup_decision("CRYPTO", "SOL", {"setup": "v4_primary_long", "name": "v4 primary long", "side": "long",
                                               "price": 100.0, "stop": 99.0, "target": 103.0})
        b = P.setup_decision("CRYPTO", "SOL", {"setup": "v4_secondary_long", "name": "v4 OB/FVG secondary long",
                                               "side": "long", "price": 100.0, "stop": 99.0, "target": 103.0})
        check("2. a ticked v4 setup goes through the agents; an unticked one is skipped with the reason",
              a["result"] == "LOG ONLY" and b["result"] == "skipped" and "unticked" in b["why"], (a["why"], b["why"]))

        # NSE: opening-range breaks off under v4
        AN.record_setups = lambda s, lg: None
        AN.run_one = lambda *a, **k: ran.append("nse") or {"time": "t", "symbol": "X", "result": "PAPER BUY", "why": "x"}
        set_version(P, "INDIA", "v4")
        logs.clear()
        st = {}
        out = AN.process(st, {"hits": [{"symbol": "RELIANCE", "new": True, "holding": True, "time": "09:40"}],
                              "as_of": datetime.now(timezone.utc).isoformat(), "setups": []}, log)
        check("3. NSE on v4: no opening-range breakout trade, logged", out == [] and "nse" not in ran
              and any("NSE: Scanner v4 only" in x for x in logs), logs)
        for v in ("v2", "rules"):
            set_version(P, "INDIA", v)
            AN.process({}, {"hits": [], "as_of": datetime.now(timezone.utc).isoformat(), "setups": []}, log)
        import smc_playbook as PB
        check("   v2 is 'own rules only' too; 'rules' runs the opening-range breaks and no Scanner setups",
              PB.v4_only("NSE") is None and PB.owner_setups([(None,)] * 40, lambda t: t, version="rules") == [],
              PB.v4_only("NSE"))
        set_version(P, "INDIA", "v4")

        # F&O index ORB off under v4 (INDIA)
        logs.clear()
        st = {}
        out = AF.process(st, log)
        check("4. F&O on v4 (INDIA): no index opening-range trade", out == [] and "Scanner v4 only" in
              st["markets"]["FNO"]["status"], st)

        # US: ORB scan / trades off under v4
        set_version(P, "US", "v4")
        called = []
        AU.scan_setups = lambda lg: called.append("setups")
        AU.sh = lambda *a, **k: called.append("orb scan") or (0, "")
        P.session = lambda m, n: "open"
        st = {}
        AU.process(st, log)
        check("5. US on v4: the v4 setup scan runs, the opening-range scan does not",
              called == ["setups"] and "Scanner v4 only" in st["markets"]["US"]["status"], (called, st))

        # Settings API: every market's rules, v4 setups per account
        from fastapi.testclient import TestClient
        import api._ops as O
        O.LIVE = os.path.join(tmp, "trader", "live")
        O.PAPER_CFG = os.path.join(tmp, "trader", "paper", "config.json")
        O.LOG = os.path.join(O.LIVE, "log.txt")
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(O.router)
        c = TestClient(app)
        doc = c.get("/api/py/ops/settings").json()
        check("6. Settings has NSE, US and F&O rules (not only crypto)", set(doc["markets"]) == {"NSE", "US", "FNO"}
              and "entry_start" in doc["markets"]["NSE"]["fields"], list(doc["markets"]))
        r = c.post("/api/py/ops/settings/market-rules", json={"market": "NSE", "changes": {"entry_end": "12:15",
                                                                                           "target_r": 2.5}})
        check("   NSE rules save to the NSE agent's own file (the agent reads it)", r.status_code == 200
              and AN.load_cfg()["entry_end"] == "12:15" and AN.load_cfg()["target_r"] == 2.5, r.text)
        bad = c.post("/api/py/ops/settings/market-rules", json={"market": "NSE", "changes": {"entry_end": "25:99"}})
        inv = c.post("/api/py/ops/settings/market-rules", json={"market": "NSE", "changes": {"entry_end": "09:00"}})
        check("   a bad time or an entry window that ends before it starts is refused",
              bad.status_code == 400 and inv.status_code == 400, (bad.text, inv.text))
        r = c.post("/api/py/ops/settings/market-rules", json={"market": "FNO", "changes": {"indices": ["BANKNIFTY"]}})
        check("   F&O rules save (indices)", r.status_code == 200 and AF.load_cfg()["indices"] == ["BANKNIFTY"], r.text)
        c.post("/api/py/ops/settings/market-rules/reset", json={"market": "NSE"})
        check("   reset puts the NSE defaults back", AN.load_cfg()["entry_end"] == AN.DEFAULTS["entry_end"])
        r = c.post("/api/py/ops/settings/risk", json={"account": "US", "changes": {"v4_setups": []}})
        check("   the v4 setups per account can be saved, even all unticked", r.status_code == 200
              and P.load_config()["accounts"]["US"]["v4_setups"] == [], r.text)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
