"""Provider-independent abstract interface for future instrument discovery adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List

from ..instruments.schemas import Instrument, ProviderInstrumentMapping


@dataclass(frozen=True)
class InstrumentCandidate:
    """Normalized instrument candidate returned by an InstrumentAdapter."""

    instrument: Instrument
    mappings: List[ProviderInstrumentMapping] = field(default_factory=list)


class InstrumentAdapter(ABC):
    """Abstract provider-independent instrument discovery interface.

    Concrete provider adapters (Alpaca, Zerodha Kite, US Futures, Crypto exchanges)
    will implement these methods without leaking raw provider payloads.
    """

    @abstractmethod
    def fetch_equities(self) -> List[InstrumentCandidate]:
        """Return normalized equity and ETF candidates."""

    @abstractmethod
    def fetch_options(self, underlying: str) -> List[InstrumentCandidate]:
        """Return normalized option contract candidates for an underlying."""

    @abstractmethod
    def fetch_futures(self, underlying: str) -> List[InstrumentCandidate]:
        """Return normalized futures contract candidates for an underlying."""

    @abstractmethod
    def fetch_crypto_spot(self) -> List[InstrumentCandidate]:
        """Return normalized crypto spot pair candidates."""

    @abstractmethod
    def fetch_crypto_derivatives(self) -> List[InstrumentCandidate]:
        """Return normalized crypto dated futures and perpetual swap candidates."""
