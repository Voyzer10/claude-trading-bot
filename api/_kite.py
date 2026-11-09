"""Zerodha (Kite Connect) endpoints for the dashboard, PC / VPS only. Data only: nothing here can trade.

  GET  /api/py/kite/status     configured? connected today? who, until when (never a key or token)
  GET  /api/py/kite/login      -> Zerodha's login page (once a day; Kite tokens expire ~6:00 IST)
  GET  /api/py/kite/callback   Zerodha sends the browser back here with a request_token (set this URL as the
                               app's Redirect URL in the Kite developer console)
  POST /api/py/kite/logout     forget today's session
  GET  /api/py/live/ticks      the latest Indian market ticks (kite_ticker.py), for the dashboard's 1-second view
"""
import json
import os
import sys
import time
import urllib.parse

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import kite as K  # noqa: E402

# the API process may run from anywhere: point kite.py at the bot's own data folder
K.LIVE_DIR = os.path.join(ROOT, "trader", "live")
K.SESSION_FILE = os.path.join(K.LIVE_DIR, "kite_session.json")
K.INSTR_DIR = os.path.join(K.LIVE_DIR, "kite_instruments")
K.TICKS_FILE = os.path.join(K.LIVE_DIR, "ticks.json")

router = APIRouter()
FIELDS = ("ltp", "t", "open", "high", "low", "close", "volume", "oi")


def _ticker():
    try:
        with open(K.TICKS_FILE, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc, time.time() - float(doc.get("written", 0))
    except (FileNotFoundError, ValueError, TypeError):
        return {}, None


@router.get("/api/py/kite/status")
def kite_status():
    doc, age = _ticker()
    return dict(K.status(), ticker={"running": age is not None and age < 10,
                                    "age_s": None if age is None else round(age, 1),
                                    "instruments": len(doc.get("ticks") or {})})


@router.get("/api/py/kite/login")
def kite_login():
    try:
        return RedirectResponse(K.login_url(), status_code=302)
    except K.KiteError as e:
        return RedirectResponse("/?kite=" + urllib.parse.quote(str(e)) + "#control", status_code=302)


@router.get("/api/py/kite/callback")
def kite_callback(request_token: str = "", status: str = ""):
    if status != "success" or not request_token:
        msg = "Zerodha login was cancelled"
    else:
        try:
            K.exchange(request_token)
            msg = "connected"
        except K.KiteError as e:
            msg = str(e)
    return RedirectResponse("/?kite=" + urllib.parse.quote(msg) + "#control", status_code=302)


@router.post("/api/py/kite/logout")
def kite_logout():
    K.forget_session()
    return K.status()


@router.get("/api/py/live/ticks")
def live_ticks():
    doc, age = _ticker()
    ticks = {k: {f: v.get(f) for f in FIELDS if v.get(f) is not None} for k, v in (doc.get("ticks") or {}).items()}
    return {"age_s": None if age is None else round(age, 1), "live": age is not None and age < 5,
            "connected": K.connected(), "ticks": ticks}
