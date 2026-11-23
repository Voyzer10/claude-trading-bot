# V6 Module A — Stabilization, Bug Fixes & Stress Validation (23 Nov 2026)

> **Update (23 Nov 2026, later): calendar behaviour reconciliation.** Item 10.4 below is now RESOLVED.
> - `detect_gaps` with no calendar now ALWAYS gives `UNKNOWN / SESSION_CALENDAR_MISSING`.
> - With a calendar, an irregular interval now gives `UNKNOWN / IRREGULAR_INTERVAL`.
> - `GapStream.report()` was added for batch/stream status parity.
> - `integrity.py` changed, and the suite is now 212 tests.
> - Details: `MODULE_A_CALENDAR_RECONCILIATION_REPORT.md`. The claims below that this update supersedes are marked *(superseded)*.

## Verdict: **PASS**

- **Defects:** 4 Module A defect families (D1–D4) were reproduced with failing tests before any fix. Each got the smallest possible fix, in allowed Module A files only.
- **Matrix:** all 30 required adversarial cases are covered by deterministic regression tests, and all pass.
- **Suite:** the full V6 suite passes, 207/207 under pytest and in script mode.
- **Historical regression:** the 25 historical segments give byte-identical output.
- **Open items:** none blocks a required behaviour. They are documented limitations or OPEN spec decisions (section 10), not reproducible defects.
- **Scope:** Module B was not started. Nothing was staged, committed, pushed or deployed.

## 1. Preflight (before any read or change)

| Item | Expected | Found |
|---|---|---|
| Branch | research/v6-smc-scanner | same |
| HEAD | 7f16f0953798a7b82e7cb595096487b66ab7ac3e | same |
| Index hash | e7490c2c616620c0 | same |
| Staged diff hash | f724a4ad7956d99c | same |
| Staged paths | 37 | 37, identical list |
| Spec SHA-256 | 835fc013…a2d8f | 835fc01360bb91563f1fa101b33e93f2147fc712e1a56522287a103ce38a2d8f |
| Worktree diff hash | 88ef185d8cae226f | same |
| Status hash (`git status --porcelain=v1 -uall`) | 8551dac70c90c7d2 | same |

The full git output was byte-identical to the previous task's postflight. Baseline test run: 183 passed.

**Scope verification.** None of the allowed files is among the 37 staged files:
- `candle_models.py` is tracked with an unstaged modification (` M`).
- `integrity.py`, `market_config.py`, `test_market_data.py` and `test_chart_ingestion.py` are untracked.
- `test_defect_fixes.py` covers the structure scanner, not Module A, so it was not touched.

## 2. Module A audit findings

| Area | Finding |
|---|---|
| A. Tick size | Positive finite number required; bool, string, NaN, ±inf, 0 and negatives are rejected; missing → `TickSizeStatus.MISSING`, never defaulted. OK. |
| A. Timeframe | `timedelta > 0` required; no string parsing; no default. OK. |
| A. Session calendar | EXCHANGE needs explicit ordered, non-overlapping intervals; CONTINUOUS must be explicit; IANA time zone mandatory. **D4:** a malformed session list or session bound escaped as TypeError / OverflowError. |
| A. Test-only isolation | Fixture config is always `TEST_FIXTURE`; `require_instrument_config` refuses it; unknown keys are an error. OK. |
| A. Fixture config | **D4:** `timeframe_seconds` too large for a timedelta raised OverflowError. |
| B. Strict loader | Every row is checked and nothing is skipped; reason priority and fields are correct; order is checked against the highest earlier source timestamp. **D1:** an out-of-range epoch crashed the loader with OverflowError. **D2:** an int beyond float range crashed it with OverflowError. **D3:** a non-sequence array raised TypeError (docstring promises CandleError), a str array was read char by char, and a dict was read by its keys as prices. |
| B. Legacy loader | Compatibility kept: skips None-price rows and records them; X03 records truncated-volume rows; a longer volume array is ignored (documented). Malformed values still raise as before, now as CandleError instead of OverflowError (D1 / D2 via `to_utc` / `Candle`). |
| B. Provenance | `CandleSeries` enforces strictly increasing positions, unique invalid rows, no candle/invalid overlap, and no unaccounted row between candles. OK. |
| B. `upto()` | Prefix positions are kept; only invalid rows before candle k's source row are included (no look-ahead). Trailing invalid rows are not in `upto(n-1)`, by documented design. OK. |
| C. Gaps | Batch counts are verified by the series invariant. The stream never infers a count from a position difference (None unless invalid positions are given or the rows are adjacent). The stream validates positions atomically. Parity holds with complete provenance. OK. |
| D. Completed candles | Completion must be an explicit bool; forming candles are never returned; abandoned candles are recorded, never completed; no duplication, reorder or change. OK. |
| D. Data state | NORMAL / RESUMED → INTERRUPTED and INTERRUPTED → RESUMED; staleness only with an explicit policy; no clock reads; nothing fabricated. DATA_RESUMED → NORMAL is **NOT_IMPLEMENTED** (not defined by the spec). |
| E. API boundary | `MarketDataProvider` is a Protocol only; no provider, credential or engine wiring; no hidden fallbacks found. OK. |

## 3–6. Reproduced defects, root cause, fix, regression test

Each defect was reproduced first: the probe script, then failing tests. Pre-fix result: `3 failed, 47 passed` (`test_chart_ingestion.py`) and `1 failed, 30 passed` (`test_market_data.py`).

### D1 — out-of-range timestamps crash instead of becoming INVALID_TIMESTAMP

- **Reproduction:** `to_utc(1e20)`, `to_utc(-1e20)` and `to_utc(10**400)` raised `OverflowError`. `inspect_chart_json` and `load_chart_json_strict` with such a `t` crashed instead of reporting the row.
- **Root cause:** `datetime.fromtimestamp` raises `OverflowError` / `OSError` / `ValueError` outside the platform range, and `math.isfinite(huge int)` raises `OverflowError`. `to_utc` wrapped neither, and `_try_utc` only catches `CandleError`.
- **Fix (`candle_models.to_utc`):** use `_finite()` and wrap `fromtimestamp` errors as `CandleError`.
- **Regression test:** `test_d1_out_of_range_timestamps_are_invalid_rows_not_crashes`.

### D2 — numbers beyond float range crash instead of becoming invalid values

- **Reproduction:** an OHLC or volume value of `10**400` crashed both the strict loader and `Candle(...)` with `OverflowError`.
- **Root cause:** `math.isfinite(int)` converts the int to float and overflows.
- **Fix:** a new helper `_finite()` returns False on overflow. It is used in `Candle.__post_init__` and `_bad_number`.
- **Regression test:** `test_d2_numbers_beyond_float_range_are_invalid_not_crashes`.

### D3 — strict loader accepted or mis-read non-sequence arrays

- **Reproduction:** `t` / `o` / `v` = 5 raised `TypeError`. `t = "abc"` gave three INVALID_TIMESTAMP rows. **`o = {0:1, 1:2, 2:3}` was read by its keys as open prices.**
- **Root cause:** `_chart_arrays` only called `len()`; it never checked the type.
- **Fix (`_chart_arrays`, strict path only):** every present array must be a `Sequence` other than str / bytes / bytearray; otherwise structural `CandleError`. Lists and tuples are unaffected. The legacy loader was not changed.
- **Regression test:** `test_d3_strict_arrays_must_be_real_sequences`.

### D4 — malformed configuration escaped as TypeError / OverflowError

- **Reproduction:** `from_fixture({"timeframe_seconds": 1e300})` raised OverflowError. `sessions: 5` and `sessions: [5]` raised TypeError. `SessionCalendar(..., 5)` raised TypeError. A session bound of `1e20` raised OverflowError.
- **Root cause:** timedelta overflow was not caught; the session list shape was not checked; the session-bound overflow came from D1.
- **Fix (`market_config`):**
  - `SessionCalendar` requires a tuple or list of pairs.
  - `from_fixture` checks the list shape, passes non-pairs through to `SessionCalendar` validation, and wraps timedelta overflow as `ConfigError`.
  - The session-bound case is fixed by D1.
- **Regression test:** `test_d4_malformed_configuration_is_config_error_not_crash`.

**Behaviour preserved:**
- No trading or structure rule was changed.
- The legacy result is unchanged.
- No default was added; no error was suppressed (each crash now raises the documented error type with a clear message).

## 4. Adversarial test matrix (actual results after the fix)

All tests are deterministic, need no network, and fabricate no OHLC.

| # | Input | Expected | Actual | P/F | Regression test |
|---|---|---|---|---|---|
| 1 | 5 valid 5m rows | complete, indices 0..4, positions 0..4, no gaps | as expected | PASS | test_m01 |
| 2 | `h=None` in row 1 | MISSING_OHLC, fields (high); strict raises; legacy skips + records | as expected | PASS | test_m02 |
| 3 | NaN / +inf / −inf in each OHLC field | INVALID_OHLC_VALUE; Candle raises | as expected | PASS | test_m03 |
| 4 | high < open, high < close | INCONSISTENT_OHLC, all 4 fields | as expected | PASS | test_m04_m05_m06 |
| 5 | low > open, low > close | INCONSISTENT_OHLC | as expected | PASS | test_m04_m05_m06 |
| 6 | high < low | INCONSISTENT_OHLC | as expected | PASS | test_m04_m05_m06 |
| 7 | o = h = l = c | valid, range 0 | as expected | PASS | test_m07 |
| 8 | `t=None` | MISSING_TIMESTAMP | as expected | PASS | test_m08_m09 |
| 9 | ISO string, NaN, inf, bool, list, 1e20, −1e20, 10**400 | INVALID_TIMESTAMP, ts None | as expected (1e20 / 10**400 crashed before the fix) | PASS | test_m08_m09, test_d1 |
| 10 | duplicate timestamp | NON_INCREASING_TIMESTAMP | as expected | PASS | test_m10_m11 |
| 11 | out-of-order timestamp | NON_INCREASING_TIMESTAMP; partial series keeps order | as expected | PASS | test_m10_m11 |
| 12 | no `v` key | documented all-zero volume | as expected | PASS | test_m12_to_m15 |
| 13 | `v=[]` | strict: structural CandleError | as expected | PASS | test_m12_to_m15 |
| 14 | shorter `v` | strict: CandleError; legacy: VOLUME_ARRAY_TRUNCATED recorded | as expected | PASS | test_m12_to_m15 |
| 15 | longer `v` | strict: CandleError; legacy: extra ignored (documented) | as expected | PASS | test_m12_to_m15 |
| 16 | 4 different invalid rows in 8 | all reported in source order; error lists all; every row accounted for | as expected | PASS | test_m16 |
| 17 | inconsistent OHLC, parseable ts | ts kept; row takes part in the timestamp order | as expected | PASS | test_m17_m18 |
| 18 | invalid ts plus missing high | INVALID_TIMESTAMP, fields (timestamp, high) | as expected | PASS | test_m17_m18 |
| 19 | invalid row vs absent timestamp | skipped_source_rows 1 vs 0 | as expected | PASS | test_m19 |
| 20 | `from_rows` (no positions) | provenance unknown, skipped None, invalid_rows refused | as expected | PASS | test_m20 |
| 21 | `upto(0 / 1 / 2 / n-1 / -1 / n)` with leading, inner and trailing invalid rows | correct prefixes; out of range raises IndexError; no look-ahead | as expected | PASS | test_m21 |
| 22 | GapStream with invalid positions | counts recorded rows (2) | as expected | PASS | test_m22_m23_m24 |
| 23 | GapStream without | None for an unverified difference, 0 when adjacent | as expected | PASS | test_m22_m23_m24 |
| 24 | batch vs stream, complete provenance | identical findings | as expected | PASS | test_m22_m23_m24 |
| 25 | duplicate, decreasing, negative, short, unaccounted or overlapping positions; GapStream with bad positions | CandleError / ValueError | as expected | PASS | test_m25 |
| 26 | no tick size | MISSING, value None | as expected | PASS | test_m26 |
| 27 | 0, negative, NaN, ±inf, str, bool, type object | ConfigError (validate / constructor / fixture) | as expected | PASS | test_m27 |
| 28 | no timeframe / calendar / session fields | UNKNOWN (TIMEFRAME_MISSING / SESSION_CALENDAR_MISSING); fixture fields stay None; malformed → ConfigError | as expected (overflow and non-iterable cases crashed before the fix) | PASS | test_m28, test_d4 |
| 29 | stale feed, no data, future data, missing policy | DATA_INTERRUPTED once; entries suspended; errors for bad input | as expected | PASS | test_m29 |
| 30 | fresh data after interruption | DATA_RESUMED; then stays RESUMED; no NORMAL path (NOT_IMPLEMENTED); can re-interrupt | as expected | PASS | test_m30 |

## 7–8. Test results (all executed during this task)

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/scanner_v6/test_chart_ingestion.py tests/scanner_v6/test_market_data.py
81 passed in 0.30s
$ PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/scanner_v6
207 passed in 1.14s          (baseline before this task: 183 passed; +24 new)
```

Script mode, `python3 -B tests/scanner_v6/<file>`, gives "all passed" for every file:

| File | Tests |
|---|---|
| test_bos | 7 |
| test_chart_ingestion | 50 |
| test_choch | 11 |
| test_defect_fixes | 12 |
| test_market_data | 31 |
| test_models | 12 |
| test_no_lookahead | 5 |
| test_regression_medium_bos | 6 |
| test_replay_audit | 12 |
| test_swing_fixtures | 41 |
| test_swing_mutants | 8 |
| test_swings | 12 |
| **Total** | **207** |

The structure-scanner regression tests (BOS, CHoCH, defect fixes, medium BOS, replay audit, no-look-ahead, swings) all pass unchanged.

## 9. Historical regression (25 segments, read-only)

The same tool as the visual validation (`run_v6.py`) was re-run with the fixed code into a scratch directory.

- Raw output SHA `a6d0d856e5255615b3496d3f4d3f5c2a8b18ef99564fd0fd0b8d11c2d05ed349`, **identical** to the frozen output.
- 25/25 integrity reports and scanner-event files identical.
- 25/25 strict ACCEPTED; 1,821 candles (unchanged); 0 invalid rows.
- Source rows consistent with each segment's range; no data lost.
- Structure scanner output unchanged.

As noted in the task, these segments are clean, so they do not exercise the warnings; the matrix above does.

## 10. Remaining limitations and OPEN items (not defects; no assumption implemented)

1. **DATA_RESUMED → NORMAL:** NOT_IMPLEMENTED; the spec does not define it.
2. **Volume None:** becomes 0.0, so missing and zero volume cannot be told apart (existing convention).
3. **Legacy loader:**
   - a longer volume array is ignored;
   - a non-sequence input still raises TypeError (legacy path deliberately unchanged; changing it needs owner approval).
4. *(superseded: RESOLVED by the calendar reconciliation; a missing calendar now always gives UNKNOWN / SESSION_CALENDAR_MISSING)* **`detect_gaps` without a calendar:** reports OK when there are no timestamp gaps. That means no gaps found, not session membership verified. **OPEN:** should a missing calendar always give UNKNOWN?
5. **Tick size:** has no lower bound (e.g. 1e-320 is accepted as positive and finite). **OPEN:** the spec defines no minimum.
6. **Duplicate timestamp after an invalid row:** a valid row whose timestamp equals an earlier invalid-OHLC row's timestamp is rejected as NON_INCREASING. This is documented (Fix 2) and may deserve an owner decision.
7. **`upto(n-1)`:** excludes trailing invalid rows (prefix semantics: "known at candle k's close").
8. **GapStream without invalid positions:** reports None where batch reports a count; parity is guaranteed only with complete provenance (by design: no inferred counts).
9. **No real configuration exists:** no production session calendar, tick size or provider (B-7…B-13 OPEN). Chart JSON carries no completion flag, so incomplete candles are handled only through `CompletedCandleGate` / `CandleUpdate`.

## 11. Changed files and SHA-256

| File | Change | Before | After |
|---|---|---|---|
| scanner_v6/data/candle_models.py | +19 / −6 (D1, D2, D3) | 029fb170…5ff5ca3 | 024fd32626ac90a9f6fbe622ea5081acf56639f50dcd39fe8ea14e06ff7824a8 |
| scanner_v6/data/market_config.py | +11 / −3 (D4) | 695aaca2…c33e80f | 12fb913586f51bb8d8e3c319940c6d8cc1e13841e1d39e90faef9017529bf648 |
| tests/scanner_v6/test_chart_ingestion.py | +217 / −0 (M01–M25, D1–D3) | 52e450a3…693c7f | 9961bf0b4a27a6f56c9e193286ff27e58d5b23c1fcc7b6e7e776ed3f3f5a41b1 |
| tests/scanner_v6/test_market_data.py | +85 / −0 (M26–M30, D4) *(superseded: now 87d2383e…, see the calendar reconciliation)* | 66bc5f94…cf04fc | 771f37a49fed75ec745b8998874a88323485f94bf68cafb948fa35d367baf0d1 |
| scanner_v6/data/integrity.py | unchanged in this task *(superseded: changed by the calendar reconciliation, now fcd9ad4f66f6ac69c72f1a3ed49dda64b0e86927b47c627e8399006195bb7d38)* | d2e2c92e… | d2e2c92ed2840a5136f1c4e0052fe4bb9fbce1daa75df60f38142450a43d9521 |

- **Review patch:** `ModuleA_stabilization_2026-11-23.patch`, SHA `cd648738897c434dcd62138ce50733a016f64e6727e6b3ff2f2eb6104f89bc53`.
- **Patch provenance:** the pre-change files were reconstructed and match the preflight hashes, 4/4.
- **Existing tests:** no existing test was edited; the new tests were appended.

## 12. Postflight

| Check | Result |
|---|---|
| Branch / HEAD | unchanged |
| Index hash | e7490c2c616620c0 (unchanged) |
| Staged diff hash | f724a4ad7956d99c (unchanged) |
| Staged paths | 37, identical list |
| Protected staged files | `sha256sum -c` ALL OK |
| Spec SHA | unchanged |
| Status hash (`-uall`) | 8551dac70c90c7d2 (unchanged; same 48 status lines) |
| Worktree diff hash | 88ef185d8cae226f → 207c7e9b9c789a3c, **expected**: `candle_models.py` is a tracked file with an unstaged edit; the same 9 tracked files show worktree changes |
| Changed files | exactly the 4 listed above (177-file uncommitted baseline: only these 4 differ) |
| New repo files | 0 |
| `.pyc` / `__pycache__` | 0 |
| Stash / commits / branches | 0 / none / unchanged |
| V4 / production (`/opt/trader`) | untouched |

## 13. Module B

**Module B was not started.** No Liquidity, Candlestick, Confirmation, Entry, SL/TP or Exit code was written, and no provider, credential, broker or engine wiring was added. PAPER ONLY.

Stopping here for owner review and acceptance.
