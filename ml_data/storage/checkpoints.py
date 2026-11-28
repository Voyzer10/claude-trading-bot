"""Atomic, key-isolated ingestion checkpoint store."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any, Dict, Optional


class IngestionCheckpointStore:
    """Persists isolated checkpoints keyed by instrument, timeframe, range, feed, adjustment, and snapshot."""

    def __init__(self, root_dir: str) -> None:
        self.root_dir = root_dir

    def _path(self, key_fields: Dict[str, Any]) -> str:
        raw = json.dumps(key_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()[:20]
        return os.path.join(self.root_dir, f"ckpt_{digest}.json")

    def load(self, key_fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        p = self._path(key_fields)
        if not os.path.isfile(p):
            return None
        try:
            with open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
            if isinstance(doc, dict) and doc.get("key_fields") == key_fields:
                return doc
        except Exception:
            return None
        return None

    def save(self, key_fields: Dict[str, Any], state: Dict[str, Any]) -> str:
        p = self._path(key_fields)
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
        tmp = f"{p}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"key_fields": key_fields, "state": state}, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
        return p
