"""Dynamic US equity and ETF discovery, immutable daily snapshots, and Identity v3 mapping."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

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

    def _paths(self, snap_date: date) -> Tuple[str, str]:
        sdir = os.path.join(self.raw_root, f"date={snap_date.isoformat()}")
        mdir = os.path.join(self.manifest_root, f"date={snap_date.isoformat()}")
        return os.path.join(sdir, "assets.json.gz"), os.path.join(mdir, "assets_manifest.json")

    def _atomic_write_gz(self, path: str, text: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise

    def _atomic_write_json(self, path: str, payload: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
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
        now_utc = datetime.now(UTC_TZ)
        target_date = snap_date or now_utc.astimezone(NY_TZ).date()
        gz_path, man_path = self._paths(target_date)

        if not force_refresh and os.path.isfile(gz_path) and os.path.isfile(man_path):
            with open(man_path, encoding="utf-8") as fh:
                man = json.load(fh)
            with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
                raw_text = fh.read()
            sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            if sha == man.get("sha256"):
                rows = json.loads(raw_text)
                return AssetSnapshot(
                    snapshot_date=target_date,
                    retrieved_at_utc=datetime.fromisoformat(man["retrieved_at_utc"]),
                    sha256=sha,
                    raw_count=len(rows),
                    raw_gz_path=gz_path,
                    manifest_path=man_path,
                    raw_assets=tuple(rows),
                )

        rows = self.fetch_raw_assets(statuses=statuses)
        raw_text = json.dumps(rows, sort_keys=True)
        sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        if not dry_run:
            self._atomic_write_gz(gz_path, raw_text)
            self._atomic_write_json(
                man_path,
                {
                    "snapshot_date": target_date.isoformat(),
                    "retrieved_at_utc": now_utc.isoformat(),
                    "sha256": sha,
                    "raw_count": len(rows),
                },
            )
        return AssetSnapshot(
            snapshot_date=target_date,
            retrieved_at_utc=now_utc,
            sha256=sha,
            raw_count=len(rows),
            raw_gz_path=gz_path,
            manifest_path=man_path,
            raw_assets=tuple(rows),
        )

    def discover(
        self,
        *,
        snapshot: Optional[AssetSnapshot] = None,
        registry: Optional[InstrumentRegistry] = None,
        dry_run: bool = False,
    ) -> AssetDiscoveryReport:
        snap = snapshot or self.download_snapshot(dry_run=dry_run)
        report = AssetDiscoveryReport(snapshot_date=snap.snapshot_date, snapshot_sha256=snap.sha256)
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
