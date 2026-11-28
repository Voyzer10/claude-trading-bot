"""Strict schema, compatibility matrix, and category-specific validation."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .enums import AssetClass, ContractType, InstrumentStatus, Market, OptionRight, Segment, SettlementType
from .schemas import InstrumentValidationError

if TYPE_CHECKING:
    from .schemas import Instrument, ProviderInstrumentMapping

_DECIMAL_FIELDS = (
    "strike_price",
    "contract_multiplier",
    "lot_size",
    "tick_size",
    "minimum_order_quantity",
    "quantity_step",
    "deliverable_shares",
)

# Explicit Market + Segment -> allowed AssetClasses compatibility matrix
_COMPATIBILITY_MATRIX = {
    (Market.US, Segment.US_EQUITY): {AssetClass.EQUITY, AssetClass.ETF},
    (Market.US, Segment.US_INDEX): {AssetClass.INDEX},
    (Market.US, Segment.US_OPTIONS): {AssetClass.OPTION},
    (Market.US, Segment.US_FUTURES): {AssetClass.FUTURE},
    (Market.IN, Segment.IN_INDEX): {AssetClass.INDEX},
    (Market.IN, Segment.IN_INDEX_FUTURES): {AssetClass.FUTURE},
    (Market.IN, Segment.IN_INDEX_OPTIONS): {AssetClass.OPTION},
    (Market.CRYPTO, Segment.CRYPTO_SPOT): {AssetClass.CRYPTO_SPOT},
    (Market.CRYPTO, Segment.CRYPTO_FUTURES): {AssetClass.CRYPTO_FUTURE},
    (Market.CRYPTO, Segment.CRYPTO_PERPETUALS): {AssetClass.CRYPTO_PERPETUAL},
}

_ASSET_CONTRACT_TYPES = {
    AssetClass.EQUITY: {ContractType.EQUITY, ContractType.UNKNOWN},
    AssetClass.ETF: {ContractType.ETF, ContractType.UNKNOWN},
    AssetClass.INDEX: {ContractType.INDEX, ContractType.UNKNOWN},
    AssetClass.OPTION: {ContractType.OPTION, ContractType.UNKNOWN},
    AssetClass.FUTURE: {ContractType.DATED_FUTURE, ContractType.UNKNOWN},
    AssetClass.CRYPTO_SPOT: {ContractType.SPOT, ContractType.UNKNOWN},
    AssetClass.CRYPTO_FUTURE: {ContractType.DATED_FUTURE, ContractType.UNKNOWN},
    AssetClass.CRYPTO_PERPETUAL: {ContractType.PERPETUAL, ContractType.UNKNOWN},
}

_INDIAN_ALLOWED_EXACT = {"NIFTY", "BANKNIFTY"}


def _require_non_empty(val: Optional[str], name: str) -> str:
    if not isinstance(val, str) or not val.strip():
        raise InstrumentValidationError(f"{name} is required and must be a non-empty string")
    return val.strip()


def _check_bool(val: Any, name: str) -> None:
    if not isinstance(val, bool):
        raise InstrumentValidationError(f"{name} must be a bool (got {type(val).__name__})")


def _check_decimal(val: Any, name: str, *, required: bool = False, positive: bool = True) -> None:
    if val is None:
        if required:
            raise InstrumentValidationError(f"{name} is required")
        return
    if isinstance(val, (float, bool)) or not isinstance(val, Decimal):
        raise InstrumentValidationError(f"{name} must be a Decimal (got {type(val).__name__})")
    if not val.is_finite():
        raise InstrumentValidationError(f"{name} must be a finite Decimal")
    if positive and val <= 0:
        raise InstrumentValidationError(f"{name} must be > 0 (got {val})")
    if not positive and val < 0:
        raise InstrumentValidationError(f"{name} must be >= 0 (got {val})")


def _check_aware_dt(val: Any, name: str) -> None:
    if val is None:
        return
    if not isinstance(val, datetime) or val.tzinfo is None or val.utcoffset() is None:
        raise InstrumentValidationError(f"{name} must be a timezone-aware datetime")


def _check_date(val: Any, name: str) -> None:
    if val is None:
        return
    if isinstance(val, datetime) or not isinstance(val, date):
        raise InstrumentValidationError(f"{name} must be a datetime.date")


def _extract_in_root_symbol(underlying_id: str) -> Optional[str]:
    """Extract exact symbol from an IN:NSE:INDEX:<SYMBOL>#<hash> (or legacy) ID."""
    prefix = underlying_id.strip().upper().split("#")[0]
    parts = prefix.split(":")
    if len(parts) == 4 and parts[0] == "IN" and parts[2] == "INDEX":
        return parts[3]
    return None


def validate_instrument(inst: "Instrument", *, check_id: bool = True) -> None:
    """Validate universal, compatibility matrix, and asset-class-specific invariants."""
    if check_id:
        _require_non_empty(inst.instrument_id, "instrument_id")
    _require_non_empty(inst.schema_version, "schema_version")
    _require_non_empty(inst.identity_version, "identity_version")
    _require_non_empty(inst.exchange, "exchange")
    _require_non_empty(inst.canonical_symbol, "canonical_symbol")
    _require_non_empty(inst.trading_symbol, "trading_symbol")
    _require_non_empty(inst.display_name, "display_name")
    pc = _require_non_empty(inst.price_currency, "price_currency")
    if not (2 <= len(pc) <= 10 and pc.isalpha() and pc.isupper()):
        raise InstrumentValidationError(f"price_currency must be an uppercase currency code (got {pc!r})")
    tz = _require_non_empty(inst.timezone, "timezone")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InstrumentValidationError(f"Unknown or non-IANA timezone: {tz!r}") from exc

    _check_bool(inst.is_inverse, "is_inverse")
    _check_bool(inst.is_tradable, "is_tradable")
    _check_bool(inst.is_active, "is_active")

    if not isinstance(inst.market, Market):
        raise InstrumentValidationError(f"Invalid market: {inst.market!r}")
    if not isinstance(inst.asset_class, AssetClass):
        raise InstrumentValidationError(f"Invalid asset_class: {inst.asset_class!r}")
    if not isinstance(inst.segment, Segment):
        raise InstrumentValidationError(f"Invalid segment: {inst.segment!r}")

    allowed_ac = _COMPATIBILITY_MATRIX.get((inst.market, inst.segment))
    if not allowed_ac or inst.asset_class not in allowed_ac:
        raise InstrumentValidationError(
            f"Incompatible (market={inst.market.value}, segment={inst.segment.value}, "
            f"asset_class={inst.asset_class.value})"
        )

    if inst.contract_type not in _ASSET_CONTRACT_TYPES[inst.asset_class]:
        raise InstrumentValidationError(
            f"contract_type {inst.contract_type.value} is invalid for {inst.asset_class.value}"
        )

    for f in _DECIMAL_FIELDS:
        _check_decimal(getattr(inst, f), f, required=False, positive=True)
    for f in ("expiry_date", "last_trade_date", "listing_date", "delisting_date"):
        _check_date(getattr(inst, f), f)
    for f in ("effective_from", "last_verified_at", "created_at", "updated_at"):
        _check_aware_dt(getattr(inst, f), f)

    if inst.listing_date and inst.delisting_date and inst.delisting_date < inst.listing_date:
        raise InstrumentValidationError("delisting_date cannot precede listing_date")
    if inst.last_trade_date and inst.expiry_date and inst.last_trade_date > inst.expiry_date:
        raise InstrumentValidationError("last_trade_date cannot be after expiry_date")

    # Indian market scope: strictly NIFTY and BANKNIFTY indices, futures, and options
    if inst.market == Market.IN:
        if inst.asset_class == AssetClass.INDEX:
            if inst.canonical_symbol.strip().upper() not in _INDIAN_ALLOWED_EXACT:
                raise InstrumentValidationError(
                    f"Indian index scope allows only NIFTY or BANKNIFTY (got {inst.canonical_symbol!r})"
                )
        else:
            und = _require_non_empty(inst.underlying_instrument_id, "underlying_instrument_id")
            root_sym = _extract_in_root_symbol(und)
            if root_sym not in _INDIAN_ALLOWED_EXACT:
                raise InstrumentValidationError(
                    f"Indian derivatives scope allows only exact NIFTY/BANKNIFTY index underlyings (got {und!r})"
                )

    ac = inst.asset_class
    if ac in (AssetClass.EQUITY, AssetClass.ETF):
        if inst.expiry_date is not None or inst.strike_price is not None or inst.option_right is not None:
            raise InstrumentValidationError(f"{ac.value} must not define expiry_date, strike_price, or option_right")

    elif ac == AssetClass.INDEX:
        if inst.is_tradable:
            raise InstrumentValidationError("INDEX instruments must have is_tradable=False")
        if inst.expiry_date is not None or inst.strike_price is not None or inst.option_right is not None:
            raise InstrumentValidationError("INDEX must not define expiry_date, strike_price, or option_right")

    elif ac == AssetClass.OPTION:
        _require_non_empty(inst.underlying_instrument_id, "underlying_instrument_id")
        if inst.expiry_date is None:
            raise InstrumentValidationError("OPTION requires expiry_date")
        _check_decimal(inst.strike_price, "strike_price", required=True, positive=True)
        if not isinstance(inst.option_right, OptionRight):
            raise InstrumentValidationError("OPTION requires option_right (CALL or PUT)")
        _check_decimal(inst.contract_multiplier, "contract_multiplier", required=True, positive=True)

    elif ac == AssetClass.FUTURE:
        _require_non_empty(inst.underlying_instrument_id, "underlying_instrument_id")
        if inst.expiry_date is None:
            raise InstrumentValidationError("FUTURE requires expiry_date")
        _check_decimal(inst.contract_multiplier, "contract_multiplier", required=True, positive=True)
        _check_decimal(inst.tick_size, "tick_size", required=True, positive=True)
        if inst.settlement_type == SettlementType.UNKNOWN:
            raise InstrumentValidationError("FUTURE requires explicit settlement_type")

    elif ac == AssetClass.CRYPTO_SPOT:
        _require_non_empty(inst.base_currency, "base_currency")
        _require_non_empty(inst.quote_currency, "quote_currency")
        _check_decimal(inst.quantity_step, "quantity_step", required=True, positive=True)
        if inst.expiry_date is not None:
            raise InstrumentValidationError("CRYPTO_SPOT must not have expiry_date")

    elif ac in (AssetClass.CRYPTO_FUTURE, AssetClass.CRYPTO_PERPETUAL):
        _require_non_empty(inst.base_currency, "base_currency")
        _require_non_empty(inst.quote_currency, "quote_currency")
        _require_non_empty(inst.settlement_currency, "settlement_currency")
        _check_decimal(inst.quantity_step, "quantity_step", required=True, positive=True)
        _check_decimal(inst.tick_size, "tick_size", required=True, positive=True)
        _check_decimal(inst.contract_multiplier, "contract_multiplier", required=True, positive=True)
        if ac == AssetClass.CRYPTO_FUTURE and inst.expiry_date is None:
            raise InstrumentValidationError("CRYPTO_FUTURE requires expiry_date")
        if ac == AssetClass.CRYPTO_PERPETUAL and inst.expiry_date is not None:
            raise InstrumentValidationError("CRYPTO_PERPETUAL must not have expiry_date")

    if inst.instrument_status == InstrumentStatus.EXPIRED and inst.is_active:
        raise InstrumentValidationError("EXPIRED instrument cannot have is_active=True")


def validate_provider_mapping(mapping: "ProviderInstrumentMapping") -> None:
    """Validate external provider mapping invariants."""
    _require_non_empty(mapping.mapping_id, "mapping_id")
    _require_non_empty(mapping.instrument_id, "instrument_id")
    _require_non_empty(mapping.provider, "provider")
    _require_non_empty(mapping.provider_symbol, "provider_symbol")
    _check_bool(mapping.is_primary, "is_primary")
    for f in ("valid_from", "valid_until", "last_verified_at"):
        _check_aware_dt(getattr(mapping, f), f)
    if mapping.valid_from and mapping.valid_until and mapping.valid_until <= mapping.valid_from:
        raise InstrumentValidationError("valid_until must be strictly after valid_from")
