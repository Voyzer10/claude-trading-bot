# V6 BOS + CHoCH: Phase 2 defect fix report

Date: 22 Nov 2026 · Worktree `/home/claude/v6_wt` · Branch `research/v6-smc-scanner` · HEAD
`7f16f0953798a7b82e7cb595096487b66ab7ac3e`

Source: `research/v6/audits/V6_BOS_CHOCH_CODE_AUDIT.md`

**Scope:** D-1, D-2 (inside the CHU04 boundary), D-3, D-4. D-5 is reported only. S-1 and R-1 are analysis only.

**Not done:**
- Nothing staged, unstaged, committed, pushed, merged, rebased, reset or deployed.
- No V4, production, broker or Liquidity-Sweep code.
- No auto-formatting.

## 1. Summary

| ID | Fix | Behaviour change |
|---|---|---|
| D-1 | Equal-price swings get a neutral `EQUAL_SWING_PRICE` diagnostic. `MIXED_STRUCTURE` claims CHU05 only for HH + LL; LH + HL is MIXED without a CHU05 claim. | **Diagnostic text / code only.** State stays UNKNOWN (A3). |
| D-2 | A close exactly at the protected level gets a neutral `EXACT_LEVEL_CLOSE` diagnostic (not `WICK_ONLY`). The strict close is documented as the **current default, CHU04 unresolved**. | **Diagnostic only.** No CHoCH emission or transition changed. |
| D-3 | Dead `_opposite()` removed (0 callers in the repo) | none |
| D-4 | `medium_bos.json` → `easy_bos.json` (EASY01 / EASY02, with `legacy_case_id` MED01 / MED02); all code references updated | none; candle and expectation data are identical (SHA-256 checked against the index blob) |

**Equivalence proof:**
- Pre-fix `choch.py` (saved copy) vs the fixed module, comparing events, state timeline, protected level per candle and
  BOS:
  - **0 differences** on all 22 CHoCH fixtures and their mirrors (44 series);
  - **0 differences** on 300 integer-grid random series, which contained 23 exact-level closes.
- Only diagnostics changed.

## 2. Defects, root causes and fixes

### D-1: MIXED_STRUCTURE claimed CHU05 for equal-price swings

- **Root cause.** `_establish` uses strict comparisons for HH / HL / LH / LL. Every other combination fell into one
  `else` branch with the fixed text "A3; CHU05 unresolved". That branch also catches:
  - equal highs or equal lows (FIXTURE_REVIEW C6, open);
  - LH + HL (contracting structure).

  Neither of those is CHU05 (HH + LL). In the audit fuzz, 127 of 255 MIXED diagnostics came from equal prices.
- **Fix** (`scanner_v6/structure/choch.py`, `_establish`, `else` branch only):
  - equal high or equal low → `EQUAL_SWING_PRICE`, citing C6 as open;
  - HH + LL → `MIXED_STRUCTURE` "HH + LL (CHU05 unresolved)";
  - LH + HL → `MIXED_STRUCTURE` "LH + HL: no approved classification".

  The branch still returns `None`, so the state stays UNKNOWN in every case. Docstring updated.
- **Before / after** (synthetic, c14):

| Input | Before | After |
|---|---|---|
| highs 22.5→22.5, lows 15.5→16.5 | MIXED_STRUCTURE "…(A3; CHU05 unresolved)" | EQUAL_SWING_PRICE "…not approved (FIXTURE_REVIEW C6, open); stays UNKNOWN (A3)" |
| highs 22.5→24.5, lows 15.5→14.5 | MIXED_STRUCTURE "…(A3; CHU05 unresolved)" | MIXED_STRUCTURE "HH + LL (CHU05 unresolved); stays UNKNOWN (A3)" |
| highs 22.5→21.5, lows 15.5→16.5 | MIXED_STRUCTURE "…(A3; CHU05 unresolved)" | MIXED_STRUCTURE "LH + HL: no approved classification; stays UNKNOWN (A3)" |

  Events are `[]` and the state is UNKNOWN in all six runs (each case and its mirror), before and after.

### D-2: an exact-level close was labelled WICK_ONLY

- **Operators** (`StructureStream.on_candle`):
  - `beyond = close < prot` (bearish) / `close > prot` (bullish): **strict**;
  - `wick = low < prot` / `high > prot`.
- **Root cause.** When `close == prot`, `beyond` is False. The code then fell through to `elif wick`, so a candle that
  closed exactly on the level was recorded as "NO_CHOCH … WICK_ONLY". This presented the unresolved CHU04 question as
  if it were settled wick-only evidence.
- **Fix:**
  - New `at_level = close == prot`, checked **after** `beyond` and **before** `wick`. It writes only an
    `EXACT_LEVEL_CLOSE` diagnostic: "…no CHoCH under the current strict-close default; CHU04 unresolved".
  - The `beyond` branch (CHoCH / COMPLEX) is untouched, so emission and transitions are unchanged.
  - Docstring: A6 says the strict comparison is the **current default, not an approved CHoCH decision**; a separate
    CHU04 paragraph states that it is unresolved.
- **Before / after:**

| Case | Before | After | Events (before = after) |
|---|---|---|---|
| CHU04 (c18 close 101 = protected 101, low 100) | WICK_ONLY | EXACT_LEVEL_CLOSE | ESTABLISHED c16 only |
| CHU04 mirror (close 99 = protected 99) | WICK_ONLY | EXACT_LEVEL_CLOSE | ESTABLISHED c16 only |
| CHD03 (wick 100, close 102) | WICK_ONLY | WICK_ONLY | ESTABLISHED c16 only |
| CHD01 / CHD02 (close strictly beyond) | – | – | CHoCH c18 + TRANSITION |

- **Side effect** (diagnostic only): a close on the level whose wick does *not* cross it used to produce no diagnostic.
  It now produces EXACT_LEVEL_CLOSE.

### D-3: unused `_opposite()`

- **Callers:** the repo has no reference outside its definition. It was a leftover helper; no rule needs it, because
  CHoCH direction is derived from `pre_state`.
- **Fix:** removed (4 lines). No new abstraction.

### D-4: `medium_bos.json` held the Easy charts

**References inspected** (all files, including docs):

| Reference | Action |
|---|---|
| `tests/scanner_v6/test_regression_medium_bos.py` (path, docstring, 7×MED01, 7×MED02) | path → `easy_bos.json`; ids → EASY01 / EASY02; docstring corrected |
| `tests/scanner_v6/test_bos.py` (path) | path updated |
| `research/v6/specs/choch_v0_9/build_choch_drafts.py` (path, MED01 / MED02 lookups) | updated; rerun gives a **byte-identical** `choch_fixtures.draft.json` |
| `research/v6/experiments/medium_bos_retest.py` (FIXTURE path) | updated; `grade` → RETEST: ALL PASS |
| `scanner_v6/README.md` (test list comment) | updated |
| `research/v6/specs/volume1/MEDIUM_BOS_MISTAKE_RCA.md` (coverage line) | updated |

**Fixture:**
- `tests/scanner_v6/fixtures/regression/easy_bos.json` (new): `dataset` = `v6_regression_easy_bos`, plus an
  `identity_note`.
- Each case keeps `legacy_case_id` (MED01 / MED02). `source` says "Easy visual exam, Chart N … (formerly mislabelled
  Medium)".

**Data preserved:**
- candles, expected_swings, expected_equal_levels, expected_bos and rejected_mistake were compared;
- the canonical-JSON SHA-256 is `58be2734…c6ec8` for both the index blob of `medium_bos.json` and `easy_bos.json`;
- a test now pins it.

**Old file:**
- `medium_bos.json` was removed **from the working tree only**. Its staged blob is untouched in the index (status `AD`),
  and a byte copy is in the session scratchpad.
- Nothing was overwritten: the Medium-chart data (still not provided) was never substituted.

## 3. D-5 whitespace findings (reported only; untouched)

| File | Error | Staged | Working tree |
|---|---|---|---|
| `research/v6/specs/volume1/SYNTHETIC_DATASET_PLAN.md` | line 1326: new blank line at EOF (the file ends `\n\n`) | yes | yes (identical to staged) |
| `research/v6/specs/volume1/TEST_CASE_CATALOG.md` | line 128: new blank line at EOF (the file ends `\n\n`) | yes | yes (identical to staged) |

- Both are new files (not in HEAD).
- `git diff --check` (working vs index) is clean for them. `git diff --cached --check` still fails (rc = 2) with exactly
  these two lines.
- The fix would delete one trailing newline in each file and re-stage it. **Awaiting separate approval.**

## 4. S-1 and R-1

Full documents (untracked):
- `research/v6/audits/S1_PROTECTED_RESELECTION_ANALYSIS.md`
- `research/v6/audits/R1_REAL_MARKET_EVALUATION_PLAN.md`

**S-1 (no code change):**
- A same-leg lower low that confirms after the origin was already activated: the current code keeps 106 →
  **CHoCH at c22**.
- The literal reading L-a (origin = 104, A5 fails, fall back to 101) → **no CHoCH**.
- Measured on CHD01 c1–c16 plus c17–c22 (both directions).
- Four decision options are listed in the S-1 doc. It needs an owner decision.

**R-1 (plan only; not run):**
- Markets and timeframes:
  - crypto via Coinbase: BTC, ETH, SOL, XRP;
  - NSE via Zerodha: NIFTY, BANKNIFTY and 6 large caps;
  - US via Alpaca IEX: SPY, QQQ and 6 large caps;
  - timeframes 5m / 15m / 1h / 1D, plus 4h for crypto.
- Metrics M1–M8: unprotected %, causes, run lengths, bullish / bearish split, event rates, ATR distance, S-1
  frequency, breaks missed during gaps.
- Segmentation: session, volatility tercile, trend label, gap proximity.
- A matched synthetic control is run separately.
- **The 59 % random-walk figure is not a market statistic.**

## 5. New tests: `tests/scanner_v6/test_defect_fixes.py` (12, untracked)

- **D-1:**
  - `test_d1_equal_swing_price_is_not_labelled_chu05`
  - `test_d1_hh_plus_ll_keeps_the_chu05_mixed_label`
  - `test_d1_lh_plus_hl_is_mixed_but_not_chu05`
  - `test_d1_chu05_fixture_still_mixed_and_unknown`

  Each runs the bullish and the mirrored input and asserts UNKNOWN with no events.
- **D-2:**
  - `test_d2_wick_only_rejection_both_directions` (CHD03 / CHD04)
  - `test_d2_close_strictly_beyond_is_a_choch_both_directions` (CHD01 / CHD02)
  - `test_d2_exact_level_close_is_not_wick_only_and_chu04_stays_open` (CHU04 + mirror). It asserts the label and that
    emission is unchanged; it does **not** score CHU04.
  - `test_d2_mirror_states_are_symmetric`
- **D-3:** `test_d3_opposite_helper_removed`
- **D-4:**
  - `test_d4_easy_fixture_identity_and_legacy_ids` (data SHA, legacy ids, old file gone)
  - `test_d4_no_code_reference_to_the_old_fixture_name`
- **Causality:** `test_new_inputs_batch_stream_parity_and_no_lookahead` (`replay_audit` + `no_lookahead_violations` on
  all new inputs and mirrors)

**Existing tests:** none deleted, skipped or weakened. The only edits are the D-4 path / id updates in
`test_regression_medium_bos.py` and `test_bos.py`; their assertions are unchanged.

## 6. Test execution (Python 3.13.18, pytest 9.1.1)

```
pytest -q tests/scanner_v6/test_defect_fixes.py                          12 passed
pytest -q test_choch.py test_bos.py test_regression_medium_bos.py        24 passed
pytest -q tests/scanner_v6                                               126 passed   (baseline 114 + 12 new; 0 failed)
  per file: bos 7 · choch 11 · defect_fixes 12 · models 12 · no_lookahead 5 · regression 6 · replay_audit 12 ·
            swing_fixtures 41 · swing_mutants 8 · swings 12
script mode: test_choch / test_bos / test_regression_medium_bos / test_defect_fixes / test_replay_audit /
             test_no_lookahead → "all passed"
research/v6/experiments/medium_bos_retest.py grade                       RETEST: ALL PASS
```

- **Parity and no-look-ahead:** `test_choch` / `test_bos` `test_causality_and_batch_stream_parity` and the new
  causality test pass.
- **Mirror:** the D-1 / D-2 tests run mirrored inputs, and `test_d2_mirror_states_are_symmetric` passes.

## 7. Remaining known issues

**Open decisions (unchanged):**
- CHU04, CHU05, C6;
- O4, O5 residual, O7, O8, O9;
- A1;
- **S-1** and **R-1** (above).

**Naming debt (intentionally not renamed):**
- `test_regression_medium_bos.py` (module name), its `test_A_med01_…` function names, and the `MED` variable in
  `test_bos.py`. Renaming would change test identities; that needs approval.
- `research/v6/retest/answer_keys/medium_answer_key.json` and `retest/medium/`.
- MED01 mentions in the liquidity docs (resolvable through `legacy_case_id`).
- The untracked test-pack ZIP snapshot and `exports/TEST_INSTRUCTIONS.md` still say `medium_bos.json` / 114.

**Index vs working tree:**
- The 37 staged files are the **pre-fix** versions. Seven of them now differ in the working tree, and
  `medium_bos.json` is deleted there.
- If the pending save-point commit is made from the index as it is, it will **not** include these fixes.
- Re-staging is a separate decision for the owner.

**Audit residuals still open:** R-2 (weak parity), R-3 (O4 diagnostic spam), R-4 (COMPLEX path unreachable), R-5, R-7,
and the §11 coverage gaps.

## 8. Approved rules preserved

- Swings (SW-001…005), BOS (Option A, D4, BOS-002, BOS-005, D5), and CHoCH A1–A10 / D1 / D2 P-B / D3 / D5: no code path
  changed. `swings.py`, `bos.py`, `protected_levels.py` and `engine.py` are byte-unchanged.
- In `choch.py`, only diagnostics, a docstring and the dead helper changed.
- Before / after equivalence: 0 differences in events, states, protected levels and BOS across 44 fixture series and
  300 fuzz series.

## 9. Git state

**Index:**
- `git ls-files -s` is identical to the Phase-2 start.
- The SHA-256 of `git diff --cached` = `f724a4ad7956d99c…` (unchanged).
- 37 staged files.

**Status changes vs the start:**
- `AM` for `medium_bos_retest.py`, `build_choch_drafts.py`, `MEDIUM_BOS_MISTAKE_RCA.md`, `test_bos.py`,
  `test_regression_medium_bos.py`.
- `MM` for `scanner_v6/README.md` and `structure/choch.py`.
- `AD` for `fixtures/regression/medium_bos.json`.
- New untracked: `fixtures/regression/easy_bos.json`, `tests/scanner_v6/test_defect_fixes.py`, and three docs under the
  already untracked `research/v6/audits/`.

No commit, push, merge, rebase, reset or deploy.
