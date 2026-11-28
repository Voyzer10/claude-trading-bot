"""US equity-index futures contract discovery and Identity v3 registry mapping."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence

from ..instruments import (
    AssetClass,
    ContractType,
    Instrument,
    InstrumentRegistry,
    InstrumentStatus,
    MarginType,
    Market,
    ProviderInstrumentMapping,
    Segment,
    SettlementType,
)
from .client import DatabentoHistoricalClient
from .config import CANDIDATE_INDEX_FUTURES_ROOTS, DATABENTO_DATASET, UTC_TZ
from .instrument_definitions import DatabentoDefinitionRecord, parse_definition_records

DEFAULT_FUTURES_RAW_ROOT = os.path.join("data", "raw", "us", "databento", "definitions")
DEFAULT_FUTURES_MANIFEST_ROOT = os.path.join("data", "manifests", "us", "databento")


@dataclass
class FuturesDiscoveryReport:
    dataset: str
    snapshot_date: date
    snapshot_sha256: str
    snapshot_path: Optional[str] = None
    contracts: List[Instrument] = field(default_factory=list)
    mappings: List[ProviderInstrumentMapping] = field(default_factory=list)
    skipped: List[Dict[str, str]] = field(default_factory=list)


_ROOT_TO_INDEX_SYMBOL: Dict[str, str] = {
    "ES": "SPX",
    "MES": "SPX",
    "NQ": "NDX",
    "MNQ": "NDX",
    "YM": "DJI",
    "MYM": "DJI",
    "RTY": "RUT",
    "M2K": "RUT",
}


class FuturesContractDiscovery:
    """Discovers active and historical CME equity-index futures from Databento definition records."""

    def __init__(
        self,
        *,
        client: Optional[DatabentoHistoricalClient] = None,
        dataset: str = DATABENTO_DATASET,
        raw_root: str = DEFAULT_FUTURES_RAW_ROOT,
        manifest_root: str = DEFAULT_FUTURES_MANIFEST_ROOT,
    ) -> None:
        self.client = client or DatabentoHistoricalClient()
        self.dataset = dataset
        self.raw_root = raw_root
        self.manifest_root = manifest_root

    def _persist_snapshot(self, snap_date: date, now_utc: datetime, raw_rows: Sequence[Dict[str, Any]]) -> tuple[str, str]:
        payload = json.dumps(list(raw_rows), sort_keys=True)
        sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        sdir = os.path.join(self.raw_root, f"date={snap_date.isoformat()}")
        mdir = os.path.join(self.manifest_root, f"date={snap_date.isoformat()}")
        os.makedirs(sdir, exist_ok=True)
        os.makedirs(mdir, exist_ok=True)
        gz_path = os.path.join(sdir, "definitions.json.gz")
        man_path = os.path.join(mdir, "definitions_manifest.json")
        rev = 0
        already = False
        while os.path.exists(gz_path) and os.path.exists(man_path):
            try:
                with open(man_path, encoding="utf-8") as fh:
                    if json.load(fh).get("sha256") == sha:
                        already = True
                        break
            except Exception:
                pass
            rev += 1
            gz_path = os.path.join(sdir, f"definitions.rev{rev}.json.gz")
            man_path = os.path.join(mdir, f"definitions_manifest.rev{rev}.json")
        if not already:
            tmp_gz = f"{gz_path}.{os.getpid()}.tmp"
            with gzip.open(tmp_gz, "wt", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
            os.replace(tmp_gz, gz_path)
            tmp_man = f"{man_path}.{os.getpid()}.tmp"
            with open(tmp_man, "w", encoding="utf-8") as fh:
                json.dump({
                    "dataset": self.dataset,
                    "snapshot_date": snap_date.isoformat(),
                    "revision": rev,
                    "retrieved_at_utc": now_utc.isoformat(),
                    "sha256": sha,
                    "count": len(raw_rows),
                }, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_man, man_path)
        return sha, gz_path

    def discover_from_definitions(
        self,
        raw_definitions: Sequence[Dict[str, Any]],
        *,
        registry: Optional[InstrumentRegistry] = None,
        allowed_roots: Sequence[str] = CANDIDATE_INDEX_FUTURES_ROOTS,
        as_of_date: Optional[date] = None,
        dry_run: bool = False,
    ) -> FuturesDiscoveryReport:
        now_utc = datetime.now(UTC_TZ)
        ref_date = as_of_date or now_utc.date()
        allowed = {r.strip().upper() for r in allowed_roots}
        defs = parse_definition_records(raw_definitions, dataset=self.dataset)
        sha = hashlib.sha256(json.dumps(list(raw_definitions), sort_keys=True).encode("utf-8")).hexdigest()
        snap_path: Optional[str] = None
        if not dry_run:
            sha, snap_path = self._persist_snapshot(ref_date, now_utc, raw_definitions)

        report = FuturesDiscoveryReport(
            dataset=self.dataset,
            snapshot_date=ref_date,
            snapshot_sha256=sha,
            snapshot_path=snap_path,
        )

        for d in defs:
            if d.product_root not in allowed:
                report.skipped.append({"raw_symbol": d.raw_symbol, "reason": f"Root {d.product_root!r} outside initial scope"})
                continue
            is_expired = d.expiry_date < ref_date
            status = InstrumentStatus.EXPIRED if is_expired else InstrumentStatus.ACTIVE
            settle = SettlementType.PHYSICAL if d.settlement_type == "PHYSICAL" else SettlementType.CASH

            idx_sym = _ROOT_TO_INDEX_SYMBOL.get(d.product_root)
            und_id: Optional[str] = None
            if idx_sym is not None:
                und_inst = Instrument(
                    instrument_id="",
                    market=Market.US,
                    asset_class=AssetClass.INDEX,
                    segment=Segment.US_INDEX,
                    exchange=d.exchange,
                    canonical_symbol=idx_sym,
                    trading_symbol=idx_sym,
                    display_name=f"{idx_sym} Index",
                    price_currency=d.currency,
                    is_tradable=False,
                    trading_calendar="XCME_GLOBEX",
                    timezone="America/Chicago",
                    primary_provider="databento",
                    source="canonical_index",
                )
                if registry is not None and not dry_run:
                    registry.upsert(und_inst, validate_underlying=False)
                und_id = und_inst.instrument_id

            inst = Instrument(
                instrument_id="",
                market=Market.US,
                asset_class=AssetClass.FUTURE,
                segment=Segment.US_FUTURES,
                exchange=d.exchange,
                exchange_mic="XCME",
                canonical_symbol=d.raw_symbol,
                trading_symbol=d.raw_symbol,
                display_name=f"{d.product_root} {d.expiry_date.isoformat()} Future ({d.raw_symbol})",
                underlying_instrument_id=und_id,
                price_currency=d.currency,
                expiry_date=d.expiry_date,
                last_trade_date=d.last_trade_date,
                contract_multiplier=d.contract_multiplier,
                tick_size=d.tick_size,
                contract_type=ContractType.DATED_FUTURE,
                settlement_type=settle,
                margin_type=MarginType.STANDARD,
                is_tradable=not is_expired,
                is_active=not is_expired,
                instrument_status=status,
                trading_calendar="XCME_GLOBEX",
                timezone="America/Chicago",
                primary_provider="databento",
                provider_instrument_id=str(d.publisher_instrument_id),
                provider_symbol=d.raw_symbol,
                source="databento_definition",
                last_verified_at=now_utc,
                effective_from=d.ts_event_utc,
                metadata={
                    "dataset": d.dataset,
                    "publisher_id": d.publisher_id,
                    "venue": d.venue,
                    "product_root": d.product_root,
                    "publisher_instrument_id": d.publisher_instrument_id,
                    "tick_value": str(d.tick_value),
                    "snapshot_date": ref_date.isoformat(),
                    "snapshot_sha256": sha,
                },
            )
            mapping = ProviderInstrumentMapping(
                instrument_id=inst.instrument_id,
                provider="databento",
                provider_symbol=d.raw_symbol,
                provider_instrument_id=str(d.publisher_instrument_id),
                provider_exchange=d.venue,
                provider_feed=d.dataset,
                last_verified_at=now_utc,
                is_primary=True,
            )
            report.contracts.append(inst)
            report.mappings.append(mapping)
            if registry is not None and not dry_run:
                registry.upsert(inst, mappings=[mapping], validate_underlying=(und_id is not None))

        return report
