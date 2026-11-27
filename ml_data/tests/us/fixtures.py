"""Synthetic mocked Alpaca REST and WebSocket payloads for offline unit tests."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

# pyrefly: ignore[missing-import]
import msgpack

from ml_data.us.client import AlpacaHTTPResponse
from ml_data.us.config import AlpacaCredential

TEST_CRED = AlpacaCredential(key_id="PKTEST00000000000001", secret_key="TEST_SECRET_DO_NOT_EXPOSE", source="test")

ACTIVE_EQUITIES = [
    {
        "id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415",
        "class": "us_equity",
        "exchange": "NASDAQ",
        "symbol": "AAPL",
        "name": "Apple Inc. Common Stock",
        "status": "active",
        "tradable": True,
        "marginable": True,
        "shortable": True,
        "attributes": ["has_options"],
        "has_options": True,
        "options_late_close": False,
    },
    {
        "id": "b6d1aa75-5c9c-4353-8442-a6caa2a2a4d1",
        "class": "us_equity",
        "exchange": "NASDAQ",
        "symbol": "MSFT",
        "name": "Microsoft Corporation Common Stock",
        "status": "active",
        "tradable": True,
        "marginable": True,
        "shortable": True,
        "attributes": [],
        "has_options": True,
        "options_late_close": False,
    },
    {
        "id": "e1111111-1111-1111-1111-111111111111",
        "class": "us_equity",
        "exchange": "ARCA",
        "symbol": "SPY",
        "name": "SPDR S&P 500 ETF Trust",
        "status": "active",
        "tradable": True,
        "marginable": True,
        "shortable": True,
        "attributes": ["etf", "options_late_close"],
        "has_options": True,
        "options_late_close": True,
    },
    {
        "id": "e2222222-2222-2222-2222-222222222222",
        "class": "us_equity",
        "exchange": "NYSE",
        "symbol": "BRK.A",
        "name": "Berkshire Hathaway Inc.",
        "status": "active",
        "tradable": False,  # Not tradable on Alpaca, but data-available!
        "marginable": False,
        "shortable": False,
        "attributes": [],
        "has_options": False,
        "options_late_close": False,
    },
]

INACTIVE_EQUITIES = [
    {
        "id": "i1111111-1111-1111-1111-111111111111",
        "class": "us_equity",
        "exchange": "NASDAQ",
        "symbol": "OLDCO",
        "name": "Old Delisted Corp",
        "status": "inactive",
        "tradable": False,
        "marginable": False,
        "shortable": False,
        "attributes": [],
        "has_options": False,
        "options_late_close": False,
    }
]

US_INDICES = [
    {
        "id": "idx-spx-0001",
        "class": "us_index",
        "exchange": "INDEX",
        "symbol": "SPX",
        "name": "S&P 500 Index",
        "status": "active",
        "tradable": False,
        "has_options": True,
        "options_late_close": True,
    }
]

OPTION_CONTRACTS_PAGE1 = [
    {
        "id": "opt-aapl-std",
        "symbol": "AAPL261218C00200000",
        "name": "AAPL Dec 18 2026 200 Call",
        "status": "active",
        "tradable": True,
        "expiration_date": "2026-12-18",
        "root_symbol": "AAPL",
        "underlying_symbol": "AAPL",
        "type": "call",
        "style": "american",
        "strike_price": "200",
        "multiplier": "100",
        "size": "100",
        "open_interest": "1500",
        "close_price": "12.50",
        "deliverables": [{"type": "equity", "symbol": "AAPL", "amount": "100"}],
    },
    {
        "id": "opt-aapl-adj",
        "symbol": "AAPL1261218C00200000",
        "name": "AAPL1 Dec 18 2026 200 Call (Adjusted 50 sh)",
        "status": "active",
        "tradable": True,
        "expiration_date": "2026-12-18",
        "root_symbol": "AAPL1",
        "underlying_symbol": "AAPL",
        "type": "call",
        "style": "american",
        "strike_price": "200",
        "multiplier": "100",
        "size": "50",
        "deliverables": [{"type": "equity", "symbol": "AAPL", "amount": "50"}],
    },
]

OPTION_CONTRACTS_PAGE2 = [
    {
        "id": "opt-spy-put",
        "symbol": "SPY261218P00580000",
        "name": "SPY Dec 18 2026 580 Put",
        "status": "active",
        "tradable": True,
        "expiration_date": "2026-12-18",
        "root_symbol": "SPY",
        "underlying_symbol": "SPY",
        "type": "put",
        "style": "american",
        "strike_price": "580",
        "multiplier": "100",
        "size": "100",
        "deliverables": [{"type": "equity", "symbol": "SPY", "amount": "100"}],
    },
    {
        "id": "opt-spx-euro",
        "symbol": "SPX261218C06000000",
        "name": "SPX Dec 18 2026 6000 Call",
        "status": "active",
        "tradable": True,
        "expiration_date": "2026-12-18",
        "root_symbol": "SPX",
        "underlying_symbol": "SPX",
        "type": "call",
        "style": "european",
        "strike_price": "6000",
        "multiplier": "100",
        "size": "100",
        "deliverables": [{"type": "cash", "symbol": "USD", "amount": "100"}],
    },
]


class FakeAlpacaTransport:
    """In-memory mock transport for Alpaca Trading metadata and Market Data endpoints."""

    def __init__(self, *, block_sip: bool = False, block_opra: bool = False, rate_limit_once: bool = False):
        self.calls: List[Tuple[str, str, Optional[Dict[str, Any]]]] = []
        self.block_sip = block_sip
        self.block_opra = block_opra
        self.rate_limit_once = rate_limit_once
        self._429_done = False

    def __call__(self, method: str, url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]], timeout_s: float) -> AlpacaHTTPResponse:
        self.calls.append((method, url, dict(params or {})))
        p = params or {}
        base_hdr = {"X-RateLimit-Limit": "200", "X-RateLimit-Remaining": "199", "X-Request-ID": "req-test-1"}

        if self.rate_limit_once and not self._429_done:
            self._429_done = True
            return AlpacaHTTPResponse(429, {"message": "too many requests"}, {**base_hdr, "X-RateLimit-Remaining": "0"})

        if url.endswith("/v2/assets"):
            if p.get("asset_class") == "us_index":
                return AlpacaHTTPResponse(200, US_INDICES, base_hdr)
            if p.get("status") == "inactive":
                return AlpacaHTTPResponse(200, INACTIVE_EQUITIES, base_hdr)
            return AlpacaHTTPResponse(200, ACTIVE_EQUITIES, base_hdr)

        if url.endswith("/v2/options/contracts"):
            root = p.get("root_symbol")
            if root == "SPXW":
                return AlpacaHTTPResponse(200, {"option_contracts": []}, base_hdr)
            if root == "SPX":
                return AlpacaHTTPResponse(200, {"option_contracts": [OPTION_CONTRACTS_PAGE2[1]]}, base_hdr)
            if p.get("page_token") == "p2":
                return AlpacaHTTPResponse(200, {"option_contracts": OPTION_CONTRACTS_PAGE2, "next_page_token": None}, base_hdr)
            rows = OPTION_CONTRACTS_PAGE1
            if p.get("underlying_symbols"):
                wanted = set(str(p["underlying_symbols"]).split(","))
                all_c = OPTION_CONTRACTS_PAGE1 + OPTION_CONTRACTS_PAGE2
                return AlpacaHTTPResponse(
                    200,
                    {"option_contracts": [c for c in all_c if c["underlying_symbol"] in wanted], "next_page_token": None},
                    base_hdr,
                )
            return AlpacaHTTPResponse(200, {"option_contracts": rows, "next_page_token": "p2"}, base_hdr)

        if url.endswith("/v2/stocks/bars"):
            if self.block_sip and p.get("feed") == "sip":
                return AlpacaHTTPResponse(403, {"message": "subscription does not permit querying SIP"}, base_hdr)
            if p.get("page_token") == "b2":
                return AlpacaHTTPResponse(
                    200,
                    {
                        "bars": {"MSFT": [{"t": "2026-11-25T14:30:00Z", "o": 420.0, "h": 421.0, "l": 419.5, "c": 420.5, "v": 1500, "n": 10, "vw": 420.2}]},
                        "next_page_token": None,
                    },
                    base_hdr,
                )
            return AlpacaHTTPResponse(
                200,
                {
                    "bars": {"AAPL": [{"t": "2026-11-25T14:30:00Z", "o": 200.0, "h": 201.0, "l": 199.5, "c": 200.5, "v": 2000, "n": 20, "vw": 200.2}]},
                    "next_page_token": "b2",
                },
                base_hdr,
            )

        if url.endswith("/v1beta1/options/bars"):
            if self.block_opra and p.get("feed") == "opra":
                return AlpacaHTTPResponse(403, {"message": "subscription does not permit querying OPRA"}, base_hdr)
            sym = str(p.get("symbols", "")).split(",")[0]
            return AlpacaHTTPResponse(
                200,
                {"bars": {sym: [{"t": "2026-11-25T14:30:00Z", "o": 12.0, "h": 12.5, "l": 11.8, "c": 12.4, "v": 50, "n": 5, "vw": 12.2}]}, "next_page_token": None},
                base_hdr,
            )

        if url.endswith("/v1beta1/options/trades"):
            sym = str(p.get("symbols", "")).split(",")[0]
            return AlpacaHTTPResponse(
                200,
                {"trades": {sym: [{"t": "2026-11-25T14:30:01Z", "p": 12.4, "s": 10, "x": "C", "c": ["I"]}]}, "next_page_token": None},
                base_hdr,
            )

        if url.endswith("/v1beta1/options/quotes"):
            sym = str(p.get("symbols", "")).split(",")[0]
            return AlpacaHTTPResponse(
                200,
                {"quotes": {sym: [{"t": "2026-11-25T14:30:01Z", "bp": 12.3, "bs": 20, "bx": "C", "ap": 12.5, "as": 15, "ax": "C", "c": ["A"]}]}, "next_page_token": None},
                base_hdr,
            )

        if url.endswith("/v1beta1/options/snapshots"):
            syms = str(p.get("symbols", "")).split(",")
            snaps = {
                s: {
                    "latestQuote": {"t": "2026-11-25T14:30:01Z", "bp": 12.3, "ap": 12.5},
                    "latestTrade": {"t": "2026-11-25T14:30:01Z", "p": 12.4},
                    "impliedVolatility": 0.25,
                    "greeks": {"delta": 0.55},
                }
                for s in syms if s
            }
            return AlpacaHTTPResponse(200, {"snapshots": snaps}, base_hdr)

        return AlpacaHTTPResponse(404, {"message": f"not mocked: {url}"}, base_hdr)


def build_option_msgpack(items: List[Dict[str, Any]]) -> bytes:
    return msgpack.packb(items)
