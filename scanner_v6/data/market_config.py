"""Market-data configuration for Scanner V6 (Module A): tick size, timeframe and session calendar, with an explicit
origin so test-only fixture values can never stand in for real instrument configuration.

Spec references (research/v6/specs/V6_TRADING_SPEC_v0.2.md):
  CK-1   tick size is instrument-specific; unavailable -> the caller reports UNSCORABLE / UNKNOWN. No fallback value.
         (OHLC_COMPARISON_EPSILON = TickSize x 0.000001 and TREND_NEUTRAL_THRESHOLD = 2 x TickSize are NOT computed
         here: they belong to the candlestick module, which is not implemented.)
  CK-24  session calendar and time zone are instrument-specific.
  CK-26  no invented configuration values; missing mandatory values stay missing.
  OQ-7   official exchange calendar and time zone; 24/7 instruments must configure a continuous calendar explicitly;
         missing calendar or time zone -> EXECUTION_CONFIG_INCOMPLETE (decided downstream, not here).
  IR-3 / OQ-15  a synthetic fixture may declare an explicit, TEST-ONLY configuration. It is never production / live
         configuration and never a fallback for a missing one.

Nothing here holds a real value: no tick size, no market hours, no provider. Every value comes from the caller.
Research only: no orders, no broker, no live routing.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .candle_models import CandleError, TimestampLike, to_utc


class ConfigError(ValueError):
    """A configuration value is malformed (not: missing; a missing value is represented as None)."""


class ConfigIsolationError(ConfigError):
    """Test-only fixture configuration was offered where real instrument configuration is required."""


class ConfigOrigin(str, Enum):
    """Where a configuration came from. There is no default origin."""
    TEST_FIXTURE = "test_fixture"            # IR-3 / OQ-15: synthetic tests only
    INSTRUMENT_CONFIG = "instrument_config"  # real instrument configuration (source still OPEN: B-7...B-13)


def validate_tick_size(v: Any) -> float:
    """A positive, finite tick size as float. Nothing is inferred or defaulted."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ConfigError("tick size must be a number, got %r" % (v,))
    if not math.isfinite(v) or v <= 0:
        raise ConfigError("tick size must be positive and finite, got %r" % (v,))
    return float(v)


def validate_timeframe(v: Any) -> timedelta:
    """A positive timedelta (candle length). No string parsing, no default."""
    if not isinstance(v, timedelta):
        raise ConfigError("timeframe must be a datetime.timedelta, got %r" % (v,))
    if v <= timedelta(0):
        raise ConfigError("timeframe must be positive, got %r" % (v,))
    return v


class TickSizeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"      # CK-1: the consuming rule reports UNSCORABLE / UNKNOWN; never replaced by a default


@dataclass(frozen=True)
class TickSizeResult:
    status: TickSizeStatus
    value: Optional[float] = None


class SessionKind(str, Enum):
    CONTINUOUS = "continuous_24_7"         # OQ-7 item 5: must be configured explicitly
    EXCHANGE = "exchange_sessions"         # explicit session intervals from an official calendar


@dataclass(frozen=True)
class SessionCalendar:
    """An instrument's trading sessions, supplied by the caller. Nothing is hardcoded.

    EXCHANGE: `sessions` is a non-empty tuple of (open, close) timezone-aware datetimes (normalised to UTC), strictly
    ordered and non-overlapping; a timestamp t is in session j when open_j <= t < close_j.
    CONTINUOUS: `sessions` must be empty; every timestamp is in the one continuous session (index 0).
    `timezone` is the instrument's IANA time zone (OQ-7) and is mandatory for both kinds."""
    kind: SessionKind
    timezone: str
    sessions: Tuple[Tuple[datetime, datetime], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SessionKind):
            raise ConfigError("kind must be a SessionKind")
        if not isinstance(self.timezone, str) or not self.timezone:
            raise ConfigError("timezone must be a non-empty IANA time zone name")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ConfigError("unknown time zone %r" % self.timezone) from e
        if not isinstance(self.sessions, (tuple, list)):     # D4: a malformed session list is a ConfigError
            raise ConfigError("sessions must be a tuple of (open, close) pairs, got %s" % type(self.sessions).__name__)
        norm = []
        for j, pair in enumerate(self.sessions):
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ConfigError("session %d must be an (open, close) pair" % j)
            try:
                o, c = to_utc(pair[0]), to_utc(pair[1])
            except CandleError as e:
                raise ConfigError("session %d: %s" % (j, e)) from e
            if not o < c:
                raise ConfigError("session %d: open %s is not before close %s" % (j, o.isoformat(), c.isoformat()))
            if norm and o < norm[-1][1]:
                raise ConfigError("session %d overlaps or precedes session %d" % (j, j - 1))
            norm.append((o, c))
        if self.kind is SessionKind.CONTINUOUS and norm:
            raise ConfigError("a CONTINUOUS calendar takes no session intervals")
        if self.kind is SessionKind.EXCHANGE and not norm:
            raise ConfigError("an EXCHANGE calendar needs at least one explicit session interval")
        object.__setattr__(self, "sessions", tuple(norm))
        object.__setattr__(self, "_opens", tuple(o for o, _ in norm))

    def session_index(self, ts: TimestampLike) -> Optional[int]:
        """The session that contains `ts`, or None (outside every configured session)."""
        t = to_utc(ts)
        if self.kind is SessionKind.CONTINUOUS:
            return 0
        j = bisect.bisect_right(self._opens, t) - 1      # type: ignore[attr-defined]
        if j >= 0 and t < self.sessions[j][1]:
            return j
        return None

    def contains(self, ts: TimestampLike) -> bool:
        return self.session_index(ts) is not None


_FIXTURE_KEYS = ("instrument_id", "timeframe_seconds", "tick_size", "session")


@dataclass(frozen=True)
class MarketDataConfig:
    """Module A configuration. `origin` is mandatory; every other field is None when it was not supplied (missing
    stays missing, CK-26). No field has a real default value."""
    origin: ConfigOrigin
    instrument_id: Optional[str] = None
    timeframe: Optional[timedelta] = None
    tick_size: Optional[float] = None
    session: Optional[SessionCalendar] = None

    def __post_init__(self) -> None:
        if not isinstance(self.origin, ConfigOrigin):
            raise ConfigError("origin must be a ConfigOrigin")
        if self.instrument_id is not None and (not isinstance(self.instrument_id, str) or not self.instrument_id):
            raise ConfigError("instrument_id must be a non-empty string or None")
        if self.timeframe is not None:
            validate_timeframe(self.timeframe)
        if self.tick_size is not None:
            object.__setattr__(self, "tick_size", validate_tick_size(self.tick_size))
        if self.session is not None and not isinstance(self.session, SessionCalendar):
            raise ConfigError("session must be a SessionCalendar or None")

    def tick_size_result(self) -> TickSizeResult:
        """AVAILABLE with the configured value, or MISSING. Never inferred from prices, never defaulted."""
        if self.tick_size is None:
            return TickSizeResult(TickSizeStatus.MISSING)
        return TickSizeResult(TickSizeStatus.AVAILABLE, self.tick_size)

    @classmethod
    def from_fixture(cls, d: Mapping[str, Any]) -> "MarketDataConfig":
        """Test-only configuration from a synthetic fixture (IR-3 / OQ-15). Keys: instrument_id, timeframe_seconds,
        tick_size, session = {"kind", "timezone", "sessions": [[open_epoch, close_epoch], ...]}. Every key is
        optional; an omitted key stays None. An unknown key is an error (no silent typo)."""
        if not isinstance(d, Mapping):
            raise ConfigError("fixture configuration must be a mapping")
        unknown = sorted(set(d) - set(_FIXTURE_KEYS))
        if unknown:
            raise ConfigError("unknown Module A fixture configuration keys: %s" % ", ".join(unknown))
        tf = d.get("timeframe_seconds")
        if tf is not None and (isinstance(tf, bool) or not isinstance(tf, (int, float)) or not math.isfinite(tf)):
            raise ConfigError("timeframe_seconds must be a finite number")
        session = None
        if d.get("session") is not None:
            s = d["session"]
            if not isinstance(s, Mapping):
                raise ConfigError("session must be a mapping")
            bad = sorted(set(s) - {"kind", "timezone", "sessions"})
            if bad:
                raise ConfigError("unknown session keys: %s" % ", ".join(bad))
            try:
                kind = SessionKind(s.get("kind"))
            except ValueError as e:
                raise ConfigError("session kind must be one of %s" % [k.value for k in SessionKind]) from e
            pairs: Sequence = s.get("sessions") or ()
            if not isinstance(pairs, (list, tuple)):          # D4
                raise ConfigError("session 'sessions' must be a list of [open, close] pairs")
            session = SessionCalendar(kind, s.get("timezone"),
                                      tuple(tuple(p) if isinstance(p, (list, tuple)) else p for p in pairs))
        try:
            timeframe = None if tf is None else timedelta(seconds=tf)
        except (OverflowError, ValueError) as e:                # D4: too large for a timedelta
            raise ConfigError("timeframe_seconds %r is out of range" % (tf,)) from e
        return cls(ConfigOrigin.TEST_FIXTURE, d.get("instrument_id"),
                   None if timeframe is None else validate_timeframe(timeframe), d.get("tick_size"), session)


def require_instrument_config(cfg: MarketDataConfig) -> MarketDataConfig:
    """Gate for any path that needs REAL instrument configuration (production / live evaluation). Test-only fixture
    configuration is refused, so it can never be promoted silently (IR-3 / OQ-15 rule 6)."""
    if not isinstance(cfg, MarketDataConfig):
        raise ConfigError("expected a MarketDataConfig")
    if cfg.origin is not ConfigOrigin.INSTRUMENT_CONFIG:
        raise ConfigIsolationError("test-only fixture configuration cannot be used as instrument configuration")
    return cfg
