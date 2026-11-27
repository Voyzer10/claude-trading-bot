"""Provider-independent InstrumentAdapter implementation for Alpaca (US Equities, ETFs, Indices, Options)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from ..instruments import InstrumentRegistry
from ..us.assets import AlpacaAssetsDiscovery, AssetDiscoveryReport
from ..us.client import AlpacaDataClient
from ..us.config import NY_TZ, UTC_TZ
from ..us.contracts import AlpacaOptionsContractDiscovery
from ..us.indices import AlpacaIndexDiscovery
from .base import InstrumentAdapter, InstrumentCandidate


class AlpacaUSAdapter(InstrumentAdapter):
    """Read-only Alpaca adapter for US equities, ETFs, indices, and equity/ETF/index options."""

    def __init__(
        self,
        *,
        client: Optional[AlpacaDataClient] = None,
        assets_discovery: Optional[AlpacaAssetsDiscovery] = None,
        index_discovery: Optional[AlpacaIndexDiscovery] = None,
        options_discovery: Optional[AlpacaOptionsContractDiscovery] = None,
        registry: Optional[InstrumentRegistry] = None,
        dry_run: bool = False,
    ) -> None:
        self.client = client or AlpacaDataClient()
        self.assets_discovery = assets_discovery or AlpacaAssetsDiscovery(client=self.client)
        self.index_discovery = index_discovery or AlpacaIndexDiscovery(client=self.client)
        self.options_discovery = options_discovery or AlpacaOptionsContractDiscovery(client=self.client)
        self.registry = registry
        self.dry_run = bool(dry_run)
        self._cached_assets: Optional[AssetDiscoveryReport] = None
        self._assets_cache_key: Optional[Tuple[date, str]] = None

    def _to_candidates(self, instruments, mappings) -> List[InstrumentCandidate]:
        by_id: Dict[str, List] = {}
        for m in mappings:
            by_id.setdefault(m.instrument_id, []).append(m)
        return [InstrumentCandidate(instrument=inst, mappings=by_id.get(inst.instrument_id, [])) for inst in instruments]

    def _get_assets_report(self, *, snap_date: Optional[date] = None, refresh: bool = False) -> AssetDiscoveryReport:
        target_date = snap_date or datetime.now(UTC_TZ).astimezone(NY_TZ).date()
        if (
            self._cached_assets is not None
            and not refresh
            and self._assets_cache_key is not None
            and self._assets_cache_key[0] == target_date
        ):
            return self._cached_assets
        snap = self.assets_discovery.download_snapshot(snap_date=target_date, dry_run=self.dry_run, force_refresh=refresh)
        rep = self.assets_discovery.discover(snapshot=snap, registry=self.registry, dry_run=self.dry_run)
        self._cached_assets = rep
        self._assets_cache_key = (target_date, rep.snapshot_sha256)
        return rep

    def fetch_equities(self) -> List[InstrumentCandidate]:
        rep = self._get_assets_report()
        return self._to_candidates(rep.equities + rep.etfs, rep.mappings)

    def fetch_indices(self) -> List[InstrumentCandidate]:
        rep = self.index_discovery.discover_indices(registry=self.registry, dry_run=(self.registry is None))
        return self._to_candidates(rep.indices, rep.mappings)

    def fetch_options(self, underlying: str) -> List[InstrumentCandidate]:
        if self.registry is None:
            # Populate in-memory temp registry? Require explicit registry or build ephemeral one for discovery
            reg = InstrumentRegistry(":memory:")
            try:
                self.assets_discovery.discover(
                    snapshot=self.assets_discovery.download_snapshot(dry_run=True),
                    registry=reg,
                    dry_run=False,
                )
                self.index_discovery.discover_indices(registry=reg, dry_run=False)
                rep = self.options_discovery.discover_and_map(
                    registry=reg, underlying_symbols=[underlying.strip().upper()], dry_run=False
                )
                return self._to_candidates(rep.contracts, rep.mappings)
            finally:
                reg.close()
        rep = self.options_discovery.discover_and_map(
            registry=self.registry, underlying_symbols=[underlying.strip().upper()], dry_run=False
        )
        return self._to_candidates(rep.contracts, rep.mappings)

    def fetch_futures(self, underlying: str) -> List[InstrumentCandidate]:
        # US futures are outside Milestone 3 scope.
        return []

    def fetch_crypto_spot(self) -> List[InstrumentCandidate]:
        return []

    def fetch_crypto_derivatives(self) -> List[InstrumentCandidate]:
        return []
