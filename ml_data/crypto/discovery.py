"""Dynamic Crypto Spot (Coinbase) and Derivatives (Binance USD-M / COIN-M) instrument discovery."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence

from ..instruments import (
    AssetClass,
    ContractType,
    Instrument,
    InstrumentRegistry,
    InstrumentStatus,
    MarginType,
    Market,
    ProviderInstrumentMapping,
    Segment,
    SettlementType,
)
from .config import (
    BINANCE_COINM_BASE,
    BINANCE_USDM_BASE,
    COINBASE_REST_BASE,
    DEFAULT_CRYPTO_UNIVERSE,
    UTC_TZ,
    PublicCryptoHTTPClient,
)
from .exceptions import CryptoInputError


def _pos_dec(val: Any, name: str) -> Decimal:
    try:
        d = Decimal(str(val).strip())
        if not d.is_finite() or d <= 0:
            raise ValueError("non-positive")
        return d
    except (InvalidOperation, ValueError) as e:
        raise CryptoInputError(f"Invalid positive decimal {name}: {val!r}") from e


@dataclass
class CryptoDiscoveryReport:
    provider: str
    snapshot_date: date
    snapshot_sha256: str
    instruments: List[Instrument] = field(default_factory=list)
    mappings: List[ProviderInstrumentMapping] = field(default_factory=list)


class CryptoSpotDiscovery:
    """Discovers Coinbase public spot products reusing coinbase.py conventions."""

    def __init__(self, *, client: Optional[PublicCryptoHTTPClient] = None) -> None:
        self.client = client or PublicCryptoHTTPClient()

    def discover(
        self,
        *,
        registry: Optional[InstrumentRegistry] = None,
        universe: Optional[Sequence[str]] = DEFAULT_CRYPTO_UNIVERSE,
        dry_run: bool = False,
    ) -> CryptoDiscoveryReport:
        now_utc = datetime.now(UTC_TZ)
        resp = self.client.get(f"{COINBASE_REST_BASE}/products")
        rows = resp.body if isinstance(resp.body, list) else []
        sha = hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()
        allowed = {u.strip().upper() for u in universe} if universe else None
        report = CryptoDiscoveryReport(provider="coinbase", snapshot_date=now_utc.date(), snapshot_sha256=sha)

        for r in rows:
            if not isinstance(r, dict):
                continue
            pid = str(r.get("id") or "").strip().upper()
            base = str(r.get("base_currency") or "").strip().upper()
            quote = str(r.get("quote_currency") or "").strip().upper()
            if not pid or not base or not quote:
                continue
            if allowed is not None and base not in allowed:
                continue
            online = str(r.get("status") or "online").lower() == "online" and not bool(r.get("trading_disabled", False))
            base_inc = _pos_dec(r.get("base_increment") or "0.00000001", f"base_increment ({pid})")
            quote_inc = _pos_dec(r.get("quote_increment") or "0.01", f"quote_increment ({pid})")
            min_sz_raw = r.get("base_min_size")
            min_sz = _pos_dec(min_sz_raw, "base_min_size") if min_sz_raw else base_inc

            inst = Instrument(
                instrument_id="",
                market=Market.CRYPTO,
                asset_class=AssetClass.CRYPTO_SPOT,
                segment=Segment.CRYPTO_SPOT,
                exchange="COINBASE",
                canonical_symbol=f"{base}/{quote}",
                trading_symbol=pid,
                display_name=f"{base}/{quote} Spot (Coinbase)",
                base_currency=base,
                quote_currency=quote,
                price_currency=quote,
                tick_size=quote_inc,
                quantity_step=base_inc,
                minimum_order_quantity=min_sz,
                contract_type=ContractType.SPOT,
                settlement_type=SettlementType.CRYPTO,
                is_tradable=online,
                is_active=online,
                instrument_status=InstrumentStatus.ACTIVE if online else InstrumentStatus.INACTIVE,
                trading_calendar="CRYPTO_24_7",
                timezone="UTC",
                primary_provider="coinbase",
                provider_instrument_id=pid,
                provider_symbol=pid,
                source="coinbase_products_public",
                last_verified_at=now_utc,
                metadata={
                    "product_id": pid,
                    "status": r.get("status"),
                    "trading_disabled": bool(r.get("trading_disabled", False)),
                    "snapshot_sha256": sha,
                },
            )
            mapping = ProviderInstrumentMapping(
                instrument_id=inst.instrument_id,
                provider="coinbase",
                provider_symbol=pid,
                provider_instrument_id=pid,
                provider_exchange="COINBASE",
                provider_feed="public_spot",
                last_verified_at=now_utc,
                is_primary=True,
            )
            report.instruments.append(inst)
            report.mappings.append(mapping)
            if registry is not None and not dry_run:
                registry.upsert(inst, mappings=[mapping])

        return report


class CryptoDerivativesDiscovery:
    """Discovers Binance USD-M (linear) and COIN-M (inverse) perpetuals & dated futures."""

    def __init__(self, *, client: Optional[PublicCryptoHTTPClient] = None) -> None:
        self.client = client or PublicCryptoHTTPClient()

    def discover_binance(
        self,
        *,
        venue: str = "usdm",
        registry: Optional[InstrumentRegistry] = None,
        universe: Optional[Sequence[str]] = DEFAULT_CRYPTO_UNIVERSE,
        dry_run: bool = False,
    ) -> CryptoDiscoveryReport:
        v = venue.strip().lower()
        if v == "usdm":
            url = f"{BINANCE_USDM_BASE}/fapi/v1/exchangeInfo"
            ex_name = "BINANCE_USDM"
            is_inverse = False
            margin_type = MarginType.LINEAR
        elif v == "coinm":
            url = f"{BINANCE_COINM_BASE}/dapi/v1/exchangeInfo"
            ex_name = "BINANCE_COINM"
            is_inverse = True
            margin_type = MarginType.INVERSE
        else:
            raise CryptoInputError(f"Unsupported Binance derivatives venue: {venue!r}")

        now_utc = datetime.now(UTC_TZ)
        resp = self.client.get(url)
        body = resp.body if isinstance(resp.body, dict) else {}
        symbols = body.get("symbols") or []
        sha = hashlib.sha256(json.dumps(symbols, sort_keys=True).encode("utf-8")).hexdigest()
        allowed = {u.strip().upper() for u in universe} if universe else None
        report = CryptoDiscoveryReport(provider=ex_name.lower(), snapshot_date=now_utc.date(), snapshot_sha256=sha)

        for r in symbols:
            if not isinstance(r, dict):
                continue
            sym = str(r.get("symbol") or "").strip().upper()
            base = str(r.get("baseAsset") or "").strip().upper()
            quote = str(r.get("quoteAsset") or "").strip().upper()
            settle = str(r.get("marginAsset") or quote).strip().upper()
            ctype = str(r.get("contractType") or "").strip().upper()
            if not sym or not base or not quote or ctype not in ("PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER", "DATED_FUTURE"):
                continue
            if allowed is not None and base not in allowed:
                continue

            is_perp = ctype == "PERPETUAL"
            ac = AssetClass.CRYPTO_PERPETUAL if is_perp else AssetClass.CRYPTO_FUTURE
            seg = Segment.CRYPTO_PERPETUALS if is_perp else Segment.CRYPTO_FUTURES
            ct = ContractType.PERPETUAL if is_perp else ContractType.DATED_FUTURE

            exp_date: Optional[date] = None
            if not is_perp and r.get("deliveryDate"):
                exp_date = datetime.fromtimestamp(int(r["deliveryDate"]) / 1000.0, tz=UTC_TZ).date()

            filters = {f.get("filterType"): f for f in (r.get("filters") or []) if isinstance(f, dict)}
            tick = _pos_dec((filters.get("PRICE_FILTER") or {}).get("tickSize") or "0.1", f"tickSize ({sym})")
            step = _pos_dec((filters.get("LOT_SIZE") or {}).get("stepSize") or "0.001", f"stepSize ({sym})")
            min_qty = _pos_dec((filters.get("LOT_SIZE") or {}).get("minQty") or step, f"minQty ({sym})")
            mult = _pos_dec(r.get("contractSize") or "1", f"contractSize ({sym})")
            active = str(r.get("contractStatus") or r.get("status") or "").upper() == "TRADING"

            inst = Instrument(
                instrument_id="",
                market=Market.CRYPTO,
                asset_class=ac,
                segment=seg,
                exchange=ex_name,
                canonical_symbol=sym,
                trading_symbol=sym,
                display_name=f"{base}/{quote} {'Perpetual' if is_perp else 'Future'} ({ex_name})",
                base_currency=base,
                quote_currency=quote,
                settlement_currency=settle,
                price_currency=quote,
                expiry_date=exp_date,
                contract_multiplier=mult,
                tick_size=tick,
                quantity_step=step,
                minimum_order_quantity=min_qty,
                contract_type=ct,
                settlement_type=SettlementType.CRYPTO,
                margin_type=margin_type,
                is_inverse=is_inverse,
                is_tradable=active,
                is_active=active,
                instrument_status=InstrumentStatus.ACTIVE if active else InstrumentStatus.INACTIVE,
                trading_calendar="CRYPTO_24_7",
                timezone="UTC",
                primary_provider=ex_name.lower(),
                provider_instrument_id=sym,
                provider_symbol=sym,
                source=f"{ex_name.lower()}_exchangeInfo",
                last_verified_at=now_utc,
                metadata={
                    "contract_type_raw": ctype,
                    "is_inverse": is_inverse,
                    "unit_semantics": "contract_usd_inverse" if is_inverse else "base_asset_linear",
                    "snapshot_sha256": sha,
                },
            )
            mapping = ProviderInstrumentMapping(
                instrument_id=inst.instrument_id,
                provider=ex_name.lower(),
                provider_symbol=sym,
                provider_instrument_id=sym,
                provider_exchange=ex_name,
                provider_feed="public_futures",
                last_verified_at=now_utc,
                is_primary=True,
            )
            report.instruments.append(inst)
            report.mappings.append(mapping)
            if registry is not None and not dry_run:
                registry.upsert(inst, mappings=[mapping])

        return report
