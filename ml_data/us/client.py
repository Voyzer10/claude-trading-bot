"""Read-only Alpaca HTTP client separating Trading metadata and Market Data hosts."""
from __future__ import annotations

import json
import random
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple

import requests

from .config import AlpacaCredential, AlpacaRateLimiter, resolve_alpaca_credential
from .exceptions import (
    AlpacaAdapterError,
    AlpacaAuthError,
    AlpacaBlockedEndpointError,
    AlpacaInputError,
    AlpacaPaginationIncompleteError,
    AlpacaRateLimitError,
    AlpacaSubscriptionError,
)

TRADING_PAPER_BASE = "https://paper-api.alpaca.markets"
MARKET_DATA_BASE = "https://data.alpaca.markets"

APPROVED_TRADING_HOSTS: FrozenSet[str] = frozenset({"paper-api.alpaca.markets"})
APPROVED_DATA_HOSTS: FrozenSet[str] = frozenset({"data.alpaca.markets"})

_ALLOWED_TRADING_PATHS = (
    re.compile(r"^/v2/assets$"),
    re.compile(r"^/v2/assets/[^/]+$"),
    re.compile(r"^/v2/options/contracts$"),
    re.compile(r"^/v2/options/contracts/[^/]+$"),
)

_ALLOWED_DATA_PATHS = (
    re.compile(r"^/v2/stocks/bars$"),
    re.compile(r"^/v2/stocks/snapshots$"),
    re.compile(r"^/v1beta1/options/bars$"),
    re.compile(r"^/v1beta1/options/trades$"),
    re.compile(r"^/v1beta1/options/quotes$"),
    re.compile(r"^/v1beta1/options/snapshots$"),
    re.compile(r"^/v1beta1/options/snapshots/[^/]+$"),
)

TransportCallable = Callable[[str, str, Dict[str, str], Optional[Dict[str, Any]], float], "AlpacaHTTPResponse"]


@dataclass(frozen=True)
class AlpacaHTTPResponse:
    status_code: int
    body: Any
    headers: Dict[str, str]


@dataclass(frozen=True)
class PaginatedResult:
    items: List[Any]
    pages_fetched: int
    pagination_complete: bool
    last_page_token: Optional[str] = None


class AlpacaDataClient:
    """Read-only Alpaca REST client with strict host/path allowlists, rate-limit tracking, and bounded retries."""

    def __init__(
        self,
        *,
        credential: Optional[AlpacaCredential] = None,
        trading_base_url: str = TRADING_PAPER_BASE,
        data_base_url: str = MARKET_DATA_BASE,
        approved_sandbox_hosts: FrozenSet[str] = frozenset(),
        rate_limiter: Optional[AlpacaRateLimiter] = None,
        transport: Optional[TransportCallable] = None,
        max_retries: int = 3,
        base_backoff_s: float = 0.5,
        timeout_s: float = 15.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._credential = credential
        self._approved_sandbox_hosts = frozenset(h.strip().lower() for h in approved_sandbox_hosts if h.strip())
        self.trading_base_url = trading_base_url.rstrip("/")
        self.data_base_url = data_base_url.rstrip("/")
        self.validate_base_url(self.trading_base_url, "trading", self._approved_sandbox_hosts)
        self.validate_base_url(self.data_base_url, "data", self._approved_sandbox_hosts)
        self.rate_limiter = rate_limiter or AlpacaRateLimiter()
        self._transport = transport
        self.max_retries = max(0, int(max_retries))
        self.base_backoff_s = max(0.05, float(base_backoff_s))
        self.timeout_s = float(timeout_s)
        self._sleeper = sleeper
        self._session: Optional[requests.Session] = None

    @staticmethod
    def validate_base_url(
        base_url: str,
        target: str,
        approved_sandbox_hosts: FrozenSet[str] = frozenset(),
    ) -> None:
        u = urllib.parse.urlsplit(base_url)
        if u.scheme.lower() != "https":
            raise AlpacaBlockedEndpointError(f"Only HTTPS is permitted for Alpaca {target} URL (got {u.scheme!r})")
        if u.username or u.password or u.port is not None or u.query or u.fragment:
            raise AlpacaBlockedEndpointError(f"Unexpected URL components in Alpaca {target} base URL: {base_url!r}")
        host = (u.hostname or "").strip().lower()
        allowed = (APPROVED_TRADING_HOSTS if target == "trading" else APPROVED_DATA_HOSTS) | approved_sandbox_hosts
        if host not in allowed:
            raise AlpacaBlockedEndpointError(
                f"Unapproved Alpaca {target} host {host!r}; credentials will not be sent"
            )

    def _get_credential(self) -> AlpacaCredential:
        if self._credential is None:
            self._credential = resolve_alpaca_credential()
        return self._credential

    def _sanitize(self, text: str) -> str:
        cred = self._credential
        if cred is None:
            return text
        out = text
        if cred.secret_key:
            out = out.replace(cred.secret_key, "***")
        if cred.key_id:
            out = out.replace(cred.key_id, f"{cred.key_id[:4]}***")
        return out

    @staticmethod
    def validate_request(method: str, target: str, path: str) -> None:
        m = method.strip().upper()
        if m != "GET":
            raise AlpacaBlockedEndpointError(f"Only GET is permitted by read-only Alpaca client (got {m})")
        if target == "trading":
            if not any(p.fullmatch(path) for p in _ALLOWED_TRADING_PATHS):
                raise AlpacaBlockedEndpointError(f"Blocked non-metadata trading path: {path}")
        elif target == "data":
            if not any(p.fullmatch(path) for p in _ALLOWED_DATA_PATHS):
                raise AlpacaBlockedEndpointError(f"Blocked non-market-data path: {path}")
        else:
            raise AlpacaBlockedEndpointError(f"Unknown Alpaca API target: {target!r}")

    def _default_transport(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]],
        timeout_s: float,
    ) -> AlpacaHTTPResponse:
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
            raise AlpacaBlockedEndpointError(f"Refused HTTP redirect ({resp.status_code}) on read-only Alpaca client")
        try:
            payload = resp.json() if resp.content else {}
        except ValueError:
            payload = {"raw_text": resp.text[:300]}
        return AlpacaHTTPResponse(
            status_code=int(resp.status_code),
            body=payload,
            headers={str(k): str(v) for k, v in resp.headers.items()},
        )

    def request(
        self,
        target: str,
        path: str,
        *,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
    ) -> AlpacaHTTPResponse:
        self.validate_request(method, target, path)
        base = self.trading_base_url if target == "trading" else self.data_base_url
        self.validate_base_url(base, target, self._approved_sandbox_hosts)
        cred = self._get_credential()
        url = f"{base}{path}"
        headers = {**cred.headers(), "Accept": "application/json"}
        transport = self._transport or self._default_transport

        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self.rate_limiter.acquire()
            try:
                resp = transport("GET", url, headers, params, self.timeout_s)
            except AlpacaBlockedEndpointError:
                raise
            except Exception as e:
                last_err = e
                low = str(e).lower()
                if attempt >= self.max_retries or not any(
                    tok in low for tok in ("timeout", "timed out", "connection", "temporarily")
                ):
                    raise AlpacaAdapterError(self._sanitize(f"Alpaca request error on {path}: {e}")) from e
                delay = self.base_backoff_s * (2 ** attempt) + random.uniform(0.0, 0.25 * self.base_backoff_s)
                self._sleeper(delay)
                continue

            self.rate_limiter.update_from_headers(resp.headers)
            req_id = resp.headers.get("X-Request-ID") or resp.headers.get("APCA-Request-ID") or ""
            msg = ""
            if isinstance(resp.body, dict):
                msg = str(resp.body.get("message") or resp.body.get("error") or "")

            if resp.status_code == 200:
                return resp
            if resp.status_code == 401:
                raise AlpacaAuthError(self._sanitize(f"Alpaca HTTP 401 unauthorized on {path} (req={req_id}): {msg}"))
            if resp.status_code in (402, 403):
                low_m = msg.lower()
                if any(tok in low_m for tok in ("subscription", "entitle", "sip", "opra", "feed", "permit", "upgrade")):
                    raise AlpacaSubscriptionError(
                        self._sanitize(f"Alpaca HTTP {resp.status_code} subscription/entitlement error on {path}: {msg}")
                    )
                raise AlpacaAuthError(self._sanitize(f"Alpaca HTTP {resp.status_code} forbidden on {path}: {msg}"))
            if resp.status_code in (400, 422):
                raise AlpacaInputError(self._sanitize(f"Alpaca HTTP {resp.status_code} invalid input on {path}: {msg}"))
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = AlpacaRateLimitError(f"HTTP {resp.status_code}: {msg}")
                if attempt >= self.max_retries:
                    if resp.status_code == 429:
                        raise AlpacaRateLimitError(
                            self._sanitize(f"Alpaca HTTP 429 rate limit exhausted on {path} (req={req_id})")
                        )
                    raise AlpacaAdapterError(
                        self._sanitize(f"Alpaca HTTP {resp.status_code} failed on {path} (req={req_id}): {msg}")
                    )
                delay = self.base_backoff_s * (2 ** attempt) + random.uniform(0.0, 0.25 * self.base_backoff_s)
                self._sleeper(delay)
                continue

            raise AlpacaAdapterError(
                self._sanitize(f"Alpaca HTTP {resp.status_code} on {path} (req={req_id}): {msg}")
            )

        raise AlpacaAdapterError(self._sanitize(f"Alpaca request failed on {path}: {last_err}"))

    def get_paginated(
        self,
        target: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        items_key: Optional[str] = None,
        max_pages: int = 500,
        raise_on_incomplete: bool = False,
    ) -> PaginatedResult:
        """Follow next_page_token until exhausted; detect repeated tokens and incomplete pagination."""
        q = dict(params or {})
        pages_fetched = 0
        collected: List[Any] = []
        token: Optional[str] = None
        seen_tokens: Set[str] = set()
        for _ in range(max_pages):
            if token:
                q["page_token"] = token
            else:
                q.pop("page_token", None)
            resp = self.request(target, path, method="GET", params=q)
            pages_fetched += 1
            body = resp.body
            if items_key and isinstance(body, dict):
                chunk = body.get(items_key)
                if isinstance(chunk, list):
                    collected.extend(chunk)
                elif isinstance(chunk, dict):
                    collected.append(chunk)
            else:
                collected.append(body)
            nxt = body.get("next_page_token") if isinstance(body, dict) else None
            token = str(nxt) if nxt else None
            if not token:
                return PaginatedResult(
                    items=collected,
                    pages_fetched=pages_fetched,
                    pagination_complete=True,
                    last_page_token=None,
                )
            if token in seen_tokens:
                raise AlpacaPaginationIncompleteError(
                    f"Repeated next_page_token {token!r} on {path} after {pages_fetched} pages"
                )
            seen_tokens.add(token)

        if raise_on_incomplete:
            raise AlpacaPaginationIncompleteError(
                f"Pagination incomplete on {path}: reached max_pages={max_pages} with remaining next_page_token={token!r}"
            )
        return PaginatedResult(
            items=collected,
            pages_fetched=pages_fetched,
            pagination_complete=False,
            last_page_token=token,
        )
