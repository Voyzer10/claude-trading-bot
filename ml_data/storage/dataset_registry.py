"""SQLite dataset & ingestion run registry with schema migrations."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .exceptions import DatasetVersionConflictError
from .manifests import DatasetManifest


class DatasetRegistry:
    """Tracks versioned canonical datasets, manifests, and failed ingestion runs."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._conn = sqlite3.connect(db_path, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS storage_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    pagination_complete INTEGER NOT NULL,
                    manifest_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, dataset_version)
                );

                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    run_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    started_at_utc TEXT NOT NULL,
                    finished_at_utc TEXT
                );
                """
            )
            applied = {r[0] for r in self._conn.execute("SELECT version FROM storage_migrations").fetchall()}
            if 1 not in applied:
                self._conn.execute(
                    "INSERT INTO storage_migrations (version, applied_at) VALUES (1, ?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )

    def schema_version(self) -> int:
        row = self._conn.execute("SELECT MAX(version) FROM storage_migrations").fetchone()
        return int(row[0] or 0)

    def register_manifest(self, manifest: DatasetManifest) -> None:
        existing = self.get_manifest(manifest.dataset_id, manifest.dataset_version)
        if existing is not None:
            existing_sem = DatasetManifest(**existing).semantic_dict()
            if existing_sem != manifest.semantic_dict():
                raise DatasetVersionConflictError(
                    f"Dataset {manifest.dataset_id}@{manifest.dataset_version} is already registered with a different manifest"
                )
            return
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO datasets (
                    dataset_id, dataset_version, schema_version, row_count,
                    pagination_complete, manifest_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.dataset_id,
                    manifest.dataset_version,
                    manifest.schema_version,
                    manifest.row_count,
                    1 if manifest.pagination_complete else 0,
                    json.dumps(manifest.to_dict(), sort_keys=True),
                    manifest.created_at_utc,
                ),
            )

    def record_run(self, run_id: str, dataset_id: str, status: str, error_message: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO ingestion_runs (
                    run_id, dataset_id, status, error_message, started_at_utc, finished_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, dataset_id, status, error_message, now, now),
            )

    def get_manifest(self, dataset_id: str, dataset_version: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT manifest_json FROM datasets WHERE dataset_id = ? AND dataset_version = ?",
            (dataset_id, dataset_version),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def close(self) -> None:
        self._conn.close()
