"""PyArrow Parquet reader/writer with strict Decimal128 preservation and atomic Zstd writes."""
from __future__ import annotations

import os
import threading
from datetime import date, datetime, timezone
from decimal import Context, Decimal, InvalidOperation, Overflow, Rounded, Inexact
from typing import List, Optional, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..instruments.identity import normalize_decimal_str
from .canonical_schema import CanonicalCandle, CanonicalQuote, CanonicalTrade
from .exceptions import PrecisionLossError

PARQUET_DECIMAL_TYPE = pa.decimal128(38, 12)
_TARGET_QUANT = Decimal("1e-12")
_UTC = timezone.utc

CANDLE_ARROW_SCHEMA = pa.schema([
    ("schema_version", pa.string()),
    ("instrument_id", pa.string()),
    ("market", pa.string()),
    ("asset_class", pa.string()),
    ("segment", pa.string()),
    ("exchange", pa.string()),
    ("provider", pa.string()),
    ("provider_symbol", pa.string()),
    ("provider_instrument_id", pa.string()),
    ("timestamp_start_utc", pa.timestamp("us", tz="UTC")),
    ("timestamp_end_utc", pa.timestamp("us", tz="UTC")),
    ("event_time_utc", pa.timestamp("us", tz="UTC")),
    ("received_at_utc", pa.timestamp("us", tz="UTC")),
    ("timeframe", pa.string()),
    ("trading_date", pa.date32()),
    ("trading_session", pa.string()),
    ("session_id", pa.string()),
    ("calendar_id", pa.string()),
    ("calendar_version", pa.string()),
    ("open", PARQUET_DECIMAL_TYPE),
    ("high", PARQUET_DECIMAL_TYPE),
    ("low", PARQUET_DECIMAL_TYPE),
    ("close", PARQUET_DECIMAL_TYPE),
    ("volume", PARQUET_DECIMAL_TYPE),
    ("quote_volume", PARQUET_DECIMAL_TYPE),
    ("trade_count", pa.int64()),
    ("open_interest", PARQUET_DECIMAL_TYPE),
    ("mark_price", PARQUET_DECIMAL_TYPE),
    ("index_price", PARQUET_DECIMAL_TYPE),
    ("funding_rate", PARQUET_DECIMAL_TYPE),
    ("funding_timestamp_utc", pa.timestamp("us", tz="UTC")),
    ("provider_feed", pa.string()),
    ("source_snapshot_id", pa.string()),
    ("source_record_id", pa.string()),
    ("dataset_version", pa.string()),
    ("adjustment_mode", pa.string()),
    ("retrieval_run_id", pa.string()),
    ("quality_status", pa.string()),
    ("quality_flags", pa.list_(pa.string())),
])


_DECIMAL128_CTX = Context(prec=38, traps=[InvalidOperation, Overflow, Rounded, Inexact])


def _check_decimal_scale(val: Optional[Decimal], name: str) -> Optional[Decimal]:
    if val is None:
        return None
    if not isinstance(val, Decimal) or not val.is_finite():
        raise PrecisionLossError(f"Decimal {name}={val!r} must be a finite Decimal")
    canon = Decimal(normalize_decimal_str(val))
    try:
        q = canon.quantize(_TARGET_QUANT, context=_DECIMAL128_CTX)
    except (InvalidOperation, Overflow, Rounded, Inexact) as exc:
        raise PrecisionLossError(
            f"Decimal {name}={val} exceeds Decimal128(38,12) precision/scale; refusing silent rounding"
        ) from exc
    if len(q.as_tuple().digits) > 38 or q != canon:
        raise PrecisionLossError(f"Decimal {name}={val} exceeds Decimal128(38,12); refusing silent rounding")
    return q


def _atomic_write_table(table: pa.Table, path: str) -> None:
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    os.makedirs(parent, exist_ok=True)
    tmp = os.path.join(parent, f".t{os.getpid()}_{threading.get_ident()}.tmp")
    try:
        pq.write_table(table, tmp, compression="zstd")
        os.replace(tmp, abs_path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def write_candles_parquet(candles: Sequence[CanonicalCandle], path: str) -> int:
    ordered = sorted(candles, key=lambda c: (c.instrument_id, c.timestamp_start_utc))
    rows = {f.name: [] for f in CANDLE_ARROW_SCHEMA}
    for c in ordered:
        rows["schema_version"].append(c.schema_version)
        rows["instrument_id"].append(c.instrument_id)
        rows["market"].append(c.market)
        rows["asset_class"].append(c.asset_class)
        rows["segment"].append(c.segment)
        rows["exchange"].append(c.exchange)
        rows["provider"].append(c.provider)
        rows["provider_symbol"].append(c.provider_symbol)
        rows["provider_instrument_id"].append(c.provider_instrument_id)
        rows["timestamp_start_utc"].append(c.timestamp_start_utc)
        rows["timestamp_end_utc"].append(c.timestamp_end_utc)
        rows["event_time_utc"].append(c.event_time_utc)
        rows["received_at_utc"].append(c.received_at_utc)
        rows["timeframe"].append(c.timeframe)
        rows["trading_date"].append(c.trading_date)
        rows["trading_session"].append(c.trading_session)
        rows["session_id"].append(c.session_id)
        rows["calendar_id"].append(c.calendar_id)
        rows["calendar_version"].append(c.calendar_version)
        rows["open"].append(_check_decimal_scale(c.open, "open"))
        rows["high"].append(_check_decimal_scale(c.high, "high"))
        rows["low"].append(_check_decimal_scale(c.low, "low"))
        rows["close"].append(_check_decimal_scale(c.close, "close"))
        rows["volume"].append(_check_decimal_scale(c.volume, "volume"))
        rows["quote_volume"].append(_check_decimal_scale(c.quote_volume, "quote_volume"))
        rows["trade_count"].append(c.trade_count)
        rows["open_interest"].append(_check_decimal_scale(c.open_interest, "open_interest"))
        rows["mark_price"].append(_check_decimal_scale(c.mark_price, "mark_price"))
        rows["index_price"].append(_check_decimal_scale(c.index_price, "index_price"))
        rows["funding_rate"].append(_check_decimal_scale(c.funding_rate, "funding_rate"))
        rows["funding_timestamp_utc"].append(c.funding_timestamp_utc)
        rows["provider_feed"].append(c.provider_feed)
        rows["source_snapshot_id"].append(c.source_snapshot_id)
        rows["source_record_id"].append(c.source_record_id)
        rows["dataset_version"].append(c.dataset_version)
        rows["adjustment_mode"].append(c.adjustment_mode)
        rows["retrieval_run_id"].append(c.retrieval_run_id)
        rows["quality_status"].append(c.quality_status)
        rows["quality_flags"].append(list(c.quality_flags))

    table = pa.Table.from_pydict(rows, schema=CANDLE_ARROW_SCHEMA)
    _atomic_write_table(table, path)
    return len(ordered)


def read_candles_parquet(path: str) -> List[CanonicalCandle]:
    table = pq.read_table(path)
    cols = table.to_pydict()
    n = table.num_rows
    out: List[CanonicalCandle] = []
    for i in range(n):
        def _opt_dec(k: str) -> Optional[Decimal]:
            v = cols[k][i]
            return v.normalize(context=_DECIMAL128_CTX) if isinstance(v, Decimal) else None

        out.append(
            CanonicalCandle(
                schema_version=cols["schema_version"][i],
                instrument_id=cols["instrument_id"][i],
                market=cols["market"][i],
                asset_class=cols["asset_class"][i],
                segment=cols["segment"][i],
                exchange=cols["exchange"][i],
                provider=cols["provider"][i],
                provider_symbol=cols["provider_symbol"][i],
                provider_instrument_id=cols["provider_instrument_id"][i],
                timestamp_start_utc=cols["timestamp_start_utc"][i].astimezone(_UTC),
                timestamp_end_utc=cols["timestamp_end_utc"][i].astimezone(_UTC),
                event_time_utc=cols["event_time_utc"][i].astimezone(_UTC),
                received_at_utc=cols["received_at_utc"][i].astimezone(_UTC),
                timeframe=cols["timeframe"][i],
                trading_date=cols["trading_date"][i],
                trading_session=cols["trading_session"][i],
                session_id=cols["session_id"][i],
                calendar_id=cols["calendar_id"][i],
                calendar_version=cols["calendar_version"][i],
                open=cols["open"][i].normalize(context=_DECIMAL128_CTX),
                high=cols["high"][i].normalize(context=_DECIMAL128_CTX),
                low=cols["low"][i].normalize(context=_DECIMAL128_CTX),
                close=cols["close"][i].normalize(context=_DECIMAL128_CTX),
                volume=cols["volume"][i].normalize(context=_DECIMAL128_CTX),
                quote_volume=_opt_dec("quote_volume"),
                trade_count=cols["trade_count"][i],
                open_interest=_opt_dec("open_interest"),
                mark_price=_opt_dec("mark_price"),
                index_price=_opt_dec("index_price"),
                funding_rate=_opt_dec("funding_rate"),
                funding_timestamp_utc=cols["funding_timestamp_utc"][i].astimezone(_UTC) if cols["funding_timestamp_utc"][i] else None,
                provider_feed=cols["provider_feed"][i],
                source_snapshot_id=cols["source_snapshot_id"][i],
                source_record_id=cols["source_record_id"][i],
                dataset_version=cols["dataset_version"][i],
                adjustment_mode=cols["adjustment_mode"][i],
                retrieval_run_id=cols["retrieval_run_id"][i],
                quality_status=cols["quality_status"][i],
                quality_flags=tuple(cols["quality_flags"][i] or ()),
            )
        )
    return out
