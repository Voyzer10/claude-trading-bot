"""Exact NIFTY/BANKNIFTY contract discovery and Identity v3 registry mapping."""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
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


class ContractDiscovery:
    """Discovers NIFTY & BANKNIFTY indices, futures, and options from Kite master snapshots."""

    def discover_from_snapshots(
        self,
        *,
        nse_snapshot: Optional[MasterSnapshot],
        nfo_snapshot: MasterSnapshot,
        registry: Optional[InstrumentRegistry] = None,
        dry_run: bool = False,
    ) -> DiscoveryReport:
        report = DiscoveryReport(snapshot_date=nfo_snapshot.snapshot_date)
        now_utc = datetime.now(timezone.utc)
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
                        provider_instrument_id=f"NSE:{spec['kite_tradingsymbol']}@{nse_snap_date_iso}",
                        provider_exchange="NSE",
                        provider_feed="kite",
                        last_verified_at=now_utc,
                        is_primary=True,
                    )
                )

        # 2. NFO Futures and Options (exact NIFTY / BANKNIFTY roots only)
        for row in nfo_snapshot.rows:
            ex = row.get("exchange", "").upper()
            seg = row.get("segment", "").upper()
            tsym = row.get("tradingsymbol", "").strip().upper()
            nm = row.get("name", "").strip().upper()
            itype = row.get("instrument_type", "").strip().upper()

            if ex != "NFO":
                continue

            # Only consider rows claiming NIFTY/BANKNIFTY name or symbol prefix, reject anything ambiguous
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
                        is_tradable=True,
                        is_active=True,
                        trading_calendar="XNSE",
                        timezone="Asia/Kolkata",
                        primary_provider="kite",
                        provider_instrument_id=f"NFO:{tsym}@{nfo_snapshot.snapshot_date.isoformat()}",
                        provider_symbol=tsym,
                        source="kite_instrument_master",
                        last_verified_at=now_utc,
                        metadata={
                            "instrument_token": tok,
                            "exchange_token": row.get("exchange_token"),
                            "snapshot_date": nfo_snapshot.snapshot_date.isoformat(),
                            "snapshot_sha256": nfo_snapshot.sha256,
                        },
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
                        is_tradable=True,
                        is_active=True,
                        trading_calendar="XNSE",
                        timezone="Asia/Kolkata",
                        primary_provider="kite",
                        provider_instrument_id=f"NFO:{tsym}@{nfo_snapshot.snapshot_date.isoformat()}",
                        provider_symbol=tsym,
                        source="kite_instrument_master",
                        last_verified_at=now_utc,
                        metadata={
                            "instrument_token": tok,
                            "exchange_token": row.get("exchange_token"),
                            "snapshot_date": nfo_snapshot.snapshot_date.isoformat(),
                            "snapshot_sha256": nfo_snapshot.sha256,
                        },
                    )
                    report.options.append(inst)

                report.mappings.append(
                    ProviderInstrumentMapping(
                        instrument_id=inst.instrument_id,
                        provider="kite",
                        provider_symbol=tsym,
                        provider_instrument_id=f"NFO:{tsym}@{nfo_snapshot.snapshot_date.isoformat()}",
                        provider_exchange="NFO",
                        provider_feed="kite",
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
            for inst in report.indices + report.futures + report.options:
                registry.upsert(inst, mappings=map_by_id.get(inst.instrument_id, []))

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
