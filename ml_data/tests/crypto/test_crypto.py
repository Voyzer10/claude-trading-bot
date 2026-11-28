"""Tests for CoinDCX Spot & Perpetual Futures, Coinbase Spot, and Binance deactivation."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest

from ml_data.adapters.coinbase import CoinbaseSpotAdapter
from ml_data.adapters.coindcx import CoinDCXFuturesAdapter, CoinDCXSpotAdapter
from ml_data.adapters.crypto_derivatives import CryptoDerivativesAdapter
from ml_data.crypto import (
    CRYPTO_DERIVATIVES_EVALUATIONS,
    CryptoBlockedEndpointError,
    CryptoCoveragePreflight,
    CryptoHTTPResponse,
    CryptoHistoricalClient,
    CryptoLiveBridge,
    CryptoRateLimiter,
    CryptoSpotDiscovery,
    CoinDCXDiscovery,
    CoinDCXHistoricalClient,
    CoinDCXLiveBridge,
    PublicCryptoHTTPClient,
    UTC_TZ,
    inspect_coindcx_credentials,
)
from ml_data.instruments import AssetClass, InstrumentRegistry


def _mock_crypto_transport(method, url, headers, params, timeout):
    if "api.exchange.coinbase.com/products/BTC-USD/candles" in url:
        return CryptoHTTPResponse(200, [[1764072000, "94000.00", "95000.00", "94200.00", "94800.00", "12.5"]], {})
    if "api.exchange.coinbase.com/products" in url:
        return CryptoHTTPResponse(200, [
            {"id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.0001", "status": "online", "trading_disabled": False},
            {"id": "ETH-USD", "base_currency": "ETH", "quote_currency": "USD", "base_increment": "0.000001", "quote_increment": "0.01", "base_min_size": "0.001", "status": "online", "trading_disabled": False},
        ], {})
    if "api.coindcx.com/exchange/v1/markets_details" in url:
        return CryptoHTTPResponse(200, [
            {"coindcx_name": "BTCUSDT", "pair": "KC-BTC_USDT", "base_currency_short_name": "USDT", "target_currency_short_name": "BTC", "status": "active", "step": 0.00001, "min_quantity": 0.0001, "base_currency_precision": 2, "target_currency_precision": 5, "min_notional": 10},
            {"coindcx_name": "ETHUSDT", "pair": "KC-ETH_USDT", "base_currency_short_name": "USDT", "target_currency_short_name": "ETH", "status": "active", "step": 0.0001, "min_quantity": 0.001, "base_currency_precision": 2, "target_currency_precision": 4, "min_notional": 10},
        ], {})
    if "api.coindcx.com/exchange/v1/markets" in url:
        return CryptoHTTPResponse(200, ["BTCUSDT", "ETHUSDT"], {})
    if "api.coindcx.com/exchange/v1/derivatives/futures/data/active_instruments" in url:
        mc = (params or {}).get("margin_currency_short_name[]")
        if mc == "USDT":
            return CryptoHTTPResponse(200, ["B-BTC_USDT", "B-ETH_USDT"], {})
        return CryptoHTTPResponse(200, [], {})
    if "api.coindcx.com/exchange/v1/derivatives/futures/data/instrument" in url:
        pair = (params or {}).get("pair")
        base = "BTC" if "BTC" in pair else "ETH"
        return CryptoHTTPResponse(200, {"instrument": {
            "pair": pair, "position_currency_short_name": base, "quote_currency_short_name": "USDT",
            "settlement_currency_short_name": "USDT", "margin_currency_short_name": "USDT",
            "kind": "perpetual", "settlement": "never", "unit_value": "1",
            "quantity_increment": "0.001", "price_increment": "0.1", "min_trade_size": "0.001",
            "is_inverse": False, "is_quanto": False, "funding_frequency": 8, "status": "active", "exit_only": False,
        }}, {})
    if url.endswith("/market_data/candles"):
        st_ms = int((params or {}).get("startTime") or 1764072000000)
        return CryptoHTTPResponse(200, [
            {"time": st_ms + 300_000, "open": 94800.0, "high": 95000.0, "low": 94700.0, "close": 94950.0, "volume": 5.2},
            {"time": st_ms, "open": 94200.0, "high": 94850.0, "low": 94100.0, "close": 94800.0, "volume": 4.1},
        ], {})
    if url.endswith("/market_data/candlesticks"):
        fr_s = int((params or {}).get("from") or 1764072000)
        return CryptoHTTPResponse(200, {"s": "ok", "data": [
            {"time": fr_s, "open": "94200", "high": "94500", "low": "94100", "close": "94400", "volume": "10"},
            {"time": fr_s + 300, "open": "94400", "high": "94700", "low": "94300", "close": "94600", "volume": "12"},
            {"time": fr_s + 600, "open": "94600", "high": "94900", "low": "94500", "close": "94850", "volume": "8"},
        ]}, {})
    return CryptoHTTPResponse(404, {}, {})


def test_binance_deactivated_and_coindcx_spot_futures_flow(tmp_path, monkeypatch):
    assert CRYPTO_DERIVATIVES_EVALUATIONS["coindcx"].selected is True
    assert CRYPTO_DERIVATIVES_EVALUATIONS["binance_usdm"].selected is False

    monkeypatch.setenv("COINDCX_API_KEY", "cdx_key_test")
    monkeypatch.setenv("COINDCX_API_SECRET", "cdx_secret_test")
    assert inspect_coindcx_credentials()["COINDCX_API_KEY/COINDCX_API_SECRET"] == "PRESENT"

    client = PublicCryptoHTTPClient(
        transport=_mock_crypto_transport,
        rate_limiter=CryptoRateLimiter(requests_per_second=1000, sleeper=lambda _: None),
    )

    # Binance hosts & private/POST paths strictly blocked
    with pytest.raises(CryptoBlockedEndpointError):
        client.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
    with pytest.raises(CryptoBlockedEndpointError):
        client.get("https://dapi.binance.com/dapi/v1/exchangeInfo")
    with pytest.raises(CryptoBlockedEndpointError):
        PublicCryptoHTTPClient.validate_url("https://api.coindcx.com/exchange/v1/orders/create", "POST")

    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))
    cb_rep = CryptoSpotDiscovery(client=client).discover(registry=reg)
    cdx_spot = CoinDCXDiscovery(client=client).discover_spot(registry=reg)
    cdx_fut = CoinDCXDiscovery(client=client).discover_futures(registry=reg)

    btc_cb = next(i for i in cb_rep.instruments if i.trading_symbol == "BTC-USD")
    btc_cdx_spot = next(i for i in cdx_spot.spot_instruments if i.trading_symbol == "BTCUSDT")
    btc_cdx_perp = next(i for i in cdx_fut.perpetual_instruments if i.trading_symbol == "B-BTC_USDT")

    assert len({btc_cb.instrument_id, btc_cdx_spot.instrument_id, btc_cdx_perp.instrument_id}) == 3
    assert btc_cdx_perp.asset_class == AssetClass.CRYPTO_PERPETUAL
    assert btc_cdx_perp.expiry_date is None
    assert btc_cdx_perp.metadata["funding_frequency"] == 8
    assert cdx_fut.dated_futures_status == "UNSUPPORTED"

    # Historical spot (descending -> chronological ascending, ms) and futures (seconds + derived 15m)
    cdx_hist = CoinDCXHistoricalClient(client=client, registry=reg, checkpoint_dir=str(tmp_path / "ckpts"))
    s = datetime(2025, 11, 25, 12, 0, tzinfo=UTC_TZ)
    e = datetime(2025, 11, 25, 12, 30, tzinfo=UTC_TZ)
    spot_bars = cdx_hist.fetch_spot_candles("KC-BTC_USDT", interval="5m", start=s, end=e)
    assert len(spot_bars) == 2
    assert spot_bars[0].ts_utc < spot_bars[1].ts_utc  # sorted chronologically ascending!
    assert spot_bars[0].open == Decimal("94200.0")

    fut_15m = cdx_hist.fetch_futures_candles("B-BTC_USDT", interval="15m", start=s, end=e)
    assert len(fut_15m) == 1
    assert fut_15m[0].open == Decimal("94200") and fut_15m[0].close == Decimal("94850")
    assert fut_15m[0].volume == Decimal("30")
    assert cdx_hist.last_metadata["historical_funding_status"] == "UNSUPPORTED"
    assert cdx_hist.last_metadata["historical_oi_status"] == "UNSUPPORTED"

    # CoinDCX WebSocket & Coinbase WebSocket
    cdx_ws = CoinDCXLiveBridge(registry=reg)
    ev = cdx_ws.on_event("candlestick", {"pair": "B-BTC_USDT", "c": "94900.5", "T": 1764072600000})
    assert ev["instrument_id"] == btc_cdx_perp.instrument_id and ev["price"] == Decimal("94900.5")

    cb_hist = CryptoHistoricalClient(client=client, registry=reg)
    assert len(cb_hist.fetch_coinbase_candles("BTC-USD", granularity_s=300, start=s, end=e)) == 1

    # Adapters
    assert len(CoinbaseSpotAdapter(client=client).fetch_crypto_spot()) == 2
    assert len(CoinDCXSpotAdapter(client=client).fetch_crypto_spot()) == 2
    assert len(CoinDCXFuturesAdapter(client=client).fetch_crypto_derivatives()) == 2
    assert len(CryptoDerivativesAdapter(client=client).fetch_crypto_derivatives()) == 2

    # Coverage preflight checks Coinbase + CoinDCX (no Binance)
    cov = CryptoCoveragePreflight(client=client).check_providers()
    assert set(cov.keys()) == {"coinbase_spot", "coindcx_spot", "coindcx_futures"}
    assert all(v["status"] == "VERIFIED" for v in cov.values())
    reg.close()
