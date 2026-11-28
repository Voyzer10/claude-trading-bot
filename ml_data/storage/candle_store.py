"""Partitioned, immutable CanonicalCandleStore backed by PyArrow Parquet and manifests."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..instruments.identity import normalize_decimal_str
from .canonical_schema import CANONICAL_SCHEMA_VERSION, CanonicalCandle
from .dataset_registry import DatasetRegistry
from .exceptions import DatasetVersionConflictError, ManifestError
from .manifests import DatasetManifest, compute_file_sha256, verify_manifest, write_manifest
from .parquet import read_candles_parquet, write_candles_parquet


def _canonical_candle_signature(c: CanonicalCandle) -> str:
    """Complete deterministic content signature covering every persisted CanonicalCandle field."""
    def _d(v: Optional[Decimal]) -> Optional[str]:
        return normalize_decimal_str(v) if v is not None else None

    payload = {
        "schema_version": c.schema_version,
        "instrument_id": c.instrument_id,
        "market": c.market,
        "asset_class": c.asset_class,
        "segment": c.segment,
        "exchange": c.exchange,
        "provider": c.provider,
        "provider_symbol": c.provider_symbol,
        "provider_instrument_id": c.provider_instrument_id,
        "timestamp_start_utc": c.timestamp_start_utc.astimezone(timezone.utc).isoformat(),
        "timestamp_end_utc": c.timestamp_end_utc.astimezone(timezone.utc).isoformat(),
        "event_time_utc": c.event_time_utc.astimezone(timezone.utc).isoformat(),
        "received_at_utc": c.received_at_utc.astimezone(timezone.utc).isoformat(),
        "timeframe": c.timeframe,
        "trading_date": c.trading_date.isoformat(),
        "trading_session": c.trading_session,
        "session_id": c.session_id,
        "calendar_id": c.calendar_id,
        "calendar_version": c.calendar_version,
        "open": _d(c.open),
        "high": _d(c.high),
        "low": _d(c.low),
        "close": _d(c.close),
        "volume": _d(c.volume),
        "quote_volume": _d(c.quote_volume),
        "trade_count": c.trade_count,
        "open_interest": _d(c.open_interest),
        "mark_price": _d(c.mark_price),
        "index_price": _d(c.index_price),
        "funding_rate": _d(c.funding_rate),
        "funding_timestamp_utc": c.funding_timestamp_utc.astimezone(timezone.utc).isoformat() if c.funding_timestamp_utc else None,
        "provider_feed": c.provider_feed,
        "source_snapshot_id": c.source_snapshot_id,
        "source_record_id": c.source_record_id,
        "dataset_version": c.dataset_version,
        "adjustment_mode": c.adjustment_mode,
        "retrieval_run_id": c.retrieval_run_id,
        "quality_status": c.quality_status,
        "quality_flags": list(c.quality_flags),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _partition_content_hash(candles: Sequence[CanonicalCandle]) -> str:
    ordered = sorted(candles, key=lambda y: (y.instrument_id, y.timestamp_start_utc, y.adjustment_mode))
    sigs = [_canonical_candle_signature(x) for x in ordered]
    return hashlib.sha256("\n".join(sigs).encode("utf-8")).hexdigest()


class CanonicalCandleStore:
    """Stores partitioned canonical candles as immutable Zstd Parquet files with manifests."""

    def __init__(
        self,
        *,
        canonical_root: str = os.path.join("data", "canonical", "candles"),
        manifest_root: str = os.path.join("data", "manifests", "datasets"),
        registry: Optional[DatasetRegistry] = None,
    ) -> None:
        self.canonical_root = canonical_root
        self.manifest_root = manifest_root
        self.registry = registry

    def write_partitioned(
        self,
        candles: Sequence[CanonicalCandle],
        *,
        dataset_id: str,
        dataset_version: str,
        requested_start_utc: datetime,
        requested_end_utc: datetime,
        duplicate_count: int = 0,
        invalid_count: int = 0,
        missing_timestamps_count: int = 0,
        pagination_complete: bool = True,
        quality_summary: Optional[Dict[str, Any]] = None,
        git_commit: Optional[str] = None,
        registry: Optional[DatasetRegistry] = None,
    ) -> DatasetManifest:
        # Deduplicate exact duplicates; reject same-key conflicting content regardless of input order
        dedup: Dict[tuple, CanonicalCandle] = {}
        dedup_sigs: Dict[tuple, str] = {}
        for c in candles:
            k = (c.instrument_id, c.timeframe, c.adjustment_mode, c.timestamp_start_utc)
            sig = _canonical_candle_signature(c)
            if k in dedup:
                if dedup_sigs[k] != sig:
                    raise DatasetVersionConflictError(
                        f"Conflicting duplicate candle for {c.instrument_id}@{c.timestamp_start_utc.isoformat()} "
                        f"({c.timeframe}, {c.adjustment_mode})"
                    )
                continue
            dedup[k] = c
            dedup_sigs[k] = sig

        # Group by low-to-medium cardinality partition: (market, asset_class, trading_date, timeframe)
        partitions: Dict[Tuple[str, str, str, str], List[CanonicalCandle]] = {}
        for c in dedup.values():
            pkey = (c.market, c.asset_class, c.trading_date.isoformat(), c.timeframe)
            partitions.setdefault(pkey, []).append(c)

        file_paths: List[str] = []
        file_sha256s: Dict[str, str] = {}

        for (mkt, ac, tdate, tf), part_candles in sorted(partitions.items()):
            pdir = os.path.join(
                self.canonical_root,
                f"market={mkt}",
                f"asset_class={ac}",
                f"trading_date={tdate}",
                f"timeframe={tf}",
            )
            part_hash = _partition_content_hash(part_candles)
            fpath = os.path.join(pdir, f"part-{dataset_version}-{part_hash}.parquet")
            if os.path.isfile(fpath):
                existing_candles = read_candles_parquet(fpath)
                if _partition_content_hash(existing_candles) != part_hash:
                    raise DatasetVersionConflictError(
                        f"Existing partition {fpath} content hash does not match {part_hash}"
                    )
            else:
                write_candles_parquet(part_candles, fpath)
            file_paths.append(fpath)
            file_sha256s[fpath] = compute_file_sha256(fpath)

        all_c = sorted(dedup.values(), key=lambda x: (x.instrument_id, x.timestamp_start_utc))
        manifest = DatasetManifest(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            schema_version=CANONICAL_SCHEMA_VERSION,
            markets=sorted({c.market for c in all_c}),
            providers=sorted({c.provider for c in all_c}),
            feeds=sorted({c.provider_feed for c in all_c}),
            instrument_ids=sorted({c.instrument_id for c in all_c}),
            requested_start_utc=requested_start_utc.astimezone(timezone.utc).isoformat(),
            requested_end_utc=requested_end_utc.astimezone(timezone.utc).isoformat(),
            actual_start_utc=all_c[0].timestamp_start_utc.isoformat() if all_c else None,
            actual_end_utc=all_c[-1].timestamp_end_utc.isoformat() if all_c else None,
            source_snapshot_ids=sorted({c.source_snapshot_id for c in all_c}),
            adjustment_modes=sorted({c.adjustment_mode for c in all_c}),
            calendar_versions=sorted({f"{c.calendar_id}:{c.calendar_version}" for c in all_c}),
            row_count=len(all_c),
            duplicate_count=duplicate_count,
            invalid_count=invalid_count,
            missing_timestamps_count=missing_timestamps_count,
            pagination_complete=pagination_complete,
            quality_summary=dict(quality_summary or {}),
            file_paths=file_paths,
            file_sha256s=file_sha256s,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            git_commit=git_commit,
        )
        man_path = os.path.join(self.manifest_root, dataset_id, f"{dataset_version}.json")
        if os.path.isfile(man_path):
            existing_man = verify_manifest(man_path)
            if existing_man.semantic_dict() != manifest.semantic_dict():
                raise DatasetVersionConflictError(
                    f"Dataset version {dataset_id}@{dataset_version} already exists with different semantic metadata or content"
                )
            manifest = existing_man
        else:
            write_manifest(manifest, man_path)

        target_reg = registry if registry is not None else self.registry
        if target_reg is not None:
            target_reg.register_manifest(manifest)
        return manifest

    def read_partition_files(self, file_paths: Sequence[str]) -> List[CanonicalCandle]:
        out: List[CanonicalCandle] = []
        for p in file_paths:
            out.extend(read_candles_parquet(p))
        return sorted(out, key=lambda c: (c.instrument_id, c.timestamp_start_utc))
