# SYNTHETIC DATASET PLAN: V6 Volume 1 (swings, structure, BOS)

**Status: DRAFT, pending approval.** Every expected result is tied to a named **illustrative** profile (SP-*, ML-A, TS-A, BOS-P*, RL/RH). None of them is an approved rule. Where the result depends on an open policy, the alternatives are listed instead of choosing one.

## Storage (PROPOSAL)

- **Draft data:** `research/v6/specs/volume1/synthetic_volume1.draft.json` (this file set). Each case holds:
  - `case_id`, `group`, `description`
  - `tick_size`
  - `candles` (`i`, `t`, `o`, `h`, `l`, `c`)
  - `expected` (a map from profile to events)
  - `expected_non_events`, `rationale`, `policy_dependence`
- **Proposed final home** once approved: `research/v6/data/synthetic/volume1/<case_id>.json`, one file per case, inputs separate from labels (PDF §9: *"Keep labels separate from OHLC input"*):
  - `<case_id>.candles.json`
  - `<case_id>.expected.json`

  **Note:** `research/v6/data/.gitignore` currently ignores everything in that folder (meant for real market data), so the synthetic folder needs an exception. That is decision D-DATA-1. Real market data stays under `research/v6/data/market/` and stays ignored.
- **Stable IDs (PROPOSAL):**
  - swings: `<case>:SW:<H|L><event_index>:<profile>`
  - breaks: `<case>:BRK:<dir>:<reference_swing_id>:<profile>`
  - Deterministic: they depend only on inputs and profile, never on run order or time.
- **Timestamps:** t0 = 2026-01-05 09:00 UTC, 5-minute bars, except RB03 (a 60-minute gap). Tick size 0.01.
- **How the data was built:**
  - Every series was **hand-designed**: a manual OHLC table, or a hand-chosen zig-zag path (a list of pivot points) expanded linearly.
  - Every open equals the previous close, except the deliberate gap in BOS07.
  - No random candles.
- **Verification done:**
  - Every OHLC row was checked for validity.
  - Every expectation in a computable profile was recomputed by a separate **scratch** checker. It lives in the session scratchpad, not the repo, and it is not V6 code. Result: **0 mismatches in 39 cases.**
  - Every case was loaded through the existing `CandleSeries`: 35 normal cases load; RB01, RB02 and RB04 are rejected and RB03 loads, as expected.

## Illustrative profiles used in expectations

| Profile | Meaning |
|---|---|
| SP-A | fixed window L2/R2, strict > on both sides (PDF illustrative, not approved) |
| SP-B | L2/R2, left strict, right inclusive (first of a tie) |
| SP-C | L2/R2, left inclusive, right strict (last of a tie) |
| SP-D | L2/R2 inclusive both (every tied bar) |
| SP-E | L5/R5 strict |
| SP-F | L3/R3 strict |
| SP-G | L2/R3 strict |
| SP-H | L2/R1 strict |
| ML-A | label vs previous confirmed swing of the same kind: >, <, == -> HH/LH/EH, HL/LL/EL; first = NONE |
| TS-A | state as of close k-1: BULLISH if latest high label HH and latest low label HL; BEARISH if LH and LL; else UNKNOWN |
| BOS-P1 | close strictly beyond level |
| BOS-P2 | close at or beyond level |
| BOS-P3 | wick beyond level |
| BOS-P4 | close beyond level + 2 ticks |
| RL | reference = latest confirmed swing of that kind, if unbroken |
| RH | reference = highest unbroken high / lowest unbroken low |
| dedup | one event per reference swing unless stated |
| break timing | break candle index > reference confirmed_index; event emitted at the break candle close |

## Coverage

| Requested scenario | Case(s) |
|---|---|
| Clear swing high / low | SW01, SW03 (PDF §4 dataset verbatim in SW01) |
| Equal highs / equal lows | SW04, SW05, SW13, SW14 / SW06 |
| Near-equal | SW07 |
| Insufficient right bars | SW01 (final low), SW08 |
| Outside candle | SW09 |
| Nested pivots | SW10, MS06 |
| Consecutive candidates | SW11 |
| Late confirmation | SW12, SW02 |
| HH → HL | MS01 |
| LH → LL | MS02 |
| Equal swing sequence | MS03, SW05 |
| Missing swing | MS01 (first swings), BOS14 |
| Conflicting structure | MS05 |
| Internal vs external | SW10, MS06 |
| Bullish / bearish BOS | BOS01 / BOS02 |
| Wick-only | BOS03 |
| Close-based | BOS01, BOS04 |
| Close exactly at level | BOS05 |
| One tick beyond | BOS06 |
| Gap through | BOS07 |
| Repeated break | BOS08 |
| Break before swing confirmation | BOS09 |
| Break against structure | BOS10, BOS12 |
| New level, distinct event | BOS11 |
| Close back through | BOS13 |
| Precision | BOS15 |
| Data integrity | RB01 (duplicate time), RB02 (invalid OHLC), RB03 (time gap), RB04 (unsorted) |

## Cases

### SW01: PDF section 4 dataset verbatim: clear swing high, final low unconfirmed (end-of-series trap).

- **Group:** swing
- **Policy dependence:** none

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 10.5 |
| 1 | 09:05 | 10.5 | 12 | 10 | 11.5 |
| 2 | 09:10 | 11.5 | 15 | 11 | 13 |
| 3 | 09:15 | 13 | 14 | 12 | 12.5 |
| 4 | 09:20 | 12.5 | 13 | 10 | 10.5 |
| 5 | 09:25 | 10.5 | 11 | 8 | 9 |
| 6 | 09:30 | 9 | 10 | 7 | 8 |
| 7 | 09:35 | 8 | 9 | 6 | 7 |

**Expected (per profile):**

- **SP-A:** SH2 (conf 4, 15)

**Expected non-events:** no swing low at 7 (only 0 right bars); no swing at 0/1 (insufficient left)

**Why:** PDF p4: 'swing high at i=2, confirmed at i=4. No confirmed swing low in this truncated sample.'

### SW02: SW01 plus two bars with lows above 6.0, as the PDF instructs: the low at 7 confirms at 9.

- **Group:** swing
- **Policy dependence:** none

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 10.5 |
| 1 | 09:05 | 10.5 | 12 | 10 | 11.5 |
| 2 | 09:10 | 11.5 | 15 | 11 | 13 |
| 3 | 09:15 | 13 | 14 | 12 | 12.5 |
| 4 | 09:20 | 12.5 | 13 | 10 | 10.5 |
| 5 | 09:25 | 10.5 | 11 | 8 | 9 |
| 6 | 09:30 | 9 | 10 | 7 | 8 |
| 7 | 09:35 | 8 | 9 | 6 | 7 |
| 8 | 09:40 | 7 | 8.5 | 6.5 | 8 |
| 9 | 09:45 | 8 | 9.5 | 7 | 9 |

**Expected (per profile):**

- **SP-A:** SH2 (conf 4, 15); SL7 (conf 9, 6)

**Expected non-events:** L7 not available at k=7 or k=8

**Why:** PDF p4: 'Append two later bars with lows above 6.0 to test confirmation of i=7.'

### SW03: Mirror of SW01 (price' = 20 - price): clear swing low; final high unconfirmed.

- **Group:** swing
- **Policy dependence:** none

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 9.5 |
| 1 | 09:05 | 9.5 | 10 | 8 | 8.5 |
| 2 | 09:10 | 8.5 | 9 | 5 | 7 |
| 3 | 09:15 | 7 | 8 | 6 | 7.5 |
| 4 | 09:20 | 7.5 | 10 | 7 | 9.5 |
| 5 | 09:25 | 9.5 | 12 | 9 | 11 |
| 6 | 09:30 | 11 | 13 | 10 | 12 |
| 7 | 09:35 | 12 | 14 | 11 | 13 |

**Expected (per profile):**

- **SP-A:** SL2 (conf 4, 5)

**Expected non-events:** no swing high at 7

**Why:** High/low symmetry: same indices as SW01 with kinds swapped.

### SW04: Adjacent equal highs (14 at i=2 and i=3).

- **Group:** swing_tie
- **Policy dependence:** SW-003, SW-004

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 10.5 |
| 1 | 09:05 | 10.5 | 12 | 10 | 11.5 |
| 2 | 09:10 | 11.5 | 14 | 11 | 13 |
| 3 | 09:15 | 13 | 14 | 12 | 12.5 |
| 4 | 09:20 | 12.5 | 13 | 10 | 10.5 |
| 5 | 09:25 | 10.5 | 12 | 9.5 | 10 |
| 6 | 09:30 | 10 | 11 | 9 | 9.5 |

**Expected (per profile):**

- **SP-A:** none
- **SP-B:** SH2 (conf 4, 14)
- **SP-C:** SH3 (conf 5, 14)
- **SP-D:** SH2 (conf 4, 14); SH3 (conf 5, 14)

**Expected non-events:** SP-A: no unique strict pivot (PDF E3)

**Why:** Strict > rejects ties (PDF 2.B). The outcome depends on the tie policy; cluster policy would give ONE cluster {2,3} confirmed at 5.

### SW05: Double top: equal highs (14) four bars apart, separated by a swing low.

- **Group:** swing_tie
- **Policy dependence:** SW-004, MS-001

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 10.5 |
| 1 | 09:05 | 10.5 | 12 | 10 | 11.5 |
| 2 | 09:10 | 11.5 | 14 | 11 | 13 |
| 3 | 09:15 | 13 | 13.5 | 11.5 | 12 |
| 4 | 09:20 | 12 | 12.5 | 10.5 | 11 |
| 5 | 09:25 | 11 | 13 | 10.8 | 12.5 |
| 6 | 09:30 | 12.5 | 14 | 12 | 13.5 |
| 7 | 09:35 | 13.5 | 13.8 | 12 | 12.5 |
| 8 | 09:40 | 12.5 | 13 | 11 | 11.5 |

**Expected (per profile):**

- **SP-A:** SH2 (conf 4, 14, NONE); SL4 (conf 6, 10.5, NONE); SH6 (conf 8, 14, EH)

**Expected non-events:** none listed

**Why:** Each peak is a strict pivot in its own window. The second high equals the first: HH/LH label undefined (EH).

### SW06: Adjacent equal lows (mirror of SW04).

- **Group:** swing_tie
- **Policy dependence:** SW-003, SW-004

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 9.5 |
| 1 | 09:05 | 9.5 | 10 | 8 | 8.5 |
| 2 | 09:10 | 8.5 | 9 | 6 | 7 |
| 3 | 09:15 | 7 | 8 | 6 | 7.5 |
| 4 | 09:20 | 7.5 | 10 | 7 | 9.5 |
| 5 | 09:25 | 9.5 | 10.5 | 8 | 10 |
| 6 | 09:30 | 10 | 11 | 9 | 10.5 |

**Expected (per profile):**

- **SP-A:** none
- **SP-B:** SL2 (conf 4, 6)
- **SP-C:** SL3 (conf 5, 6)
- **SP-D:** SL2 (conf 4, 6); SL3 (conf 5, 6)

**Expected non-events:** SP-A: no strict pivot low

**Why:** Mirror of SW04.

### SW07: Near-equal highs: 14.00 at i=2 and 13.99 at i=3 (one tick apart).

- **Group:** swing_tie
- **Policy dependence:** SW-004

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 10.5 |
| 1 | 09:05 | 10.5 | 12 | 10 | 11.5 |
| 2 | 09:10 | 11.5 | 14 | 11 | 13 |
| 3 | 09:15 | 13 | 13.99 | 12 | 12.5 |
| 4 | 09:20 | 12.5 | 13 | 10 | 10.5 |
| 5 | 09:25 | 10.5 | 12 | 9.5 | 10 |
| 6 | 09:30 | 10 | 11 | 9 | 9.5 |

**Expected (per profile):**

- **SP-A:** SH2 (conf 4, 14)
- **SP-A + tolerance >= 1 tick:** same as SW04 (treated as equal)

**Expected non-events:** none listed

**Why:** Under raw-price strict comparison the 1-tick-higher bar is the pivot. A tolerance of >=1 tick turns this into a tie case.

### SW08: Candidate high at i=3 with only one right-side bar at the end of the data.

- **Group:** swing
- **Policy dependence:** SW-002

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 10.5 |
| 1 | 09:05 | 10.5 | 12 | 10 | 11.5 |
| 2 | 09:10 | 11.5 | 13 | 11 | 12.5 |
| 3 | 09:15 | 12.5 | 14 | 12 | 13.5 |
| 4 | 09:20 | 13.5 | 13.8 | 12.5 | 13 |

**Expected (per profile):**

- **SP-A:** none
- **SP-H (R=1):** SH3 (conf 4, 14)

**Expected non-events:** SP-A: H3 stays a candidate (needs i=5)

**Why:** PDF E2 / end-of-dataset: insufficient right-side evidence -> unconfirmed. Must not be forced.

### SW09: Outside candle at i=2: highest high and lowest low of its window.

- **Group:** swing_outside
- **Policy dependence:** SW-005

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 10.5 |
| 1 | 09:05 | 10.5 | 11.5 | 9.5 | 11 |
| 2 | 09:10 | 11 | 13 | 8 | 9 |
| 3 | 09:15 | 9 | 12 | 8.5 | 11.5 |
| 4 | 09:20 | 11.5 | 12.5 | 9 | 10 |

**Expected (per profile):**

- **SP-A (both allowed):** SH2 (conf 4, 13); SL2 (conf 4, 8)
- **alt: reject both:** none
- **alt: tie-break:** one of H2 / L2

**Expected non-events:** none listed

**Why:** PDF 7: outside bar -> allow both, reject both, or tie-break.

### SW10: Small swing (H5/L7) inside the advance to a larger top at i=10.

- **Group:** swing_nested
- **Policy dependence:** SW-002, SW-006, SW-007

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 8.3 | 9 | 8 | 8.7 |
| 1 | 09:05 | 8.7 | 9.5 | 8.5 | 9.2 |
| 2 | 09:10 | 9.2 | 10 | 9 | 9.7 |
| 3 | 09:15 | 9.7 | 10.5 | 9.5 | 10.2 |
| 4 | 09:20 | 10.2 | 11 | 10.2 | 10.76 |
| 5 | 09:25 | 11 | 12 | 11 | 11.7 |
| 6 | 09:30 | 11.5 | 11.5 | 10.5 | 10.8 |
| 7 | 09:35 | 10.8 | 11.2 | 10 | 10.36 |
| 8 | 09:40 | 11 | 12.5 | 11 | 12.05 |
| 9 | 09:45 | 12.05 | 13.5 | 12 | 13.05 |
| 10 | 09:50 | 13.5 | 15 | 13.5 | 14.55 |
| 11 | 09:55 | 14.5 | 14.5 | 13.5 | 13.8 |
| 12 | 10:00 | 13.8 | 14 | 13 | 13.3 |
| 13 | 10:05 | 13 | 13 | 12 | 12.3 |
| 14 | 10:10 | 12.3 | 12.5 | 11.5 | 11.8 |
| 15 | 10:15 | 11.8 | 12 | 11 | 11.3 |
| 16 | 10:20 | 11.3 | 11.5 | 10.5 | 10.8 |

**Expected (per profile):**

- **SP-A:** SH5 (conf 7, 12, NONE); SL7 (conf 9, 10, NONE); SH10 (conf 12, 15, HH)
- **SP-F (3/3):** SL7 (conf 10, 10); SH10 (conf 13, 15)
- **SP-E (5/5):** SH10 (conf 15, 15)

**Expected non-events:** none listed

**Why:** Different windows give different structure; with 5/5 only the external top exists and it confirms 3 bars later.

### SW11: Candidate high at 2 rejected when bar 4 makes a higher high; bar 4 becomes the pivot.

- **Group:** swing_replace
- **Policy dependence:** SW-008

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 8.95 | 10 | 8.5 | 9.55 |
| 1 | 09:05 | 9.55 | 11 | 9.5 | 10.55 |
| 2 | 09:10 | 11.5 | 13 | 11.5 | 12.55 |
| 3 | 09:15 | 12 | 12 | 10.5 | 10.95 |
| 4 | 09:20 | 12.5 | 14 | 12.5 | 13.55 |
| 5 | 09:25 | 13 | 13 | 11.5 | 11.95 |
| 6 | 09:30 | 11.95 | 12.5 | 11.0 | 11.45 |
| 7 | 09:35 | 11.45 | 12 | 10.5 | 10.95 |

**Expected (per profile):**

- **SP-A:** SH4 (conf 6, 14)

**Expected non-events:** H2 never emitted (rejected at close of 4)

**Why:** A candidate is not an event: its rejection is not a repaint because it was never emitted.

### SW12: Late confirmation: candidate at 3.

- **Group:** swing_timing
- **Policy dependence:** SW-002

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 8.95 | 10 | 8.5 | 9.55 |
| 1 | 09:05 | 9.55 | 11 | 9.5 | 10.55 |
| 2 | 09:10 | 10.55 | 12 | 10.5 | 11.55 |
| 3 | 09:15 | 13.5 | 15 | 13.5 | 14.55 |
| 4 | 09:20 | 13 | 13 | 11.5 | 11.95 |
| 5 | 09:25 | 11.95 | 12 | 10.5 | 10.95 |
| 6 | 09:30 | 10.95 | 11.5 | 10.0 | 10.45 |
| 7 | 09:35 | 10.45 | 11 | 9.5 | 9.95 |

**Expected (per profile):**

- **SP-A:** SH3 (conf 5, 15)
- **SP-G (R=3):** SH3 (conf 6, 15)
- **SP-H (R=1):** SH3 (conf 4, 15)

**Expected non-events:** SP-A: nothing at k=3 or k=4

**Why:** PDF section 3: event_index 3, confirmed_index = 3 + R. Replay must emit at k=5.

### SW13: Plateau: three equal highs (14) at 2, 3, 4.

- **Group:** swing_tie
- **Policy dependence:** SW-004

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 9.3 | 10 | 9 | 9.7 |
| 1 | 09:05 | 10 | 11 | 10 | 10.7 |
| 2 | 09:10 | 12.5 | 14 | 12.5 | 13.55 |
| 3 | 09:15 | 13.55 | 14 | 12.8 | 13.16 |
| 4 | 09:20 | 13.16 | 14 | 12.6 | 13.02 |
| 5 | 09:25 | 12 | 12 | 10.5 | 10.95 |
| 6 | 09:30 | 10.95 | 11 | 9.5 | 9.95 |

**Expected (per profile):**

- **SP-A:** none
- **SP-B:** SH2 (conf 4, 14)
- **SP-C:** SH4 (conf 6, 14)
- **SP-D:** SH2 (conf 4, 14); SH3 (conf 5, 14); SH4 (conf 6, 14)

**Expected non-events:** SP-A: no pivot

**Why:** First / last / all / cluster: each tie policy gives a different answer.

### SW14: Equal high (14) reached again at the right-window boundary (i=4) after a lower bar.

- **Group:** swing_tie
- **Policy dependence:** SW-004

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 9.3 | 10 | 9 | 9.7 |
| 1 | 09:05 | 10 | 11 | 10 | 10.7 |
| 2 | 09:10 | 12.5 | 14 | 12.5 | 13.55 |
| 3 | 09:15 | 13 | 13 | 11.8 | 12.16 |
| 4 | 09:20 | 12.6 | 14 | 12.6 | 13.58 |
| 5 | 09:25 | 12 | 12 | 10.5 | 10.95 |
| 6 | 09:30 | 10.95 | 11 | 9.5 | 9.95 |

**Expected (per profile):**

- **SP-A:** none
- **SP-B:** SH2 (conf 4, 14)
- **SP-C:** SH4 (conf 6, 14)
- **SP-D:** SH2 (conf 4, 14); SH4 (conf 6, 14)

**Expected non-events:** SP-A: H2 rejected at close of 4, H4 rejected by equal left neighbour

**Why:** Non-adjacent tie inside one window.

### SW15: Highest high on the very first bar (no left history).

- **Group:** swing
- **Policy dependence:** SW-002

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 12.95 | 14 | 12.5 | 12.95 |
| 1 | 09:05 | 12 | 12 | 11 | 11.3 |
| 2 | 09:10 | 11 | 11 | 10 | 10.3 |
| 3 | 09:15 | 10.3 | 10.5 | 9.6 | 9.87 |
| 4 | 09:20 | 9.87 | 10 | 9 | 9.3 |

**Expected (per profile):**

- **SP-A:** none
- **alt: partial left window at series start:** SH0 (conf 2, 14)

**Expected non-events:** SP-A: bars 0-1 not eligible

**Why:** Insufficient left history: either ineligible or a relaxed start rule.

### MS01: Clean uptrend: L, H, HL, HH, HL.

- **Group:** structure
- **Policy dependence:** MS-001

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.2 | 109.2 | 106.8 | 107.2 |
| 16 | 10:20 | 107.2 | 108.2 | 105.8 | 106.2 |
| 17 | 10:25 | 106.2 | 107.2 | 104.8 | 105.2 |
| 18 | 10:30 | 105.2 | 106.2 | 103.8 | 104.2 |
| 19 | 10:35 | 104.8 | 107.2 | 104.8 | 106.8 |
| 20 | 10:40 | 106.8 | 108.2 | 105.8 | 107.8 |

**Expected (per profile):**

- **SP-A + ML-A:** SL2 (conf 4, 98.8, NONE); SH6 (conf 8, 107.2, NONE); SL10 (conf 12, 101.8, HL); SH14 (conf 16, 110.2, HH); SL18 (conf 20, 103.8, HL)
- **TS-A state:** k<16: UNKNOWN; 16..20: BULLISH (HH@16 + HL@12, then HL@20)
- **BOS-P1 (close>, RL):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED)

**Expected non-events:** no label before a comparable earlier swing exists (first H and first L = NONE)

**Why:** Labels compare each swing with the previous confirmed swing of the same kind; labels exist from that swing's confirmation.

### MS02: Mirror of MS01: clean downtrend LH / LL.

- **Group:** structure
- **Policy dependence:** MS-001

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 108.8 | 109.2 | 106.8 | 107.2 |
| 1 | 09:05 | 107.8 | 110.2 | 107.8 | 109.8 |
| 2 | 09:10 | 109.8 | 111.2 | 108.8 | 110.8 |
| 3 | 09:15 | 109.7 | 109.7 | 107.3 | 107.7 |
| 4 | 09:20 | 107.7 | 108.2 | 105.8 | 106.2 |
| 5 | 09:25 | 106.2 | 106.7 | 104.3 | 104.7 |
| 6 | 09:30 | 104.7 | 105.2 | 102.8 | 103.2 |
| 7 | 09:35 | 103.55 | 105.95 | 103.55 | 105.55 |
| 8 | 09:40 | 105.55 | 106.7 | 104.3 | 106.3 |
| 9 | 09:45 | 106.3 | 107.45 | 105.05 | 107.05 |
| 10 | 09:50 | 107.05 | 108.2 | 105.8 | 107.8 |
| 11 | 09:55 | 106.7 | 106.7 | 104.3 | 104.7 |
| 12 | 10:00 | 104.7 | 105.2 | 102.8 | 103.2 |
| 13 | 10:05 | 103.2 | 103.7 | 101.3 | 101.7 |
| 14 | 10:10 | 101.7 | 102.2 | 99.8 | 100.2 |
| 15 | 10:15 | 100.8 | 103.2 | 100.8 | 102.8 |
| 16 | 10:20 | 102.8 | 104.2 | 101.8 | 103.8 |
| 17 | 10:25 | 103.8 | 105.2 | 102.8 | 104.8 |
| 18 | 10:30 | 104.8 | 106.2 | 103.8 | 105.8 |
| 19 | 10:35 | 105.2 | 105.2 | 102.8 | 103.2 |
| 20 | 10:40 | 103.2 | 104.2 | 101.8 | 102.2 |

**Expected (per profile):**

- **SP-A + ML-A:** SH2 (conf 4, 111.2, NONE); SL6 (conf 8, 102.8, NONE); SH10 (conf 12, 108.2, LH); SL14 (conf 16, 99.8, LL); SH18 (conf 20, 106.2, LH)
- **BOS-P1 (close<, RL):** bearish break @13 of SL6 102.8 (ref conf 8, close, UNCLASSIFIED)

**Expected non-events:** none listed

**Why:** Mirror symmetry.

### MS03: Equal swing highs: H14 equals H6 (107.2).

- **Group:** structure
- **Policy dependence:** SW-004, MS-001

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 102.55 | 104.95 | 102.55 | 104.55 |
| 12 | 10:00 | 104.55 | 105.7 | 103.3 | 105.3 |
| 13 | 10:05 | 105.3 | 106.45 | 104.05 | 106.05 |
| 14 | 10:10 | 106.05 | 107.2 | 104.8 | 106.8 |
| 15 | 10:15 | 106.7 | 106.7 | 104.3 | 104.7 |
| 16 | 10:20 | 104.7 | 106.2 | 103.8 | 104.2 |
| 17 | 10:25 | 104.2 | 105.7 | 103.3 | 103.7 |
| 18 | 10:30 | 103.7 | 105.2 | 102.8 | 103.2 |
| 19 | 10:35 | 103.3 | 105.7 | 103.3 | 105.3 |
| 20 | 10:40 | 105.3 | 106.2 | 103.8 | 105.8 |

**Expected (per profile):**

- **SP-A + ML-A:** SL2 (conf 4, 98.8, NONE); SH6 (conf 8, 107.2, NONE); SL10 (conf 12, 101.8, HL); SH14 (conf 16, 107.2, EH); SL18 (conf 20, 102.8, HL)
- **TS-A state:** UNKNOWN (EH is neither HH nor LH)
- **BOS-P1:** none

**Expected non-events:** no break: no close above 107.2

**Why:** Equal-structure labelling must be decided (EH treated as HH, LH, or neutral).

### MS05: Broadening: HH then LL (conflicting).

- **Group:** structure
- **Policy dependence:** MS-001, BOS-003

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 103.2 | 105.2 | 102.8 | 104.8 |
| 1 | 09:05 | 104.2 | 104.2 | 101.8 | 102.2 |
| 2 | 09:10 | 102.2 | 103.2 | 100.8 | 101.2 |
| 3 | 09:15 | 101.8 | 104.2 | 101.8 | 103.8 |
| 4 | 09:20 | 103.8 | 105.2 | 102.8 | 104.8 |
| 5 | 09:25 | 104.8 | 106.2 | 103.8 | 105.8 |
| 6 | 09:30 | 105.8 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 105.7 | 105.7 | 103.3 | 103.7 |
| 8 | 09:40 | 103.7 | 104.2 | 101.8 | 102.2 |
| 9 | 09:45 | 102.2 | 102.7 | 100.3 | 100.7 |
| 10 | 09:50 | 100.7 | 101.2 | 98.8 | 99.2 |
| 11 | 09:55 | 100.8 | 103.2 | 100.8 | 102.8 |
| 12 | 10:00 | 102.8 | 105.2 | 102.8 | 104.8 |
| 13 | 10:05 | 104.8 | 107.2 | 104.8 | 106.8 |
| 14 | 10:10 | 106.8 | 109.2 | 106.8 | 108.8 |
| 15 | 10:15 | 106.7 | 106.7 | 104.3 | 104.7 |
| 16 | 10:20 | 104.2 | 104.2 | 101.8 | 102.2 |
| 17 | 10:25 | 101.7 | 101.7 | 99.3 | 99.7 |
| 18 | 10:30 | 99.2 | 99.2 | 96.8 | 97.2 |
| 19 | 10:35 | 97.8 | 100.2 | 97.8 | 99.8 |
| 20 | 10:40 | 99.8 | 101.2 | 98.8 | 100.8 |

**Expected (per profile):**

- **SP-A + ML-A:** SL2 (conf 4, 100.8, NONE); SH6 (conf 8, 107.2, NONE); SL10 (conf 12, 98.8, LL); SH14 (conf 16, 109.2, HH); SL18 (conf 20, 96.8, LL)
- **TS-A state:** UNKNOWN throughout
- **BOS-P1 (RL):** bearish break @9 of SL2 100.8 (ref conf 4, close, UNCLASSIFIED); bullish break @14 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bearish break @18 of SL10 98.8 (ref conf 12, close, UNCLASSIFIED)

**Expected non-events:** no BOS/CHoCH label: state unknown

**Why:** Every sequence of pivots is not a trend; breaks exist but cannot be labelled.

### MS06: SW10 data: internal (2/2) vs external (5/5) structure.

- **Group:** structure_nested
- **Policy dependence:** SW-006, BOS-001

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 8.3 | 9 | 8 | 8.7 |
| 1 | 09:05 | 8.7 | 9.5 | 8.5 | 9.2 |
| 2 | 09:10 | 9.2 | 10 | 9 | 9.7 |
| 3 | 09:15 | 9.7 | 10.5 | 9.5 | 10.2 |
| 4 | 09:20 | 10.2 | 11 | 10.2 | 10.76 |
| 5 | 09:25 | 11 | 12 | 11 | 11.7 |
| 6 | 09:30 | 11.5 | 11.5 | 10.5 | 10.8 |
| 7 | 09:35 | 10.8 | 11.2 | 10 | 10.36 |
| 8 | 09:40 | 11 | 12.5 | 11 | 12.05 |
| 9 | 09:45 | 12.05 | 13.5 | 12 | 13.05 |
| 10 | 09:50 | 13.5 | 15 | 13.5 | 14.55 |
| 11 | 09:55 | 14.5 | 14.5 | 13.5 | 13.8 |
| 12 | 10:00 | 13.8 | 14 | 13 | 13.3 |
| 13 | 10:05 | 13 | 13 | 12 | 12.3 |
| 14 | 10:10 | 12.3 | 12.5 | 11.5 | 11.8 |
| 15 | 10:15 | 11.8 | 12 | 11 | 11.3 |
| 16 | 10:20 | 11.3 | 11.5 | 10.5 | 10.8 |

**Expected (per profile):**

- **SP-A:** SH5 (conf 7, 12, NONE); SL7 (conf 9, 10, NONE); SH10 (conf 12, 15, HH)
- **SP-E:** SH10 (conf 15, 15, NONE)
- **BOS-P1 on SP-A:** bullish break @8 of SH5 12 (ref conf 7, close, UNCLASSIFIED)
- **BOS-P1 on SP-E:** none

**Expected non-events:** none listed

**Why:** The same candles produce an internal BOS under 2/2 and none under 5/5.

### BOS01: Bullish continuation: MS01 then close above SH14 (110.2) at 22.

- **Group:** bos
- **Policy dependence:** BOS-001, BOS-002, BOS-003

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.2 | 109.2 | 106.8 | 107.2 |
| 16 | 10:20 | 107.2 | 108.2 | 105.8 | 106.2 |
| 17 | 10:25 | 106.2 | 107.2 | 104.8 | 105.2 |
| 18 | 10:30 | 105.2 | 106.2 | 103.8 | 104.2 |
| 19 | 10:35 | 104.8 | 107.2 | 104.8 | 106.8 |
| 20 | 10:40 | 106.8 | 108.2 | 105.8 | 107.8 |
| 21 | 10:45 | 107.8 | 109.7 | 107.3 | 109.3 |
| 22 | 10:50 | 109.3 | 111.2 | 108.8 | 110.8 |
| 23 | 10:55 | 110.8 | 112.2 | 109.8 | 111.8 |

**Expected (per profile):**

- **SP-A + BOS-P1/P2/P3/P4 (RL):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @22 of SH14 110.2 (ref conf 16, close, BOS)

**Expected non-events:** no event at 21 (close 109.3, high 109.7)

**Why:** Bullish state (HH@14, HL@18) + close above the latest confirmed high.

### BOS02: Bearish continuation: mirror of BOS01.

- **Group:** bos
- **Policy dependence:** BOS-001, BOS-002, BOS-003

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 108.8 | 109.2 | 106.8 | 107.2 |
| 1 | 09:05 | 107.8 | 110.2 | 107.8 | 109.8 |
| 2 | 09:10 | 109.8 | 111.2 | 108.8 | 110.8 |
| 3 | 09:15 | 109.7 | 109.7 | 107.3 | 107.7 |
| 4 | 09:20 | 107.7 | 108.2 | 105.8 | 106.2 |
| 5 | 09:25 | 106.2 | 106.7 | 104.3 | 104.7 |
| 6 | 09:30 | 104.7 | 105.2 | 102.8 | 103.2 |
| 7 | 09:35 | 103.55 | 105.95 | 103.55 | 105.55 |
| 8 | 09:40 | 105.55 | 106.7 | 104.3 | 106.3 |
| 9 | 09:45 | 106.3 | 107.45 | 105.05 | 107.05 |
| 10 | 09:50 | 107.05 | 108.2 | 105.8 | 107.8 |
| 11 | 09:55 | 106.7 | 106.7 | 104.3 | 104.7 |
| 12 | 10:00 | 104.7 | 105.2 | 102.8 | 103.2 |
| 13 | 10:05 | 103.2 | 103.7 | 101.3 | 101.7 |
| 14 | 10:10 | 101.7 | 102.2 | 99.8 | 100.2 |
| 15 | 10:15 | 100.8 | 103.2 | 100.8 | 102.8 |
| 16 | 10:20 | 102.8 | 104.2 | 101.8 | 103.8 |
| 17 | 10:25 | 103.8 | 105.2 | 102.8 | 104.8 |
| 18 | 10:30 | 104.8 | 106.2 | 103.8 | 105.8 |
| 19 | 10:35 | 105.2 | 105.2 | 102.8 | 103.2 |
| 20 | 10:40 | 103.2 | 104.2 | 101.8 | 102.2 |
| 21 | 10:45 | 102.2 | 102.7 | 100.3 | 100.7 |
| 22 | 10:50 | 100.7 | 101.2 | 98.8 | 99.2 |
| 23 | 10:55 | 99.2 | 100.2 | 97.8 | 98.2 |

**Expected (per profile):**

- **SP-A + BOS-P1 (RL):** bearish break @13 of SL6 102.8 (ref conf 8, close, UNCLASSIFIED); bearish break @22 of SL14 99.8 (ref conf 16, close, BOS)

**Expected non-events:** none listed

**Why:** Mirror symmetry.

### BOS03: Wick-only break: high 110.6 > 110.2 at 21, closes stay below.

- **Group:** bos_false
- **Policy dependence:** BOS-002

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.2 | 109.2 | 106.8 | 107.2 |
| 16 | 10:20 | 107.2 | 108.2 | 105.8 | 106.2 |
| 17 | 10:25 | 106.2 | 107.2 | 104.8 | 105.2 |
| 18 | 10:30 | 105.2 | 106.2 | 103.8 | 104.2 |
| 19 | 10:35 | 104.8 | 107.2 | 104.8 | 106.8 |
| 20 | 10:40 | 106.8 | 108.2 | 105.8 | 107.8 |
| 21 | 10:45 | 107.8 | 110.6 | 107.5 | 109.8 |
| 22 | 10:50 | 109.8 | 110.1 | 108.9 | 109.2 |
| 23 | 10:55 | 109.2 | 109.9 | 108.6 | 109.5 |

**Expected (per profile):**

- **BOS-P1/P2/P4 (close):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED)
- **BOS-P3 (wick):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, wick, BOS)
- **side effect:** new swing high H21 (110.6) confirmed at 23 under SP-A

**Expected non-events:** close profiles: no break of SH14

**Why:** PDF E4: depends on the wick/close policy.

### BOS04: Wick at 21, then a close above at 22.

- **Group:** bos
- **Policy dependence:** BOS-002, BOS-005

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.2 | 109.2 | 106.8 | 107.2 |
| 16 | 10:20 | 107.2 | 108.2 | 105.8 | 106.2 |
| 17 | 10:25 | 106.2 | 107.2 | 104.8 | 105.2 |
| 18 | 10:30 | 105.2 | 106.2 | 103.8 | 104.2 |
| 19 | 10:35 | 104.8 | 107.2 | 104.8 | 106.8 |
| 20 | 10:40 | 106.8 | 108.2 | 105.8 | 107.8 |
| 21 | 10:45 | 107.8 | 110.6 | 107.5 | 109.8 |
| 22 | 10:50 | 109.8 | 111.4 | 109.5 | 111.0 |
| 23 | 10:55 | 111.0 | 111.6 | 110.6 | 111.3 |

**Expected (per profile):**

- **BOS-P1/P2/P4:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @22 of SH14 110.2 (ref conf 16, close, BOS)
- **BOS-P3 (wick):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, wick, BOS)

**Expected non-events:** BOS-P3 dedup: no second event at 22

**Why:** Wick and close profiles give different event candles for the same level.

### BOS05: Close exactly at the level (110.2) at 21.

- **Group:** bos_boundary
- **Policy dependence:** BOS-002, BOS-006

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.2 | 109.2 | 106.8 | 107.2 |
| 16 | 10:20 | 107.2 | 108.2 | 105.8 | 106.2 |
| 17 | 10:25 | 106.2 | 107.2 | 104.8 | 105.2 |
| 18 | 10:30 | 105.2 | 106.2 | 103.8 | 104.2 |
| 19 | 10:35 | 104.8 | 107.2 | 104.8 | 106.8 |
| 20 | 10:40 | 106.8 | 108.2 | 105.8 | 107.8 |
| 21 | 10:45 | 107.8 | 110.5 | 107.5 | 110.2 |
| 22 | 10:50 | 110.2 | 110.3 | 109.2 | 109.6 |
| 23 | 10:55 | 109.6 | 109.9 | 108.9 | 109.3 |

**Expected (per profile):**

- **BOS-P1 (close >):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED)
- **BOS-P2 (close >=):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, close, BOS)
- **BOS-P3 (wick):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, wick, BOS)

**Expected non-events:** none listed

**Why:** PDF section 7: strict vs inclusive comparison.

### BOS06: Close one tick above the level (110.21).

- **Group:** bos_boundary
- **Policy dependence:** BOS-002, BOS-006

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.2 | 109.2 | 106.8 | 107.2 |
| 16 | 10:20 | 107.2 | 108.2 | 105.8 | 106.2 |
| 17 | 10:25 | 106.2 | 107.2 | 104.8 | 105.2 |
| 18 | 10:30 | 105.2 | 106.2 | 103.8 | 104.2 |
| 19 | 10:35 | 104.8 | 107.2 | 104.8 | 106.8 |
| 20 | 10:40 | 106.8 | 108.2 | 105.8 | 107.8 |
| 21 | 10:45 | 107.8 | 110.5 | 107.5 | 110.21 |
| 22 | 10:50 | 110.21 | 110.3 | 109.2 | 109.6 |
| 23 | 10:55 | 109.6 | 109.9 | 108.9 | 109.3 |

**Expected (per profile):**

- **BOS-P1/P2/P3:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, close, BOS)
- **BOS-P4 (close > level + 2 ticks):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED)

**Expected non-events:** none listed

**Why:** PDF E5: depends on strictness, tick size and buffer.

### BOS07: Gap through: bar 21 opens 110.6 above the level (previous close 107.8) and never trades below it.

- **Group:** bos_gap
- **Policy dependence:** BOS-006

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.2 | 109.2 | 106.8 | 107.2 |
| 16 | 10:20 | 107.2 | 108.2 | 105.8 | 106.2 |
| 17 | 10:25 | 106.2 | 107.2 | 104.8 | 105.2 |
| 18 | 10:30 | 105.2 | 106.2 | 103.8 | 104.2 |
| 19 | 10:35 | 104.8 | 107.2 | 104.8 | 106.8 |
| 20 | 10:40 | 106.8 | 108.2 | 105.8 | 107.8 |
| 21 | 10:45 | 110.6 | 111.4 | 110.4 | 111.1 |
| 22 | 10:50 | 111.1 | 111.6 | 110.8 | 111.3 |
| 23 | 10:55 | 111.3 | 111.9 | 111.0 | 111.7 |

**Expected (per profile):**

- **BOS-P1..P4 (gap counts):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, close; gap, BOS)
- **alt: gap excluded:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED)
- **alt: gap flagged:** same event with evidence 'gap'

**Expected non-events:** none listed

**Why:** PDF section 7: specify whether a gap qualifies.

### BOS08: Repeated breaks of one level: closes above at 21, back below at 22, above again at 23 and 24.

- **Group:** bos_dup
- **Policy dependence:** BOS-005

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.2 | 109.2 | 106.8 | 107.2 |
| 16 | 10:20 | 107.2 | 108.2 | 105.8 | 106.2 |
| 17 | 10:25 | 106.2 | 107.2 | 104.8 | 105.2 |
| 18 | 10:30 | 105.2 | 106.2 | 103.8 | 104.2 |
| 19 | 10:35 | 104.8 | 107.2 | 104.8 | 106.8 |
| 20 | 10:40 | 106.8 | 108.2 | 105.8 | 107.8 |
| 21 | 10:45 | 107.8 | 110.7 | 107.6 | 110.5 |
| 22 | 10:50 | 110.5 | 110.6 | 109.4 | 109.8 |
| 23 | 10:55 | 109.8 | 111.0 | 109.6 | 110.8 |
| 24 | 11:00 | 110.8 | 111.3 | 110.5 | 111.1 |

**Expected (per profile):**

- **BOS-P1 + one event per level:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, close, BOS)
- **alt: event per new cross:** 21 and 23
- **alt: event per close beyond:** 21, 23, 24

**Expected non-events:** no second SH14 event under dedup

**Why:** PDF E7 / section 7: deduplicate by stable level ID.

### BOS09: Price exceeds the high of bar 14 at bar 15, before bar 14 could confirm as a swing.

- **Group:** bos_causal
- **Policy dependence:** BOS-001, BOS-004

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.8 | 110.9 | 109.5 | 110.7 |
| 16 | 10:20 | 110.7 | 111.0 | 110.1 | 110.4 |
| 17 | 10:25 | 110.4 | 110.6 | 109.8 | 110.0 |

**Expected (per profile):**

- **SP-A + BOS-P1:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED)

**Expected non-events:** no swing H14 (rejected by bar 15); no break event referencing bar 14

**Why:** PDF E6: a level cannot be used before its swing confirms. Under a fixed strict window the candidate is simply never confirmed.

### BOS10: Bullish structure, then closes below the lows: SL18 (103.8) at 22, SL10 (101.8) at 23.

- **Group:** bos_counter
- **Policy dependence:** BOS-001, BOS-003, MS-001

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.2 | 109.2 | 106.8 | 107.2 |
| 16 | 10:20 | 107.2 | 108.2 | 105.8 | 106.2 |
| 17 | 10:25 | 106.2 | 107.2 | 104.8 | 105.2 |
| 18 | 10:30 | 105.2 | 106.2 | 103.8 | 104.2 |
| 19 | 10:35 | 104.8 | 107.2 | 104.8 | 106.8 |
| 20 | 10:40 | 106.8 | 108.2 | 105.8 | 107.8 |
| 21 | 10:45 | 106.7 | 106.7 | 104.3 | 104.7 |
| 22 | 10:50 | 104.7 | 105.2 | 102.8 | 103.2 |
| 23 | 10:55 | 103.2 | 103.7 | 101.3 | 101.7 |
| 24 | 11:00 | 101.7 | 102.7 | 100.3 | 100.7 |

**Expected (per profile):**

- **BOS-P1 + RL (latest confirmed low):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bearish break @22 of SL18 103.8 (ref conf 20, close, CHOCH_CANDIDATE)
- **alt: protected low = low that started the last HH leg (SL10):** bearish counter-structure break at 23
- **BOS-P1 + RH (lowest unbroken low):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED)
- **side effect:** new swing high H20 (LH) confirmed at 22

**Expected non-events:** must NOT be labelled BOS by direction alone

**Why:** PDF section 6: counter-structure break = potential CHoCH only with a state model.

### BOS11: Two continuation BOS on two different levels (SH14 at 22, SH24 at 31).

- **Group:** bos
- **Policy dependence:** BOS-005

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.2 | 109.2 | 106.8 | 107.2 |
| 16 | 10:20 | 107.2 | 108.2 | 105.8 | 106.2 |
| 17 | 10:25 | 106.2 | 107.2 | 104.8 | 105.2 |
| 18 | 10:30 | 105.2 | 106.2 | 103.8 | 104.2 |
| 19 | 10:35 | 104.8 | 107.2 | 104.8 | 106.8 |
| 20 | 10:40 | 106.8 | 108.2 | 105.8 | 107.8 |
| 21 | 10:45 | 107.8 | 109.7 | 107.3 | 109.3 |
| 22 | 10:50 | 109.3 | 111.2 | 108.8 | 110.8 |
| 23 | 10:55 | 110.8 | 112.2 | 109.8 | 111.8 |
| 24 | 11:00 | 111.8 | 113.2 | 110.8 | 112.8 |
| 25 | 11:05 | 112.325 | 112.325 | 109.925 | 110.325 |
| 26 | 11:10 | 110.325 | 111.45 | 109.05 | 109.45 |
| 27 | 11:15 | 109.45 | 110.575 | 108.175 | 108.575 |
| 28 | 11:20 | 108.575 | 109.7 | 107.3 | 107.7 |
| 29 | 11:25 | 108.675 | 111.075 | 108.675 | 110.675 |
| 30 | 11:30 | 110.675 | 112.45 | 110.05 | 112.05 |
| 31 | 11:35 | 112.05 | 113.825 | 111.425 | 113.425 |
| 32 | 11:40 | 113.425 | 115.2 | 112.8 | 114.8 |

**Expected (per profile):**

- **SP-A + BOS-P1 (RL):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @22 of SH14 110.2 (ref conf 16, close, BOS); bullish break @31 of SH24 113.2 (ref conf 26, close, BOS)

**Expected non-events:** none listed

**Why:** PDF section 10: a new reference level creates a distinct event.

### BOS12: Bearish structure; price closes above the latest LH (106.7) but not the older high (110.7).

- **Group:** bos_reference
- **Policy dependence:** BOS-001, BOS-003

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 105.2 | 107.2 | 104.8 | 106.8 |
| 1 | 09:05 | 106.8 | 108.95 | 106.55 | 108.55 |
| 2 | 09:10 | 108.55 | 110.7 | 108.3 | 110.3 |
| 3 | 09:15 | 108.825 | 108.825 | 106.425 | 106.825 |
| 4 | 09:20 | 106.825 | 106.95 | 104.55 | 104.95 |
| 5 | 09:25 | 104.95 | 105.075 | 102.675 | 103.075 |
| 6 | 09:30 | 103.075 | 103.2 | 100.8 | 101.2 |
| 7 | 09:35 | 101.675 | 104.075 | 101.675 | 103.675 |
| 8 | 09:40 | 103.675 | 104.95 | 102.55 | 104.55 |
| 9 | 09:45 | 104.55 | 105.825 | 103.425 | 105.425 |
| 10 | 09:50 | 105.425 | 106.7 | 104.3 | 106.3 |
| 11 | 09:55 | 105.325 | 105.325 | 102.925 | 103.325 |
| 12 | 10:00 | 103.325 | 103.95 | 101.55 | 101.95 |
| 13 | 10:05 | 101.95 | 102.575 | 100.175 | 100.575 |
| 14 | 10:10 | 100.575 | 101.2 | 98.8 | 99.2 |
| 15 | 10:15 | 100.8 | 103.2 | 100.8 | 102.8 |
| 16 | 10:20 | 102.8 | 105.2 | 102.8 | 104.8 |
| 17 | 10:25 | 104.8 | 107.2 | 104.8 | 106.8 |
| 18 | 10:30 | 106.8 | 109.2 | 106.8 | 108.8 |
| 19 | 10:35 | 108.2 | 108.2 | 105.8 | 106.2 |
| 20 | 10:40 | 106.2 | 107.2 | 104.8 | 105.2 |

**Expected (per profile):**

- **BOS-P1 + RL:** bearish break @13 of SL6 100.8 (ref conf 8, close, UNCLASSIFIED); bullish break @17 of SH10 106.7 (ref conf 12, close, CHOCH_CANDIDATE)
- **BOS-P1 + RH (highest unbroken high):** bearish break @13 of SL6 100.8 (ref conf 8, close, UNCLASSIFIED)

**Expected non-events:** none listed

**Why:** Which confirmed swing is the reference changes the result (V4 audit B1: 52% of V4 BOS broke a lower high).

### BOS13: BOS at 21, then a close back below the level at 23.

- **Group:** bos_invalidation
- **Policy dependence:** BOS-007

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 101.2 | 103.2 | 100.8 | 102.8 |
| 1 | 09:05 | 102.2 | 102.2 | 99.8 | 100.2 |
| 2 | 09:10 | 100.2 | 101.2 | 98.8 | 99.2 |
| 3 | 09:15 | 100.3 | 102.7 | 100.3 | 102.3 |
| 4 | 09:20 | 102.3 | 104.2 | 101.8 | 103.8 |
| 5 | 09:25 | 103.8 | 105.7 | 103.3 | 105.3 |
| 6 | 09:30 | 105.3 | 107.2 | 104.8 | 106.8 |
| 7 | 09:35 | 106.45 | 106.45 | 104.05 | 104.45 |
| 8 | 09:40 | 104.45 | 105.7 | 103.3 | 103.7 |
| 9 | 09:45 | 103.7 | 104.95 | 102.55 | 102.95 |
| 10 | 09:50 | 102.95 | 104.2 | 101.8 | 102.2 |
| 11 | 09:55 | 103.3 | 105.7 | 103.3 | 105.3 |
| 12 | 10:00 | 105.3 | 107.2 | 104.8 | 106.8 |
| 13 | 10:05 | 106.8 | 108.7 | 106.3 | 108.3 |
| 14 | 10:10 | 108.3 | 110.2 | 107.8 | 109.8 |
| 15 | 10:15 | 109.2 | 109.2 | 106.8 | 107.2 |
| 16 | 10:20 | 107.2 | 108.2 | 105.8 | 106.2 |
| 17 | 10:25 | 106.2 | 107.2 | 104.8 | 105.2 |
| 18 | 10:30 | 105.2 | 106.2 | 103.8 | 104.2 |
| 19 | 10:35 | 104.8 | 107.2 | 104.8 | 106.8 |
| 20 | 10:40 | 106.8 | 108.2 | 105.8 | 107.8 |
| 21 | 10:45 | 107.8 | 110.9 | 107.6 | 110.7 |
| 22 | 10:50 | 110.7 | 110.9 | 110.0 | 110.3 |
| 23 | 10:55 | 110.3 | 110.5 | 109.4 | 109.7 |
| 24 | 11:00 | 109.7 | 110.0 | 109.0 | 109.3 |

**Expected (per profile):**

- **BOS-P1:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, close, BOS)
- **alt invalidation:** BOS stays (immutable); an optional separate INVALIDATION event at 23 referencing it

**Expected non-events:** the BOS at 21 must NOT disappear or move

**Why:** PDF section 3 replay contract + BOS-007.

### BOS14: One confirmed swing high only, then a close above it (no structure state).

- **Group:** bos_context
- **Policy dependence:** BOS-003

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 10.5 |
| 1 | 09:05 | 10.5 | 12 | 10 | 11.5 |
| 2 | 09:10 | 11.5 | 15 | 11 | 13 |
| 3 | 09:15 | 13 | 14 | 12 | 12.5 |
| 4 | 09:20 | 12.5 | 13 | 10 | 10.5 |
| 5 | 09:25 | 10.5 | 15.5 | 10.4 | 15.4 |
| 6 | 09:30 | 15.4 | 15.8 | 15.0 | 15.6 |

**Expected (per profile):**

- **SP-A:** SH2 (conf 4, 15, NONE); SL4 (conf 6, 10, NONE)
- **BOS-P1:** bullish break @5 of SH2 15 (ref conf 4, close, UNCLASSIFIED)

**Expected non-events:** must not be labelled BOS or CHoCH: insufficient context

**Why:** PDF section 6: return insufficient-context/unknown.

### BOS15: Floating point: reference high stored as 0.30000000000000004, close 0.3.

- **Group:** bos_precision
- **Policy dependence:** BOS-006, INV-PRECISION

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 0.2 | 0.22 | 0.18 | 0.21 |
| 1 | 09:05 | 0.21 | 0.25 | 0.2 | 0.24 |
| 2 | 09:10 | 0.24 | 0.30000000000000004 | 0.23 | 0.27 |
| 3 | 09:15 | 0.27 | 0.28 | 0.25 | 0.26 |
| 4 | 09:20 | 0.26 | 0.27 | 0.24 | 0.25 |
| 5 | 09:25 | 0.25 | 0.3 | 0.25 | 0.3 |
| 6 | 09:30 | 0.3 | 0.3 | 0.27 | 0.28 |

**Expected (per profile):**

- **raw float, any profile:** none
- **tick-rounded (0.01), BOS-P2 (>=):** bullish break @5 of SH2 0.3 (ref conf 4, close, UNCLASSIFIED)
- **tick-rounded, BOS-P1 (>):** none

**Expected non-events:** none listed

**Why:** PDF section 7 'Precision': tick-aware boundary tests.

### RB01: Duplicate timestamp at bar 2.

- **Group:** robustness
- **Policy dependence:** none

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 10.5 |
| 1 | 09:05 | 10.5 | 12 | 10 | 11.5 |
| 2 | 09:05 | 11.5 | 13 | 11 | 12.5 |

**Expected (per profile):**

- **loader:** REJECT (CandleError: timestamps must strictly increase)

**Expected non-events:** none listed

**Why:** PDF section 1: timestamps strictly increasing.

### RB02: Invalid OHLC: high below close at bar 1.

- **Group:** robustness
- **Policy dependence:** none

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 10 | 11 | 9 | 10.5 |
| 1 | 09:05 | 10.5 | 11.0 | 10 | 11.5 |
| 2 | 09:10 | 11.5 | 13 | 11 | 12.5 |

**Expected (per profile):**

- **loader:** REJECT (CandleError: inconsistent OHLC)

**Expected non-events:** none listed

**Why:** PDF section 1: H >= max(O,C).

### RB03: A 60-minute time gap between bars 3 and 4 inside a 2/2 window around a pivot at 3.

- **Group:** robustness
- **Policy dependence:** SW-002, INV-GAPS

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:00 | 8.95 | 10 | 8.5 | 9.55 |
| 1 | 09:05 | 9.55 | 11 | 9.5 | 10.55 |
| 2 | 09:10 | 10.55 | 12 | 10.5 | 11.55 |
| 3 | 09:15 | 13.5 | 15 | 13.5 | 14.55 |
| 4 | 10:15 | 13 | 13 | 11.5 | 11.95 |
| 5 | 10:20 | 11.95 | 12 | 10.5 | 10.95 |
| 6 | 10:25 | 10.95 | 11.5 | 10.0 | 10.45 |

**Expected (per profile):**

- **SP-A (window counts bars):** SH3 (conf 5, 15)
- **alt: window counts time / gap breaks window:** no swing or later confirmation

**Expected non-events:** none listed

**Why:** Missing bars: the window definition (bars vs time) must be declared.

### RB04: Unsorted input (bar 1 earlier than bar 0).

- **Group:** robustness
- **Policy dependence:** none

| i | time (UTC) | O | H | L | C |
|---|---|---|---|---|---|
| 0 | 09:05 | 10 | 11 | 9 | 10.5 |
| 1 | 09:00 | 10.5 | 12 | 10 | 11.5 |
| 2 | 09:10 | 11.5 | 13 | 11 | 12.5 |

**Expected (per profile):**

- **loader:** REJECT

**Expected non-events:** none listed

**Why:** Ordering invariant.

