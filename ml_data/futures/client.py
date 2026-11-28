"""Read-only Databento Historical API client with strict host/endpoint allowlists and credit guard."""
from __future__ import annotations

import base64
import random
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Optional

import requests

from .config import DatabentoCredential, DatabentoRateLimiter, resolve_databento_credential
from .exceptions import (
    FuturesAdapterError,
    FuturesAuthError,
    FuturesBlockedEndpointError,
    FuturesInputError,
    FuturesRateLimitError,
    FuturesSubscriptionError,
)

DATABENTO_HIST_BASE = "https://hist.databento.com"
APPROVED_DATABENTO_HOSTS: FrozenSet[str] = frozenset({"hist.databento.com"})

_ALLOWED_PATHS = (
    re.compile(r"^/v0/metadata\.list_datasets$"),
    re.compile(r"^/v0/metadata\.list_schemas$"),
    re.compile(r"^/v0/metadata\.get_dataset_range$"),
    re.compile(r"^/v0/metadata\.get_cost$"),
    re.compile(r"^/v0/symbology\.resolve$"),
    re.compile(r"^/v0/timeseries\.get_range$"),
)

TransportCallable = Callable[[str, str, Dict[str, str], Optional[Dict[str, Any]], float], "DatabentoHTTPResponse"]


@dataclass(frozen=True)
class DatabentoHTTPResponse:
    status_code: int
    body: Any
    headers: Dict[str, str]


class DatabentoHistoricalClient:
    """Read-only HTTPS GET client for Databento Historical API."""

    def __init__(
        self,
        *,
        credential: Optional[DatabentoCredential] = None,
        base_url: str = DATABENTO_HIST_BASE,
        rate_limiter: Optional[DatabentoRateLimiter] = None,
        transport: Optional[TransportCallable] = None,
        allow_billable_timeseries: bool = False,
        max_retries: int = 3,
        base_backoff_s: float = 0.5,
        timeout_s: float = 20.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._credential = credential
        self.base_url = base_url.rstrip("/")
        self.validate_base_url(self.base_url)
        self.rate_limiter = rate_limiter or DatabentoRateLimiter()
        self._transport = transport
        self.allow_billable_timeseries = bool(allow_billable_timeseries)
        self.max_retries = max(0, int(max_retries))
        self.base_backoff_s = max(0.05, float(base_backoff_s))
        self.timeout_s = float(timeout_s)
        self._sleeper = sleeper
        self._session: Optional[requests.Session] = None

    @staticmethod
    def validate_base_url(base_url: str) -> None:
        u = urllib.parse.urlsplit(base_url)
        if u.scheme.lower() != "https":
            raise FuturesBlockedEndpointError(f"Only HTTPS is permitted for Databento (got {u.scheme!r})")
        if u.username or u.password or u.port is not None or u.query or u.fragment:
            raise FuturesBlockedEndpointError(f"Unexpected URL components in Databento base URL: {base_url!r}")
        host = (u.hostname or "").strip().lower()
        if host not in APPROVED_DATABENTO_HOSTS:
            raise FuturesBlockedEndpointError(f"Unapproved Databento host {host!r}")

    @staticmethod
    def validate_request(method: str, path: str) -> None:
        if method.strip().upper() != "GET":
            raise FuturesBlockedEndpointError(f"Only GET is permitted by read-only Databento client (got {method})")
        if not any(p.fullmatch(path) for p in _ALLOWED_PATHS):
            raise FuturesBlockedEndpointError(f"Blocked Databento endpoint: {path}")

    def _get_credential(self) -> DatabentoCredential:
        if self._credential is None:
            self._credential = resolve_databento_credential()
        return self._credential

    def _auth_headers(self) -> Dict[str, str]:
        cred = self._get_credential()
        token = base64.b64encode(f"{cred.api_key}:".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}", "Accept": "application/json"}

    def _sanitize(self, text: str) -> str:
        if self._credential and self._credential.api_key:
            return text.replace(self._credential.api_key, "***")
        return text

    def _default_transport(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]],
        timeout_s: float,
    ) -> DatabentoHTTPResponse:
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
            raise FuturesBlockedEndpointError(f"Refused HTTP redirect ({resp.status_code}) on Databento client")
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = resp.text
        return DatabentoHTTPResponse(
            status_code=int(resp.status_code),
            body=body,
            headers={str(k): str(v) for k, v in resp.headers.items()},
        )

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
    ) -> DatabentoHTTPResponse:
        self.validate_base_url(self.base_url)
        self.validate_request(method, path)
        if path == "/v0/timeseries.get_range" and not self.allow_billable_timeseries and self._transport is None:
            raise FuturesBlockedEndpointError(
                "Live /v0/timeseries.get_range blocked by default to prevent accidental Databento credit usage; "
                "set allow_billable_timeseries=True explicitly after preflight."
            )
        headers = self._auth_headers()
        url = f"{self.base_url}{path}"
        transport = self._transport or self._default_transport

        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self.rate_limiter.acquire()
            try:
                resp = transport("GET", url, headers, params, self.timeout_s)
            except FuturesBlockedEndpointError:
                raise
            except Exception as e:
                last_err = e
                low = str(e).lower()
                if attempt >= self.max_retries or not any(tok in low for tok in ("timeout", "timed out", "connection")):
                    raise FuturesAdapterError(self._sanitize(f"Databento request failed on {path}: {e}")) from e
                delay = self.base_backoff_s * (2 ** attempt) + random.uniform(0.0, 0.25 * self.base_backoff_s)
                self._sleeper(delay)
                continue

            msg = str((resp.body or {}).get("detail") or (resp.body or {}).get("message") or "") if isinstance(resp.body, dict) else str(resp.body)[:200]
            if resp.status_code == 200:
                return resp
            if resp.status_code == 401:
                raise FuturesAuthError(self._sanitize(f"Databento HTTP 401 unauthorized on {path}: {msg}"))
            if resp.status_code in (402, 403):
                raise FuturesSubscriptionError(self._sanitize(f"Databento HTTP {resp.status_code} entitlement error on {path}: {msg}"))
            if resp.status_code in (400, 422):
                raise FuturesInputError(self._sanitize(f"Databento HTTP {resp.status_code} invalid input on {path}: {msg}"))
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = FuturesRateLimitError(f"HTTP {resp.status_code}: {msg}")
                if attempt >= self.max_retries:
                    if resp.status_code == 429:
                        raise FuturesRateLimitError(self._sanitize(f"Databento HTTP 429 rate limit exhausted on {path}"))
                    raise FuturesAdapterError(self._sanitize(f"Databento HTTP {resp.status_code} failed on {path}: {msg}"))
                delay = self.base_backoff_s * (2 ** attempt) + random.uniform(0.0, 0.25 * self.base_backoff_s)
                self._sleeper(delay)
                continue
            raise FuturesAdapterError(self._sanitize(f"Databento HTTP {resp.status_code} on {path}: {msg}"))

        raise FuturesAdapterError(self._sanitize(f"Databento request failed on {path}: {last_err}"))
