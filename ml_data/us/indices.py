"""Dynamic US index asset discovery and index-option capability probing for Alpaca."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from ..instruments import (
    AssetClass,
    ContractType,
    Instrument,
    InstrumentRegistry,
    InstrumentStatus,
    Market,
    ProviderInstrumentMapping,
    Segment,
    SettlementType,
)
from .client import AlpacaDataClient
from .config import NY_TZ, UTC_TZ
from .exceptions import AlpacaAdapterError, AlpacaAuthError, AlpacaSubscriptionError


@dataclass(frozen=True)
class IndexOptionCapability:
    symbol: str
    underlying_asset_support: bool
    contract_master_support: bool
    historical_bars_support: str       # SUPPORTED / UNSUPPORTED / UNVERIFIED / BLOCKED_BY_SUBSCRIPTION
    historical_quotes_trades_support: str
    snapshot_support: str
    realtime_feed_support: str
    status: str                        # SUPPORTED / UNSUPPORTED / UNVERIFIED
    notes: str = ""


DEFAULT_US_INDICES_ROOT = os.path.join("data", "raw", "us", "alpaca", "indices")
DEFAULT_US_MANIFEST_ROOT = os.path.join("data", "manifests", "us", "alpaca")


@dataclass
class IndexDiscoveryReport:
    snapshot_date: date
    snapshot_sha256: Optional[str] = None
    snapshot_path: Optional[str] = None
    indices: List[Instrument] = field(default_factory=list)
    mappings: List[ProviderInstrumentMapping] = field(default_factory=list)
    capabilities: Dict[str, IndexOptionCapability] = field(default_factory=dict)


class AlpacaIndexDiscovery:
    """Discovers supported US index assets (asset_class=us_index, exchange=INDEX) and probes option families."""

    def __init__(
        self,
        *,
        client: Optional[AlpacaDataClient] = None,
        raw_root: str = DEFAULT_US_INDICES_ROOT,
        manifest_root: str = DEFAULT_US_MANIFEST_ROOT,
    ) -> None:
        self.client = client or AlpacaDataClient()
        self.raw_root = raw_root
        self.manifest_root = manifest_root

    def fetch_raw_indices(self) -> List[Dict[str, Any]]:
        resp = self.client.request(
            "trading",
            "/v2/assets",
            params={"asset_class": "us_index", "exchange": "INDEX"},
        )
        rows = resp.body if isinstance(resp.body, list) else (resp.body or {}).get("assets") or []
        return [r for r in rows if isinstance(r, dict)]

    def discover_indices(
        self,
        *,
        registry: Optional[InstrumentRegistry] = None,
        dry_run: bool = False,
        snap_date: Optional[date] = None,
    ) -> IndexDiscoveryReport:
        now_utc = datetime.now(UTC_TZ)
        target_date = snap_date or now_utc.astimezone(NY_TZ).date()
        raw_rows = self.fetch_raw_indices()
        sha = hashlib.sha256(json.dumps(raw_rows, sort_keys=True).encode("utf-8")).hexdigest()
        snap_path: Optional[str] = None
        if not dry_run:
            sdir = os.path.join(self.raw_root, f"date={target_date.isoformat()}")
            mdir = os.path.join(self.manifest_root, f"date={target_date.isoformat()}")
            os.makedirs(sdir, exist_ok=True)
            os.makedirs(mdir, exist_ok=True)
            snap_path = os.path.join(sdir, "indices.json.gz")
            man_path = os.path.join(mdir, "indices_manifest.json")
            if not os.path.exists(snap_path):
                tmp_gz = f"{snap_path}.{os.getpid()}.tmp"
                with gzip.open(tmp_gz, "wt", encoding="utf-8") as fh:
                    fh.write(json.dumps(raw_rows, sort_keys=True))
                os.replace(tmp_gz, snap_path)
                tmp_man = f"{man_path}.{os.getpid()}.tmp"
                with open(tmp_man, "w", encoding="utf-8") as fh:
                    json.dump({
                        "snapshot_date": target_date.isoformat(),
                        "retrieved_at_utc": now_utc.isoformat(),
                        "sha256": sha,
                        "count": len(raw_rows),
                    }, fh, indent=2, sort_keys=True)
                os.replace(tmp_man, man_path)

        report = IndexDiscoveryReport(snapshot_date=target_date, snapshot_sha256=sha, snapshot_path=snap_path)

        for raw in raw_rows:
            sym = str(raw.get("symbol") or "").strip().upper()
            if not sym:
                continue
            provider_id = str(raw.get("id") or sym)
            st = InstrumentStatus.ACTIVE if str(raw.get("status", "")).lower() == "active" else InstrumentStatus.INACTIVE

            inst = Instrument(
                instrument_id="",
                market=Market.US,
                asset_class=AssetClass.INDEX,
                segment=Segment.US_INDEX,
                exchange="INDEX",
                canonical_symbol=sym,
                trading_symbol=sym,
                display_name=str(raw.get("name") or f"{sym} Index").strip(),
                price_currency="USD",
                contract_type=ContractType.INDEX,
                settlement_type=SettlementType.CASH,
                is_tradable=False,
                is_active=(st == InstrumentStatus.ACTIVE),
                instrument_status=st,
                trading_calendar="XNYS",
                timezone="America/New_York",
                primary_provider="alpaca",
                provider_instrument_id=provider_id,
                provider_symbol=sym,
                source="alpaca_us_index_v2",
                last_verified_at=now_utc,
                metadata={
                    "alpaca_asset_id": provider_id,
                    "has_options": bool(raw.get("has_options", False)),
                    "options_late_close": bool(raw.get("options_late_close", False)),
                    "snapshot_date": target_date.isoformat(),
                },
            )
            mapping = ProviderInstrumentMapping(
                instrument_id=inst.instrument_id,
                provider="alpaca",
                provider_symbol=sym,
                provider_instrument_id=provider_id,
                provider_exchange="INDEX",
                last_verified_at=now_utc,
                is_primary=True,
            )
            report.indices.append(inst)
            report.mappings.append(mapping)
            if registry is not None and not dry_run:
                registry.upsert(inst, mappings=[mapping])

        return report

    def probe_index_option_families(
        self,
        families: Sequence[str] = ("SPX", "SPXW"),
        *,
        discovered_indices: Optional[Sequence[Instrument]] = None,
        option_feed: str = "indicative",
    ) -> Dict[str, IndexOptionCapability]:
        """Probe whether each index option family has contract master and market data support."""
        idx_syms = {i.canonical_symbol for i in (discovered_indices or ())}
        out: Dict[str, IndexOptionCapability] = {}
        for fam in families:
            root = fam.strip().upper()
            has_underlying = root in idx_syms or (root == "SPXW" and "SPX" in idx_syms)
            contract_ok = False
            sample_contract: Optional[str] = None
            try:
                resp = self.client.request(
                    "trading",
                    "/v2/options/contracts",
                    params={"root_symbol": root, "status": "active", "limit": 5, "show_deliverables": "true"},
                )
                contracts = (resp.body or {}).get("option_contracts") or []
                if contracts:
                    contract_ok = True
                    sample_contract = str(contracts[0].get("symbol") or "")
            except AlpacaAdapterError:
                contract_ok = False

            bars_st = "UNVERIFIED"
            qt_st = "UNVERIFIED"
            snap_st = "UNVERIFIED"
            rt_st = "UNVERIFIED"
            if not contract_ok:
                bars_st = qt_st = snap_st = rt_st = "UNSUPPORTED"
                overall = "UNSUPPORTED"
            else:
                try:
                    s_resp = self.client.request(
                        "data",
                        "/v1beta1/options/snapshots",
                        params={"symbols": sample_contract, "feed": option_feed},
                    )
                    snaps = (s_resp.body or {}).get("snapshots") or {}
                    snap_st = "SUPPORTED" if sample_contract in snaps else "UNVERIFIED"
                except AlpacaSubscriptionError:
                    snap_st = "BLOCKED_BY_SUBSCRIPTION"
                except AlpacaAuthError:
                    snap_st = "BLOCKED_BY_AUTH"
                except AlpacaAdapterError:
                    snap_st = "UNSUPPORTED"

                # Contract discovery + 1 snapshot alone does NOT prove historical bars/quotes/trades or realtime
                if snap_st in ("BLOCKED_BY_SUBSCRIPTION", "BLOCKED_BY_AUTH"):
                    overall = snap_st
                elif snap_st == "SUPPORTED":
                    overall = "UNVERIFIED"
                else:
                    overall = "UNSUPPORTED"
                rt_st = f"FEED_{option_feed.upper()}_UNVERIFIED"

            out[root] = IndexOptionCapability(
                symbol=root,
                underlying_asset_support=has_underlying,
                contract_master_support=contract_ok,
                historical_bars_support=bars_st,
                historical_quotes_trades_support=qt_st,
                snapshot_support=snap_st,
                realtime_feed_support=rt_st,
                status=overall,
                notes=f"sample_contract={sample_contract}" if sample_contract else "no active contracts returned",
            )
        return out
