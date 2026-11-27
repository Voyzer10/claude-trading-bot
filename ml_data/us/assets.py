"""Dynamic US equity and ETF discovery, immutable daily snapshots, and Identity v3 mapping."""
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
)
from .client import AlpacaDataClient
from .config import NY_TZ, UTC_TZ
from .snapshots import (
    ImmutableSnapshotStore,
    StoredSnapshot,
    atomic_write_gz as _shared_atomic_write_gz,
    atomic_write_json as _shared_atomic_write_json,
)

DEFAULT_US_ASSETS_ROOT = os.path.join("data", "raw", "us", "alpaca", "equities")
DEFAULT_US_MANIFEST_ROOT = os.path.join("data", "manifests", "us", "alpaca")

_EXCHANGE_MICS = {
    "NYSE": "XNYS",
    "NASDAQ": "XNAS",
    "ARCA": "ARCX",
    "NYSEARCA": "ARCX",
    "BATS": "BATS",
    "BZX": "BATS",
    "BYX": "BYX",
    "EDGX": "EDGX",
    "EDGA": "EDGA",
    "MEMX": "MEMX",
    "AMEX": "XASE",
    "IEX": "IEXG",
    "OTC": "OTCM",
    "TXSE": "TXSE",
}

_KNOWN_ETFS = frozenset({"SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "XLK", "XLF", "XLE", "GLD", "SLV", "TLT"})
_DEFAULT_ASSET_FILTERS = {"statuses": ["active", "inactive"]}


def _classify_etf_asset(raw: Dict[str, Any]) -> Tuple[bool, str, bool]:
    """Return (is_etf, classification_source, verified)."""
    sym = str(raw.get("symbol") or "").strip().upper()
    name = str(raw.get("name") or "").strip().upper()
    attrs = [str(a).strip().lower() for a in (raw.get("attributes") or [])]
    if "etf" in attrs or "etp" in attrs:
        return True, "alpaca_attribute", True
    if sym in _KNOWN_ETFS:
        return True, "heuristic_known_etf_list", False
    if " ETF" in name or name.endswith("ETF") or "EXCHANGE TRADED FUND" in name:
        return True, "heuristic_name", False
    return False, "equity_default", False


def _map_status(raw_status: Any) -> InstrumentStatus:
    s = str(raw_status or "").strip().lower()
    if s == "active":
        return InstrumentStatus.ACTIVE
    if s == "inactive":
        return InstrumentStatus.INACTIVE
    return InstrumentStatus.UNKNOWN


@dataclass(frozen=True)
class AssetSnapshot:
    snapshot_date: date
    retrieved_at_utc: datetime
    sha256: str
    raw_count: int
    raw_gz_path: str
    manifest_path: str
    raw_assets: Tuple[Dict[str, Any], ...]
    revision: int = 1
    filters: Dict[str, Any] = field(default_factory=dict)


def _to_asset_snapshot(s: StoredSnapshot) -> AssetSnapshot:
    return AssetSnapshot(
        snapshot_date=s.snapshot_date,
        retrieved_at_utc=s.retrieved_at_utc,
        sha256=s.sha256,
        raw_count=s.count,
        raw_gz_path=s.raw_gz_path,
        manifest_path=s.manifest_path,
        raw_assets=s.rows,
        revision=s.revision,
        filters=s.filters,
    )


@dataclass
class AssetDiscoveryReport:
    snapshot_date: date
    snapshot_sha256: str
    equities: List[Instrument] = field(default_factory=list)
    etfs: List[Instrument] = field(default_factory=list)
    mappings: List[ProviderInstrumentMapping] = field(default_factory=list)
    provider_coverage_note: str = (
        "Alpaca /v2/assets reflects Alpaca-supported US equities/ETFs (not a complete US consolidated security master); "
        "non-tradable assets are retained for data availability."
    )
    retrieved_at_utc: Optional[datetime] = None
    snapshot_path: Optional[str] = None
    manifest_path: Optional[str] = None
    snapshot_revision: Optional[int] = None


def diff_asset_snapshots(
    prev_assets: Sequence[Dict[str, Any]],
    curr_assets: Sequence[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Detect additions, removals, and status/tradability changes keyed by provider asset id or symbol."""
    prev_map = {str(a.get("id") or a.get("symbol")): a for a in prev_assets}
    curr_map = {str(a.get("id") or a.get("symbol")): a for a in curr_assets}

    added = [curr_map[k] for k in sorted(curr_map.keys() - prev_map.keys())]
    removed = [prev_map[k] for k in sorted(prev_map.keys() - curr_map.keys())]
    changed: List[Dict[str, Any]] = []
    tracked = ("symbol", "exchange", "status", "tradable", "marginable", "shortable", "has_options", "options_late_close")
    for k in sorted(prev_map.keys() & curr_map.keys()):
        p, c = prev_map[k], curr_map[k]
        diffs = {f: {"old": p.get(f), "new": c.get(f)} for f in tracked if p.get(f) != c.get(f)}
        if diffs:
            changed.append({"id": k, "symbol": c.get("symbol"), "changes": diffs})
    return {"added": added, "removed": removed, "changed": changed}


class AlpacaAssetsDiscovery:
    """Discovers US equities and ETFs via Alpaca GET /v2/assets with immutable daily snapshots."""

    def __init__(
        self,
        *,
        client: Optional[AlpacaDataClient] = None,
        raw_root: str = DEFAULT_US_ASSETS_ROOT,
        manifest_root: str = DEFAULT_US_MANIFEST_ROOT,
    ) -> None:
        self.client = client or AlpacaDataClient()
        self.raw_root = raw_root
        self.manifest_root = manifest_root

    def _store(self) -> ImmutableSnapshotStore:
        return ImmutableSnapshotStore(
            component="assets",
            raw_root=self.raw_root,
            manifest_root=self.manifest_root,
            default_filters=_DEFAULT_ASSET_FILTERS,
        )

    @staticmethod
    def _normalize_filters(statuses: Optional[Sequence[str]]) -> Optional[Dict[str, Any]]:
        if statuses is None:
            return None
        return {"statuses": list(dict.fromkeys(str(s).strip().lower() for s in statuses if str(s).strip()))}

    def _atomic_write_gz(self, path: str, text: str) -> None:
        _shared_atomic_write_gz(path, text)

    def _atomic_write_json(self, path: str, payload: Dict[str, Any]) -> None:
        _shared_atomic_write_json(path, payload)

    def load_snapshot(
        self,
        snap_date: date,
        *,
        statuses: Optional[Sequence[str]] = ("active", "inactive"),
        revision: Optional[int] = None,
        sha256: Optional[str] = None,
    ) -> Optional[AssetSnapshot]:
        """Load the latest (or specific revision/sha256) validated assets snapshot on snap_date."""
        stored = self._store().load_snapshot(
            snap_date,
            filters=self._normalize_filters(statuses),
            revision=revision,
            sha256=sha256,
        )
        return _to_asset_snapshot(stored) if stored is not None else None

    def list_snapshots(
        self,
        snap_date: date,
        *,
        statuses: Optional[Sequence[str]] = None,
    ) -> List[AssetSnapshot]:
        """List all immutable asset snapshot revisions committed on snap_date."""
        stored = self._store().list_snapshots(snap_date, filters=self._normalize_filters(statuses))
        return [_to_asset_snapshot(s) for s in stored]

    def fetch_raw_assets(self, *, statuses: Sequence[str] = ("active", "inactive")) -> List[Dict[str, Any]]:
        by_id: Dict[str, Dict[str, Any]] = {}
        for st in statuses:
            resp = self.client.request(
                "trading",
                "/v2/assets",
                params={"asset_class": "us_equity", "status": st},
            )
            rows = resp.body if isinstance(resp.body, list) else (resp.body or {}).get("assets") or []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                key = str(r.get("id") or r.get("symbol") or "").strip()
                if key:
                    by_id[key] = r
        return list(by_id.values())

    def download_snapshot(
        self,
        *,
        snap_date: Optional[date] = None,
        statuses: Sequence[str] = ("active", "inactive"),
        dry_run: bool = False,
        force_refresh: bool = False,
    ) -> AssetSnapshot:
        """Fetch and persist an immutable asset snapshot; force_refresh creates a new revision only on content change."""
        now_utc = datetime.now(UTC_TZ)
        target_date = snap_date or now_utc.astimezone(NY_TZ).date()
        filters = self._normalize_filters(statuses) or dict(_DEFAULT_ASSET_FILTERS)
        norm_statuses = tuple(filters["statuses"])

        if not force_refresh:
            existing = self.load_snapshot(target_date, statuses=norm_statuses)
            if existing is not None:
                return existing

        rows = self.fetch_raw_assets(statuses=norm_statuses)
        stored = self._store().persist(
            snap_date=target_date,
            now_utc=now_utc,
            filters=filters,
            raw_rows=rows,
            pages_fetched=1,
            pagination_complete=True,
            dry_run=dry_run,
            write_gz=self._atomic_write_gz,
            write_json=self._atomic_write_json,
        )
        return _to_asset_snapshot(stored)

    def discover(
        self,
        *,
        snapshot: Optional[AssetSnapshot] = None,
        registry: Optional[InstrumentRegistry] = None,
        dry_run: bool = False,
    ) -> AssetDiscoveryReport:
        snap = snapshot or self.download_snapshot(dry_run=dry_run)
        snap_path = snap.raw_gz_path if (snap.raw_gz_path and os.path.isfile(snap.raw_gz_path)) else None
        man_path = snap.manifest_path if (snap.manifest_path and os.path.isfile(snap.manifest_path)) else None
        report = AssetDiscoveryReport(
            snapshot_date=snap.snapshot_date,
            snapshot_sha256=snap.sha256,
            retrieved_at_utc=snap.retrieved_at_utc,
            snapshot_path=snap_path,
            manifest_path=man_path,
            snapshot_revision=snap.revision,
        )
        now_utc = snap.retrieved_at_utc

        for raw in snap.raw_assets:
            sym = str(raw.get("symbol") or "").strip().upper()
            ex = str(raw.get("exchange") or "UNKNOWN").strip().upper()
            if not sym:
                continue
            is_etf, etf_src, etf_verified = _classify_etf_asset(raw)
            ac = AssetClass.ETF if is_etf else AssetClass.EQUITY
            ct = ContractType.ETF if is_etf else ContractType.EQUITY
            status = _map_status(raw.get("status"))
            is_active = status == InstrumentStatus.ACTIVE
            tradable = bool(raw.get("tradable", False))
            provider_id = str(raw.get("id") or sym)
            ex_mic = _EXCHANGE_MICS.get(ex)
            ex_verified = ex_mic is not None
            cal_name = ex_mic if ex_mic is not None else "UNKNOWN"

            inst = Instrument(
                instrument_id="",
                market=Market.US,
                asset_class=ac,
                segment=Segment.US_EQUITY,
                exchange=ex,
                exchange_mic=ex_mic,
                canonical_symbol=sym,
                trading_symbol=sym,
                display_name=str(raw.get("name") or sym).strip(),
                price_currency="USD",
                contract_type=ct,
                is_tradable=tradable,
                is_active=is_active,
                instrument_status=status,
                trading_calendar=cal_name,
                timezone="America/New_York",
                primary_provider="alpaca",
                provider_instrument_id=provider_id,
                provider_symbol=sym,
                source="alpaca_assets_v2",
                last_verified_at=now_utc,
                metadata={
                    "alpaca_asset_id": provider_id,
                    "alpaca_class": raw.get("class") or raw.get("asset_class") or "us_equity",
                    "in_alpaca_asset_master": True,
                    "tradable": tradable,
                    "data_availability": "UNVERIFIED",
                    "exchange_verified": ex_verified,
                    "etf_classification_source": etf_src,
                    "etf_classification_verified": etf_verified,
                    "marginable": bool(raw.get("marginable", False)),
                    "shortable": bool(raw.get("shortable", False)),
                    "attributes": list(raw.get("attributes") or []),
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
                provider_exchange=ex,
                provider_feed=None,
                last_verified_at=now_utc,
                is_primary=True,
            )
            if is_etf:
                report.etfs.append(inst)
            else:
                report.equities.append(inst)
            report.mappings.append(mapping)

            if registry is not None and not dry_run:
                registry.upsert(inst, mappings=[mapping])

        return report
