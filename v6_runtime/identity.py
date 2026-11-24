"""Backend-verified scanner identity. The dashboard shows what this returns; it never hard-codes the label.

The identity is derived from the scanner_v6 package actually importable by this process. If that package is missing,
or its safety constants are not PAPER_ONLY=True / PLACES_ORDERS=False, the identity is NOT CONNECTED and nothing runs.
"""
from __future__ import annotations

import hashlib
import os
from typing import Dict, Optional

SCANNER_NAME = "V6 SMC Scanner"
SCANNER_VERSION = "V6"
EXECUTION_MODE = "PAPER TRADING"
PIPELINE = ("CHoCH", "BOS", "Liquidity sweep", "Candlestick formation", "Confirmation", "Entry")

# Status words shown to the owner. Exactly one applies at a time.
CONNECTED = "V6 SMC Scanner"
NOT_CONNECTED = "V6 NOT CONNECTED"
NOT_ACTIVE = "V6 NOT ACTIVE"


def _package_fingerprint(pkg_dir: str) -> str:
    """sha256 over the scanner_v6 .py sources (sorted relative paths and contents): which code is really loaded."""
    h = hashlib.sha256()
    for dp, dirs, files in os.walk(pkg_dir):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for f in sorted(files):
            if f.endswith(".py"):
                p = os.path.join(dp, f)
                h.update(os.path.relpath(p, pkg_dir).replace(os.sep, "/").encode())
                with open(p, "rb") as fh:
                    h.update(fh.read())
    return h.hexdigest()


def scanner_identity() -> Dict[str, object]:
    """What scanner this backend would run, verified by importing it. Never raises."""
    try:
        import scanner_v6
        from scanner_v6 import config as v6cfg
    except Exception as e:  # noqa: BLE001 - any import failure means "not connected"
        return {"status": NOT_CONNECTED, "scanner_name": None, "scanner_version": None, "execution_mode": None,
                "reason": "scanner_v6 is not importable: %s" % type(e).__name__, "paper_only": None,
                "places_orders": None, "package_sha256": None}
    paper_only, places = getattr(v6cfg, "PAPER_ONLY", None), getattr(v6cfg, "PLACES_ORDERS", None)
    if paper_only is not True or places is not False:
        return {"status": NOT_CONNECTED, "scanner_name": None, "scanner_version": None, "execution_mode": None,
                "reason": "scanner_v6 safety constants are not PAPER_ONLY=True / PLACES_ORDERS=False",
                "paper_only": paper_only, "places_orders": places, "package_sha256": None}
    return {"status": CONNECTED, "scanner_name": SCANNER_NAME, "scanner_version": SCANNER_VERSION,
            "execution_mode": EXECUTION_MODE, "reason": None, "paper_only": True, "places_orders": False,
            "pipeline": list(PIPELINE), "package_sha256": _package_fingerprint(os.path.dirname(scanner_v6.__file__))}


def stamp(extra: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Metadata attached to every V6 signal, trade record and log line."""
    out: Dict[str, object] = {"scanner_name": SCANNER_NAME, "scanner_version": SCANNER_VERSION,
                              "execution_mode": EXECUTION_MODE}
    if extra:
        out.update(extra)
    return out
