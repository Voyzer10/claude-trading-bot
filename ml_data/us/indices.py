"""Dynamic US index asset discovery and index-option capability probing for Alpaca."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

# pyrefly: ignore[missing-import]
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
from .snapshots import (
    ImmutableSnapshotStore,
    StoredSnapshot,
    atomic_write_gz as _shared_atomic_write_gz,
    atomic_write_json as _shared_atomic_write_json,
)


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

_INDEX_DISCOVERY_FILTERS = {"asset_class": "us_index", "exchange": "INDEX"}


@dataclass(frozen=True)
class IndexSnapshot:
    """Immutable, content-addressed US index discovery snapshot."""

    snapshot_date: date
    retrieved_at_utc: datetime
    sha256: str
    raw_count: int
    raw_gz_path: str
    manifest_path: str
    raw_indices: Tuple[Dict[str, Any], ...]
    revision: int = 1
    filters: Dict[str, Any] = field(default_factory=dict)


def _to_index_snapshot(s: StoredSnapshot) -> IndexSnapshot:
    return IndexSnapshot(
        snapshot_date=s.snapshot_date,
        retrieved_at_utc=s.retrieved_at_utc,
        sha256=s.sha256,
        raw_count=s.count,
        raw_gz_path=s.raw_gz_path,
        manifest_path=s.manifest_path,
        raw_indices=s.rows,
        revision=s.revision,
        filters=s.filters,
    )


@dataclass
class IndexDiscoveryReport:
    snapshot_date: date
    snapshot_sha256: Optional[str] = None
    snapshot_path: Optional[str] = None
    indices: List[Instrument] = field(default_factory=list)
    mappings: List[ProviderInstrumentMapping] = field(default_factory=list)
    capabilities: Dict[str, IndexOptionCapability] = field(default_factory=dict)
    retrieved_at_utc: Optional[datetime] = None
    manifest_path: Optional[str] = None
    snapshot_revision: Optional[int] = None


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

    def _store(self) -> ImmutableSnapshotStore:
        return ImmutableSnapshotStore(
            component="indices",
            raw_root=self.raw_root,
            manifest_root=self.manifest_root,
            default_filters=_INDEX_DISCOVERY_FILTERS,
        )

    def _atomic_write_gz(self, path: str, text: str) -> None:
        _shared_atomic_write_gz(path, text)

    def _atomic_write_json(self, path: str, payload: Dict[str, Any]) -> None:
        _shared_atomic_write_json(path, payload)

    def load_snapshot(
        self,
        snap_date: date,
        *,
        revision: Optional[int] = None,
        sha256: Optional[str] = None,
    ) -> Optional[IndexSnapshot]:
        """Load the latest (or specific revision/sha256) validated index snapshot on snap_date."""
        stored = self._store().load_snapshot(
            snap_date,
            filters=_INDEX_DISCOVERY_FILTERS,
            revision=revision,
            sha256=sha256,
        )
        return _to_index_snapshot(stored) if stored is not None else None

    def list_snapshots(self, snap_date: date) -> List[IndexSnapshot]:
        """List all immutable index snapshot revisions committed on snap_date."""
        return [_to_index_snapshot(s) for s in self._store().list_snapshots(snap_date, filters=_INDEX_DISCOVERY_FILTERS)]

    def fetch_raw_indices(self) -> List[Dict[str, Any]]:
        resp = self.client.request(
            "trading",
            "/v2/assets",
            params=dict(_INDEX_DISCOVERY_FILTERS),
        )
        rows = resp.body if isinstance(resp.body, list) else (resp.body or {}).get("assets") or []
        return [r for r in rows if isinstance(r, dict)]

    def download_snapshot(
        self,
        *,
        snap_date: Optional[date] = None,
        dry_run: bool = False,
        force_refresh: bool = False,
    ) -> IndexSnapshot:
        """Fetch and persist an immutable US index snapshot; force_refresh adds a revision only on content change."""
        now_utc = datetime.now(UTC_TZ)
        target_date = snap_date or now_utc.astimezone(NY_TZ).date()

        if not force_refresh:
            existing = self.load_snapshot(target_date)
            if existing is not None:
                return existing

        raw_rows = self.fetch_raw_indices()
        stored = self._store().persist(
            snap_date=target_date,
            now_utc=now_utc,
            filters=dict(_INDEX_DISCOVERY_FILTERS),
            raw_rows=raw_rows,
            pages_fetched=1,
            pagination_complete=True,
            dry_run=dry_run,
            write_gz=self._atomic_write_gz,
            write_json=self._atomic_write_json,
        )
        return _to_index_snapshot(stored)

    def discover_indices(
        self,
        *,
        registry: Optional[InstrumentRegistry] = None,
        dry_run: bool = False,
        snap_date: Optional[date] = None,
        snapshot: Optional[IndexSnapshot] = None,
        force_refresh: Optional[bool] = None,
    ) -> IndexDiscoveryReport:
        if snapshot is not None:
            snap = snapshot
        else:
            snap = self.download_snapshot(
                snap_date=snap_date,
                dry_run=dry_run,
                force_refresh=True if force_refresh is None else force_refresh,
            )

        now_utc = snap.retrieved_at_utc
        snap_path = snap.raw_gz_path if (not dry_run or os.path.isfile(snap.raw_gz_path)) else None
        man_path = snap.manifest_path if (not dry_run or os.path.isfile(snap.manifest_path)) else None
        report = IndexDiscoveryReport(
            snapshot_date=snap.snapshot_date,
            snapshot_sha256=snap.sha256,
            snapshot_path=snap_path,
            retrieved_at_utc=now_utc,
            manifest_path=man_path,
            snapshot_revision=snap.revision,
        )

        for raw in snap.raw_indices:
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
                    "snapshot_date": snap.snapshot_date.isoformat(),
                    "snapshot_sha256": snap.sha256,
                    "snapshot_revision": snap.revision,
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
