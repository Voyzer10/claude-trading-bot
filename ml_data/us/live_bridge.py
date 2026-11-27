"""Real-time Alpaca US stock (JSON) and option (MessagePack) WebSocket bridge."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import msgpack

from ..instruments import InstrumentRegistry, Market
from .config import OPTION_FEEDS, STOCK_FEEDS, UTC_TZ
from .exceptions import AlpacaInputError

STOCK_WS_URL = "wss://stream.data.alpaca.markets/v2/{feed}"
OPTION_WS_URL = "wss://stream.data.alpaca.markets/v1beta1/{feed}"


@dataclass(frozen=True)
class USRealtimeEvent:
    instrument_id: str
    provider_symbol: str
    feed: str
    event_type: str      # "trade" | "quote" | "bar" | "daily_bar" | "updated_bar"
    event_ts_utc: datetime
    received_at_utc: datetime
    data_source: str     # "alpaca_ws_stocks" | "alpaca_ws_options"
    price: Optional[Decimal] = None
    size: Optional[int] = None
    bid_price: Optional[Decimal] = None
    bid_size: Optional[int] = None
    ask_price: Optional[Decimal] = None
    ask_size: Optional[int] = None
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    close: Optional[Decimal] = None
    volume: Optional[int] = None
    revision_count: int = 0


def _ts(raw: Any) -> datetime:
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=UTC_TZ)
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(UTC_TZ)


class AlpacaUSLiveBridge:
    """Isolated read-only WebSocket decoder & state bridge for Alpaca US stocks and options."""

    def __init__(
        self,
        *,
        registry: InstrumentRegistry,
        stock_feed: str = "iex",
        option_feed: str = "indicative",
        max_stock_symbols: int = 30,
        max_option_symbols: int = 200,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if stock_feed not in STOCK_FEEDS:
            raise AlpacaInputError(f"Unsupported stock feed: {stock_feed!r}")
        if option_feed not in OPTION_FEEDS:
            raise AlpacaInputError(f"Unsupported option feed: {option_feed!r}")
        self.registry = registry
        self.stock_feed = stock_feed
        self.option_feed = option_feed
        self.max_stock_symbols = int(max_stock_symbols)
        self.max_option_symbols = int(max_option_symbols)
        self._clock = clock
        self._lock = threading.RLock()
        self._stock_syms: Dict[str, str] = {}     # symbol -> instrument_id
        self._option_syms: Dict[str, str] = {}    # occ_symbol -> instrument_id
        self._bars: Dict[Tuple[str, datetime], USRealtimeEvent] = {}
        self._latest_quotes: Dict[str, USRealtimeEvent] = {}
        self._latest_trades: Dict[str, USRealtimeEvent] = {}

    @property
    def stock_ws_url(self) -> str:
        return STOCK_WS_URL.format(feed=self.stock_feed)

    @property
    def option_ws_url(self) -> str:
        return OPTION_WS_URL.format(feed=self.option_feed)

    def subscribe_stocks(self, symbols: Sequence[str], *, ws: Any = None) -> List[str]:
        with self._lock:
            added: List[str] = []
            for sym in symbols:
                s_u = sym.strip().upper()
                if s_u == "*" or not s_u:
                    raise AlpacaInputError("Wildcard stock subscriptions are not permitted")
                if s_u not in self._stock_syms:
                    if len(self._stock_syms) >= self.max_stock_symbols:
                        raise AlpacaInputError(
                            f"Stock WebSocket symbol limit reached ({self.max_stock_symbols})"
                        )
                    inst = self.registry.resolve_provider_symbol("alpaca", s_u)
                    if inst is None:
                        inst = next((i for i in self.registry.list_by_market(Market.US) if i.canonical_symbol == s_u), None)
                    if inst is None:
                        raise AlpacaInputError(f"Unknown US stock symbol in registry: {s_u}")
                    self._stock_syms[s_u] = inst.instrument_id
                    added.append(s_u)
            if ws is not None and added:
                ws.send(json.dumps({"action": "subscribe", "trades": added, "quotes": added, "bars": added}))
            return added

    def subscribe_options(self, occ_symbols: Sequence[str], *, ws: Any = None) -> List[str]:
        with self._lock:
            added: List[str] = []
            for sym in occ_symbols:
                s_u = sym.strip().upper()
                if s_u == "*" or "*" in s_u or not s_u:
                    raise AlpacaInputError("Wildcard option quote subscriptions are forbidden")
                if s_u not in self._option_syms:
                    if len(self._option_syms) >= self.max_option_symbols:
                        raise AlpacaInputError(
                            f"Option WebSocket quote limit reached ({self.max_option_symbols})"
                        )
                    inst = self.registry.resolve_provider_symbol("alpaca", s_u)
                    if inst is None:
                        inst = next((i for i in self.registry.list_by_market(Market.US) if i.canonical_symbol == s_u), None)
                    if inst is None:
                        raise AlpacaInputError(f"Unknown US option symbol in registry: {s_u}")
                    self._option_syms[s_u] = inst.instrument_id
                    added.append(s_u)
            if ws is not None and added:
                ws.send(msgpack.packb({"action": "subscribe", "trades": added, "quotes": added}))
            return added

    def on_stock_message(self, raw_msg: str | bytes) -> List[USRealtimeEvent]:
        """Decode Alpaca v2 stock JSON frame and reconcile updated bars ('u') in place."""
        payload = json.loads(raw_msg.decode("utf-8") if isinstance(raw_msg, bytes) else raw_msg)
        items = payload if isinstance(payload, list) else [payload]
        now_dt = datetime.fromtimestamp(self._clock(), tz=UTC_TZ)
        out: List[USRealtimeEvent] = []

        with self._lock:
            for item in items:
                if not isinstance(item, dict):
                    continue
                t_code = item.get("T")
                sym = str(item.get("S") or "").strip().upper()
                iid = self._stock_syms.get(sym)
                if not iid:
                    continue
                ev_ts = _ts(item["t"])
                if t_code == "t":
                    ev = USRealtimeEvent(
                        instrument_id=iid,
                        provider_symbol=sym,
                        feed=self.stock_feed,
                        event_type="trade",
                        event_ts_utc=ev_ts,
                        received_at_utc=now_dt,
                        data_source="alpaca_ws_stocks",
                        price=Decimal(str(item["p"])),
                        size=int(item["s"]),
                    )
                    self._latest_trades[iid] = ev
                    out.append(ev)
                elif t_code == "q":
                    ev = USRealtimeEvent(
                        instrument_id=iid,
                        provider_symbol=sym,
                        feed=self.stock_feed,
                        event_type="quote",
                        event_ts_utc=ev_ts,
                        received_at_utc=now_dt,
                        data_source="alpaca_ws_stocks",
                        bid_price=Decimal(str(item["bp"])),
                        bid_size=int(item["bs"]),
                        ask_price=Decimal(str(item["ap"])),
                        ask_size=int(item["as"]),
                    )
                    self._latest_quotes[iid] = ev
                    out.append(ev)
                elif t_code in ("b", "d", "u"):
                    ev_type = "bar" if t_code == "b" else "daily_bar" if t_code == "d" else "updated_bar"
                    key = (iid, ev_ts)
                    prev = self._bars.get(key)
                    rev = (prev.revision_count + 1) if (t_code == "u" and prev is not None) else 0
                    ev = USRealtimeEvent(
                        instrument_id=iid,
                        provider_symbol=sym,
                        feed=self.stock_feed,
                        event_type=ev_type,
                        event_ts_utc=ev_ts,
                        received_at_utc=now_dt,
                        data_source="alpaca_ws_stocks",
                        open=Decimal(str(item["o"])),
                        high=Decimal(str(item["h"])),
                        low=Decimal(str(item["l"])),
                        close=Decimal(str(item["c"])),
                        volume=int(item["v"]),
                        revision_count=rev,
                    )
                    if t_code in ("b", "u"):
                        self._bars[key] = ev
                    out.append(ev)
        return out

    def on_option_message(self, raw_msg: bytes) -> List[USRealtimeEvent]:
        """Decode Alpaca v1beta1 option MessagePack frame."""
        if not isinstance(raw_msg, (bytes, bytearray)):
            raise AlpacaInputError("Option WebSocket messages must be MessagePack binary bytes")
        payload = msgpack.unpackb(raw_msg, raw=False)
        items = payload if isinstance(payload, list) else [payload]
        now_dt = datetime.fromtimestamp(self._clock(), tz=UTC_TZ)
        out: List[USRealtimeEvent] = []

        with self._lock:
            for item in items:
                if not isinstance(item, dict):
                    continue
                t_code = item.get("T")
                sym = str(item.get("S") or "").strip().upper()
                iid = self._option_syms.get(sym)
                if not iid:
                    continue
                ev_ts = _ts(item["t"])
                if t_code == "t":
                    ev = USRealtimeEvent(
                        instrument_id=iid,
                        provider_symbol=sym,
                        feed=self.option_feed,
                        event_type="trade",
                        event_ts_utc=ev_ts,
                        received_at_utc=now_dt,
                        data_source="alpaca_ws_options",
                        price=Decimal(str(item["p"])),
                        size=int(item["s"]),
                    )
                    self._latest_trades[iid] = ev
                    out.append(ev)
                elif t_code == "q":
                    ev = USRealtimeEvent(
                        instrument_id=iid,
                        provider_symbol=sym,
                        feed=self.option_feed,
                        event_type="quote",
                        event_ts_utc=ev_ts,
                        received_at_utc=now_dt,
                        data_source="alpaca_ws_options",
                        bid_price=Decimal(str(item["bp"])),
                        bid_size=int(item["bs"]),
                        ask_price=Decimal(str(item["ap"])),
                        ask_size=int(item["as"]),
                    )
                    self._latest_quotes[iid] = ev
                    out.append(ev)
        return out

    def get_reconciled_bar(self, instrument_id: str, bar_ts_utc: datetime) -> Optional[USRealtimeEvent]:
        with self._lock:
            return self._bars.get((instrument_id, bar_ts_utc.astimezone(UTC_TZ)))
