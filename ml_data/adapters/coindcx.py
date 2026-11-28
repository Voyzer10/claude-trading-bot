"""Provider-independent CoinDCX Spot and Perpetual Futures adapters."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from ..instruments import InstrumentRegistry
from ..crypto.coindcx import CoinDCXDiscovery
from ..crypto.config import DEFAULT_CRYPTO_UNIVERSE, PublicCryptoHTTPClient
from .base import InstrumentAdapter, InstrumentCandidate


class CoinDCXSpotAdapter(InstrumentAdapter):
    """Read-only CoinDCX spot adapter."""

    def __init__(
        self,
        *,
        client: Optional[PublicCryptoHTTPClient] = None,
        discovery: Optional[CoinDCXDiscovery] = None,
        registry: Optional[InstrumentRegistry] = None,
        universe: Optional[Sequence[str]] = DEFAULT_CRYPTO_UNIVERSE,
    ) -> None:
        self.client = client or PublicCryptoHTTPClient()
        self.discovery = discovery or CoinDCXDiscovery(client=self.client)
        self.registry = registry
        self.universe = universe

    def fetch_equities(self) -> List[InstrumentCandidate]:
        return []

    def fetch_options(self, underlying: str) -> List[InstrumentCandidate]:
        return []

    def fetch_futures(self, underlying: str) -> List[InstrumentCandidate]:
        return []

    def fetch_crypto_spot(self) -> List[InstrumentCandidate]:
        rep = self.discovery.discover_spot(registry=self.registry, universe=self.universe, dry_run=(self.registry is None))
        by_id: Dict[str, List] = {}
        for m in rep.mappings:
            by_id.setdefault(m.instrument_id, []).append(m)
        return [InstrumentCandidate(instrument=i, mappings=by_id.get(i.instrument_id, [])) for i in rep.spot_instruments]

    def fetch_crypto_derivatives(self) -> List[InstrumentCandidate]:
        return []


class CoinDCXFuturesAdapter(InstrumentAdapter):
    """Read-only CoinDCX perpetual futures adapter."""

    def __init__(
        self,
        *,
        client: Optional[PublicCryptoHTTPClient] = None,
        discovery: Optional[CoinDCXDiscovery] = None,
        registry: Optional[InstrumentRegistry] = None,
        universe: Optional[Sequence[str]] = DEFAULT_CRYPTO_UNIVERSE,
        margin_currencies: Sequence[str] = ("USDT", "INR"),
    ) -> None:
        self.client = client or PublicCryptoHTTPClient()
        self.discovery = discovery or CoinDCXDiscovery(client=self.client)
        self.registry = registry
        self.universe = universe
        self.margin_currencies = tuple(margin_currencies)

    def fetch_equities(self) -> List[InstrumentCandidate]:
        return []

    def fetch_options(self, underlying: str) -> List[InstrumentCandidate]:
        return []

    def fetch_futures(self, underlying: str) -> List[InstrumentCandidate]:
        return []

    def fetch_crypto_spot(self) -> List[InstrumentCandidate]:
        return []

    def fetch_crypto_derivatives(self) -> List[InstrumentCandidate]:
        rep = self.discovery.discover_futures(
            margin_currencies=self.margin_currencies,
            registry=self.registry,
            universe=self.universe,
            dry_run=(self.registry is None),
        )
        by_id: Dict[str, List] = {}
        for m in rep.mappings:
            by_id.setdefault(m.instrument_id, []).append(m)
        all_derivs = rep.perpetual_instruments + rep.dated_futures_instruments
        return [InstrumentCandidate(instrument=i, mappings=by_id.get(i.instrument_id, [])) for i in all_derivs]
