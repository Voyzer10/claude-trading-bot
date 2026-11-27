# Universal Instrument Schema (`ml_data.instruments`)

## Overview
`Instrument` (`ml_data/instruments/schemas.py`) is the provider-independent canonical model for all supported asset classes across **US**, **India (`IN`)**, and **Crypto (`CRYPTO`)**.

- All financial numbers (`strike_price`, `contract_multiplier`, `lot_size`, `tick_size`, `minimum_order_quantity`, `quantity_step`) use `decimal.Decimal` (binary `float` is rejected).
- All timestamps (`last_verified_at`, `created_at`, `updated_at`, `valid_from`, `valid_until`) are timezone-aware UTC `datetime` objects.
- Contract dates (`expiry_date`, `last_trade_date`, `listing_date`, `delisting_date`) use `datetime.date`.

## Supported Categories
- **US**: `EQUITY`, `ETF`, `OPTION` (equity & index), `FUTURE`.
- **India (`IN`)**: `INDEX` (`NIFTY`, `BANKNIFTY`), `FUTURE` (`NIFTY`, `BANKNIFTY`), `OPTION` (`NIFTY`, `BANKNIFTY`). Individual Indian stock F&O is rejected by validation.
- **Crypto (`CRYPTO`)**: `CRYPTO_SPOT`, `CRYPTO_FUTURE` (dated), `CRYPTO_PERPETUAL` (no expiry).

## Deterministic Canonical Identity (`identity.py`)
`build_instrument_id(...)` produces collision-free IDs:
- Equity / ETF / Index: `{MARKET}:{VENUE_OR_EXCHANGE}:{ASSET_CLASS}:{CANONICAL_SYMBOL}`
- Option: `{MARKET}:{VENUE_OR_EXCHANGE}:OPTION:{UNDERLYING}:{YYYYMMDD}:{STRIKE}:{CALL|PUT}`
- Future: `{MARKET}:{VENUE_OR_EXCHANGE}:FUTURE:{UNDERLYING}:{YYYYMMDD}:{CANONICAL_SYMBOL}`
- Crypto Spot: `CRYPTO:{EXCHANGE}:CRYPTO_SPOT:{CANONICAL_SYMBOL}`
- Crypto Dated Future: `CRYPTO:{EXCHANGE}:DATED_FUTURE:{CANONICAL_SYMBOL}:{YYYYMMDD}`
- Crypto Perpetual: `CRYPTO:{EXCHANGE}:PERPETUAL:{CANONICAL_SYMBOL}`

Corporate ticker changes (e.g. `SQ` -> `XYZ`) and provider symbol changes are handled by keeping `ProviderInstrumentMapping` records with `valid_from`/`valid_until` windows pointing to the canonical `instrument_id`, or registering the successor ticker with `metadata` linkage without overwriting historical records.

## Synthetic JSON Examples

### 1. US Equity (`AAPL`)
```json
{
  "instrument_id": "US:NASDAQ:EQUITY:AAPL",
  "schema_version": "1.0.0",
  "market": "US",
  "asset_class": "EQUITY",
  "segment": "US_EQUITY",
  "exchange": "NASDAQ",
  "exchange_mic": "XNAS",
  "venue": "NASDAQ",
  "canonical_symbol": "AAPL",
  "trading_symbol": "AAPL",
  "display_name": "Apple Inc.",
  "price_currency": "USD",
  "tick_size": "0.01",
  "lot_size": "1",
  "contract_multiplier": "1",
  "contract_type": "EQUITY",
  "settlement_type": "PHYSICAL",
  "margin_type": "STANDARD",
  "is_tradable": true,
  "is_active": true,
  "instrument_status": "ACTIVE",
  "trading_calendar": "XNYS",
  "timezone": "America/New_York"
}
```

### 2. US Option (`AAPL` Call)
```json
{
  "instrument_id": "US:OPRA:OPTION:AAPL:20261218:220:CALL",
  "schema_version": "1.0.0",
  "market": "US",
  "asset_class": "OPTION",
  "segment": "US_OPTIONS",
  "exchange": "OPRA",
  "venue": "OPRA",
  "canonical_symbol": "AAPL261218C00220000",
  "trading_symbol": "AAPL261218C00220000",
  "display_name": "AAPL Dec 18 2026 220 Call",
  "underlying_instrument_id": "US:NASDAQ:EQUITY:AAPL",
  "price_currency": "USD",
  "expiry_date": "2026-12-18",
  "strike_price": "220",
  "option_right": "CALL",
  "contract_multiplier": "100",
  "tick_size": "0.01",
  "contract_type": "OPTION",
  "settlement_type": "PHYSICAL"
}
```

### 3. US Futures Contract (`ESZ26`)
```json
{
  "instrument_id": "US:CME:FUTURE:SPX:20261218:ESZ26",
  "schema_version": "1.0.0",
  "market": "US",
  "asset_class": "FUTURE",
  "segment": "US_FUTURES",
  "exchange": "CME",
  "exchange_mic": "XCME",
  "canonical_symbol": "ESZ26",
  "trading_symbol": "ESZ26",
  "display_name": "E-mini S&P 500 Dec 2026 Future",
  "underlying_instrument_id": "US:CBOE:INDEX:SPX",
  "price_currency": "USD",
  "expiry_date": "2026-12-18",
  "contract_multiplier": "50",
  "tick_size": "0.25",
  "contract_type": "DATED_FUTURE",
  "settlement_type": "CASH"
}
```

### 4. Indian NIFTY Option
```json
{
  "instrument_id": "IN:NFO:OPTION:NIFTY:20261203:24500:CALL",
  "schema_version": "1.0.0",
  "market": "IN",
  "asset_class": "OPTION",
  "segment": "IN_INDEX_OPTIONS",
  "exchange": "NFO",
  "exchange_mic": "XNSE",
  "canonical_symbol": "NIFTY26D0324500CE",
  "trading_symbol": "NIFTY26D0324500CE",
  "display_name": "NIFTY 03 Dec 2026 24500 CE",
  "underlying_instrument_id": "IN:NSE:INDEX:NIFTY",
  "price_currency": "INR",
  "expiry_date": "2026-12-03",
  "strike_price": "24500",
  "option_right": "CALL",
  "contract_multiplier": "1",
  "lot_size": "75",
  "tick_size": "0.05",
  "settlement_type": "CASH"
}
```

### 5. Indian BANKNIFTY Future
```json
{
  "instrument_id": "IN:NFO:FUTURE:BANKNIFTY:20261231:BANKNIFTY26DECFUT",
  "schema_version": "1.0.0",
  "market": "IN",
  "asset_class": "FUTURE",
  "segment": "IN_INDEX_FUTURES",
  "exchange": "NFO",
  "exchange_mic": "XNSE",
  "canonical_symbol": "BANKNIFTY26DECFUT",
  "trading_symbol": "BANKNIFTY26DECFUT",
  "display_name": "BANKNIFTY Dec 2026 Future",
  "underlying_instrument_id": "IN:NSE:INDEX:BANKNIFTY",
  "price_currency": "INR",
  "expiry_date": "2026-12-31",
  "contract_multiplier": "1",
  "lot_size": "30",
  "tick_size": "0.05",
  "settlement_type": "CASH"
}
```

### 6. Crypto Spot Pair (`BTC/USDT`)
```json
{
  "instrument_id": "CRYPTO:BINANCE:CRYPTO_SPOT:BTC/USDT",
  "schema_version": "1.0.0",
  "market": "CRYPTO",
  "asset_class": "CRYPTO_SPOT",
  "segment": "CRYPTO_SPOT",
  "exchange": "BINANCE",
  "canonical_symbol": "BTC/USDT",
  "trading_symbol": "BTCUSDT",
  "display_name": "Bitcoin / Tether Spot",
  "base_currency": "BTC",
  "quote_currency": "USDT",
  "settlement_currency": "USDT",
  "price_currency": "USDT",
  "tick_size": "0.01",
  "quantity_step": "0.00001",
  "contract_type": "SPOT",
  "settlement_type": "CRYPTO"
}
```

### 7. Crypto Perpetual (`BTCUSDT`)
```json
{
  "instrument_id": "CRYPTO:BINANCE_FUTURES:PERPETUAL:BTCUSDT",
  "schema_version": "1.0.0",
  "market": "CRYPTO",
  "asset_class": "CRYPTO_PERPETUAL",
  "segment": "CRYPTO_PERPETUALS",
  "exchange": "BINANCE",
  "venue": "BINANCE_FUTURES",
  "canonical_symbol": "BTCUSDT",
  "trading_symbol": "BTCUSDT",
  "display_name": "BTCUSDT Perpetual Swap",
  "underlying_instrument_id": "CRYPTO:BINANCE:CRYPTO_SPOT:BTC/USDT",
  "base_currency": "BTC",
  "quote_currency": "USDT",
  "settlement_currency": "USDT",
  "price_currency": "USDT",
  "contract_multiplier": "1",
  "tick_size": "0.1",
  "quantity_step": "0.001",
  "contract_type": "PERPETUAL",
  "settlement_type": "CRYPTO",
  "margin_type": "LINEAR",
  "is_inverse": false
}
```
