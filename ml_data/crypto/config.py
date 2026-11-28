"""Crypto configuration, provider evaluations, rate limiter, and 24/7 UTC calendar."""
from __future__ import annotations

import random
import threading
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, FrozenSet, Optional, Tuple

import requests

from .exceptions import (
    CryptoAdapterError,
    CryptoBlockedEndpointError,
    CryptoGeoBlockedError,
    CryptoInputError,
    CryptoRateLimitError,
)

UTC_TZ = timezone.utc

COINBASE_REST_BASE = "https://api.exchange.coinbase.com"
COINDCX_API_BASE = "https://api.coindcx.com"
COINDCX_PUBLIC_BASE = "https://public.coindcx.com"
COINDCX_WS_URL = "wss://stream.coindcx.com"

# Binance is deactivated as an active production provider.
BINANCE_USDM_BASE = "https://fapi.binance.com"
BINANCE_COINM_BASE = "https://dapi.binance.com"
DERIBIT_PUBLIC_BASE = "https://www.deribit.com"

APPROVED_CRYPTO_HOSTS: FrozenSet[str] = frozenset({
    "api.exchange.coinbase.com",
    "api.coindcx.com",
    "public.coindcx.com",
})

DEFAULT_CRYPTO_UNIVERSE: Tuple[str, ...] = ("BTC", "ETH")


@dataclass(frozen=True)
class CryptoProviderEvaluation:
    provider_id: str
    name: str
    verification_date: str
    products: str
    public_market_data: str
    funding_and_oi: str
    geo_and_licensing_notes: str
    selected: bool


CRYPTO_DERIVATIVES_EVALUATIONS: Dict[str, CryptoProviderEvaluation] = {
    "coindcx": CryptoProviderEvaluation(
        provider_id="coindcx",
        name="CoinDCX",
        verification_date="2026-11-28",
        products="Spot (INR/USDT) and Perpetual Futures (USDT/INR margin)",
        public_market_data="Public GET /exchange/v1/markets*, /derivatives/futures/data/*, /market_data/candles*",
        funding_and_oi="funding_frequency in contract details; no documented historical funding/OI series (UNSUPPORTED)",
        geo_and_licensing_notes=(
            "Restricted under CoinDCX API Terms Section 2.3(c): no redistribution, display, or dissemination "
            "of market data or derived charts/analytics/research to third parties."
        ),
        selected=True,
    ),
    "binance_usdm": CryptoProviderEvaluation(
        provider_id="binance_usdm",
        name="Binance USDⓈ-M Futures (DEPRECATED / INACTIVE)",
        verification_date="2026-11-28",
        products="Linear USDT/USDC perpetuals and dated futures",
        public_market_data="Deactivated by project decision; CoinDCX is primary crypto provider",
        funding_and_oi="Deactivated",
        geo_and_licensing_notes="Inactive — do not call Binance endpoints.",
        selected=False,
    ),
    "binance_coinm": CryptoProviderEvaluation(
        provider_id="binance_coinm",
        name="Binance COIN-M Futures (DEPRECATED / INACTIVE)",
        verification_date="2026-11-28",
        products="Inverse coin-margined perpetuals and dated futures",
        public_market_data="Deactivated by project decision",
        funding_and_oi="Deactivated",
        geo_and_licensing_notes="Inactive — do not call Binance endpoints.",
        selected=False,
    ),
}


@dataclass(frozen=True)
class CryptoCalendar:
    """24/7 UTC continuous crypto calendar."""

    verified_years: FrozenSet[int] = frozenset({2024, 2025, 2026, 2027})

    def is_trading_day(self, day: date) -> bool:
        return True

    def classify_session(self, ts: datetime) -> str:
        return "CONTINUOUS_24_7"


@dataclass(frozen=True)
class CryptoHTTPResponse:
    status_code: int
    body: Any
    headers: Dict[str, str]


TransportCallable = Callable[[str, str, Dict[str, str], Optional[Dict[str, Any]], float], CryptoHTTPResponse]


class CryptoRateLimiter:
    """Thread-safe shared rate limiter for public crypto REST endpoints."""

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


class PublicCryptoHTTPClient:
    """Read-only public GET client for Coinbase, Binance Futures, and Deribit."""

    def __init__(
        self,
        *,
        rate_limiter: Optional[CryptoRateLimiter] = None,
        transport: Optional[TransportCallable] = None,
        max_retries: int = 3,
        base_backoff_s: float = 0.5,
        timeout_s: float = 12.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rate_limiter = rate_limiter or CryptoRateLimiter()
        self._transport = transport
        self.max_retries = max(0, int(max_retries))
        self.base_backoff_s = max(0.05, float(base_backoff_s))
        self.timeout_s = float(timeout_s)
        self._sleeper = sleeper
        self._session: Optional[requests.Session] = None

    @staticmethod
    def validate_url(url: str, method: str = "GET") -> None:
        if method.strip().upper() != "GET":
            raise CryptoBlockedEndpointError(f"Only GET is permitted (got {method})")
        u = urllib.parse.urlsplit(url)
        if u.scheme.lower() != "https":
            raise CryptoBlockedEndpointError(f"Only HTTPS is permitted (got {u.scheme!r})")
        if u.username or u.password or u.port is not None:
            raise CryptoBlockedEndpointError(f"Unexpected URL authority components in {url!r}")
        host = (u.hostname or "").strip().lower()
        if host not in APPROVED_CRYPTO_HOSTS:
            raise CryptoBlockedEndpointError(f"Unapproved crypto host {host!r}")
        low_path = u.path.lower()
        if any(tok in low_path for tok in ("/orders", "/account", "/position", "/trade")):
            if "/trades" not in low_path and "/aggtrades" not in low_path and "/historicaltrades" not in low_path:
                raise CryptoBlockedEndpointError(f"Blocked private/trading path {u.path!r}")

    def _default_transport(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]],
        timeout_s: float,
    ) -> CryptoHTTPResponse:
        if self._session is None:
            self._session = requests.Session()
        resp = self._session.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            timeout=timeout_s,
            allow_redirects=False,
        )
        if 300 <= resp.status_code < 400:
            raise CryptoBlockedEndpointError(f"Refused HTTP redirect ({resp.status_code}) on crypto client")
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = resp.text
        return CryptoHTTPResponse(
            status_code=int(resp.status_code),
            body=body,
            headers={str(k): str(v) for k, v in resp.headers.items()},
        )

    def get(self, url: str, *, params: Optional[Dict[str, Any]] = None) -> CryptoHTTPResponse:
        self.validate_url(url, "GET")
        headers = {"Accept": "application/json", "User-Agent": "ml-data-crypto-adapter"}
        transport = self._transport or self._default_transport

        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self.rate_limiter.acquire()
            try:
                resp = transport("GET", url, headers, params, self.timeout_s)
            except CryptoBlockedEndpointError:
                raise
            except Exception as e:
                last_err = e
                low = str(e).lower()
                if attempt >= self.max_retries or not any(tok in low for tok in ("timeout", "timed out", "connection")):
                    raise CryptoAdapterError(f"Crypto request error on {url}: {e}") from e
                delay = self.base_backoff_s * (2 ** attempt) + random.uniform(0.0, 0.25 * self.base_backoff_s)
                self._sleeper(delay)
                continue

            if resp.status_code == 200:
                return resp
            if resp.status_code == 451:
                raise CryptoGeoBlockedError(f"Crypto endpoint geo-restricted (HTTP 451): {url}")
            if resp.status_code in (400, 404, 422):
                raise CryptoInputError(f"Crypto HTTP {resp.status_code} on {url}: {resp.body}")
            if resp.status_code in (418, 429) or resp.status_code >= 500:
                last_err = CryptoRateLimitError(f"HTTP {resp.status_code}")
                if attempt >= self.max_retries:
                    if resp.status_code in (418, 429):
                        raise CryptoRateLimitError(f"Crypto rate limit exhausted ({resp.status_code}) on {url}")
                    raise CryptoAdapterError(f"Crypto HTTP {resp.status_code} failed on {url}")
                delay = self.base_backoff_s * (2 ** attempt) + random.uniform(0.0, 0.25 * self.base_backoff_s)
                self._sleeper(delay)
                continue
            raise CryptoAdapterError(f"Crypto HTTP {resp.status_code} on {url}")

        raise CryptoAdapterError(f"Crypto request failed on {url}: {last_err}")
