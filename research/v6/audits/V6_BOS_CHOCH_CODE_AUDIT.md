# V6 BOS + CHoCH code audit (read-only, 22 Nov 2026)

**Scope:**
- Worktree `/home/claude/v6_wt`, branch `research/v6-smc-scanner`, HEAD `7f16f09`, plus the uncommitted / staged V6 work.
- Read-only: no code, test, spec or git state was changed by this audit.
- Every check script ran from the session scratchpad and wrote nothing into the repo. Python bytecode writing was disabled, and coverage data was kept in the scratchpad.

**Labels:**
- **PASS:** verified against the approved spec.
- **FAIL:** a confirmed deviation.
- **PARTIAL:** correct where tested, with gaps.
- **NOT VERIFIED.**
- **OPEN BY DESIGN:** the rule is unresolved, so it is not counted as a failure.

## 1. Executive summary

- **The approved rules are implemented as documented.** That covers swings L2/R2 strict, BOS Option A / D4 / BOS-005, and CHoCH D1–D5. No approved rule was found to be violated.
- **The fuzz check was clean.** It covered 434 series: 400 random walks with integer / half / quarter ticks (to force ties), the 12-chart pack and the 22 CHoCH drafts. Results:
  - 0 crashes and 0 invariant violations;
  - 0 mirror asymmetries;
  - 0 look-ahead violations and 0 batch / stream parity failures.
- **Unresolved items stay unresolved in behaviour.** O4, O7, O8 and O9 are diagnostics only, and CHU05 stays UNKNOWN. **CHU04 is effectively defaulted to a strict close**; this is documented, but it is still a default.
- **No functional defect was confirmed.** Five low-severity defects were confirmed: two diagnostic labels, one dead function, one fixture naming issue and one whitespace problem in staged files.
- **One spec gap was demonstrated (S-1):** the D2 origin re-selection is order-dependent when a lower low in the same BOS leg confirms after an earlier one was already activated (§9 / §10).
- **Largest risk (R-1):** in random data, **59 % of the candles in a BULLISH / BEARISH state have no protected swing in force**, so a CHoCH is impossible there. This follows from the approved D2 (P-B) + A5 + "no origin swing → unchanged". It needs real-data evaluation before any trading use.
- **Not production-ready** (§12). This is research code: not wired to any runner or broker, never evaluated on real data, and with open decisions.

## 2. Files inspected

| Area | Files |
|---|---|
| Code | `scanner_v6/structure/swings.py` (150 lines), `bos.py` (84), `protected_levels.py` (95), `choch.py` (292), `engine.py` (223), `models.py` (229), `data/candle_models.py` (138), `config.py`; the stubs in `liquidity/`, `entry/`, `exit/`, `fvg/`, `order_blocks/` |
| Tests | `tests/scanner_v6/`: `test_swings.py`, `test_swing_fixtures.py`, `test_swing_mutants.py`, `test_bos.py`, `test_choch.py`, `test_regression_medium_bos.py`, `test_replay_audit.py`, `test_no_lookahead.py`, `test_models.py`, `_util.py` |
| Specs / decisions | `research/v6/specs/volume1/*` (incl. `BOS_RULE_MATRIX.md`, `FIXTURE_REVIEW.md`, `MEDIUM_BOS_MISTAKE_RCA.md`); `research/v6/specs/choch_v0_9/PHASE1_2_DECISIONS.md` (approval register, rev. 2), `AUDIT_CHD01-09.md`, `README.md` |
| Fixtures | `research/v6/specs/volume1/synthetic_volume1.draft.json`, `swing_oracle_addendum.json`; `research/v6/specs/choch_v0_9/choch_fixtures.draft.json` (CHD01–CHD16, CHU01–CHU06); `tests/scanner_v6/fixtures/regression/medium_bos.json` |
| External test data (not in the repo) | The user's 12-chart pack: OHLC JSON + PNG, read from the session scratchpad |

## 3. Module-by-module findings

| Module / concern | Result | Evidence | Notes |
|---|---|---|---|
| **Swing detection** (`swings.py`) | **PASS** | SW-001…005 in the code (`_beats` is strict; ties go to `unresolved_equal_levels` only). 41 fixture tests and 8 mutant tests (inclusive / wick / window mutants must fail). Batch and stream share `_evaluate`. | Initial history (a full left window only) and gaps: **OPEN BY DESIGN** (SW unresolved) |
| **BOS** (`bos.py`) | **PASS** | Reference = the latest confirmed swing per kind (D4), strict close (BOS-002), emitted at k (BOS-004), one per reference id (BOS-005), swings from k−1 only (D5). Matches all 15 Volume-1 BOS drafts under the approved-profile key, the test-local evaluator on every fixture, and the Medium regression. | BOS-006 (gap / exact / tick) and BOS-007 (close-back): **OPEN BY DESIGN**, not assumed |
| **Protected swing lifecycle** (`protected_levels.py`, D2 P-B) | **PARTIAL** | Origin = the lowest (highest) confirmed opposite swing in (ref.index, k]; A5 HL / LH check; activation at its own confirmation; retention until then; newer BOS replaces older; consumed set. Verified by CHD16 / CHD13, the pack, and the fuzz invariant "protected confirmed ≤ the candle". | Untested branches (§11). **Spec gap S-1** (order-dependent re-selection). The "continuation" wording of D2 is undefined while the state is UNKNOWN (§10 R-5). |
| **CHoCH detection** (`choch.py`) | **PASS** (approved parts) | Close strictly beyond the pre-candle protected swing; only from BULLISH / BEARISH; one per protected id; wick-only gives the WICK_ONLY diagnostic. Fuzz: 71 CHoCH, every one checked for pre-state, pre-candle protected price, protected confirmed < k, close beyond, and TRANSITION after. | CHU04 exact-level close defaults to strict: **OPEN BY DESIGN** (documented default; see D-2) |
| **Structure state transitions** | **PASS** | UNKNOWN → BULLISH / BEARISH only through A2 / A4 establishment at step 4; CHoCH → TRANSITION; TRANSITION → confirmed only through a same-direction BOS; no other path. 363 establishments in the fuzz without error. | Mixed / equal swings stay UNKNOWN (CHU05 / C6: **OPEN BY DESIGN**); the label issue is D-1 |
| **Transition confirmation (D1)** | **PASS** | Confirmation requires the pre-candle state to be TRANSITION, so a same-candle BOS cannot confirm. CHD10 / CHD11 cover both directions. Fuzz: 29 reversals, every one with pre-state TRANSITION and the cited BOS on that candle. | Old-direction BOS during TRANSITION → `O4_UNRESOLVED` only (**OPEN BY DESIGN**); that code path is untested (§11) |
| **Complex break (D3)** | **PARTIAL** | X1 is verified (CHD12; pack Hard 1 / Extreme 1 `levels_crossed`). `classify_break` is unit-tested; a `ComplexStructureBreak` can be constructed (checked in the audit). | The event path is **unreachable** with one protected swing per direction (documented), so it is never exercised end to end. The state after COMPLEX (UNKNOWN) is a placeholder, **OPEN BY DESIGN** (O5 residual). |
| **D5 same-candle order** | **PASS** | In code: `prot` and `known_before` are captured before BOS evaluation; BOS uses `_latest` before the swing update; P-B activation and establishment happen after the state update. Tests: CHD15 (no CHoCH while UNKNOWN), CHD16 (c20 swing not used). Fuzz invariant: protected confirmed ≤ candle, and CHoCH protected confirmed < k. | – |
| **Batch vs streaming parity** | **PASS, but a weak test** | `replay_audit` with `detector` + `make_stream` is clean on all repo fixtures, the 12 pack charts and 60 fuzz series (structure + BOS). | Batch detectors are implemented **by running the stream**, so parity is close to tautological and cannot catch logic errors shared by both (R-2) |
| **No-look-ahead** | **PASS** | `no_lookahead_violations` on the same set: 0. The streams hold only the candles already fed. Swings are emitted at i + R; no event refers to a future candle. | – |
| **Event ids / duplicates** | **PASS** | `bos:<dir>:<swing id>`, `choch:<dir>:<protected swing id>`, `state:<k>:<from>-><to>`, `complex:<k>`. Every id is unique across 434 series; `replay_audit` checks duplicates and repaint. | Stable-id semantics across data revisions: O8 (**OPEN BY DESIGN**) |
| **Event timestamps / indices** | **PASS** | BOS, CHoCH and state changes are stamped `index = confirmed_index = k`; swings `index i`, `confirmed i + R`; ESTABLISHED at the confirming candle | – |
| **Diagnostics / unresolved handling** | **PARTIAL** | O4 and O9 never change the state; CHU05 stays UNKNOWN; nothing is invented on CHU01 / 04 / 05 (tests). | D-1 / D-2 label inaccuracies; O4 diagnostic repeats every candle (R-3) |
| **Integration boundaries** | **PASS** | `scanner_v6` has **no** non-stdlib, non-relative import (grep); `test_models` enforces V4 isolation; `liquidity/`, `entry/`, `exit/`, `fvg/`, `order_blocks/` are unchanged vs HEAD (still stubs); `choch.py` uses `BOSStream` as its BOS source, so they are consistent by construction | – |
| **Symmetry** | **PASS** | Mirror test (p → 2000 − p) on 434 series: identical swings, BOS, events and timeline after mapping | – |

## 4. Approved rule compliance matrix

| Approved decision | Implemented where | Result |
|---|---|---|
| Swing window L2/R2 (SW-002) | `SwingConfig(left=2, right=2)` | PASS |
| Strict pivot comparison (SW-003); equal levels are not swings (SW-004) | `_beats`, `_check` | PASS |
| BOS Option A: independent of structure direction | `BOSStream`, which has no state input | PASS |
| BOS D4: latest eligible confirmed swing reference, no latest-unbroken fallback | `BOSStream._latest` + `_used` | PASS |
| BOS-005: one BOS per reference swing id | `_used` set; id = `bos:<dir>:<swing id>` | PASS |
| CHoCH D1: CHoCH → TRANSITION → a later new-direction BOS confirms; a same-candle BOS never does | `on_candle` step 3 (`pre_state` must be TRANSITION) | PASS |
| CHoCH D2: protected = BOS-origin swing, only after its L2/R2 confirmation, previous kept until then | `ProtectedTracker` | PASS on fixtures; **spec gap S-1** for late lower candidates |
| CHoCH D3: X1 for one responsible protected swing; COMPLEX for genuinely competing ones, never forced | `classify_break` + branch | PASS for X1; the COMPLEX path is unreachable / untested (PARTIAL) |
| D4 (CHoCH context): latest eligible confirmed swing reference | via `BOSStream` | PASS |
| D5: BOS → CHoCH on the pre-candle state → state update → swing confirmation | `on_candle` order | PASS |

## 5. Unresolved rule handling

| Item | Behaviour in code | Result |
|---|---|---|
| O4 (failed CHoCH; old-direction BOS during TRANSITION) | `O4_UNRESOLVED` diagnostic; no event; no state change | OPEN BY DESIGN (kept) |
| O5 residual (state after COMPLEX) | UNKNOWN + `unresolved_reason`, in an unreachable path | OPEN BY DESIGN |
| O7 (gaps / sessions) | none; candles counted as given | OPEN BY DESIGN |
| O8 (ids / invalidation) | deterministic ids; no invalidation | OPEN BY DESIGN |
| O9 (initial chronology) | `O9_UNRESOLVED` when established with the close already beyond protected (4 in fuzz + CHD15); later behaviour unscored | OPEN BY DESIGN |
| CHU04 (strictness of the CHoCH close) | strict default (same as BOS); the exact-level close is logged as WICK_ONLY | OPEN BY DESIGN, **but a behavioural default exists** (see D-2) |
| CHU05 (mixed HH + LL) | stays UNKNOWN (A3) with MIXED_STRUCTURE | OPEN BY DESIGN |
| A1 (external structure) | every L2/R2 swing treated as external | OPEN BY DESIGN (documented limitation) |
| Proposed Liquidity B0 rules | not implemented (stubs unchanged) | correct: not treated as approved |

**No proposed rule was found treated as approved**, apart from the documented CHU04 strict default.

## 6. No-look-ahead findings

- `no_lookahead_violations(detect_structure / detect_bos, s)` returns `[]` on:
  - every repo fixture;
  - the 12 pack charts;
  - 60 fuzz series (25–90 candles).
- Fuzz invariant: the protected swing in force at every candle has `confirmed_index ≤ candle`. A CHoCH's protected swing has `confirmed_index < k`, and a BOS reference has `confirmed_index < k`. **0 violations.**
- **Structurally:**
  - The streams receive candles one by one.
  - `detect_swings` never evaluates the last R candles.
  - Nothing reads `series[k+1:]`.
- **Result: PASS.**

## 7. Batch / stream parity results

- `replay_audit(series, oracle, detector=…, make_stream=…)` for structure and BOS on the same set: **0 findings** in every category (premature / early / late / missing / unexpected / duplicate / repaint / parity_time / parity_fields).
- **Caveat:** both modes share the stream code, so this mainly proves prefix-stability and determinism, not two independent implementations agreeing.
- The BOS module is additionally checked against an **independent** test-local evaluator (`approved_bos`): equal on every fixture.
- No independent evaluator exists for CHoCH.

## 8. Test execution results

**Commands, run from `/home/claude/v6_wt`, with no cache or bytecode written:**
```
python3 -m pytest -p no:cacheprovider -q tests/scanner_v6
→ 114 passed in 0.63s
```

**Tests per file:**

| File | Tests |
|---|---|
| test_bos.py | 7 |
| test_choch.py | 11 |
| test_models.py | 12 |
| test_no_lookahead.py | 5 |
| test_regression_medium_bos.py | 6 |
| test_replay_audit.py | 12 |
| test_swing_fixtures.py | 41 |
| test_swing_mutants.py | 8 |
| test_swings.py | 12 |

**Coverage**, with coverage 7.x installed in the scratchpad only (`--branch`): structure 95 % overall.

| Module | Coverage | Uncovered |
|---|---|---|
| `choch.py` | 95 % | 65 (`_opposite`, dead), 188–189 and 207–209 (COMPLEX), 220 (O4 old-direction BOS), branch 265→270 (ESTABLISHED with no protected) |
| `protected_levels.py` | 93 % | 83 (NO_ORIGIN_SWING note), 94 (`protected()` returning None for min-BOS / consumed), branch 77→81 (an older origin not overriding a newer one) |
| `bos.py` | 96 % | 52 (`latest()` unused), branch 73→70 |
| `swings.py` | 98 % | 133 |

**Audit-only checks** (scratchpad scripts `audit_checks*.py`; not added to the repo):

| Check | Result |
|---|---|
| Fuzz invariants + mirror + exceptions (434 series) | 0 errors, 0 invariant failures, 0 asymmetries; 71 CHoCH, 29 reversals, 363 establishments, **0 COMPLEX** |
| No-look-ahead + parity (72 series × 2 detectors) | 0 failures |
| `ComplexStructureBreak` construction (unreachable type) | constructs without a model error |
| Protected-gap breakdown (400 fuzz series) | 9 645 structured candles, 5 696 (59 %) with no protected swing |
| Same-leg late-lower-origin probe (synthetic) | demonstrates S-1 (§10) |

## 9. Confirmed defects (all low severity, none changes an approved outcome)

| ID | Defect | Evidence | Impact |
|---|---|---|---|
| **D-1** | The `MIXED_STRUCTURE` diagnostic says "CHU05 unresolved" also when a swing **equals** the previous one (EH / EL), which is the equal-level case (FIXTURE_REVIEW C6), not HH + LL | 127 of 255 MIXED diagnostics in the fuzz come from equal prices | Diagnostic text only; the state (UNKNOWN) is correct under A3 |
| **D-2** | An exact-level close at the protected swing (close == level) is logged as `WICK_ONLY` | CHU04 run: low 100, close 101, protected 101 → WICK_ONLY | The label hides that CHU04 (strictness) is unresolved; the outcome follows the strict default |
| **D-3** | Dead code: `_opposite()` in `choch.py` is never called | coverage line 65 | none |
| **D-4** | Fixture naming: `tests/scanner_v6/fixtures/regression/medium_bos.json` (MED01 / MED02) holds **Easy** charts 1 / 2 | reported 21 Nov; rename awaiting approval | Misleading name; the content is verified correct |
| **D-5** | Two staged files fail `git diff --cached --check` (`research/v6/specs/volume1/SYNTHETIC_DATASET_PLAN.md:1326`, `TEST_CASE_CATALOG.md:128`: a new blank line at EOF) | reported at the save-point attempt | Blocks the pending save-point commit; no runtime effect |

## 10. Potential risks and spec gaps

| ID | Risk / gap | Detail |
|---|---|---|
| **S-1** | **D2 origin re-selection is order-dependent** (spec gap) | In one BOS leg, swing low 106 (c16, confirmed c18) is activated when BOS c19 closes above 116. A lower low 104 (c19) in the same leg confirms at c21 and fails A5 (it is below 106). The code **keeps 106**, so c22 (close 105.5) is a CHoCH. The literal reading ("origin = the lowest swing in the leg = 104 → fails A5 → previous protected 101 kept") would give **no CHoCH** at c22. The approved D2 text does not settle which one applies. **Needs an owner decision; not fixed.** |
| **R-1** | **Large protected-gap fraction** | In 400 random walks, 59 % of the candles in BULLISH / BEARISH have no protected swing in force, so no CHoCH is possible. Causes: the last BOS had no confirmed origin swing (2 601 + 143), the origin was not HL / LH (2 106 + 11), no same-direction BOS yet (666), origin pending (169). This follows from approved D2 + A5; behaviour on real data is unknown. |
| R-2 | Parity tests are weak | Batch is a wrapper over the stream (§7) |
| R-3 | O4 diagnostic spam | 280 O4 diagnostics come from only 68 distinct episodes: the diagnostic repeats on every candle while price stays back across the consumed level |
| R-4 | COMPLEX path never exercised end to end | Unreachable under D2. If a future rule adds a second protected level, that path will run for the first time in production-like use. |
| R-5 | "Continuation BOS" in D2 | The code uses the latest same-direction BOS of **any** state (including UNKNOWN) for the initial protected swing (P-B rule 7). Whether a BOS made while UNKNOWN counts as "continuation" is not stated. |
| R-6 | A1 external structure | Every L2/R2 swing counts. On real data, minor swings will drive BOS / CHoCH more often than an "external" model would. |
| R-7 | Float equality | Raw float comparisons, no tick rounding (BOS-006 / C1 open). Exact ties depend on the data's representation. |

## 11. Missing test coverage

1. COMPLEX event path end to end (unreachable today; at minimum a test that injects two competing protected levels into the state machine).
2. Old-direction BOS during TRANSITION → `O4_UNRESOLVED` (`choch.py` line 220).
3. ESTABLISHED with no protected swing in force (branch 265→270), together with "no CHoCH possible until one activates".
4. `ProtectedTracker.protected()` returning None because of `min_bos_index` (a stale origin after a reversal) or `consumed` (line 94).
5. NO_ORIGIN_SWING (line 83). It occurs in pack chart Medium 3 c16, but the pack is not a repo fixture.
6. An older BOS origin activating after a newer one (branch 77→81).
7. The S-1 same-leg late-lower-candidate case (needs the owner decision first).
8. A repeated reversal cycle: BULLISH → CHoCH → BEARISH → CHoCH → BULLISH in one series.
9. Mirror symmetry and random-walk invariants as permanent tests (today they exist only as audit scripts).
10. Real-data no-look-ahead / regression on actual market candles.
11. Exact-level close (CHU04) and equal-swing structure (C6) remain unscored until decided.

## 12. Production-readiness assessment

**NOT READY.** Use is limited to research and synthetic validation.
- **Not wired:** no runner, broker or execution integration (by design; PAPER ONLY).
- **No real-data evaluation:** no backtest, no out-of-sample numbers. Repo rule: strategy changes need a backtest first.
- **Open decisions:** O4, O7, O8, O9, CHU04, CHU05, A1, plus S-1 from this audit.
- **R-1** may make CHoCH rare or late on real data. It needs measurement before any decision.
- **What is ready:** a deterministic, causal, symmetric, test-covered research implementation of the approved swing / BOS / CHoCH rules, suitable as the base for the next research phase (Liquidity Sweep), provided its open items stay open.
