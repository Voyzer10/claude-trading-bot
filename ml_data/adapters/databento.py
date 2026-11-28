"""Provider-independent InstrumentAdapter implementation for Databento US Equity-Index Futures."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..instruments import InstrumentRegistry
from ..futures.client import DatabentoHistoricalClient
from ..futures.contract_discovery import FuturesContractDiscovery
from .base import InstrumentAdapter, InstrumentCandidate


class DatabentoFuturesAdapter(InstrumentAdapter):
    """Read-only Databento adapter for US CME Globex equity-index futures."""

    def __init__(
        self,
        *,
        client: Optional[DatabentoHistoricalClient] = None,
        discovery: Optional[FuturesContractDiscovery] = None,
        registry: Optional[InstrumentRegistry] = None,
        definitions: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> None:
        self.client = client or DatabentoHistoricalClient()
        self.discovery = discovery or FuturesContractDiscovery(client=self.client)
        self.registry = registry
        self._definitions = list(definitions or [])

    def fetch_equities(self) -> List[InstrumentCandidate]:
        return []

    def fetch_options(self, underlying: str) -> List[InstrumentCandidate]:
        return []

    def fetch_futures(self, underlying: str) -> List[InstrumentCandidate]:
        root = underlying.strip().upper()
        rep = self.discovery.discover_from_definitions(
            self._definitions,
            registry=self.registry,
            allowed_roots=(root,),
            dry_run=(self.registry is None),
        )
        by_id: Dict[str, List] = {}
        for m in rep.mappings:
            by_id.setdefault(m.instrument_id, []).append(m)
        return [InstrumentCandidate(instrument=c, mappings=by_id.get(c.instrument_id, [])) for c in rep.contracts]

    def fetch_crypto_spot(self) -> List[InstrumentCandidate]:
        return []

    def fetch_crypto_derivatives(self) -> List[InstrumentCandidate]:
        return []
