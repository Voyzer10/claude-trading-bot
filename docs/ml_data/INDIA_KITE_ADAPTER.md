# Indian NIFTY / BANKNIFTY Market Data Adapter (`ml_data.india`)

## Architecture
Read-only market data subsystem for **NIFTY 50** and **BANKNIFTY** indices, index futures, and index options (CE/PE) via Zerodha Kite Connect. Indian individual stock F&O and other indices (e.g. `FINNIFTY`, `NIFTYIT`) are strictly excluded.

### Modules
- `ml_data/india/config.py` — `KiteClientWrapper` (reuses `kite.py` `keys()` / `load_session()` / `forget_session()`), `KiteRateLimiter` (thread-safe 2 req/s historical, 1 req/s quote), `NSECalendar` (`Asia/Kolkata`, `09:15–15:30 IST`, holidays & special sessions).
- `ml_data/india/instrument_master.py` — `InstrumentMasterDownloader` (CSV validation, SHA-256 checksum, immutable daily `.csv.gz` + `manifest.json` snapshots under `data/raw/india/kite/instrument_master/date=YYYY-MM-DD/`, snapshot diffing).
- `ml_data/india/contract_discovery.py` — `ContractDiscovery` & `parse_kite_nfo_symbol` (exact `NIFTY`/`BANKNIFTY` root matching, `Decimal` strikes/lots/ticks, Identity v3 + `InstrumentRegistry` registration).
- `ml_data/adapters/india_kite.py` — `IndiaKiteAdapter(InstrumentAdapter)`.
- `ml_data/india/historical.py` — `KiteHistoricalDataClient` (chunked `minute`..`60minute` retrieval, `UTC` + `IST` timestamps, `Decimal` OHLC, optional `oi`, duplicate/missing/OHLC validation, checkpointing, `coverage_preflight`).
- `ml_data/india/archive.py` — `OptionContractArchive` & `ContractSelectionPolicy` (pre-expiry intraday archival with final-session verification; refuses unbounded all-strike downloads).
- `ml_data/india/live_bridge.py` — `KiteLiveBridge` (reuses `kite_ticker.parse_binary`, canonical token mapping, reconnects, staleness tracking, `3000` instruments/connection limit).

## Expired Options Retention Limitation
Kite Connect does **not** provide retrospective intraday candles for already-expired option contracts once removed from the active master. Storing an old `instrument_token` alone cannot recover expired option intraday history; `OptionContractArchive` must archive selected active contracts **before** expiry.

## Required Environment Variables (Names Only)
- `KITE_API_KEY`
- `KITE_API_SECRET`
*(Access token is session-bound per trading day via `trader/live/kite_session.json`.)*

## CLI Commands
```bash
python -m ml_data.india.instrument_master --dry-run
python -m ml_data.india.contract_discovery --dry-run
python -m ml_data.india.historical --help
```
