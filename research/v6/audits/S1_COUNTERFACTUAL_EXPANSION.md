# S-1 counterfactual expansion: O3-A vs O3-B (Phase 3.1)

**Prepared:** 22 Nov 2026. Research only.
- **O1 (the official implementation) stays the temporary research baseline.**
- No option is approved or implemented.
- No code, test, spec, fixture file in the repo or Git index was changed. Everything below comes from a counterfactual
  simulator that swaps the protected-swing tracker **in memory** on the unchanged `StructureStream`.

**Builds on:**
- `S1_PROTECTED_RESELECTION_DECISION_ANALYSIS.md` (Phase 3);
- `R1_REAL_MARKET_EVALUATION_REPORT.md` (NSE data, limits apply).

## 1. O3 split into two independent switches

Every origin evaluation in `ProtectedTracker` checks A5 against a **base** swing. O3 changes that base in two different
situations, so it is split into two switches:

| Switch | Applies to | A5 base under O1 (current) | A5 base under the switch |
|---|---|---|---|
| **O3-A** (late-candidate handling, same BOS leg only) | a **late** candidate: a more extreme swing of the **same** leg that confirms after an earlier candidate was already evaluated (the S-1 path; only possible on candle k or k−1) | the swing immediately before it, which is the earlier in-leg candidate, so it always fails | the last same-kind swing at or before the BOS reference (the **pre-leg** swing) |
| **O3-B** (general A5 qualification change) | the **first** evaluation of every leg's origin | the swing immediately before the origin, which may be a higher in-leg swing (no late candidate involved) | the pre-leg swing |

| Option | First evaluation | Late candidate |
|---|---|---|
| O1 (baseline) | immediate | immediate |
| **O3A** | immediate | **pre-leg** |
| **O3B** | **pre-leg** | immediate |
| O3 (= Phase-3 O3) | pre-leg | pre-leg |

**Shared sub-rule** (all options, unchanged from Phase 3, **owner to confirm**): a candidate that fails A5 leaves the
active protected swing unchanged. There is no withdrawal and no fallback.

**Simulator checks** (`S1_artifacts/ab_equivalence.txt`), over 444 series (all fixtures + mirrors + 400 random walks):
- O1 equals the official `analyze_structure` (events, timeline, BOS, diagnostics): **0 mismatches**.
- O3 (A + B) equals the Phase-3 O3 simulator: **0 mismatches**.

## 2. Fixtures (DRAFT / UNSCORED)

**File:** `S1_artifacts/s1_fixtures_v31.draft.json`
- 11 cases × bullish + bearish mirror (p → 200 − p) = **22 fixtures**.
- Each fixture holds the candles (1-based candle numbers and timestamps) and the **counterfactual outcomes** of O1 /
  O3A / O3B / O3.
- The outcomes are labelled `counterfactual_outcomes_not_expectations`. **They are not approved expected results.**

**Checks:**
- Every fixture is causal and batch / stream consistent under the official code (`replay_audit` and
  `no_lookahead_violations` run in the builder).
- **Mirror symmetry:** 11 cases × 4 options, 0 mismatches.

Base for all cases: CHD01 c1–c16 (BULLISH established at c16, protected low 101, swing high 116 at c14).

| Case | Category | What it tests |
|---|---|---|
| SX00 | control | CHD01 as given: no late candidate, no in-leg swing. All options are identical. |
| SX01 | A / **passes** | late low 104 on the BOS candle (k = c19). 104 is HL vs pre-leg 101. c22 closes 105.5, between 104 and 106. |
| SX02 | A / **passes** | the same, with the late low on **k − 1** (c19, BOS c20) |
| SX03 | A / **fails** + **invalidates the original** protected swing | the late low **100 < 101**: its wick takes out the protected swing in force before the BOS (101). The close stays above. c22 closes 102. |
| SX04 | A / passes | as SX01, but c22 closes 103.5, **below the late low** |
| SX05 | A / **original invalidated first** | the activated protected 106 is broken by a close (CHoCH c20, consumed) **before** the late low 104 confirms (c21). Then a bearish BOS c22. |
| SX06 | A / **repeated continuation BOS** | SX01, then a new continuation BOS (c25 over 119) with origin 112; c27 closes 111 |
| SX07 | B / **passes** | one leg with two lows, 106 (c16) then 104 (c20), and no swing high between; BOS c23 over 116. Origin 104 is LL vs the in-leg 106 but HL vs pre-leg 101. c24 closes 103.5. |
| SX08 | B / **fails** + **invalidates the original** | as SX07 with the second low **100 < 101** (its wick takes out the protected 101); c24 closes 103.5 |
| SX09 | B / **repeated continuation BOS** | SX07, then a new continuation BOS (c29 over 119) with origin 111; c31 closes 110.5 |
| SX10 | **A + B in the same leg** | in-leg lows 106 → 104 (B path), plus a late low 103 on the BOS candle (A path); c26 closes 103.8 |

### 2.1 Outcomes (bullish; the mirror is identical after the flip)

"prot" = protected level in force (candle from which it applies).

| Case | O1 (baseline) | O3A | O3B | O3 (A + B) |
|---|---|---|---|---|
| SX00 | CHoCH c18 @101 | same | same | same |
| SX01 | CHoCH c22 @106 | **no CHoCH**; prot 104 from c22 | = O1 | = O3A |
| SX02 | CHoCH c23 @106 | **no CHoCH**; prot 104 | = O1 | = O3A |
| SX03 | CHoCH c22 @106 | = O1 (100 fails vs 101; 106 kept) | = O1 | = O1 |
| SX04 | CHoCH c22 @106 | **CHoCH c22 @104** | = O1 | = O3A |
| SX05 | CHoCH c20 @106; reversal BEARISH c22 | same (104 activates at c21 but the state is already TRANSITION, so no effect) | same | same |
| SX06 | CHoCH c27 @112 | same (prot 104 from c22 until 112 replaces it at c26) | same | same |
| SX07 | no CHoCH (104 `NOT_QUALIFIED`; prot stays 101) | = O1 | **CHoCH c24 @104** (prot 104 from c24) | = O3B |
| SX08 | no CHoCH (prot 101) | = O1 | = O1 (100 fails vs 101) | = O1 |
| SX09 | CHoCH c31 @111 | same | same (prot 104 from c24 until 111 at c31) | same |
| SX10 | no CHoCH (prot 101) | no CHoCH; **prot 103** from c26 | **CHoCH c26 @104** | no CHoCH; prot 104 (c24) → **103** (c26) |

Full details, including every origin evaluation (path, base, A5 verdict, activation):
`S1_artifacts/s1_fixtures_v31_outcomes.csv`.

**Reading the fixtures:**
- O3-A changes outcomes **only** in legs with a late candidate (SX01, 02, 04, 10).
- O3-B changes outcomes **only** in legs whose first-evaluated origin has a higher in-leg swing before it (SX07, 10).
- When the candidate fails even against the pre-leg swing (SX03, SX08: candidates whose wick took out the original
  protected swing), **no option changes anything**. That outcome depends on the shared sub-rule.
- When the activated swing was already consumed before the late candidate confirms (SX05), nothing changes.
- After a further continuation BOS (SX06, SX09), all options converge.
- **SX10 is the only case where the switches interact.** The four options give **four different protected-level
  paths**, and O3 ≠ O3A ≠ O3B:
  - O3B alone gives a CHoCH;
  - O3A alone and O3 do not, at different protected levels.

## 3. Real-data impact, measured separately

Source: `S1_artifacts/s1_ab_pooled.csv` and `s1_ab_by_series.csv`. NSE only: 50 stocks, Yahoo 5m, 60 sessions; 15m /
1h / 1D derived. Counterfactual counts only: **no profitability, predictive or edge claim.**

| ALL 50 | 5m | 15m | 1h* |
|---|---|---|---|
| Eligible BOS legs | 13 347 | 5 044 | 1 469 |
| Late-candidate evaluations (O1) | 342 | 163 | 30 |
| **Legs touched by O3-A** (a late verdict changes) | 120 (**0.90 %**) | 52 (1.03 %) | 13 (0.88 %) |
| **Legs touched by O3-B** (a first verdict changes) | 284 (**2.13 %**) | 114 (2.26 %) | 27 (1.84 %) |
| Legs where O3 changes **both** paths | 7 | 5 | 0 |
| CHoCH: O1 / O3A / O3B / O3 | 2 311 / 2 305 / 2 382 / 2 372 | 835 / 837 / 855 / 853 | 233 / 233 / 239 / 238 |
| CHoCH events changed vs O1: O3A / O3B / O3 | 70 / 199 / 255 | 30 / 68 / 92 | 8 / 8 / 15 |
| Candles whose protected level changes: O3A / O3B / O3 | 1 641 / 7 427 / 8 753 | 987 / 3 145 / 3 891 | 160 / 276 / 391 |
| Unprotected % of BULLISH / BEARISH candles: O1 → O3A / O3B / O3 | 45.17 → 45.05 / 43.43 / 43.42 | 44.02 → 43.73 / 43.09 / 42.81 | 41.56 → 41.38 / 40.64 / 40.38 |
| **Interaction:** candles changed by both A and B | 262 | 241 | 45 |
| **Interaction:** candles where O3 ≠ the single switch that changed them | 87 | 0 | 41 |
| **Interaction:** CHoCH changed by O3 but by neither A nor B alone | 1 | 0 | 0 |

\* 1h: INSUFFICIENT DATA per series; pooled figures are indicative only. 1D (209 legs) is INSUFFICIENT DATA and is in
the CSV only.

**Reading:**
- **O3-B is the larger change.** It affects ~2.1–2.3 % of legs and ~85 % of O3's protected-candle changes, and it is
  the only switch that adds CHoCH (+3.1 % on 5m).
- **O3-A is narrow.** It affects ~0.9–1.0 % of legs (only about a third of the late candidates actually qualify against
  the pre-leg swing). It changes the CHoCH count by < 0.3 %.
- The unprotected share moves by at most ~1.8 pt (5m, O3B). Neither switch materially solves R-1.
- **The effects are almost additive:**
  - Δ(O3) ⊆ Δ(O3A) ∪ Δ(O3B) for CHoCH, apart from one event on 5m.
  - Only 7 + 5 legs have both paths changed.
  - 87 (5m) and 41 (1h) candles carry a combined effect that neither switch produces alone. These are SX10-type legs
    and cascades (a changed CHoCH alters later state and therefore later protected swings).

## 4. Can O3-A and O3-B be implemented independently?

**Yes, technically.**
- They are two separate decisions in one place: the choice of A5 base in `ProtectedTracker.on_close`, keyed on whether
  the leg already has an evaluated candidate (`p.origin is None`).
- Each can be switched on alone, each alone is deterministic and causal (no look-ahead), and each alone passes every
  approved CHD fixture. CHD01–CHD16 match their approved expectations under all four options (Phase 3), and neither
  switch changes SX00.

**But their effects are not fully independent:**
1. **Same-leg interaction (SX10).** When a leg has both a higher in-leg swing *and* a late candidate, the outcome under
   A + B differs from either switch alone (O3A → 103; O3B → 104 + CHoCH; O3 → 104 then 103). On NSE this affects
   7 / 5 / 0 legs (5m / 15m / 1h).
2. **O3-A alone partially overlaps B.** A late candidate is judged against the pre-leg swing even when the leg's first
   candidate was rejected by the in-leg base (SX10 under O3A activates 103). So O3-A also "rescues" some B-type legs,
   but only those with a late candidate.
3. **Cascades.** Any changed CHoCH changes the later state, and with it the protected swings, so candle-level effects
   are not strictly additive (87 candles on 5m).

**Consequences for a decision** (no choice made here):

| If the owner approves… | Then |
|---|---|
| A only | S-1 in the narrow sense is resolved (late candidate judged as an HL of the structure). The current A5 base stays for every first evaluation, so the ~2 % of legs rejected only because of an in-leg swing remain unprotected. |
| B only | First evaluations use the structural HL meaning of A5. S-1 late candidates are still compared with the earlier candidate (so SX01 / 02 / 04 keep the O1 CHoCH at 106). That is an internal inconsistency: the same leg's origin is judged by two different bases. |
| A and B (= Phase-3 O3) | One A5 base everywhere (pre-leg). SX10 needs an explicit expected result, because it is the case where the two switches interact. |
| neither | O1 stays; it should then be approved explicitly and pinned by SX01 / SX02 / SX04 / SX07 as expected results. |

Whichever is chosen, the SX fixtures that the chosen rule decides must get approved expected results first. The shared
sub-rule (fail → keep active) also needs its own decision.

## 5. Artifacts

| Path | Content |
|---|---|
| `S1_artifacts/s1_fixtures_v31.draft.json` | 22 DRAFT fixtures with counterfactual outcomes per option |
| `S1_artifacts/s1_fixtures_v31_outcomes.csv` | the same outcomes, flat: per case × direction × option, CHoCH, reversal, final state, protected changes, origin-evaluation log |
| `S1_artifacts/s1_ab_pooled.csv`, `s1_ab_by_series.csv` | real-data impact of O3A / O3B / O3 (pooled; per series) |
| `S1_artifacts/ab_equivalence.txt` | simulator equivalence checks |
| `S1_artifacts/scripts/s1_ab.py` | the counterfactual tracker (in-memory; not imported by `scanner_v6` or any test) |
| `S1_artifacts/scripts/s1_fixtures_v31.py` | rebuilds the fixtures and outcomes |
| `S1_artifacts/scripts/s1_ab_measure.py` | rebuilds the real-data measurement (uses `R1_artifacts/scripts/r1_eval.py` loaders) |

**Reproduce:**

```bash
export V6_ROOT=/home/claude/v6_wt
S=research/v6/audits/S1_artifacts/scripts   # copy outside the repo if preferred
python3 $S/s1_fixtures_v31.py /tmp/s1_fx
python3 $S/s1_ab_measure.py /mnt/user-data/uploads/trader/trader/research/cache /tmp/s1_ab
```

Re-running both from the in-repo copies reproduced the four output files **byte-identically**.
