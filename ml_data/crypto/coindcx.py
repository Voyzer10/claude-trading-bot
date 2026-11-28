"""CoinDCX Spot & Perpetual Futures public market data adapter (read-only)."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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
    COINDCX_API_BASE,
    COINDCX_PUBLIC_BASE,
    COINDCX_WS_URL,
    DEFAULT_CRYPTO_UNIVERSE,
    UTC_TZ,
    PublicCryptoHTTPClient,
)
from .exceptions import CryptoAdapterError, CryptoInputError
from .historical import CryptoCandle

COINDCX_SPOT_INTERVALS = ("1m", "5m", "15m", "30m", "1h")
COINDCX_FUTURES_RESOLUTIONS = {"1m": "1", "5m": "5", "1h": "60", "1d": "1D"}
COINDCX_MAX_CANDLES = 1000
COINDCX_LICENSE_NOTE = (
    "CoinDCX API Terms Section 2.3(c): market data and derived charts, analytics, or research "
    "must not be redistributed, displayed, or disseminated to third parties. Local/private research only."
)


def inspect_coindcx_credentials() -> Dict[str, str]:
    """Inspect CoinDCX API key presence without ever exposing values."""
    k = os.environ.get("COINDCX_API_KEY", "").strip()
    s = os.environ.get("COINDCX_API_SECRET", "").strip()
    if k and s:
        return {"COINDCX_API_KEY/COINDCX_API_SECRET": "PRESENT"}
    if k or s:
        return {"COINDCX_API_KEY/COINDCX_API_SECRET": "INVALID"}
    return {"COINDCX_API_KEY/COINDCX_API_SECRET": "ABSENT"}


def _dec(val: Any, name: str, *, positive: bool = False) -> Decimal:
    try:
        d = Decimal(str(val).strip())
        if not d.is_finite() or (positive and d <= 0):
            raise ValueError("invalid decimal")
        return d
    except (InvalidOperation, ValueError) as e:
        raise CryptoAdapterError(f"Malformed CoinDCX decimal {name}: {val!r}") from e


@dataclass
class CoinDCXDiscoveryReport:
    snapshot_date: date
    snapshot_sha256: str
    spot_instruments: List[Instrument] = field(default_factory=list)
    perpetual_instruments: List[Instrument] = field(default_factory=list)
    dated_futures_instruments: List[Instrument] = field(default_factory=list)
    dated_futures_status: str = "UNSUPPORTED"
    mappings: List[ProviderInstrumentMapping] = field(default_factory=list)
    unsupported: List[Dict[str, str]] = field(default_factory=list)


class CoinDCXDiscovery:
    """Dynamic spot and perpetual-futures discovery via CoinDCX public GET endpoints."""

    def __init__(self, *, client: Optional[PublicCryptoHTTPClient] = None) -> None:
        self.client = client or PublicCryptoHTTPClient()

    def discover_spot(
        self,
        *,
        registry: Optional[InstrumentRegistry] = None,
        universe: Optional[Sequence[str]] = DEFAULT_CRYPTO_UNIVERSE,
        dry_run: bool = False,
    ) -> CoinDCXDiscoveryReport:
        now_utc = datetime.now(UTC_TZ)
        resp_m = self.client.get(f"{COINDCX_API_BASE}/exchange/v1/markets")
        resp_d = self.client.get(f"{COINDCX_API_BASE}/exchange/v1/markets_details")
        details = resp_d.body if isinstance(resp_d.body, list) else []
        sha = hashlib.sha256(json.dumps(details, sort_keys=True).encode("utf-8")).hexdigest()
        allowed = {u.strip().upper() for u in universe} if universe else None
        rep = CoinDCXDiscoveryReport(snapshot_date=now_utc.date(), snapshot_sha256=sha)

        for r in details:
            if not isinstance(r, dict):
                continue
            pair = str(r.get("pair") or "").strip().upper()
            mcode = str(r.get("coindcx_name") or "").strip().upper()
            base = str(r.get("target_currency_short_name") or "").strip().upper()
            quote = str(r.get("base_currency_short_name") or "").strip().upper()
            if not pair or not mcode or not base or not quote:
                continue
            if allowed is not None and base not in allowed:
                continue

            status_raw = str(r.get("status") or "active").lower()
            is_active = status_raw == "active"
            step = _dec(r.get("step") or "0.00001", f"step ({mcode})", positive=True)
            min_qty = _dec(r.get("min_quantity") or step, f"min_quantity ({mcode})", positive=True)
            prec_q = int(r.get("base_currency_precision") or 2)
            tick = Decimal(10) ** (-max(0, prec_q))

            inst = Instrument(
                instrument_id="",
                market=Market.CRYPTO,
                asset_class=AssetClass.CRYPTO_SPOT,
                segment=Segment.CRYPTO_SPOT,
                exchange="COINDCX",
                canonical_symbol=f"{base}/{quote}",
                trading_symbol=mcode,
                display_name=f"{base}/{quote} Spot (CoinDCX)",
                base_currency=base,
                quote_currency=quote,
                price_currency=quote,
                tick_size=tick,
                quantity_step=step,
                minimum_order_quantity=min_qty,
                contract_type=ContractType.SPOT,
                settlement_type=SettlementType.CRYPTO,
                is_tradable=is_active,
                is_active=is_active,
                instrument_status=InstrumentStatus.ACTIVE if is_active else InstrumentStatus.INACTIVE,
                trading_calendar="CRYPTO_24_7",
                timezone="UTC",
                primary_provider="coindcx",
                provider_instrument_id=pair,
                provider_symbol=pair,
                source="coindcx_markets_details",
                last_verified_at=now_utc,
                metadata={
                    "provider_pair": pair,
                    "market_code": mcode,
                    "min_notional": str(r.get("min_notional")) if r.get("min_notional") is not None else None,
                    "max_quantity": str(r.get("max_quantity")) if r.get("max_quantity") is not None else None,
                    "base_currency_precision": r.get("base_currency_precision"),
                    "target_currency_precision": r.get("target_currency_precision"),
                    "snapshot_sha256": sha,
                    "license_restriction": COINDCX_LICENSE_NOTE,
                },
            )
            mapping = ProviderInstrumentMapping(
                instrument_id=inst.instrument_id,
                provider="coindcx",
                provider_symbol=pair,
                provider_instrument_id=pair,
                provider_exchange="COINDCX",
                provider_feed="public_spot",
                last_verified_at=now_utc,
                is_primary=True,
            )
            rep.spot_instruments.append(inst)
            rep.mappings.append(mapping)
            if registry is not None and not dry_run:
                registry.upsert(inst, mappings=[mapping])
        return rep

    def discover_futures(
        self,
        *,
        margin_currencies: Sequence[str] = ("USDT", "INR"),
        registry: Optional[InstrumentRegistry] = None,
        universe: Optional[Sequence[str]] = DEFAULT_CRYPTO_UNIVERSE,
        dry_run: bool = False,
    ) -> CoinDCXDiscoveryReport:
        now_utc = datetime.now(UTC_TZ)
        allowed = {u.strip().upper() for u in universe} if universe else None
        all_details: List[Dict[str, Any]] = []

        for mcurr in margin_currencies:
            mc = mcurr.strip().upper()
            resp = self.client.get(
                f"{COINDCX_API_BASE}/exchange/v1/derivatives/futures/data/active_instruments",
                params={"margin_currency_short_name[]": mc},
            )
            pairs = resp.body if isinstance(resp.body, list) else []
            for pair in pairs:
                p_str = str(pair).strip()
                if not p_str:
                    continue
                if allowed is not None and not any(f"-{u}_" in p_str.upper() for u in allowed):
                    continue
                d_resp = self.client.get(
                    f"{COINDCX_API_BASE}/exchange/v1/derivatives/futures/data/instrument",
                    params={"pair": p_str, "margin_currency_short_name": mc},
                )
                inst_doc = (d_resp.body or {}).get("instrument") if isinstance(d_resp.body, dict) else None
                if isinstance(inst_doc, dict):
                    all_details.append(inst_doc)

        sha = hashlib.sha256(json.dumps(all_details, sort_keys=True).encode("utf-8")).hexdigest()
        rep = CoinDCXDiscoveryReport(snapshot_date=now_utc.date(), snapshot_sha256=sha)

        for r in all_details:
            pair = str(r.get("pair") or "").strip()
            if not pair:
                continue
            base = str(r.get("position_currency_short_name") or r.get("base_currency_short_name") or "").strip().upper()
            quote = str(r.get("quote_currency_short_name") or "").strip().upper()
            settle = str(
                r.get("settle_currency_short_name")
                or r.get("settlement_currency_short_name")
                or r.get("margin_currency_short_name")
                or quote
            ).strip().upper()
            if not base or not quote:
                continue

            kind = str(r.get("kind") or "perpetual").strip().lower()
            settlement = str(r.get("settlement") or "never").strip().lower()
            is_perp = (kind == "perpetual" or settlement == "never")
            is_inverse = bool(r.get("is_inverse", False))
            is_quanto = bool(r.get("is_quanto", False))
            if is_quanto:
                rep.unsupported.append({"pair": pair, "reason": "UNSUPPORTED_QUANTO"})
                continue
            tick = _dec(r.get("price_increment") or "0.1", f"price_increment ({pair})", positive=True)
            step = _dec(r.get("quantity_increment") or "0.001", f"quantity_increment ({pair})", positive=True)
            min_qty = _dec(r.get("min_quantity") or r.get("min_trade_size") or step, f"min_quantity ({pair})", positive=True)
            raw_mult = None
            for mk in ("unit_contract_value", "contract_value", "unit_value", "contract_multiplier"):
                if r.get(mk) is not None and str(r.get(mk)).strip() != "":
                    raw_mult = r.get(mk)
                    break
            if raw_mult is None:
                rep.unsupported.append({"pair": pair, "reason": "MISSING_CONTRACT_VALUE"})
                continue
            mult = _dec(raw_mult, f"unit_contract_value ({pair})", positive=True)
            status_raw = str(r.get("status") or "active").lower()
            exit_only = bool(r.get("exit_only", False))
            is_tradable = (status_raw == "active") and not exit_only

            exp_date: Optional[date] = None
            if not is_perp and r.get("expiry_time"):
                exp_date = datetime.fromtimestamp(float(r["expiry_time"]) / 1000.0 if float(r["expiry_time"]) > 1e12 else float(r["expiry_time"]), tz=UTC_TZ).date()

            inst = Instrument(
                instrument_id="",
                market=Market.CRYPTO,
                asset_class=AssetClass.CRYPTO_PERPETUAL if is_perp else AssetClass.CRYPTO_FUTURE,
                segment=Segment.CRYPTO_PERPETUALS if is_perp else Segment.CRYPTO_FUTURES,
                exchange="COINDCX_FUTURES",
                canonical_symbol=pair.upper(),
                trading_symbol=pair,
                display_name=f"{base}/{quote} {'Perpetual' if is_perp else 'Future'} (CoinDCX)",
                base_currency=base,
                quote_currency=quote,
                settlement_currency=settle,
                price_currency=quote,
                expiry_date=exp_date,
                contract_multiplier=mult,
                tick_size=tick,
                quantity_step=step,
                minimum_order_quantity=min_qty,
                contract_type=ContractType.PERPETUAL if is_perp else ContractType.DATED_FUTURE,
                settlement_type=SettlementType.CRYPTO,
                margin_type=MarginType.INVERSE if is_inverse else MarginType.LINEAR,
                is_inverse=is_inverse,
                is_tradable=is_tradable,
                is_active=(status_raw == "active"),
                instrument_status=InstrumentStatus.ACTIVE if status_raw == "active" else InstrumentStatus.INACTIVE,
                trading_calendar="CRYPTO_24_7",
                timezone="UTC",
                primary_provider="coindcx",
                provider_instrument_id=pair,
                provider_symbol=pair,
                source="coindcx_futures_instrument",
                last_verified_at=now_utc,
                metadata={
                    "kind": kind,
                    "settlement": settlement,
                    "margin_currency": r.get("margin_currency_short_name"),
                    "is_inverse": is_inverse,
                    "is_quanto": is_quanto,
                    "funding_frequency": r.get("funding_frequency"),
                    "exit_only": exit_only,
                    "snapshot_sha256": sha,
                    "license_restriction": COINDCX_LICENSE_NOTE,
                },
            )
            mapping = ProviderInstrumentMapping(
                instrument_id=inst.instrument_id,
                provider="coindcx",
                provider_symbol=pair,
                provider_instrument_id=pair,
                provider_exchange="COINDCX_FUTURES",
                provider_feed="public_futures",
                last_verified_at=now_utc,
                is_primary=True,
            )
            if is_perp:
                rep.perpetual_instruments.append(inst)
            else:
                rep.dated_futures_instruments.append(inst)
                rep.dated_futures_status = "SUPPORTED"
            rep.mappings.append(mapping)
            if registry is not None and not dry_run:
                registry.upsert(inst, mappings=[mapping])

        return rep


class CoinDCXHistoricalClient:
    """Chunked, checkpointed historical candle client for CoinDCX spot and perpetual futures."""

    def __init__(
        self,
        *,
        client: Optional[PublicCryptoHTTPClient] = None,
        registry: Optional[InstrumentRegistry] = None,
        checkpoint_dir: Optional[str] = None,
    ) -> None:
        self.client = client or PublicCryptoHTTPClient()
        self.registry = registry
        self.checkpoint_dir = checkpoint_dir
        self.last_metadata: Dict[str, Any] = {}

    def _resolve_id(self, pair: str) -> Tuple[str, bool]:
        if self.registry is not None:
            inst = self.registry.resolve_provider_symbol("coindcx", pair)
            if inst is not None:
                return inst.instrument_id, inst.is_inverse
        return f"CRYPTO:UNREGISTERED:COINDCX:{pair}", False

    def _ckpt_path(self, meta: Dict[str, Any]) -> Optional[str]:
        if not self.checkpoint_dir:
            return None
        key = hashlib.sha256(json.dumps(meta, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        return os.path.join(self.checkpoint_dir, f"coindcx_{key}.json")

    def fetch_spot_candles(
        self,
        pair: str,
        *,
        interval: str = "5m",
        start: datetime,
        end: datetime,
        limit: int = COINDCX_MAX_CANDLES,
    ) -> List[CryptoCandle]:
        if interval not in COINDCX_SPOT_INTERVALS:
            raise CryptoInputError(f"Unsupported CoinDCX spot interval: {interval!r}")
        if limit < 1 or limit > COINDCX_MAX_CANDLES:
            raise CryptoInputError(f"CoinDCX spot candle limit must be 1..{COINDCX_MAX_CANDLES}")
        s_utc, e_utc = start.astimezone(UTC_TZ), end.astimezone(UTC_TZ)
        if e_utc <= s_utc:
            raise CryptoInputError("end must be after start")

        iid, is_inv = self._resolve_id(pair)
        ckpt_meta = {"kind": "spot", "pair": pair, "interval": interval, "s": s_utc.isoformat(), "e": e_utc.isoformat()}
        cp = self._ckpt_path(ckpt_meta)
        if cp and os.path.isfile(cp):
            try:
                with open(cp, encoding="utf-8") as fh:
                    doc = json.load(fh)
                if doc.get("meta") == ckpt_meta:
                    rows = doc.get("rows") or []
                    return self._parse_candles(rows, iid, pair, interval, s_utc, e_utc, is_inv, ts_ms=True)
            except Exception:
                pass

        resp = self.client.get(
            f"{COINDCX_PUBLIC_BASE}/market_data/candles",
            params={
                "pair": pair,
                "interval": interval,
                "startTime": int(s_utc.timestamp() * 1000),
                "endTime": int(e_utc.timestamp() * 1000),
                "limit": int(limit),
            },
        )
        rows = resp.body if isinstance(resp.body, list) else []
        out = self._parse_candles(rows, iid, pair, interval, s_utc, e_utc, is_inv, ts_ms=True)
        if cp:
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            tmp = f"{cp}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"meta": ckpt_meta, "rows": rows}, fh)
            os.replace(tmp, cp)
        return out

    def fetch_futures_candles(
        self,
        pair: str,
        *,
        interval: str = "5m",
        start: datetime,
        end: datetime,
    ) -> List[CryptoCandle]:
        """Fetch CoinDCX futures candlesticks (epoch seconds) or derive 15m from verified 5m bars."""
        if interval == "15m":
            bars_5m = self.fetch_futures_candles(pair, interval="5m", start=start, end=end)
            return self._derive_15m_from_5m(bars_5m)
        if interval not in COINDCX_FUTURES_RESOLUTIONS:
            raise CryptoInputError(f"Unsupported CoinDCX futures interval: {interval!r}")
        res_code = COINDCX_FUTURES_RESOLUTIONS[interval]
        s_utc, e_utc = start.astimezone(UTC_TZ), end.astimezone(UTC_TZ)
        if e_utc <= s_utc:
            raise CryptoInputError("end must be after start")

        iid, is_inv = self._resolve_id(pair)
        resp = self.client.get(
            f"{COINDCX_PUBLIC_BASE}/market_data/candlesticks",
            params={
                "pair": pair,
                "from": int(s_utc.timestamp()),   # epoch seconds!
                "to": int(e_utc.timestamp()),     # epoch seconds!
                "resolution": res_code,
                "pcode": "f",
            },
        )
        body = resp.body if isinstance(resp.body, dict) else {}
        rows = body.get("data") if isinstance(body, dict) else resp.body
        if not isinstance(rows, list):
            rows = []
        self.last_metadata = {
            "pair": pair,
            "interval": interval,
            "historical_funding_status": "UNSUPPORTED",
            "historical_oi_status": "UNSUPPORTED",
            "notes": "CoinDCX documents funding_frequency in contract details; no historical funding/OI series.",
        }
        return self._parse_candles(rows, iid, pair, interval, s_utc, e_utc, is_inv, ts_ms=False)

    @staticmethod
    def _parse_candles(
        rows: Sequence[Dict[str, Any]],
        iid: str,
        pair: str,
        interval: str,
        s_utc: datetime,
        e_utc: datetime,
        is_inv: bool,
        *,
        ts_ms: bool,
    ) -> List[CryptoCandle]:
        by_ts: Dict[datetime, CryptoCandle] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            raw_t = int(r["time"])
            sec = raw_t / 1000.0 if (ts_ms or raw_t > 10**12) else float(raw_t)
            ts = datetime.fromtimestamp(sec, tz=UTC_TZ)
            if ts < s_utc or ts > e_utc:
                continue
            o_d, h_d, l_d, c_d, v_d = (
                _dec(r["open"], "open"),
                _dec(r["high"], "high"),
                _dec(r["low"], "low"),
                _dec(r["close"], "close"),
                _dec(r["volume"], "volume"),
            )
            if h_d < max(o_d, c_d) or l_d > min(o_d, c_d) or v_d < 0:
                raise CryptoAdapterError(f"Invalid CoinDCX OHLCV for {pair} at {ts.isoformat()}")
            by_ts[ts] = CryptoCandle(
                instrument_id=iid,
                symbol=pair,
                provider="coindcx",
                timeframe=interval,
                ts_utc=ts,
                open=o_d,
                high=h_d,
                low=l_d,
                close=c_d,
                volume=v_d,
                quote_volume=None,
                quantity_unit="contracts_usd" if is_inv else "base_asset",
                is_inverse=is_inv,
            )
        return [by_ts[k] for k in sorted(by_ts)]

    @staticmethod
    def _derive_15m_from_5m(bars_5m: Sequence[CryptoCandle]) -> List[CryptoCandle]:
        buckets: Dict[datetime, List[CryptoCandle]] = {}
        for b in sorted(bars_5m, key=lambda x: x.ts_utc):
            m15 = (int(b.ts_utc.timestamp() // 60) // 15) * 15
            b_ts = datetime.fromtimestamp(m15 * 60, tz=UTC_TZ)
            buckets.setdefault(b_ts, []).append(b)
        out: List[CryptoCandle] = []
        for b_ts, grp in sorted(buckets.items()):
            out.append(
                CryptoCandle(
                    instrument_id=grp[0].instrument_id,
                    symbol=grp[0].symbol,
                    provider="coindcx",
                    timeframe="15m",
                    ts_utc=b_ts,
                    open=grp[0].open,
                    high=max(x.high for x in grp),
                    low=min(x.low for x in grp),
                    close=grp[-1].close,
                    volume=sum((x.volume for x in grp), Decimal("0")),
                    quote_volume=None,
                    quantity_unit=grp[0].quantity_unit,
                    is_inverse=grp[0].is_inverse,
                )
            )
        return out


class CoinDCXLiveBridge:
    """Decoder for CoinDCX Socket.IO (wss://stream.coindcx.com) public spot/futures market events."""

    ws_url = COINDCX_WS_URL

    def __init__(self, *, registry: InstrumentRegistry, clock: Callable[[], float] = time.time) -> None:
        self.registry = registry
        self._clock = clock
        self._lock = threading.RLock()
        self._latest: Dict[str, Dict[str, Any]] = {}

    def on_event(self, event_name: str, payload: str | Dict[str, Any]) -> Optional[Dict[str, Any]]:
        doc = json.loads(payload) if isinstance(payload, str) else dict(payload)
        data = doc.get("data") if isinstance(doc.get("data"), dict) else doc
        if isinstance(data, str):
            data = json.loads(data)
        pair = str(data.get("pair") or data.get("s") or "").strip()
        if not pair:
            return None
        inst = self.registry.resolve_provider_symbol("coindcx", pair)
        if inst is None:
            return None
        raw_t = data.get("T") or data.get("ts") or data.get("t")
        if raw_t:
            sec = float(raw_t) / 1000.0 if float(raw_t) > 1e12 else float(raw_t)
            ts = datetime.fromtimestamp(sec, tz=UTC_TZ)
        else:
            ts = datetime.fromtimestamp(self._clock(), tz=UTC_TZ)
        price = _dec(data["p"], "p") if data.get("p") is not None else (_dec(data["c"], "c") if data.get("c") is not None else None)
        rec = {
            "instrument_id": inst.instrument_id,
            "provider": "coindcx",
            "pair": pair,
            "event": event_name,
            "price": price,
            "ts_utc": ts,
        }
        with self._lock:
            self._latest[inst.instrument_id] = rec
        return rec
