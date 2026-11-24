"""Scanner V6 data structures: swing points, structure events (BOS / CHoCH), liquidity pools, sweeps and reclaims.

These are containers only. They record WHERE an event happened (source candle index and time), WHEN it became known
(confirmation candle index and time) and WHICH other events it relates to (ids). They hold no trading rule: nothing
here decides what a valid swing, BOS, CHoCH, pool, sweep or reclaim is. Those rules are written later, one concept at
a time, in the structure / liquidity / entry / exit modules.

Index rules enforced here (data integrity, not strategy):
  - every index is a non-negative int; every timestamp is timezone-aware (stored as UTC)
  - confirmed_index >= index, and confirmed_ts >= ts when both are given
  - an event's id is a non-empty string; related ids never include the event's own id
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from .data.candle_models import Candle, CandleError, CandleSeries, to_utc  # noqa: F401  (re-exported)


class ModelError(ValueError):
    """A model that breaks an integrity rule (not a trading rule)."""


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class SwingKind(str, Enum):
    HIGH = "high"
    LOW = "low"


class PoolSide(str, Enum):
    """Where resting liquidity sits relative to price: ABOVE (buy-stops over highs) or BELOW (sell-stops under lows)."""
    ABOVE = "above"
    BELOW = "below"


def _check_index(name: str, v) -> None:
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ModelError("%s must be a non-negative int, got %r" % (name, v))


def _check_price(name: str, v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ModelError("%s must be a finite number, got %r" % (name, v))
    return float(v)


@dataclass(frozen=True)
class EventStamp:
    """Where an event comes from and when it became known.

    index / ts:                     the candle the event is about (e.g. the candle that formed a swing)
    confirmed_index / confirmed_ts: the candle at whose CLOSE the event is first known; None = not confirmed yet.
    A detector may only report an event at candle k if confirmed_index <= k (see engine.no_lookahead_violations)."""
    index: int
    ts: datetime
    confirmed_index: Optional[int] = None
    confirmed_ts: Optional[datetime] = None

    def __post_init__(self) -> None:
        _check_index("index", self.index)
        try:
            object.__setattr__(self, "ts", to_utc(self.ts))
            if self.confirmed_ts is not None:
                object.__setattr__(self, "confirmed_ts", to_utc(self.confirmed_ts))
        except CandleError as e:
            raise ModelError(str(e)) from None
        if self.confirmed_index is not None:
            _check_index("confirmed_index", self.confirmed_index)
            if self.confirmed_index < self.index:
                raise ModelError("confirmed_index %d is before index %d" % (self.confirmed_index, self.index))
        if self.confirmed_ts is not None:
            if self.confirmed_index is None:
                raise ModelError("confirmed_ts given without confirmed_index")
            if self.confirmed_ts < self.ts:
                raise ModelError("confirmed_ts %s is before ts %s" % (self.confirmed_ts, self.ts))

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_index is not None

    def known_at(self, k: int) -> bool:
        """True if the event is confirmed at or before the close of candle k."""
        return self.confirmed_index is not None and self.confirmed_index <= k

    @classmethod
    def from_candles(cls, source: Candle, confirmed: Optional[Candle] = None) -> "EventStamp":
        return cls(source.index, source.ts, confirmed.index if confirmed else None, confirmed.ts if confirmed else None)


@dataclass(frozen=True)
class Event:
    """Common fields of every V6 event. `related` holds the ids of the events this one refers to (e.g. a sweep's
    pool, a reclaim's sweep); what those links mean is defined by each concept module, not here."""
    id: str
    stamp: EventStamp
    related: Tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ModelError("event id must be a non-empty string")
        if not isinstance(self.stamp, EventStamp):
            raise ModelError("stamp must be an EventStamp")
        rel = tuple(self.related)
        if any(not isinstance(r, str) or not r for r in rel):
            raise ModelError("related ids must be non-empty strings")
        if self.id in rel:
            raise ModelError("event %s lists itself as related" % self.id)
        object.__setattr__(self, "related", rel)

    @property
    def index(self) -> int:
        return self.stamp.index

    @property
    def confirmed_index(self) -> Optional[int]:
        return self.stamp.confirmed_index


@dataclass(frozen=True)
class SwingPoint(Event):
    """A swing high or low at `price`. How swings are found is not defined here."""
    kind: SwingKind = SwingKind.HIGH
    price: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.kind, SwingKind):
            raise ModelError("kind must be a SwingKind")
        object.__setattr__(self, "price", _check_price("price", self.price))


@dataclass(frozen=True)
class StructureEvent(Event):
    """A market-structure event: a `level` (price) taken out in `direction`. `broken_swing_id` names the swing
    whose level it was, when there is one."""
    direction: Direction = Direction.BULLISH
    level: float = 0.0
    broken_swing_id: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.direction, Direction):
            raise ModelError("direction must be a Direction")
        object.__setattr__(self, "level", _check_price("level", self.level))
        if self.broken_swing_id is not None and (not isinstance(self.broken_swing_id, str) or not self.broken_swing_id):
            raise ModelError("broken_swing_id must be a non-empty string or None")


@dataclass(frozen=True)
class BOSEvent(StructureEvent):
    """Break of structure. The rule that makes a break a BOS is defined in structure/bos.py (not yet written)."""


@dataclass(frozen=True)
class CHoCHEvent(StructureEvent):
    """Change of character. The rule is defined in structure/choch.py (not yet written)."""


@dataclass(frozen=True)
class LiquidityPool(Event):
    """Resting liquidity at `price`, ABOVE or BELOW price. `related` may hold the swing / structure ids it came
    from. What counts as a pool is defined in liquidity/liquidity_pools.py (not yet written)."""
    side: PoolSide = PoolSide.BELOW
    price: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.side, PoolSide):
            raise ModelError("side must be a PoolSide")
        object.__setattr__(self, "price", _check_price("price", self.price))


@dataclass(frozen=True)
class SweepEvent(Event):
    """`pool_id` was taken: price traded through `level`, reaching `extreme`. Whether a wick or a close counts is
    defined in liquidity/sweep.py (not yet written)."""
    pool_id: str = ""
    level: float = 0.0
    extreme: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.pool_id, str) or not self.pool_id:
            raise ModelError("pool_id must be a non-empty string")
        if self.pool_id == self.id:
            raise ModelError("a sweep cannot be its own pool")
        object.__setattr__(self, "level", _check_price("level", self.level))
        object.__setattr__(self, "extreme", _check_price("extreme", self.extreme))


@dataclass(frozen=True)
class ReclaimEvent(Event):
    """Price came back across the swept `level` after `sweep_id`. The rule is defined in liquidity/reclaim.py (not
    yet written)."""
    sweep_id: str = ""
    level: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.sweep_id, str) or not self.sweep_id:
            raise ModelError("sweep_id must be a non-empty string")
        if self.sweep_id == self.id:
            raise ModelError("a reclaim cannot be its own sweep")
        object.__setattr__(self, "level", _check_price("level", self.level))


def check_stamp_against(series: CandleSeries, ev: Event) -> None:
    """Integrity check of an event against the series it came from: its indices exist, and its timestamps are the
    timestamps of those candles. Raises ModelError."""
    st = ev.stamp
    for name, i in (("index", st.index), ("confirmed_index", st.confirmed_index)):
        if i is not None and i >= len(series):
            raise ModelError("%s %s: %s %d is outside the series (0..%d)" % (type(ev).__name__, ev.id, name, i,
                                                                             len(series) - 1))
    if series[st.index].ts != st.ts:
        raise ModelError("%s %s: ts %s is not candle %d's time %s" % (type(ev).__name__, ev.id, st.ts.isoformat(),
                                                                       st.index, series[st.index].ts.isoformat()))
    if st.confirmed_ts is not None and series[st.confirmed_index].ts != st.confirmed_ts:
        raise ModelError("%s %s: confirmed_ts is not candle %d's time" % (type(ev).__name__, ev.id,
                                                                          st.confirmed_index))
