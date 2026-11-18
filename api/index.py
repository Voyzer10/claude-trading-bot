"""
Trader bot dashboard API (FastAPI). It runs next to the runner on your PC or VPS (start_dashboard.bat, or
the trader-api service) on 127.0.0.1:8000; Next.js forwards /api/py/* to it and checks the dashboard
password (middleware.ts). It reads the runner's own files directly.

    GET  /api/py/snapshot   the runner's latest trader/live/dashboard_snapshot.json
    GET  /api/py/control    which markets are on
    POST /api/py/control    change them: trader/live/control.json, which live.py reads before every cycle
    /api/py/ops/*           settings, runner commands, health, backtests, downloads (api/_ops.py)
"""
import json
import os
import sys
import time

from fastapi import FastAPI, Request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo root, where the bot's .py files live
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from api._ops import router as _ops_router  # noqa: E402  (needs ROOT on sys.path)

app = FastAPI(docs_url="/api/py/docs", openapi_url="/api/py/openapi.json")
app.include_router(_ops_router)

SNAPSHOT = os.path.join(ROOT, "trader", "live", "dashboard_snapshot.json")
CONTROL = os.path.join(ROOT, "trader", "live", "control.json")
DEFAULT_CONTROL = {"CRYPTO": True, "US": True, "NSE": True, "FNO": True, "paused": False}


def get_control():
    c = dict(DEFAULT_CONTROL)
    try:
        with open(CONTROL, encoding="utf-8") as fh:
            c.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return c


@app.get("/api/py/control")
def control_get():
    return {"control": get_control()}


@app.post("/api/py/control")
async def control_set(request: Request):
    body = await request.json()
    c = get_control()
    for k in DEFAULT_CONTROL:
        if k in body:
            c[k] = bool(body[k])
    os.makedirs(os.path.dirname(CONTROL), exist_ok=True)
    tmp = CONTROL + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(c, fh, indent=2)
    os.replace(tmp, CONTROL)
    return {"control": c}


@app.get("/api/py/snapshot")
def snapshot():
    """The runner's own file; "received" = when the runner last wrote it."""
    try:
        with open(SNAPSHOT, encoding="utf-8") as fh:
            snap = json.load(fh)
        return {"received": int(os.path.getmtime(SNAPSHOT)), "snapshot": snap, "now": int(time.time())}
    except (OSError, ValueError):
        return {"received": None, "snapshot": None, "now": int(time.time())}
