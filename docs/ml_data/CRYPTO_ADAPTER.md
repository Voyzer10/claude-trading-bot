# Crypto Spot & Derivatives Adapters (`ml_data/crypto`)

## 1. Scope & Providers
- **Spot**: Reuses `coinbase.py` public endpoints (`https://api.exchange.coinbase.com`, `wss://ws-feed.exchange.coinbase.com`, no API key).
- **Derivatives Evaluation (verified 2026-11-28)**: Evaluated Binance USDⓈ-M (`fapi.binance.com`), Binance COIN-M (`dapi.binance.com`), and Deribit (`www.deribit.com`). Selected **Binance USDⓈ-M (linear)** and **Binance COIN-M (inverse)** public market-data endpoints, with Deribit retained as extensible alternative.
- **Note**: Public market-data access does not imply trading eligibility in restricted jurisdictions (HTTP 451 geo-blocks are classified as `BLOCKED_BY_LICENSING`).

## 2. Instrument Identity & Units
- Spot (`BTC/USD`), linear perpetuals (`BTCUSDT`), inverse perpetuals (`BTCUSD_PERP`), and dated futures (`BTCUSDT_261225`) map to distinct Identity v3 IDs and never collide.
- Linear (`base_asset`) and inverse (`contracts_usd`) quantities are preserved separately without conflating units.
- Funding rates (`fundingRate`, `markPrice`) and open interest (`openInterest`) are never fabricated when absent.
