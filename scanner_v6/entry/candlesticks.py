"""Module C: candlestick formation DETECTION (spec Section 16 + 17.P IR-2/IR-3 + 17.Q OQ-14). PAPER / RESEARCH ONLY.

Implemented from OWNER APPROVED rules only:
  16.B        geometry R, B, UW, LW, BodyRatio, UpperRatio, LowerRatio, CloseLocation; R == 0 exactly -> UNSCORABLE (no division); a positive R, however small, is scored
  16.C / 16.D the 10 canonical families with the approved baseline thresholds (configurable, CandlestickConfig)
  CS-1, CK-4  Inverted Hammer / Shooting Star / Hammer / Hanging Man need a preceding trend; without it the shape is still
              detected with the contextual label UNCLASSIFIED_SHAPE (never a pattern type, OQ-14 rule 4)
  CS-2        every valid family is emitted; no priority, no suppression (e.g. Dragonfly Doji + Hammer on one candle)
  CS-3, CK-5  bias BULLISH_BIAS / BEARISH_BIAS / NEUTRAL; bias is not a BUY / SELL signal
  CS-4        a wick is present only when wick > 0, compared EXACTLY (no epsilon: the tolerance never creates or
              removes a wick)
  CS-5, CK-1, CK-3  trend context: mean close of the 5 candles before the pattern minus mean close of the 5 before
              those, D > 2 x TickSize -> UPTREND (BULLISH), D < -2 x TickSize -> DOWNTREND (BEARISH), else SIDEWAYS
              (NEUTRAL); fewer than 10 earlier candles or no tick size -> UNKNOWN. Pattern candles are excluded.
  CS-6        Engulfing: inclusive body boundaries, wick engulfment not needed, a Doji (C == O) is neither bullish nor
              bearish, no trend condition. CS-8 pattern range kept as pattern_high / pattern_low (for Module D).
  CK-1, CK-8  OHLC_COMPARISON_EPSILON = TickSize x 0.000001 on the threshold, candle-colour, engulfing-boundary, star
              midpoint and trend-threshold comparisons (never on wick presence or zero range);
              tick size missing -> every evaluation UNSCORABLE (no fallback). Original OHLC never changed.
  CK-2, OQ-14 pattern:<instrument>:<timeframe>:<start_candle>:<pattern_type>, family token only, zero-based
  16.G / 16.H / CS-10  status DETECTED only. Confirmation, expiry and invalidation are Module D (entry/confirmation.py).

Delegated decisions UQ-C1..UQ-C4 (OWNER APPROVED — DELEGATED DECISION, 24 Nov 2026; spec 17.T):
  * UQ-C1  Inverted Hammer and Shooting Star share one shape: DOWNTREND -> INVERTED_HAMMER, UPTREND -> SHOOTING_STAR,
           SIDEWAYS / UNKNOWN -> both families retained with label UNCLASSIFIED_SHAPE, each with its own family bias.
  * UQ-C2  HAMMER_HANGING_MAN with label UNCLASSIFIED_SHAPE has bias UNDETERMINED.
  * UQ-C3  the CK-1 epsilon applies to the trend neutral-threshold comparison (D > threshold + eps -> UPTREND,
           D < -threshold - eps -> DOWNTREND, else SIDEWAYS).
  * UQ-C4  Engulfing bias follows its bullish / bearish direction.
Implementation choices (not trading rules):
  * Thresholds are compared in price units: e.g. Doji is B <= 0.10 x R + eps (equivalent to BodyRatio <= 0.10 without
    dividing). Inclusive a <= b -> a <= b + eps; a >= b -> a >= b - eps; strict a > b -> a > b + eps; a < b -> a < b - eps.
  * Within one candle the events follow the 16.A family order.
No BUY / SELL, no order, no confirmation, no setup lifecycle.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from scanner_v6.data.candle_models import Candle, CandleSeries
from scanner_v6.data.market_config import MarketDataConfig, TickSizeStatus
from scanner_v6.models import Event, EventStamp, ModelError

# canonical family tokens (OQ-14), in 16.A order
CLASSIC_DOJI = "CLASSIC_DOJI"
GRAVESTONE_DOJI = "GRAVESTONE_DOJI"
LONG_LEGGED_DOJI = "LONG_LEGGED_DOJI"
INVERTED_HAMMER = "INVERTED_HAMMER"
DRAGONFLY_DOJI = "DRAGONFLY_DOJI"
HAMMER_HANGING_MAN = "HAMMER_HANGING_MAN"
ENGULFING = "ENGULFING"
SHOOTING_STAR = "SHOOTING_STAR"
MORNING_STAR = "MORNING_STAR"
EVENING_STAR = "EVENING_STAR"
PATTERN_TYPES = (CLASSIC_DOJI, GRAVESTONE_DOJI, LONG_LEGGED_DOJI, INVERTED_HAMMER, DRAGONFLY_DOJI, HAMMER_HANGING_MAN,
                 ENGULFING, SHOOTING_STAR, MORNING_STAR, EVENING_STAR)
CANDLES = {ENGULFING: 2, MORNING_STAR: 3, EVENING_STAR: 3}            # all other families: 1

# labels (event attribute, never part of the id)
HAMMER = "HAMMER"
HANGING_MAN = "HANGING_MAN"
BULLISH_ENGULFING = "BULLISH_ENGULFING"
BEARISH_ENGULFING = "BEARISH_ENGULFING"
UNCLASSIFIED_SHAPE = "UNCLASSIFIED_SHAPE"

# bias (CS-3, CK-5) and direction terminology (CK-3)
BULLISH_BIAS = "BULLISH_BIAS"
BEARISH_BIAS = "BEARISH_BIAS"
NEUTRAL = "NEUTRAL"
UNDETERMINED = "UNDETERMINED"
BIAS_DIRECTION = {BULLISH_BIAS: "BULLISH", BEARISH_BIAS: "BEARISH", NEUTRAL: "NEUTRAL", UNDETERMINED: "UNDETERMINED"}

UPTREND, DOWNTREND, SIDEWAYS, UNKNOWN = "UPTREND", "DOWNTREND", "SIDEWAYS", "UNKNOWN"
CONTEXT_DIRECTION = {UPTREND: "BULLISH", DOWNTREND: "BEARISH", SIDEWAYS: "NEUTRAL", UNKNOWN: "UNKNOWN"}   # CK-3

DETECTED = "DETECTED"            # the only pattern status Module C emits (16.G / CS-10)
SCORED = "SCORED"
UNSCORABLE = "UNSCORABLE"
MISSING_TICK_SIZE = "MISSING_TICK_SIZE"
ZERO_RANGE = "ZERO_RANGE"
ZERO_RANGE_IN_WINDOW = "ZERO_RANGE_IN_WINDOW"


class CandlestickConfigError(ValueError):
    pass


@dataclass(frozen=True)
class CandlestickConfig:
    """Approved initial baseline (16.C, 16.D, CK-1); every value is configurable per instrument. Tick size is NOT here:
    it comes from the instrument's MarketDataConfig (CK-1, IR-3), with no default."""
    doji_body_max: float = 0.10
    small_body_max: float = 0.30
    large_body_min: float = 0.60
    dominant_wick_multiple: float = 2.0
    small_opposite_wick_max: float = 0.10
    gravestone_upper_min: float = 0.60
    gravestone_lower_max: float = 0.10
    long_legged_wick_min: float = 0.25
    dragonfly_lower_min: float = 0.60
    dragonfly_upper_max: float = 0.10
    epsilon_multiplier: float = 0.000001
    neutral_threshold_ticks: float = 2.0
    recent_window: int = 5
    previous_window: int = 5

    def __post_init__(self) -> None:
        for k, v in self.__dict__.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                raise CandlestickConfigError("%s must be a finite non-negative number, got %r" % (k, v))
        for k in ("recent_window", "previous_window"):
            if not isinstance(getattr(self, k), int) or getattr(self, k) < 1:
                raise CandlestickConfigError("%s must be a positive int" % k)


@dataclass(frozen=True)
class Geometry:
    """16.B for one candle. Ratios are None when the candle is UNSCORABLE (R == 0 exactly, or no tick size): nothing
    is divided or fabricated."""
    index: int
    range: float
    body: float
    upper_wick: float
    lower_wick: float
    body_ratio: Optional[float]
    upper_ratio: Optional[float]
    lower_ratio: Optional[float]
    close_location: Optional[float]
    status: str
    reason: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return dict(index=self.index, range=self.range, body=self.body, upper_wick=self.upper_wick,
                    lower_wick=self.lower_wick, body_ratio=self.body_ratio, upper_ratio=self.upper_ratio,
                    lower_ratio=self.lower_ratio, close_location=self.close_location, status=self.status,
                    reason=self.reason)


@dataclass(frozen=True)
class TrendContext:
    context: str                 # UPTREND / DOWNTREND / SIDEWAYS / UNKNOWN
    direction: str               # CK-3 terminology
    d: Optional[float]           # recent mean close - previous mean close
    threshold: Optional[float]
    candles: Tuple[int, ...]     # indices used (pattern candles never included)
    reason: Optional[str] = None


@dataclass(frozen=True)
class PatternEvent(Event):
    """A DETECTED candlestick formation. stamp.index = start candle, stamp.confirmed_index = end (detection) candle:
    the pattern is known only after the end candle closes."""
    instrument: str = ""
    timeframe: str = ""
    pattern_type: str = ""
    pattern_label: str = ""
    bias: str = NEUTRAL
    direction: str = "NEUTRAL"
    start_candle: int = 0
    end_candle: int = 0
    pattern_high: float = 0.0
    pattern_low: float = 0.0
    geometry: Tuple[Geometry, ...] = field(default_factory=tuple)
    trend: Optional[TrendContext] = None
    context_qualified: bool = False         # True when the required preceding trend is present (CS-1)
    status: str = DETECTED
    evaluation_status: str = SCORED
    reasons: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.pattern_type not in PATTERN_TYPES:
            raise ModelError("unknown pattern_type %r" % (self.pattern_type,))
        if self.status != DETECTED:
            raise ModelError("Module C emits DETECTED patterns only")
        if not (0 <= self.start_candle <= self.end_candle) or self.end_candle - self.start_candle + 1 != CANDLES.get(
                self.pattern_type, 1):
            raise ModelError("bad candle span for %s" % self.pattern_type)
        if self.id != pattern_id(self.instrument, self.timeframe, self.start_candle, self.pattern_type):
            raise ModelError("pattern id does not follow CK-2 / OQ-14")


@dataclass(frozen=True)
class EvaluationRecord:
    """Why a family could not be evaluated at an end candle (UNSCORABLE), so nothing is silently skipped."""
    end_candle: int
    pattern_type: Optional[str]    # None = the whole candle (every family)
    status: str
    reason: str
    candles: Tuple[int, ...]


def _token(name: str, v) -> str:
    if not isinstance(v, str) or not v or ":" in v or v != v.strip():
        raise CandlestickConfigError("%s must be a non-empty identifier without ':' (canonical set OPEN, B-7), got %r"
                                     % (name, v))
    return v


def pattern_id(instrument: str, timeframe: str, start_candle: int, pattern_type: str) -> str:
    """CK-2 / OQ-14: pattern:<instrument>:<timeframe>:<start_candle>:<pattern_type> (zero-based, family token)."""
    if pattern_type not in PATTERN_TYPES:
        raise ValueError("unknown pattern_type %r" % (pattern_type,))
    if isinstance(start_candle, bool) or not isinstance(start_candle, int) or start_candle < 0:
        raise ValueError("start_candle must be a non-negative int")
    return "pattern:%s:%s:%d:%s" % (_token("instrument", instrument), _token("timeframe", timeframe), start_candle,
                                    pattern_type)


class _Cmp:
    """CK-1 / CK-8 tolerant comparisons in price units. eps = TickSize x epsilon_multiplier."""

    def __init__(self, eps: float):
        self.eps = eps

    def le(self, a: float, b: float) -> bool:
        return a <= b + self.eps

    def ge(self, a: float, b: float) -> bool:
        return a >= b - self.eps

    def gt(self, a: float, b: float) -> bool:
        return a > b + self.eps

    def lt(self, a: float, b: float) -> bool:
        return a < b - self.eps


def geometry(c: Candle, cmp: Optional[_Cmp]) -> Geometry:
    """16.B. Without a tick size (cmp None) the candle is UNSCORABLE (CK-1). The zero-range condition is R == 0
    exactly (16.B); a positive range smaller than the epsilon is still a valid, scored candle."""
    r = c.high - c.low
    b = abs(c.close - c.open)
    uw = c.high - max(c.open, c.close)
    lw = min(c.open, c.close) - c.low
    if cmp is None:
        return Geometry(c.index, r, b, uw, lw, None, None, None, None, UNSCORABLE, MISSING_TICK_SIZE)
    if r == 0.0:
        return Geometry(c.index, r, b, uw, lw, None, None, None, None, UNSCORABLE, ZERO_RANGE)
    return Geometry(c.index, r, b, uw, lw, b / r, uw / r, lw / r, (c.close - c.low) / r, SCORED)


class CandlestickStream:
    """Feed completed candles in order. on_candle(c) returns the PatternEvents whose END candle is c (known at c's
    close). Uses only candles 0..c.index. Same output as detect_candlestick_patterns at every prefix."""

    def __init__(self, instrument: str, timeframe: str, market: MarketDataConfig,
                 config: Optional[CandlestickConfig] = None):
        self.instrument = _token("instrument", instrument)
        self.timeframe = _token("timeframe", timeframe)
        if not isinstance(market, MarketDataConfig):
            raise CandlestickConfigError("market must be a MarketDataConfig (tick size source, CK-1)")
        self.config = config if config is not None else CandlestickConfig()
        if not isinstance(self.config, CandlestickConfig):
            raise CandlestickConfigError("config must be a CandlestickConfig")
        ts = market.tick_size_result()
        self.tick_size = ts.value if ts.status is TickSizeStatus.AVAILABLE else None
        self.cmp = _Cmp(self.tick_size * self.config.epsilon_multiplier) if self.tick_size is not None else None
        self.threshold = self.config.neutral_threshold_ticks * self.tick_size if self.tick_size is not None else None
        self.candles: List[Candle] = []
        self.geoms: List[Geometry] = []
        self.patterns: List[PatternEvent] = []
        self.evaluations: List[EvaluationRecord] = []
        self._ids = set()

    # ---------------------------------------------------------------- context (CS-5, CK-1, CK-3)
    def trend(self, start: int) -> TrendContext:
        n_r, n_p = self.config.recent_window, self.config.previous_window
        if self.tick_size is None:
            return TrendContext(UNKNOWN, CONTEXT_DIRECTION[UNKNOWN], None, None, (), MISSING_TICK_SIZE)
        if start < n_r + n_p:
            return TrendContext(UNKNOWN, CONTEXT_DIRECTION[UNKNOWN], None, self.threshold, (), "INSUFFICIENT_HISTORY")
        recent = self.candles[start - n_r:start]                 # pattern candles (>= start) never included
        prev = self.candles[start - n_r - n_p:start - n_r]
        d = math.fsum(c.close for c in recent) / n_r - math.fsum(c.close for c in prev) / n_p
        # UQ-C3 (delegated decision): CK-1 epsilon on the CS-5 "within the threshold" comparison
        ctx = UPTREND if self.cmp.gt(d, self.threshold) else DOWNTREND if self.cmp.lt(d, -self.threshold) else SIDEWAYS
        return TrendContext(ctx, CONTEXT_DIRECTION[ctx], d, self.threshold,
                            tuple(c.index for c in prev) + tuple(c.index for c in recent))

    # ---------------------------------------------------------------- per-candle shape tests (16.C / 16.D)
    def _doji(self, g: Geometry) -> bool:
        return self.cmp.le(g.body, self.config.doji_body_max * g.range)

    def _small(self, g: Geometry) -> bool:
        return self.cmp.le(g.body, self.config.small_body_max * g.range)

    def _large(self, g: Geometry) -> bool:
        return self.cmp.ge(g.body, self.config.large_body_min * g.range)

    def _bull(self, c: Candle) -> bool:
        return self.cmp.gt(c.close, c.open)

    def _bear(self, c: Candle) -> bool:
        return self.cmp.lt(c.close, c.open)

    def _upper_shape(self, g: Geometry) -> bool:        # Inverted Hammer / Shooting Star geometry
        cf = self.config
        return self._small(g) and self.cmp.ge(g.upper_wick, cf.dominant_wick_multiple * g.body) and \
            self.cmp.le(g.lower_wick, cf.small_opposite_wick_max * g.range)

    def _lower_shape(self, g: Geometry) -> bool:        # Hammer / Hanging Man geometry
        cf = self.config
        return self._small(g) and self.cmp.ge(g.lower_wick, cf.dominant_wick_multiple * g.body) and \
            self.cmp.le(g.upper_wick, cf.small_opposite_wick_max * g.range)

    # ---------------------------------------------------------------- stream
    def on_candle(self, c: Candle) -> List[PatternEvent]:
        if not isinstance(c, Candle):
            raise TypeError("expected a Candle")
        if c.index != len(self.candles):
            raise ValueError("candles must arrive in order: expected index %d, got %d" % (len(self.candles), c.index))
        if self.candles and c.ts <= self.candles[-1].ts:
            raise ValueError("timestamps must be strictly increasing")
        self.candles.append(c)
        g = geometry(c, self.cmp)
        self.geoms.append(g)
        k = c.index
        out: List[PatternEvent] = []
        if self.cmp is None:
            self.evaluations.append(EvaluationRecord(k, None, UNSCORABLE, MISSING_TICK_SIZE, (k,)))
            return out
        for ptype in PATTERN_TYPES:
            n = CANDLES.get(ptype, 1)
            s = k - n + 1
            if s < 0:
                continue                                              # incomplete history: nothing to evaluate
            win = list(range(s, k + 1))
            bad = [i for i in win if self.geoms[i].status != SCORED]
            if bad:
                self.evaluations.append(EvaluationRecord(k, ptype, UNSCORABLE,
                                                         ZERO_RANGE if n == 1 else ZERO_RANGE_IN_WINDOW, tuple(bad)))
                continue
            out += self._evaluate(ptype, s, k)
        for e in out:
            if e.id in self._ids:                                     # CK-2: duplicate generation is preventable
                raise AssertionError("duplicate pattern id %s" % e.id)
            self._ids.add(e.id)
        self.patterns += out
        return out

    def _event(self, ptype: str, s: int, k: int, label: str, bias: str, trend: TrendContext, qualified: bool,
               reasons: Tuple[str, ...], direction: Optional[str] = None) -> PatternEvent:
        cs = self.candles[s:k + 1]
        return PatternEvent(pattern_id(self.instrument, self.timeframe, s, ptype),
                            EventStamp.from_candles(cs[0], cs[-1]), instrument=self.instrument,
                            timeframe=self.timeframe, pattern_type=ptype, pattern_label=label, bias=bias,
                            direction=direction or BIAS_DIRECTION[bias], start_candle=s, end_candle=k,
                            pattern_high=max(x.high for x in cs), pattern_low=min(x.low for x in cs),
                            geometry=tuple(self.geoms[s:k + 1]), trend=trend, context_qualified=qualified,
                            reasons=reasons)

    def _evaluate(self, ptype: str, s: int, k: int) -> List[PatternEvent]:
        cf, cmp = self.config, self.cmp
        g = self.geoms[k]
        c = self.candles[k]
        if ptype == CLASSIC_DOJI:
            if self._doji(g) and g.upper_wick > 0.0 and g.lower_wick > 0.0:
                return [self._event(ptype, s, k, CLASSIC_DOJI, NEUTRAL, self.trend(s), False, ("16.D.1",))]
        elif ptype == GRAVESTONE_DOJI:
            if self._doji(g) and cmp.ge(g.upper_wick, cf.gravestone_upper_min * g.range) and \
                    cmp.le(g.lower_wick, cf.gravestone_lower_max * g.range):
                return [self._event(ptype, s, k, GRAVESTONE_DOJI, BEARISH_BIAS, self.trend(s), False, ("16.D.2",))]
        elif ptype == LONG_LEGGED_DOJI:
            if self._doji(g) and cmp.ge(g.upper_wick, cf.long_legged_wick_min * g.range) and \
                    cmp.ge(g.lower_wick, cf.long_legged_wick_min * g.range):
                return [self._event(ptype, s, k, LONG_LEGGED_DOJI, NEUTRAL, self.trend(s), False, ("16.D.3",))]
        elif ptype == DRAGONFLY_DOJI:
            if self._doji(g) and cmp.ge(g.lower_wick, cf.dragonfly_lower_min * g.range) and \
                    cmp.le(g.upper_wick, cf.dragonfly_upper_max * g.range):
                return [self._event(ptype, s, k, DRAGONFLY_DOJI, BULLISH_BIAS, self.trend(s), False, ("16.D.5",))]
        elif ptype in (INVERTED_HAMMER, SHOOTING_STAR):
            if self._upper_shape(g):
                t = self.trend(s)
                need, bias, rule = (DOWNTREND, BULLISH_BIAS, "16.D.4") if ptype == INVERTED_HAMMER else \
                    (UPTREND, BEARISH_BIAS, "16.D.8")
                if t.context == need:
                    return [self._event(ptype, s, k, ptype, bias, t, True, (rule, "CS-1"))]
                if t.context in (SIDEWAYS, UNKNOWN):                  # CK-4 / CS-1: shape kept, no directional label
                    return [self._event(ptype, s, k, UNCLASSIFIED_SHAPE, bias, t, False, (rule, "CK-4", t.context))]
                # opposite trend: this shape is the other family's label (DOWNTREND -> Inverted Hammer, UPTREND ->
                # Shooting Star), emitted by that family
        elif ptype == HAMMER_HANGING_MAN:
            if self._lower_shape(g):
                t = self.trend(s)
                if t.context == DOWNTREND:
                    return [self._event(ptype, s, k, HAMMER, BULLISH_BIAS, t, True, ("16.D.6", "CS-1"))]
                if t.context == UPTREND:
                    return [self._event(ptype, s, k, HANGING_MAN, BEARISH_BIAS, t, True, ("16.D.6", "CS-1"))]
                return [self._event(ptype, s, k, UNCLASSIFIED_SHAPE, UNDETERMINED, t, False,
                                    ("16.D.6", "CK-4", t.context))]
        elif ptype == ENGULFING:
            p, cur = self.candles[s], c
            plo, phi = min(p.open, p.close), max(p.open, p.close)
            clo, chi = min(cur.open, cur.close), max(cur.open, cur.close)
            covers = cmp.le(clo, plo) and cmp.ge(chi, phi)            # CS-6 inclusive
            if covers and self._bear(p) and self._bull(cur):
                return [self._event(ptype, s, k, BULLISH_ENGULFING, BULLISH_BIAS, self.trend(s), False,
                                    ("16.D.7", "CS-6"), "BULLISH")]
            if covers and self._bull(p) and self._bear(cur):
                return [self._event(ptype, s, k, BEARISH_ENGULFING, BEARISH_BIAS, self.trend(s), False,
                                    ("16.D.7", "CS-6"), "BEARISH")]
        elif ptype in (MORNING_STAR, EVENING_STAR):
            a, m, z = self.candles[s], self.candles[s + 1], c
            ga, gm, gz = self.geoms[s], self.geoms[s + 1], g
            mid = (a.open + a.close) / 2.0
            if ptype == MORNING_STAR:
                ok = self._large(ga) and self._bear(a) and self._small(gm) and self._large(gz) and self._bull(z) \
                    and cmp.gt(z.close, mid)
                if ok:
                    return [self._event(ptype, s, k, MORNING_STAR, BULLISH_BIAS, self.trend(s), False, ("16.D.9",))]
            else:
                ok = self._large(ga) and self._bull(a) and self._small(gm) and self._large(gz) and self._bear(z) \
                    and cmp.lt(z.close, mid)
                if ok:
                    return [self._event(ptype, s, k, EVENING_STAR, BEARISH_BIAS, self.trend(s), False, ("16.D.10",))]
        return []


@dataclass
class CandlestickReport:
    patterns: List[PatternEvent]
    geometry: List[Geometry]
    evaluations: List[EvaluationRecord]
    tick_size: Optional[float]


def detect_candlestick_patterns(series: CandleSeries, instrument: str, timeframe: str, market: MarketDataConfig,
                                config: Optional[CandlestickConfig] = None) -> CandlestickReport:
    """Batch detector: exactly the stream run over the series."""
    st = CandlestickStream(instrument, timeframe, market, config)
    for c in series:
        st.on_candle(c)
    return CandlestickReport(list(st.patterns), list(st.geoms), list(st.evaluations), st.tick_size)
