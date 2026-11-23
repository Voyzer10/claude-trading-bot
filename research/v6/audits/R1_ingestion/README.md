# R-1 data ingestion and evaluation: instructions

**Scope.** Research only (V6, Phase 3.1). This is an interface for adding more historical OHLC datasets to the R-1
protected-swing availability study.
- **No change to the V6 detector.** It is used read-only from the worktree.
- **No data are fabricated, filled or substituted.** Each new market is evaluated as a **separate dataset**.
- The Phase-3 NSE results in `../R1_artifacts/` are never modified.

## 1. What to provide

One **dataset directory** per market / source, containing:

```
<dataset_dir>/
  dataset.json          metadata (schema: dataset.schema.json; templates: templates/*.dataset.json)
  <INSTRUMENT>_<TF>.csv one CSV per instrument x native timeframe
```

**CSV format:**
- A header row is required.
- The columns are case-insensitive and may come in any order.

```
timestamp,open,high,low,close,volume
<bar time>,<open>,<high>,<low>,<close>,<volume or empty>
```

| Column | Rule |
|---|---|
| `timestamp` | ISO-8601 (with offset or `Z`; without an offset it is read in `timezone`), or epoch seconds / milliseconds (`timestamp_format`). It must be the bar **open** time, unless `timestamp_is` = `bar_close` (it is then shifted back by one timeframe). |
| `open, high, low, close` | numbers; raw vendor values, never edited |
| `volume` | optional; empty = 0 (not used by the detector) |

**Required metadata** for every file. Each field may be set once at the dataset level and overridden per file.

| Field | Meaning |
|---|---|
| `instrument` | the vendor's symbol, as traded (e.g. `BTC-USD`, `SPY`, `NIFTY 50`) |
| `exchange` | venue / feed (e.g. `Coinbase`, `IEX`, `NSE`) |
| `timeframe` | `1m 3m 5m 15m 30m 1h 2h 4h 1D` |
| `timezone` | IANA zone of the timestamps (`UTC`, `America/New_York`, `Asia/Kolkata`, …) |
| `date_range` | `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`: the declared, inclusive range in session-local dates |
| `data_source` | vendor + endpoint / product (and feed, e.g. IEX-only vs SIP) |
| `adjusted` | `adjusted`, `unadjusted` or `unknown`. `unknown` is allowed but carried into every output. |

**Strongly recommended:**
- `retrieval_date`: recorded, not inferred.
- `license_notes`.

**Session model** (`session`), one per dataset:
- `{"type": "24x7"}` for crypto:
  - UTC days;
  - no session gaps;
  - segments ASIA / EUROPE / US / LATE (UTC), with Sat / Sun = WEEKEND.
- `{"type": "exchange", "tz": …, "open": "HH:MM", "close": "HH:MM", "segments": […], "holidays": […]}` for an exchange
  session:
  - bars outside the session (pre / post-market) are excluded and counted;
  - the trading calendar is the union of session dates present in the dataset's valid files (minus any declared
    `holidays`).

## 2. Commands

**Environment:**
- Python ≥ 3.9 (zoneinfo). No third-party package is needed.
- `V6_ROOT` = the worktree whose `scanner_v6` is evaluated. Default: `/home/claude/v6_wt`.
- `R1_SCRIPTS` = the Phase-3 scripts directory. Default: `../R1_artifacts/scripts`.

Keep the raw datasets **outside the repository**, and copy the scripts out too if you prefer:

```bash
export V6_ROOT=/home/claude/v6_wt
S=research/v6/audits/R1_ingestion/scripts

python3 $S/r1_ingest.py validate /data/r1/crypto_coinbase_20261201          # exit 0 = every file OK, 2 = a file failed
python3 $S/r1_ingest.py evaluate /data/r1/crypto_coinbase_20261201 \
        --out /data/r1_results --derive 15m,1h,4h,1D --primary BTC-USD,ETH-USD,SOL-USD,XRP-USD
python3 $S/r1_ingest_selftest.py                                            # 16 validation self-tests
```

- **`--derive`** builds higher timeframes from the native one. For an exchange session, bars are anchored at the
  session open; for 24x7, at UTC midnight.
  - A derived bar missing any constituent is marked **incomplete**, which puts it in the DATA_QUALITY bucket.
  - A derived bar with no constituent is **absent**; nothing is created.
- **`--primary`** labels instruments PRIMARY (the plan's list); all others are EXTENDED. They are pooled separately.

## 3. Validation rules (nothing is repaired)

| Check | Effect |
|---|---|
| missing / invalid required metadata, unknown timeframe or zone, file not found | **dataset error** (nothing evaluated) |
| unparseable row, NaN / inf | row excluded, counted |
| OHLC inconsistent (low > min(o, c), high < max(o, c), low > high, price ≤ 0) | row excluded, counted |
| timestamp off the timeframe grid (anchored at the session open / UTC midnight) | row excluded, counted |
| bar outside the exchange session | row excluded, counted |
| identical duplicate timestamp | dropped, counted |
| **conflicting** duplicate timestamp | **file FAILS** |
| any row outside the declared `date_range` | **file FAILS** |
| excluded rows > `--max-bad-pct` (default 1 %) | **file FAILS** |
| out-of-order rows | sorted, counted (reported) |
| missing bars vs the expected grid × calendar | reported (`missing_candles`, `coverage_pct`), **never filled** |

A FAILED file is listed in `r1_ingest_validation.csv` and `r1_run_meta.json → failed`, and it is not evaluated. Fix the
**source export** (not the numbers) and re-run under a **new `dataset_id`**: an existing results directory is never
overwritten.

## 4. Evaluation and outputs

**Method.**
- The method and definitions are exactly those of `../R1_REAL_MARKET_EVALUATION_REPORT.md` §2:
  - the same buckets: DATA_QUALITY > SESSION_GAP > INSUFFICIENT_HISTORY > TRANSITION > UNKNOWN_STRUCTURE >
    STRUCTURED;
  - the same metrics, reliability thresholds (S ≥ 500, BOS ≥ 30, legs ≥ 30) and day-block bootstrap.
- Only the session / gap / segment functions are driven by the dataset's session model.
- For 24x7 data there is no SESSION_GAP bucket.

**Outputs** go to `<out>/<dataset_id>/`, separate from every other dataset:

| File | Content |
|---|---|
| `r1_ingest_validation.csv` | per file: metadata, SHA-256, valid bars, every QC counter, OK / FAIL |
| `r1_data_quality.csv` | per instrument × TF: start / end, candles, expected, missing, incomplete, coverage, calendar days, adjusted, source, S, reliability |
| `r1_summary_by_instrument_timeframe.csv` | every R-1 metric per series (the same columns as Phase 3, plus dataset / market / exchange / derived_from) |
| `r1_pooled_by_timeframe.csv` | pooled U % with 95 % day-block bootstrap CI, per sample |
| `r1_segments.csv`, `r1_unprotected_runs.csv`, `r1_s1_reselections.csv` | detail |
| `r1_run_meta.json` | dataset.json, calendar, evaluated / failed files, thresholds, detector root, evaluation time |

To aggregate several datasets, read each `<dataset_id>/r1_summary_by_instrument_timeframe.csv` and **group by
`market`**. Markets are never pooled together by default.

## 5. Validation evidence (this phase)

- **NSE round-trip** (`validation/nse_roundtrip_comparison.txt`). The 6 primary NSE cache files were re-exported to
  CSV (in the scratchpad, not the repo) and evaluated through this interface, with 15m / 1h / 1D derived.
  - The result was compared with the Phase-3 per-series table: 24 series, 1 656 metric fields, **0 differences**.
  - The pooled U % and bootstrap CIs are identical.
- **Self-test** (`validation/r1_ingest_selftest_results.txt`): **16 / 16 PASS** on tiny **synthetic, test-only** files,
  which are never reported as market results. It covers:
  - missing / invalid metadata;
  - conflicting and identical duplicates;
  - OHLC exclusion below and above the threshold;
  - out-of-range rows; off-grid bars;
  - epoch-ms + bar-close timestamps;
  - a US session across the 1 Nov 2026 DST change, with naive local timestamps and a pre-market bar excluded;
  - a 24x7 series with a deliberate 1-hour hole: 12 missing 5m bars reported and not filled; the 1h bar absent; the
    4h / 1D bars incomplete; no SESSION_GAP; WEEKEND segment present;
  - refusal to overwrite results.
- **Self-test lesson.** A generator with fixed wick sizes produced no swings at all: every peak became an equal-high
  tie, which SW-004 does not count. Synthetic inputs must have independent wicks.

## 6. Getting the missing markets (nothing has been downloaded)

| Market | Where the data can legitimately come from | Notes |
|---|---|---|
| Crypto BTC / ETH / SOL / XRP | Coinbase Exchange public candles (no key) | Not reachable from this workspace. It can be fetched on the VPS / a computer with internet and attached. The API returns at most 300 candles per request, newest first (`[time, low, high, open, close, volume]`); re-order to the CSV columns above. |
| US SPY / QQQ / 6 large caps | a licensed historical source the owner chooses | Alpaca needs a key, which is excluded here unless the owner supplies the export. Record IEX-only vs SIP and adjusted / unadjusted. |
| NSE NIFTY 50 / NIFTY BANK | a licensed historical source | The index has no volume. Use the same NSE session as the stocks. |

Add each as its own `dataset_id`. If a requested instrument or timeframe cannot be obtained, leave it out and list it
as unavailable. **Do not substitute** another instrument or vendor without a separate, labelled dataset.
