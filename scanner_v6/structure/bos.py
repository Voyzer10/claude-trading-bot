"""Break of structure (BOSEvent): the APPROVED V6 BOS rules only.

Approved rules implemented here:
  BOS-001 / D4  reference = the LATEST confirmed swing of that kind (swing high for a bullish BOS, swing low for a
                bearish BOS). Once a reference has produced its BOS there is no BOS of that kind until a newer swing
                of that kind confirms. No fall-back to older unbroken swings (the C3 'latest unbroken' reading is
                NOT implemented).
  BOS-002       a candle CLOSE strictly beyond the reference price (bullish: close > level; bearish: close < level).
                A wick alone is never a BOS.
  BOS-004       emitted at the close of the break candle k (index = confirmed_index = k).
  BOS-005       at most one BOS per reference swing id.
  Option A      independent of market-structure direction: continuation and counter-structure breaks are both BOS.
  D5            at the close of candle k, BOS is evaluated with the swings confirmed at or before k - 1 only. A swing
                confirmed at the close of k is first usable at k + 1.

NOT decided, so NOT assumed: gap / exact-level / tick rounding (BOS-006), close-back invalidation (BOS-007), session
gaps (O7). Raw prices are compared as given.

Research only: no orders, no broker, no live routing.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

from ..data.candle_models import Candle, CandleSeries
from ..models import BOSEvent, Direction, EventStamp, SwingKind, SwingPoint
from .swings import SwingConfig, SwingStream

RULE_ID = "latest-confirmed"


def bos_id(direction: Direction, reference: SwingPoint) -> str:
    """Stable id: one BOS per reference swing (BOS-005)."""
    return "bos:%s:%s" % (direction.value, reference.id)


class BOSStream:
    """Streaming BOS. Feed closed candles in order. on_candle(c) returns the BOS events at c's close.

    After each call, `new_swings` holds the swings confirmed at c's close (usable from the next candle), and
    `swings` holds every swing confirmed so far."""

    def __init__(self, config: Optional[SwingConfig] = None):
        self.swing_stream = SwingStream(config)
        self.swings: List[SwingPoint] = []
        self.new_swings: List[SwingPoint] = []
        self._latest: Dict[SwingKind, Optional[SwingPoint]] = {SwingKind.HIGH: None, SwingKind.LOW: None}
        self._used: Set[str] = set()
        self.candles: List[Candle] = []

    def latest(self, kind: SwingKind) -> Optional[SwingPoint]:
        return self._latest[kind]

    def on_candle(self, candle: Candle) -> List[BOSEvent]:
        out: List[BOSEvent] = []
        # (1) BOS from swings confirmed at or before k - 1 (D5)
        for kind, direction in ((SwingKind.HIGH, Direction.BULLISH), (SwingKind.LOW, Direction.BEARISH)):
            ref = self._latest[kind]
            if ref is None or ref.id in self._used:
                continue
            beyond = candle.close > ref.price if kind is SwingKind.HIGH else candle.close < ref.price
            if beyond:
                self._used.add(ref.id)
                out.append(BOSEvent(bos_id(direction, ref), EventStamp.from_candles(candle, candle),
                                    related=(ref.id,), direction=direction, level=ref.price,
                                    broken_swing_id=ref.id))
        # (4) swings confirmed at the close of k: usable from k + 1
        self.candles.append(candle)
        self.new_swings = self.swing_stream.on_candle(candle)
        for sw in self.new_swings:
            self.swings.append(sw)
            cur = self._latest[sw.kind]
            if cur is None or (sw.confirmed_index, sw.index) > (cur.confirmed_index, cur.index):
                self._latest[sw.kind] = sw
        return out


def detect_bos(series: CandleSeries, config: Optional[SwingConfig] = None) -> List[BOSEvent]:
    """Batch form: every BOS within `series`. Same events and ids as BOSStream at every prefix."""
    st = BOSStream(config)
    out: List[BOSEvent] = []
    for c in series:
        out.extend(st.on_candle(c))
    return out
