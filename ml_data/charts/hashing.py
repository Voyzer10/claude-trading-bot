"""Canonical serialization and SHA-256 helpers for chart identities (no floats, stable key order)."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .exceptions import ChartContractError

SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _reject_floats(obj: Any, path: str = "$") -> None:
    if isinstance(obj, float):
        raise ChartContractError(f"float values are not allowed in canonical identity payloads (at {path})")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise ChartContractError(f"non-string key in canonical payload at {path}: {k!r}")
            _reject_floats(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _reject_floats(v, f"{path}[{i}]")


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators, ASCII only; floats are rejected."""
    _reject_floats(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of_payload(obj: Any) -> str:
    return sha256_hex(canonical_json(obj).encode("utf-8"))


def is_sha256_hex(val: Any) -> bool:
    """True for a complete lowercase 64-character SHA-256 hex digest."""
    return isinstance(val, str) and bool(SHA256_HEX_RE.match(val))


def require_sha256_hex(val: Any, name: str) -> str:
    if not is_sha256_hex(val):
        raise ChartContractError(f"{name} must be a lowercase 64-character SHA-256 hex digest (got {val!r})")
    return val
