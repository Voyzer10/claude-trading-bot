# V6 — Final Structure Sequence Audit (Pre-Module B), 23 Nov 2026

**Audit only.** No code, test, fixture, spec or report in the repository was changed.

## Overall verdict: **PARTIAL**

- **No reproducible defect** was found against the approved rules (D1–D5, BOS-001…005 / Option A, SW-001…005, A2–A8, CHU04 STRICT).
- **Two structural behaviours change the CHoCH → BOS sequence and rest on OPEN spec readings.** They are not defects, but they decide whether some trades exist at all (U1, U2 below).
- **Test coverage of those areas is thin.**
- **The structure layer is therefore not declared "fully correct".**

| Area | Verdict | One-line reason |
|---|---|---|
| 1. CHoCH → BOS reversal | **PASS** | 52 CHoCH all entered TRANSITION; all 31 confirmations come from a later same-direction BOS; 35 same-candle BOS never confirmed; 0 violations |
| 2. Continuation BOS | **PASS** | 138 continuation BOS stay valid with no CHoCH needed (Option A); no state change; setup-level mapping is a spec question (U6) |
| 3. Protected swings | **PARTIAL** | Matches the approved text exactly where the text decides; CHU04 correct both ways; but sticky origin (U1) and "established with no protected" (U2) are OPEN and change events |
| 4. Event ordering | **PASS** | 0 invariant violations, only allowed transitions, timestamps / indices exact, 0 mismatches in 5,371 prefix replays |
| 5. Historical + synthetic regression | **PARTIAL** | 212/212 tests pass and outputs reproduce, but several sequence behaviours have no test (section 8) |

## 1. Method and coverage

**Preflight.** All baselines matched:

| Item | Value |
|---|---|
| Branch | research/v6-smc-scanner |
| HEAD | 7f16f095 |
| Index | e7490c2c616620c0 |
| Staged diff | f724a4ad7956d99c |
| Staged paths | 37 |
| Spec | 835fc013… |
| Status | 8551dac70c90c7d2 |
| Worktree diff | 207c7e9b9c789a3c |

**Corpus: 75 charts, 5,371 candles.**

| Source | Charts |
|---|---|
| Historical NSE 5m segments (hv25) | 25 |
| Difficulty pack (synthetic) | 25 |
| `choch_fixtures` (16 decidable + 6 unscored) | 22 |
| `easy_bos` | 2 |
| `synthetic_5m` (partial series) | 1 |

Totals over the corpus:

| Item | Count |
|---|---|
| BOS | 426 |
| CHoCH | 52 |
| REVERSAL_CONFIRMED | 31 |
| ESTABLISHED | 69 |

**Checks** (tools in the scratchpad, `struct_audit/tools/`; the repo is imported read-only):

1. **Invariants I1–I7 on V6 output:**
   - I1: event index, timestamp and confirmed index;
   - I2: state chain plus the allowed transition set;
   - I3: CHoCH direction, level equal to the pre-candle protected level, strict close, entry into TRANSITION;
   - I4: confirmation only by a later, same-direction BOS on that candle, never on the CHoCH candle;
   - I5: protected level kind, confirmation and state;
   - I6: WICK_ONLY / EXACT_LEVEL_CLOSE only in an established state;
   - I7: one CHoCH per protected id.
   - **Result: 0 violations.**
2. **Independent oracle:**
   - **Scope:** re-implements, from the approved spec text, swings, BOS, the D5 order, the D1 state machine, D2 P-B with A5, and CHU04 strict, then diffs against V6.
   - **Limits:** the same auditor wrote it after reading the code, so it validates "code equals the approved text as I read it". It cannot settle open readings.
   - **Variants:** three P-B variants measure which readings actually matter.
3. **Prefix replay:** `analyze_structure(series.upto(k))` against the full run for every k of every chart: 5,371 replays, **0 mismatches** (no look-ahead, no repaint).
4. **BOS role classification:** every BOS gets exactly one role (section 3).
5. **Minimal hand-built cases:** CHU04 equality in both directions (Appendix B).

**Oracle versus V6:**

| Oracle variant | Swings | BOS | Events | Timeline |
|---|---|---|---|---|
| incremental + sticky (the approved-text reading, PHASE1_2 §4 / CHD16) | 75/75 identical | 75/75 | 75/75 | 0 differing candles |
| incremental, non-sticky (alternative D2/A5 reading, U1) | identical | identical | 1 chart differs (ME03) | 79 candles, 3 charts |
| "final leg" (activate only when the whole BOS leg is confirmed) | identical | identical | 6 differ | 274 candles, 51 charts |

The "final-leg" reading is **ruled out by the approved text**. PHASE1_2 §4 / CHD16 activates L 106 at its own confirmation (c18), one candle before the leg could be complete. Its differences are therefore not a spec dependency; they only show that the comparison is sensitive.

## 2. Area 1 — CHoCH → BOS reversal: **PASS**

**Evidence (all 75 charts):**
- **CHoCH outcomes:** 52 CHoCH; every one moved BULLISH → TRANSITION(bearish) or BEARISH → TRANSITION(bullish) on its own candle (I3).
- **Confirmations:** 31 reversal confirmations. Each is backed by a BOS in the CHoCH direction on that candle, strictly after the CHoCH (I4). CHoCH → confirm gap: minimum 1, median 20, maximum 43 candles.
- **Same-candle BOS:** 35 BOS on a CHoCH candle in the CHoCH direction (12 in `choch_fixtures`, 9 historical, 12 synthetic, 2 `synthetic_5m`). **None confirmed the reversal.** The same-candle BOS also uses up the latest swing reference (BOS-005), so confirmation always needs a newer swing, consistent with D1 / D4 / CHD14.
- **No CHoCH while in TRANSITION** (A8, I6).

**Reference timeline, CHD10 (V6 output, k zero-based):**

| k | close | pre-state | pre-protected | events | state after | protected for k+1 |
|---|---|---|---|---|---|---|
| 15 | 107 | UNKNOWN | – | ESTABLISHED (H 116 confirmed) | BULLISH | 101 |
| 17 | 100 | BULLISH | 101 | **CHoCH bearish vs 101 (low@9)** + **BOS bearish vs 101 on the same candle: does NOT confirm** | TRANSITION(bearish) | – |
| 20 | 100.5 | TRANSITION(bearish) | – | swing L 97 (c18) confirmed | TRANSITION(bearish) | – |
| 23 | 96 | TRANSITION(bearish) | – | **BOS bearish vs 97 → REVERSAL_CONFIRMED** | BEARISH | 103 (origin activated at close 23) |

Two observations are D1-consistent but suspicious for trading. Both are listed as owner questions; neither is a defect.

- **U5 — the confirming BOS may break a swing confirmed before the CHoCH.**
  - **Counts:** 31 confirmations; the reference swing was confirmed before the CHoCH once (HV19), on the CHoCH candle 3 times (HV20, EA02, ME03; usable from the next candle under D5), and after the CHoCH 27 times.
  - **HV19:**

    | k | close | event | pre-state → state | protected |
    |---|---|---|---|---|
    | 50 | 1568.0 | CHoCH bullish vs protected high 1567.5 | BEARISH → TRANSITION(bullish) | — |
    | 51–52 | 1566.9 / 1567.3 | O4_UNRESOLVED (close back below 1567.5) | TRANSITION(bullish) | — |
    | 53 | 1569.9 | BOS bullish vs swing high 1568.10 (c45, confirmed c47, i.e. before the CHoCH) → REVERSAL_CONFIRMED | → BULLISH | none until c54 |

    The "confirmation" is a break of a high 0.60 above the CHoCH level, after two close-backs.
- **U3 / O4 — a reversal can be confirmed after the old trend made a new extreme inside TRANSITION.**
  - **HV04:**

    | k | event | pre-state → state |
    |---|---|---|
    | 60 | bearish BOS vs 10000 (new lower low); O4_UNRESOLVED, no state change | TRANSITION(bullish) |
    | 63 | bullish BOS vs 10040 → REVERSAL_CONFIRMED | → BULLISH, with **no protected low** (origin 9969 is NOT_QUALIFIED, an LL) |

  - **Coverage of open-ended TRANSITION:** 21 of 52 CHoCH are never confirmed before the data ends; 418 O4 diagnostics. TRANSITION has no exit other than a same-direction BOS (O4 OPEN).

## 3. Area 2 — Continuation BOS: **PASS**

Every BOS is classified by its pre-candle state and V6's own state-change events (`audit.py::classify_bos`):

| Role | Historical | Synthetic | Fixtures (`choch` + `easy` + `5m`) | Total |
|---|---|---|---|---|
| CONTINUATION (BOS in the established direction) | 59 | 73 | 6 | **138** |
| REVERSAL_CONFIRMING (first same-direction BOS in TRANSITION) | 7 | 20 | 4 | **31** |
| Same candle as a CHoCH, same direction (does not confirm) | 9 | 12 | 14 | 35 |
| Counter-structure, no CHoCH | 28 | 70 | 3 | 101 |
| Opposite direction during TRANSITION (O4) | 6 | 20 | 1 | 27 |
| Pre-structure (UNKNOWN) | 38 | 30 | 26 | 94 |

- **Continuation BOS:** never needs a CHoCH, never changes the state, and updates the protected level through P-B (example HV09 c34; CHD13 101 → 106).
- **"Counter-structure, no CHoCH" (101):** either no protected level was in force (59; see U2) or the protected level lies beyond the BOS reference, so the close crossed the nearer swing but not the protected one (42; e.g. HV07 c65 bearish BOS vs 559.10 while protected low 550.55; HV16 c45 bullish BOS vs 7552.5 while protected high 7630).
- **U6 (spec, not code):**
  - **Structure layer:** correctly does not require a CHoCH before a BOS.
  - **Setup layer:** CK-17 (delegated, OWNER APPROVED) defines the setup sequence as CHoCH → *the next subsequent same-direction BOS* → sweep. Under CK-17 a continuation BOS cannot start a setup.
  - **Owner check:** if continuation setups are wanted, CK-17 must say so.
  - **Module B note:** `BOSEvent` carries no role label. Module B must derive "reversal-confirming" from `StructureStateChange(cause="REVERSAL_CONFIRMED").related == (bos.id,)`.

## 4. Area 3 — Protected swings: **PARTIAL**

**What is correct (evidence):**
- **P-B origin selection, A5 qualification, activation at the origin's own confirmation, replacement by a later BOS, consumption by CHoCH:** identical to the independent approved-text oracle on all 75 charts, with 0 timeline differences.
- **The D2 timing example (CHD16):** reproduced exactly, with 101 kept through c17 and 106 from c18.
- **CHU04 STRICT (OWNER APPROVED):** correct in both directions (Appendix B, minimal cases E1–E3).
  - Close == protected gives no CHoCH and no BOS (BOS-002 strict too); a neutral EXACT_LEVEL_CLOSE diagnostic is recorded; the protected swing is **not consumed**.
  - A later close strictly beyond gives a CHoCH against the **same** swing id (low@9 / high@9).
  - Two equality closes in a row give no CHoCH.
- **CHU04 coverage:** only the `CHU04` fixture exercises equality in the corpus (1 EXACT_LEVEL_CLOSE); no historical or synthetic chart hits equality.
- **Known stale labels (IR-1, not fixed, needs separate authorisation):** the `choch.py` docstring, the EXACT_LEVEL_CLOSE text ("CHU04 unresolved"), and `test_d2_exact_level_close_is_not_wick_only_and_chu04_stays_open`. Behaviour is correct; the labels are stale.

### U1 — "sticky" origin when the final leg low fails A5 (OPEN: D2 / A5 reading)

**Code behaviour.** `ProtectedTracker.on_close` re-selects a BOS's origin as more leg swings confirm. When the newly lowest swing (bullish case) fails A5, the code keeps the origin it already activated for that BOS.

**Why this always fails A5.** A swing that confirms later has a higher index. If it is lower than an earlier leg swing, it is an LL against that swing, so it always fails A5.

**Two readings:**
- **(a) sticky:** the earlier-activated swing stays protected (V6).
- **(b) non-sticky:** the true D2 origin is "not protected", so the protected level reverts to the one before this BOS (or to none).

**Corpus counts:** 5 occurrences (HV06, HV14, HV15, EX02, ME03). The timeline differs in 3; **the events differ in 1.**

**ME03 (synthetic; candles in Appendix A):**

| k | close | event | pre-state → state | protected for k+1: V6 / non-sticky |
|---|---|---|---|---|
| 96 | 94.22 | bearish BOS vs 94.4458; origin H 95.716 (c92) ACTIVATED | BEARISH | 95.716 / 95.716 |
| 97 | 95.31 | H 96.186 (c95) confirms and becomes the leg's highest swing (the new D2 origin); it is not an LH against 95.716, so NOT_QUALIFIED | BEARISH | **95.716 / 99.3881** |
| 100 | 95.73 | **CHoCH bullish vs 95.716** | BEARISH → TRANSITION(bullish) | — / 99.3881 (no CHoCH: 95.73 < 99.39) |
| 102 | 96.08 | bullish BOS vs 96.081 → **REVERSAL_CONFIRMED** | → BULLISH | — / still BEARISH |

**Effect on trading:** a whole CHoCH → BOS reversal exists only under reading (a).

**HV06 (historical):** BOS c51 activates L 1192.40 (c47). At c52, L 1191.5 (c50) confirms and fails A5. V6 keeps 1192.40 for c52–71; the non-sticky reading gives no protected level. This is exactly the 21 "UNRESOLVED protected-level" checkpoints of the earlier historical validation.

**Owner decision needed:**
- Is (a) sticky or (b) non-sticky intended?
- Should A5 compare a BOS origin with the immediately previous swing (an intra-leg swing) or with the previous structural / protected swing?

### U2 — established structure with NO protected level, so CHoCH is impossible (OPEN: D2 vs A5 gap)

**Code behaviour.** Under D2 the protected swing can only be a qualifying BOS origin. When the established structure (or the reversal-confirming BOS) has no qualifying origin, the state is BULLISH or BEARISH with no protected level. No CHoCH can occur until a later same-direction BOS supplies one.

**Size:** 1,316 established-state candles in 44 of 75 charts. Historical: **432 of 1,043 established candles (41%) in 22 of 25 charts.**

| Cause | Historical | Synthetic | `synthetic_5m` |
|---|---|---|---|
| ESTABLISHED, no qualifying origin yet | 407 | 578 | 0 |
| Reversal-confirming BOS origin NOT_QUALIFIED (A5) | 6 | 114 | 9 |
| Reversal-confirming BOS has NO_ORIGIN_SWING | 11 | 30 | 11 |
| Both of the above | 4 | 24 | 0 |
| Waiting for origin confirmation (R = 2 delay) | 4 | 9 | 2 |
| Other (only opposite-direction activations seen) | 0 | 79 | 28 |

**HV01 (historical):**

| k | close | event | state | protected |
|---|---|---|---|---|
| 30 | 3090.5 | ESTABLISHED by L 3076.0 (c28) confirming (HH + HL) | BULLISH | **none** (L 3076 is not a BOS origin) |
| 42 | 3072.7 | **bearish BOS vs 3076.0**: the close is below the very HL that established the structure, but **no CHoCH** | BULLISH | none |
| 44 | 2972.1 | price falls about 100 points | **still BULLISH** | none |

**Effect on trading:** in these windows the strategy's first stage (CHoCH) can never fire, whatever price does.

**Owner decision needed:** should the HL / LH that establishes the structure (A5 "protected = a qualifying HL / LH"), or the last qualifying protected swing, act as the protected level when no BOS origin qualifies?

### Other OPEN dependencies seen in protected handling

- **O9 (2 cases):**

  | Case | k | Event |
  |---|---|---|
  | EX04 | 18 | established BULLISH while close 99.31 is already below the protected 99.76, with a bearish BOS on the same candle; O9_UNRESOLVED recorded |
  | EX04 | 19 | CHoCH bearish (close 98.22) |
  | CHD15 | — | the fixture's own O9 case; scored only through c16, by design |

- **Lagging protected level (informational):**
  - **HV09:** BOS c34's origin 412.0 is NOT_QUALIFIED (an LL against 412.15), so the protected level stays 409.15 while price trades at 416.
  - **Effect:** CHoCH then needs a much deeper move. This is rule-consistent under D2.

## 5. Area 4 — Event ordering: **PASS**

- **I1:** every event, BOS and swing has `confirmed_index == index` (swings `index + 2`), and its timestamp equals the candle's timestamp.
- **I2:** the state chain is unbroken. Only these transitions occur:
  - UNKNOWN → BULLISH / BEARISH;
  - BULLISH → TRANSITION(bearish) and BEARISH → TRANSITION(bullish);
  - TRANSITION(d) → d.
  - **No impossible or contradictory transition, and no state change without an event.**
- **Prefix replay:** 5,371 replays, 0 mismatches.
- **Batch / stream parity and no-look-ahead:** covered by the suite.
- **Distinguishing continuation from reversal-confirming BOS:** possible and unambiguous from the output (section 3); there are no ties.

**Informational (not defects):**
- The state never returns to UNKNOWN once established. COMPLEX_STRUCTURE_BREAK is unreachable with one protected level per direction (O5 guard).
- BOS events (BOS stream) and CHoCH / state events (structure stream) on the same candle have no explicit intra-candle sequence field. The D5 order (BOS → CHoCH → state → swings) is implicit, so Module B must not re-order by list position.

## 6. Area 5 — Regression: **PARTIAL**

- **Suite:** `PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/scanner_v6` gives **212 passed** (read-only run during this audit).
- **Reproducibility:**
  - all 16 decidable CHoCH fixtures match their approved expectations (`test_all_decidable_fixtures_under_the_approved_rules`);
  - the historical output is byte-identical to the frozen hv25 output (`a6d0d856…`, verified in the previous task).
- **No expected output was modified.**

## 7. Reproduced defects

**None against the approved rules.** Every behaviour that looks suspicious traces to an OPEN item. The table gives a reproducible case for each, so the owner can rule.

| # | Behaviour | Reproducible case | Depends on |
|---|---|---|---|
| S-1 | Sticky origin after an A5 failure | ME03 c96–102 (events change); HV06 c51–71 | U1: D2 / A5 reading |
| S-2 | Established, or newly reversed, with no protected level; CHoCH impossible | HV01 c30–44; HV04 c63+ | U2: D2 vs A5 gap; O9 |
| S-3 | Reversal confirmed after the old trend's new extreme inside TRANSITION | HV04 c60–63 | O4 |
| S-4 | Confirmation by breaking a swing confirmed before the CHoCH | HV19 c45–53 | U5: D1 / CK-17 wording |
| S-5 | CHoCH one candle after establishment because the break predates it | EX04 c18–19 | O9 |
| S-6 | TRANSITION open until the data ends (21 of 52 CHoCH) | HV05 c53–72 | O4 |

## 8. Coverage gaps (no test pins these behaviours today)

1. Sticky origin re-selection (U1). No test; observed only in the corpus.
2. Established structure with no protected level, and a counter BOS without CHoCH (U2).
3. CHU04: equality followed by a strict close against the same protected id (Appendix B E1 / E2). The existing test checks only the single equality candle, and asserts the stale "CHU04 unresolved" label.
4. Opposite BOS during TRANSITION followed by a confirmation (S-3), and a confirming BOS on a pre-CHoCH swing (S-4).
5. Continuation BOS: protected replacement in a long trend is covered only by CHD13 / CHD16 (one replacement each).
6. Equality at BOS or CHoCH level in real data: never exercised. Real-data unresolved regions are large (from the earlier validation: 832 of 1,821 checkpoints not graded).

## 9. Exact files and functions involved (all inspected, none modified)

| File | Functions |
|---|---|
| `scanner_v6/structure/choch.py` | `StructureStream.on_candle` (D5 steps; CHoCH test `beyond` / `at_level` / `wick`; TRANSITION confirmation; O4 diagnostics); `_establish` (A2–A4, MIXED / EQUAL, O9); `protected_in_force`; `analyze_structure` / `detect_structure` |
| `scanner_v6/structure/protected_levels.py` | `ProtectedTracker.on_bos` / `on_close` (P-B origin, A5 check, activation, re-selection: **U1**); `protected` (min_bos_index / consumed filter: **U2**) |
| `scanner_v6/structure/bos.py` | `BOSStream.on_candle` (D4 latest reference, BOS-002 strict, BOS-005, D5) |
| `scanner_v6/structure/swings.py` | `_check`, `_evaluate`, `SwingStream.on_candle` (SW-001…005) |
| `scanner_v6/engine.py` | `no_lookahead_violations`, `replay_audit` (harness) |

These are among the 37 protected staged files and were only read.

## 10. Unresolved specification dependencies (summary)

| ID | Item | Impact on CHoCH → BOS |
|---|---|---|
| U1 | D2 / A5 sticky vs non-sticky origin; A5 comparator (intra-leg vs structural previous swing) | Changes protected levels in 3 charts and a full reversal in 1 |
| U2 | Protected level when no BOS origin qualifies (D2 vs A5 "qualifying HL / LH") | 41% of established historical candles cannot produce a CHoCH |
| U3 / O4 | Failed CHoCH; opposite BOS in TRANSITION; TRANSITION exit | 21 of 52 CHoCH never resolve; reversal after a new extreme |
| O9 | Initial chronology | CHoCH right after establishment (EX04) |
| U5 | Must the confirming BOS reference a post-CHoCH swing? | Weak confirmations like HV19 |
| U6 | CK-17: may a continuation BOS start a setup? | Whether continuation trades exist at all |
| O5 | State after COMPLEX (unreachable today) | none now |
| A1 | "External" structure undefined (all L2/R2 swings count) | All structure decisions |
| CHU05 / C6 | Mixed / equal swing classification keeps UNKNOWN | Delays establishment (21 MIXED, 1 EQUAL diagnostics) |
| IR-1 | Stale CHU04 labels (behaviour correct) | Documentation / test name only |

## 11. Postflight

| Check | Result |
|---|---|
| Branch / HEAD | unchanged |
| Index | e7490c2c616620c0 (unchanged) |
| Staged diff | f724a4ad7956d99c (unchanged) |
| Staged paths | 37, identical list |
| Spec | unchanged |
| Status | 8551dac70c90c7d2 (identical) |
| Worktree diff | 207c7e9b9c789a3c (unchanged) |
| Tracked-changed, untracked and staged files | all 177 unchanged |
| Protected files | OK |
| New repo files / `.pyc` | 0 / 0 |
| Stash / commits / push / deploy | none |
| V4 / production | untouched |
| Scope | PAPER ONLY; Module B not started |

Stopping here for owner review.
