"""Live WebSocket bridge reusing kite_ticker binary decoding for canonical NIFTY/BANKNIFTY ticks."""
from __future__ import annotations

import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import kite_ticker as KT
from ..instruments import InstrumentRegistry
from .exceptions import KiteInputError

MAX_INSTRUMENTS_PER_CONNECTION = 3000
MAX_CONNECTIONS_PER_API_KEY = 3


@dataclass(frozen=True)
class DepthLevel:
    quantity: int
    price: Decimal
    orders: int


@dataclass(frozen=True)
class NormalizedTick:
    instrument_id: str
    instrument_token: int
    ltp: Decimal
    exchange_ts_utc: Optional[datetime]
    received_at_utc: datetime
    volume: Optional[int] = None
    oi: Optional[int] = None
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    close: Optional[Decimal] = None
    last_traded_quantity: Optional[int] = None
    average_traded_price: Optional[Decimal] = None
    buy_quantity: Optional[int] = None
    sell_quantity: Optional[int] = None
    oi_day_high: Optional[int] = None
    oi_day_low: Optional[int] = None
    last_traded_timestamp_utc: Optional[datetime] = None
    net_change: Optional[Decimal] = None
    depth_buy: Optional[Tuple[DepthLevel, ...]] = None
    depth_sell: Optional[Tuple[DepthLevel, ...]] = None


class KiteConnectionSlotRegistry:
    """In-process registry enforcing Kite's maximum 3 concurrent WebSocket connections per API key.

    Note:
        This registry only tracks ``KiteLiveBridge`` instances sharing the same in-process
        ``KiteConnectionSlotRegistry`` instance and does NOT enforce limits across separate OS
        processes. If the root-level ``kite_ticker.py`` WebSocket service is running separately
        for the same API key, it consumes 1 of the 3 allowed Kite WebSocket connections.
        ``KiteLiveBridge`` reuses ``kite_ticker.parse_binary`` rather than spawning a second
        WebSocket service.
    """

    def __init__(self, max_per_key: int = MAX_CONNECTIONS_PER_API_KEY) -> None:
        self.max_per_key = int(max_per_key)
        self._lock = threading.Lock()
        self._active: Dict[str, Set[int]] = {}

    def acquire(self, api_key: str, conn_id: int) -> None:
        with self._lock:
            slots = self._active.setdefault(api_key, set())
            if conn_id in slots:
                return
            if len(slots) >= self.max_per_key:
                raise KiteInputError(
                    f"Kite WebSocket connection limit reached ({self.max_per_key} connections per API key)"
                )
            slots.add(conn_id)

    def release(self, api_key: str, conn_id: int) -> None:
        with self._lock:
            slots = self._active.get(api_key)
            if slots:
                slots.discard(conn_id)
                if not slots:
                    self._active.pop(api_key, None)

    def active_count(self, api_key: str) -> int:
        with self._lock:
            return len(self._active.get(api_key, ()))


_DEFAULT_CONNECTION_REGISTRY = KiteConnectionSlotRegistry()


def _extract_raw_packets(buf: bytes) -> Dict[int, bytes]:
    """Slice Kite binary frame into {token: raw_packet_bytes} for extended full-packet fields."""
    if len(buf) < 2:
        return {}
    n = struct.unpack(">H", buf[:2])[0]
    out: Dict[int, bytes] = {}
    j = 2
    for _ in range(n):
        if j + 2 > len(buf):
            break
        ln = struct.unpack(">H", buf[j:j + 2])[0]
        p = buf[j + 2:j + 2 + ln]
        j += 2 + ln
        if len(p) >= 8:
            tok = struct.unpack(">I", p[:4])[0]
            out[tok] = p
    return out


class KiteLiveBridge:
    """Isolated read-only bridge between kite_ticker WebSocket binary frames and canonical instrument IDs.

    Reuses ``kite_ticker.parse_binary`` for binary packet decoding without duplicating the
    ``kite_ticker.py`` WebSocket service. Passing ``api_key`` registers this instance in an
    in-process ``KiteConnectionSlotRegistry`` (call ``close()`` to release the slot); cross-process
    connections such as a standalone ``kite_ticker.py`` daemon share the same 3-connection Kite
    API-key quota externally.
    """

    def __init__(
        self,
        *,
        registry: InstrumentRegistry,
        max_instruments: int = MAX_INSTRUMENTS_PER_CONNECTION,
        stale_after_seconds: float = 15.0,
        clock: Callable[[], float] = time.time,
        api_key: Optional[str] = None,
        connection_registry: Optional[KiteConnectionSlotRegistry] = None,
    ) -> None:
        if max_instruments < 1 or max_instruments > MAX_INSTRUMENTS_PER_CONNECTION:
            raise KiteInputError(f"max_instruments must be between 1 and {MAX_INSTRUMENTS_PER_CONNECTION}")
        self.registry = registry
        self.max_instruments = max_instruments
        self.stale_after_seconds = float(stale_after_seconds)
        self._clock = clock
        self.api_key = api_key
        self._conn_registry = connection_registry or _DEFAULT_CONNECTION_REGISTRY
        self._conn_acquired = False
        if self.api_key:
            self._conn_registry.acquire(self.api_key, id(self))
            self._conn_acquired = True
        self._lock = threading.RLock()
        self._token_to_id: Dict[int, str] = {}
        self._id_to_token: Dict[str, int] = {}
        self._subscribed_tokens: Set[int] = set()
        self._ticks: Dict[str, NormalizedTick] = {}
        self.reconnect_count: int = 0
        self.market_data_errors: List[str] = []

    def close(self) -> None:
        if self._conn_acquired and self.api_key:
            self._conn_registry.release(self.api_key, id(self))
            self._conn_acquired = False

    def subscribe(self, instrument_ids: Sequence[str], ws: Any = None) -> List[int]:
        """Resolve canonical IDs to verified tokens and subscribe (respecting 3000-instrument limit)."""
        with self._lock:
            added: List[int] = []
            for iid in instrument_ids:
                inst = self.registry.get(iid)
                if inst is None:
                    raise KiteInputError(f"Cannot subscribe unknown instrument_id: {iid}")
                tok = (inst.metadata or {}).get("instrument_token")
                if tok is None:
                    raise KiteInputError(f"Missing instrument_token for {iid}")
                tok_i = int(tok)
                if tok_i not in self._subscribed_tokens:
                    if len(self._subscribed_tokens) >= self.max_instruments:
                        raise KiteInputError(
                            f"Kite WebSocket limit reached ({self.max_instruments} instruments per connection)"
                        )
                    self._subscribed_tokens.add(tok_i)
                    self._token_to_id[tok_i] = iid
                    self._id_to_token[iid] = tok_i
                    added.append(tok_i)
            if ws is not None and added:
                import json
                ws.send(json.dumps({"a": "subscribe", "v": added}))
                ws.send(json.dumps({"a": "mode", "v": ["full", added]}))
            return added

    def unsubscribe(self, instrument_ids: Sequence[str], ws: Any = None) -> List[int]:
        with self._lock:
            removed: List[int] = []
            for iid in instrument_ids:
                tok_i = self._id_to_token.pop(iid, None)
                if tok_i is not None and tok_i in self._subscribed_tokens:
                    self._subscribed_tokens.remove(tok_i)
                    self._token_to_id.pop(tok_i, None)
                    self._ticks.pop(iid, None)
                    removed.append(tok_i)
            if ws is not None and removed:
                import json
                ws.send(json.dumps({"a": "unsubscribe", "v": removed}))
            return removed

    def on_reconnect(self, ws: Any = None) -> List[int]:
        """Handle WebSocket reconnect and re-subscribe active tokens."""
        with self._lock:
            self.reconnect_count += 1
            toks = sorted(self._subscribed_tokens)
            if ws is not None and toks:
                import json
                ws.send(json.dumps({"a": "subscribe", "v": toks}))
                ws.send(json.dumps({"a": "mode", "v": ["full", toks]}))
            return toks

    def on_binary_message(self, buf: bytes) -> List[NormalizedTick]:
        """Decode Kite binary WebSocket frame via kite_ticker.parse_binary into canonical NormalizedTicks."""
        now_s = self._clock()
        now_dt = datetime.fromtimestamp(now_s, tz=timezone.utc)
        parsed = KT.parse_binary(buf)
        raw_packets = _extract_raw_packets(buf)
        out: List[NormalizedTick] = []
        with self._lock:
            for raw in parsed:
                tok = int(raw["token"])
                iid = self._token_to_id.get(tok)
                if iid is None:
                    continue
                p = raw_packets.get(tok, b"")
                div_d = Decimal(str(int(KT._div(tok))))
                ex_ts = datetime.fromtimestamp(float(raw["t"]), tz=timezone.utc) if raw.get("t") else None

                ltq = avg_p = buy_q = sell_q = oi_hi = oi_lo = ltt_utc = net_chg = d_buy = d_sell = None
                if len(p) in (28, 32):
                    net_chg = Decimal(struct.unpack(">i", p[24:28])[0]) / div_d
                elif len(p) >= 44:
                    v = struct.unpack(">iiiIIIiiii", p[4:44])
                    ltq = int(v[1])
                    avg_p = Decimal(v[2]) / div_d
                    buy_q = int(v[4])
                    sell_q = int(v[5])
                    if len(p) >= 64:
                        ltt_raw = struct.unpack(">I", p[44:48])[0]
                        ltt_utc = datetime.fromtimestamp(ltt_raw, tz=timezone.utc) if ltt_raw > 0 else None
                        oi_hi = int(struct.unpack(">I", p[52:56])[0])
                        oi_lo = int(struct.unpack(">I", p[56:60])[0])
                    if len(p) >= 184:
                        levels: List[DepthLevel] = []
                        for off in range(64, 184, 12):
                            qty, price_i, orders = struct.unpack(">IiHxx", p[off:off + 12])
                            levels.append(DepthLevel(quantity=int(qty), price=Decimal(price_i) / div_d, orders=int(orders)))
                        d_buy = tuple(levels[:5])
                        d_sell = tuple(levels[5:10])

                nt = NormalizedTick(
                    instrument_id=iid,
                    instrument_token=tok,
                    ltp=Decimal(str(raw["ltp"])),
                    exchange_ts_utc=ex_ts,
                    received_at_utc=now_dt,
                    volume=int(raw["volume"]) if raw.get("volume") is not None else None,
                    oi=int(raw["oi"]) if raw.get("oi") is not None else None,
                    open=Decimal(str(raw["open"])) if raw.get("open") is not None else None,
                    high=Decimal(str(raw["high"])) if raw.get("high") is not None else None,
                    low=Decimal(str(raw["low"])) if raw.get("low") is not None else None,
                    close=Decimal(str(raw["close"])) if raw.get("close") is not None else None,
                    last_traded_quantity=ltq,
                    average_traded_price=avg_p,
                    buy_quantity=buy_q,
                    sell_quantity=sell_q,
                    oi_day_high=oi_hi,
                    oi_day_low=oi_lo,
                    last_traded_timestamp_utc=ltt_utc,
                    net_change=net_chg,
                    depth_buy=d_buy,
                    depth_sell=d_sell,
                )
                self._ticks[iid] = nt
                out.append(nt)
        return out

    def stale_instruments(self) -> List[str]:
        """Return subscribed instrument IDs with no tick or ticks older than stale_after_seconds."""
        now_s = self._clock()
        with self._lock:
            stale: List[str] = []
            for iid in sorted(self._id_to_token):
                t = self._ticks.get(iid)
                if t is None or (now_s - t.received_at_utc.timestamp()) > self.stale_after_seconds:
                    stale.append(iid)
            return stale

    def latest_tick(self, instrument_id: str) -> Optional[NormalizedTick]:
        with self._lock:
            return self._ticks.get(instrument_id)
