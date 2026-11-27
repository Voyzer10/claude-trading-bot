"""Historical US stock and option data clients for Alpaca Market Data API."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..instruments import InstrumentRegistry, Market
from .client import AlpacaDataClient
from .config import (
    NY_TZ,
    OPTION_FEEDS,
    OPTION_HISTORY_EARLIEST,
    STOCK_ADJUSTMENTS,
    STOCK_FEEDS,
    SUPPORTED_TIMEFRAMES,
    UTC_TZ,
    USCalendar,
)
from .exceptions import AlpacaAdapterError, AlpacaInputError

MAX_DATA_POINTS_PER_PAGE = 10000
MAX_OPTION_SYMBOLS_PER_REQUEST = 100

_TF_MINUTES = {"1Min": 1, "5Min": 5, "15Min": 15, "1Hour": 60}


def _to_dec(val: Any, name: str) -> Decimal:
    try:
        d = Decimal(str(val))
        if not d.is_finite():
            raise ValueError("non-finite")
        return d
    except (InvalidOperation, ValueError) as e:
        raise AlpacaAdapterError(f"Malformed decimal {name}: {val!r}") from e


def _parse_ts_utc(raw_ts: Any) -> datetime:
    s = str(raw_ts).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(UTC_TZ)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC_TZ).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class USStockBar:
    instrument_id: str
    symbol: str
    timeframe: str
    ts_utc: datetime
    ts_ny: datetime
    session: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trade_count: Optional[int]
    vwap: Optional[Decimal]
    feed: str
    adjustment: str
    asof: Optional[str] = None
    snapshot_version: Optional[str] = None


@dataclass
class StockBarsResult:
    bars_by_symbol: Dict[str, List[USStockBar]] = field(default_factory=dict)
    feed: str = "iex"
    adjustment: str = "raw"
    pages_fetched: int = 0
    pagination_complete: bool = True
    duplicates_dropped: int = 0
    out_of_range_dropped: int = 0
    missing_by_symbol: Dict[str, List[datetime]] = field(default_factory=dict)


def expected_us_session_timestamps(
    calendar: USCalendar,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    *,
    options_late_close: bool = False,
    require_verified: bool = True,
) -> List[datetime]:
    """Generate exact expected UTC regular-session bar timestamps within [start_dt, end_dt)."""
    if timeframe not in _TF_MINUTES:
        raise AlpacaInputError(f"Unsupported timeframe: {timeframe!r}")
    s_ny = start_dt.astimezone(NY_TZ) if start_dt.tzinfo else start_dt.replace(tzinfo=NY_TZ)
    e_ny = end_dt.astimezone(NY_TZ) if end_dt.tzinfo else end_dt.replace(tzinfo=NY_TZ)
    s_utc = s_ny.astimezone(UTC_TZ)
    e_utc = e_ny.astimezone(UTC_TZ)
    step = timedelta(minutes=_TF_MINUTES[timeframe])

    expected: List[datetime] = []
    cur_day = s_ny.date()
    end_day = e_ny.date()
    while cur_day <= end_day:
        bounds = calendar.session_bounds(cur_day, options_late_close=options_late_close, require_verified=require_verified)
        if bounds is not None:
            open_utc = bounds[0].astimezone(UTC_TZ)
            close_utc = bounds[1].astimezone(UTC_TZ)
            cur = open_utc
            while cur < close_utc:
                if s_utc <= cur < e_utc:
                    expected.append(cur)
                cur += step
        cur_day += timedelta(days=1)
    return expected


@dataclass(frozen=True)
class USOptionBar:
    instrument_id: str
    symbol: str
    timeframe: str
    ts_utc: datetime
    ts_ny: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    trade_count: Optional[int]
    vwap: Optional[Decimal]
    feed: str


@dataclass(frozen=True)
class USOptionTrade:
    instrument_id: str
    symbol: str
    ts_utc: datetime
    price: Decimal
    size: int
    exchange: str
    conditions: Tuple[str, ...]
    feed: str


@dataclass(frozen=True)
class USOptionQuote:
    instrument_id: str
    symbol: str
    ts_utc: datetime
    bid_price: Decimal
    bid_size: int
    bid_exchange: str
    ask_price: Decimal
    ask_size: int
    ask_exchange: str
    conditions: Tuple[str, ...]
    feed: str


@dataclass(frozen=True)
class USOptionSnapshot:
    instrument_id: str
    symbol: str
    feed: str
    bid_price: Optional[Decimal]
    ask_price: Optional[Decimal]
    last_trade_price: Optional[Decimal]
    implied_volatility: Optional[Decimal]
    greeks: Dict[str, Any]
    snapshot_ts_utc: Optional[datetime]


class AlpacaHistoricalStocks:
    """Historical US equity/ETF bars client (GET /v2/stocks/bars) with strict feed, adjustment, and checkpointing."""

    def __init__(
        self,
        *,
        client: Optional[AlpacaDataClient] = None,
        registry: Optional[InstrumentRegistry] = None,
        calendar: Optional[USCalendar] = None,
        checkpoint_dir: Optional[str] = None,
    ) -> None:
        self.client = client or AlpacaDataClient()
        self.registry = registry
        self.calendar = calendar or USCalendar()
        self.checkpoint_dir = checkpoint_dir

    def _resolve_id(self, symbol: str) -> Tuple[str, bool, Optional[str]]:
        sym = symbol.strip().upper()
        if self.registry is None:
            return f"US:UNREGISTERED:{sym}", False, None
        inst = self.registry.resolve_provider_symbol("alpaca", sym)
        if inst is None:
            inst = next((i for i in self.registry.list_by_market(Market.US) if i.canonical_symbol == sym), None)
        if inst is not None:
            late = bool((inst.metadata or {}).get("options_late_close", False))
            snap = (inst.metadata or {}).get("snapshot_date")
            return inst.instrument_id, late, snap
        return f"US:UNREGISTERED:{sym}", False, None

    def _ckpt_path(self, meta: Dict[str, Any]) -> Optional[str]:
        if not self.checkpoint_dir:
            return None
        key = hashlib.sha256(json.dumps(meta, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
        safe_syms = "_".join(meta["symbols"])[:40]
        return os.path.join(self.checkpoint_dir, f"{safe_syms}_{meta['timeframe']}_{meta['feed']}_{meta['adjustment']}_{key}.json")

    def _save_ckpt(self, path: Optional[str], data: Dict[str, Any]) -> None:
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def fetch_bars(
        self,
        symbols: Sequence[str],
        *,
        timeframe: str = "5Min",
        start: datetime,
        end: datetime,
        feed: str = "iex",
        adjustment: str = "raw",
        asof: Optional[date] = None,
        limit: int = MAX_DATA_POINTS_PER_PAGE,
    ) -> StockBarsResult:
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise AlpacaInputError(f"Unsupported stock timeframe: {timeframe!r}")
        if feed not in STOCK_FEEDS:
            raise AlpacaInputError(f"Unsupported stock feed: {feed!r} (expected {STOCK_FEEDS})")
        if adjustment not in STOCK_ADJUSTMENTS:
            raise AlpacaInputError(f"Unsupported adjustment: {adjustment!r} (expected {STOCK_ADJUSTMENTS})")
        syms = [s.strip().upper() for s in symbols if s.strip()]
        if not syms:
            raise AlpacaInputError("At least one stock symbol is required")
        start_utc = start.astimezone(UTC_TZ) if start.tzinfo else start.replace(tzinfo=NY_TZ).astimezone(UTC_TZ)
        end_utc = end.astimezone(UTC_TZ) if end.tzinfo else end.replace(tzinfo=NY_TZ).astimezone(UTC_TZ)
        if end_utc <= start_utc:
            raise AlpacaInputError("end must be after start")

        id_map = {s: self._resolve_id(s) for s in syms}
        ckpt_meta = {
            "version": 1,
            "symbols": sorted(syms),
            "instrument_ids": [id_map[s][0] for s in sorted(syms)],
            "timeframe": timeframe,
            "start": _iso_z(start_utc),
            "end": _iso_z(end_utc),
            "feed": feed,
            "adjustment": adjustment,
            "asof": asof.isoformat() if asof else None,
            "snapshot_version": id_map[syms[0]][2],
        }
        ckpt_path = self._ckpt_path(ckpt_meta)
        if ckpt_path and os.path.isfile(ckpt_path):
            try:
                with open(ckpt_path, encoding="utf-8") as fh:
                    ck = json.load(fh)
                if isinstance(ck, dict) and ck.get("meta") == ckpt_meta and ck.get("complete") is True:
                    # Reconstruct from validated checkpoint
                    pages_raw = ck.get("pages") or []
                    return self._parse_pages(pages_raw, syms, id_map, timeframe, start_utc, end_utc, feed, adjustment, asof, len(pages_raw))
            except Exception:
                pass

        params: Dict[str, Any] = {
            "symbols": ",".join(syms),
            "timeframe": timeframe,
            "start": _iso_z(start_utc),
            "end": _iso_z(end_utc),
            "feed": feed,
            "adjustment": adjustment,
            "limit": min(MAX_DATA_POINTS_PER_PAGE, max(1, int(limit))),
            "sort": "asc",
        }
        if asof is not None:
            params["asof"] = asof.isoformat()

        pag = self.client.get_paginated("data", "/v2/stocks/bars", params=params)
        if pag.pagination_complete:
            self._save_ckpt(ckpt_path, {"meta": ckpt_meta, "complete": True, "pages": pag.items})
        return self._parse_pages(
            pag.items, syms, id_map, timeframe, start_utc, end_utc, feed, adjustment, asof, pag.pages_fetched, pag.pagination_complete
        )

    def _parse_pages(
        self,
        pages: Sequence[Dict[str, Any]],
        syms: Sequence[str],
        id_map: Dict[str, Tuple[str, bool, Optional[str]]],
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
        feed: str,
        adjustment: str,
        asof: Optional[date],
        page_count: int,
        pagination_complete: bool = True,
    ) -> StockBarsResult:
        by_sym_ts: Dict[str, Dict[datetime, USStockBar]] = {s: {} for s in syms}
        dups = 0
        oor = 0

        for page in pages:
            bars_dict = (page or {}).get("bars") or {}
            if not isinstance(bars_dict, dict):
                continue
            for sym, raw_list in bars_dict.items():
                s_u = str(sym).strip().upper()
                if s_u not in by_sym_ts:
                    by_sym_ts[s_u] = {}
                iid, late, snap_ver = id_map.get(s_u, (f"US:UNREGISTERED:{s_u}", False, None))
                for b in raw_list or ():
                    ts_utc = _parse_ts_utc(b["t"])
                    if ts_utc < start_utc or ts_utc > end_utc:
                        oor += 1
                        continue
                    o_d = _to_dec(b["o"], "o")
                    h_d = _to_dec(b["h"], "h")
                    l_d = _to_dec(b["l"], "l")
                    c_d = _to_dec(b["c"], "c")
                    if h_d < max(o_d, c_d) or l_d > min(o_d, c_d) or h_d < l_d:
                        raise AlpacaAdapterError(f"Invalid OHLC for {s_u} at {ts_utc.isoformat()}")
                    vol = int(b["v"])
                    if vol < 0:
                        raise AlpacaAdapterError(f"Negative volume for {s_u} at {ts_utc.isoformat()}")
                    if ts_utc in by_sym_ts[s_u]:
                        dups += 1
                        continue
                    ts_ny = ts_utc.astimezone(NY_TZ)
                    sess = self.calendar.classify_session(ts_ny, options_late_close=late)
                    by_sym_ts[s_u][ts_utc] = USStockBar(
                        instrument_id=iid,
                        symbol=s_u,
                        timeframe=timeframe,
                        ts_utc=ts_utc,
                        ts_ny=ts_ny,
                        session=sess,
                        open=o_d,
                        high=h_d,
                        low=l_d,
                        close=c_d,
                        volume=vol,
                        trade_count=int(b["n"]) if b.get("n") is not None else None,
                        vwap=_to_dec(b["vw"], "vw") if b.get("vw") is not None else None,
                        feed=feed,
                        adjustment=adjustment,
                        asof=asof.isoformat() if asof else None,
                        snapshot_version=snap_ver,
                    )

        ordered: Dict[str, List[USStockBar]] = {}
        missing_by_sym: Dict[str, List[datetime]] = {}
        step = timedelta(minutes=_TF_MINUTES[timeframe])
        for s_u, ts_map in by_sym_ts.items():
            lst = [ts_map[k] for k in sorted(ts_map)]
            ordered[s_u] = lst
            miss: List[datetime] = []
            for p, c in zip(lst, lst[1:]):
                if p.ts_ny.date() != c.ts_ny.date():
                    continue
                cur = p.ts_utc + step
                while cur < c.ts_utc:
                    if self.calendar.is_in_regular_session(cur):
                        miss.append(cur)
                    cur += step
            missing_by_sym[s_u] = miss

        return StockBarsResult(
            bars_by_symbol=ordered,
            feed=feed,
            adjustment=adjustment,
            pages_fetched=page_count,
            pagination_complete=pagination_complete,
            duplicates_dropped=dups,
            out_of_range_dropped=oor,
            missing_by_symbol=missing_by_sym,
        )


class AlpacaHistoricalOptions:
    """Historical US options bars, trades, quotes, and snapshots client (since Feb 2024)."""

    def __init__(
        self,
        *,
        client: Optional[AlpacaDataClient] = None,
        registry: Optional[InstrumentRegistry] = None,
    ) -> None:
        self.client = client or AlpacaDataClient()
        self.registry = registry
        self.last_fetch_stats: Dict[str, Any] = {}

    def _resolve_id(self, occ_symbol: str) -> str:
        sym = occ_symbol.strip().upper()
        if self.registry is not None:
            inst = self.registry.resolve_provider_symbol("alpaca", sym)
            if inst is None:
                inst = next((i for i in self.registry.list_by_market(Market.US) if i.canonical_symbol == sym), None)
            if inst is not None:
                return inst.instrument_id
        return f"US:UNREGISTERED_OPTION:{sym}"

    @staticmethod
    def _validate_symbols_and_feed(symbols: Sequence[str], feed: str) -> List[str]:
        if feed not in OPTION_FEEDS:
            raise AlpacaInputError(f"Unsupported option feed: {feed!r} (expected {OPTION_FEEDS})")
        syms = [s.strip().upper() for s in symbols if s.strip()]
        if not syms:
            raise AlpacaInputError("At least one option symbol is required")
        if len(syms) > MAX_OPTION_SYMBOLS_PER_REQUEST:
            raise AlpacaInputError(
                f"Maximum {MAX_OPTION_SYMBOLS_PER_REQUEST} option symbols per request (got {len(syms)})"
            )
        return syms

    @staticmethod
    def _validate_range(start: datetime, end: datetime) -> Tuple[datetime, datetime, bool, Optional[datetime]]:
        s_utc = start.astimezone(UTC_TZ) if start.tzinfo else start.replace(tzinfo=NY_TZ).astimezone(UTC_TZ)
        e_utc = end.astimezone(UTC_TZ) if end.tzinfo else end.replace(tzinfo=NY_TZ).astimezone(UTC_TZ)
        if e_utc <= s_utc:
            raise AlpacaInputError("end must be after start")
        if e_utc.date() < OPTION_HISTORY_EARLIEST:
            raise AlpacaInputError(
                f"Alpaca historical options data is only available from {OPTION_HISTORY_EARLIEST.isoformat()}"
            )
        earliest_dt = datetime(OPTION_HISTORY_EARLIEST.year, OPTION_HISTORY_EARLIEST.month, OPTION_HISTORY_EARLIEST.day, tzinfo=UTC_TZ)
        if s_utc < earliest_dt:
            return earliest_dt, e_utc, True, s_utc
        return s_utc, e_utc, False, None

    def fetch_bars(
        self,
        symbols: Sequence[str],
        *,
        timeframe: str = "5Min",
        start: datetime,
        end: datetime,
        feed: str = "indicative",
    ) -> Tuple[Dict[str, List[USOptionBar]], int]:
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise AlpacaInputError(f"Unsupported option timeframe: {timeframe!r}")
        syms = self._validate_symbols_and_feed(symbols, feed)
        q_start, e_utc, pre_feb, orig_start = self._validate_range(start, end)
        pag = self.client.get_paginated(
            "data",
            "/v1beta1/options/bars",
            params={
                "symbols": ",".join(syms),
                "timeframe": timeframe,
                "start": _iso_z(q_start),
                "end": _iso_z(e_utc),
                "feed": feed,
                "limit": MAX_DATA_POINTS_PER_PAGE,
                "sort": "asc",
            },
        )
        by_sym_ts: Dict[str, Dict[datetime, USOptionBar]] = {s: {} for s in syms}
        dups = 0
        oor = 0
        for page in pag.items:
            for sym, rows in ((page or {}).get("bars") or {}).items():
                s_u = sym.strip().upper()
                iid = self._resolve_id(s_u)
                sym_map = by_sym_ts.setdefault(s_u, {})
                for b in rows or ():
                    ts_utc = _parse_ts_utc(b["t"])
                    if ts_utc < q_start or ts_utc > e_utc:
                        oor += 1
                        continue
                    o_d, h_d, l_d, c_d = _to_dec(b["o"], "o"), _to_dec(b["h"], "h"), _to_dec(b["l"], "l"), _to_dec(b["c"], "c")
                    if h_d < max(o_d, c_d) or l_d > min(o_d, c_d) or h_d < l_d:
                        raise AlpacaAdapterError(f"Invalid option OHLC for {s_u} at {ts_utc.isoformat()}")
                    vol = int(b["v"])
                    if vol < 0:
                        raise AlpacaAdapterError(f"Negative option volume for {s_u} at {ts_utc.isoformat()}")
                    if ts_utc in sym_map:
                        dups += 1
                        continue
                    sym_map[ts_utc] = USOptionBar(
                        instrument_id=iid,
                        symbol=s_u,
                        timeframe=timeframe,
                        ts_utc=ts_utc,
                        ts_ny=ts_utc.astimezone(NY_TZ),
                        open=o_d,
                        high=h_d,
                        low=l_d,
                        close=c_d,
                        volume=vol,
                        trade_count=int(b["n"]) if b.get("n") is not None else None,
                        vwap=_to_dec(b["vw"], "vw") if b.get("vw") is not None else None,
                        feed=feed,
                    )
        out = {s: [m[k] for k in sorted(m)] for s, m in by_sym_ts.items()}
        self.last_fetch_stats = {
            "endpoint": "bars",
            "pagination_complete": pag.pagination_complete,
            "pages_fetched": pag.pages_fetched,
            "duplicates_dropped": dups,
            "out_of_range_dropped": oor,
            "unavailable_pre_feb_2024": pre_feb,
            "unavailable_portion_start": orig_start.isoformat() if orig_start else None,
            "unavailable_portion_end": q_start.isoformat() if pre_feb else None,
        }
        return out, pag.pages_fetched

    def fetch_trades(
        self,
        symbols: Sequence[str],
        *,
        start: datetime,
        end: datetime,
        feed: str = "indicative",
    ) -> Tuple[Dict[str, List[USOptionTrade]], int]:
        syms = self._validate_symbols_and_feed(symbols, feed)
        q_start, e_utc, pre_feb, orig_start = self._validate_range(start, end)
        pag = self.client.get_paginated(
            "data",
            "/v1beta1/options/trades",
            params={
                "symbols": ",".join(syms),
                "start": _iso_z(q_start),
                "end": _iso_z(e_utc),
                "feed": feed,
                "limit": MAX_DATA_POINTS_PER_PAGE,
                "sort": "asc",
            },
        )
        by_sym: Dict[str, List[USOptionTrade]] = {s: [] for s in syms}
        seen: Dict[str, set] = {s: set() for s in syms}
        dups = 0
        oor = 0
        for page in pag.items:
            for sym, rows in ((page or {}).get("trades") or {}).items():
                s_u = sym.strip().upper()
                iid = self._resolve_id(s_u)
                lst = by_sym.setdefault(s_u, [])
                s_seen = seen.setdefault(s_u, set())
                for t in rows or ():
                    ts_utc = _parse_ts_utc(t["t"])
                    if ts_utc < q_start or ts_utc > e_utc:
                        oor += 1
                        continue
                    px = _to_dec(t["p"], "p")
                    sz = int(t["s"])
                    if sz < 0:
                        raise AlpacaAdapterError(f"Negative option trade size for {s_u} at {ts_utc.isoformat()}")
                    ex = str(t.get("x") or "")
                    conds = tuple(str(c) for c in (t.get("c") or ()))
                    dkey = (ts_utc, px, sz, ex, conds)
                    if dkey in s_seen:
                        dups += 1
                        continue
                    s_seen.add(dkey)
                    lst.append(USOptionTrade(
                        instrument_id=iid,
                        symbol=s_u,
                        ts_utc=ts_utc,
                        price=px,
                        size=sz,
                        exchange=ex,
                        conditions=conds,
                        feed=feed,
                    ))
        out = {s: sorted(lst, key=lambda x: x.ts_utc) for s, lst in by_sym.items()}
        self.last_fetch_stats = {
            "endpoint": "trades",
            "pagination_complete": pag.pagination_complete,
            "pages_fetched": pag.pages_fetched,
            "duplicates_dropped": dups,
            "out_of_range_dropped": oor,
            "unavailable_pre_feb_2024": pre_feb,
            "unavailable_portion_start": orig_start.isoformat() if orig_start else None,
            "unavailable_portion_end": q_start.isoformat() if pre_feb else None,
        }
        return out, pag.pages_fetched

    def fetch_quotes(
        self,
        symbols: Sequence[str],
        *,
        start: datetime,
        end: datetime,
        feed: str = "indicative",
    ) -> Tuple[Dict[str, List[USOptionQuote]], int]:
        syms = self._validate_symbols_and_feed(symbols, feed)
        q_start, e_utc, pre_feb, orig_start = self._validate_range(start, end)
        pag = self.client.get_paginated(
            "data",
            "/v1beta1/options/quotes",
            params={
                "symbols": ",".join(syms),
                "start": _iso_z(q_start),
                "end": _iso_z(e_utc),
                "feed": feed,
                "limit": MAX_DATA_POINTS_PER_PAGE,
                "sort": "asc",
            },
        )
        by_sym: Dict[str, List[USOptionQuote]] = {s: [] for s in syms}
        seen: Dict[str, set] = {s: set() for s in syms}
        dups = 0
        oor = 0
        for page in pag.items:
            for sym, rows in ((page or {}).get("quotes") or {}).items():
                s_u = sym.strip().upper()
                iid = self._resolve_id(s_u)
                lst = by_sym.setdefault(s_u, [])
                s_seen = seen.setdefault(s_u, set())
                for q in rows or ():
                    ts_utc = _parse_ts_utc(q["t"])
                    if ts_utc < q_start or ts_utc > e_utc:
                        oor += 1
                        continue
                    bp, ap = _to_dec(q["bp"], "bp"), _to_dec(q["ap"], "ap")
                    bs, as_ = int(q["bs"]), int(q["as"])
                    if bs < 0 or as_ < 0:
                        raise AlpacaAdapterError(f"Negative option quote size for {s_u} at {ts_utc.isoformat()}")
                    bx, ax = str(q.get("bx") or ""), str(q.get("ax") or "")
                    conds = tuple(str(c) for c in (q.get("c") or ()))
                    dkey = (ts_utc, bp, bs, bx, ap, as_, ax, conds)
                    if dkey in s_seen:
                        dups += 1
                        continue
                    s_seen.add(dkey)
                    lst.append(USOptionQuote(
                        instrument_id=iid,
                        symbol=s_u,
                        ts_utc=ts_utc,
                        bid_price=bp,
                        bid_size=bs,
                        bid_exchange=bx,
                        ask_price=ap,
                        ask_size=as_,
                        ask_exchange=ax,
                        conditions=conds,
                        feed=feed,
                    ))
        out = {s: sorted(lst, key=lambda x: x.ts_utc) for s, lst in by_sym.items()}
        self.last_fetch_stats = {
            "endpoint": "quotes",
            "pagination_complete": pag.pagination_complete,
            "pages_fetched": pag.pages_fetched,
            "duplicates_dropped": dups,
            "out_of_range_dropped": oor,
            "unavailable_pre_feb_2024": pre_feb,
            "unavailable_portion_start": orig_start.isoformat() if orig_start else None,
            "unavailable_portion_end": q_start.isoformat() if pre_feb else None,
        }
        return out, pag.pages_fetched

    def fetch_snapshots(
        self,
        symbols: Sequence[str],
        *,
        feed: str = "indicative",
    ) -> Dict[str, USOptionSnapshot]:
        """Fetch current option snapshots (Greeks/IV only from snapshot endpoint, never backfilled as history)."""
        syms = self._validate_symbols_and_feed(symbols, feed)
        resp = self.client.request(
            "data",
            "/v1beta1/options/snapshots",
            params={"symbols": ",".join(syms), "feed": feed},
        )
        snaps = (resp.body or {}).get("snapshots") or {}
        out: Dict[str, USOptionSnapshot] = {}
        for sym, d in snaps.items():
            if not isinstance(d, dict):
                continue
            s_u = sym.strip().upper()
            q = d.get("latestQuote") or {}
            tr = d.get("latestTrade") or {}
            ts_raw = q.get("t") or tr.get("t")
            out[s_u] = USOptionSnapshot(
                instrument_id=self._resolve_id(s_u),
                symbol=s_u,
                feed=feed,
                bid_price=_to_dec(q["bp"], "bp") if q.get("bp") is not None else None,
                ask_price=_to_dec(q["ap"], "ap") if q.get("ap") is not None else None,
                last_trade_price=_to_dec(tr["p"], "p") if tr.get("p") is not None else None,
                implied_volatility=_to_dec(d["impliedVolatility"], "iv") if d.get("impliedVolatility") is not None else None,
                greeks=dict(d.get("greeks") or {}),
                snapshot_ts_utc=_parse_ts_utc(ts_raw) if ts_raw else None,
            )
        return out
