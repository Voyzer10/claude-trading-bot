"""Protected swings: decision D2 (P-B), approved by the owner on 22 Nov 2026.

  Origin.     For a bullish BOS at candle k against swing high SH_r, the origin is the LOWEST confirmed swing low with
              index in (SH_r.index, k]. Bearish is the mirror: the HIGHEST confirmed swing high.
  A5.         The origin must be an HL (a bearish origin an LH) relative to the previous confirmed swing of the same
              kind. Otherwise it is not protected.
  Activation. Protected ONLY after its own L2/R2 confirmation. Until then the previous valid protected swing is
              kept. Activation happens in step (4) of a candle (D5), so it is in force from the next candle.
  Replace.    A qualifying origin of a later BOS (higher k) replaces the earlier one.
  No origin.  A BOS leg with no confirmed swing of the needed kind leaves the protected swing unchanged.
  Consumed.   choch.py marks a protected swing consumed when a close goes beyond it (one CHoCH per protected id).

Research only: no orders, no broker, no live routing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..models import BOSEvent, Direction, SwingKind, SwingPoint


@dataclass
class _Pending:
    bos_id: str
    direction: Direction
    ref_index: int
    bos_index: int
    origin: Optional[SwingPoint] = None


@dataclass(frozen=True)
class OriginNote:
    """A diagnostic about an origin (not an Event): ACTIVATED, NOT_QUALIFIED (fails A5), or NO_ORIGIN_SWING."""
    index: int
    code: str
    bos_id: str
    swing_id: Optional[str]
    detail: str


class ProtectedTracker:
    """Tracks the active BOS-origin swing for each direction under P-B."""

    def __init__(self, right: int = 2):
        self.right = right
        self._pending: List[_Pending] = []
        self.active: Dict[Direction, Optional[Tuple[int, SwingPoint, str]]] = {Direction.BULLISH: None,
                                                                                Direction.BEARISH: None}
        self.notes: List[OriginNote] = []

    def on_bos(self, bos: BOSEvent, reference: SwingPoint) -> None:
        self._pending.append(_Pending(bos.id, bos.direction, reference.index, bos.index))

    @staticmethod
    def _need(direction: Direction) -> SwingKind:
        return SwingKind.LOW if direction is Direction.BULLISH else SwingKind.HIGH

    def on_close(self, k: int, swings: List[SwingPoint]) -> None:
        """Step (4) at the close of candle k. `swings` = every swing confirmed at or before k."""
        keep = []
        for p in self._pending:
            kind = self._need(p.direction)
            cands = [s for s in swings if s.kind is kind and p.ref_index < s.index <= p.bos_index]
            if cands:
                o = min(cands, key=lambda s: s.price) if kind is SwingKind.LOW else max(cands, key=lambda s: s.price)
                if p.origin is None or o.id != p.origin.id:
                    p.origin = o
                    prev = [s for s in swings if s.kind is kind and s.index < o.index]
                    prev_s = max(prev, key=lambda s: s.index) if prev else None
                    ok = prev_s is not None and (o.price > prev_s.price if kind is SwingKind.LOW else o.price < prev_s.price)
                    if not ok:
                        self.notes.append(OriginNote(k, "NOT_QUALIFIED", p.bos_id, o.id,
                                                     "origin %s is not an %s (A5)" % (o.price, "HL" if kind is SwingKind.LOW else "LH")))
                    else:
                        cur = self.active[p.direction]
                        if cur is None or p.bos_index >= cur[0]:
                            self.active[p.direction] = (p.bos_index, o, p.bos_id)
                            self.notes.append(OriginNote(k, "ACTIVATED", p.bos_id, o.id,
                                                         "protected %s %s activated at the close of index %d, in force from index %d" % (kind.value, o.price, k, k + 1)))
            if k >= p.bos_index + self.right:
                if p.origin is None:
                    self.notes.append(OriginNote(k, "NO_ORIGIN_SWING", p.bos_id, None,
                                                 "no confirmed %s swing in the BOS leg; protected unchanged" % kind.value))
                continue
            keep.append(p)
        self._pending = keep

    def protected(self, direction: Direction, min_bos_index: int, consumed) -> Optional[SwingPoint]:
        """The protected swing in force for a `direction` structure: the active origin of a BOS at or after
        min_bos_index that has not been consumed."""
        a = self.active[direction]
        if a is None or a[0] < min_bos_index or a[1].id in consumed:
            return None
        return a[1]
