"""Dynamic US equity, ETF, and index options contract discovery and Identity v3 mapping."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

# pyrefly: ignore[missing-import]
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
from .snapshots import (
    ImmutableSnapshotStore,
    StoredSnapshot,
    atomic_write_gz as _shared_atomic_write_gz,
    atomic_write_json as _shared_atomic_write_json,
)

MAX_CONTRACTS_PAGE_LIMIT = 10000

DEFAULT_US_OPTIONS_ROOT = os.path.join("data", "raw", "us", "alpaca", "options")
DEFAULT_US_MANIFEST_ROOT = os.path.join("data", "manifests", "us", "alpaca")

CANONICAL_US_OPTIONS_EXCHANGE = "US_OPTIONS"
"""Canonical options-market identity namespace for multi-listed US options.

Representation policy for multi-listed options and OPRA separation:
- US listed equity/ETF options are multi-listed across participating US options exchanges
  (e.g., Cboe/XCBO, Nasdaq PHLX/XPHL, ISE/XISX, NYSE Arca Options/ARCO, MIAX/XMIO) and
  cleared centrally through OCC.
- OPRA (Options Price Reporting Authority) is strictly the consolidated reporting processor
  and market-data feed, NOT a listing exchange or ISO-10383 exchange MIC.
- When an individual authoritative listing exchange is unavailable from Alpaca's
  ``/v2/options/contracts`` contract master, canonical Identity v3 assigns
  ``exchange="US_OPTIONS"`` (never inventing a single venue and never using ``OPRA`` as an
  exchange or ``exchange_mic``) and keeps ``exchange_mic=None`` unless an authoritative
  non-OPRA ISO MIC is explicitly provided.
- ``ProviderInstrumentMapping.provider_exchange`` and instrument metadata preserve the
  provider/OPRA tape attribution independently of canonical exchange identity, while market
  data endpoints preserve their active feed (``opra`` or ``indicative``).
"""

_NON_EXCHANGE_TOKENS = frozenset({"", "OPRA", "OCC", "UNKNOWN", CANONICAL_US_OPTIONS_EXCHANGE})


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


def _resolve_option_exchange_identity(
    raw_contract: Dict[str, Any],
) -> Tuple[str, Optional[str], str, bool]:
    """Separate canonical option exchange identity from OPRA consolidated reporting metadata.

    Returns ``(canonical_exchange, exchange_mic, provider_exchange, is_multi_listed)``.
    Never assigns ``OPRA`` as ``exchange_mic`` and never invents an exchange when absent.
    """
    raw_ex = str(raw_contract.get("exchange") or "").strip().upper()
    raw_mic = str(raw_contract.get("exchange_mic") or "").strip().upper()

    provider_exchange = raw_ex if raw_ex else "OPRA"
    if raw_ex in _NON_EXCHANGE_TOKENS:
        canonical_exchange = CANONICAL_US_OPTIONS_EXCHANGE
        is_multi_listed = True
    else:
        canonical_exchange = raw_ex
        is_multi_listed = False

    exchange_mic = raw_mic if raw_mic not in _NON_EXCHANGE_TOKENS else None
    return canonical_exchange, exchange_mic, provider_exchange, is_multi_listed


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


@dataclass(frozen=True)
class OptionContractsSnapshot:
    """Immutable, content-addressed US option contracts discovery snapshot."""

    snapshot_date: date
    retrieved_at_utc: datetime
    sha256: str
    raw_count: int
    raw_gz_path: str
    manifest_path: str
    raw_contracts: Tuple[Dict[str, Any], ...]
    filters: Dict[str, Any] = field(default_factory=dict)
    pages_fetched: int = 1
    pagination_complete: bool = True
    revision: int = 1


def _to_contracts_snapshot(s: StoredSnapshot) -> OptionContractsSnapshot:
    return OptionContractsSnapshot(
        snapshot_date=s.snapshot_date,
        retrieved_at_utc=s.retrieved_at_utc,
        sha256=s.sha256,
        raw_count=s.count,
        raw_gz_path=s.raw_gz_path,
        manifest_path=s.manifest_path,
        raw_contracts=s.rows,
        filters=s.filters,
        pages_fetched=s.pages_fetched,
        pagination_complete=s.pagination_complete,
        revision=s.revision,
    )


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
    snapshot_date: Optional[date] = None
    manifest_path: Optional[str] = None
    snapshot_revision: Optional[int] = None


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

    def _store(self) -> ImmutableSnapshotStore:
        return ImmutableSnapshotStore(
            component="contracts",
            raw_root=self.raw_root,
            manifest_root=self.manifest_root,
        )

    def _atomic_write_gz(self, path: str, text: str) -> None:
        _shared_atomic_write_gz(path, text)

    def _atomic_write_json(self, path: str, payload: Dict[str, Any]) -> None:
        _shared_atomic_write_json(path, payload)

    @staticmethod
    def _build_query_params(
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
        reference_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        if status not in ("active", "inactive"):
            raise AlpacaInputError(f"status must be 'active' or 'inactive' (got {status!r})")
        if limit < 1 or limit > MAX_CONTRACTS_PAGE_LIMIT:
            raise AlpacaInputError(f"limit must be between 1 and {MAX_CONTRACTS_PAGE_LIMIT}")

        today_ny = reference_date or datetime.now(UTC_TZ).astimezone(NY_TZ).date()
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
        return params

    def load_snapshot(
        self,
        snap_date: date,
        *,
        filters: Optional[Dict[str, Any]] = None,
        revision: Optional[int] = None,
        sha256: Optional[str] = None,
    ) -> Optional[OptionContractsSnapshot]:
        """Load the latest (or specific revision/sha256) validated contracts snapshot on snap_date."""
        stored = self._store().load_snapshot(snap_date, filters=filters, revision=revision, sha256=sha256)
        return _to_contracts_snapshot(stored) if stored is not None else None

    def list_snapshots(
        self,
        snap_date: date,
        *,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[OptionContractsSnapshot]:
        """List all immutable contracts snapshot revisions committed on snap_date."""
        return [_to_contracts_snapshot(s) for s in self._store().list_snapshots(snap_date, filters=filters)]

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
        reference_date: Optional[date] = None,
    ) -> Tuple[List[Dict[str, Any]], int, bool, Dict[str, Any]]:
        params = self._build_query_params(
            underlying_symbols=underlying_symbols,
            root_symbol=root_symbol,
            status=status,
            expiration_date_gte=expiration_date_gte,
            expiration_date_lte=expiration_date_lte,
            option_type=option_type,
            style=style,
            strike_price_gte=strike_price_gte,
            strike_price_lte=strike_price_lte,
            show_deliverables=show_deliverables,
            limit=limit,
            reference_date=reference_date,
        )
        pag = self.client.get_paginated(
            "trading",
            "/v2/options/contracts",
            params=params,
            items_key="option_contracts",
        )
        return [r for r in pag.items if isinstance(r, dict)], pag.pages_fetched, pag.pagination_complete, params

    def download_snapshot(
        self,
        *,
        snap_date: Optional[date] = None,
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
        dry_run: bool = False,
        force_refresh: bool = False,
    ) -> OptionContractsSnapshot:
        """Fetch and persist an immutable option contracts snapshot; force_refresh adds a revision only on change."""
        now_utc = datetime.now(UTC_TZ)
        target_date = snap_date or now_utc.astimezone(NY_TZ).date()
        params = self._build_query_params(
            underlying_symbols=underlying_symbols,
            root_symbol=root_symbol,
            status=status,
            expiration_date_gte=expiration_date_gte,
            expiration_date_lte=expiration_date_lte,
            option_type=option_type,
            style=style,
            strike_price_gte=strike_price_gte,
            strike_price_lte=strike_price_lte,
            show_deliverables=show_deliverables,
            limit=limit,
            reference_date=target_date if snap_date is not None else None,
        )
        if not force_refresh:
            existing = self.load_snapshot(target_date, filters=params)
            if existing is not None:
                return existing

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
            show_deliverables=show_deliverables,
            limit=limit,
            reference_date=target_date if snap_date is not None else None,
        )
        stored = self._store().persist(
            snap_date=target_date,
            now_utc=now_utc,
            filters=used_params,
            raw_rows=raw_rows,
            pages_fetched=pages,
            pagination_complete=complete,
            dry_run=dry_run,
            write_gz=self._atomic_write_gz,
            write_json=self._atomic_write_json,
        )
        return _to_contracts_snapshot(stored)

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
        snap_date: Optional[date] = None,
        snapshot: Optional[OptionContractsSnapshot] = None,
        force_refresh: Optional[bool] = None,
    ) -> OptionDiscoveryReport:
        if snapshot is not None:
            snap = snapshot
        else:
            snap = self.download_snapshot(
                snap_date=snap_date,
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
                dry_run=dry_run,
                force_refresh=True if force_refresh is None else force_refresh,
            )

        now_utc = snap.retrieved_at_utc
        snap_path = snap.raw_gz_path if (not dry_run or os.path.isfile(snap.raw_gz_path)) else None
        man_path = snap.manifest_path if (not dry_run or os.path.isfile(snap.manifest_path)) else None
        report = OptionDiscoveryReport(
            retrieved_at_utc=now_utc,
            pages_fetched=snap.pages_fetched,
            pagination_complete=snap.pagination_complete,
            snapshot_sha256=snap.sha256,
            snapshot_path=snap_path,
            snapshot_date=snap.snapshot_date,
            manifest_path=man_path,
            snapshot_revision=snap.revision,
        )

        # Build lookup of registered US underlyings (EQUITY, ETF, INDEX) by canonical symbol
        und_by_sym: Dict[str, Instrument] = {}
        for ac in (AssetClass.EQUITY, AssetClass.ETF, AssetClass.INDEX):
            for inst in registry.list_by_asset_class(ac):
                if inst.market == Market.US:
                    und_by_sym[inst.canonical_symbol.upper()] = inst

        for raw in snap.raw_contracts:
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

            canonical_ex, ex_mic, provider_ex, is_multi_listed = _resolve_option_exchange_identity(raw)

            inst = Instrument(
                instrument_id="",
                market=Market.US,
                asset_class=AssetClass.OPTION,
                segment=Segment.US_OPTIONS,
                exchange=canonical_ex,
                exchange_mic=ex_mic,
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
                provider_feed="opra",
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
                    "multi_listed": is_multi_listed,
                    "provider_exchange": provider_ex,
                    "provider_feed": "opra",
                    "reporting_processor": "OPRA",
                    "snapshot_date": snap.snapshot_date.isoformat(),
                    "snapshot_sha256": snap.sha256,
                    "snapshot_revision": snap.revision,
                },
            )
            mapping = ProviderInstrumentMapping(
                instrument_id=inst.instrument_id,
                provider="alpaca",
                provider_symbol=occ_sym,
                provider_instrument_id=provider_id,
                provider_exchange=provider_ex,
                provider_feed=None,
                last_verified_at=now_utc,
                is_primary=True,
            )
            report.contracts.append(inst)
            report.mappings.append(mapping)
            if not dry_run:
                registry.upsert(inst, mappings=[mapping])

        return report
