"""Canonical Universal Instrument, Provider Mapping, and Spec Version schemas."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional

from .enums import (
    AssetClass,
    ContractType,
    InstrumentStatus,
    MarginType,
    Market,
    OptionRight,
    Segment,
    SettlementType,
)
from .identity import (
    IDENTITY_VERSION,
    build_instrument_id,
    build_mapping_id,
    normalize_decimal_str,
    normalize_option_right,
)

SCHEMA_VERSION = "1.0.0"


class InstrumentValidationError(ValueError):
    """Raised when an instrument or provider mapping violates schema rules."""


def _parse_decimal(val: Any, field_name: str) -> Optional[Decimal]:
    if val is None:
        return None
    if isinstance(val, bool) or isinstance(val, float):
        raise InstrumentValidationError(
            f"{field_name} must be Decimal or exact str/int, not {type(val).__name__}"
        )
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception as e:
        raise InstrumentValidationError(f"Invalid Decimal for {field_name}: {val!r}") from e


def _parse_date(val: Any, field_name: str) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        raise InstrumentValidationError(f"{field_name} must be a date, not datetime")
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val))
    except Exception as e:
        raise InstrumentValidationError(f"Invalid ISO date for {field_name}: {val!r}") from e


def _parse_dt(val: Any, field_name: str) -> Optional[datetime]:
    if val is None:
        return None
    if not isinstance(val, datetime):
        try:
            val = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        except Exception as e:
            raise InstrumentValidationError(f"Invalid ISO datetime for {field_name}: {val!r}") from e
    if val.tzinfo is None or val.utcoffset() is None:
        raise InstrumentValidationError(f"{field_name} must be timezone-aware")
    return val.astimezone(timezone.utc)


def _normalize_utc_dt(val: Any, field_name: str) -> Optional[datetime]:
    if val is None:
        return None
    if not isinstance(val, datetime) or val.tzinfo is None or val.utcoffset() is None:
        raise InstrumentValidationError(f"{field_name} must be a timezone-aware datetime")
    return val.astimezone(timezone.utc)


def _ser_val(val: Any) -> Any:
    if isinstance(val, Decimal):
        return normalize_decimal_str(val)
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc).isoformat()
    if isinstance(val, date):
        return val.isoformat()
    if hasattr(val, "value"):
        return val.value
    if isinstance(val, Mapping):
        return dict(val)
    return val


@dataclass(frozen=True)
class Instrument:
    """Provider-independent canonical instrument specification."""

    # Core identity
    instrument_id: str
    market: Market
    asset_class: AssetClass
    segment: Segment
    exchange: str
    canonical_symbol: str
    trading_symbol: str
    display_name: str
    price_currency: str
    schema_version: str = SCHEMA_VERSION
    identity_version: str = IDENTITY_VERSION
    exchange_mic: Optional[str] = None
    clearing_exchange: Optional[str] = None
    venue: Optional[str] = None
    underlying_instrument_id: Optional[str] = None

    # Currency & pricing
    base_currency: Optional[str] = None
    quote_currency: Optional[str] = None
    settlement_currency: Optional[str] = None

    # Contract specifications (Decimal only, never float)
    expiry_date: Optional[date] = None
    last_trade_date: Optional[date] = None
    strike_price: Optional[Decimal] = None
    option_right: Optional[OptionRight] = None
    contract_multiplier: Optional[Decimal] = None
    lot_size: Optional[Decimal] = None
    tick_size: Optional[Decimal] = None
    minimum_order_quantity: Optional[Decimal] = None
    quantity_step: Optional[Decimal] = None
    deliverable_shares: Optional[Decimal] = None
    deliverable_type: Optional[str] = None
    exercise_style: Optional[str] = None
    contract_type: ContractType = ContractType.UNKNOWN
    settlement_type: SettlementType = SettlementType.UNKNOWN
    margin_type: MarginType = MarginType.UNKNOWN
    is_inverse: bool = False

    # Trading properties
    is_tradable: bool = True
    is_active: bool = True
    trading_calendar: Optional[str] = None
    timezone: str = "UTC"
    listing_date: Optional[date] = None
    delisting_date: Optional[date] = None
    instrument_status: InstrumentStatus = InstrumentStatus.ACTIVE

    # Provenance & effective timestamps
    primary_provider: str = "unknown"
    provider_instrument_id: Optional[str] = None
    provider_symbol: Optional[str] = None
    provider_feed: Optional[str] = None
    source: str = "canonical"
    effective_from: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from .validation import validate_instrument

        now = datetime.now(timezone.utc)
        object.__setattr__(self, "created_at", _normalize_utc_dt(self.created_at, "created_at") or now)
        object.__setattr__(self, "updated_at", _normalize_utc_dt(self.updated_at, "updated_at") or self.created_at)
        object.__setattr__(self, "last_verified_at", _normalize_utc_dt(self.last_verified_at, "last_verified_at"))
        object.__setattr__(self, "effective_from", _normalize_utc_dt(self.effective_from, "effective_from"))
        if self.option_right is not None and not isinstance(self.option_right, OptionRight):
            object.__setattr__(self, "option_right", normalize_option_right(self.option_right))

        # Validate identity_version matches current supported algorithm
        if self.identity_version != IDENTITY_VERSION:
            raise InstrumentValidationError(
                f"Unsupported identity_version {self.identity_version!r} (expected {IDENTITY_VERSION!r})"
            )

        # Normalize provider/exchange identifiers consistently
        object.__setattr__(self, "exchange", self.exchange.strip().upper())
        if self.clearing_exchange:
            object.__setattr__(self, "clearing_exchange", self.clearing_exchange.strip().upper())
        object.__setattr__(self, "primary_provider", self.primary_provider.strip().lower())
        if self.provider_feed:
            object.__setattr__(self, "provider_feed", self.provider_feed.strip().lower())

        # Freeze metadata to prevent external mutation
        if not isinstance(self.metadata, Mapping):
            raise InstrumentValidationError("metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

        # Validate enums & fields before computing/checking canonical ID
        validate_instrument(self, check_id=False)

        expected_id = build_instrument_id(
            market=self.market,
            asset_class=self.asset_class,
            exchange=self.exchange,
            canonical_symbol=self.canonical_symbol,
            clearing_exchange=self.clearing_exchange,
            underlying_instrument_id=self.underlying_instrument_id,
            expiry_date=self.expiry_date,
            strike_price=self.strike_price,
            option_right=self.option_right,
            contract_type=self.contract_type,
            contract_multiplier=self.contract_multiplier,
            deliverable_shares=self.deliverable_shares,
            deliverable_type=self.deliverable_type,
            base_currency=self.base_currency,
            quote_currency=self.quote_currency,
            settlement_currency=self.settlement_currency,
            is_inverse=self.is_inverse,
        )
        if not self.instrument_id:
            object.__setattr__(self, "instrument_id", expected_id)
        elif self.instrument_id != expected_id:
            raise InstrumentValidationError(
                f"Supplied instrument_id {self.instrument_id!r} does not match canonical ID {expected_id!r}"
            )

    def spec_dict(self) -> Dict[str, Any]:
        """Contract specification snapshot used for historical version tracking."""
        keys = (
            "asset_class",
            "segment",
            "exchange",
            "exchange_mic",
            "clearing_exchange",
            "venue",
            "underlying_instrument_id",
            "base_currency",
            "quote_currency",
            "settlement_currency",
            "price_currency",
            "expiry_date",
            "last_trade_date",
            "strike_price",
            "option_right",
            "contract_multiplier",
            "lot_size",
            "tick_size",
            "minimum_order_quantity",
            "quantity_step",
            "deliverable_shares",
            "deliverable_type",
            "exercise_style",
            "contract_type",
            "settlement_type",
            "margin_type",
            "is_inverse",
            "trading_calendar",
            "timezone",
        )
        return {k: _ser_val(getattr(self, k)) for k in keys}

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k in self.__dataclass_fields__:
            v = getattr(self, k)
            out[k] = dict(v) if k == "metadata" else _ser_val(v)
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Instrument":
        d = dict(data)
        d["market"] = Market(d["market"])
        d["asset_class"] = AssetClass(d["asset_class"])
        d["segment"] = Segment(d["segment"])
        if d.get("option_right") is not None:
            d["option_right"] = normalize_option_right(d["option_right"])
        d["contract_type"] = ContractType(d.get("contract_type", ContractType.UNKNOWN))
        d["settlement_type"] = SettlementType(d.get("settlement_type", SettlementType.UNKNOWN))
        d["margin_type"] = MarginType(d.get("margin_type", MarginType.UNKNOWN))
        d["instrument_status"] = InstrumentStatus(d.get("instrument_status", InstrumentStatus.ACTIVE))

        for dec_f in (
            "strike_price",
            "contract_multiplier",
            "lot_size",
            "tick_size",
            "minimum_order_quantity",
            "quantity_step",
            "deliverable_shares",
        ):
            d[dec_f] = _parse_decimal(d.get(dec_f), dec_f)

        for dt_f in ("expiry_date", "last_trade_date", "listing_date", "delisting_date"):
            d[dt_f] = _parse_date(d.get(dt_f), dt_f)

        for ts_f in ("effective_from", "last_verified_at", "created_at", "updated_at"):
            d[ts_f] = _parse_dt(d.get(ts_f), ts_f)

        d["metadata"] = dict(d.get("metadata") or {})
        return cls(**d)

    @classmethod
    def from_json(cls, payload: str) -> "Instrument":
        return cls.from_dict(json.loads(payload))


@dataclass(frozen=True)
class ProviderInstrumentMapping:
    """External provider identifier mapping for a canonical instrument."""

    instrument_id: str
    provider: str
    provider_symbol: str
    mapping_id: str = ""
    provider_instrument_id: Optional[str] = None
    provider_exchange: Optional[str] = None
    provider_feed: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None
    is_primary: bool = False

    def __post_init__(self) -> None:
        from .validation import validate_provider_mapping

        object.__setattr__(self, "provider", self.provider.strip().lower())
        if self.provider_exchange is not None:
            ex_norm = self.provider_exchange.strip().upper()
            object.__setattr__(self, "provider_exchange", ex_norm or None)
        if self.provider_feed is not None:
            feed_norm = self.provider_feed.strip().lower()
            object.__setattr__(self, "provider_feed", feed_norm or None)
        object.__setattr__(self, "valid_from", _normalize_utc_dt(self.valid_from, "valid_from"))
        object.__setattr__(self, "valid_until", _normalize_utc_dt(self.valid_until, "valid_until"))
        object.__setattr__(self, "last_verified_at", _normalize_utc_dt(self.last_verified_at, "last_verified_at"))

        if not self.mapping_id:
            mid = build_mapping_id(
                self.instrument_id,
                self.provider,
                self.provider_exchange,
                self.provider_symbol,
                self.provider_instrument_id,
                self.valid_from.isoformat() if self.valid_from else None,
                self.provider_feed,
            )
            object.__setattr__(self, "mapping_id", mid)
        validate_provider_mapping(self)

    def to_dict(self) -> Dict[str, Any]:
        return {k: _ser_val(v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProviderInstrumentMapping":
        d = dict(data)
        for ts_f in ("valid_from", "valid_until", "last_verified_at"):
            d[ts_f] = _parse_dt(d.get(ts_f), ts_f)
        return cls(**d)


@dataclass(frozen=True)
class InstrumentSpecVersion:
    """Historical contract specification version preserved on specification changes."""

    version_id: int
    instrument_id: str
    effective_from: Optional[datetime]
    effective_to: Optional[datetime]
    spec_hash: str
    specification: Dict[str, Any]
    recorded_at: datetime
