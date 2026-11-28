"""Crypto historical candles, funding rates, open interest, and WebSocket live bridge."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..instruments import InstrumentRegistry
from .config import (
    BINANCE_COINM_BASE,
    BINANCE_USDM_BASE,
    COINBASE_REST_BASE,
    UTC_TZ,
    PublicCryptoHTTPClient,
)
from .exceptions import CryptoAdapterError, CryptoInputError


def _dec(val: Any, name: str) -> Decimal:
    try:
        d = Decimal(str(val))
        if not d.is_finite():
            raise ValueError("non-finite")
        return d
    except (InvalidOperation, ValueError) as e:
        raise CryptoAdapterError(f"Malformed crypto decimal {name}: {val!r}") from e


@dataclass(frozen=True)
class CryptoCandle:
    instrument_id: str
    symbol: str
    provider: str
    timeframe: str
    ts_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Optional[Decimal]
    quantity_unit: str
    is_inverse: bool


@dataclass(frozen=True)
class CryptoFundingRecord:
    instrument_id: str
    symbol: str
    provider: str
    funding_time_utc: datetime
    funding_rate: Decimal
    mark_price: Optional[Decimal]
    next_funding_time_utc: Optional[datetime] = None


@dataclass(frozen=True)
class CryptoOpenInterestRecord:
    instrument_id: str
    symbol: str
    provider: str
    ts_utc: datetime
    open_interest: Decimal
    unit: str


class CryptoHistoricalClient:
    """Historical OHLCV, funding rate, and open interest client for Coinbase & Binance Futures."""

    def __init__(
        self,
        *,
        client: Optional[PublicCryptoHTTPClient] = None,
        registry: Optional[InstrumentRegistry] = None,
    ) -> None:
        self.client = client or PublicCryptoHTTPClient()
        self.registry = registry

    def _resolve_id(self, provider: str, sym: str) -> str:
        if self.registry is not None:
            inst = self.registry.resolve_provider_symbol(provider, sym)
            if inst is not None:
                return inst.instrument_id
        return f"CRYPTO:UNREGISTERED:{provider.upper()}:{sym}"

    def fetch_coinbase_candles(
        self,
        product_id: str,
        *,
        granularity_s: int = 300,
        start: datetime,
        end: datetime,
    ) -> List[CryptoCandle]:
        pid = product_id.strip().upper()
        if granularity_s not in (60, 300, 900, 3600, 21600, 86400):
            raise CryptoInputError(f"Unsupported Coinbase granularity_s: {granularity_s}")
        s_utc = start.astimezone(UTC_TZ)
        e_utc = end.astimezone(UTC_TZ)
        resp = self.client.get(
            f"{COINBASE_REST_BASE}/products/{pid}/candles",
            params={"granularity": int(granularity_s), "start": s_utc.isoformat(), "end": e_utc.isoformat()},
        )
        rows = resp.body if isinstance(resp.body, list) else []
        by_ts: Dict[datetime, CryptoCandle] = {}
        iid = self._resolve_id("coinbase", pid)
        tf_label = f"{granularity_s // 60}m" if granularity_s < 3600 else f"{granularity_s // 3600}h"
        for r in rows:
            # Coinbase format: [time, low, high, open, close, volume]
            ts = datetime.fromtimestamp(int(r[0]), tz=UTC_TZ)
            if ts < s_utc or ts > e_utc:
                continue
            l_d, h_d, o_d, c_d, v_d = _dec(r[1], "low"), _dec(r[2], "high"), _dec(r[3], "open"), _dec(r[4], "close"), _dec(r[5], "volume")
            if h_d < max(o_d, c_d) or l_d > min(o_d, c_d) or v_d < 0:
                raise CryptoAdapterError(f"Invalid Coinbase OHLCV at {ts.isoformat()}")
            by_ts[ts] = CryptoCandle(
                instrument_id=iid, symbol=pid, provider="coinbase", timeframe=tf_label,
                ts_utc=ts, open=o_d, high=h_d, low=l_d, close=c_d, volume=v_d,
                quote_volume=None, quantity_unit="base_asset", is_inverse=False,
            )
        return [by_ts[k] for k in sorted(by_ts)]

    def fetch_binance_klines(
        self,
        symbol: str,
        *,
        venue: str = "usdm",
        interval: str = "5m",
        start: datetime,
        end: datetime,
        limit: int = 1000,
    ) -> List[CryptoCandle]:
        v = venue.strip().lower()
        base_url = BINANCE_USDM_BASE if v == "usdm" else BINANCE_COINM_BASE
        path = "/fapi/v1/klines" if v == "usdm" else "/dapi/v1/klines"
        prov = "binance_usdm" if v == "usdm" else "binance_coinm"
        is_inv = v == "coinm"
        sym = symbol.strip().upper()
        s_utc, e_utc = start.astimezone(UTC_TZ), end.astimezone(UTC_TZ)

        resp = self.client.get(
            f"{base_url}{path}",
            params={
                "symbol": sym,
                "interval": interval,
                "startTime": int(s_utc.timestamp() * 1000),
                "endTime": int(e_utc.timestamp() * 1000),
                "limit": min(1500, int(limit)),
            },
        )
        rows = resp.body if isinstance(resp.body, list) else []
        by_ts: Dict[datetime, CryptoCandle] = {}
        iid = self._resolve_id(prov, sym)
        for r in rows:
            ts = datetime.fromtimestamp(int(r[0]) / 1000.0, tz=UTC_TZ)
            if ts < s_utc or ts > e_utc:
                continue
            o_d, h_d, l_d, c_d, v_d = _dec(r[1], "o"), _dec(r[2], "h"), _dec(r[3], "l"), _dec(r[4], "c"), _dec(r[5], "v")
            qv_d = _dec(r[7], "qv") if len(r) > 7 and r[7] is not None else None
            if h_d < max(o_d, c_d) or l_d > min(o_d, c_d) or v_d < 0:
                raise CryptoAdapterError(f"Invalid Binance OHLCV for {sym} at {ts.isoformat()}")
            by_ts[ts] = CryptoCandle(
                instrument_id=iid, symbol=sym, provider=prov, timeframe=interval,
                ts_utc=ts, open=o_d, high=h_d, low=l_d, close=c_d, volume=v_d,
                quote_volume=qv_d,
                quantity_unit="contracts_usd" if is_inv else "base_asset",
                is_inverse=is_inv,
            )
        return [by_ts[k] for k in sorted(by_ts)]

    def fetch_funding_rates(
        self,
        symbol: str,
        *,
        venue: str = "usdm",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[CryptoFundingRecord]:
        v = venue.strip().lower()
        base_url = BINANCE_USDM_BASE if v == "usdm" else BINANCE_COINM_BASE
        path = "/fapi/v1/fundingRate" if v == "usdm" else "/dapi/v1/fundingRate"
        prov = "binance_usdm" if v == "usdm" else "binance_coinm"
        sym = symbol.strip().upper()
        params: Dict[str, Any] = {"symbol": sym, "limit": 1000}
        if start:
            params["startTime"] = int(start.astimezone(UTC_TZ).timestamp() * 1000)
        if end:
            params["endTime"] = int(end.astimezone(UTC_TZ).timestamp() * 1000)
        resp = self.client.get(f"{base_url}{path}", params=params)
        rows = resp.body if isinstance(resp.body, list) else []
        iid = self._resolve_id(prov, sym)
        out = [
            CryptoFundingRecord(
                instrument_id=iid,
                symbol=sym,
                provider=prov,
                funding_time_utc=datetime.fromtimestamp(int(r["fundingTime"]) / 1000.0, tz=UTC_TZ),
                funding_rate=_dec(r["fundingRate"], "fundingRate"),
                mark_price=_dec(r["markPrice"], "markPrice") if r.get("markPrice") not in (None, "") else None,
            )
            for r in rows if isinstance(r, dict)
        ]
        return sorted(out, key=lambda x: x.funding_time_utc)

    def fetch_open_interest(self, symbol: str, *, venue: str = "usdm") -> CryptoOpenInterestRecord:
        v = venue.strip().lower()
        base_url = BINANCE_USDM_BASE if v == "usdm" else BINANCE_COINM_BASE
        path = "/fapi/v1/openInterest" if v == "usdm" else "/dapi/v1/openInterest"
        prov = "binance_usdm" if v == "usdm" else "binance_coinm"
        sym = symbol.strip().upper()
        resp = self.client.get(f"{base_url}{path}", params={"symbol": sym})
        d = resp.body if isinstance(resp.body, dict) else {}
        ts = datetime.fromtimestamp(int(d["time"]) / 1000.0, tz=UTC_TZ) if d.get("time") else datetime.now(UTC_TZ)
        return CryptoOpenInterestRecord(
            instrument_id=self._resolve_id(prov, sym),
            symbol=sym,
            provider=prov,
            ts_utc=ts,
            open_interest=_dec(d["openInterest"], "openInterest"),
            unit="contracts" if v == "coinm" else "base_asset",
        )


class CryptoLiveBridge:
    """Read-only WebSocket decoder for Coinbase public ticker & Binance Futures public streams."""

    def __init__(self, *, registry: InstrumentRegistry, clock: Callable[[], float] = time.time) -> None:
        self.registry = registry
        self._clock = clock
        self._lock = threading.RLock()
        self._latest: Dict[str, Dict[str, Any]] = {}

    def on_coinbase_ticker(self, raw_msg: str | bytes) -> Optional[Dict[str, Any]]:
        d = json.loads(raw_msg.decode("utf-8") if isinstance(raw_msg, bytes) else raw_msg)
        if d.get("type") != "ticker" or not d.get("product_id"):
            return None
        pid = str(d["product_id"]).strip().upper()
        inst = self.registry.resolve_provider_symbol("coinbase", pid)
        if inst is None:
            return None
        ts = datetime.fromisoformat(str(d["time"]).replace("Z", "+00:00")).astimezone(UTC_TZ) if d.get("time") else datetime.fromtimestamp(self._clock(), tz=UTC_TZ)
        rec = {
            "instrument_id": inst.instrument_id,
            "provider": "coinbase",
            "symbol": pid,
            "price": _dec(d["price"], "price"),
            "ts_utc": ts,
        }
        with self._lock:
            self._latest[inst.instrument_id] = rec
        return rec

    def on_binance_futures_event(self, raw_msg: str | bytes, *, venue: str = "usdm") -> Optional[Dict[str, Any]]:
        d = json.loads(raw_msg.decode("utf-8") if isinstance(raw_msg, bytes) else raw_msg)
        sym = str(d.get("s") or "").strip().upper()
        if not sym:
            return None
        prov = "binance_usdm" if venue.lower() == "usdm" else "binance_coinm"
        inst = self.registry.resolve_provider_symbol(prov, sym)
        if inst is None:
            return None
        ts = datetime.fromtimestamp(int(d["E"]) / 1000.0, tz=UTC_TZ) if d.get("E") else datetime.fromtimestamp(self._clock(), tz=UTC_TZ)
        rec = {
            "instrument_id": inst.instrument_id,
            "provider": prov,
            "symbol": sym,
            "event_type": str(d.get("e") or ""),
            "price": _dec(d["p"], "p") if d.get("p") is not None else None,
            "ts_utc": ts,
        }
        with self._lock:
            self._latest[inst.instrument_id] = rec
        return rec
