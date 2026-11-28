"""Provider-independent InstrumentAdapter implementation for Coinbase Crypto Spot."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from ..instruments import InstrumentRegistry
from ..crypto.config import DEFAULT_CRYPTO_UNIVERSE, PublicCryptoHTTPClient
from ..crypto.discovery import CryptoSpotDiscovery
from .base import InstrumentAdapter, InstrumentCandidate


class CoinbaseSpotAdapter(InstrumentAdapter):
    """Read-only Coinbase public spot adapter."""

    def __init__(
        self,
        *,
        client: Optional[PublicCryptoHTTPClient] = None,
        discovery: Optional[CryptoSpotDiscovery] = None,
        registry: Optional[InstrumentRegistry] = None,
        universe: Optional[Sequence[str]] = DEFAULT_CRYPTO_UNIVERSE,
    ) -> None:
        self.client = client or PublicCryptoHTTPClient()
        self.discovery = discovery or CryptoSpotDiscovery(client=self.client)
        self.registry = registry
        self.universe = universe

    def fetch_equities(self) -> List[InstrumentCandidate]:
        return []

    def fetch_options(self, underlying: str) -> List[InstrumentCandidate]:
        return []

    def fetch_futures(self, underlying: str) -> List[InstrumentCandidate]:
        return []

    def fetch_crypto_spot(self) -> List[InstrumentCandidate]:
        rep = self.discovery.discover(registry=self.registry, universe=self.universe, dry_run=(self.registry is None))
        by_id: Dict[str, List] = {}
        for m in rep.mappings:
            by_id.setdefault(m.instrument_id, []).append(m)
        return [InstrumentCandidate(instrument=i, mappings=by_id.get(i.instrument_id, [])) for i in rep.instruments]

    def fetch_crypto_derivatives(self) -> List[InstrumentCandidate]:
        return []
