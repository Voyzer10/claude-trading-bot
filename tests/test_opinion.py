#!/usr/bin/env python3
"""Your opinion (api/_opinion.py): the owner's fixed questions on a trade or a candidate, stored with a snapshot,
the latest version counts, and the export carries them (opinions.csv). Offline.

    python tests/test_opinion.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    try:
        import paper as P
        now = datetime.now(timezone.utc).isoformat()
        led = P.load_ledger(P.load_config())
        led["closed"] = [{"key": "US:RTX", "market": "US", "symbol": "RTX", "side": "long", "qty": 23, "entry": 200.44,
                          "stop": 198.34, "risk_stop": 198.34, "target": 204.27, "entry_time": now, "exit_time": now,
                          "exit": 198.3, "reason": "stop", "r": -1.0, "pnl": -49, "setup_name": "v4 primary long",
                          "scanner": "v4", "liquidity": "closed below the swing low 201.31, then a doji"}]
        P.save_json(P.LEDGER, led)
        os.makedirs("trader/live", exist_ok=True)
        dec = {"time": "2026-11-12T22:36:26+05:30", "symbol": "US:QCOM", "setup": "v4_primary_short", "result": "blocked",
               "why": "planned R:R 0.13 is below the minimum 1.0",
               "steps": {"1_scanner": {"scanner": "v4", "setup_name": "v4 primary short", "side": "short", "signal": "doji",
                                       "signal_at": "2026-11-12T11:50:00-05:00", "price": 179.83},
                         "4_exit": {"entry": 179.83, "stop": 183.51, "target": 179.36}}}
        open("trader/live/decisions.jsonl", "w").write(json.dumps(dec) + "\n")

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import api._opinion as OP
        app = FastAPI()
        app.include_router(OP.router)
        cl = TestClient(app)
        qs = cl.get("/api/py/opinion/questions").json()["questions"]
        ids = [q["id"] for q in qs]
        check("1. the questions: verdict (required), would you take it, mistakes (only when wrong / partly), quality "
              "1-5, HTF, better entry / stop / target, rule change, confidence, notes",
              ids[:3] == ["verdict", "would_take", "mistakes"] and qs[0]["required"]
              and qs[2]["show_if"] == {"verdict": ["wrong", "partly"]} and {"quality", "htf", "better_entry", "better_stop",
              "better_target", "rule_change", "confidence", "notes"} <= set(ids)
              and qs[0]["text"]["skipped"] == "Was skipping it the right call?", ids)

        ref = {"kind": "position", "key": "US:RTX", "entry_time": now}
        r = cl.post("/api/py/opinion", json={"ref": ref, "answers": {
            "verdict": "wrong", "would_take": "no", "mistakes": ["signal_wrong", "should_skip"], "quality": 2,
            "htf": "against", "better_entry": "none", "rule_change": "a doji with an 85% lower wick is a hammer, not a buy",
            "confidence": "high"}})
        rec = json.loads(open("trader/live/opinions.jsonl").read().splitlines()[-1])
        check("2. saved with a snapshot of the trade (setup, result, R, reason, levels)", r.status_code == 200
              and rec["ref_id"] == "pos|US:RTX|" + now and rec["version"] == 1 and rec["context"]["kind"] == "closed"
              and rec["context"]["r"] == -1.0 and rec["context"]["reason"] == "stop"
              and rec["answers"]["mistakes"] == ["signal_wrong", "should_skip"] and rec["answers"]["quality"] == 2, rec)
        for bad, why in (({"would_take": "no"}, "verdict missing"), ({"verdict": "maybe"}, "not an option"),
                         ({"verdict": "right", "quality": 9}, "quality out of range"),
                         ({"verdict": "right", "hack": 1}, "unknown question")):
            check("   refused: %s" % why, cl.post("/api/py/opinion", json={"ref": ref, "answers": bad}).status_code == 400)
        r = cl.post("/api/py/opinion", json={"ref": ref, "answers": {"verdict": "right", "mistakes": ["stop_tight"]}})
        got = cl.get("/api/py/opinion", params={"ref_id": "pos|US:RTX|" + now}).json()
        check("3. answering again adds version 2 and it counts; mistakes are dropped when the verdict is right",
              got["version"] == 2 and got["answers"] == {"verdict": "right"}, got)
        dref = {"kind": "decision", "time": dec["time"], "symbol": "US:QCOM"}
        cl.post("/api/py/opinion", json={"ref": dref, "answers": {"verdict": "right", "confidence": "medium"}})
        idx = cl.get("/api/py/opinion/index").json()
        d = cl.get("/api/py/opinion", params={"ref_id": "dec|US:QCOM|" + dec["time"]}).json()
        check("4. a skipped candidate: its own snapshot (result, why, planned levels); the index lists both",
              d["context"]["kind"] == "skipped" and d["context"]["result"] == "blocked" and d["context"]["stop"] == 183.51
              and set(idx) == {"pos|US:RTX|" + now, "dec|US:QCOM|" + dec["time"]}, (d["context"], idx))
        check("   an unknown trade: 404", cl.post("/api/py/opinion", json={"ref": {"kind": "position", "key": "US:NOPE"},
                                                                         "answers": {"verdict": "right"}}).status_code == 404)

        # 5. the export
        import api._ops as O
        O.LIVE, O.LEDGER, O.T = os.path.abspath("trader/live"), os.path.abspath(P.LEDGER), os.path.abspath("trader")
        resp = O._download_all()
        z = zipfile.ZipFile(io.BytesIO(resp.body))
        csv_txt = z.read("opinions.csv").decode()
        check("5. Download all: opinions.csv (latest per trade / candidate) and live/opinions.jsonl (every version)",
              "live/opinions.jsonl" in z.namelist() and csv_txt.splitlines()[0].startswith("saved_at,version,kind,symbol")
              and len(csv_txt.strip().splitlines()) == 3 and "US:QCOM" in csv_txt and "blocked" in csv_txt
              and "opinions.csv" in z.read("README.txt").decode(), csv_txt[:300])
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), FAILS)))
    sys.exit(1 if FAILS else 0)
