#!/usr/bin/env python3
"""CI smoke test for the dashboard API in local (PC/VPS) mode, with no network and a throwaway data folder.

Starts nothing: it calls the FastAPI app in-process with fastapi.testclient, checks that the read endpoints
answer, that a settings change is validated and saved, and that a runner command is queued.
    python tests/smoke_api.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
work = tempfile.mkdtemp(prefix="trader-smoke-")
# a copy of the repo's Python files, so the test's trader/ data folder is throwaway
for name in os.listdir(ROOT):
    if name.endswith(".py"):
        shutil.copy(os.path.join(ROOT, name), work)
shutil.copytree(os.path.join(ROOT, "api"), os.path.join(work, "api"))
os.makedirs(os.path.join(work, "trader", "live"))
with open(os.path.join(work, "trader", "live", "dashboard_snapshot.json"), "w") as fh:
    json.dump({"version": 1, "generated_at": "2026-01-01T00:00:00+05:30"}, fh)
os.chdir(work)
sys.path.insert(0, work)
for k in ("VERCEL", "KV_REST_API_URL", "UPSTASH_REDIS_REST_URL", "DASHBOARD_PASSWORD"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402
import api.index as index  # noqa: E402

assert index.LOCAL, "the API should run in local mode without Redis"
c = TestClient(index.app)
fails = []


def check(name, cond, detail=""):
    print("  %-4s %s %s" % ("OK" if cond else "FAIL", name, detail))
    if not cond:
        fails.append(name)


r = c.get("/api/py/health"); check("health", r.status_code == 200 and r.json()["ok"], r.text[:120])
r = c.get("/api/py/snapshot"); check("snapshot", r.status_code == 200 and r.json()["snapshot"]["version"] == 1)
r = c.get("/api/py/control"); check("control", r.status_code == 200 and r.json()["mode"] == "local")
r = c.get("/api/py/ops/settings"); check("ops settings", r.status_code == 200 and "rules" in r.json())
r = c.post("/api/py/ops/settings/rules", json={"changes": {"target_r": 99}})
check("rule limits enforced", r.status_code == 400, r.text[:80])
r = c.post("/api/py/ops/settings/rules", json={"changes": {"target_r": 2.5}})
check("rule saved", r.status_code == 200 and r.json()["changed"], r.text[:80])
r = c.post("/api/py/ops/command", json={"action": "run_now"})
check("command queued", r.status_code == 200 and os.path.exists("trader/live/commands.jsonl"))
r = c.get("/api/py/ops/performance"); check("performance", r.status_code == 200)
r = c.get("/api/py/ops/system"); check("system", r.status_code == 200 and "disk" in r.json())
r = c.get("/api/py/ops/agents"); check("agents", r.status_code == 200 and len(r.json()["agents"]) == 11)
r = c.post("/api/py/ops/autobuy", json={"market": "NSE", "on": True})
check("autobuy on", r.status_code == 200 and c.get("/api/py/ops/autobuy").json()["NSE"]["on"]
      and json.load(open("trader/live/auto_nse_config.json"))["auto_buy"] is True)
r = c.post("/api/py/ops/autobuy", json={"market": "BSE", "on": True}); check("autobuy bad market", r.status_code == 400)
r = c.post("/api/py/ops/autobuy", json={"market": "US_SHORT", "on": False})
check("us shorts off", r.status_code == 200 and c.get("/api/py/ops/autobuy").json()["US_SHORT"]["on"] is False
      and json.load(open("trader/live/auto_us_config.json"))["allow_short"] is False)
r = c.get("/api/py/ops/download/trades.csv"); check("trades csv", r.status_code == 200)

shutil.rmtree(work, ignore_errors=True)
print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
