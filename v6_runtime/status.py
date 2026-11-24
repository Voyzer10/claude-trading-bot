"""Aggregated V6 status for the API and the dashboard. Never fabricates figures: a book that does not exist or does not
reconcile is NOT READY, and its money fields are absent, not zero."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from . import identity, options, us_stocks
from .books import BOOKS
from .data.alpaca import DEFAULT_CREDENTIAL_FILE
from .ledger import BookLedger, LedgerError
from .paths import DataRoot

HEARTBEAT_MAX_AGE = timedelta(minutes=3)


def _parse(ts: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def runner_state(root: DataRoot, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    hb = root.read_json("runtime", "heartbeat.json") if root.exists() else None
    at = _parse((hb or {}).get("at"))
    if hb is None or at is None:
        return {"state": "NOT_ACTIVE", "reason": "no runner heartbeat", "heartbeat": None}
    if now - at > HEARTBEAT_MAX_AGE:
        return {"state": "NOT_ACTIVE", "reason": "heartbeat older than %s" % HEARTBEAT_MAX_AGE, "heartbeat": hb}
    return {"state": "ACTIVE", "reason": None, "heartbeat": hb}


def credential_present(path: str = DEFAULT_CREDENTIAL_FILE) -> bool:
    """Existence only: the API never opens the credential."""
    return os.path.exists(path)


def book_status(root: DataRoot, book_id: str, mtm: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    sp = BOOKS[book_id]
    base = {"book_id": book_id, "label": sp.label, "currency": sp.currency, "starting_budget": str(sp.starting_budget),
            "budget_decision": sp.decision}
    if not root.exists() or not BookLedger.exists(root, book_id):
        return dict(base, state="NOT_INITIALISED", summary=None, reason="book not created (needs owner authorisation)")
    try:
        led = BookLedger.load(root, book_id)
    except LedgerError as e:
        return dict(base, state="NOT_READY", summary=None, reason="ledger does not load / reconcile: %s" % e)
    hb_mtm = mtm
    if hb_mtm is None and led.open_trade is not None:
        rt = root.read_json("runtime", "mtm_%s.json" % book_id) or None
        hb_mtm = rt
    return dict(base, state="LOADED", summary=led.summary(hb_mtm), reason=None)


def overall(root: DataRoot, now: Optional[datetime] = None, cred_path: str = DEFAULT_CREDENTIAL_FILE) -> Dict[str, Any]:
    ident = identity.scanner_identity()
    rs = runner_state(root, now) if root.exists() else {"state": "NOT_ACTIVE", "reason": "V6 data root missing",
                                                         "heartbeat": None}
    if ident["status"] != identity.CONNECTED:
        label, why = identity.NOT_CONNECTED, ident["reason"]
    elif not root.exists():
        label, why = identity.NOT_CONNECTED, "V6 data root %s does not exist" % root.root
    elif rs["state"] != "ACTIVE":
        label, why = identity.NOT_ACTIVE, rs["reason"]
    else:
        label, why = identity.CONNECTED, None
    cal = us_stocks.load_calendar()
    try:
        cfg = us_stocks.load_config(root) if root.exists() else None
        us_ready = us_stocks.readiness(cfg, cal, credential_present(cred_path))
    except (us_stocks.USConfigError, ValueError) as e:
        us_ready = {"book_id": "US", "ready": False, "blockers": ["us_stocks.json invalid: %s" % e]}
    return {
        "scanner": {"label": label, "reason": why, **{k: ident.get(k) for k in (
            "scanner_name", "scanner_version", "execution_mode", "paper_only", "places_orders", "package_sha256",
            "pipeline")}},
        "paper_only": True, "places_orders": False,
        "data_root": {"path": root.root, "exists": root.exists()},
        "runner": rs,
        "readiness": {"US": us_ready, "USFNO": options.readiness()},
        "books": {b: book_status(root, b) for b in BOOKS},
        "calendar": {"verified": bool(cal.get("verified")), "note": cal.get("verification_note")},
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
    }
