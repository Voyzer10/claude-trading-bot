"""
Trader bot backend (FastAPI). It runs next to the runner on the VPS (trader-api service, 127.0.0.1:8000) or a PC
(npm run dev); Next.js forwards /api/py/* to it and checks the dashboard password (middleware.ts). It reads and
writes the runner's own files under trader/.

    GET  /api/py/control    which markets are on
    POST /api/py/control    change them: trader/live/control.json, which live.py reads before every cycle
    GET  /api/py/snapshot   the runner's latest trader/live/dashboard_snapshot.json
    GET  /api/py/health     is the API up, when the runner last wrote its snapshot
    /api/py/ops/*, /api/py/kite/*, /api/py/chart*, /api/py/opinion*, /api/py/timemachine*   the routers below
"""
import json
import os
import sys
import time

from fastapi import FastAPI, Request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo root, where the bot's .py files live
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from api._chart import router as _chart_router  # noqa: E402  (needs ROOT on sys.path)
from api._kite import router as _kite_router  # noqa: E402
from api._opinion import router as _opinion_router  # noqa: E402
from api._ops import router as _ops_router  # noqa: E402
from api._timemachine import router as _tm_router  # noqa: E402

app = FastAPI(docs_url="/api/py/docs", openapi_url="/api/py/openapi.json")
for _router in (_ops_router, _kite_router, _chart_router, _opinion_router, _tm_router):
    app.include_router(_router)

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


@app.get("/api/py/health")
def health():
    try:
        received = int(os.path.getmtime(SNAPSHOT))
    except OSError:
        received = None
    return {"ok": True, "password_set": bool(os.environ.get("DASHBOARD_PASSWORD")), "last_snapshot": received,
            "control": get_control(), "now": int(time.time())}
