# Phase 0 — Step 2: Chart Contract

**Proposed Contract Version**: `1.0.0` (`CHART_CONTRACT_VERSION = "1.0.0"`)
**Status**: Proposed, with the remediation (P1-A, P1-B, P1-C, P2-A, P2-B) and the integrity patch (price-axis policy, spec-hash integrity) applied. Awaiting independent review. Not self-approved.
**Depends on**: Phase 0 Step 1 Canonical Market-Data Contract `1.0.0` (frozen; reused unchanged)
**Implementation**: `ml_data/charts/` (specification and validation only). **No renderer, no image generation, no ML inference.**

---

## 1. Scope and Separation from the Trading Dashboard

This contract defines the **ML research chart**. It is a deterministic, reproducible pairing of:

1. Canonical market data (`CanonicalCandle` records)
2. Visible chart content
3. Chart configuration (`ChartSpec`)
4. The rendered image (PNG)
5. Image and data snapshot identifiers

Existing chart infrastructure was inspected. It is **unrelated and unchanged**:

| Existing component | What it is | Relation to this contract |
|---|---|---|
| `components/ChartView.tsx` | V4/V6 dashboard chart (TradingView `lightweight-charts`, interactive, responsive) | Not used. Not changed. |
| `api/_chart.py` | Dashboard "View on chart" API (Yahoo 5m candles, trade markers, verdicts) | Not used. Not changed. Its markers/verdicts are post-outcome annotations, forbidden here. |
| `components/ChartTesting.tsx`, `lib/chartExtractor.ts`, `tests/test_chart*.py` | Dashboard chart-reading / calibration tools | Not used. Not changed. |
| `ml_data/us/snapshots.py` | Content-addressed storage of Alpaca discovery snapshots | Different concept (provider discovery data, not chart snapshots). |

No ML chart renderer, image pipeline or screenshot pipeline existed before this step, and none is added.

---

## 2. Canvas and Image Format

| Property | v1.0.0 value | Enforcement (`validate_chart_png`, standard library only) |
|---|---|---|
| Width × height | **1280 × 720 px** (16:9) | `ChartSpec` must equal the profile; IHDR must match exactly |
| Image format | **PNG** | Signature; every chunk CRC; IHDR first; IDAT chunks consecutive; exactly one empty IEND, last |
| Colour mode | **RGB**, 8-bit, no alpha | IHDR colour type 2, bit depth 8; compression method 0, filter method 0, interlace 0 |
| Image data | Must decode exactly | Concatenated IDAT zlib stream must decompress completely (end of stream, no trailing data) to exactly `height × (1 + width × 3)` bytes; every scanline filter byte must be 0–4 |
| Colour space | **sRGB** | Exactly one `sRGB` chunk (1 byte, rendering intent 0–3) before the first IDAT; an embedded ICC profile (`iCCP`) is rejected |
| Resizing | None | Any other size is rejected; alternatives require a new versioned profile |

---

## 3. Profile `intraday_v1_200bar` (version `1.0.0`)

| Field | Value |
|---|---|
| `visible_candle_count` | 200 (explicit in `ChartSpec`; actual count recorded in the manifest) |
| `x_axis_mode` | `TRADING_BAR_INDEX` (one candle = one equal slot; closed-market periods compressed) |
| `price_scale` | `LINEAR` |
| `price_axis_policy` | `PADDED_RANGE_V1` (profile-locked; §4) |
| `price_axis_padding_ratio` | default `0.05`; explicit in every `ChartSpec`, allowed range `(0, 0.25]` |
| `volume_panel_enabled` | `true` |
| Plot split | price panel `0.78`, volume panel `0.22` (decimal strings, sum = 1) |
| Default theme | `dark_v1` / `1.0.0` |
| Default overlays | none (`[]`) |
| Default sessions | `["REGULAR"]` (`ChartSpec.create` default) |

`ChartSpec` fields that come from the profile must match it exactly (type and value).

### 3.1 Visible window, warm-up, session context and missing data

- **Visible candles** are the 200 bars drawn. `visible_start_utc` is the first visible `timestamp_start_utc`. `visible_end_utc` (exclusive) is the last visible `timestamp_end_utc`.
- **Warm-up candles** feed bar-count overlays (EMA, SMA, Bollinger). They strictly precede the first visible candle, and they are never rendered or counted as visible.
- **Session-context candles** (`session_context_candles`) are the non-rendered bars from the **official open** of the first visible session up to the first visible candle. They are used only for VWAP (§5.1) and are rejected on non-VWAP charts. They must belong to the first visible session and end exactly where the visible window starts. A record that also appears in warm-up must be identical.
- **Incomplete windows.** A chart is `INCOMPLETE` if it has fewer than 200 visible candles, fewer warm-up candles than declared, or VWAP session context that cannot be proven. It can never be `READY` or `MODEL_READY`. More than 200 visible candles is rejected.
- **No synthetic candles.** Inputs must be strictly increasing and non-overlapping, and duplicates are rejected. Within a `session_id`, a step larger than one timeframe is recorded as a gap (`intra_session_gap_count`, `missing_bar_count`) and never filled. Steps across `session_id` boundaries are the compressed closed-market periods.
- **Sessions.** `session_policy = ALLOWLIST`. Every input candle's `trading_session` must be in `allowed_sessions`. The default is `REGULAR` only. `PRE_MARKET` and `POST_MARKET` must be listed explicitly, and they stay distinguishable because the manifest records `sessions_present`. `CLOSED` and `MAINTENANCE` can never be allowed.

---

## 4. Layout

Base chart: OHLC candlesticks with wicks in the price panel (78%), and volume bars in the volume panel (22%) on the same bar slot. There is a price axis, a volume axis and a timestamp X-axis, plus instrument, exchange and timeframe identification. Price scaling is linear.

### 4.1 Price-axis bounds policy `PADDED_RANGE_V1`

The price-axis range is **not** a free render output that the manifest asserts. It is **derived deterministically** from the validated visible data and the spec's axis configuration (`price_axis_bounds()`):

- `visible_low` = min of the visible lows. `visible_high` = max of the visible highs. Both are exact Decimals from the canonical candles.
- `pad = (visible_high − visible_low) × price_axis_padding_ratio`. For a flat window (`high == low`), `pad = (|visible_high|, or 1 if that is 0) × ratio`.
- `price_axis_min = visible_low − pad` and `price_axis_max = visible_high + pad`. These are exact Decimal arithmetic: no float, no rounding (an inexact result raises), stored as canonical decimal strings.
- Example: low `101.09`, high `103.18`, ratio `0.05` give `[100.9855, 103.2845]`.
- Bounds use the visible OHLC only. Overlay values outside that range (for example Bollinger bands) are clipped by the renderer.

`price_axis_policy` and `price_axis_padding_ratio` are `ChartSpec` fields. So a different axis configuration changes `chart_spec_hash` and therefore `chart_snapshot_id`, while `data_snapshot_id` stays the same.

The manifest records the policy, the ratio, `visible_low`/`visible_high` and the derived bounds. **Manifest validation recomputes the bounds from those fields, and `verify_chart_snapshot()` recomputes them from the `ChartSpec` and `DataSnapshot`.** It never reads them back from the manifest.

A renderer may report the bounds it drew (`price_axis_min/max` arguments of `build_chart_snapshot_manifest`). They are only a cross-check, and must equal the policy bounds exactly. **No renderer exists in this step, and the PNG's visual axis labels are not decoded or verified. Only the declared, policy-derived bounds are verified.**

---

## 5. Overlay Contract

The default overlay list is **empty**. No indicator is ever added implicitly. Every overlay is an explicit `OverlaySpec`:

| Field | Rule |
|---|---|
| `overlay_id` | Canonical id derived from type and parameters (`ema_20_close`, `sma_50_close`, `bollinger_20_close_2`, `vwap_hlc3_session`). Duplicates in a spec are rejected. |
| `overlay_type` | `EMA`, `SMA`, `VWAP`, `BOLLINGER`. Nothing else (no RSI, MACD, signals, arrows) |
| `parameters` | Exact key set per type, no defaults filled, int periods `2..500`, Decimal-string multipliers (no float, `0 < m <= 10`) |
| `calculation_version` | `ema_v1`, `sma_v1`, `vwap_session_v1`, `bbands_v1` |
| `placement` | `PRICE_PANEL` |
| `visible` | bool |
| `warmup_bars` | EMA = **3 × period**, SMA and BOLLINGER = period − 1, VWAP = 0 (VWAP is session-anchored instead) |
| `session_anchored` | `true` only for VWAP |
| `style_ref` | Must resolve in the selected theme |

Formulas (`calculation_version`):
- `ema_v1`: α = 2/(n+1), seeded with the SMA of the first n closes.
- `sma_v1`: mean of the last n closes.
- `bbands_v1`: SMA(n) ± m × population stddev(n).
- `vwap_session_v1`: Σ(HLC3 × volume) / Σ(volume), reset at each official session open.

### 5.1 VWAP session context (proven from the exchange calendar)

VWAP must use every source bar from the **official session start**, through the visible window, up to the decision time. `build_data_snapshot(..., session_context_candles=..., calendar=...)` proves this:

- The calendar must be the candles' own: `metadata.calendar_id` and `calendar_version` must equal the candles' values. Otherwise it is a `ProvenanceError`. `trade_date_for()` must also agree with every visible session's `trading_date`.
- The official open of each visible session is taken from the calendar's `session_bounds(trading_date, require_verified=True)` (for example 09:30 New York for XNYS, 09:15 IST for XNSE, or a special-session open). **It is never inferred from the first supplied candle.**
- **First visible session:** `session_context + visible bars of that session` must start exactly at the official open and continue bar by bar with no missing bar.
- **Each later visible session:** its first visible bar must be the official open, followed by consecutive bars (the VWAP resets there).
- **When context cannot be proven, the chart is `INCOMPLETE` with reason `INSUFFICIENT_VWAP_SESSION_CONTEXT`.** This covers:
  - a missing opening bar or a missing bar inside the session
  - no calendar
  - a calendar year that is not verified
  - a non-trading day
  - `PRE_MARKET` or `POST_MARKET` sessions (their start is not provable in v1)
  - a calendar without `session_bounds`

  VWAP is never silently swapped for another calculation.
- The official opens (`official_session_opens_utc`), the result, any issues, and every context record are part of `data_snapshot_id`. Context candles obey the same lookahead and provenance rules.
- Known consequences: XNAS is `PARTIALLY_VERIFIED` in Step 1, so VWAP charts on XNAS-calendar data stay `INCOMPLETE` until XNAS is verified. Crypto continuous sessions have no provable `session_bounds` in v1.

---

## 6. Theme Contract

Themes are looked up by the exact `(theme_id, theme_version)`. There is no fallback and no "latest". The manifest records `theme_id`, `theme_version` and `theme_hash`, and the hash must equal the registered definition. `require_single_theme()` rejects a model dataset that mixes themes.

| Element | `dark_v1` 1.0.0 (default) | `light_v1` 1.0.0 |
|---|---|---|
| Background | `#0B1220` | `#FFFFFF` |
| Plot panel | `#111827` | `#FFFFFF` |
| Grid / grid opacity | `#273449` / `0.6` | `#E2E8F0` / `0.8` |
| Text | `#CBD5E1` | `#334155` |
| Axis line | `#273449` | `#CBD5E1` |
| Bullish / Bearish / Neutral candle | `#22C55E` / `#EF4444` / `#94A3B8` | `#15803D` / `#B91C1C` / `#64748B` |
| Candle body width (share of a bar slot) | `0.7` | `0.7` |
| Wick | 1 px, candle colour | 1 px, candle colour |
| Volume bars | candle colour, opacity `0.5` | candle colour, opacity `0.5` |
| Font | `DejaVu Sans`, 12 px | `DejaVu Sans`, 12 px |
| Overlay styles | `ema_fast #38BDF8`, `ema_slow #F59E0B`, `sma #A78BFA`, `vwap #F472B6` (dashed), `bollinger #94A3B8` (fill `0.08`) | `ema_fast #0284C7`, `ema_slow #D97706`, `sma #7C3AED`, `vwap #DB2777` (dashed), `bollinger #64748B` (fill `0.08`) |

The renderer records `font_fingerprint` (SHA-256 over `{font file name → SHA-256 of the file}`), `renderer_name`, `renderer_version` and `renderer_build_id`.

---

## 7. Timestamps, Point-in-Time and No-Lookahead

Internal timestamps are timezone-aware UTC and authoritative. The display zone is **fixed per segment**:

| Segment | `display_timezone` |
|---|---|
| `US_EQUITY`, `US_INDEX`, `US_OPTIONS` | `America/New_York` |
| `US_FUTURES` | `America/Chicago` |
| `IN_INDEX`, `IN_INDEX_FUTURES`, `IN_INDEX_OPTIONS` | `Asia/Kolkata` |
| `CRYPTO_SPOT`, `CRYPTO_FUTURES`, `CRYPTO_PERPETUALS` | `UTC` |

**Availability modes and point-in-time basis.** A model dataset uses exactly one mode. `require_single_availability_mode()` rejects a mix.

| `availability_mode` | `point_in_time_basis` | Meaning |
|---|---|---|
| `AS_KNOWN_AT_DECISION` (default) | `AS_KNOWN_AT_DECISION` | Live-faithful. Candle `received_at_utc` and the instrument spec `recorded_at` must be ≤ the decision time |
| `EVENT_TIME` | `RETROSPECTIVE_EVENT_TIME` | Backfilled or retrospective research reconstruction. **Not live-faithful evidence.** A later-recorded spec revision is allowed but flagged (`instrument_spec_known_at_decision = false`) and never claimed as known |

Rules. A violation raises `LookaheadError`, which is a hard error and never a status:

1. Every visible, warm-up and session-context candle has `timestamp_end_utc <= decision`. Only closed candles are allowed.
2. Every such candle has `event_time_utc <= decision`.
3. In `AS_KNOWN_AT_DECISION`, every candle also has `received_at_utc <= decision`.
4. In `AS_KNOWN_AT_DECISION`, `InstrumentSpecVersion.recorded_at <= decision`. `recorded_at` must be timezone-aware. Effective dating (`effective_from <= decision < effective_to`) applies in both modes.
5. Overlays only use those validated candles.
6. Labels, outcomes, future highs/lows, trade results and annotations cannot be expressed in the contract.
7. Axis labels come from `axis_timestamp()` as `{utc, local_iso (with offset), utc_offset_minutes, tz_abbreviation, label}`. Repeated DST wall-clock times stay distinguishable (`01:30 EDT` vs `01:30 EST`). The manifest stores `visible_start_display`, `visible_end_display` and `display_utc_offsets_minutes`.

---

## 8. Identities

| Identity | Definition | Changes when |
|---|---|---|
| `data_snapshot_id` | SHA-256 (64 lowercase hex) of the canonical data payload below | any visible, warm-up or context record, provenance, spec revision (incl. `recorded_at`), decision time, mode, window or proven session opens change |
| `chart_spec_hash` | SHA-256 of canonical `ChartSpec` JSON | any spec field changes |
| `chart_snapshot_id` | SHA-256 of `{chart_contract_version, data_snapshot_id, chart_spec_hash, renderer{name, version, build_id, font_fingerprint}, theme{id, version, theme_hash}}` | data, spec, renderer, font or theme changes |
| `image_sha256` | SHA-256 of the actual PNG bytes | the image bytes change |

Canonical serialization (`canonical_json`): sorted keys, compact, ASCII. **Floats are rejected.** Decimals are exact strings (Step 1 `normalize_decimal_str`), and timestamps are UTC ISO-8601.

**`data_snapshot_id` payload** (`chart-data-snapshot/1.0.0`):
- `instrument_id`, `timeframe`, `adjustment_mode`, `calendar_id`, `calendar_version`, `decision_timestamp_utc`, `availability_mode`, `point_in_time_basis`
- `window`: `visible_start_utc`, `visible_end_utc`, `visible_count`, `warmup_start_utc`, `warmup_count`, `session_context_count`
- `instrument_spec`: `version_id`, `spec_hash`, `effective_from`, `effective_to`, `recorded_at`, `known_at_decision`
- `dataset`: `dataset_id`, `dataset_version`, `manifest_sha256`, `partition_sha256s`
- `session_context`: `official_session_opens_utc`, `vwap_session_context_complete`, `issues`
- `warmup_records`, `session_context_records`, `visible_records`: the full Step 1 `CanonicalCandle.to_dict()` of every record

**Dataset manifest identity (`manifest_sha256`, float-free).** This covers `DatasetManifest.semantic_dict()`: `created_at_utc` is excluded, and partitions are identified by content SHA-256 only, so file locations do not matter. It is hashed with the shared `canonical_json`. `quality_summary` values are normalized before hashing:
- `int`, `str`, `bool` and `None` are kept.
- `Decimal` becomes a canonical decimal string.
- `float` is converted by its **exact** binary value, `Decimal(float)`, with no rounding. So `0.5` becomes `"0.5"`, but `0.1` becomes `"0.1000000000000000055511151231257827021181583404541015625"`, which is not the same as `"0.1"`.
- NaN and ±Infinity (float or Decimal), and unsupported types, raise `ProvenanceError`.

---

## 9. Provenance Validation (`ProvenanceError`, hard error)

- All inputs share one `instrument_id`, `timeframe`, `market`, `segment`, `calendar_id`/`calendar_version` and `adjustment_mode`.
- These must match the `DatasetManifest`:
  - the schema version
  - the instrument
  - `"<calendar_id>:<calendar_version>"`
  - the adjustment mode
  - the market
  - every candle's `dataset_version`, `source_snapshot_id`, `provider` and `provider_feed`
  - the actual time range
  - at least one partition SHA-256
- The `InstrumentSpecVersion` must belong to the instrument. Its `specification` must be a mapping whose Step 1 `compute_spec_hash()` (`ml_data.instruments.identity`, reused, not duplicated) **exactly equals `spec_hash`**. This is checked before the data identity is built. A changed or mutated specification with a stale hash is a `ProvenanceError`. The revision must also be effective at the decision, and have an aware `recorded_at` (§7).
- The exchange calendar used for VWAP must be the candles' own calendar (§5.1).
- `ChartSpec` must match the data snapshot: same `data_snapshot_id`, instrument, timeframe, decision and mode. The display zone must be the segment's zone. Sessions must be within the allowlist. Context candles are only allowed with VWAP.

---

## 10. Render Status and Complete Verification

The status is **derived, never asserted**. `derive_render_status()` is the single source used by the builder, by manifest validation and by verification:

| Order | Condition | Status | `status_reasons` |
|---|---|---|---|
| 1 | Renderer reported an error | `FAILED` (no image) | incompleteness reasons + `RENDER_FAILED` |
| 2 | Visible count, warm-up or VWAP context incomplete | `INCOMPLETE` | `INSUFFICIENT_VISIBLE_CANDLES` / `INSUFFICIENT_WARMUP_CANDLES` / `INSUFFICIENT_VWAP_SESSION_CONTEXT` |
| 3 | Complete, no image yet | `PENDING_RENDER` | none |
| 4 | Complete, validated image, with blockers | `READY` | `QUALITY_NOT_VERIFIED` / `INTRA_SESSION_GAPS` / `DATASET_PAGINATION_INCOMPLETE` |
| 5 | Complete, validated image, no blockers | `MODEL_READY` | none |

The manifest records every input of that derivation:
- `actual_visible_candle_count`, `warmup_candle_count`, `required_warmup_candle_count`
- `vwap_session_context_complete` (null unless VWAP)
- `all_inputs_quality_verified`, `intra_session_gap_count`/`missing_bar_count`, `dataset_pagination_complete`
- the image fields

**Manifest validation** re-derives the status, so a forged status or reason list is rejected on construction (including `from_dict`/`from_json`). It also checks the theme hash against the registry, the point-in-time flags, and that the price bounds contain the visible range.

**`verify_chart_snapshot(manifest, spec, data_snapshot, renderer, image_root=None)`** rebuilds the **entire** manifest from the spec, data snapshot, renderer, theme and the manifest's image state, and compares every semantic field. That covers:
- identities
- renderer and font
- theme and its hash
- instrument and timeframe
- counts
- UTC boundaries, decision and display fields
- calendar, adjustment and sources
- point-in-time fields
- overlays
- visible low/high, the axis policy, padding ratio and the policy-derived price bounds
- gaps and missing bars
- status and reasons

A manifest whose recorded flags were also edited to look self-consistent still fails, because the data snapshot supplies the true values. With `image_root`, the image file is re-hashed against `image_sha256` and its size, and re-validated.

**Immutability.** Nested manifest mappings (`visible_start_display`, `visible_end_display`, `overlay_specs` with their `parameters`) are deep-frozen read-only mappings. `to_dict()` returns independent plain copies.

---

## 11. Machine-Readable Contract (`ml_data/charts/`)

| Module | Contents |
|---|---|
| `profiles.py` | `CHART_CONTRACT_VERSION`, `ChartProfile`, `INTRADAY_V1_200BAR`, `get_profile` |
| `themes.py` | `ChartTheme`, `OverlayStyle`, `DARK_V1`, `LIGHT_V1`, `get_theme`, `require_single_theme` |
| `overlays.py` | `OverlaySpec`, `canonical_overlay_id`, `required_warmup_bars`, `CALCULATION_VERSIONS` |
| `spec.py` | `ChartSpec`, `RendererInfo`, `compute_font_fingerprint`, display-zone map |
| `snapshot.py` | `build_data_snapshot` → `DataSnapshot`, `dataset_manifest_identity`, `compute_chart_snapshot_id`, `derive_render_status`, `build_chart_snapshot_manifest` → `ChartSnapshotManifest`, `verify_chart_snapshot`, `verify_chart_image`, `axis_timestamp`, `require_single_availability_mode` |
| `png.py` | Standard-library PNG structure and image-stream validation |
| `hashing.py` | `canonical_json` (float-rejecting), `sha256_of_payload`, `is_sha256_hex` |

Standard library and dataclasses only. No new dependency.

### 11.1 Example `ChartSpec` (synthetic test data; EMA 20 overlay)

```json
{
  "chart_contract_version": "1.0.0",
  "chart_profile_id": "intraday_v1_200bar",
  "instrument_id": "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c",
  "timeframe": "5m",
  "width_px": 1280,
  "height_px": 720,
  "image_format": "PNG",
  "color_mode": "RGB",
  "color_space": "sRGB",
  "visible_candle_count": 200,
  "warmup_candle_count": 60,
  "session_policy": "ALLOWLIST",
  "allowed_sessions": [
    "REGULAR"
  ],
  "display_timezone": "America/New_York",
  "x_axis_mode": "TRADING_BAR_INDEX",
  "price_scale": "LINEAR",
  "price_axis_policy": "PADDED_RANGE_V1",
  "price_axis_padding_ratio": "0.05",
  "volume_panel_enabled": true,
  "theme_id": "dark_v1",
  "theme_version": "1.0.0",
  "overlay_specs": [
    {
      "overlay_id": "ema_20_close",
      "overlay_type": "EMA",
      "parameters": {
        "period": 20,
        "source": "CLOSE"
      },
      "calculation_version": "ema_v1",
      "placement": "PRICE_PANEL",
      "visible": true,
      "warmup_bars": 60,
      "style_ref": "ema_fast",
      "session_anchored": false
    }
  ],
  "decision_timestamp_utc": "2026-01-08T21:00:02+00:00",
  "availability_mode": "AS_KNOWN_AT_DECISION",
  "data_snapshot_id": "bccda3c3e1ed6c3cffa0d3bf7042e8f0b74a495c340c63e9cd3ef4f75025ab17"
}
```

### 11.2 Example `ChartSnapshotManifest` (same chart; synthetic 1280×720 PNG; `MODEL_READY`)

```json
{
  "chart_contract_version": "1.0.0",
  "chart_snapshot_id": "aa831decae8f28cfa9e7588083d7416a2496adbe80cb5bf521bc30b39100d96c",
  "chart_spec_hash": "cf025d218f05aa139fc23a85cc79be6c75003bc70ac4b78ebe8c22a6e590a023",
  "data_snapshot_id": "bccda3c3e1ed6c3cffa0d3bf7042e8f0b74a495c340c63e9cd3ef4f75025ab17",
  "image_sha256": "e3c1b2bf3525e2d63f732d964b49ec53fd301b6af5f753bd52991817f8c07f78",
  "image_path": "charts/aapl.png",
  "image_size_bytes": 4326,
  "instrument_id": "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c",
  "timeframe": "5m",
  "chart_profile_id": "intraday_v1_200bar",
  "expected_visible_candle_count": 200,
  "actual_visible_candle_count": 200,
  "required_warmup_candle_count": 60,
  "warmup_candle_count": 60,
  "session_context_candle_count": 0,
  "visible_start_utc": "2026-01-06T17:20:00+00:00",
  "visible_end_utc": "2026-01-08T21:00:00+00:00",
  "decision_timestamp_utc": "2026-01-08T21:00:02+00:00",
  "availability_mode": "AS_KNOWN_AT_DECISION",
  "point_in_time_basis": "AS_KNOWN_AT_DECISION",
  "last_visible_event_time_utc": "2026-01-08T21:00:00+00:00",
  "last_visible_received_at_utc": "2026-01-08T21:00:01+00:00",
  "display_timezone": "America/New_York",
  "visible_start_display": {
    "utc": "2026-01-06T17:20:00+00:00",
    "local_iso": "2026-01-06T12:20:00-05:00",
    "utc_offset_minutes": -300,
    "tz_abbreviation": "EST",
    "label": "2026-01-06 12:20 EST"
  },
  "visible_end_display": {
    "utc": "2026-01-08T21:00:00+00:00",
    "local_iso": "2026-01-08T16:00:00-05:00",
    "utc_offset_minutes": -300,
    "tz_abbreviation": "EST",
    "label": "2026-01-08 16:00 EST"
  },
  "display_utc_offsets_minutes": [
    -300
  ],
  "calendar_id": "XNAS",
  "calendar_version": "2026.1",
  "adjustment_mode": "RAW",
  "sessions_present": [
    "REGULAR"
  ],
  "dataset_id": "us_equity_5m",
  "dataset_version": "v1",
  "dataset_manifest_sha256": "6ceed4c14d146d49f2e95aede9a832f2ab3db8f80ef1b4f97ac63af3a17d8acf",
  "dataset_pagination_complete": true,
  "source_snapshot_ids": [
    "snap-1"
  ],
  "source_file_sha256s": [
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  ],
  "instrument_spec_version_id": 1,
  "instrument_spec_hash": "a20dee376a183f8e8f6cca38481c229e8d0f9ef5ccc25155b47eac7fff7629d1",
  "instrument_spec_recorded_at_utc": "2025-12-31T00:00:00+00:00",
  "instrument_spec_known_at_decision": true,
  "theme_id": "dark_v1",
  "theme_version": "1.0.0",
  "theme_hash": "871323b4c34944182a478fae08c2da55c6b9be9c78e42d164f80dc7ac9b2f977",
  "width_px": 1280,
  "height_px": 720,
  "image_format": "PNG",
  "color_mode": "RGB",
  "color_space": "sRGB",
  "renderer_name": "ml-chart-renderer",
  "renderer_version": "1.0.0",
  "renderer_build_id": "build-1",
  "font_fingerprint": "1397e3988cd98fc483bb1f8061ea396ba80d87176710307d0bf25b4eb835a1b8",
  "overlay_specs": [
    {
      "overlay_id": "ema_20_close",
      "overlay_type": "EMA",
      "parameters": {
        "period": 20,
        "source": "CLOSE"
      },
      "calculation_version": "ema_v1",
      "placement": "PRICE_PANEL",
      "visible": true,
      "warmup_bars": 60,
      "style_ref": "ema_fast",
      "session_anchored": false
    }
  ],
  "vwap_session_context_complete": null,
  "visible_low": "101.09",
  "visible_high": "103.18",
  "price_axis_policy": "PADDED_RANGE_V1",
  "price_axis_padding_ratio": "0.05",
  "price_axis_min": "100.9855",
  "price_axis_max": "103.2845",
  "all_inputs_quality_verified": true,
  "intra_session_gap_count": 0,
  "missing_bar_count": 0,
  "render_status": "MODEL_READY",
  "status_reasons": [],
  "created_at_utc": "2026-11-28T12:00:00+00:00"
}
```

---

## 12. Frozen v1.0.0 Policies

| Policy | v1.0.0 rule |
|---|---|
| Price-axis bounds | **`PADDED_RANGE_V1`**: `[low − pad, high + pad]`, `pad = range × ratio` (default `0.05`), Decimal-only, part of `ChartSpec`; derived, never asserted |
| Instrument spec hash | `spec_hash` must equal `compute_spec_hash(specification)` |
| Intra-session gaps | Recorded, never filled. **Any gap blocks `MODEL_READY`** (the chart stays `READY` with `INTRA_SESSION_GAPS`) |
| EMA warm-up | **3 × period** (`ema_v1`) |
| VWAP | Requires **full session context** proven from the exchange calendar (§5.1); otherwise `INCOMPLETE` |
| Display timezone | **Fixed per segment** (§7); no per-chart override |
| Colour space | **sRGB chunk required; `iCCP` prohibited** |
| Availability modes | `AS_KNOWN_AT_DECISION` and `EVENT_TIME` charts are **never mixed** in one model dataset |
| `EVENT_TIME` | **Retrospective / backfilled research** (`RETROSPECTIVE_EVENT_TIME`), not live-faithful evidence |
| Quality-summary identity | **Float-free** (exact normalization; NaN/Infinity rejected) |
| Instrument spec `recorded_at` | **Point-in-time validated**: ≤ decision in `AS_KNOWN_AT_DECISION`; recorded and flagged in `EVENT_TIME` |
| US sessions | Default **`REGULAR`**. `PRE_MARKET`/`POST_MARKET` need an explicit allowlist and stay distinguishable (`sessions_present`) |

Known consequences, not open decisions:
- XNAS-calendar VWAP charts cannot be `MODEL_READY` until XNAS is verified in Step 1.
- Crypto VWAP context is not provable in v1.
- Backfilled history is usable only as `EVENT_TIME`.

---

## 13. Out of Scope (not implemented)

- Chart renderer
- Training images
- Vision model or inference
- RSI, MACD, signals, arrows
- Changes to the Step 1 contract, the V4/V6 dashboard charts, provider adapters, the Phase 2 simulator or labels, or live trading logic
