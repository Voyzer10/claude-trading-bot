"""Exact NIFTY/BANKNIFTY contract discovery, Identity v3 mapping, and point-in-time lifecycle management."""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

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
from .config import IST_TZ, UTC_TZ
from .exceptions import ContractDiscoveryError
from .instrument_master import InstrumentMasterDownloader, MasterSnapshot

# Exact allowed index roots (no substring matching!)
INDEX_SPECS: Dict[str, Dict[str, str]] = {
    "NIFTY": {
        "kite_tradingsymbol": "NIFTY 50",
        "kite_name": "NIFTY 50",
        "display_name": "NIFTY 50 Index",
    },
    "BANKNIFTY": {
        "kite_tradingsymbol": "NIFTY BANK",
        "kite_name": "NIFTY BANK",
        "display_name": "NIFTY Bank Index",
    },
}

_ALLOWED_ROOTS = frozenset({"NIFTY", "BANKNIFTY"})
# Monthly/Weekly NFO symbol patterns:
#   Futures: NIFTY26DECFUT, BANKNIFTY26DECFUT
#   Monthly Opt: NIFTY26DEC24500CE, BANKNIFTY26DEC52500PE
#   Weekly Opt: NIFTY26D0324500CE, NIFTY2611424500PE (YY + M/MMM/DD + STRIKE + CE|PE)
_NFO_FUT_RE = re.compile(r"^(NIFTY|BANKNIFTY)(\d{2}[A-Z]{3})FUT$")
_NFO_OPT_RE = re.compile(r"^(NIFTY|BANKNIFTY)(\d{2}[A-Z0-9]{2,3})(\d+(?:\.\d+)?)(CE|PE)$")


@dataclass(frozen=True)
class ParsedNFOSymbol:
    root: str
    instrument_type: str  # "FUT", "CE", "PE"
    strike: Optional[Decimal] = None


@dataclass
class DiscoveryReport:
    snapshot_date: date
    indices: List[Instrument] = field(default_factory=list)
    futures: List[Instrument] = field(default_factory=list)
    options: List[Instrument] = field(default_factory=list)
    mappings: List[ProviderInstrumentMapping] = field(default_factory=list)
    rejected: List[Dict[str, str]] = field(default_factory=list)
    expired: List[str] = field(default_factory=list)
    temporarily_missing: List[str] = field(default_factory=list)
    withdrawn: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    reassigned_tokens: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def nifty_counts(self) -> Dict[str, int]:
        return {
            "futures": sum(1 for f in self.futures if f.canonical_symbol.startswith("NIFTY")),
            "ce": sum(1 for o in self.options if o.canonical_symbol.startswith("NIFTY") and o.option_right == OptionRight.CALL),
            "pe": sum(1 for o in self.options if o.canonical_symbol.startswith("NIFTY") and o.option_right == OptionRight.PUT),
        }

    @property
    def banknifty_counts(self) -> Dict[str, int]:
        return {
            "futures": sum(1 for f in self.futures if f.canonical_symbol.startswith("BANKNIFTY")),
            "ce": sum(1 for o in self.options if o.canonical_symbol.startswith("BANKNIFTY") and o.option_right == OptionRight.CALL),
            "pe": sum(1 for o in self.options if o.canonical_symbol.startswith("BANKNIFTY") and o.option_right == OptionRight.PUT),
        }


def parse_kite_nfo_symbol(tradingsymbol: str, name: str, instrument_type: str) -> Optional[ParsedNFOSymbol]:
    """Strictly parse a Kite NFO tradingsymbol for exact NIFTY or BANKNIFTY roots."""
    tsym = tradingsymbol.strip().upper()
    nm = name.strip().upper()
    itype = instrument_type.strip().upper()
    if nm not in _ALLOWED_ROOTS:
        return None
    if itype == "FUT":
        m = _NFO_FUT_RE.fullmatch(tsym)
        if not m or m.group(1) != nm:
            return None
        return ParsedNFOSymbol(root=nm, instrument_type="FUT")
    if itype in ("CE", "PE"):
        m = _NFO_OPT_RE.fullmatch(tsym)
        if not m or m.group(1) != nm or m.group(4) != itype:
            return None
        return ParsedNFOSymbol(root=nm, instrument_type=itype, strike=Decimal(m.group(3)))
    return None


def _to_decimal(val: Any, field_name: str) -> Decimal:
    try:
        d = Decimal(str(val).strip())
        if not d.is_finite():
            raise ValueError("non-finite")
        return d
    except (InvalidOperation, ValueError) as e:
        raise ContractDiscoveryError(f"Invalid decimal for {field_name}: {val!r}") from e


def _to_date(val: Any, field_name: str) -> date:
    s = str(val or "").strip()
    if not s:
        raise ContractDiscoveryError(f"Missing required date for {field_name}")
    try:
        return date.fromisoformat(s[:10])
    except ValueError as e:
        raise ContractDiscoveryError(f"Invalid ISO date for {field_name}: {s!r}") from e


def _snapshot_effective_utc(snap_date: date) -> datetime:
    """Start-of-day IST effective timestamp in UTC for point-in-time [valid_from, valid_until) bounds."""
    return datetime.combine(snap_date, dt_time(0, 0), tzinfo=IST_TZ).astimezone(UTC_TZ)


class ContractDiscovery:
    """Discovers NIFTY & BANKNIFTY indices, futures, and options from Kite master snapshots."""

    @staticmethod
    def _reconcile_mapping_for_instrument(
        registry: InstrumentRegistry,
        inst: Instrument,
        new_mapping: ProviderInstrumentMapping,
        *,
        effective_utc: datetime,
        now_utc: datetime,
        close_at_effective: bool = False,
        report: Optional[DiscoveryReport] = None,
    ) -> ProviderInstrumentMapping:
        """Maintain idempotent, non-overlapping [valid_from, valid_until) mappings on upsert.

        - If another instrument currently holds an open mapping for the same provider token or
          symbol, close that prior instrument's mapping at ``effective_utc`` without altering its
          canonical identity or earlier history.
        - If this instrument already has an identical open mapping, reuse its original
          ``valid_from`` so repeated snapshots remain idempotent.
        """
        prov = new_mapping.provider
        ex = new_mapping.provider_exchange
        ext_id = new_mapping.provider_instrument_id
        sym = new_mapping.provider_symbol

        # Close conflicting open mappings belonging to OTHER instruments (e.g. recycled Kite token)
        if ext_id:
            closed_tok = registry.close_provider_mappings(
                prov,
                close_at=effective_utc,
                provider_exchange=ex,
                provider_instrument_id=ext_id,
                exclude_instrument_id=inst.instrument_id,
            )
            if closed_tok and report is not None:
                report.reassigned_tokens.append({
                    "provider_exchange": ex,
                    "provider_instrument_id": ext_id,
                    "new_instrument_id": inst.instrument_id,
                    "effective_from": effective_utc.isoformat(),
                    "closed_prior_mappings": closed_tok,
                })
        registry.close_provider_mappings(
            prov,
            close_at=effective_utc,
            provider_exchange=ex,
            provider_symbol=sym,
            exclude_instrument_id=inst.instrument_id,
        )

        # Check this instrument's existing mappings for idempotent reuse vs token rotation
        existing_maps = [
            m for m in registry.get_provider_mappings(inst.instrument_id)
            if m.provider == prov and (m.provider_exchange or "") == (ex or "")
        ]
        open_same = [
            m for m in existing_maps
            if (m.valid_until is None or m.valid_until > effective_utc)
            and m.provider_symbol == sym
            and (m.provider_instrument_id or "") == (ext_id or "")
        ]
        if open_same:
            cur = open_same[-1]
            return ProviderInstrumentMapping(
                instrument_id=inst.instrument_id,
                provider=prov,
                provider_symbol=sym,
                provider_instrument_id=ext_id,
                provider_exchange=ex,
                provider_feed=new_mapping.provider_feed,
                valid_from=cur.valid_from,
                valid_until=effective_utc if close_at_effective and (cur.valid_from is None or effective_utc > cur.valid_from) else cur.valid_until,
                last_verified_at=now_utc,
                is_primary=True,
            )

        # Token or symbol changed for this same canonical instrument -> close its previous open mappings
        registry.close_provider_mappings(
            prov,
            close_at=effective_utc,
            provider_exchange=ex,
            instrument_id=inst.instrument_id,
        )
        return ProviderInstrumentMapping(
            instrument_id=inst.instrument_id,
            provider=prov,
            provider_symbol=sym,
            provider_instrument_id=ext_id,
            provider_exchange=ex,
            provider_feed=new_mapping.provider_feed,
            valid_from=effective_utc,
            valid_until=effective_utc if close_at_effective else None,
            last_verified_at=now_utc,
            is_primary=True,
        )

    @staticmethod
    def _reconcile_missing_derivatives(
        registry: InstrumentRegistry,
        *,
        seen_ids: Set[str],
        snap_date: date,
        effective_utc: datetime,
        now_utc: datetime,
        withdrawn_symbols: Set[str],
        report: DiscoveryReport,
    ) -> None:
        """Update registered IN derivatives absent from the latest NFO snapshot without misclassifying absence."""
        for ac in (AssetClass.FUTURE, AssetClass.OPTION):
            for existing in registry.list_by_asset_class(ac):
                if (
                    existing.market != Market.IN
                    or existing.exchange != "NFO"
                    or existing.primary_provider != "kite"
                    or existing.instrument_id in seen_ids
                ):
                    continue
                if existing.instrument_status in (InstrumentStatus.EXPIRED, InstrumentStatus.DELISTED):
                    continue

                meta = dict(existing.metadata or {})
                eff_exp = existing.last_trade_date or existing.expiry_date
                is_withdrawn = (
                    existing.canonical_symbol in withdrawn_symbols
                    or bool(meta.get("withdrawn", False))
                )
                expiry_established = bool(meta.get("expiry_established", eff_exp is not None))

                if is_withdrawn:
                    new_status = InstrumentStatus.DELISTED
                    lifecycle_state = "WITHDRAWN"
                    report.withdrawn.append(existing.instrument_id)
                    registry.close_provider_mappings(
                        "kite",
                        close_at=effective_utc,
                        provider_exchange="NFO",
                        instrument_id=existing.instrument_id,
                    )
                elif expiry_established and eff_exp is not None and eff_exp < snap_date:
                    new_status = InstrumentStatus.EXPIRED
                    lifecycle_state = "EXPIRED"
                    report.expired.append(existing.instrument_id)
                    registry.close_provider_mappings(
                        "kite",
                        close_at=effective_utc,
                        provider_exchange="NFO",
                        instrument_id=existing.instrument_id,
                    )
                elif eff_exp is None or not expiry_established:
                    new_status = InstrumentStatus.UNKNOWN
                    lifecycle_state = "UNRESOLVED"
                    report.unresolved.append(existing.instrument_id)
                else:
                    # Absent prior to established expiry -> TEMPORARILY_MISSING, NOT EXPIRED!
                    new_status = InstrumentStatus.UNKNOWN
                    lifecycle_state = "TEMPORARILY_MISSING"
                    report.temporarily_missing.append(existing.instrument_id)

                meta["lifecycle_state"] = lifecycle_state
                meta["missing_from_snapshot"] = True
                meta.setdefault("missing_since_snapshot_date", snap_date.isoformat())
                d = existing.to_dict()
                d["instrument_status"] = new_status.value
                d["is_active"] = False
                d["is_tradable"] = False
                d["updated_at"] = now_utc.isoformat()
                d["metadata"] = meta
                registry.upsert(Instrument.from_dict(d), validate_underlying=False)

    def discover_from_snapshots(
        self,
        *,
        nse_snapshot: Optional[MasterSnapshot],
        nfo_snapshot: MasterSnapshot,
        registry: Optional[InstrumentRegistry] = None,
        dry_run: bool = False,
        reconcile_missing: bool = True,
        withdrawn_symbols: Sequence[str] = (),
    ) -> DiscoveryReport:
        snap_date = nfo_snapshot.snapshot_date
        report = DiscoveryReport(snapshot_date=snap_date)
        now_utc = datetime.now(timezone.utc)
        nfo_effective_utc = _snapshot_effective_utc(snap_date)
        nse_effective_utc = (
            _snapshot_effective_utc(nse_snapshot.snapshot_date) if nse_snapshot is not None else nfo_effective_utc
        )
        nse_rows = nse_snapshot.rows if nse_snapshot else ()

        # 1. Underlying indices (exact match on NSE INDICES)
        idx_by_root: Dict[str, Instrument] = {}
        for root, spec in INDEX_SPECS.items():
            matched_row = next(
                (
                    r for r in nse_rows
                    if r.get("exchange", "").upper() == "NSE"
                    and r.get("segment", "").upper() == "INDICES"
                    and r.get("tradingsymbol", "").strip().upper() == spec["kite_tradingsymbol"]
                ),
                None,
            )
            token_meta = {"instrument_token": int(matched_row["instrument_token"])} if matched_row else {}
            tick_d = _to_decimal(matched_row.get("tick_size") or "0.05", "tick_size") if matched_row else Decimal("0.05")
            nse_snap_date_iso = nse_snapshot.snapshot_date.isoformat() if nse_snapshot is not None else None
            nse_snap_sha = nse_snapshot.sha256 if nse_snapshot is not None else None
            inst = Instrument(
                instrument_id="",
                market=Market.IN,
                asset_class=AssetClass.INDEX,
                segment=Segment.IN_INDEX,
                exchange="NSE",
                exchange_mic="XNSE",
                canonical_symbol=root,
                trading_symbol=spec["kite_tradingsymbol"],
                display_name=spec["display_name"],
                price_currency="INR",
                tick_size=tick_d,
                contract_type=ContractType.INDEX,
                settlement_type=SettlementType.CASH,
                margin_type=MarginType.STANDARD,
                is_tradable=False,
                is_active=True,
                trading_calendar="XNSE",
                timezone="Asia/Kolkata",
                primary_provider="kite",
                provider_instrument_id=(
                    f"NSE:{spec['kite_tradingsymbol']}@{nse_snap_date_iso}"
                    if (matched_row is not None and nse_snap_date_iso is not None) else None
                ),
                provider_symbol=f"NSE:{spec['kite_tradingsymbol']}",
                source="kite_instrument_master",
                last_verified_at=now_utc,
                metadata={
                    **token_meta,
                    "snapshot_date": nse_snap_date_iso,
                    "snapshot_sha256": nse_snap_sha,
                    "index_token_available": matched_row is not None,
                    "lifecycle_state": "ACTIVE" if matched_row is not None else "UNVERIFIED",
                },
            )
            idx_by_root[root] = inst
            report.indices.append(inst)
            if matched_row is not None and nse_snap_date_iso is not None:
                report.mappings.append(
                    ProviderInstrumentMapping(
                        instrument_id=inst.instrument_id,
                        provider="kite",
                        provider_symbol=spec["kite_tradingsymbol"],
                        provider_instrument_id=str(int(matched_row["instrument_token"])),
                        provider_exchange="NSE",
                        provider_feed="kite",
                        valid_from=nse_effective_utc,
                        valid_until=None,
                        last_verified_at=now_utc,
                        is_primary=True,
                    )
                )

        # 2. NFO Futures and Options (exact NIFTY / BANKNIFTY roots only)
        seen_derivative_ids: Set[str] = set()
        for row in nfo_snapshot.rows:
            ex = row.get("exchange", "").upper()
            seg = row.get("segment", "").upper()
            tsym = row.get("tradingsymbol", "").strip().upper()
            nm = row.get("name", "").strip().upper()
            itype = row.get("instrument_type", "").strip().upper()

            if ex != "NFO":
                continue

            parsed = parse_kite_nfo_symbol(tsym, nm, itype)
            if parsed is None:
                if "NIFTY" in nm or "NIFTY" in tsym:
                    report.rejected.append({
                        "tradingsymbol": tsym,
                        "name": nm,
                        "reason": "Out-of-scope or ambiguous NIFTY-like symbol (only exact NIFTY/BANKNIFTY permitted)",
                    })
                continue

            try:
                exp = _to_date(row.get("expiry"), "expiry")
                lot = _to_decimal(row.get("lot_size"), "lot_size")
                tick = _to_decimal(row.get("tick_size"), "tick_size")
                tok = int(row["instrument_token"])
                und_inst = idx_by_root[parsed.root]

                expired_by_meta = exp < snap_date
                inst_status = InstrumentStatus.EXPIRED if expired_by_meta else InstrumentStatus.ACTIVE
                lifecycle_state = "EXPIRED" if expired_by_meta else "ACTIVE"
                common_meta = {
                    "instrument_token": tok,
                    "exchange_token": row.get("exchange_token"),
                    "snapshot_date": snap_date.isoformat(),
                    "snapshot_sha256": nfo_snapshot.sha256,
                    "lifecycle_state": lifecycle_state,
                    "last_seen_snapshot_date": snap_date.isoformat(),
                    "expiry_established": True,
                    "missing_from_snapshot": False,
                }

                if parsed.instrument_type == "FUT":
                    if seg not in ("NFO-FUT", ""):
                        raise ContractDiscoveryError(f"Unexpected segment {seg!r} for NFO future")
                    inst = Instrument(
                        instrument_id="",
                        market=Market.IN,
                        asset_class=AssetClass.FUTURE,
                        segment=Segment.IN_INDEX_FUTURES,
                        exchange="NFO",
                        exchange_mic="XNSE",
                        canonical_symbol=tsym,
                        trading_symbol=tsym,
                        display_name=f"{parsed.root} {exp.isoformat()} Future",
                        underlying_instrument_id=und_inst.instrument_id,
                        price_currency="INR",
                        expiry_date=exp,
                        last_trade_date=exp,
                        contract_multiplier=Decimal("1"),
                        lot_size=lot,
                        tick_size=tick,
                        minimum_order_quantity=lot,
                        quantity_step=lot,
                        contract_type=ContractType.DATED_FUTURE,
                        settlement_type=SettlementType.CASH,
                        margin_type=MarginType.STANDARD,
                        is_tradable=not expired_by_meta,
                        is_active=not expired_by_meta,
                        instrument_status=inst_status,
                        trading_calendar="XNSE",
                        timezone="Asia/Kolkata",
                        primary_provider="kite",
                        provider_instrument_id=f"NFO:{tsym}@{snap_date.isoformat()}",
                        provider_symbol=tsym,
                        source="kite_instrument_master",
                        last_verified_at=now_utc,
                        metadata=common_meta,
                    )
                    report.futures.append(inst)
                else:
                    if seg not in ("NFO-OPT", ""):
                        raise ContractDiscoveryError(f"Unexpected segment {seg!r} for NFO option")
                    strike = _to_decimal(row.get("strike"), "strike")
                    right = OptionRight.CALL if parsed.instrument_type == "CE" else OptionRight.PUT
                    inst = Instrument(
                        instrument_id="",
                        market=Market.IN,
                        asset_class=AssetClass.OPTION,
                        segment=Segment.IN_INDEX_OPTIONS,
                        exchange="NFO",
                        exchange_mic="XNSE",
                        canonical_symbol=tsym,
                        trading_symbol=tsym,
                        display_name=f"{parsed.root} {exp.isoformat()} {strike} {parsed.instrument_type}",
                        underlying_instrument_id=und_inst.instrument_id,
                        price_currency="INR",
                        expiry_date=exp,
                        last_trade_date=exp,
                        strike_price=strike,
                        option_right=right,
                        contract_multiplier=Decimal("1"),
                        exercise_style="EUROPEAN",
                        lot_size=lot,
                        tick_size=tick,
                        minimum_order_quantity=lot,
                        quantity_step=lot,
                        contract_type=ContractType.OPTION,
                        settlement_type=SettlementType.CASH,
                        margin_type=MarginType.STANDARD,
                        is_tradable=not expired_by_meta,
                        is_active=not expired_by_meta,
                        instrument_status=inst_status,
                        trading_calendar="XNSE",
                        timezone="Asia/Kolkata",
                        primary_provider="kite",
                        provider_instrument_id=f"NFO:{tsym}@{snap_date.isoformat()}",
                        provider_symbol=tsym,
                        source="kite_instrument_master",
                        last_verified_at=now_utc,
                        metadata=common_meta,
                    )
                    report.options.append(inst)

                seen_derivative_ids.add(inst.instrument_id)
                report.mappings.append(
                    ProviderInstrumentMapping(
                        instrument_id=inst.instrument_id,
                        provider="kite",
                        provider_symbol=tsym,
                        provider_instrument_id=str(tok),
                        provider_exchange="NFO",
                        provider_feed="kite",
                        valid_from=nfo_effective_utc,
                        valid_until=None,
                        last_verified_at=now_utc,
                        is_primary=True,
                    )
                )
            except Exception as e:
                report.rejected.append({"tradingsymbol": tsym, "name": nm, "reason": str(e)})

        if registry is not None and not dry_run:
            map_by_id: Dict[str, List[ProviderInstrumentMapping]] = {}
            for m in report.mappings:
                map_by_id.setdefault(m.instrument_id, []).append(m)
            for idx_inst in report.indices:
                eff = nse_effective_utc
                idx_maps = [
                    self._reconcile_mapping_for_instrument(
                        registry, idx_inst, m, effective_utc=eff, now_utc=now_utc, report=report
                    )
                    for m in map_by_id.get(idx_inst.instrument_id, [])
                ]
                registry.upsert(idx_inst, mappings=idx_maps)
            for inst in report.futures + report.options:
                reconciled_maps = [
                    self._reconcile_mapping_for_instrument(
                        registry,
                        inst,
                        m,
                        effective_utc=nfo_effective_utc,
                        now_utc=now_utc,
                        close_at_effective=(inst.instrument_status == InstrumentStatus.EXPIRED),
                        report=report,
                    )
                    for m in map_by_id.get(inst.instrument_id, [])
                ]
                registry.upsert(inst, mappings=reconciled_maps)

            if reconcile_missing:
                self._reconcile_missing_derivatives(
                    registry,
                    seen_ids=seen_derivative_ids,
                    snap_date=snap_date,
                    effective_utc=nfo_effective_utc,
                    now_utc=now_utc,
                    withdrawn_symbols={s.strip().upper() for s in withdrawn_symbols if s.strip()},
                    report=report,
                )

        return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Discover NIFTY/BANKNIFTY contracts from Kite instrument master.")
    p.add_argument("--dry-run", action="store_true", help="Inspect discovery counts without writing to registry.")
    p.add_argument("--db", default="data/instruments.sqlite3", help="Registry SQLite path.")
    args = p.parse_args(argv)

    dl = InstrumentMasterDownloader()
    nse_snap = dl.download_snapshot("NSE", dry_run=args.dry_run)
    nfo_snap = dl.download_snapshot("NFO", dry_run=args.dry_run)
    reg = None if args.dry_run else InstrumentRegistry(args.db)
    try:
        rep = ContractDiscovery().discover_from_snapshots(
            nse_snapshot=nse_snap, nfo_snapshot=nfo_snap, registry=reg, dry_run=args.dry_run
        )
    finally:
        if reg is not None:
            reg.close()

    print(json.dumps({
        "snapshot_date": rep.snapshot_date.isoformat(),
        "indices": len(rep.indices),
        "nifty": rep.nifty_counts,
        "banknifty": rep.banknifty_counts,
        "rejected": len(rep.rejected),
        "dry_run": args.dry_run,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
