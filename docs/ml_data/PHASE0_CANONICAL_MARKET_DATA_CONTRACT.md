# Phase 0 — Step 1: Canonical Market-Data Contract

**Proposed Contract Version**: `1.0.0` (`CANONICAL_SCHEMA_VERSION = "1.0.0"`, `Instrument.SCHEMA_VERSION = "1.0.0"`, `IDENTITY_VERSION = "v3"`)  
**Status**: Frozen Reference Specification (audited against Phase 1 implementation)

---

## 1. Contract Overview

This document formalizes the provider-independent canonical market-data contract implemented across `ml_data/instruments/` and `ml_data/storage/`. It governs:

1. **Instrument Contract** (`Instrument`, `ProviderInstrumentMapping`, `InstrumentSpecVersion`)
2. **Candle Contract** (`CanonicalCandle`)
3. **Quote Contract** (`CanonicalQuote`)
4. **Trade Contract** (`CanonicalTrade`)
5. **Dataset Provenance & Immutability Contract** (`DatasetManifest`)

Supported markets and asset classes:
- **US Equities & ETFs**: `Market.US`, `Segment.US_EQUITY`, `AssetClass.EQUITY | ETF`
- **US Equity & Index Options**: `Market.US`, `Segment.US_OPTIONS`, `AssetClass.OPTION` (subject to documented indicative/feed limitations)
- **US Index Futures**: `Market.US`, `Segment.US_FUTURES`, `AssetClass.FUTURE` (Databento paid discovery deferred)
- **India Index & Derivatives (NIFTY, BANKNIFTY only)**: `Market.IN`, `Segment.IN_INDEX | IN_INDEX_FUTURES | IN_INDEX_OPTIONS`, `AssetClass.INDEX | FUTURE | OPTION`
- **Crypto Spot & Perpetuals**: `Market.CRYPTO`, `Segment.CRYPTO_SPOT | CRYPTO_PERPETUALS | CRYPTO_FUTURES`, `AssetClass.CRYPTO_SPOT | CRYPTO_PERPETUAL | CRYPTO_FUTURE` (CoinDCX / Coinbase; Binance deactivated)

---

## 2. Exact Field Tables

### 2.1 `Instrument` (`ml_data/instruments/schemas.py`, `ml_data/instruments/validation.py`)

| Field | Type | Requirement | Applicable Asset Classes / Notes |
|---|---|---|---|
| `instrument_id` | `str` | Required (auto-computed if `""`) | All; v3 format `<prefix>#<32-hex>` |
| `market` | `Market` | Required | `US`, `IN`, `CRYPTO` |
| `asset_class` | `AssetClass` | Required | `EQUITY`, `ETF`, `INDEX`, `OPTION`, `FUTURE`, `CRYPTO_SPOT`, `CRYPTO_FUTURE`, `CRYPTO_PERPETUAL` |
| `segment` | `Segment` | Required | Must match `(market, segment) -> asset_class` compatibility matrix |
| `exchange` | `str` | Required | Normalized uppercase listing exchange |
| `canonical_symbol` | `str` | Required | Non-empty canonical symbol |
| `trading_symbol` | `str` | Required | Non-empty exchange trading symbol |
| `display_name` | `str` | Required | Non-empty human-readable name |
| `price_currency` | `str` | Required | Non-empty quoted price currency |
| `schema_version` | `str` | Optional (`"1.0.0"`) | Non-empty |
| `identity_version` | `str` | Optional (`"v3"`) | Must equal `"v3"` |
| `exchange_mic` | `Optional[str]` | Optional (`None`) | ISO 10383 MIC |
| `clearing_exchange` | `Optional[str]` | Optional (`None`) | Normalized uppercase |
| `venue` | `Optional[str]` | Optional (`None`) | Execution/trading venue |
| `underlying_instrument_id` | `Optional[str]` | **Conditional** | **Required** for `OPTION`, `FUTURE`, and all `Market.IN` derivatives (`IN_INDEX_FUTURES`, `IN_INDEX_OPTIONS`) |
| `base_currency` | `Optional[str]` | **Conditional** | **Required** non-empty for `CRYPTO_SPOT`, `CRYPTO_FUTURE`, `CRYPTO_PERPETUAL` |
| `quote_currency` | `Optional[str]` | **Conditional** | **Required** non-empty for `CRYPTO_SPOT`, `CRYPTO_FUTURE`, `CRYPTO_PERPETUAL` |
| `settlement_currency` | `Optional[str]` | **Conditional** | **Required** non-empty for `CRYPTO_FUTURE` and `CRYPTO_PERPETUAL` |
| `expiry_date` | `Optional[date]` | **Conditional** | **Required** for `OPTION`, `FUTURE`, `CRYPTO_FUTURE`; **forbidden** for `EQUITY`, `ETF`, `INDEX`, `CRYPTO_SPOT`, `CRYPTO_PERPETUAL` |
| `last_trade_date` | `Optional[date]` | Optional (`None`) | Must be `<= expiry_date` when both set |
| `strike_price` | `Optional[Decimal]` | **Conditional** | **Required** positive `Decimal` for `OPTION`; **forbidden** for `EQUITY`, `ETF`, `INDEX` |
| `option_right` | `Optional[OptionRight]` | **Conditional** | **Required** (`CALL`/`PUT`; `CE`/`PE` normalized) for `OPTION`; **forbidden** for `EQUITY`, `ETF`, `INDEX` |
| `contract_multiplier` | `Optional[Decimal]` | **Conditional** | **Required** positive `Decimal` for `OPTION`, `FUTURE`, `CRYPTO_FUTURE`, `CRYPTO_PERPETUAL` |
| `lot_size` | `Optional[Decimal]` | Optional (`None`) | Positive `Decimal` when set |
| `tick_size` | `Optional[Decimal]` | **Conditional** | **Required** positive `Decimal` for `FUTURE`, `CRYPTO_FUTURE`, `CRYPTO_PERPETUAL` |
| `minimum_order_quantity` | `Optional[Decimal]` | Optional (`None`) | Positive `Decimal` when set |
| `quantity_step` | `Optional[Decimal]` | **Conditional** | **Required** positive `Decimal` for `CRYPTO_SPOT`, `CRYPTO_FUTURE`, `CRYPTO_PERPETUAL` |
| `deliverable_shares` | `Optional[Decimal]` | Optional (`None`) | Positive `Decimal` when set |
| `deliverable_type` | `Optional[str]` | Optional (`None`) | Standard vs. non-standard/adjusted deliverable |
| `exercise_style` | `Optional[str]` | Optional (`None`) | e.g. `AMERICAN`, `EUROPEAN` |
| `contract_type` | `ContractType` | Optional (`UNKNOWN`) | `SPOT`, `EQUITY`, `ETF`, `INDEX`, `OPTION`, `DATED_FUTURE`, `PERPETUAL`, `UNKNOWN` |
| `settlement_type` | `SettlementType` | **Conditional** | **Explicit non-`UNKNOWN` required** for `FUTURE` (`CASH`, `PHYSICAL`, `CRYPTO`, `UNKNOWN`) |
| `margin_type` | `MarginType` | Optional (`UNKNOWN`) | `LINEAR`, `INVERSE`, `STANDARD`, `PORTFOLIO`, `UNKNOWN` |
| `is_inverse` | `bool` | Optional (`False`) | `bool` |
| `is_tradable` | `bool` | Optional (`True`) | Must be `False` for `INDEX` |
| `is_active` | `bool` | Optional (`True`) | Cannot be `True` when `instrument_status == EXPIRED` |
| `trading_calendar` | `Optional[str]` | Optional (`None`) | Calendar identifier |
| `timezone` | `str` | Optional (`"UTC"`) | Constructor-enforced valid IANA timezone via `zoneinfo.ZoneInfo` |
| `listing_date` | `Optional[date]` | Optional (`None`) | `datetime.date` |
| `delisting_date` | `Optional[date]` | Optional (`None`) | Must be `>= listing_date` when both set |
| `instrument_status` | `InstrumentStatus` | Optional (`ACTIVE`) | `ACTIVE`, `INACTIVE`, `HALTED`, `EXPIRED`, `DELISTED`, `PRELISTING`, `UNKNOWN` |
| `primary_provider` | `str` | Optional (`"unknown"`) | Non-empty, normalized lowercase |
| `provider_instrument_id` | `Optional[str]` | Optional (`None`) | Upstream provider ID |
| `provider_symbol` | `Optional[str]` | Optional (`None`) | Upstream provider symbol |
| `provider_feed` | `Optional[str]` | Optional (`None`) | Normalized lowercase |
| `source` | `str` | Optional (`"canonical"`) | Source tag |
| `effective_from` | `Optional[datetime]` | Optional (`None`) | UTC-normalized aware datetime |
| `last_verified_at` | `Optional[datetime]` | Optional (`None`) | UTC-normalized aware datetime |
| `created_at` | `Optional[datetime]` | Optional (auto-UTC) | UTC-normalized aware datetime |
| `updated_at` | `Optional[datetime]` | Optional (`created_at`) | UTC-normalized aware datetime |
| `metadata` | `Mapping[str, Any]` | Optional (`{}`) | Frozen `MappingProxyType` |

### 2.2 `ProviderInstrumentMapping` & `InstrumentSpecVersion`

- **`ProviderInstrumentMapping`**: `instrument_id`, `provider` (lowercase), `provider_symbol`, `mapping_id` (auto SHA-256 via `build_mapping_id`), `provider_instrument_id`, `provider_exchange` (uppercase), `provider_feed` (lowercase), `valid_from` (UTC), `valid_until` (UTC, `> valid_from`), `last_verified_at` (UTC), `is_primary` (`bool`).
- **`InstrumentSpecVersion`**: `version_id` (`int`), `instrument_id` (`str`), `effective_from` (`Optional[datetime]`), `effective_to` (`Optional[datetime]`), `spec_hash` (`str`), `specification` (`Dict[str, Any]` from `Instrument.spec_dict()`), `recorded_at` (`datetime`).

### 2.3 `CanonicalCandle` (`ml_data/storage/canonical_schema.py`)

| Field | Type | Required | Enforcement |
|---|---|---|---|
| `instrument_id` | `str` | Yes | Constructor: non-empty `str` |
| `market`, `asset_class`, `segment`, `exchange` | `str` | Yes | Constructor: non-empty `str` |
| `provider`, `provider_symbol`, `provider_instrument_id` | `str` | Yes | Constructor: non-empty `str` |
| `timestamp_start_utc` | `datetime` | Yes | Constructor: aware datetime normalized to `UTC` |
| `timestamp_end_utc` | `datetime` | Yes | Constructor: aware datetime normalized to `UTC`; `> timestamp_start_utc` |
| `event_time_utc`, `received_at_utc` | `datetime` | Yes | Constructor: aware datetime normalized to `UTC` |
| `timeframe` | `str` | Yes | Constructor: in `STANDARD_TIMEFRAMES_MINUTES` (`"1m"`, `"5m"`, `"15m"`, `"1h"`); `(timestamp_end_utc - timestamp_start_utc) <= timeframe` (allows partial buckets) |
| `trading_date` | `date` | Yes | Constructor: `datetime.date` required (`datetime`, `str`, `None` rejected); `DataQualityEngine`: must match `calendar.trade_date_for(timestamp_start_utc)` |
| `trading_session` | `str` | Yes | Constructor: non-empty `str`; `DataQualityEngine`: must match `calendar.classify_session(...)` |
| `session_id`, `calendar_id`, `calendar_version` | `str` | Yes | Constructor: non-empty `str` |
| `open`, `high`, `low`, `close`, `volume` | `Decimal` | Yes | Constructor: finite `Decimal` (no `float`/`bool`); `high >= max(o,c,l)`, `low <= min(o,c,h)`, `volume >= 0` |
| `schema_version` | `str` | Default `"1.0.0"` | Constructor: must equal `CANONICAL_SCHEMA_VERSION` (`"1.0.0"`) |
| `quote_volume` | `Optional[Decimal]` | No | Constructor: finite `Decimal` or `None` |
| `trade_count` | `Optional[int]` | No | Constructor: non-negative `int` (not `bool`) or `None` |
| `open_interest`, `mark_price`, `index_price`, `funding_rate` | `Optional[Decimal]` | No | Constructor: finite `Decimal` or `None` |
| `funding_timestamp_utc` | `Optional[datetime]` | No | Constructor: aware datetime normalized to `UTC` or `None` |
| `provider_feed`, `source_snapshot_id`, `source_record_id` | `str` | Yes | Constructor: non-empty `str` |
| `dataset_version`, `adjustment_mode`, `retrieval_run_id`, `quality_status` | `str` | Yes | Constructor: non-empty `str` |
| `quality_flags` | `Tuple[str, ...]` | Default `()` | Constructor: accepts `tuple`/`list` of `str`, normalized to `tuple[str, ...]` (plain `str`/non-`str` elements rejected) |

### 2.4 `CanonicalQuote` & `CanonicalTrade` (`ml_data/storage/canonical_schema.py`)

- **`CanonicalQuote`**: `instrument_id`, `event_time_utc` (UTC), `received_at_utc` (UTC), `bid_price` (`Decimal`), `ask_price` (`Decimal`), `bid_size` (`Decimal >= 0`), `ask_size` (`Decimal >= 0`), `exchange`, `provider`, `feed` (all required non-empty `str`), `sequence_id` (`Optional[str]`, `str | None`), `depth_json` (`Optional[str]`, `str | None`), `quality_flags` (`Tuple[str, ...]`, accepts `tuple`/`list` of `str`, normalized to `tuple`). Supports `to_dict()`, `to_json()`, `from_dict()`, `from_json()`.
- **`CanonicalTrade`**: `instrument_id`, `trade_id`, `event_time_utc` (UTC), `received_at_utc` (UTC), `price` (`Decimal`), `quantity` (`Decimal >= 0`), `exchange`, `provider`, `feed`, `source_id` (all required non-empty `str`), `quote_quantity` (`Optional[Decimal]`), `aggressor_side` (`Optional[str]`, `str | None`), `conditions` (`Tuple[str, ...]`, accepts `tuple`/`list` of `str`, normalized to `tuple`). Supports `to_dict()`, `to_json()`, `from_dict()`, `from_json()`.

### 2.5 `DatasetManifest` (`ml_data/storage/manifests.py`)

| Field | Type | Notes |
|---|---|---|
| `dataset_id` | `str` | Logical dataset identifier |
| `dataset_version` | `str` | Immutable revision identifier |
| `schema_version` | `str` | Canonical schema version (`"1.0.0"`) |
| `markets` | `List[str]` | Sorted distinct `market` values |
| `providers` | `List[str]` | Sorted distinct `provider` values |
| `feeds` | `List[str]` | Sorted distinct `provider_feed` values |
| `instrument_ids` | `List[str]` | Sorted distinct canonical `instrument_id` values |
| `requested_start_utc` | `str` | Requested window start (UTC ISO-8601) |
| `requested_end_utc` | `str` | Requested window end (UTC ISO-8601) |
| `actual_start_utc` | `Optional[str]` | Earliest `timestamp_start_utc` in dataset (or `None`) |
| `actual_end_utc` | `Optional[str]` | Latest `timestamp_end_utc` in dataset (or `None`) |
| `source_snapshot_ids` | `List[str]` | Sorted distinct `source_snapshot_id` values |
| `adjustment_modes` | `List[str]` | Sorted distinct `adjustment_mode` values |
| `calendar_versions` | `List[str]` | Sorted distinct `<calendar_id>:<calendar_version>` strings |
| `row_count` | `int` | Total deduplicated canonical rows written |
| `duplicate_count` | `int` | Input duplicate count reported by ingestion |
| `invalid_count` | `int` | Rejected/invalid record count reported by ingestion |
| `missing_timestamps_count` | `int` | Missing timestamp count reported by quality/coverage |
| `pagination_complete` | `bool` | Whether upstream pagination completed without truncation |
| `quality_summary` | `Dict[str, Any]` | Structured quality report summary |
| `file_paths` | `List[str]` | Ordered Parquet partition file paths |
| `file_sha256s` | `Dict[str, str]` | Mapping of `file_path -> 64-char SHA-256 hex digest` |
| `created_at_utc` | `str` | Manifest creation timestamp (excluded from `semantic_dict()`) |
| `git_commit` | `Optional[str]` | Optional source revision commit hash |

**Semantic Immutability Policy**: `DatasetManifest.semantic_dict()` includes all 23 semantic fields above (excluding only `created_at_utc`). Both `CanonicalCandleStore.write_partitioned()` and `DatasetRegistry.register_manifest()` reject any write/registration for an existing `(dataset_id, dataset_version)` whose `semantic_dict()` differs, raising `DatasetVersionConflictError`. Identical semantic metadata is idempotent.

---

## 3. Illustrative / Synthetic JSON Examples

> [!NOTE]
> All payloads below are **illustrative/synthetic** examples. Contract specifications (tick size, lot size, contract multiplier) are **effective-dated** via `InstrumentSpecVersion`; any sample multiplier or lot size (such as NIFTY) must not be interpreted as a permanent or current exchange lot-size rule.

### 3.1 `Instrument` (Valid AAPL Canonical ID Example)
```json
{
  "asset_class": "EQUITY",
  "canonical_symbol": "AAPL",
  "display_name": "Apple Inc.",
  "exchange": "NASDAQ",
  "identity_version": "v3",
  "instrument_id": "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c",
  "instrument_status": "ACTIVE",
  "is_active": true,
  "is_inverse": false,
  "is_tradable": true,
  "market": "US",
  "price_currency": "USD",
  "primary_provider": "alpaca",
  "schema_version": "1.0.0",
  "segment": "US_EQUITY",
  "tick_size": "0.01",
  "timezone": "America/New_York",
  "trading_calendar": "XNAS",
  "trading_symbol": "AAPL"
}
```

### 3.2 `CanonicalCandle` (Illustrative 5m US Equity Bar)
```json
{
  "schema_version": "1.0.0",
  "instrument_id": "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c",
  "market": "US",
  "asset_class": "EQUITY",
  "segment": "US_EQUITY",
  "exchange": "NASDAQ",
  "provider": "alpaca",
  "provider_symbol": "AAPL",
  "provider_instrument_id": "AAPL",
  "timestamp_start_utc": "2026-01-05T14:30:00+00:00",
  "timestamp_end_utc": "2026-01-05T14:35:00+00:00",
  "event_time_utc": "2026-01-05T14:35:00+00:00",
  "received_at_utc": "2026-01-05T14:35:01+00:00",
  "timeframe": "5m",
  "trading_date": "2026-01-05",
  "trading_session": "REGULAR",
  "session_id": "XNAS_2026-01-05",
  "calendar_id": "XNAS",
  "calendar_version": "2026.1",
  "open": "185.10",
  "high": "185.45",
  "low": "185.00",
  "close": "185.30",
  "volume": "12450",
  "quote_volume": null,
  "trade_count": 142,
  "open_interest": null,
  "mark_price": null,
  "index_price": null,
  "funding_rate": null,
  "funding_timestamp_utc": null,
  "provider_feed": "iex",
  "source_snapshot_id": "snap-20260105-01",
  "source_record_id": "rec-001",
  "dataset_version": "v1",
  "adjustment_mode": "RAW",
  "retrieval_run_id": "run-20260105",
  "quality_status": "VERIFIED",
  "quality_flags": []
}
```

### 3.3 `CanonicalQuote` & `CanonicalTrade` (Illustrative)
```json
{
  "quote": {
    "instrument_id": "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c",
    "event_time_utc": "2026-01-05T14:30:00.500000+00:00",
    "received_at_utc": "2026-01-05T14:30:00.510000+00:00",
    "bid_price": "185.10",
    "ask_price": "185.12",
    "bid_size": "200",
    "ask_size": "300",
    "exchange": "NASDAQ",
    "provider": "alpaca",
    "feed": "iex",
    "sequence_id": "seq-1001",
    "depth_json": null,
    "quality_flags": []
  },
  "trade": {
    "instrument_id": "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c",
    "trade_id": "trd-9001",
    "event_time_utc": "2026-01-05T14:30:00.600000+00:00",
    "received_at_utc": "2026-01-05T14:30:00.610000+00:00",
    "price": "185.12",
    "quantity": "50",
    "exchange": "NASDAQ",
    "provider": "alpaca",
    "feed": "iex",
    "source_id": "alpaca-iex",
    "quote_quantity": "9256",
    "aggressor_side": null,
    "conditions": ["@"]
  }
}
```

---

## 4. Field-to-Existing-Code Mapping

| Contract Entity | Source Module |
|---|---|
| `Instrument`, `ProviderInstrumentMapping`, `InstrumentSpecVersion` | `ml_data/instruments/schemas.py` |
| Enumerations (`Market`, `AssetClass`, `Segment`, `MarginType`, etc.) | `ml_data/instruments/enums.py` |
| Identity v3 (`build_instrument_id`, `normalize_decimal_str`, `build_mapping_id`) | `ml_data/instruments/identity.py` |
| Compatibility matrix & category validation | `ml_data/instruments/validation.py` |
| `CanonicalCandle`, `CanonicalQuote`, `CanonicalTrade`, `resample_candles` | `ml_data/storage/canonical_schema.py` |
| Parquet `Decimal128(38,12)` I/O (`CANDLE_ARROW_SCHEMA`) | `ml_data/storage/parquet.py` |
| Content-addressed partitions & deduplication | `ml_data/storage/candle_store.py` |
| `DatasetManifest`, `verify_manifest` | `ml_data/storage/manifests.py` |
| `DataQualityEngine` | `ml_data/quality/engine.py` |

---

## 5. Timestamp, Currency, Venue, Session & Feed Semantics

- **Interval Boundary Convention**: Half-open intervals `[timestamp_start_utc, timestamp_end_utc)` with `0 < (timestamp_end_utc - timestamp_start_utc) <= timeframe`. Partial buckets (e.g. closing buckets or early closes) are permitted and explicitly flagged (`partial_bucket`) by `resample_candles()`.
- **Opening / Closing Timestamp Semantics**: `timestamp_start_utc` is the bar open; `timestamp_end_utc` is the bar close. `event_time_utc` is the exchange/provider event time; `received_at_utc` is local ingestion receipt time.
- **Timezone Conversion**: All datetime fields must be timezone-aware and are normalized to `UTC` via `object.__setattr__()`. Naive datetimes raise `SchemaValidationError` or `InstrumentValidationError`.
- **Currency Resolution**: Prices on `CanonicalCandle`, `CanonicalQuote`, and `CanonicalTrade` resolve to `Instrument.price_currency`; crypto pairs resolve `base_currency`, `quote_currency`, and `settlement_currency` on `Instrument`.
- **Missing & Unavailable Values**: Unprovided fields remain `None` (never fabricated).
- **Duplicate & Out-of-Order Handling**: `CanonicalCandleStore` sorts by `(instrument_id, timestamp_start_utc)`, deduplicates exact content matches, and raises `DatasetVersionConflictError` on same-key conflicting content regardless of input order.
- **Top-of-Book vs. Depth & Locked/Crossed Quotes**: `CanonicalQuote` represents top-of-book with optional `depth_json`; locked/crossed quotes are preserved on construction and inspected via downstream quality rules/flags.

---

## 6. Validation Rules & Enforcement Boundaries

### 6.1 `CanonicalCandle` Rule Classification
- **Constructor-enforced (`CanonicalCandle.__post_init__`)**:
  - `schema_version == "1.0.0"`
  - `timeframe in {"1m", "5m", "15m", "1h"}`
  - Non-empty string checks on all required string identifiers
  - Timezone-aware timestamps normalized to `UTC`
  - `0 < (timestamp_end_utc - timestamp_start_utc) <= timeframe`
  - `trade_count` is `None` or non-negative `int` (not `bool`)
  - Finite `Decimal` (no `float`/`bool`) and OHLCV invariants (`high >= max(o,c,l)`, `low <= min(o,c,h)`, `volume >= 0`)
- **Registry / Ingestion / `DataQualityEngine`-enforced**:
  - `instrument_id` exists in `InstrumentRegistry` (when `registry` is supplied to `DataQualityEngine`)
  - `trading_date == calendar.trade_date_for(timestamp_start_utc)` (when `calendar` is supplied)
  - `trading_session == calendar.classify_session(timestamp_start_utc)` and non-closed/non-maintenance session
  - Tick-size compliance against `Instrument.tick_size`
  - Temporal sanity (rejecting future event timestamps)
  - Full-content deduplication and immutable manifest checks in `CanonicalCandleStore` / `DatasetRegistry`

### 6.2 Cross-Entity Contract Integrity (`Record -> Instrument`)

| Cross-Entity Relationship | Enforcing Component | Status |
|---|---|---|
| `instrument_id` exists in `InstrumentRegistry` | `DataQualityEngine` (when `registry` is provided) | **Enforced** |
| `tick_size` compliance against `Instrument.tick_size` | `DataQualityEngine` (`check_tick_size_compliance`) | **Enforced** |
| `trading_date` / `trading_session` match `ExchangeCalendar` | `DataQualityEngine` (when `calendar` is provided) | **Enforced** |
| `CanonicalCandle.market == Instrument.market.value` | — | **Pending validation boundary** |
| `CanonicalCandle.asset_class == Instrument.asset_class.value` | — | **Pending validation boundary** |
| `CanonicalCandle.segment == Instrument.segment.value` | — | **Pending validation boundary** |
| `CanonicalCandle.exchange == Instrument.exchange` | — | **Pending validation boundary** |
| `price_currency` resolution via `Instrument.price_currency` | Downstream consumers / `Instrument` lookup | **Documented (lookup by `instrument_id`)** |
| `provider` / `provider_feed` match `ProviderInstrumentMapping` | — | **Pending validation boundary** |

---

## 7. Unsupported & Deferred Items

- **`CanonicalQuote` and `CanonicalTrade` Parquet Persistence**: **DEFERRED** in Phase 1 (in-memory schemas and JSON round-trip only).
- **Provider-Unsupported Fields**: Historical funding/OI where unsupported, or missing `aggressor_side` / `quote_volume`, remain `None` / `UNSUPPORTED`.
- **Missing Contract Specifications**: Missing `unit_contract_value` or unverified calendar years fail closed rather than silently defaulting.

---

## 8. Versioning & Compatibility Policy

- `Instrument.schema_version = "1.0.0"`, `Instrument.identity_version = "v3"`.
- `CanonicalCandle.schema_version = "1.0.0"`.
- `DatasetManifest` enforces immutable `(dataset_id, dataset_version)` semantics via `semantic_dict()`.

---

## 9. Open Decisions

1. **Cross-Entity Field Enforcement**: Whether `DataQualityEngine` should enforce `market`/`asset_class`/`segment`/`exchange` and `ProviderInstrumentMapping` consistency against `InstrumentRegistry` in Phase 1 or Phase 2.
2. **Quote/Trade Parquet Persistence**: Whether Phase 2/3 requires typed `QUOTE_ARROW_SCHEMA` / `TRADE_ARROW_SCHEMA` Parquet stores.
3. **Locked/Crossed Quote Policy**: Whether `DataQualityEngine` should flag or reject crossed quotes when `CanonicalQuote` quality evaluation is added.
