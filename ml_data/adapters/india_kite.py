"""Provider-independent InstrumentAdapter implementation for Zerodha Kite (India NIFTY/BANKNIFTY)."""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional, Tuple

from ..india.config import IST_TZ, KiteClientWrapper
from ..india.contract_discovery import ContractDiscovery, DiscoveryReport
from ..india.instrument_master import InstrumentMasterDownloader
from .base import InstrumentAdapter, InstrumentCandidate


class IndiaKiteAdapter(InstrumentAdapter):
    """Zerodha Kite Connect adapter scoped strictly to NIFTY & BANKNIFTY indices, futures, and options."""

    def __init__(
        self,
        *,
        client: Optional[KiteClientWrapper] = None,
        downloader: Optional[InstrumentMasterDownloader] = None,
        discovery: Optional[ContractDiscovery] = None,
    ) -> None:
        self.client = client or KiteClientWrapper()
        self.downloader = downloader or InstrumentMasterDownloader(client=self.client)
        self.discovery = discovery or ContractDiscovery()
        self._cached_report: Optional[DiscoveryReport] = None
        self._cache_key: Optional[Tuple[date, str, str]] = None

    def discover(
        self,
        *,
        snap_date: Optional[date] = None,
        dry_run: bool = True,
        refresh: bool = False,
    ) -> DiscoveryReport:
        target_date = snap_date or datetime.now(IST_TZ).date()
        if (
            self._cached_report is not None
            and not refresh
            and self._cache_key is not None
            and self._cache_key[0] == target_date
        ):
            return self._cached_report

        nse_snap = self.downloader.download_snapshot(
            "NSE", snap_date=target_date, dry_run=dry_run, force_refresh=refresh
        )
        nfo_snap = self.downloader.download_snapshot(
            "NFO", snap_date=target_date, dry_run=dry_run, force_refresh=refresh
        )
        key = (target_date, nse_snap.sha256, nfo_snap.sha256)
        if self._cached_report is not None and not refresh and self._cache_key == key:
            return self._cached_report

        self._cached_report = self.discovery.discover_from_snapshots(
            nse_snapshot=nse_snap, nfo_snapshot=nfo_snap, registry=None, dry_run=True
        )
        self._cache_key = key
        return self._cached_report

    def _to_candidates(self, instruments, mappings) -> List[InstrumentCandidate]:
        by_id = {}
        for m in mappings:
            by_id.setdefault(m.instrument_id, []).append(m)
        return [InstrumentCandidate(instrument=inst, mappings=by_id.get(inst.instrument_id, [])) for inst in instruments]

    def fetch_equities(self) -> List[InstrumentCandidate]:
        # Indian individual equities are outside Milestone 2 scope; return empty list.
        return []

    def fetch_indices(self) -> List[InstrumentCandidate]:
        rep = self.discover()
        return self._to_candidates(rep.indices, rep.mappings)

    def fetch_options(self, underlying: str) -> List[InstrumentCandidate]:
        root = underlying.strip().upper()
        if root not in ("NIFTY", "BANKNIFTY"):
            return []
        rep = self.discover()
        opts = [o for o in rep.options if o.canonical_symbol.startswith(root)]
        return self._to_candidates(opts, rep.mappings)

    def fetch_futures(self, underlying: str) -> List[InstrumentCandidate]:
        root = underlying.strip().upper()
        if root not in ("NIFTY", "BANKNIFTY"):
            return []
        rep = self.discover()
        futs = [f for f in rep.futures if f.canonical_symbol.startswith(root)]
        return self._to_candidates(futs, rep.mappings)

    def fetch_crypto_spot(self) -> List[InstrumentCandidate]:
        return []

    def fetch_crypto_derivatives(self) -> List[InstrumentCandidate]:
        return []
