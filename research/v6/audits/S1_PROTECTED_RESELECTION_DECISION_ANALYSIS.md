# S-1 protected-swing re-selection: decision analysis

**Prepared:** 22 Nov 2026, Phase 3. Research only. **No option was selected or implemented. The decision stays with the
owner.**

**Inputs:**
- `S1_PROTECTED_RESELECTION_ANALYSIS.md` (the four options);
- `research/v6/specs/choch_v0_9/PHASE1_2_DECISIONS.md` (D2 P-B, A5);
- `scanner_v6/structure/protected_levels.py` and `choch.py` (unchanged);
- the CHD / CHU fixtures and `tests/scanner_v6/test_choch.py`.

**Evidence:**
- A counterfactual simulator (`R1_artifacts/scripts/s1_options.py`). It swaps the tracker object **in memory** on an
  unmodified `StructureStream`.
- O1 in the simulator reproduces the official implementation exactly on 444 series: every fixture and its mirror, plus
  400 random walks. Events, timeline, BOS and diagnostics all match, with 0 mismatches.
- Real-market frequencies come from the R-1 run (`R1_REAL_MARKET_EVALUATION_REPORT.md`, NSE only).

## 1. Current behaviour reproduced

Input: CHD01 c1–c16 plus c17–c22 (`R1_artifacts/s1/s1_variants.txt`, variant V1).

| c | Event (official code) | Protected in force after the close |
|---|---|---|
| 12 | BOS bullish over 109; origin 101 (HL vs 98) | – |
| 16 | ESTABLISHED BULLISH | 101 |
| 18 | swing low 106 (c16) confirms | 101 |
| 19 | BOS bullish over 116 (close 116.5, **low 104**). Origin = 106, HL vs 101 → `ACTIVATED` | **106** (from c20) |
| 20 | low 104.5 < 106, close 117 → `WICK_ONLY` | 106 |
| 21 | swing low **104 (c19)** confirms. It is the new lowest candidate of the leg. Its A5 base is the swing immediately before it = **106**, and 104 < 106 → `NOT_QUALIFIED` | **106 kept** |
| 22 | close 105.5 < 106 → **CHoCH bearish @106**, TRANSITION(bearish) | – |

The mirror (p → 200 − p) gives the same events at 94 (BEARISH → CHoCH bullish).

**Structural facts from the code** (they bound every option):
- A BOS's origin search stays open until `k + R` (R = 2). Every swing in `(ref, k]` is confirmed by then, so no
  candidate is ever missed.
- A **late** candidate, one that confirms after an earlier candidate was already evaluated, can only sit on candle
  **k** (the BOS candle) or **k − 1**. Any earlier swing is already confirmed at k.
- Under the current A5 base, a later lower low in the same leg is compared with the **earlier candidate itself**. It is
  therefore always "not HL" and can never replace it. S-1 is not an edge case of the code: it is what the A5 base does.

## 2. The four options

The options are the ones already listed in `S1_PROTECTED_RESELECTION_ANALYSIS.md` §5. One sub-rule needed for
simulation is labelled **[sub-rule, owner to confirm]**. No other option is proposed.

Synthetic variants used below (bullish; every one was also run mirrored, with identical results):

| Variant | What changes vs V1 |
|---|---|
| **V1** | the late low 104 is on the BOS candle; c22 closes 105.5, between 104 and 106 |
| **V2** | the late low 104 is on k − 1 (c19); BOS on c20; c23 closes 105.5 |
| **V3** | the late low is **100, below the pre-leg low 101**; c22 closes 102 |
| **V4** | V1, then a new continuation BOS (c25 over 119) with origin 112; c27 closes 111 |
| **V6** | V1, but c22 closes 103.5, below the late low 104 |

(V5 duplicated V1 and was dropped.)

### Option 1: CURRENT (keep the active swing)

1. **Rule.**
   - Origin = the most extreme confirmed opposite swing in `(ref.index, k]`.
   - A5 base = the same-kind swing immediately before the candidate.
   - A candidate that fails A5 is recorded `NOT_QUALIFIED` and the active protected swing is kept.
2. **Lifecycle (V1).** 101 → (c19) 106 → c21: 104 `NOT_QUALIFIED`, 106 kept → c22 CHoCH @106.
3. **Does 106 remain protected?** Yes.
4. **Can 104 replace it?** Never inside the same leg: its A5 base is 106 itself.
5. **Must 104 qualify as HL / LH?** Yes, but against 106, which it cannot pass.
6. **Is the original origin authoritative?** The *first* candidate to activate is authoritative, not the leg's real
   extreme.
7. **Effect on CHoCH:**
   - Bullish: CHoCH at 106 in V1, V2, V3, V6 (and the bearish mirror at 94).
   - The CHoCH can fire while price is still **above** the leg's real low (104).
8. **Repeated continuation BOS (V4).** The next qualified BOS origin (112) replaces 106 normally. The divergence lasts
   only until the next continuation BOS.
9. **Risks.**
   - **False positive:** a CHoCH on a close between the leg low and the earlier candidate (V1 / V2: 105.5 above 104).
   - False negative: none specific.
10. **Tests needed if approved:**
    - V1, V2, V3, V6 (both directions) as approved fixtures;
    - a test that the late candidate is logged `NOT_QUALIFIED`;
    - V4 to confirm convergence.

### Option 2: L-a (the final origin is authoritative; withdraw if it fails A5)

1. **Rule.**
   - Origin = the leg's final extreme. A5 is checked with the same base as Option 1.
   - If a later candidate replaces the activated one and fails A5, the activation made by **this** BOS is **withdrawn**.
   - The protected swing in force before that activation is restored (in the example, 101).
2. **Lifecycle (V1).** 101 → (c19) 106 → c21: 104 fails A5 → `WITHDRAWN`, back to **101** → c22 105.5 > 101: no CHoCH;
   still BULLISH.
3. **Does 106 remain protected?** No. It is withdrawn at c21, in force from c22.
4. **Can 104 replace it?** No. 104 fails A5 under the same base.
5. **Must 104 qualify?** Yes; it fails, which triggers the withdrawal.
6. **Is the original origin authoritative?** The final leg extreme is authoritative, but only to *disqualify*. The
   result is an *older* level.
7. **Effect on CHoCH:**
   - V1, V2, V3, V6: no CHoCH, in both directions.
   - The protected level moves **away** from price (106 → 101).
8. **Repeated continuation BOS (V4).** It converges at the next BOS (112), the same as every option.
9. **Risks.**
   - **False negative:** V6 closes 103.5, below the leg's own low 104, with no CHoCH. A bearish BOS fires on that
     candle, but the structure stays BULLISH.
   - **Revision risk:** a level that was in force is withdrawn and replaced by an older one. This is not repainting
     (past events are unchanged), but the current protection is retroactively weakened.
10. **Tests needed if approved:**
    - V1 / V2 / V3 / V6 with no CHoCH and protected 101 from k + 1;
    - a `WITHDRAWN` diagnostic test;
    - a nested case: the withdrawn activation's predecessor was itself consumed, so the result is no protection;
    - parity and no-look-ahead.

### Option 3: REPLACE (A5 judged against the swing before the leg)

1. **Rule.**
   - Origin = the leg's extreme.
   - The A5 base for every candidate of the leg = the last same-kind swing **at or before the BOS reference**, i.e. the
     swing before the leg (101).
   - A later, more extreme candidate that qualifies **replaces** the active one at its confirmation.
   - **[sub-rule, owner to confirm]:** a later candidate that does *not* qualify against the pre-leg swing leaves the
     active one unchanged. (V3: 100 < 101, so 106 is kept.) The alternative, withdrawal, would be Option 2 for that
     sub-case.
2. **Lifecycle (V1).** 101 → (c19) 106 → c21: 104 is HL vs 101 → `ACTIVATED`, **104** in force from c22 → c22 105.5 >
   104: no CHoCH. V6 (close 103.5): CHoCH @104.
3. **Does 106 remain protected?** No. It is replaced by 104 at 104's confirmation.
4. **Can 104 replace it?** Yes, if 104 is HL vs the pre-leg low (101).
5. **Must 104 qualify?** Yes, against 101, not against 106.
6. **Is the original origin authoritative?** The leg's real extreme is authoritative, subject to A5 against the
   pre-leg swing.
7. **Effect on CHoCH:**
   - V1 / V2: none (105.5 > 104).
   - V6: CHoCH @104.
   - V3: CHoCH @106 (sub-rule).
   - The protected level moves to the real leg low, at most R candles after activation.
8. **Repeated continuation BOS (V4).** It converges at the next BOS (112).
9. **Risks.**
   - The protected level can move *down* (looser) once per leg, within R = 2 candles.
   - A CHoCH between 104 and 106 is no longer reported (V1). If 106 was the "true" level, that is a false negative.
   - The A5 base change also affects legs that are **not** S-1: legs with another same-kind swing between the reference
     and the origin (see §4). That is a wider change than S-1.
10. **Tests needed if approved:**
    - V1 / V2 (no CHoCH, protected 104);
    - V6 (CHoCH @104);
    - V3 (sub-rule as approved);
    - a multi-low leg where the current code says `NOT_QUALIFIED` but O3 activates;
    - mirror, parity, no-look-ahead;
    - the existing CHD01–CHD16. Checked in the simulator: they match their approved expectations under **all four** options (`R1_artifacts/s1/chd_under_options.txt`), so none of the approved fixtures discriminates between the options.

### Option 4: EXCLUDE the BOS candle from origin candidates

1. **Rule.** Origin candidates are the swings in `(ref.index, k)`: the BOS candle's own extreme is excluded. Everything
   else as in Option 1.
2. **Lifecycle.**
   - V1: 104 (on the BOS candle c19) is ignored → 106 stays → CHoCH @106 at c22, as in Option 1.
   - V2: 104 is on k − 1, so it is still a candidate → same as Option 1. **S-1 is not removed.**
3. **Does 106 remain protected?** Yes.
4. **Can 104 replace it?** Not when 104 is on the BOS candle; otherwise the same as Option 1.
5. **Must it qualify?** As in Option 1.
6. **Is the original origin authoritative?** The first activation is authoritative; the BOS-candle extreme never
   counts.
7. **Effect on CHoCH:** the same as Option 1 in every variant.
8. **Repeated continuation BOS (V4).** It converges.
9. **Risks.**
   - It does not fix S-1 (V2).
   - It changes origin selection for every leg whose extreme is on the BOS candle, which is ~5 % of real legs and
     unrelated to S-1.
   - It can create more `NO_ORIGIN_SWING`, so more unprotected candles.
   - No basis in the D2 text.
10. **Tests needed if approved:**
    - V1 (104 ignored);
    - V2 (S-1 remains);
    - a leg whose only candidate is on the BOS candle (→ `NO_ORIGIN_SWING`);
    - mirror, parity, no-look-ahead.

## 3. Synthetic results: all variants × options (bullish; the mirror is identical)

| Variant | O1 CURRENT | O2 L-a | O3 REPLACE | O4 EXCL-K |
|---|---|---|---|---|
| V1 late low on k, close 105.5 | CHoCH c22 @106 | none (prot 101) | none (prot 104) | CHoCH c22 @106 |
| V2 late low on k−1, close 105.5 | CHoCH c23 @106 | none (prot 101) | none (prot 104) | CHoCH c23 @106 |
| V3 late low 100 < 101, close 102 | CHoCH c22 @106 | none (prot 101) | CHoCH c22 @106 *(sub-rule)* | CHoCH c22 @106 |
| V4 + next continuation BOS | CHoCH c27 @112 | CHoCH c27 @112 | CHoCH c27 @112 | CHoCH c27 @112 |
| V6 close 103.5 < 104 | CHoCH c22 @106 | none (prot 101) | CHoCH c22 @104 | CHoCH c22 @106 |

Full output: `R1_artifacts/s1/s1_synthetic_variants.csv` and `s1_variants.txt`.

## 4. Real-market evidence (NSE only: 50 stocks, Yahoo 5m, 60 sessions; see the R-1 report for limits)

| | 5m | 15m | 1h* |
|---|---|---|---|
| Eligible BOS legs (origin evaluated) | 13 347 | 5 044 | 1 469 |
| Legs with an S-1 re-selection | 342 (**2.56 %**) | 163 (**3.23 %**) | 30 (2.04 %) |
| … of which the classic case (active kept, late one fails A5) | 186 (1.39 %) | 89 (1.76 %) | 17 |
| Bullish / bearish S-1 legs | 148 / 194 | 70 / 93 | 15 / 15 |
| Legs with another same-kind swing between the reference and the origin | 1 074 (8.0 %) | 454 (9.0 %) | 89 (6.1 %) |
| … rejected by the current A5 base but HL / LH vs the pre-leg swing | 394 (2.95 %) | 160 (3.17 %) | 40 (2.72 %) |
| Legs whose origin is on the BOS candle (affected by O4) | 701 (5.3 %) | 258 (5.1 %) | 145 (9.9 %) |
| CHoCH, official (O1) | 2 311 | 835 | 233 |
| CHoCH under O2 / O3 / O4 (counterfactual) | 2 269 / 2 372 / 2 231 | 820 / 853 / 794 | 229 / 238 / 215 |
| CHoCH events changed vs O1 (set difference) O2 / O3 / O4 | 110 / 255 / 256 | 49 / 92 / 95 | 12 / 15 / 36 |
| Candles whose protected level differs vs O1, O2 / O3 / O4 | 4 351 / 8 753 / 9 569 | 1 852 / 3 891 / 3 446 | 582 / 391 / 1 374 |

\* 1h: every single series is below the reliability threshold; pooled figures only.

**Reading:**
- S-1 itself is **rare**: about 2–3 % of BOS legs.
- The **wider** effect of O3 and O4 comes from changing origin / A5 behaviour on legs that are *not* S-1:
  - O3 changes the A5 base, which affects ~3 % more legs;
  - O4 changes the candidate window, which affects ~5 % of legs.
- O2 is the most contained change, but it removes CHoCH.
- No option changes CHoCH counts by more than ±4 %.
- **This is counterfactual counting only.** It says nothing about which option is *right* or more profitable, and no
  profitability, predictive-power or edge claim is made.

## 5. Decision matrix

| Criterion | O1 CURRENT | O2 L-a | O3 REPLACE | O4 EXCL-K |
|---|---|---|---|---|
| Consistency with approved D2 ("the BOS-origin swing … only after its own confirmation; previous kept until then") | Partial: "origin" = first activated, not the leg's extreme | Partial: uses the leg's extreme but *falls back* to an older level, which D2 does not describe | **Good:** the leg's real extreme becomes protected at its own confirmation; the previous one is kept until then (exactly D2's wording) | Weak: excluding the BOS candle is not in D2 |
| Consistency with A5 (origin must be an HL / LH) | Literal, but the base is the in-leg earlier candidate (an artefact of "swing immediately before") | Same as O1 | Base = the swing before the leg; matches the usual HL meaning (higher than the *previous structural* low). Changes A5 for ~3 % of non-S-1 legs too. | Same as O1 |
| Market-structure interpretation | Protected sits **above** a lower low already printed in the leg; a CHoCH can fire above the leg low (V1 / V2) | Protected falls back to an older, farther low; misses a close below the leg's own low (V6) | Protected = the low that actually produced the break (the common SMC reading) | Arbitrary; S-1 remains on k−1 |
| Determinism | Yes | Yes | Yes | Yes |
| No-look-ahead safety | Yes | Yes: the withdrawal acts from k+1 after the confirmation; no past event changes | Yes: replacement at the candidate's own L2/R2 confirmation | Yes |
| Implementation complexity | none (current) | Medium: per-BOS snapshot / restore; nested consumed cases | Low–medium: change the A5 base + allow replacement; one sub-rule to decide | Low: one window bound |
| CHoCH frequency (NSE 5m, counterfactual) | baseline 2 311 | −1.8 % | +2.6 % | −3.5 % |
| Fixes S-1 in all variants | n/a | yes (by withdrawal) | yes (V3 depends on the sub-rule) | **no** (V2) |
| Side effects outside S-1 | – | small (4 351 candle-levels) | moderate (8 753; the A5-base change) | largest (9 569; origin-window change) |

## 6. Recommendation (not a selection)

**Recommended: Option 3 (REPLACE vs the pre-leg swing), with the sub-rule "a late candidate that fails A5 against the
pre-leg swing leaves the active protected swing unchanged".** The final decision is the owner's.

**Reasons:**
1. It is the only option that makes the protected swing **the swing that actually originated the break** while keeping
   D2's activation rule exactly ("only after its own L2/R2 confirmation; previous kept until then"). No level is
   withdrawn to an older one, and there is no fallback invention.
2. It removes the measured false-positive pattern of O1, a CHoCH while price is still above the leg's real low (V1 /
   V2), without the O2 false negative (V6: a close below the leg low and no CHoCH).
3. It is deterministic and causal. The replacement happens at a confirmation candle, the same mechanism D2 already
   uses.
4. Real-data impact is bounded:
   - S-1 occurs in ~2.6–3.2 % of legs;
   - the CHoCH count changes by +2.6 % on 5m.

**Caveats the owner should weigh:**
- O3 also **changes A5 for legs that are not S-1**: ~3 % of legs that the current code rejects become protected. That
  is a second decision hidden inside S-1. If the owner wants S-1 fixed *without* touching A5 elsewhere, a narrower form
  is needed (pre-leg base only when the in-leg base is an earlier candidate of the same leg). That would be a **new
  proposal**, not one of the four options, and it has not been simulated.
- The protected level can move to a looser level once per leg, within R = 2 candles of activation.
- If the owner prefers stability over fidelity, **O1 (status quo)** is defensible: S-1 is rare and the divergence ends
  at the next continuation BOS (V4). It would then need to be approved explicitly and pinned by tests.
- O4 is **not recommended**: it does not fix S-1 (V2) and changes more unrelated legs than any other option.
- Evidence comes from **NSE equities only** (60 sessions). Crypto and US were unavailable (see R-1).

**Nothing has been implemented.** The fixtures V1–V6 are ready to become approved test cases once the owner decides.
