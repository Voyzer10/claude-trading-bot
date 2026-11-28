"""Databento GLBX.MDP3 futures instrument definition parser."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence

from .config import DATABENTO_DATASET, UTC_TZ
from .exceptions import FuturesInputError


def _pos_dec(val: Any, name: str) -> Decimal:
    if val in (None, ""):
        raise FuturesInputError(f"Missing required positive decimal {name} in futures definition")
    try:
        d = Decimal(str(val).strip())
        if not d.is_finite() or d <= 0:
            raise ValueError("non-positive")
        return d
    except (InvalidOperation, ValueError) as e:
        raise FuturesInputError(f"Invalid positive decimal {name}: {val!r}") from e


def _parse_iso_date(val: Any, name: str) -> date:
    s = str(val or "").strip()
    if not s:
        raise FuturesInputError(f"Missing required date {name} in futures definition")
    try:
        return date.fromisoformat(s[:10])
    except ValueError as e:
        raise FuturesInputError(f"Invalid ISO date {name}: {s!r}") from e


def _parse_ts(val: Any) -> Optional[datetime]:
    if val in (None, ""):
        return None
    if isinstance(val, datetime):
        return val.astimezone(UTC_TZ) if val.tzinfo else val.replace(tzinfo=UTC_TZ)
    dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    return dt.astimezone(UTC_TZ) if dt.tzinfo else dt.replace(tzinfo=UTC_TZ)


@dataclass(frozen=True)
class DatabentoDefinitionRecord:
    """Normalized Databento futures contract definition (never hardcodes tick/multiplier)."""

    dataset: str
    publisher_id: int
    venue: str
    exchange: str
    raw_symbol: str
    publisher_instrument_id: int
    product_root: str
    expiry_date: date
    last_trade_date: Optional[date]
    tick_size: Decimal
    contract_multiplier: Decimal
    tick_value: Decimal
    currency: str
    settlement_type: str
    instrument_class: str
    activation_utc: Optional[datetime]
    ts_event_utc: Optional[datetime]
    raw_record: Dict[str, Any]


def parse_definition_records(
    raw_rows: Sequence[Dict[str, Any]],
    *,
    dataset: str = DATABENTO_DATASET,
) -> List[DatabentoDefinitionRecord]:
    """Parse raw Databento definition JSON records into validated DatabentoDefinitionRecord instances."""
    out: List[DatabentoDefinitionRecord] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        raw_sym = str(row.get("raw_symbol") or row.get("symbol") or "").strip().upper()
        root = str(row.get("asset") or row.get("product_root") or "").strip().upper()
        if not raw_sym or not root:
            raise FuturesInputError(f"Definition record missing raw_symbol or asset root: {row!r}")
        pub_inst_id = int(row["instrument_id"])
        pub_id = int(row.get("publisher_id") or 1)
        venue = str(row.get("venue") or "GLBX").strip().upper()
        exchange = str(row.get("exchange") or "CME").strip().upper()
        exp = _parse_iso_date(row.get("expiration") or row.get("expiry_date"), "expiration")
        ltd_raw = row.get("last_trade_date")
        ltd = _parse_iso_date(ltd_raw, "last_trade_date") if ltd_raw else None
        tick = _pos_dec(row.get("min_price_increment") or row.get("tick_size"), f"min_price_increment ({raw_sym})")
        mult = _pos_dec(
            row.get("unit_of_measure_qty") or row.get("contract_multiplier"),
            f"contract_multiplier ({raw_sym})",
        )
        currency = str(row.get("currency") or "USD").strip().upper()
        settle = str(row.get("settlement_type") or "CASH").strip().upper()
        iclass = str(row.get("instrument_class") or "FUTURE").strip().upper()
        out.append(
            DatabentoDefinitionRecord(
                dataset=str(row.get("dataset") or dataset),
                publisher_id=pub_id,
                venue=venue,
                exchange=exchange,
                raw_symbol=raw_sym,
                publisher_instrument_id=pub_inst_id,
                product_root=root,
                expiry_date=exp,
                last_trade_date=ltd,
                tick_size=tick,
                contract_multiplier=mult,
                tick_value=tick * mult,
                currency=currency,
                settlement_type=settle,
                instrument_class=iclass,
                activation_utc=_parse_ts(row.get("activation")),
                ts_event_utc=_parse_ts(row.get("ts_event")),
                raw_record=dict(row),
            )
        )
    return out
