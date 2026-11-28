"""Alpaca US configuration, sanitized credential inspection, rate limiter, and US calendar."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Callable, Dict, FrozenSet, Optional, Tuple
from zoneinfo import ZoneInfo

from .exceptions import AlpacaAuthError, USCalendarError

NY_TZ = ZoneInfo("America/New_York")
UTC_TZ = timezone.utc

STOCK_FEEDS = ("iex", "sip", "delayed_sip")
OPTION_FEEDS = ("indicative", "opra")
STOCK_ADJUSTMENTS = ("raw", "split", "dividend", "all")
SUPPORTED_TIMEFRAMES = ("1Min", "5Min", "15Min", "1Hour")

OPTION_HISTORY_EARLIEST = date(2024, 2, 1)


@dataclass(frozen=True)
class AlpacaCredential:
    """Read-only Alpaca API credential with masked repr."""

    key_id: str
    secret_key: str
    source: str
    is_paper: bool = True

    def __repr__(self) -> str:
        prefix = self.key_id[:4] if len(self.key_id) >= 4 else "****"
        return f"AlpacaCredential(key_id={prefix}..., source={self.source}, is_paper={self.is_paper})"

    def headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.key_id,
            "APCA-API-SECRET-KEY": self.secret_key,
        }


def inspect_alpaca_credentials(v6_cred_path: Optional[str] = None) -> Dict[str, str]:
    """Inspect Alpaca credential presence without ever exposing key values or secrets.

    Returns a mapping of source -> status in {'PRESENT', 'ABSENT', 'INVALID', 'UNVERIFIED'}.
    """
    report: Dict[str, str] = {}

    k_id = os.environ.get("ALPACA_KEY_ID", "").strip()
    k_sec = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if k_id and k_sec:
        report["ALPACA_KEY_ID/ALPACA_SECRET_KEY"] = "PRESENT"
    elif k_id or k_sec:
        report["ALPACA_KEY_ID/ALPACA_SECRET_KEY"] = "INVALID"
    else:
        report["ALPACA_KEY_ID/ALPACA_SECRET_KEY"] = "ABSENT"

    a_id = os.environ.get("ALPACA_API_KEY", "").strip()
    a_sec = os.environ.get("ALPACA_API_SECRET", "").strip()
    if a_id and a_sec:
        report["ALPACA_API_KEY/ALPACA_API_SECRET"] = "PRESENT"
    elif a_id or a_sec:
        report["ALPACA_API_KEY/ALPACA_API_SECRET"] = "INVALID"
    else:
        report["ALPACA_API_KEY/ALPACA_API_SECRET"] = "ABSENT"

    try:
        from v6_runtime.data.alpaca import DEFAULT_CREDENTIAL_FILE, load_credential

        path = v6_cred_path or DEFAULT_CREDENTIAL_FILE
        cred = load_credential(path)
        report["v6_data_credential"] = "PRESENT" if cred is not None else "ABSENT"
    except Exception:
        report["v6_data_credential"] = "INVALID"

    return report


def resolve_alpaca_credential(v6_cred_path: Optional[str] = None) -> AlpacaCredential:
    """Resolve Alpaca credentials safely from V6 data-only store or environment variables."""
    try:
        from v6_runtime.data.alpaca import DEFAULT_CREDENTIAL_FILE, load_credential

        cred = load_credential(v6_cred_path or DEFAULT_CREDENTIAL_FILE)
        if cred is not None:
            return AlpacaCredential(
                key_id=cred.key_id,
                secret_key=cred.secret,
                source="v6_data_only",
                is_paper=cred.key_id.startswith("PK"),
            )
    except Exception:
        pass

    for id_var, sec_var in (("ALPACA_KEY_ID", "ALPACA_SECRET_KEY"), ("ALPACA_API_KEY", "ALPACA_API_SECRET")):
        k = os.environ.get(id_var, "").strip()
        s = os.environ.get(sec_var, "").strip()
        if k and s:
            return AlpacaCredential(
                key_id=k,
                secret_key=s,
                source=f"env:{id_var}",
                is_paper=k.startswith("PK"),
            )

    raise AlpacaAuthError("Alpaca credentials are not configured (checked v6 data-only file and environment)")


@dataclass
class USCalendar:
    """Explicit America/New_York US equities & options exchange trading calendar."""

    holidays: FrozenSet[date] = field(default_factory=frozenset)
    early_closes: Dict[date, dt_time] = field(default_factory=dict)
    unexpected_closures: FrozenSet[date] = field(default_factory=frozenset)
    verified_years: FrozenSet[int] = field(default_factory=frozenset)
    regular_open: dt_time = dt_time(9, 30)
    regular_close: dt_time = dt_time(16, 0)
    options_late_close_time: dt_time = dt_time(16, 15)
    premarket_open: dt_time = dt_time(4, 0)
    postmarket_close: dt_time = dt_time(20, 0)

    def is_year_verified(self, year: int) -> bool:
        return int(year) in self.verified_years

    def is_verified_for_range(self, start_day: date, end_day: date) -> bool:
        if end_day < start_day:
            start_day, end_day = end_day, start_day
        return all(y in self.verified_years for y in range(start_day.year, end_day.year + 1))

    def is_trading_day(self, day: date, *, require_verified: bool = False) -> bool:
        if require_verified and day.year not in self.verified_years:
            raise USCalendarError(f"US exchange calendar is not verified for year {day.year}")
        if day in self.unexpected_closures or day in self.holidays:
            return False
        return day.weekday() < 5

    def session_bounds(
        self,
        day: date,
        *,
        options_late_close: bool = False,
        require_verified: bool = False,
    ) -> Optional[Tuple[datetime, datetime]]:
        if not self.is_trading_day(day, require_verified=require_verified):
            return None
        if day in self.early_closes:
            close_t = self.early_closes[day]
            if options_late_close and close_t == dt_time(13, 0):
                close_t = dt_time(13, 15)
        elif options_late_close:
            close_t = self.options_late_close_time
        else:
            close_t = self.regular_close
        return (
            datetime.combine(day, self.regular_open, tzinfo=NY_TZ),
            datetime.combine(day, close_t, tzinfo=NY_TZ),
        )

    def classify_session(
        self,
        ts: datetime,
        *,
        options_late_close: bool = False,
        require_verified: bool = False,
    ) -> str:
        ny_dt = ts.astimezone(NY_TZ) if ts.tzinfo else ts.replace(tzinfo=NY_TZ)
        day = ny_dt.date()
        if not self.is_trading_day(day, require_verified=require_verified):
            return "CLOSED"
        bounds = self.session_bounds(day, options_late_close=options_late_close, require_verified=require_verified)
        assert bounds is not None
        reg_open, reg_close = bounds
        pre_open = datetime.combine(day, self.premarket_open, tzinfo=NY_TZ)
        post_close = datetime.combine(day, self.postmarket_close, tzinfo=NY_TZ)
        if pre_open <= ny_dt < reg_open:
            return "PRE_MARKET"
        if reg_open <= ny_dt < reg_close:
            return "REGULAR"
        if reg_close <= ny_dt < post_close:
            return "POST_MARKET"
        return "CLOSED"

    def is_in_regular_session(
        self,
        ts: datetime,
        *,
        options_late_close: bool = False,
        require_verified: bool = False,
    ) -> bool:
        return self.classify_session(ts, options_late_close=options_late_close, require_verified=require_verified) == "REGULAR"


class AlpacaRateLimiter:
    """Thread-safe rate limiter tracking Alpaca X-RateLimit headers."""

    def __init__(
        self,
        *,
        requests_per_minute: int = 200,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_gap = 60.0 / max(1, int(requests_per_minute))
        self._last_req: Optional[float] = None
        self._remaining: Optional[int] = None
        self._reset_epoch: Optional[float] = None
        self._limit: Optional[int] = None
        self._lock = threading.Lock()
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleeper = sleeper

    def update_from_headers(self, headers: Dict[str, str]) -> None:
        with self._lock:
            low = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
            if "x-ratelimit-limit" in low:
                try:
                    self._limit = int(low["x-ratelimit-limit"])
                except ValueError:
                    pass
            if "x-ratelimit-remaining" in low:
                try:
                    self._remaining = int(low["x-ratelimit-remaining"])
                except ValueError:
                    pass
            if "x-ratelimit-reset" in low:
                try:
                    self._reset_epoch = float(low["x-ratelimit-reset"])
                except ValueError:
                    pass

    def acquire(self) -> float:
        with self._lock:
            slept = 0.0
            now_m = self._clock()
            if self._remaining is not None and self._remaining <= 0 and self._reset_epoch is not None:
                wait_reset = max(0.0, self._reset_epoch - self._wall_clock())
                if wait_reset > 0:
                    self._sleeper(min(wait_reset, 60.0))
                    slept += min(wait_reset, 60.0)
                    now_m = self._clock()
            if self._last_req is not None:
                gap_wait = self._last_req + self._min_gap - now_m
                if gap_wait > 0:
                    self._sleeper(gap_wait)
                    slept += gap_wait
                    now_m = self._clock()
            self._last_req = now_m
            return slept
