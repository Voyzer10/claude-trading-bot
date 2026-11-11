"""Zerodha (Kite Connect) endpoints for the dashboard, PC / VPS only. Data only: nothing here can trade.

  GET  /api/py/kite/status     configured? connected today? who, until when (never a key or token)
  GET  /api/py/kite/login      -> Zerodha's login page (once a day; Kite tokens expire ~6:00 IST)
  GET  /api/py/kite/callback   Zerodha sends the browser back here with a request_token (needs an https dashboard:
                               Kite only accepts https:// or http://127.0.0.1 Redirect URLs)
  POST /api/py/kite/token      {"text": the post-login address or the request_token}: connect by pasting it
  POST /api/py/kite/logout     forget today's session
  GET  /api/py/live/ticks      the latest Indian market ticks (kite_ticker.py) and crypto prices (crypto_ticker.py,
                               Coinbase public data) and US prices (us_ticker.py, Alpaca IEX), for the dashboard's 1-second view
"""
import json
import os
import re
import sys
import time
import urllib.parse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import kite as K  # noqa: E402
import coinbase as CX  # noqa: E402
import alpaca as AL  # noqa: E402

# the API process may run from anywhere: point kite.py at the bot's own data folder
K.LIVE_DIR = os.path.join(ROOT, "trader", "live")
K.SESSION_FILE = os.path.join(K.LIVE_DIR, "kite_session.json")
K.INSTR_DIR = os.path.join(K.LIVE_DIR, "kite_instruments")
K.TICKS_FILE = os.path.join(K.LIVE_DIR, "ticks.json")
CX.LIVE_DIR = K.LIVE_DIR
AL.TICKS_FILE = os.path.join(K.LIVE_DIR, "us_ticks.json")
CX.TICKS_FILE = os.path.join(K.LIVE_DIR, "crypto_ticks.json")

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
        return RedirectResponse("/?kite=" + urllib.parse.quote(str(e)) + "#zerodha", status_code=302)


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
    return RedirectResponse("/?kite=" + urllib.parse.quote(msg) + "#zerodha", status_code=302)


def token_from(text):
    """The request_token from what the owner pastes after the Zerodha login: the whole address of the page the
    login lands on (http://127.0.0.1/...?request_token=XXXX&...) or the token alone."""
    t = (text or "").strip()
    m = re.search(r"request_token=([A-Za-z0-9]+)", t)
    if m:
        return m.group(1)
    return t if re.fullmatch(r"[A-Za-z0-9]{8,64}", t) else None


@router.post("/api/py/kite/token")
async def kite_token(request: Request):
    """Connect by pasting the post-login address. Kite only redirects to https:// or http://127.0.0.1, and this
    dashboard runs on plain http, so the login lands on an unreachable 127.0.0.1 page whose address carries the
    request_token."""
    body = await request.json()
    tok = token_from(body.get("text"))
    if not tok:
        raise HTTPException(400, "no request_token in that text: paste the whole address of the page after the login")
    try:
        st = K.exchange(tok)
    except K.KiteError as e:
        raise HTTPException(400, "Zerodha refused it: %s (a token works once, for a few minutes: log in again)" % e)
    print("kite: connected by pasted login address (user %s)" % st.get("user"), flush=True)
    return st


@router.post("/api/py/kite/logout")
def kite_logout():
    K.forget_session()
    return K.status()


def _file(path):
    """(doc, age in seconds) of a ticker's file, or ({}, None)."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc, max(0.0, time.time() - float(doc.get("written", 0)))
    except (FileNotFoundError, ValueError, TypeError):
        return {}, None


def _crypto():
    return _file(CX.TICKS_FILE)


@router.get("/api/py/live/ticks")
def live_ticks():
    doc, age = _ticker()
    ticks = {k: {f: v.get(f) for f in FIELDS if v.get(f) is not None} for k, v in (doc.get("ticks") or {}).items()}
    cdoc, cage = _crypto()
    crypto_live = cage is not None and cage < 5
    if crypto_live:   # Coinbase public ticker (crypto_ticker.py)
        for k, v in (cdoc.get("ticks") or {}).items():
            ticks[k] = {f: v.get(f) for f in FIELDS + ("chg_pct",) if v.get(f) is not None}
    udoc, uage = _file(AL.TICKS_FILE)
    us_live = uage is not None and uage < 10
    if us_live:       # Alpaca IEX (us_ticker.py)
        for k, v in (udoc.get("ticks") or {}).items():
            ticks[k] = {f: v.get(f) for f in FIELDS + ("chg_pct",) if v.get(f) is not None}
    return {"age_s": None if age is None else round(age, 1), "live": age is not None and age < 5,
            "connected": K.connected(), "ticks": ticks, "indices": K.WATCH_INDICES,
            "missing": doc.get("missing") or [],
            "crypto_live": crypto_live, "crypto_age_s": None if cage is None else round(cage, 1),
            "crypto_source": "Coinbase (public data, no API key)",
            "crypto_missing": cdoc.get("missing") or [],
            "us_live": us_live, "us_age_s": None if uage is None else round(uage, 1),
            "us_configured": AL.configured(), "us_source": "Alpaca IEX (paper key, data only)",
            "us_missing": udoc.get("missing") or []}
