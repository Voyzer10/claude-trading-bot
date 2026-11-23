# V6 Module B fix + visual blind chart test (23–24 Nov 2026)

V6 PAPER ONLY. Nothing was committed, pushed, merged or deployed. V4 and production were not touched, and no broker was used.
All numbers below come from captured outputs in `05_COMPARISON_REPORTS/test_logs/` and the metric CSVs.

## 1. Actual test results

### Phase 1: D5 terminator order in `scanner_v6/liquidity/setup_sweep.py`

**Canonical order.** PHASE1_2_DECISIONS D5 fixes the order of work at each close:
1. BOS evaluation
2. CHoCH evaluation
3. state update
4. swing confirmation

`StructureStream.on_candle` implements exactly this order.

**Defect.** When the opposite CHoCH and the opposite BOS were on the same candle, the terminating event was picked by
concatenating the list with the CHoCH first. In SR3+AFTER k28 (and its mirror), that made `closed_by` / `ended_by` the
CHoCH id.

**Fix.** A new function `terminating_events()` returns the opposite BOS first (in BOS-stream order), then the opposite
CHoCH. The first one becomes `closed_by` / `ended_by` and is the event named in the `BOS_ELIGIBILITY_ENDED` diagnostic.
- Which events end eligibility is unchanged (MB-3).
- One pending candidate per BOS and all other lifecycle invariants are kept.
- Spec 17.S gets one implementation note on the tie order; no rule was changed.

**New tests** (all mirrored BUY/SELL):

| Test | What it checks |
|---|---|
| `test_same_candle_opposite_bos_and_choch_terminator_follows_d5_mirrored` | BOS id wins the tie; candidate INVALIDATED at k28; ended_by; diagnostic; no pending left |
| `test_terminating_events_order_is_d5_regardless_of_input_order` | CHoCH listed first in the input still yields BOS first; CHoCH alone; BOS alone; same direction gives nothing |
| `test_terminator_alone_cases_and_continuation_exact_ids_mirrored` | opposite CHoCH alone at k28; opposite BOS alone at k30; continuation BOS at k25 keeps eligibility, with exact ids |

**Mutation check.** Putting the old CHoCH-first order back makes 2 tests fail. With the fix restored, all pass.

**Patch.** `05_COMPARISON_REPORTS/V6_ModuleB_D5_terminator_2026-11-23.patch` covers `setup_sweep.py`, `test_liquidity.py`
and the spec.

| Check | Result |
|---|---|
| Focused Module B (`test_liquidity.py`) | **43 passed** (40 before + 3 new) |
| Full V6 pytest suite | **276 passed**, 0 skipped |
| Script mode (14 files) | **276 ok**, every file "all passed" |
| 75-chart corpus dump vs pre-change Module B output | 0 differences in pools, events, groups, candidates, diagnostics, snapshots, structure, BOS, roles |
| Liquidity oracle (75 charts) | events 75/75, groups 75/75 |
| SR-extended structure oracle vs V6 (75 corpus + 16 new charts) | 0 mismatches in events, per-candle timeline, BOS roles |
| Prefix replay / no-look-ahead (corpus) | lookahead 0, replay findings 0 in all 5 sets |
| Historical 25 charts (`run_v6.py`) | raw sha256 `b5df10bc…7123` unchanged; integrity reports and scanner events identical; forbidden_opened [] |
| Deterministic regeneration | OHLC CSV 16/16, scenarios.json and PNG 16/16 byte-identical |
| Originals not overwritten | master charts and all 3 agent input copies identical to the generated hashes |
| Git | index byte-identical to the preflight copy; 37 staged entries identical; staged diff `f724a4ad7956d99c`; `status -uall` identical; HEAD `7f16f095…`; remote unchanged (main `22039ec`, no v6 branch) |
| V4 / production | 0 tracked non-V6 working-tree changes; `/opt/trader` not present here; liquidity detector files SHA-identical |

**Why the corpus output is identical.** All 8 corpus invalidations happen on candles that have an opposite BOS **without**
a CHoCH, so the tie never occurs in the corpus. It occurs only in the test scenario SR3+AFTER k28.

### Phase 2: dataset

- 16 charts: 4 tiers × 2 scenarios × (A + exact mirror B, where B = 200 − price).
- 78–122 candles each.
- Each chart has a fixed seed (`random.Random`), waypoint legs and engineered candles (outside, equal high/low, aimed
  sweeps). See `06_MANIFESTS_AND_SEEDS/`.
- PNGs are 1800×900 with an index axis and a price axis. They carry no labels or overlays. Chart ids are shuffled
  neutrally within each tier.

Feature coverage over the set, measured by V6 (`feature_coverage_v6.json`):

| Feature | Count |
|---|---|
| Swings | 140 H + 140 L |
| BOS | 96 (48 bullish + 48 bearish) |
| CHoCH | 24 |
| ESTABLISHED | 16 |
| REVERSAL_CONFIRMED | 12 |
| REVERSAL_INVALIDATED (SR-5) | 6 |
| BSL / SSL pools | 140 / 140 |
| SWEEP | 66 + 66 |
| REPEAT_SWEEP | 39 + 39 |
| TAKEN | 89 + 89 |
| ACTIVE → SWEPT → TAKEN pools | 106 |
| Multi-pool sweep groups | 10 |
| BSL and SSL group on the same candle | present |
| Same-candle BOS + CHoCH | 10 |
| Sweep on the BOS candle | 18 |
| Equal-level extremes | 38 zones |
| Setup candidates (all INVALIDATED) | 4 |
| Mirror symmetry (bull = bear for every feature) | exact |

### Phase 3: sealed ground truth

**How it was built.** Ground truth (GT) was computed by **independent spec-text oracles** that never import
`scanner_v6`:
- `oracle2.py`: D1–D5, A2–A8, SW, BOS-001..005, SR-1…SR-6;
- a liquidity oracle written from the register text (LQ/LS/G/OQ-4);
- a CK-17 / OQ-5 / MB-1..4 / D5 setup-link oracle.

Each event carries: type, direction or side, candle index, level, id, related swing or pool id, confirmation candle,
lifecycle or state, and BOS role.

| Item | Count |
|---|---|
| GT events | 1220 |
| GT setup candidates | 4 |
| GT timeline rows | one per candle |

**Sealing.**
1. Commitment hashes of every sealed file were written to `SEAL_COMMITMENT.sha256`
   (sha `d209694e…`).
2. GT, OHLC, generator and coverage were encrypted with AES-256 and the plaintext was deleted before any agent started.
3. After the agents finished, the material was unsealed. `sha256sum -c` passed against the commitment.

### Phase 5: bot vs sealed GT

The bot is V6 running on the OHLC CSVs. It does not process images.

| Comparison | Result |
|---|---|
| Field-level, every event | **1220/1220 identical** |
| Setup candidates | 16/16 charts identical |
| Per-candle structure timeline | 16/16 charts identical |
| Visual event types, tolerance 0 | P = R = F1 = 1.000, exact-index accuracy 1.000, level error 0.000, in every tier |
| Prefix replay on the 16 charts | 0 mismatches |
| Stream/batch parity | true |

This is an agreement between two independent implementations of the approved rules. It does not prove the rules are
"right" (see the limitations section).

## 2. Agent annotation results

There were three isolated agents. Each saw only its own copy of the 16 PNGs and the annotator README.

| Agent | Method | Charts | Events |
|---|---|---|---|
| AGENT_1 | visual only (enlarged crops) | 16/16 | 703 |
| AGENT_2 | visual only, reverse tier order, right-to-left scan | 16/16 | 618 |
| AGENT_3 | pixel analysis (own PIL/numpy + OCR calibration; about ±0.01 price) | 16/16 | 600 |

JSON parse errors: 0, 0, 0. All marked PNGs are separate copies; the originals were verified unchanged.

**Matching rule:** same chart and type (and direction), candle index within ±1, one-to-one. Exact-index accuracy counts
the matches with an index difference of 0.

Agents vs GT, all tiers:

| Type | AGENT_1 F1 | AGENT_2 F1 | AGENT_3 F1 | Adjudicated (≥2/3) F1 |
|---|---|---|---|---|
| BOS | 0.785 (R 0.65) | 0.957 | 0.923 | 0.915 |
| CHoCH | 0.500 | 0.667 | 0.741 | 0.692 |
| POOL_BSL | 0.986 | 1.000 | 1.000 | 1.000 |
| POOL_SSL | 0.974 | 0.989 | 1.000 | 0.993 |
| SWEEP_BSL | 0.908 | 0.825 | 0.819 | 0.874 |
| SWEEP_SSL | 0.887 | 0.823 | 0.819 | 0.844 |
| TAKEN_BSL (optional) | 0.930 | 0.824 | 0.673 | 0.905 |
| TAKEN_SSL (optional) | 0.922 | 0.887 | 0.673 | 0.930 |
| **All types** | **0.907** (P 0.934, R 0.882) | **0.914** (P 0.980, R 0.857) | **0.885** (P 0.973, R 0.812) | **0.928** (P 0.978, R 0.884) |

By tier, all types:

| Tier | AGENT_1 F1 | AGENT_2 F1 | AGENT_3 F1 | Adjudicated F1 |
|---|---|---|---|---|
| EASY | 0.952 | 0.939 | 0.898 | 0.960 |
| MEDIUM | 0.936 | 0.965 | 0.921 | 0.978 |
| HARD | 0.842 | 0.884 | 0.867 | 0.896 |
| EXTREME | 0.911 | 0.886 | 0.867 | 0.898 |

- Exact-index accuracy on matched events: 0.979, 0.995 and 0.983 for the three agents.
- Mean level error: 0.011, 0.006 and 0.004 in price, which is 0.14 %, 0.08 % and 0.04 % of each chart's range.
- Pairwise agent agreement (overall F1): A1~A2 0.851, A1~A3 0.832, A2~A3 0.888.
- Full tables by tier × type, including precision, recall, FP, FN, unscored and level error, are in
  `05_COMPARISON_REPORTS/AGENT_n_vs_gt_metrics.csv`. Every FP, FN and offset is in `*_details.csv`.

**Bot vs adjudicated visual annotations (≥2/3 agents):**

| Measure | Value |
|---|---|
| P | 0.884 |
| R | 0.963 |
| F1 | 0.921 |
| Exact-index accuracy | 0.990 |

| Type | F1 |
|---|---|
| Pools | 1.000 / 0.993 |
| BOS | 0.915 |
| CHoCH | 0.692 |
| Sweeps | 0.852 / 0.821 |

"FP" here means bot events that the agents did not agree on. Almost all of them are real per the rules (section 3).

## 3. Rule-based ground-truth comparison: where and why the visual reading differs

**1. Sweep misses are mostly REPEAT_SWEEP candles.**

| Agent | Sweep FN that are repeat-only | Sweep FN that are first sweeps |
|---|---|---|
| AGENT_1 | 10 | 11 |
| AGENT_2 | 31 | 18 |
| AGENT_3 | 46 | 2 |

The annotator README never said that an already-swept pool can be swept again. AGENT_3 stated that it used "one sweep
per pool". This is a gap in the instructions, not a failure to see the candles.

**2. CHoCH disagreements are rule-interpretation differences, not bot defects.** Six CHoCH that all 3 agents marked
unanimously are not in GT:

| Chart / candle | What the approved rules say |
|---|---|
| H-03 / H-04 k77 | SR-5: an opposite BOS during TRANSITION restores the previous structure (REVERSAL_INVALIDATING), and is not a CHoCH |
| X-01 / X-04 k85 | CONTINUATION BOS; no protected level is in force there, per SR-2 / D2 timing |
| X-02 / X-03 k69 | No CHoCH, because SR-3 rejected the k53 confirmation: its reference swing was confirmed before the k51 CHoCH. The state therefore stayed TRANSITION until SR-5 invalidated it at k68 |

Agent CHoCH false positives mostly sit on BOS candles with roles COUNTER_STRUCTURE, REVERSAL_INVALIDATING, CONTINUATION
or TRANSITION_REF_BEFORE_CHOCH. The README described CHoCH in plain textbook terms, without SR-2/3/5.

**This is an owner review item.** The visual intuition of three annotators differs from SR-3/SR-5 on these patterns. The
rules were **not** changed.

**3. Equal-level and 1-px ties.** Agents treated sub-pixel differences as equal highs or lows. That is the main source of
the few POOL misses and of AGENT_3's notes.

**4. AGENT_1 BOS recall (0.65).** AGENT_1 under-marked BOS but had no BOS false positives. Its CHoCH marks absorbed some
of the BOS candles.

## 4. Unresolved / disputed cases

**Adjudication of 775 agent clusters:**

| Status | Count | Supported by GT |
|---|---|---|
| UNANIMOUS 3/3 | 500 | 494 (the other 6 are the CHoCH cases in section 3) |
| DISPUTED 2/3 (accepted by majority) | 146 | 142 |
| DISPUTED 1/3 (rejected minority) | 129 | 113 (these are real events that two agents missed) |

Per-cluster detail is in `05_COMPARISON_REPORTS/adjudication_clusters.csv`. The `gt_supported` column is a separate
rule-data note; it is not part of the vote.

**Intentionally unscored (documented in each GT JSON as `unscored`; never forced):**

| Case | Count | Why |
|---|---|---|
| Equal highs / equal lows | 19 / 19 zones | LQ-03 OPEN for equal-level pools. SW-003 says equal extremes are not swings, so GT has no pool there. Agent pools or sweeps on these zones are excluded from FP. |
| Close equal to a swing level | 24 candles | BOS-006 / C1 tick epsilon OPEN. Strict comparison applied. |
| Group membership of REPEAT_SWEEP / TAKEN | — | OQ-12 OPEN; not scored. |

Unscored predictions excluded from scoring: AGENT_1 38, AGENT_2 3, AGENT_3 12.

**Still OPEN in the spec:** OQ-12, LQ-03/07/10/11/12-R1/13/20, G-3/9/10, BOS-006/C1. Modules C onward (pattern,
confirmation, entry) are not implemented, so no candidate ever reaches CONFIRMED.

**Owner review items:**
- The SR-3 / SR-5 CHoCH patterns above.
- The commit blocker is unchanged: an isolated commit is impossible while the structure layer and Module A exist only
  in the 37 protected staged entries or the worktree.

## 5. Known limitations

- **GT author.** GT and the bot are independent code paths (no shared imports), but both were written by Claude from
  the same spec text. A shared misreading of the spec would not show up. No human annotated or verified GT.
- **Annotators.** The three annotators are Claude subagents, not humans. Isolation was enforced by instruction plus
  encryption of the sealed material, not by an OS sandbox.
- **Mirror pairs.** AGENT_3 noticed the exact mirror pairs, so the effective number of independent chart geometries is 8,
  not 16.
- **README simplifications.** The annotator README (`06_MANIFESTS_AND_SEEDS/README_FOR_ANNOTATORS.md`) simplified the
  CHoCH rules and did not say that repeat sweeps count. Agent recall on CHoCH and sweeps is partly an instruction effect.
- **AGENT_3 is not purely visual.** It reconstructed OHLC from pixels (about ±1 px), so it measures rule application
  more than visual reading.
- **Bot images.** The bot does not see images. Its marked PNGs are drawn from its OHLC output, using the renderer's
  stored axes geometry.
- **Tolerances.** Agents were matched within ±1 candle; the bot within 0.
- **Data realism.** The data is synthetic: 5-minute fake timestamps, 16 charts, no real market microstructure.
- **Attached pack not scored.** The user-attached `V6_VISUAL_BLIND_CHARTS_2026-11-23.zip` (16 PNGs plus seeds) has no
  OHLC data and no generator, so no ground truth can be computed for it.
- **Excluded from the ZIP.** Agent scratch crops (AGENT_1 about 247 zoom crops, AGENT_2 crops) and AGENT_3's pixel-OHLC
  dumps were left out. Their methods are described in each `AGENT_NOTES.md`.

## Layout

| Folder | Contents |
|---|---|
| `01_CHARTS/` | the original unmarked PNGs |
| `02_AGENT_ANNOTATIONS/AGENT_n/` | `marked/`, `json/`, `annotations_all.csv`, `AGENT_NOTES.md` (AGENT_3 also has `code/`) |
| `03_BOT_ANNOTATIONS/` | `json/`, `bot_events.csv`, `marked/`, `replay_checks.json`, `bot_run.py` |
| `04_SEALED_GROUND_TRUTH/` | `json/`, `ground_truth_events.csv`, `SEAL_COMMITMENT.sha256`, `oracles/` |
| `05_COMPARISON_REPORTS/` | metric CSVs, `comparison_results.json`, adjudication, `test_logs/`, D5 patch |
| `06_MANIFESTS_AND_SEEDS/` | `MANIFEST.json` (per chart: seed, scenario, mirror, hashes, paths), `ohlc/`, `scenarios.json`, `geometry.json`, `generator/`, annotator README |
| `SHA256SUMS.txt` | hash of every file |
