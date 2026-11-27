"""Dynamic US equity, ETF, and index options contract discovery and Identity v3 mapping."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..instruments import (
    AssetClass,
    ContractType,
    Instrument,
    InstrumentRegistry,
    InstrumentStatus,
    MarginType,
    Market,
    OptionRight,
    ProviderInstrumentMapping,
    Segment,
    SettlementType,
)
from .client import AlpacaDataClient
from .config import NY_TZ, UTC_TZ
from .exceptions import AlpacaInputError

MAX_CONTRACTS_PAGE_LIMIT = 10000


DEFAULT_US_OPTIONS_ROOT = os.path.join("data", "raw", "us", "alpaca", "options")
DEFAULT_US_MANIFEST_ROOT = os.path.join("data", "manifests", "us", "alpaca")


def _to_positive_decimal(val: Any, name: str) -> Decimal:
    if val in (None, ""):
        raise AlpacaInputError(f"Missing required positive decimal field: {name}")
    try:
        d = Decimal(str(val).strip())
        if not d.is_finite() or d <= 0:
            raise ValueError("non-positive or non-finite")
        return d
    except (InvalidOperation, ValueError) as e:
        raise AlpacaInputError(f"Invalid positive decimal for {name}: {val!r}") from e


def _parse_deliverables(raw_contract: Dict[str, Any]) -> Tuple[Decimal, str, Tuple[Dict[str, Any], ...]]:
    """Extract deliverable_shares, deliverable_type, and full deliverables metadata from Alpaca contract."""
    delivs = tuple(d for d in (raw_contract.get("deliverables") or []) if isinstance(d, dict))
    size_raw = raw_contract.get("size")
    size_dec = _to_positive_decimal(size_raw, "size") if size_raw not in (None, "") else None

    if not delivs:
        if size_dec is None:
            raise AlpacaInputError(f"Option contract {raw_contract.get('symbol')!r} missing both size and deliverables")
        return size_dec, "STANDARD" if size_dec == Decimal("100") else "ADJUSTED", ()

    total_shares = Decimal("0")
    has_cash = False
    has_equity = False
    for d in delivs:
        dtype = str(d.get("type") or "").strip().lower()
        if dtype == "cash":
            has_cash = True
        else:
            has_equity = True
            amt = d.get("amount")
            if amt not in (None, ""):
                total_shares += _to_positive_decimal(amt, "deliverable.amount")

    if has_cash and has_equity:
        d_type = "MIXED"
    elif has_cash and not has_equity:
        d_type = "CASH"
    elif total_shares != Decimal("100") or len(delivs) > 1:
        d_type = "ADJUSTED"
    else:
        d_type = "STANDARD"

    deliv_shares = size_dec if size_dec is not None else (total_shares if total_shares > 0 else Decimal("100"))
    if size_dec is not None and total_shares > 0 and not has_cash and size_dec != total_shares:
        raise AlpacaInputError(
            f"Contract {raw_contract.get('symbol')!r} size={size_dec} mismatches equity deliverables={total_shares}"
        )
    return deliv_shares, d_type, delivs


@dataclass
class OptionDiscoveryReport:
    retrieved_at_utc: datetime
    pages_fetched: int = 0
    pagination_complete: bool = True
    snapshot_sha256: Optional[str] = None
    snapshot_path: Optional[str] = None
    contracts: List[Instrument] = field(default_factory=list)
    mappings: List[ProviderInstrumentMapping] = field(default_factory=list)
    skipped: List[Dict[str, str]] = field(default_factory=list)


class AlpacaOptionsContractDiscovery:
    """Discovers US equity/ETF/index option contracts via GET /v2/options/contracts."""

    def __init__(
        self,
        *,
        client: Optional[AlpacaDataClient] = None,
        raw_root: str = DEFAULT_US_OPTIONS_ROOT,
        manifest_root: str = DEFAULT_US_MANIFEST_ROOT,
    ) -> None:
        self.client = client or AlpacaDataClient()
        self.raw_root = raw_root
        self.manifest_root = manifest_root

    def _persist_snapshot(
        self,
        *,
        snap_date: date,
        now_utc: datetime,
        filters: Dict[str, Any],
        raw_rows: Sequence[Dict[str, Any]],
        pages: int,
        complete: bool,
    ) -> Tuple[str, str]:
        payload_text = json.dumps(list(raw_rows), sort_keys=True)
        sha = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
        f_hash = hashlib.sha256(json.dumps(filters, sort_keys=True).encode("utf-8")).hexdigest()[:12]
        sdir = os.path.join(self.raw_root, f"date={snap_date.isoformat()}")
        mdir = os.path.join(self.manifest_root, f"date={snap_date.isoformat()}")
        os.makedirs(sdir, exist_ok=True)
        os.makedirs(mdir, exist_ok=True)
        gz_path = os.path.join(sdir, f"contracts_{f_hash}.json.gz")
        man_path = os.path.join(mdir, f"contracts_{f_hash}_manifest.json")
        if not os.path.exists(gz_path):
            tmp_gz = f"{gz_path}.{os.getpid()}.tmp"
            with gzip.open(tmp_gz, "wt", encoding="utf-8") as fh:
                fh.write(payload_text)
            os.replace(tmp_gz, gz_path)
            tmp_man = f"{man_path}.{os.getpid()}.tmp"
            with open(tmp_man, "w", encoding="utf-8") as fh:
                json.dump({
                    "snapshot_date": snap_date.isoformat(),
                    "retrieved_at_utc": now_utc.isoformat(),
                    "filters": filters,
                    "sha256": sha,
                    "count": len(raw_rows),
                    "pages_fetched": pages,
                    "pagination_complete": complete,
                }, fh, indent=2, sort_keys=True)
            os.replace(tmp_man, man_path)
        return sha, gz_path

    def fetch_raw_contracts(
        self,
        *,
        underlying_symbols: Optional[Sequence[str]] = None,
        root_symbol: Optional[str] = None,
        status: str = "active",
        expiration_date_gte: Optional[date] = None,
        expiration_date_lte: Optional[date] = None,
        option_type: Optional[str] = None,
        style: Optional[str] = None,
        strike_price_gte: Optional[Decimal] = None,
        strike_price_lte: Optional[Decimal] = None,
        show_deliverables: bool = True,
        limit: int = MAX_CONTRACTS_PAGE_LIMIT,
    ) -> Tuple[List[Dict[str, Any]], int]:
        if status not in ("active", "inactive"):
            raise AlpacaInputError(f"status must be 'active' or 'inactive' (got {status!r})")
        if limit < 1 or limit > MAX_CONTRACTS_PAGE_LIMIT:
            raise AlpacaInputError(f"limit must be between 1 and {MAX_CONTRACTS_PAGE_LIMIT}")

        today_ny = datetime.now(UTC_TZ).astimezone(NY_TZ).date()
        exp_gte = expiration_date_gte or today_ny
        exp_lte = expiration_date_lte or (today_ny + timedelta(days=365))

        params: Dict[str, Any] = {
            "status": status,
            "expiration_date_gte": exp_gte.isoformat(),
            "expiration_date_lte": exp_lte.isoformat(),
            "show_deliverables": "true" if show_deliverables else "false",
            "limit": int(limit),
        }
        if underlying_symbols:
            params["underlying_symbols"] = ",".join(s.strip().upper() for s in underlying_symbols if s.strip())
        if root_symbol:
            params["root_symbol"] = root_symbol.strip().upper()
        if option_type:
            params["type"] = option_type.strip().lower()
        if style:
            params["style"] = style.strip().lower()
        if strike_price_gte is not None:
            params["strike_price_gte"] = str(strike_price_gte)
        if strike_price_lte is not None:
            params["strike_price_lte"] = str(strike_price_lte)

        pag = self.client.get_paginated(
            "trading",
            "/v2/options/contracts",
            params=params,
            items_key="option_contracts",
        )
        return [r for r in pag.items if isinstance(r, dict)], pag.pages_fetched, pag.pagination_complete, params

    def discover_and_map(
        self,
        *,
        registry: InstrumentRegistry,
        underlying_symbols: Optional[Sequence[str]] = None,
        root_symbol: Optional[str] = None,
        status: str = "active",
        expiration_date_gte: Optional[date] = None,
        expiration_date_lte: Optional[date] = None,
        option_type: Optional[str] = None,
        style: Optional[str] = None,
        strike_price_gte: Optional[Decimal] = None,
        strike_price_lte: Optional[Decimal] = None,
        dry_run: bool = False,
    ) -> OptionDiscoveryReport:
        now_utc = datetime.now(UTC_TZ)
        # pyrefly: ignore[bad-unpacking]
        raw_rows, pages, complete, used_params = self.fetch_raw_contracts(
            underlying_symbols=underlying_symbols,
            root_symbol=root_symbol,
            status=status,
            expiration_date_gte=expiration_date_gte,
            expiration_date_lte=expiration_date_lte,
            option_type=option_type,
            style=style,
            strike_price_gte=strike_price_gte,
            strike_price_lte=strike_price_lte,
            show_deliverables=True,
        )
        snap_sha = hashlib.sha256(json.dumps(raw_rows, sort_keys=True).encode("utf-8")).hexdigest()
        snap_path: Optional[str] = None
        if not dry_run:
            snap_sha, snap_path = self._persist_snapshot(
                snap_date=now_utc.astimezone(NY_TZ).date(),
                now_utc=now_utc,
                filters=used_params,
                raw_rows=raw_rows,
                pages=pages,
                complete=complete,
            )
        report = OptionDiscoveryReport(
            retrieved_at_utc=now_utc,
            pages_fetched=pages,
            pagination_complete=complete,
            snapshot_sha256=snap_sha,
            snapshot_path=snap_path,
        )

        # Build lookup of registered US underlyings (EQUITY, ETF, INDEX) by canonical symbol
        und_by_sym: Dict[str, Instrument] = {}
        for ac in (AssetClass.EQUITY, AssetClass.ETF, AssetClass.INDEX):
            for inst in registry.list_by_asset_class(ac):
                if inst.market == Market.US:
                    und_by_sym[inst.canonical_symbol.upper()] = inst

        for raw in raw_rows:
            occ_sym = str(raw.get("symbol") or "").strip().upper()
            und_sym = str(raw.get("underlying_symbol") or "").strip().upper()
            if not occ_sym or not und_sym:
                continue
            und_inst = und_by_sym.get(und_sym)
            if und_inst is None:
                report.skipped.append({"symbol": occ_sym, "reason": f"Underlying {und_sym!r} not in registry"})
                continue

            exp = date.fromisoformat(str(raw["expiration_date"])[:10])
            strike = _to_positive_decimal(raw.get("strike_price"), "strike_price")
            raw_type = str(raw.get("type") or "").strip().lower()
            if raw_type == "call":
                right = OptionRight.CALL
            elif raw_type == "put":
                right = OptionRight.PUT
            else:
                raise AlpacaInputError(f"Invalid or missing option type {raw.get('type')!r} for {occ_sym}")

            raw_style = raw.get("style")
            if raw_style is not None:
                ex_style = str(raw_style).strip().upper()
                if ex_style not in ("AMERICAN", "EUROPEAN"):
                    raise AlpacaInputError(f"Invalid option exercise style {raw_style!r} for {occ_sym}")
            else:
                ex_style = None

            mult = _to_positive_decimal(raw.get("multiplier"), f"multiplier ({occ_sym})")
            raw_status = str(raw.get("status") or "active").strip().lower()
            inst_status = InstrumentStatus.ACTIVE if raw_status == "active" else InstrumentStatus.INACTIVE
            deliv_shares, deliv_type, delivs = _parse_deliverables(raw)
            is_index_opt = und_inst.asset_class == AssetClass.INDEX
            settle_type = SettlementType.CASH if (is_index_opt or deliv_type == "CASH") else SettlementType.PHYSICAL
            provider_id = str(raw.get("id") or occ_sym)
            root_sym = str(raw.get("root_symbol") or und_sym).strip().upper()
            ltd_raw = raw.get("last_trade_date")
            ltd = date.fromisoformat(str(ltd_raw)[:10]) if ltd_raw else None

            inst = Instrument(
                instrument_id="",
                market=Market.US,
                asset_class=AssetClass.OPTION,
                segment=Segment.US_OPTIONS,
                exchange="OPRA",
                exchange_mic="OPRA",
                canonical_symbol=occ_sym,
                trading_symbol=occ_sym,
                display_name=str(raw.get("name") or occ_sym).strip(),
                underlying_instrument_id=und_inst.instrument_id,
                price_currency="USD",
                expiry_date=exp,
                last_trade_date=ltd,
                strike_price=strike,
                option_right=right,
                contract_multiplier=mult,
                deliverable_shares=deliv_shares,
                deliverable_type=deliv_type,
                exercise_style=ex_style,
                contract_type=ContractType.OPTION,
                settlement_type=settle_type,
                margin_type=MarginType.STANDARD,
                is_tradable=bool(raw.get("tradable", True)),
                is_active=(inst_status == InstrumentStatus.ACTIVE),
                instrument_status=inst_status,
                trading_calendar="XNYS",
                timezone="America/New_York",
                primary_provider="alpaca",
                provider_instrument_id=provider_id,
                provider_symbol=occ_sym,
                source="alpaca_options_contracts_v2",
                last_verified_at=now_utc,
                metadata={
                    "alpaca_contract_id": provider_id,
                    "underlying_symbol": und_sym,
                    "underlying_asset_class": und_inst.asset_class.value,
                    "root_symbol": root_sym,
                    "deliverables": list(delivs),
                    "open_interest": raw.get("open_interest"),
                    "close_price": raw.get("close_price"),
                    "is_adjusted": deliv_type in ("ADJUSTED", "MIXED", "CASH") or root_sym != und_sym,
                    "snapshot_sha256": snap_sha,
                },
            )
            mapping = ProviderInstrumentMapping(
                instrument_id=inst.instrument_id,
                provider="alpaca",
                provider_symbol=occ_sym,
                provider_instrument_id=provider_id,
                provider_exchange="OPRA",
                provider_feed=None,
                last_verified_at=now_utc,
                is_primary=True,
            )
            report.contracts.append(inst)
            report.mappings.append(mapping)
            if not dry_run:
                registry.upsert(inst, mappings=[mapping])

        return report
