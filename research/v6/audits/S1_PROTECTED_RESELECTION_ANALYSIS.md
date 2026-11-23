# S-1: protected swing re-selection inside one BOS leg (analysis only)

Status: **OPEN SPEC GAP. Nothing in the code was changed.** Prepared 22 Nov 2026 in Phase 2 (controlled defect fixes) for
an owner decision. Source: `V6_BOS_CHOCH_CODE_AUDIT.md` §10.

## 1. The rule as approved

D2 (P-B), PHASE1_2_DECISIONS.md:
- The protected swing is the swing that **originated** the latest continuation BOS: for a bullish BOS, the swing low the
  break leg started from.
- That swing becomes protected only after its own L2/R2 confirmation. Until then the previous protected swing stays in
  force.
- A5: the origin must be an HL (bullish) or an LH (bearish) to qualify.

The text does not say what happens when a **second, lower** swing low in the same leg confirms **after** the first one
was already activated.

## 2. Current behaviour (`protected_levels.py`, unchanged)

`ProtectedTracker` evaluates the origin of each BOS as the lowest (bullish) / highest (bearish) confirmed opposite swing
in `(reference.index, k]`. It does this whenever a swing confirms:
- If the candidate is qualified (A5) and confirmed, it is activated.
- If a later, lower candidate appears and is **not** qualified, the tracker logs `NOT_QUALIFIED` and **keeps the swing
  already activated**.

The outcome therefore depends on the order in which the two lows confirm.

## 3. Candle-by-candle example (bullish; the bearish mirror p → 200 − p gives the same events)

Candles c1–c16 are CHD01's first 16 candles. c17–c22 are added. Columns: O / H / L / C.

| c | O | H | L | C | What happens (current code) |
|---|---|---|---|---|---|
| 1–3 | 104 / 103 / 102 | 105 / 104 / 103 | 102 / 101 / 100 | 103 / 102 / 101 | down leg |
| 4 | 101 | 102 | **98** | 99 | swing low 98 (confirmed c6) |
| 7 | 105 | **109** | 104 | 108 | swing high 109 (confirmed c9) |
| 10 | 103 | 104 | **101** | 102 | swing low 101 (confirmed c12) |
| 12 | 106 | 111 | 105 | 110 | **BOS bullish** over 109; origin 101 (HL vs 98) |
| 14 | 113 | **116** | 112 | 115 | swing high 116 (confirmed c16) |
| 16 | 111 | 112 | **106** | 107 | swing low 106 (confirmed c18). c16: **ESTABLISHED BULLISH**, protected 101 |
| 17 | 107.5 | 110 | 107.5 | 109 | – |
| 18 | 109 | 111 | 108 | 110 | 106 confirms |
| 19 | 110 | 117 | **104** | 116.5 | **BOS bullish** over 116. Origin in (c14, c19] = 106 (the only confirmed low): qualified HL vs 101 → **106 activated** (in force from c19). The c19 low 104 is not yet a swing. |
| 20 | 116.5 | 118 | 104.5 | 117 | low 104.5 under 106 but close 117: `WICK_ONLY` |
| 21 | 117 | 119 | 106 | 118 | swing low **104 (c19) confirms**. It is now the lowest low of the leg, but 104 < 106, so it is **not an HL** (A5) → `NOT_QUALIFIED`; **106 stays protected** |
| 22 | 118 | 118.5 | 105 | **105.5** | close 105.5 < 106 → **CHoCH bearish**, state TRANSITION(bearish) |

Measured output (run in Phase 2, current code):
- BOS: (bullish, c12, 109), (bullish, c19, 116).
- Events: ESTABLISHED BULLISH c16; CHoCHBreak c22 at 106; state TRANSITION(bearish) c22.
- Protected in force: 101 (c16–c18), 106 (c19–c21).
- Mirror: identical events, with BEARISH and TRANSITION(bullish), at 94.

## 4. The literal alternative

Reading D2 literally:
- "origin = the lowest swing of the leg" → **104**.
- 104 is not an HL relative to the previous low 106 → **A5 fails** → "no qualified origin → previous protected
  unchanged".

What "previous" means splits the alternative into two variants:

| Variant | Protected after c21 | c22 (close 105.5) |
|---|---|---|
| **L-a** "previous" = the protected swing before this BOS's origin was activated = **101** (106 is withdrawn because it is no longer the leg's origin) | 101 | no CHoCH (105.5 > 101) |
| **L-b** "previous" = whatever is in force now = 106 | 106 | CHoCH (same as current code) |

The audit's "literal reading → no CHoCH" refers to **L-a**.

## 5. Should the later lower low replace 106?

| Argument | Supports |
|---|---|
| D2 says the protected swing is "the" origin of the BOS leg; after c21 the true origin of the c19 leg is 104, not 106 | replacing or withdrawing 106 (L-a) |
| A5 is meant to protect only an HL; 104 is below 106, so structurally the leg made a lower low before breaking. Treating 106 as protected then ignores a lower low that already happened. | L-a |
| No look-ahead: at c19, 104 is not yet a swing. 106 was the correct, causally known origin at c19. Withdrawing it at c21 changes a level that was already in force: a kind of retroactive revision, though not repainting of past events. | current (keep 106) |
| Stability: a protected level that can be withdrawn later is harder to trade or explain; the current code never downgrades a level that is in force | current |
| 104 was formed on the BOS candle itself (c19 wicked to 104 and closed 116.5). Whether a low on the break candle counts as part of the leg "before" the break is itself undefined. | open, either way |

**Neither reading is derivable from the approved text.** This is an owner decision. Options:
1. Keep the current behaviour and approve it explicitly.
2. Adopt L-a: withdraw and fall back to the previous protected swing.
3. Adopt "the later lower low replaces 106 if it qualifies against the swing before 106": this would make 104 vs 101
   qualify, so 104 becomes protected.
4. Exclude lows formed on the break candle itself from origin selection.

## 6. Expected impact on CHoCH events

| Rule | c22 in this example | General effect |
|---|---|---|
| Current | CHoCH at 106 | earlier CHoCH (the higher level is kept) |
| L-a | none (protected back to 101) | fewer and later CHoCH; more candles without an active near level |
| Option 3 (104 replaces) | none (105.5 > 104) | CHoCH only below 104 |
| Option 4 | depends on the next confirmed low | origin never comes from the break candle |

The frequency of this pattern on real data is **unknown**. It is measured as metric M7 in the R-1 plan
(`R1_REAL_MARKET_EVALUATION_PLAN.md`).

**No code, fixture or test was changed for S-1.** Fixture CHD-S1 (the c1–c22 candles above, in both directions) should
be added only after the decision, with the approved expected result.
