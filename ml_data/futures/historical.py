"""Historical US futures OHLCV, trades, BBO, and OI/statistics retrieval via Databento."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence

from ..instruments import InstrumentRegistry
from .client import DatabentoHistoricalClient
from .config import CMEGlobexCalendar, CME_TZ, DATABENTO_DATASET, DATABENTO_SCHEMAS, DATABENTO_SYMBOLOGY_TYPES, UTC_TZ
from .exceptions import FuturesAdapterError, FuturesInputError


def _dec(val: Any, name: str) -> Decimal:
    try:
        d = Decimal(str(val))
        if not d.is_finite():
            raise ValueError("non-finite")
        return d
    except (InvalidOperation, ValueError) as e:
        raise FuturesAdapterError(f"Malformed futures decimal {name}: {val!r}") from e


def _ts_utc(raw: Any) -> datetime:
    if isinstance(raw, (int, float)):
        # Databento nanoseconds or seconds
        sec = float(raw) / 1e9 if float(raw) > 1e14 else float(raw)
        return datetime.fromtimestamp(sec, tz=UTC_TZ)
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return dt.astimezone(UTC_TZ) if dt.tzinfo else dt.replace(tzinfo=UTC_TZ)


@dataclass(frozen=True)
class FuturesOHLCVBar:
    instrument_id: str
    raw_symbol: str
    publisher_instrument_id: Optional[int]
    dataset: str
    schema: str
    ts_utc: datetime
    ts_ct: datetime
    session: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    open_interest: Optional[int] = None


@dataclass
class FuturesHistoricalResult:
    dataset: str
    schema: str
    symbology_in: str
    bars: List[FuturesOHLCVBar] = field(default_factory=list)
    duplicates_dropped: int = 0
    out_of_range_dropped: int = 0


class DatabentoHistoricalFutures:
    """Streaming/chunked Databento historical futures client with Decimal and Globex session validation."""

    def __init__(
        self,
        *,
        client: Optional[DatabentoHistoricalClient] = None,
        registry: Optional[InstrumentRegistry] = None,
        calendar: Optional[CMEGlobexCalendar] = None,
        dataset: str = DATABENTO_DATASET,
    ) -> None:
        self.client = client or DatabentoHistoricalClient()
        self.registry = registry
        self.calendar = calendar or CMEGlobexCalendar()
        self.dataset = dataset

    def _resolve_id(self, raw_symbol: str) -> str:
        sym = raw_symbol.strip().upper()
        if self.registry is not None:
            inst = self.registry.resolve_provider_symbol("databento", sym)
            if inst is not None:
                return inst.instrument_id
        return f"US:UNREGISTERED_FUTURE:{sym}"

    def fetch_ohlcv(
        self,
        symbols: Sequence[str],
        *,
        schema: str = "ohlcv-1m",
        start: datetime,
        end: datetime,
        stype_in: str = "raw_symbol",
        stype_out: str = "instrument_id",
    ) -> FuturesHistoricalResult:
        if schema not in DATABENTO_SCHEMAS or not schema.startswith("ohlcv-"):
            raise FuturesInputError(f"Unsupported futures OHLCV schema: {schema!r}")
        if stype_in not in DATABENTO_SYMBOLOGY_TYPES:
            raise FuturesInputError(f"Unsupported Databento stype_in: {stype_in!r}")
        s_utc = start.astimezone(UTC_TZ) if start.tzinfo else start.replace(tzinfo=CME_TZ).astimezone(UTC_TZ)
        e_utc = end.astimezone(UTC_TZ) if end.tzinfo else end.replace(tzinfo=CME_TZ).astimezone(UTC_TZ)
        if e_utc <= s_utc:
            raise FuturesInputError("end must be after start")

        resp = self.client.request(
            "/v0/timeseries.get_range",
            params={
                "dataset": self.dataset,
                "schema": schema,
                "symbols": ",".join(s.strip() for s in symbols),
                "start": s_utc.isoformat().replace("+00:00", "Z"),
                "end": e_utc.isoformat().replace("+00:00", "Z"),
                "stype_in": stype_in,
                "stype_out": stype_out,
            },
        )
        rows = resp.body if isinstance(resp.body, list) else (resp.body or {}).get("data") or []
        by_key: Dict[tuple, FuturesOHLCVBar] = {}
        dups = 0
        oor = 0

        for r in rows:
            if not isinstance(r, dict):
                continue
            ts = _ts_utc(r["ts_event"])
            if ts < s_utc or ts > e_utc:
                oor += 1
                continue
            sym = str(r.get("raw_symbol") or r.get("symbol") or symbols[0]).strip().upper()
            iid = self._resolve_id(sym)
            o_d, h_d, l_d, c_d = _dec(r["open"], "open"), _dec(r["high"], "high"), _dec(r["low"], "low"), _dec(r["close"], "close")
            if h_d < max(o_d, c_d) or l_d > min(o_d, c_d) or h_d < l_d:
                raise FuturesAdapterError(f"Invalid futures OHLC for {sym} at {ts.isoformat()}")
            vol = int(r["volume"])
            if vol < 0:
                raise FuturesAdapterError(f"Negative futures volume for {sym} at {ts.isoformat()}")
            k = (iid, ts)
            if k in by_key:
                dups += 1
                continue
            ts_ct = ts.astimezone(CME_TZ)
            by_key[k] = FuturesOHLCVBar(
                instrument_id=iid,
                raw_symbol=sym,
                publisher_instrument_id=int(r["instrument_id"]) if r.get("instrument_id") is not None else None,
                dataset=self.dataset,
                schema=schema,
                ts_utc=ts,
                ts_ct=ts_ct,
                session=self.calendar.classify_session(ts_ct),
                open=o_d,
                high=h_d,
                low=l_d,
                close=c_d,
                volume=vol,
                open_interest=int(r["open_interest"]) if r.get("open_interest") is not None else None,
            )

        ordered = sorted(by_key.values(), key=lambda x: (x.instrument_id, x.ts_utc))
        return FuturesHistoricalResult(
            dataset=self.dataset,
            schema=schema,
            symbology_in=stype_in,
            bars=ordered,
            duplicates_dropped=dups,
            out_of_range_dropped=oor,
        )
