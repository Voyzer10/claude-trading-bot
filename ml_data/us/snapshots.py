"""Unified content-addressed, immutable snapshot storage and integrity validation for US discovery."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .config import UTC_TZ
from .exceptions import AlpacaAdapterError

_NEW_MAN_RE_TEMPLATE = r"^{comp}_([0-9a-f]{{12}})_([0-9a-f]{{16}})_manifest\.json$"
_LEGACY_FILTERED_MAN_RE_TEMPLATE = r"^{comp}_([0-9a-f]{{12}})_manifest\.json$"


def serialize_snapshot_rows(rows: Sequence[Dict[str, Any]]) -> str:
    """Serialize discovery rows canonically for deterministic SHA-256 hashing."""
    return json.dumps(list(rows), sort_keys=True)


def compute_sha256(text: str) -> str:
    """Compute hex SHA-256 digest of canonical UTF-8 payload text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_filter_hash(filters: Optional[Dict[str, Any]]) -> str:
    """Short deterministic hash of discovery filter parameters."""
    return hashlib.sha256(json.dumps(filters or {}, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def atomic_write_gz(path: str, text: str) -> None:
    """Atomically write gzipped UTF-8 text via temp file + fsync + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "wb") as raw_fh:
            with gzip.GzipFile(fileobj=raw_fh, mode="wb") as gz_fh:
                gz_fh.write(text.encode("utf-8"))
            raw_fh.flush()
            os.fsync(raw_fh.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    """Atomically write JSON file via temp file + fsync + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


@dataclass(frozen=True)
class StoredSnapshot:
    """Validated immutable snapshot record loaded from or persisted to disk."""

    component: str
    snapshot_date: date
    retrieved_at_utc: datetime
    sha256: str
    count: int
    raw_gz_path: str
    manifest_path: str
    rows: Tuple[Dict[str, Any], ...]
    filters: Dict[str, Any]
    pages_fetched: int
    pagination_complete: bool
    revision: int
    revision_id: str


class ImmutableSnapshotStore:
    """Content-addressed, append-only daily snapshot store shared across US discovery modules.

    Each distinct (filters, content_sha256) payload is written once to:
        <raw_root>/date=<YYYY-MM-DD>/<component>_<fhash>_<sha16>.json.gz
        <manifest_root>/date=<YYYY-MM-DD>/<component>_<fhash>_<sha16>_manifest.json

    Manifests are written atomically only after the compressed payload is synced on disk.
    Legacy non-content-addressed snapshots remain readable and are never overwritten.
    """

    def __init__(
        self,
        *,
        component: str,
        raw_root: str,
        manifest_root: str,
        default_filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.component = component
        self.raw_root = raw_root
        self.manifest_root = manifest_root
        self.default_filters = dict(default_filters) if default_filters is not None else None
        self._new_man_re = re.compile(_NEW_MAN_RE_TEMPLATE.format(comp=re.escape(component)))
        self._legacy_f_man_re = re.compile(_LEGACY_FILTERED_MAN_RE_TEMPLATE.format(comp=re.escape(component)))

    def date_dirs(self, snap_date: date) -> Tuple[str, str]:
        d_str = snap_date.isoformat()
        return (
            os.path.join(self.raw_root, f"date={d_str}"),
            os.path.join(self.manifest_root, f"date={d_str}"),
        )

    def content_paths(self, snap_date: date, filters: Optional[Dict[str, Any]], sha256: str) -> Tuple[str, str]:
        sdir, mdir = self.date_dirs(snap_date)
        f_hash = canonical_filter_hash(filters)
        rev_id = sha256[:16]
        return (
            os.path.join(sdir, f"{self.component}_{f_hash}_{rev_id}.json.gz"),
            os.path.join(mdir, f"{self.component}_{f_hash}_{rev_id}_manifest.json"),
        )

    def _resolve_gz_for_manifest(self, man_path: str, man: Dict[str, Any], sdir: str) -> str:
        snap_file = man.get("snapshot_file")
        if snap_file is not None:
            fname = str(snap_file)
            if not fname or os.path.basename(fname) != fname or fname in (".", ".."):
                raise AlpacaAdapterError(f"Invalid snapshot_file {fname!r} in manifest {man_path}")
            return os.path.join(sdir, fname)

        snap_path = man.get("snapshot_path")
        if snap_path:
            return str(snap_path)

        mname = os.path.basename(man_path)
        m_new = self._new_man_re.fullmatch(mname)
        if m_new:
            return os.path.join(sdir, f"{self.component}_{m_new.group(1)}_{m_new.group(2)}.json.gz")
        m_leg_f = self._legacy_f_man_re.fullmatch(mname)
        if m_leg_f:
            return os.path.join(sdir, f"{self.component}_{m_leg_f.group(1)}.json.gz")
        if mname == f"{self.component}_manifest.json":
            return os.path.join(sdir, f"{self.component}.json.gz")
        raise AlpacaAdapterError(f"Cannot resolve snapshot file from manifest {man_path}")

    def _load_manifest_entry(
        self,
        man_path: str,
        snap_date: date,
        expected_filters: Optional[Dict[str, Any]],
    ) -> Optional[StoredSnapshot]:
        try:
            with open(man_path, encoding="utf-8") as fh:
                man = json.load(fh)
        except Exception as e:
            raise AlpacaAdapterError(f"Unreadable or corrupt snapshot manifest {man_path}: {e}") from e

        if not isinstance(man, dict):
            raise AlpacaAdapterError(f"Malformed snapshot manifest (expected JSON object): {man_path}")

        man_comp = man.get("component")
        if man_comp is not None and man_comp != self.component:
            return None

        if "sha256" not in man or "retrieved_at_utc" not in man:
            raise AlpacaAdapterError(f"Incomplete snapshot manifest missing sha256/retrieved_at_utc: {man_path}")

        if expected_filters is not None:
            if "filters" in man:
                if man.get("filters") != expected_filters:
                    return None
            elif self.default_filters is not None and expected_filters != self.default_filters:
                return None

        if man.get("snapshot_date") and man["snapshot_date"] != snap_date.isoformat():
            raise AlpacaAdapterError(
                f"Manifest snapshot_date {man['snapshot_date']!r} mismatches directory date {snap_date.isoformat()}"
            )

        sdir, _ = self.date_dirs(snap_date)
        gz_path = self._resolve_gz_for_manifest(man_path, man, sdir)
        if not os.path.isfile(gz_path):
            raise AlpacaAdapterError(f"Manifest {man_path} references missing snapshot file {gz_path}")

        try:
            with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
                raw_text = fh.read()
        except Exception as e:
            raise AlpacaAdapterError(f"Failed to read snapshot gzip {gz_path}: {e}") from e

        actual_sha = compute_sha256(raw_text)
        expected_sha = str(man["sha256"])
        if actual_sha != expected_sha:
            raise AlpacaAdapterError(
                f"Checksum mismatch in snapshot {gz_path}: manifest={expected_sha}, actual={actual_sha}"
            )

        try:
            rows = json.loads(raw_text)
        except Exception as e:
            raise AlpacaAdapterError(f"Corrupt JSON payload in snapshot {gz_path}: {e}") from e
        if not isinstance(rows, list):
            raise AlpacaAdapterError(f"Malformed snapshot payload (expected list) in {gz_path}")

        expected_count = man.get("count", man.get("raw_count"))
        if expected_count is not None and int(expected_count) != len(rows):
            raise AlpacaAdapterError(
                f"Snapshot row count mismatch in {gz_path}: manifest={expected_count}, actual={len(rows)}"
            )

        dt_raw = str(man["retrieved_at_utc"]).replace("Z", "+00:00")
        retrieved_dt = datetime.fromisoformat(dt_raw)
        if retrieved_dt.tzinfo is None:
            retrieved_dt = retrieved_dt.replace(tzinfo=UTC_TZ)
        else:
            retrieved_dt = retrieved_dt.astimezone(UTC_TZ)

        return StoredSnapshot(
            component=self.component,
            snapshot_date=snap_date,
            retrieved_at_utc=retrieved_dt,
            sha256=actual_sha,
            count=len(rows),
            raw_gz_path=gz_path,
            manifest_path=man_path,
            rows=tuple(rows),
            filters=dict(man.get("filters") or expected_filters or self.default_filters or {}),
            pages_fetched=int(man.get("pages_fetched") or 1),
            pagination_complete=bool(man.get("pagination_complete", True)),
            revision=int(man.get("revision") or 1),
            revision_id=str(man.get("revision_id") or actual_sha[:16]),
        )

    def _is_component_manifest(self, filename: str) -> bool:
        if filename.endswith(".tmp"):
            return False
        if self._new_man_re.fullmatch(filename):
            return True
        if filename == f"{self.component}_manifest.json":
            return True
        if self._legacy_f_man_re.fullmatch(filename):
            return True
        return False

    def list_snapshots(
        self,
        snap_date: date,
        *,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[StoredSnapshot]:
        """List all valid committed snapshot revisions on snap_date ordered oldest to newest."""
        _, mdir = self.date_dirs(snap_date)
        if not os.path.isdir(mdir):
            return []
        entries: List[StoredSnapshot] = []
        for fname in sorted(os.listdir(mdir)):
            if not self._is_component_manifest(fname):
                continue
            snap = self._load_manifest_entry(os.path.join(mdir, fname), snap_date, filters)
            if snap is not None:
                entries.append(snap)
        entries.sort(key=lambda s: (s.revision, s.retrieved_at_utc, s.manifest_path))
        return entries

    def load_snapshot(
        self,
        snap_date: date,
        *,
        filters: Optional[Dict[str, Any]] = None,
        revision: Optional[int] = None,
        sha256: Optional[str] = None,
    ) -> Optional[StoredSnapshot]:
        """Load the latest (or specific revision/sha256) validated snapshot on snap_date."""
        entries = self.list_snapshots(snap_date, filters=filters)
        if revision is not None:
            entries = [e for e in entries if e.revision == revision]
        if sha256 is not None:
            entries = [e for e in entries if e.sha256 == sha256]
        return entries[-1] if entries else None

    def persist(
        self,
        *,
        snap_date: date,
        now_utc: datetime,
        filters: Optional[Dict[str, Any]],
        raw_rows: Sequence[Dict[str, Any]],
        pages_fetched: int = 1,
        pagination_complete: bool = True,
        dry_run: bool = False,
        write_gz: Callable[[str, str], None] = atomic_write_gz,
        write_json: Callable[[str, Dict[str, Any]], None] = atomic_write_json,
    ) -> StoredSnapshot:
        """Persist an immutable content-addressed snapshot or idempotently reuse an identical one."""
        norm_filters = dict(filters or {})
        raw_text = serialize_snapshot_rows(raw_rows)
        sha = compute_sha256(raw_text)
        ret_utc = now_utc.astimezone(timezone.utc) if now_utc.tzinfo else now_utc.replace(tzinfo=UTC_TZ)

        existing = self.list_snapshots(snap_date, filters=norm_filters)
        for snap in existing:
            if snap.sha256 == sha:
                return snap

        gz_path, man_path = self.content_paths(snap_date, norm_filters, sha)
        next_rev = max((s.revision for s in existing), default=0) + 1
        rev_id = sha[:16]

        if not dry_run:
            if os.path.exists(man_path):
                raise AlpacaAdapterError(f"Refusing to overwrite existing snapshot manifest: {man_path}")

            need_gz_write = True
            created_gz = not os.path.exists(gz_path)
            if not created_gz:
                # An unmanifested file at this content-addressed path could be from an interrupted commit.
                try:
                    with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
                        existing_text = fh.read()
                    if compute_sha256(existing_text) == sha:
                        need_gz_write = False
                    else:
                        raise AlpacaAdapterError(
                            f"Refusing to overwrite existing snapshot payload with mismatched hash: {gz_path}"
                        )
                except AlpacaAdapterError:
                    raise
                except Exception as e:
                    raise AlpacaAdapterError(
                        f"Refusing to overwrite unreadable existing snapshot file {gz_path}: {e}"
                    ) from e

            if need_gz_write:
                write_gz(gz_path, raw_text)

            manifest_payload = {
                "schema_version": 2,
                "component": self.component,
                "snapshot_date": snap_date.isoformat(),
                "retrieved_at_utc": ret_utc.isoformat(),
                "revision": next_rev,
                "revision_id": rev_id,
                "sha256": sha,
                "snapshot_file": os.path.basename(gz_path),
                "snapshot_path": gz_path,
                "manifest_file": os.path.basename(man_path),
                "count": len(raw_rows),
                "raw_count": len(raw_rows),
                "filters": norm_filters,
                "filters_hash": canonical_filter_hash(norm_filters),
                "pages_fetched": int(pages_fetched),
                "pagination_complete": bool(pagination_complete),
            }
            try:
                write_json(man_path, manifest_payload)
            except Exception:
                if created_gz and os.path.exists(gz_path):
                    try:
                        os.remove(gz_path)
                    except OSError:
                        pass
                raise

        return StoredSnapshot(
            component=self.component,
            snapshot_date=snap_date,
            retrieved_at_utc=ret_utc,
            sha256=sha,
            count=len(raw_rows),
            raw_gz_path=gz_path,
            manifest_path=man_path,
            rows=tuple(raw_rows),
            filters=norm_filters,
            pages_fetched=int(pages_fetched),
            pagination_complete=bool(pagination_complete),
            revision=next_rev,
            revision_id=rev_id,
        )
