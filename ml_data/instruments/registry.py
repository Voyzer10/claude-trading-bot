"""High-level Persistent Instrument Registry API."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .enums import AssetClass, InstrumentStatus, Market, Segment
from .repository import RegistryConflictError, RegistryError, SQLiteInstrumentRepository
from .schemas import Instrument, InstrumentSpecVersion, ProviderInstrumentMapping


class InstrumentRegistry:
    """Provider-independent persistent registry for canonical multi-market instruments."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._repo = SQLiteInstrumentRepository(db_path=db_path)

    def close(self) -> None:
        self._repo.close()

    def schema_version(self) -> int:
        return self._repo.schema_version()

    def register(
        self,
        instrument: Instrument,
        mappings: Optional[List[ProviderInstrumentMapping]] = None,
        *,
        validate_underlying: bool = True,
    ) -> Instrument:
        """Register a new instrument; raises RegistryConflictError if it already exists."""
        return self._repo.upsert_instrument(
            instrument, mappings=mappings, allow_update=False, validate_underlying=validate_underlying
        )

    def upsert(
        self,
        instrument: Instrument,
        mappings: Optional[List[ProviderInstrumentMapping]] = None,
        *,
        validate_underlying: bool = True,
    ) -> Instrument:
        """Idempotently register or update an instrument while preserving spec history."""
        return self._repo.upsert_instrument(
            instrument, mappings=mappings, allow_update=True, validate_underlying=validate_underlying
        )

    def add_provider_mapping(self, mapping: ProviderInstrumentMapping) -> None:
        self._repo.add_mapping(mapping)

    def get(self, instrument_id: str) -> Optional[Instrument]:
        return self._repo.get(instrument_id)

    def get_by_exchange_symbol(self, exchange: str, trading_symbol: str) -> List[Instrument]:
        return self._repo.query("UPPER(exchange) = UPPER(?) AND trading_symbol = ?", (exchange, trading_symbol))

    def list_by_market(self, market: Market) -> List[Instrument]:
        return self._repo.query("market = ?", (Market(market).value,))

    def list_by_asset_class(self, asset_class: AssetClass) -> List[Instrument]:
        return self._repo.query("asset_class = ?", (AssetClass(asset_class).value,))

    def list_by_segment(self, segment: Segment) -> List[Instrument]:
        return self._repo.query("segment = ?", (Segment(segment).value,))

    def list_by_underlying(self, underlying_instrument_id: str) -> List[Instrument]:
        return self._repo.query("underlying_instrument_id = ?", (underlying_instrument_id,))

    def list_by_expiry(self, expiry_date: date) -> List[Instrument]:
        return self._repo.query("expiry_date = ?", (expiry_date.isoformat(),))

    def list_active(self) -> List[Instrument]:
        return self._repo.query("is_active = 1 AND instrument_status = ?", (InstrumentStatus.ACTIVE.value,))

    def list_expired(self) -> List[Instrument]:
        return self._repo.query("instrument_status = ?", (InstrumentStatus.EXPIRED.value,))

    def get_options_for_underlying(self, underlying_instrument_id: str) -> List[Instrument]:
        return self._repo.query(
            "underlying_instrument_id = ? AND asset_class = ?",
            (underlying_instrument_id, AssetClass.OPTION.value),
        )

    def get_futures_for_underlying(self, underlying_instrument_id: str) -> List[Instrument]:
        return self._repo.query(
            "underlying_instrument_id = ? AND asset_class = ?",
            (underlying_instrument_id, AssetClass.FUTURE.value),
        )

    def get_provider_mappings(self, instrument_id: str) -> List[ProviderInstrumentMapping]:
        return self._repo.get_mappings(instrument_id)

    def resolve_provider_symbol(
        self,
        provider: str,
        provider_symbol: str,
        provider_exchange: Optional[str] = None,
        provider_feed: Optional[str] = None,
        as_of: Optional[datetime] = None,
    ) -> Optional[Instrument]:
        return self._repo.resolve_provider(
            provider,
            provider_symbol,
            provider_exchange=provider_exchange,
            provider_feed=provider_feed,
            as_of=as_of,
        )

    def resolve_provider_instrument_id(
        self,
        provider: str,
        provider_instrument_id: str,
        provider_exchange: Optional[str] = None,
        provider_feed: Optional[str] = None,
        as_of: Optional[datetime] = None,
    ) -> Optional[Instrument]:
        return self._repo.resolve_provider_instrument_id(
            provider,
            provider_instrument_id,
            provider_exchange=provider_exchange,
            provider_feed=provider_feed,
            as_of=as_of,
        )

    def close_provider_mappings(
        self,
        provider: str,
        *,
        close_at: datetime,
        provider_exchange: Optional[str] = None,
        provider_instrument_id: Optional[str] = None,
        provider_symbol: Optional[str] = None,
        instrument_id: Optional[str] = None,
        exclude_instrument_id: Optional[str] = None,
    ) -> int:
        return self._repo.close_provider_mappings(
            provider,
            close_at=close_at,
            provider_exchange=provider_exchange,
            provider_instrument_id=provider_instrument_id,
            provider_symbol=provider_symbol,
            instrument_id=instrument_id,
            exclude_instrument_id=exclude_instrument_id,
        )

    def get_spec_history(self, instrument_id: str) -> List[InstrumentSpecVersion]:
        return self._repo.get_spec_history(instrument_id)

    def export_json(self) -> str:
        """Deterministic JSON snapshot of all canonical instruments and provider mappings."""
        instruments = self._repo.query()
        bundle = [
            {
                "instrument": inst.to_dict(),
                "mappings": [m.to_dict() for m in self.get_provider_mappings(inst.instrument_id)],
            }
            for inst in instruments
        ]
        return json.dumps({"schema_version": self.schema_version(), "records": bundle}, sort_keys=True, indent=2)

    def import_json(self, payload: str) -> int:
        doc: Dict[str, Any] = json.loads(payload)
        records = doc.get("records") or []
        # Import underlyings before derivatives so underlying relationship checks succeed
        ordered = sorted(records, key=lambda r: 1 if (r.get("instrument") or {}).get("underlying_instrument_id") else 0)
        for rec in ordered:
            inst = Instrument.from_dict(rec["instrument"])
            maps = [ProviderInstrumentMapping.from_dict(m) for m in (rec.get("mappings") or [])]
            self.upsert(inst, mappings=maps)
        return len(records)


__all__ = ["InstrumentRegistry", "RegistryConflictError", "RegistryError"]
