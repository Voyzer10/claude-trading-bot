"""US Futures (Databento / CME Globex) configuration, credential inspection, and Globex calendar."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Callable, Dict, FrozenSet, Optional, Tuple
from zoneinfo import ZoneInfo

from .exceptions import FuturesAuthError, FuturesInputError

CME_TZ = ZoneInfo("America/Chicago")
UTC_TZ = timezone.utc

DATABENTO_DATASET = "GLBX.MDP3"
CANDIDATE_INDEX_FUTURES_ROOTS: Tuple[str, ...] = ("ES", "MES", "NQ", "MNQ", "YM", "MYM", "RTY", "M2K")
DATABENTO_SYMBOLOGY_TYPES: Tuple[str, ...] = ("raw_symbol", "instrument_id", "parent", "continuous")
DATABENTO_SCHEMAS: Tuple[str, ...] = (
    "definition",
    "ohlcv-1s",
    "ohlcv-1m",
    "ohlcv-1h",
    "trades",
    "mbp-1",
    "statistics",
    "status",
)


@dataclass(frozen=True)
class DatabentoCredential:
    """Databento API credential with masked repr."""

    api_key: str
    source: str = "env:DATABENTO_API_KEY"

    def __repr__(self) -> str:
        prefix = self.api_key[:5] if len(self.api_key) >= 5 else "****"
        return f"DatabentoCredential(api_key={prefix}..., source={self.source})"


def inspect_databento_credentials() -> Dict[str, str]:
    """Inspect Databento credential presence without ever exposing key values."""
    val = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not val:
        return {"DATABENTO_API_KEY": "ABSENT"}
    if len(val) < 8:
        return {"DATABENTO_API_KEY": "INVALID"}
    return {"DATABENTO_API_KEY": "PRESENT"}


def resolve_databento_credential() -> DatabentoCredential:
    val = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not val:
        raise FuturesAuthError("DATABENTO_API_KEY is not configured in environment")
    if len(val) < 8:
        raise FuturesAuthError("DATABENTO_API_KEY appears malformed")
    return DatabentoCredential(api_key=val)


@dataclass
class CMEGlobexCalendar:
    """CME Globex equity-index futures calendar (America/Chicago).

    Regular electronic session:
    - Opens Sunday 17:00 CT (for Monday trade date)
    - Daily maintenance break: 16:00–17:00 CT Monday–Thursday
    - Closes Friday 16:00 CT
    """

    holidays: FrozenSet[date] = field(default_factory=frozenset)
    early_closes: Dict[date, dt_time] = field(default_factory=dict)
    unexpected_closures: FrozenSet[date] = field(default_factory=frozenset)
    verified_years: FrozenSet[int] = field(default_factory=frozenset)

    def is_year_verified(self, year: int) -> bool:
        return int(year) in self.verified_years

    def is_verified_for_range(self, start_day: date, end_day: date) -> bool:
        if end_day < start_day:
            start_day, end_day = end_day, start_day
        return all(y in self.verified_years for y in range(start_day.year, end_day.year + 1))

    def trade_date_for(self, ts: datetime) -> date:
        ct = ts.astimezone(CME_TZ) if ts.tzinfo else ts.replace(tzinfo=CME_TZ)
        # Events at or after 17:00 CT belong to the next calendar day's Globex trade date
        if ct.time() >= dt_time(17, 0):
            nxt = ct.date() + timedelta(days=1)
            # Friday >= 17:00 is closed until Sunday 17:00 (Monday trade date)
            if ct.weekday() == 4:
                return ct.date() + timedelta(days=3)
            if ct.weekday() == 5:
                return ct.date() + timedelta(days=2)
            return nxt
        return ct.date()

    def is_trading_day(self, trade_day: date, *, require_verified: bool = False) -> bool:
        if trade_day in self.unexpected_closures or trade_day in self.holidays:
            return False
        if require_verified and trade_day.year not in self.verified_years:
            raise FuturesInputError(f"CME Globex calendar is not verified for year {trade_day.year}")
        return trade_day.weekday() < 5

    def classify_session(self, ts: datetime, *, require_verified: bool = False) -> str:
        ct = ts.astimezone(CME_TZ) if ts.tzinfo else ts.replace(tzinfo=CME_TZ)
        t = ct.time()
        wd = ct.weekday()
        # Saturday is closed all day; Sunday closed before 17:00 CT; Friday closed from 16:00 CT
        if wd == 5:
            return "CLOSED"
        if wd == 6 and t < dt_time(17, 0):
            return "CLOSED"
        if wd == 4 and t >= dt_time(16, 0):
            return "CLOSED"
        if dt_time(16, 0) <= t < dt_time(17, 0):
            return "MAINTENANCE_BREAK"
        td = self.trade_date_for(ct)
        if not self.is_trading_day(td, require_verified=require_verified):
            return "CLOSED"
        early = self.early_closes.get(td)
        if early is not None and t >= early and t < dt_time(17, 0):
            return "CLOSED"
        if dt_time(8, 30) <= t < dt_time(15, 0):
            return "RTH"
        return "ETH"


class DatabentoRateLimiter:
    """Thread-safe rate limiter for Databento historical API."""

    def __init__(
        self,
        *,
        requests_per_second: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._gap = 1.0 / max(0.1, float(requests_per_second))
        self._last: Optional[float] = None
        self._lock = threading.Lock()
        self._clock = clock
        self._sleeper = sleeper

    def acquire(self) -> float:
        with self._lock:
            now = self._clock()
            wait = (self._last + self._gap - now) if self._last is not None else 0.0
            if wait > 0:
                self._sleeper(wait)
                now = self._clock()
            self._last = now
            return max(0.0, wait)
