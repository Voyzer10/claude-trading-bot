"""Swing highs and lows (SwingPoint events): the APPROVED V6 baseline profile only (owner approval, 21 Nov 2026).

Approved rules implemented here:
  SW-001  fixed left/right window
  SW-002  L = 2, R = 2 by default; both configurable (>= 1)
  SW-003  strict comparison: a swing high's high is GREATER than every high in its left and right windows; a swing
          low's low is LOWER than every low in both windows. Never silently relaxed to >= / <=.
  SW-004  equal highs / lows are kept apart from unique pivots: a bar that fails ONLY because of an equal neighbour is
          not a swing. It is reported, as a diagnostic (not an event), by unresolved_equal_levels(). Cluster
          formation, tolerance and cluster confirmation are NOT implemented (equal_levels must be "unresolved").
  SW-005  a candle may be both a swing high and a swing low when each passes independently.

Timing: a swing at candle i is confirmed at the close of candle i + R: event index i, confirmed index i + R. Nothing
is emitted before that, and an emitted swing never changes.

NOT decided, so NOT assumed beyond the literal fixed-window definition (see UNRESOLVED_DECISIONS.md):
  - initial history: a candidate needs a FULL left window of L candles (the literal fixed window); a partial-window
    alternative is not implemented.
  - missing candles / session gaps: windows count candles as given; no time-based rule.
  - outside-bar event order: two swings on one candle are returned sorted by id (deterministic, not a priority rule).
  - tick size / rounding: raw prices are compared as given.
  - hierarchy, invalidation / replacement: not implemented.

Research only: no orders, no broker, no live routing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..data.candle_models import Candle, CandleSeries
from ..models import EventStamp, SwingKind, SwingPoint

PROFILE_ID = "fixed-window-strict"


@dataclass(frozen=True)
class SwingConfig:
    """The approved baseline: L = R = 2, strict comparison, equal levels unresolved."""
    left: int = 2
    right: int = 2
    equal_levels: str = "unresolved"

    def __post_init__(self) -> None:
        for name in ("left", "right"):
            v = getattr(self, name)
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise ValueError("%s window must be an int >= 1, got %r" % (name, v))
        if self.equal_levels != "unresolved":
            raise NotImplementedError("equal-level clusters are not approved (SW-004): only 'unresolved' is allowed")

    @property
    def tag(self) -> str:
        return "L%dR%d" % (self.left, self.right)


@dataclass(frozen=True)
class EqualLevelCandidate:
    """Diagnostic only (not an Event): a bar that would be a pivot if ties were allowed, because it is >= (<= for
    lows) every bar in its windows but EQUAL to at least one. No cluster, tolerance or confirmation is implied."""
    kind: SwingKind
    index: int
    price: float
    tied_with: tuple
    window_closed_index: int


def swing_id(kind: SwingKind, index: int, config: SwingConfig) -> str:
    """Stable id: depends only on the kind, the source candle and the profile (not on run order)."""
    return "swing:%s:%d:%s:%s" % (kind.value, index, PROFILE_ID, config.tag)


def _value(c: Candle, kind: SwingKind) -> float:
    return c.high if kind is SwingKind.HIGH else c.low


def _beats(p: float, q: float, kind: SwingKind) -> bool:
    return p > q if kind is SwingKind.HIGH else p < q      # strict (SW-003)


def _check(candles, i: int, kind: SwingKind, cfg: SwingConfig):
    """(is_unique_pivot, tied_indices). Uses only candles i - L .. i + R; the caller guarantees they exist."""
    p = _value(candles[i], kind)
    tied = []
    for j in list(range(i - cfg.left, i)) + list(range(i + 1, i + cfg.right + 1)):
        q = _value(candles[j], kind)
        if _beats(p, q, kind):
            continue
        if p == q:
            tied.append(j)
            continue
        return False, None                                  # a strictly more extreme bar: not a pivot of any kind
    return (not tied), tuple(tied)


def _evaluate(candles, i: int, cfg: SwingConfig) -> List[SwingPoint]:
    """Swings with source candle i, given that candles i - L .. i + R are closed."""
    out = []
    for kind in (SwingKind.HIGH, SwingKind.LOW):
        unique, _ = _check(candles, i, kind, cfg)
        if unique:
            c, k = candles[i], candles[i + cfg.right]
            out.append(SwingPoint(swing_id(kind, i, cfg), EventStamp.from_candles(c, k), kind=kind,
                                  price=_value(c, kind)))
    return sorted(out, key=lambda e: e.id)


def detect_swings(series: CandleSeries, config: Optional[SwingConfig] = None) -> List[SwingPoint]:
    """Batch form: every swing confirmed within `series` (candles 0..n-1). Candidates whose right window has not
    closed yet (the last R candles) are not evaluated, so a prefix never sees the future."""
    cfg = config or SwingConfig()
    n = len(series)
    out: List[SwingPoint] = []
    for i in range(cfg.left, n - cfg.right):
        out.extend(_evaluate(series, i, cfg))
    return out


class SwingStream:
    """Streaming form: feed closed candles in order; on_candle(c) returns the swings confirmed at c's close (source
    candle c.index - R). Same results and ids as detect_swings at every prefix."""

    def __init__(self, config: Optional[SwingConfig] = None):
        self.cfg = config or SwingConfig()
        self._candles: List[Candle] = []

    def on_candle(self, candle: Candle) -> List[SwingPoint]:
        if not isinstance(candle, Candle):
            raise TypeError("on_candle needs a Candle")
        if candle.index != len(self._candles):
            raise ValueError("candle index %d out of order (expected %d)" % (candle.index, len(self._candles)))
        if self._candles and candle.ts <= self._candles[-1].ts:
            raise ValueError("candle %d is not after the previous candle" % candle.index)
        self._candles.append(candle)
        i = candle.index - self.cfg.right
        if i < self.cfg.left:
            return []
        return _evaluate(self._candles, i, self.cfg)


def unresolved_equal_levels(series: CandleSeries, config: Optional[SwingConfig] = None) -> List[EqualLevelCandidate]:
    """Diagnostic list of equal-level candidates (SW-004 kept apart from unique pivots). Not events; no cluster rule."""
    cfg = config or SwingConfig()
    out = []
    for i in range(cfg.left, len(series) - cfg.right):
        for kind in (SwingKind.HIGH, SwingKind.LOW):
            unique, tied = _check(series, i, kind, cfg)
            if not unique and tied:
                out.append(EqualLevelCandidate(kind, i, _value(series[i], kind), tied, i + cfg.right))
    return out
