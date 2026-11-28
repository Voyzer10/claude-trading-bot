"""Tests for safe read-only multi-market preflight runner."""
from __future__ import annotations

from ml_data.preflight import run_all_preflights, run_coindcx_preflight
from ml_data.tests.crypto.test_crypto import _mock_crypto_transport
from ml_data.crypto import CryptoRateLimiter, PublicCryptoHTTPClient


def test_offline_and_mocked_preflight(monkeypatch):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    off = run_all_preflights(live=False)
    assert off["databento"]["status"] == "DEFERRED_BY_USER"
    assert off["mode"] == "offline_credential_inspection_only"

    client = PublicCryptoHTTPClient(
        transport=_mock_crypto_transport,
        rate_limiter=CryptoRateLimiter(requests_per_second=1000, sleeper=lambda _: None),
    )
    cdx = run_coindcx_preflight(client=client)
    assert cdx["status"] == "VERIFIED_WITH_DATA"
    assert cdx["spot_btc_eth_count"] == 2
    assert cdx["perpetual_btc_eth_count"] == 2
    assert cdx["dated_futures_status"] == "UNSUPPORTED"
    assert cdx["historical_funding_status"] == "UNSUPPORTED"
