"""Deterministic canonical identity generation (v3) for multi-market instruments."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from .enums import AssetClass, ContractType, Market, OptionRight

IDENTITY_VERSION = "v3"


def _clean_token(val: str) -> str:
    return val.strip().upper().replace(" ", "_")


def normalize_decimal_str(val: Decimal) -> str:
    """Format a Decimal canonically without context rounding, scientific notation, or trailing fractional zeros."""
    if not isinstance(val, Decimal):
        raise TypeError("Expected Decimal, got %s" % type(val).__name__)
    if not val.is_finite():
        raise ValueError(f"Decimal must be finite, got {val!r}")
    tup = val.as_tuple()
    digits = "".join(str(d) for d in tup.digits)
    if not digits or set(digits) == {"0"}:
        return "0"
    exp = int(tup.exponent)
    if exp >= 0:
        int_part = (digits + ("0" * exp)).lstrip("0") or "0"
        frac_part = ""
    else:
        pos = len(digits) + exp
        if pos <= 0:
            int_part = "0"
            frac_part = ("0" * (-pos)) + digits
        else:
            int_part = digits[:pos].lstrip("0") or "0"
            frac_part = digits[pos:]
        frac_part = frac_part.rstrip("0")
    sign = "-" if tup.sign else ""
    return f"{sign}{int_part}.{frac_part}" if frac_part else f"{sign}{int_part}"


def normalize_option_right(right: Any) -> OptionRight:
    """Normalize CALL/PUT and Indian CE/PE aliases into OptionRight."""
    if isinstance(right, OptionRight):
        return right
    s = str(right or "").strip().upper()
    if s in ("CALL", "C", "CE"):
        return OptionRight.CALL
    if s in ("PUT", "P", "PE"):
        return OptionRight.PUT
    raise ValueError("Unsupported option_right %r (expected CALL/PUT or CE/PE)" % (right,))


def _canonical_crypto_pair(canonical_symbol: str, base_currency: Optional[str], quote_currency: Optional[str]) -> str:
    if base_currency and quote_currency:
        return f"{_clean_token(base_currency)}/{_clean_token(quote_currency)}"
    return _clean_token(canonical_symbol)


def build_instrument_id(
    *,
    market: Market,
    asset_class: AssetClass,
    exchange: str,
    canonical_symbol: str,
    clearing_exchange: Optional[str] = None,
    underlying_instrument_id: Optional[str] = None,
    expiry_date: Optional[date] = None,
    strike_price: Optional[Decimal] = None,
    option_right: Optional[OptionRight] = None,
    contract_type: Optional[ContractType] = None,
    contract_multiplier: Optional[Decimal] = None,
    deliverable_shares: Optional[Decimal] = None,
    deliverable_type: Optional[str] = None,
    base_currency: Optional[str] = None,
    quote_currency: Optional[str] = None,
    settlement_currency: Optional[str] = None,
    is_inverse: bool = False,
) -> str:
    """Generate a deterministic, collision-resistant canonical instrument_id (v3).

    Uses a 128-bit (32-hex) SHA-256 digest of structured canonical fields plus a readable prefix.
    Includes canonical_symbol for options and crypto derivatives so adjusted/variant contracts
    never collide.
    """
    mkt = Market(market)
    ac = AssetClass(asset_class)
    ex = _clean_token(exchange)
    clr = _clean_token(clearing_exchange) if clearing_exchange else ""
    sym = _clean_token(canonical_symbol)

    payload: Dict[str, Any] = {
        "v": IDENTITY_VERSION,
        "market": mkt.value,
        "exchange": ex,
        "asset_class": ac.value,
    }
    if clr:
        payload["clearing_exchange"] = clr

    if ac in (AssetClass.EQUITY, AssetClass.ETF, AssetClass.INDEX):
        payload["canonical_symbol"] = sym
        prefix = f"{mkt.value}:{ex}:{ac.value}:{sym}"

    elif ac == AssetClass.OPTION:
        if not expiry_date or strike_price is None or option_right is None or not underlying_instrument_id:
            raise ValueError("Option identity requires underlying_instrument_id, expiry_date, strike_price, option_right")
        right = normalize_option_right(option_right)
        strike_s = normalize_decimal_str(strike_price)
        deliv_shares_s = normalize_decimal_str(deliverable_shares) if deliverable_shares is not None else "STANDARD"
        deliv_type_s = _clean_token(deliverable_type) if deliverable_type else "STANDARD"
        und_full = underlying_instrument_id.strip().upper()
        payload.update({
            "canonical_symbol": sym,
            "underlying_instrument_id": und_full,
            "expiry_date": expiry_date.strftime("%Y%m%d"),
            "strike_price": strike_s,
            "option_right": right.value,
            "deliverable_shares": deliv_shares_s,
            "deliverable_type": deliv_type_s,
        })
        und_short = und_full.split("#")[0].split(":")[-1]
        prefix = f"{mkt.value}:{ex}:OPTION:{und_short}:{expiry_date.strftime('%Y%m%d')}:{strike_s}:{right.value}:{sym}"

    elif ac == AssetClass.FUTURE:
        if not expiry_date:
            raise ValueError("Future identity requires expiry_date")
        und_full = underlying_instrument_id.strip().upper() if underlying_instrument_id else sym
        mult_s = normalize_decimal_str(contract_multiplier) if contract_multiplier is not None else "DEFAULT"
        payload.update({
            "underlying_instrument_id": und_full,
            "canonical_symbol": sym,
            "expiry_date": expiry_date.strftime("%Y%m%d"),
            "contract_multiplier": mult_s,
        })
        und_short = und_full.split("#")[0].split(":")[-1]
        prefix = f"{mkt.value}:{ex}:FUTURE:{und_short}:{expiry_date.strftime('%Y%m%d')}:{sym}"

    elif ac == AssetClass.CRYPTO_SPOT:
        pair = _canonical_crypto_pair(sym, base_currency, quote_currency)
        payload["pair"] = pair
        prefix = f"{mkt.value}:{ex}:CRYPTO_SPOT:{pair}"

    elif ac == AssetClass.CRYPTO_FUTURE:
        if not expiry_date:
            raise ValueError("Crypto dated future identity requires expiry_date")
        pair = _canonical_crypto_pair(sym, base_currency, quote_currency)
        lin_inv = "INVERSE" if is_inverse else "LINEAR"
        settle = _clean_token(settlement_currency or quote_currency or "")
        ct = (contract_type or ContractType.DATED_FUTURE).value
        mult_s = normalize_decimal_str(contract_multiplier) if contract_multiplier is not None else "1"
        payload.update({
            "contract_type": ct,
            "canonical_symbol": sym,
            "pair": pair,
            "settlement_currency": settle,
            "direction": lin_inv,
            "contract_multiplier": mult_s,
            "expiry_date": expiry_date.strftime("%Y%m%d"),
        })
        prefix = f"{mkt.value}:{ex}:{ct}:{sym}:{pair}:{settle}:{lin_inv}:{expiry_date.strftime('%Y%m%d')}"

    elif ac == AssetClass.CRYPTO_PERPETUAL:
        pair = _canonical_crypto_pair(sym, base_currency, quote_currency)
        lin_inv = "INVERSE" if is_inverse else "LINEAR"
        settle = _clean_token(settlement_currency or quote_currency or "")
        ct = (contract_type or ContractType.PERPETUAL).value
        mult_s = normalize_decimal_str(contract_multiplier) if contract_multiplier is not None else "1"
        payload.update({
            "contract_type": ct,
            "canonical_symbol": sym,
            "pair": pair,
            "settlement_currency": settle,
            "direction": lin_inv,
            "contract_multiplier": mult_s,
        })
        prefix = f"{mkt.value}:{ex}:{ct}:{sym}:{pair}:{settle}:{lin_inv}"

    else:
        raise ValueError("Unsupported asset_class for identity: %r" % (ac,))

    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    return f"{prefix}#{digest}"


def build_mapping_id(
    instrument_id: str,
    provider: str,
    provider_exchange: Optional[str],
    provider_symbol: str,
    provider_instrument_id: Optional[str] = None,
    valid_from_iso: Optional[str] = None,
    provider_feed: Optional[str] = None,
) -> str:
    """Deterministic mapping_id from canonical + normalized provider coordinates + feed + validity start."""
    raw = "|".join([
        instrument_id.strip().upper(),
        provider.strip().lower(),
        (provider_exchange or "").strip().upper(),
        (provider_feed or "").strip().lower(),
        provider_symbol.strip(),
        (provider_instrument_id or "").strip(),
        (valid_from_iso or "").strip(),
    ])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"MAP:{digest}"


def compute_spec_hash(spec_payload: Dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of contract specification fields."""
    encoded = json.dumps(spec_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
