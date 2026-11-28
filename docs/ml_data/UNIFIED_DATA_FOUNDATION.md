# Unified Cross-Market Data Foundation (`ml_data/storage`, `ml_data/calendars`)

## 1. Canonical Schemas & Precision
- `CanonicalCandle`, `CanonicalQuote`, and `CanonicalTrade` (`ml_data/storage/canonical_schema.py`) enforce `Decimal` end-to-end (no binary floats) and timezone-aware `UTC` timestamps.
- `resample_candles()` derives `5m`, `15m`, `1h` deterministically within `(instrument_id, trading_date, session_id)` without aggregating across closed sessions or fabricating zero-volume bars.

## 2. PyArrow / Parquet Storage & Manifests
- Install Phase 1 research/storage dependencies in an isolated environment via `pip install -r ml_data/requirements.txt`.
- `ml_data/storage/parquet.py` writes Zstandard-compressed Parquet with `pa.decimal128(38, 12)` (raising `PrecisionLossError` if scale > 12 or precision > 38) and atomic `.tmp` + `os.replace`.
- `CanonicalCandleStore` partitions under `data/canonical/candles/market=<M>/asset_class=<AC>/trading_date=<YYYY-MM-DD>/timeframe=<TF>/` with content-addressed partition hashes and immutable version conflict detection.
- **Quote/Trade Persistence Scope (Deferred in Phase 1)**: `CanonicalQuote` and `CanonicalTrade` are defined as canonical in-memory schemas (`ml_data/storage/canonical_schema.py`), while typed Parquet persistence and content-addressed manifests for Quote/Trade streams are explicitly deferred out of Phase 1.
- `DatasetManifest` + `verify_manifest()` validate SHA-256 checksums of every referenced Parquet file.
- `DatasetRegistry` (SQLite) tracks dataset versions, manifests, and ingestion runs.

## 3. Cross-Market Calendars (`ml_data/calendars`)
- `USEquityCalendarAdapter` (`America/New_York`), `USFuturesCalendarAdapter` (`America/Chicago` Globex), `IndiaNSECalendarAdapter` (`Asia/Kolkata`), `CryptoCalendarAdapter` (24/7 UTC).
