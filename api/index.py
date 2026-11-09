"""
Trader bot backend (FastAPI), deployed by Vercel as a Python function. It is two things:

1. The CLOUD RUNNER. Vercel does not keep a program running, so an outside scheduler (cron-job.org or the
   GitHub Action in .github/workflows/tick.yml) calls /api/py/cron/tick every 5 minutes. Each tick:
   loads the bot's files (state, paper ledger, rules, logs) from Redis into a temp folder, runs ONE cycle of
   the same bot code that runs on the PC (live.py: crypto scan -> agents -> paper trades -> stop/target
   checks), saves the files back to Redis and stores a fresh dashboard snapshot.
2. The DASHBOARD API for the Next.js frontend: snapshot, history, health, and the market on/off controls.

    GET|POST /api/py/cron/tick   one runner cycle      header Authorization: Bearer <CRON_SECRET>  (or ?key=)
    GET      /api/py/control     which markets are on
    POST     /api/py/control     change them           needs DASHBOARD_PASSWORD (the browser sends it)
    POST     /api/py/ingest      a snapshot pushed by the PC runner           Bearer <INGEST_TOKEN>
    POST     /api/py/seed        upload the PC's files to start the cloud runner from them (cloud_seed.py)
    GET      /api/py/snapshot | /api/py/history | /api/py/health

Environment variables (Vercel project settings):
    CRON_SECRET          required for the cloud runner (the scheduler sends it)
    INGEST_TOKEN         required for the PC push and for cloud_seed.py
    DASHBOARD_PASSWORD   protects the dashboard and is required to change the controls
    KV_REST_API_URL / KV_REST_API_TOKEN   set by the Upstash Redis integration (UPSTASH_REDIS_REST_* work too)
"""
import base64
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
import urllib.request

from fastapi import FastAPI, Header, HTTPException, Request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo root, where the bot's .py files live
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

app = FastAPI(docs_url="/api/py/docs", openapi_url="/api/py/openapi.json")

K_LATEST = "trader:snapshot:latest"
K_HISTORY = "trader:snapshot:history"
K_CONTROL = "trader:control"
K_LOCK = "trader:lock"
K_FILE = "trader:file:"
HISTORY_KEEP = 288
MAX_BYTES = 900_000

# The bot's files that persist between cloud ticks, and how many lines to keep of the growing ones.
FILES = {
    "trader/live/state.json": None,
    "trader/live/log.txt": 2500,
    "trader/live/decisions.jsonl": 400,
    "trader/live/auto_config.json": None,
    "trader/paper/config.json": None,
    "trader/paper/ledger.json": None,
    "trader/universe_crypto.txt": None,
    "trader/watchlist.json": None,
}
CLOUD_MARKETS = ["CRYPTO"]  # markets the cloud runner can run today; the others need the PC runner
DEFAULT_CONTROL = {"CRYPTO": True, "US": False, "NSE": False, "FNO": False, "paused": False}

# LOCAL MODE (the default when there is no Redis and we are not on Vercel): the API runs on your PC next to the
# runner (start_dashboard.bat). It reads the runner's own files directly and writes the market switches to
# trader/live/control.json, which live.py reads before every cycle.
LOCAL = not os.environ.get("VERCEL") and not (
    (os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")))
LOCAL_SNAPSHOT = os.path.join(ROOT, "trader", "live", "dashboard_snapshot.json")
LOCAL_CONTROL = os.path.join(ROOT, "trader", "live", "control.json")
LOCAL_MARKETS = ["CRYPTO", "US", "NSE", "FNO"]
LOCAL_DEFAULT = {"CRYPTO": True, "US": True, "NSE": True, "FNO": True, "paused": False}


# ------------------------------------------------------------------ storage (Upstash Redis, or a local folder)

def _redis_conf():
    url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    tok = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    return (url.rstrip("/"), tok) if url and tok else (None, None)


def _redis(*cmd):
    url, tok = _redis_conf()
    req = urllib.request.Request(url, data=json.dumps(list(cmd)).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        out = json.loads(r.read())
    if "error" in out:
        raise RuntimeError(out["error"])
    return out.get("result")


_LOCAL_DIR = os.path.join(tempfile.gettempdir(), "trader_store")


def _lpath(key):
    os.makedirs(_LOCAL_DIR, exist_ok=True)
    return os.path.join(_LOCAL_DIR, key.replace(":", "_").replace("/", "__"))


def kv_get(key):
    if _redis_conf()[0]:
        return _redis("GET", key)
    try:
        with open(_lpath(key), encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def kv_set(key, value, nx_seconds=None):
    """Set a string. With nx_seconds: only if absent, expiring after that many seconds (a lock)."""
    if _redis_conf()[0]:
        if nx_seconds:
            return _redis("SET", key, value, "NX", "EX", nx_seconds) == "OK"
        _redis("SET", key, value)
        return True
    p = _lpath(key)
    if nx_seconds and os.path.exists(p) and time.time() - os.path.getmtime(p) < nx_seconds:
        return False
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(value)
    return True


def kv_del(key):
    if _redis_conf()[0]:
        _redis("DEL", key)
    else:
        try:
            os.remove(_lpath(key))
        except FileNotFoundError:
            pass


def history_push(item):
    if _redis_conf()[0]:
        _redis("LPUSH", K_HISTORY, item)
        _redis("LTRIM", K_HISTORY, 0, HISTORY_KEEP - 1)
    else:
        items = json.loads(kv_get(K_HISTORY) or "[]")
        kv_set(K_HISTORY, json.dumps(([json.loads(item)] + items)[:HISTORY_KEEP]))


def history_all():
    if _redis_conf()[0]:
        return [json.loads(x) for x in (_redis("LRANGE", K_HISTORY, 0, HISTORY_KEEP - 1) or [])]
    return json.loads(kv_get(K_HISTORY) or "[]")


def storage_name():
    return "redis" if _redis_conf()[0] else ("pc-files" if LOCAL else "local-folder")


# ------------------------------------------------------------------ helpers

def _bearer(authorization, expected):
    return bool(expected) and authorization == "Bearer " + expected


def _headline(snap, received):
    acc = (snap.get("ledger") or {}).get("accounts") or {}
    return {"t": received, "crypto_cash": (acc.get("CRYPTO") or {}).get("cash"),
            "open": len((snap.get("ledger") or {}).get("open") or []),
            "decisions": (snap.get("counts") or {}).get("decisions_total"),
            "status": (snap.get("runner") or {}).get("status"),
            "mode": (snap.get("runner") or {}).get("mode")}


def store_snapshot(snap):
    received = int(time.time())
    kv_set(K_LATEST, json.dumps({"received": received, "snapshot": snap}, default=str))
    history_push(json.dumps(_headline(snap, received)))
    return received


def get_control():
    if LOCAL:
        c = dict(LOCAL_DEFAULT)
        try:
            with open(LOCAL_CONTROL, encoding="utf-8") as fh:
                c.update(json.load(fh))
        except (OSError, ValueError):
            pass
        return c
    c = dict(DEFAULT_CONTROL)
    try:
        c.update(json.loads(kv_get(K_CONTROL) or "{}"))
    except ValueError:
        pass
    return c


def save_control(c):
    if LOCAL:
        os.makedirs(os.path.dirname(LOCAL_CONTROL), exist_ok=True)
        tmp = LOCAL_CONTROL + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(c, fh, indent=2)
        os.replace(tmp, LOCAL_CONTROL)
    else:
        kv_set(K_CONTROL, json.dumps(c))


def _trim(text, keep):
    if not keep:
        return text
    lines = text.splitlines(True)
    return "".join(lines[-keep:])


# ------------------------------------------------------------------ cloud runner

def run_tick():
    """One runner cycle in a temp folder, with the files from storage. Returns a short summary."""
    control = get_control()
    work = tempfile.mkdtemp(prefix="tick_")
    old_cwd = os.getcwd()
    try:
        for rel in FILES:
            body = kv_get(K_FILE + rel)
            if body is not None:
                path = os.path.join(work, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(body)
        os.makedirs(os.path.join(work, "trader", "live"), exist_ok=True)
        os.chdir(work)
        os.environ.pop("DASHBOARD_URL", None)  # in the cloud the snapshot is stored directly, not pushed
        import live  # the same runner code as on the PC
        live = importlib.reload(live)
        markets = [] if control.get("paused") else [m for m in CLOUD_MARKETS if control.get(m)]

        class A:  # live.py's command-line options
            interval = 300
            or_minutes = 15
            nifty50 = True
            min_price = 20.0
            min_volume = 100000
            workers = 8
            auto_paper = True
            _tried_download = True

        state = live.load_state()
        state.update({"runner_mode": "cloud", "markets_scanned": markets, "pid": None})
        t0 = time.time()
        if markets:
            live.cycle(state, A, markets)
        else:  # paused or every cloud market off: still watch open paper positions (stops must work)
            state["errors"] = []
            snap = live.paper_snapshot()
            if snap is not None:
                state["paper"] = snap
            state["updated"] = live.now_ist().isoformat()
        nxt = live.now_ist() + live.timedelta(minutes=5)
        state["next_run"] = nxt.isoformat()
        state["status"] = "cloud runner: %s, next tick ~%s" % (
            "paused" if control.get("paused") else ("scanning " + "+".join(markets) if markets else "no market on"),
            nxt.strftime("%H:%M"))
        live.log("cloud tick: %s in %.1fs%s" % ("+".join(markets) or "positions only", time.time() - t0,
                                               ("; errors: " + "; ".join(state["errors"])) if state.get("errors") else ""))
        live.save_state(state)  # also writes trader/live/dashboard_snapshot.json
        # persist the files
        for rel, keep in FILES.items():
            path = os.path.join(work, rel)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    kv_set(K_FILE + rel, _trim(fh.read(), keep))
        snap_path = os.path.join(work, "trader", "live", "dashboard_snapshot.json")
        received = None
        if os.path.exists(snap_path):
            with open(snap_path, encoding="utf-8") as fh:
                received = store_snapshot(json.load(fh))
        return {"ok": True, "markets": markets, "seconds": round(time.time() - t0, 1),
                "errors": state.get("errors") or [], "snapshot_stored": received, "storage": storage_name()}
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(work, ignore_errors=True)


@app.api_route("/api/py/cron/tick", methods=["GET", "POST"])
def cron_tick(request: Request, authorization: str = Header(default="")):
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        raise HTTPException(500, "CRON_SECRET is not set on the server")
    if not (_bearer(authorization, secret) or request.query_params.get("key") == secret):
        raise HTTPException(401, "bad or missing CRON_SECRET")
    if not kv_set(K_LOCK, str(time.time()), nx_seconds=240):
        return {"ok": True, "skipped": "another tick is still running"}
    try:
        return run_tick()
    except Exception as e:
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()[-1500:]}
    finally:
        kv_del(K_LOCK)


# ------------------------------------------------------------------ controls

def _password_ok(authorization):
    pw = os.environ.get("DASHBOARD_PASSWORD")
    if not pw or not authorization.startswith("Basic "):
        return False
    try:
        return base64.b64decode(authorization[6:]).decode().split(":", 1)[1] == pw
    except Exception:
        return False


@app.get("/api/py/control")
def control_get():
    if LOCAL:
        return {"control": get_control(), "cloud_markets": LOCAL_MARKETS, "can_change": True, "mode": "local"}
    return {"control": get_control(), "cloud_markets": CLOUD_MARKETS,
            "can_change": bool(os.environ.get("DASHBOARD_PASSWORD")), "mode": "cloud"}


@app.post("/api/py/control")
async def control_set(request: Request, authorization: str = Header(default="")):
    if LOCAL:  # on your own PC (127.0.0.1) no password is needed
        body = await request.json()
        c = get_control()
        for k in LOCAL_DEFAULT:
            if k in body:
                c[k] = bool(body[k])
        save_control(c)
        return {"control": c}
    if not os.environ.get("DASHBOARD_PASSWORD"):
        raise HTTPException(403, "set DASHBOARD_PASSWORD on Vercel to enable the controls")
    if not _password_ok(authorization):
        raise HTTPException(401, "wrong dashboard password")
    body = await request.json()
    c = get_control()
    for k in DEFAULT_CONTROL:
        if k in body:
            c[k] = bool(body[k])
    save_control(c)
    return {"control": c}


# ------------------------------------------------------------------ PC runner push and seeding

@app.post("/api/py/ingest")
async def ingest(request: Request, authorization: str = Header(default="")):
    if not os.environ.get("INGEST_TOKEN"):
        raise HTTPException(500, "INGEST_TOKEN is not set on the server")
    if not _bearer(authorization, os.environ["INGEST_TOKEN"]):
        raise HTTPException(401, "bad or missing token")
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "snapshot is %d bytes; the limit is %d" % (len(raw), MAX_BYTES))
    try:
        snap = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "body is not JSON")
    return {"ok": True, "received": store_snapshot(snap), "bytes": len(raw), "storage": storage_name()}


@app.post("/api/py/seed")
async def seed(request: Request, authorization: str = Header(default="")):
    """cloud_seed.py uploads {"files": {"trader/paper/ledger.json": "...", ...}} so the cloud runner continues
    from the PC's ledger, rules and history."""
    if not _bearer(authorization, os.environ.get("INGEST_TOKEN", "")):
        raise HTTPException(401, "bad or missing token")
    body = await request.json()
    done = []
    for rel, text in (body.get("files") or {}).items():
        if rel in FILES and isinstance(text, str):
            kv_set(K_FILE + rel, _trim(text, FILES[rel]))
            done.append(rel)
    return {"ok": True, "stored": done}


# ------------------------------------------------------------------ reads

@app.get("/api/py/snapshot")
def snapshot():
    if LOCAL:  # read the runner's own file; "received" = when the runner last wrote it
        try:
            with open(LOCAL_SNAPSHOT, encoding="utf-8") as fh:
                snap = json.load(fh)
            return {"received": int(os.path.getmtime(LOCAL_SNAPSHOT)), "snapshot": snap, "now": int(time.time())}
        except (OSError, ValueError):
            return {"received": None, "snapshot": None, "now": int(time.time())}
    raw = kv_get(K_LATEST)
    doc = json.loads(raw) if raw else {"received": None, "snapshot": None}
    doc["now"] = int(time.time())
    return doc


@app.get("/api/py/history")
def history():
    return {"items": list(reversed(history_all()))}


@app.get("/api/py/health")
def health():
    try:
        last = snapshot().get("received")
    except Exception as e:
        return {"ok": False, "storage": storage_name(), "error": str(e)}
    return {"ok": True, "storage": storage_name(), "cron_secret_set": bool(os.environ.get("CRON_SECRET")),
            "ingest_token_set": bool(os.environ.get("INGEST_TOKEN")),
            "password_set": bool(os.environ.get("DASHBOARD_PASSWORD")), "last_snapshot": last,
            "control": get_control(), "now": int(time.time())}


# ------------------------------------------------------------------ operations (PC / VPS only)

if LOCAL:
    try:
        from api._ops import router as _ops_router
    except ImportError:
        from _ops import router as _ops_router
    app.include_router(_ops_router)
    try:
        from api._kite import router as _kite_router
    except ImportError:
        from _kite import router as _kite_router
    app.include_router(_kite_router)
