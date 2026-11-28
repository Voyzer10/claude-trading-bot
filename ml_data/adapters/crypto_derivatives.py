"""Provider-independent InstrumentAdapter for Crypto Derivatives (CoinDCX primary; Binance deactivated)."""
from __future__ import annotations

from typing import List, Optional, Sequence

from ..instruments import InstrumentRegistry
from ..crypto.coindcx import CoinDCXDiscovery
from ..crypto.config import DEFAULT_CRYPTO_UNIVERSE, PublicCryptoHTTPClient
from .coindcx import CoinDCXFuturesAdapter
from .base import InstrumentAdapter, InstrumentCandidate


class CryptoDerivativesAdapter(CoinDCXFuturesAdapter):
    """Active crypto derivatives adapter backed by CoinDCX perpetual futures."""

    def __init__(
        self,
        *,
        client: Optional[PublicCryptoHTTPClient] = None,
        discovery: Optional[CoinDCXDiscovery] = None,
        registry: Optional[InstrumentRegistry] = None,
        universe: Optional[Sequence[str]] = DEFAULT_CRYPTO_UNIVERSE,
        margin_currencies: Sequence[str] = ("USDT", "INR"),
    ) -> None:
        super().__init__(
            client=client,
            discovery=discovery,
            registry=registry,
            universe=universe,
            margin_currencies=margin_currencies,
        )
