# Alpaca US Equities, ETFs, Indices & Options Adapter (`ml_data/us`)

## 1. Scope & Architecture
- **In Scope**: US listed equities (NYSE, NASDAQ, ARCA, BATS, IEX, etc.), US ETFs, US index assets (`us_index` / `INDEX`), US equity/ETF options, and US index options (`SPX`, `SPXW`, etc. where supported).
- **Out of Scope**: US futures, Indian markets (handled by `ml_data/india`), Crypto, order placement, and V4/V6 execution logic.
- **Read-Only Security Boundary**:
  - `AlpacaDataClient` (`ml_data/us/client.py`) allows **only** `GET` requests to explicitly allowlisted metadata paths (`/v2/assets`, `/v2/options/contracts`) on `paper-api.alpaca.markets` and market-data paths (`/v2/stocks/...`, `/v1beta1/options/...`) on `data.alpaca.markets`.
  - Refuses `POST`, `PATCH`, `PUT`, `DELETE`, redirects, and any order/account/position paths.
  - Reuses existing `v6_runtime.data.alpaca.load_credential` (when present) or `ALPACA_KEY_ID`/`ALPACA_SECRET_KEY` and `ALPACA_API_KEY`/`ALPACA_API_SECRET` without logging or exposing secrets.

## 2. Feed & Entitlement Policy
- **Stock Feeds**: `iex` (Basic plan), `sip`, `delayed_sip` (Algo Trader Plus).
- **Option Feeds**: `indicative` (Basic plan — derived/modified quotes, not equivalent to OPRA), `opra` (Algo Trader Plus).
- Every historical and live request passes an **explicit `feed`** parameter (aligned with Alpaca's Nov 10, 2026 default-feed changes) and never silently falls back between feeds.
- **Adjustments**: `raw`, `split`, `dividend`, `all` are stored as explicit dataset/checkpoint dimensions and never silently mixed.

## 3. Licensing & Commercial Research Notice
- Personal Basic and Algo Trader Plus plans cover personal internal research and personal algorithmic trading only.
- Commercial financial products or multi-user data redistribution are **not** assumed to be covered and require separate exchange/OPRA/SIP licensing review before any commercial deployment.

## 4. Storage & Checkpoints
- Raw daily asset snapshots: `data/raw/us/alpaca/equities/date=YYYY-MM-DD/assets.json.gz`
- Manifests: `data/manifests/us/alpaca/date=YYYY-MM-DD/assets_manifest.json`
- Historical checkpoints key on `(instrument_ids, timeframe, start, end, feed, adjustment, asof, snapshot_version)`.
