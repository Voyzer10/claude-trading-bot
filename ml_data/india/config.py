"""Kite client wrapper, shared rate limiter, and NSE session calendar."""
from __future__ import annotations

import gzip
import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from .exceptions import (
    CalendarError,
    InstrumentMasterError,
    KiteAdapterError,
    KiteAuthError,
    KiteInputError,
    KiteRateLimitError,
)

IST_TZ = ZoneInfo("Asia/Kolkata")
UTC_TZ = timezone.utc

# Conservative chunking windows (subject to preflight verification)
INTERVAL_MAX_DAYS: Dict[str, int] = {
    "minute": 60,
    "3minute": 100,
    "5minute": 100,
    "10minute": 100,
    "15minute": 200,
    "30minute": 200,
    "60minute": 400,
}

SUPPORTED_INTERVALS = tuple(INTERVAL_MAX_DAYS.keys())

_READ_ONLY_PATHS = (
    "/instruments/",
    "/instruments/historical/",
    "/quote",
    "/user/profile",
)


class KiteRateLimiter:
    """Thread-safe shared rate limiter across Kite REST endpoints."""

    def __init__(
        self,
        *,
        historical_rps: float = 2.0,
        quote_rps: float = 1.0,
        other_rps: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._intervals = {
            "historical": 1.0 / max(0.1, float(historical_rps)),
            "quote": 1.0 / max(0.1, float(quote_rps)),
            "other": 1.0 / max(0.1, float(other_rps)),
        }
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._clock = clock
        self._sleeper = sleeper

    def acquire(self, bucket: str) -> float:
        gap = self._intervals.get(bucket, self._intervals["other"])
        with self._lock:
            now = self._clock()
            prev = self._last.get(bucket)
            wait = (prev + gap - now) if prev is not None else 0.0
            if wait > 0:
                self._sleeper(wait)
                now = self._clock()
            self._last[bucket] = now
            return max(0.0, wait)


@dataclass
class NSECalendar:
    """Explicit Asia/Kolkata NSE equity & index derivatives trading calendar."""

    holidays: FrozenSet[date] = field(default_factory=frozenset)
    special_sessions: Dict[date, Tuple[dt_time, dt_time]] = field(default_factory=dict)
    unexpected_closures: FrozenSet[date] = field(default_factory=frozenset)
    verified_years: FrozenSet[int] = field(default_factory=frozenset)
    regular_open: dt_time = dt_time(9, 15)
    regular_close: dt_time = dt_time(15, 30)

    def is_trading_day(self, day: date, *, require_verified: bool = False) -> bool:
        if require_verified and day.year not in self.verified_years:
            raise CalendarError(f"NSE holiday calendar is not verified for year {day.year}")
        if day in self.unexpected_closures or day in self.holidays:
            return False
        if day in self.special_sessions:
            return True
        return day.weekday() < 5

    def session_bounds(self, day: date, *, require_verified: bool = False) -> Optional[Tuple[datetime, datetime]]:
        if not self.is_trading_day(day, require_verified=require_verified):
            return None
        o_t, c_t = self.special_sessions.get(day, (self.regular_open, self.regular_close))
        return (
            datetime.combine(day, o_t, tzinfo=IST_TZ),
            datetime.combine(day, c_t, tzinfo=IST_TZ),
        )

    def is_in_session(self, ts: datetime, *, require_verified: bool = False) -> bool:
        ist_dt = ts.astimezone(IST_TZ) if ts.tzinfo else ts.replace(tzinfo=IST_TZ)
        bounds = self.session_bounds(ist_dt.date(), require_verified=require_verified)
        if bounds is None:
            return False
        return bounds[0] <= ist_dt < bounds[1]

    def session_date(self, ts: datetime) -> date:
        ist_dt = ts.astimezone(IST_TZ) if ts.tzinfo else ts.replace(tzinfo=IST_TZ)
        return ist_dt.date()

    def is_year_verified(self, year: int) -> bool:
        return int(year) in self.verified_years

    def is_verified_for_range(self, start_day: date, end_day: date) -> bool:
        if end_day < start_day:
            start_day, end_day = end_day, start_day
        return all(y in self.verified_years for y in range(start_day.year, end_day.year + 1))


class KiteClientWrapper:
    """Read-only Kite Connect wrapper reusing existing kite.py auth/session or an injected SDK client."""

    API_BASE = "https://api.kite.trade"

    def __init__(
        self,
        *,
        kite_client: Any = None,
        rate_limiter: Optional[KiteRateLimiter] = None,
        max_retries: int = 3,
        base_backoff_s: float = 0.5,
        timeout_s: float = 15.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = kite_client
        self.rate_limiter = rate_limiter or KiteRateLimiter()
        self.max_retries = max(0, int(max_retries))
        self.base_backoff_s = max(0.05, float(base_backoff_s))
        self.timeout_s = float(timeout_s)
        self._sleeper = sleeper

    def _auth_headers(self) -> Dict[str, str]:
        import kite as K

        api_key, _ = K.keys()
        sess = K.load_session()
        if not api_key or not sess or not sess.get("access_token"):
            raise KiteAuthError("Zerodha Kite session is missing or expired; re-login required")
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {api_key}:{sess['access_token']}",
            "User-Agent": "ml-data-kite-adapter",
        }

    @staticmethod
    def _forget_session_safe() -> None:
        try:
            import kite as K
            K.forget_session()
        except Exception:
            pass

    def _run_with_retry(self, bucket: str, fn: Callable[[], Any]) -> Any:
        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self.rate_limiter.acquire(bucket)
            try:
                return fn()
            except (KiteAuthError,):
                self._forget_session_safe()
                raise
            except (KiteInputError, InstrumentMasterError):
                raise
            except Exception as e:
                last_err = e
                msg = str(e)
                low = msg.lower()
                if "tokenexception" in low or "403" in low or "invalid api_key or access_token" in low:
                    self._forget_session_safe()
                    raise KiteAuthError("Kite authentication failed (403 TokenException): re-login required") from e
                if "inputexception" in low or "400" in low:
                    raise KiteInputError(f"Kite invalid input: {msg}") from e
                is_transient = any(tok in low for tok in ("429", "500", "502", "503", "timeout", "timed out", "temporarily"))
                if not is_transient or attempt >= self.max_retries:
                    if "429" in low:
                        raise KiteRateLimitError(f"Kite rate limit exceeded after {attempt + 1} attempts") from e
                    raise KiteAdapterError(f"Kite request failed: {msg}") from e
                delay = self.base_backoff_s * (2 ** attempt) + random.uniform(0.0, 0.25 * self.base_backoff_s)
                self._sleeper(delay)
        raise KiteAdapterError(f"Kite request failed: {last_err}")

    def _http_get(self, path: str, params: Optional[Dict[str, Any]] = None, *, raw: bool = False) -> Any:
        if not any(path.startswith(p) for p in _READ_ONLY_PATHS):
            raise KiteInputError(f"Blocked non-read-only Kite path: {path}")
        headers = self._auth_headers()
        url = self.API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = resp.read()
                resp_headers = getattr(resp, "headers", None)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code == 403 or "TokenException" in body:
                raise KiteAuthError("Kite authentication failed (403 TokenException)") from e
            if e.code == 400 or "InputException" in body:
                raise KiteInputError(f"Kite HTTP 400: {body[:200]}") from e
            raise KiteAdapterError(f"HTTP {e.code}: {body[:200]}") from e
        except Exception as e:
            raise KiteAdapterError(str(e)) from e
        if raw:
            headers = resp_headers
            enc_raw = ""
            if headers is not None and hasattr(headers, "get"):
                enc_raw = str(headers.get("Content-Encoding") or "").strip().lower()
            encodings = [e.strip() for e in enc_raw.split(",") if e.strip()] if enc_raw else []
            if any(e not in ("gzip", "x-gzip", "identity") for e in encodings):
                raise InstrumentMasterError(f"Unsupported Content-Encoding in instrument master response: {enc_raw!r}")
            has_gzip_header = any(e in ("gzip", "x-gzip") for e in encodings)
            has_gzip_magic = payload.startswith(b"\x1f\x8b")
            if has_gzip_header or has_gzip_magic:
                try:
                    payload = gzip.decompress(payload)
                except (OSError, EOFError, zlib.error) as e:
                    raise InstrumentMasterError("Malformed gzip payload in instrument master response") from e
            try:
                return payload.decode("utf-8")
            except UnicodeDecodeError as e:
                raise InstrumentMasterError("Invalid UTF-8 in instrument master response") from e
        doc = json.loads(payload)
        if doc.get("status") != "success":
            raise KiteAdapterError(str(doc.get("message") or "Kite API error"))
        return doc.get("data")

    def fetch_instruments_csv(self, exchange: str) -> str:
        """Download raw instrument master CSV for an exchange (e.g. 'NSE' or 'NFO')."""
        ex = exchange.strip().upper()
        if ex not in ("NSE", "NFO"):
            raise KiteInputError(f"Unsupported exchange for India adapter: {ex!r}")

        def _do() -> str:
            if self._client is not None and hasattr(self._client, "instruments_csv"):
                return str(self._client.instruments_csv(ex))
            if self._client is not None and hasattr(self._client, "instruments"):
                # Injected KiteConnect SDK returns list[dict]; convert deterministically if needed
                rows = self._client.instruments(ex)
                if isinstance(rows, str):
                    return rows
                return _rows_to_csv(rows)
            return str(self._http_get(f"/instruments/{ex}", raw=True))

        return self._run_with_retry("other", _do)

    def fetch_historical_candles(
        self,
        instrument_token: int,
        interval: str,
        from_dt: datetime,
        to_dt: datetime,
        *,
        include_oi: bool = True,
    ) -> List[Any]:
        """Fetch raw historical candles from Kite /instruments/historical/:token/:interval."""
        if interval not in INTERVAL_MAX_DAYS:
            raise KiteInputError(f"Unsupported Kite interval: {interval!r}")
        f_ist = from_dt.astimezone(IST_TZ).strftime("%Y-%m-%d %H:%M:%S")
        t_ist = to_dt.astimezone(IST_TZ).strftime("%Y-%m-%d %H:%M:%S")

        def _do() -> List[Any]:
            if self._client is not None and hasattr(self._client, "historical_data"):
                return list(
                    self._client.historical_data(
                        int(instrument_token), f_ist, t_ist, interval, continuous=False, oi=bool(include_oi)
                    )
                )
            data = self._http_get(
                f"/instruments/historical/{int(instrument_token)}/{interval}",
                params={"from": f_ist, "to": t_ist, "oi": 1 if include_oi else 0},
                raw=False,
            )
            return list((data or {}).get("candles") or [])

        return self._run_with_retry("historical", _do)


def _rows_to_csv(rows: Sequence[Dict[str, Any]]) -> str:
    import csv
    import io

    cols = [
        "instrument_token", "exchange_token", "tradingsymbol", "name", "last_price",
        "expiry", "strike", "tick_size", "lot_size", "instrument_type", "segment", "exchange",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in cols})
    return buf.getvalue()
