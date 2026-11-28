"""Read-only coverage preflight for Coinbase Spot and CoinDCX Spot & Perpetual Futures."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .config import COINBASE_REST_BASE, COINDCX_API_BASE, PublicCryptoHTTPClient
from .exceptions import CryptoAdapterError, CryptoGeoBlockedError


class CryptoCoveragePreflight:
    """Non-billable public endpoint preflight for Coinbase Spot and CoinDCX Spot/Futures."""

    def __init__(self, *, client: Optional[PublicCryptoHTTPClient] = None) -> None:
        self.client = client or PublicCryptoHTTPClient()

    def check_providers(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for name, url, params in (
            ("coinbase_spot", f"{COINBASE_REST_BASE}/products", None),
            ("coindcx_spot", f"{COINDCX_API_BASE}/exchange/v1/markets_details", None),
            (
                "coindcx_futures",
                f"{COINDCX_API_BASE}/exchange/v1/derivatives/futures/data/active_instruments",
                {"margin_currency_short_name[]": "USDT"},
            ),
        ):
            try:
                resp = self.client.get(url, params=params)
                out[name] = {"status": "VERIFIED", "http_status": resp.status_code}
            except CryptoGeoBlockedError as e:
                out[name] = {"status": "BLOCKED_BY_LICENSING", "error": str(e)}
            except CryptoAdapterError as e:
                out[name] = {"status": "UNAVAILABLE", "error": str(e)}
        return out
