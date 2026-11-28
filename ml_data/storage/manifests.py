"""Immutable dataset manifests with SHA-256 file checksums and integrity verification."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from .exceptions import ManifestError


def compute_file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    dataset_version: str
    schema_version: str
    markets: List[str]
    providers: List[str]
    feeds: List[str]
    instrument_ids: List[str]
    requested_start_utc: str
    requested_end_utc: str
    actual_start_utc: Optional[str]
    actual_end_utc: Optional[str]
    source_snapshot_ids: List[str]
    adjustment_modes: List[str]
    calendar_versions: List[str]
    row_count: int
    duplicate_count: int
    invalid_count: int
    missing_timestamps_count: int
    pagination_complete: bool
    quality_summary: Dict[str, Any]
    file_paths: List[str]
    file_sha256s: Dict[str, str]
    created_at_utc: str
    git_commit: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def semantic_dict(self) -> Dict[str, Any]:
        """All semantic metadata fields for strict immutability checks (excludes generated created_at_utc)."""
        d = asdict(self)
        d.pop("created_at_utc", None)
        return d


def write_manifest(manifest: DatasetManifest, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest.to_dict(), fh, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path


def verify_manifest(path: str) -> DatasetManifest:
    if not os.path.isfile(path):
        raise ManifestError(f"Manifest file not found: {path}")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    man = DatasetManifest(**doc)
    for fpath in man.file_paths:
        if not os.path.isfile(fpath):
            raise ManifestError(f"Manifest references missing file: {fpath}")
        expected = man.file_sha256s.get(fpath)
        actual = compute_file_sha256(fpath)
        if expected != actual:
            raise ManifestError(f"SHA-256 mismatch for {fpath}: expected {expected}, got {actual}")
    return man
