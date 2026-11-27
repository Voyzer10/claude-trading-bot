"""Tests for AlpacaDataClient security guards, credential inspection, 429 retries, and entitlement classification."""
from __future__ import annotations

import pytest

from ml_data.us import (
    AlpacaBlockedEndpointError,
    AlpacaDataClient,
    AlpacaHTTPResponse,
    AlpacaPaginationIncompleteError,
    AlpacaRateLimiter,
    AlpacaSubscriptionError,
    inspect_alpaca_credentials,
)
from ml_data.tests.us.fixtures import FakeAlpacaTransport, TEST_CRED


def test_credential_inspection_never_exposes_secrets(monkeypatch):
    monkeypatch.setenv("ALPACA_KEY_ID", "PK_FAKE_ID_12345")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "SUPER_SECRET_VALUE_999")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)

    status = inspect_alpaca_credentials(v6_cred_path="/nonexistent/v6.json")
    assert status["ALPACA_KEY_ID/ALPACA_SECRET_KEY"] == "PRESENT"
    assert status["ALPACA_API_KEY/ALPACA_API_SECRET"] == "ABSENT"
    assert "SUPER_SECRET_VALUE_999" not in repr(status)
    assert "SUPER_SECRET_VALUE_999" not in repr(TEST_CRED)


def test_read_only_guards_429_retry_and_entitlement_errors():
    tr = FakeAlpacaTransport(block_sip=True, block_opra=True, rate_limit_once=True)
    rl = AlpacaRateLimiter(requests_per_minute=6000, sleeper=lambda _: None)
    client = AlpacaDataClient(credential=TEST_CRED, transport=tr, rate_limiter=rl, base_backoff_s=0.05, sleeper=lambda _: None)

    # Non-GET and order paths blocked before any transport call
    for bad_method in ("POST", "PATCH", "PUT", "DELETE"):
        with pytest.raises(AlpacaBlockedEndpointError):
            client.request("trading", "/v2/assets", method=bad_method)
    with pytest.raises(AlpacaBlockedEndpointError):
        client.request("trading", "/v2/orders", method="GET")
    with pytest.raises(AlpacaBlockedEndpointError):
        client.request("trading", "/v2/account", method="GET")
    assert tr.calls == []

    # 429 retries and succeeds on second attempt
    resp = client.request("trading", "/v2/assets", params={"asset_class": "us_equity", "status": "active"})
    assert resp.status_code == 200
    assert len(tr.calls) == 2

    # SIP/OPRA 403 classified as AlpacaSubscriptionError without secret leakage
    with pytest.raises(AlpacaSubscriptionError) as exc_s:
        client.request("data", "/v2/stocks/bars", params={"symbols": "AAPL", "feed": "sip"})
    assert TEST_CRED.secret_key not in str(exc_s.value)

    with pytest.raises(AlpacaSubscriptionError):
        client.request("data", "/v1beta1/options/bars", params={"symbols": "AAPL261218C00200000", "feed": "opra"})


def test_host_security_and_pagination_completeness():
    captured_calls = []

    def _spy_transport(method, url, headers, params, timeout):
        captured_calls.append((url, headers))
        return AlpacaHTTPResponse(200, {}, {})

    # Attacker-controlled / non-HTTPS / userinfo / port URLs must be rejected before sending credentials
    for bad_kw in (
        {"trading_base_url": "https://evil.attacker.com"},
        {"data_base_url": "https://evil.attacker.com"},
        {"trading_base_url": "http://paper-api.alpaca.markets"},
        {"data_base_url": "https://user:pass@data.alpaca.markets"},
        {"data_base_url": "https://data.alpaca.markets:8443"},
    ):
        with pytest.raises(AlpacaBlockedEndpointError):
            AlpacaDataClient(credential=TEST_CRED, transport=_spy_transport, **bad_kw)
    assert captured_calls == []

    # Sandbox host allowed only when explicitly configured
    sb_client = AlpacaDataClient(
        credential=TEST_CRED,
        data_base_url="https://data.sandbox.alpaca.markets",
        approved_sandbox_hosts=frozenset({"data.sandbox.alpaca.markets"}),
        transport=_spy_transport,
    )
    assert sb_client.request("data", "/v2/stocks/bars").status_code == 200

    # Pagination completeness cases
    def _pag_transport(mode):
        state = {"n": 0}
        def _fn(method, url, headers, params, timeout):
            state["n"] += 1
            if mode == "one_page":
                return AlpacaHTTPResponse(200, {"items": [1], "next_page_token": None}, {})
            if mode == "multi_empty_final":
                if state["n"] == 1:
                    return AlpacaHTTPResponse(200, {"items": [1, 2], "next_page_token": "t2"}, {})
                return AlpacaHTTPResponse(200, {"items": [], "next_page_token": None}, {})
            if mode == "repeated_token":
                return AlpacaHTTPResponse(200, {"items": [1], "next_page_token": "same"}, {})
            return AlpacaHTTPResponse(200, {"items": [state["n"]], "next_page_token": f"t{state['n']}"}, {})
        return _fn

    c1 = AlpacaDataClient(credential=TEST_CRED, transport=_pag_transport("one_page"), rate_limiter=AlpacaRateLimiter(requests_per_minute=6000, sleeper=lambda _: None))
    r1 = c1.get_paginated("data", "/v2/stocks/bars", items_key="items")
    assert r1.pagination_complete is True and r1.pages_fetched == 1 and r1.items == [1]

    c2 = AlpacaDataClient(credential=TEST_CRED, transport=_pag_transport("multi_empty_final"), rate_limiter=AlpacaRateLimiter(requests_per_minute=6000, sleeper=lambda _: None))
    r2 = c2.get_paginated("data", "/v2/stocks/bars", items_key="items")
    assert r2.pagination_complete is True and r2.pages_fetched == 2 and r2.items == [1, 2]

    c3 = AlpacaDataClient(credential=TEST_CRED, transport=_pag_transport("repeated_token"), rate_limiter=AlpacaRateLimiter(requests_per_minute=6000, sleeper=lambda _: None))
    with pytest.raises(AlpacaPaginationIncompleteError):
        c3.get_paginated("data", "/v2/stocks/bars", items_key="items")

    c4 = AlpacaDataClient(credential=TEST_CRED, transport=_pag_transport("truncated"), rate_limiter=AlpacaRateLimiter(requests_per_minute=6000, sleeper=lambda _: None))
    r4 = c4.get_paginated("data", "/v2/stocks/bars", items_key="items", max_pages=2)
    assert r4.pagination_complete is False and r4.last_page_token == "t2"
    with pytest.raises(AlpacaPaginationIncompleteError):
        c4.get_paginated("data", "/v2/stocks/bars", items_key="items", max_pages=2, raise_on_incomplete=True)
