# V6 Module A — Calendar Behavior Reconciliation (23 Nov 2026)

## Result: done, all tests pass

- `detect_gaps()` now handles the four conditions as required.
- A missing calendar can no longer report `OK`.
- Regression tests reproduced the problem before the fix: 4 failed pre-fix.
- 212/212 tests pass, under pytest and in script mode.
- Scanner output on the 25 historical segments is byte-identical.
- Module B was not started. Nothing was staged, committed or deployed.

## 1. Preflight

| Item | Expected | Found |
|---|---|---|
| Branch | research/v6-smc-scanner | same |
| HEAD | 7f16f095 | 7f16f0953798a7b82e7cb595096487b66ab7ac3e |
| Index hash | e7490c2c616620c0 | same |
| Staged diff hash | f724a4ad7956d99c | same |
| Staged paths | 37 | 37, identical list |
| Spec SHA-256 | 835fc013…a2d8f | same |
| Protected staged files | — | `sha256sum -c` ALL OK |
| Stabilization changes present | candle_models 024fd326, market_config 12fb9135, integrity d2e2c92e, test_chart_ingestion 9961bf0b, test_market_data 771f37a4 | all 5 match |

Worktree diff `207c7e9b9c789a3c` and status `8551dac70c90c7d2` both match the post-stabilization state.

## 2. Root cause

`detect_gaps` decided its status only from whether an `UNCLASSIFIED_GAP` finding existed:

```python
if any(g.kind is GapKind.UNCLASSIFIED_GAP for g in gaps):
    return GapReport(UNKNOWN, "SESSION_CALENDAR_MISSING", ...)
return GapReport(OK, None, ...)
```

That had two consequences:

1. **Missing calendar could report OK.** With no calendar and no absent slot (contiguous candles, a single candle, an empty series, or only irregular spacing), the status was `OK`. It looked as if exchange-session validity had been checked, when no session check had happened at all. The existing test pinned this behaviour: `assert detect_gaps(ser(day(D1, 4)), M5, None).status is GapReportStatus.OK`.
2. **Unclassifiable interval reported OK.** With a calendar configured, an `IRREGULAR_INTERVAL` finding (spacing not a whole multiple of the timeframe, or shorter than it) still gave `OK`, although that interval cannot be classified as missing data or session closure.

`GapStream` had no status at all, so stream consumers had no batch-equivalent signal.

## 3. Fix (Module A only)

| File | Change | SHA-256 before → after |
|---|---|---|
| `scanner_v6/data/integrity.py` | +29 / −9 | d2e2c92ed2840a5136f1c4e0052fe4bb9fbce1daa75df60f38142450a43d9521 → **fcd9ad4f66f6ac69c72f1a3ed49dda64b0e86927b47c627e8399006195bb7d38** |
| `tests/scanner_v6/test_market_data.py` | +92 / −1 | 771f37a49fed75ec745b8998874a88323485f94bf68cafb948fa35d367baf0d1 → **87d2383ef9335b2ca18ba74499dc1513df02c063910ffa82334d871d2c1e00a5** |

**Changes in `integrity.py`:**
- A new helper, `_report(gaps, calendar)`, holds the single status rule. `detect_gaps` uses it after its existing timeframe check.
- `GapStream` now keeps its findings and has a new `report()` method using the same rule. This is a small **additive** API, added for batch/stream status parity. It changes no existing return value; `on_candle` is unchanged.
- The docstrings and the `GapReportStatus` comments were updated.
- No finding, kind, slot count, provenance count or session boundary logic was changed. No calendar is inferred.

**Status rule, in priority order:**

1. No timeframe → `UNKNOWN / TIMEFRAME_MISSING`, with no findings (unchanged).
2. No calendar → `UNKNOWN / SESSION_CALENDAR_MISSING`, **always**. Timestamp findings (`UNCLASSIFIED_GAP`, `IRREGULAR_INTERVAL`) are still listed.
3. A calendar, but at least one `IRREGULAR_INTERVAL` → `UNKNOWN / IRREGULAR_INTERVAL` (new reason). The finding is kept.
4. Otherwise → `OK`. It may still carry classified findings: `MISSING_CANDLES`, `SESSION_CLOSURE`, `OUT_OF_SESSION_CANDLE`.

**The one existing test line changed:** `test_a3_missing_timeframe_or_calendar_is_unknown_not_assumed` pinned the old behaviour. That single assertion now expects `UNKNOWN / SESSION_CALENDAR_MISSING`, with a comment noting the old value. All other existing assertions are unchanged.

## 4. Before / after

| Case | Before | After |
|---|---|---|
| Timeframe missing (any calendar) | UNKNOWN / TIMEFRAME_MISSING | same |
| No calendar, contiguous / single / empty series | **OK** | UNKNOWN / SESSION_CALENDAR_MISSING |
| No calendar, absent slots | UNKNOWN / SESSION_CALENDAR_MISSING (UNCLASSIFIED_GAP) | same |
| No calendar, irregular spacing only | **OK** | UNKNOWN / SESSION_CALENDAR_MISSING (IRREGULAR_INTERVAL listed) |
| Calendar, no gap | OK | same |
| Calendar, MISSING_CANDLES / SESSION_CLOSURE / OUT_OF_SESSION_CANDLE | OK with findings | same |
| Calendar, irregular interval | **OK** | UNKNOWN / IRREGULAR_INTERVAL |
| GapStream status | none | `report()` equals `detect_gaps` on the same prefix |

Known intraday gaps keep their exact findings (kind, slots, missing count, first/last missing time, session-break flag, skipped source rows). Only the status changes, and only in the three bold rows.

## 5. Regression tests (`test_market_data.py`)

| Test | Covers | Pre-fix result |
|---|---|---|
| `test_cal1_timeframe_missing_is_unknown` | condition 1, 5 series × 3 calendars | pass (unchanged behaviour) |
| `test_cal2_calendar_missing_is_always_unknown` | condition 2: empty / single / contiguous / absent slots / irregular; no session kinds without a calendar | **FAIL** (OK returned) |
| `test_cal3_calendar_configured_and_classifiable_is_ok` | condition 3, plus classified findings keep OK | pass (unchanged behaviour) |
| `test_cal4_calendar_configured_but_interval_unclassifiable_is_unknown` | condition 4: irregular, shorter than timeframe, mixed with MISSING_CANDLES; EXCHANGE and CONTINUOUS | **FAIL** (OK returned) |
| `test_cal5_stream_report_equals_batch_at_every_prefix_with_provenance` | `GapStream.report() == detect_gaps(s.upto(k))` at every prefix, 8 series × 3 calendars, including complete provenance with an invalid source row and a genuinely absent timestamp | **FAIL** (no `report`) |
| `test_a3_missing_timeframe_or_calendar_is_unknown_not_assumed` (updated line) | old pinned behaviour | **FAIL** after the test update (OK returned) |

Two mistakes in my own new test data were corrected during the run; the code was not changed for them:
- a 10:07 → 10:12 interval is regular, not irregular;
- a 10:55 + 7 min candle falls outside the test session, so OUT_OF_SESSION was correctly reported.

## 6. Test results (executed in this task)

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/scanner_v6/test_market_data.py tests/scanner_v6/test_chart_ingestion.py
86 passed in 0.40s
$ PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/scanner_v6
212 passed in 1.12s          (before this task: 207; +5 new tests)
```

Script mode, `python3 -B tests/scanner_v6/<file>`, gives "all passed" for every file:

| File | Tests |
|---|---|
| test_bos | 7 |
| test_chart_ingestion | 50 |
| test_choch | 11 |
| test_defect_fixes | 12 |
| test_market_data | 36 |
| test_models | 12 |
| test_no_lookahead | 5 |
| test_regression_medium_bos | 6 |
| test_replay_audit | 12 |
| test_swing_fixtures | 41 |
| test_swing_mutants | 8 |
| test_swings | 12 |
| **Total** | **212** |

## 7. Batch / stream compatibility

- **Findings:** unchanged. The existing parity tests (`test_a3_batch_stream_parity_and_determinism`, M22–M24, `test_stream_batch_parity_with_complete_provenance`) pass.
- **Status:** `GapStream.report()` equals `detect_gaps` at every prefix (test_cal5), with calendar CAL, CONT or none, with and without provenance, and before any candle.
- **Provenance:** `skipped_source_rows` handling is untouched. Parity of counts still requires complete provenance; without `invalid_positions` the stream keeps reporting None for an unverified position difference (unchanged, by design).

## 8. Historical compatibility (25 segments, read-only)

- **Scanner output:** raw output SHA `a6d0d856e5255615b3496d3f4d3f5c2a8b18ef99564fd0fd0b8d11c2d05ed349`, identical; 25/25 scanner-event files identical.
- **Integrity reports:** the only differing field is `gaps.status` / `gaps.reason`, which moved from `OK / None` to `UNKNOWN / SESSION_CALENDAR_MISSING` in all 25 (the run uses calendar None, since no production calendar exists). Findings are identical (0 gaps).
- **Earlier visual validation:** its stored integrity reports record `status OK` under the old behaviour. They were not rewritten (historical results stay as produced).

## 9. Postflight

| Check | Result |
|---|---|
| Branch / HEAD | unchanged (7f16f0953798a7b82e7cb595096487b66ab7ac3e) |
| Index hash | e7490c2c616620c0 (unchanged) |
| Staged diff hash | f724a4ad7956d99c (unchanged) |
| Staged paths | 37, identical list |
| Protected staged files | ALL OK |
| Spec SHA | 835fc01360bb91563f1fa101b33e93f2147fc712e1a56522287a103ce38a2d8f (unchanged) |
| Status hash (`-uall`) | 8551dac70c90c7d2 (identical) |
| Worktree diff hash | 207c7e9b9c789a3c (unchanged: both changed files are untracked) |
| Changed files | exactly `integrity.py` and `test_market_data.py` |
| New repo files / `.pyc` | 0 / 0 |
| Stash / commits | 0 / none |
| V4 / production | untouched |

- **Review patch:** `ModuleA_calendar_reconciliation_2026-11-23.patch`, SHA `aaf7d58335f86d8397325e7bfc837c28985b25a40e88eeda23946192389a378f`.
- **Patch provenance:** the pre-change files were reconstructed and match this task's preflight hashes.
- **Stabilization report:** updated. Item 10.4 is marked resolved, and the integrity / test hashes are marked superseded.

## 10. Remaining limitations

1. No production session calendar exists (B-7…B-13 OPEN), so every real-data gap report is now `UNKNOWN / SESSION_CALENDAR_MISSING` until one is configured. This is correct, but every consumer must treat UNKNOWN as "not checked".
2. `IRREGULAR_INTERVAL` is a new reason string. Any consumer that matches on reason strings must add it. No such consumer exists in the repo.
3. **Unchanged, as instructed:**
   - tick-size policy (no minimum);
   - duplicate-timestamp handling;
   - DATA_RESUMED → NORMAL (NOT_IMPLEMENTED);
   - volume None → 0.0;
   - legacy loader limitations;
   - all trading and structure rules.

**Module B was not started.** Stopping here for owner review.
