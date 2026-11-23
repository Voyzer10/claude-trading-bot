# V6 BOS + CHoCH: Phase 1 audit, Phase 2 decisions and approval register

**Revision 2, 22 Nov 2026: owner decisions recorded.** Revision 1 (the proposals) is preserved in §9.

**Not all CHoCH rules are final.** O4, O7, O8, O9, CHU04 and CHU05 remain **unresolved**, and nothing here decides them.

**Conventions:** candles are 1-based. "conf cN" means the swing is confirmed at the close of candle N (index + R, with R = 2). Every example was checked with the approved swing detector and the approved BOS rules.

## 0. Owner decisions of 22 Nov 2026 (exact)

**APPROVED**
- **D1:** CHoCH → TRANSITION → a separate, subsequent BOS in the new direction confirms the reversal. A same-candle BOS cannot confirm the reversal.
- **D2:** Adopt P-B, clarified as follows. A BOS-origin swing becomes protected only after its L2/R2 confirmation. Until then, the previous valid protected swing is retained.
- **D4:** Keep the existing reference rule: the latest eligible confirmed swing. The latest-unbroken (C3) alternative is not implemented.
- **D5:** Order within a candle is BOS evaluation → CHoCH evaluation using the pre-candle state → state update → swing confirmation. A swing confirmed on candle k cannot be used for BOS or CHoCH evaluation on candle k.
- Add both a bullish and a bearish CHoCH → TRANSITION → subsequent BOS reversal fixture.

**D3: CONDITIONAL APPROVAL WITH MODIFICATION**
- Use X1 when one protected level is clearly responsible for the CHoCH and the other crossed levels are non-protected evidence.
- If several competing protected or structural levels make the event direction or classification genuinely ambiguous, emit COMPLEX_STRUCTURE_BREAK.
- Never force an ambiguous case into a bullish or bearish CHoCH.
- Keep the previously accepted complex-break concept.

**Kept unresolved:** O4, O7, O8, O9, CHU04, CHU05.

## 1. Approval register

### 1.1 Previously approved (unchanged)

| ID | Rule | Approved |
|---|---|---|
| SW | Swings: L2/R2 fixed window, strict comparison. Equal highs / lows are not swings. Dual pivots allowed. Confirmed at index + R. | 21 Nov |
| BOS-001…005 | Reference = the latest eligible confirmed swing. A close strictly beyond it. Emitted at the close of the break candle. One BOS per reference id. | 21 Nov |
| Option A | BOS is independent of structure direction. A continuation BOS needs no CHoCH. | 21 Nov |
| WICK | Wick-only gives NO_CHOCH with basis WICK_ONLY (a rejected candidate, not an event) | 21 Nov |
| A1–A10 | External structure only; HH + HL / LH + LL; UNKNOWN when there is too little; at least 2 highs + 2 lows; protected = a qualifying HL / LH; CHoCH by close; TRANSITION; transition lock; the failed-CHoCH concept; the complex-break concept | Spec v0.9 |

### 1.2 Newly approved on 22 Nov 2026

| ID | Rule (as implemented) | Status |
|---|---|---|
| **D1** | After a CHoCH at candle k the state is TRANSITION(dir). A BOS in direction dir at a candle j > k confirms the reversal: the state becomes dir. A BOS at k itself never confirms it. A8 still holds: no CHoCH while the state is TRANSITION. After confirmation, the protected swing is the origin of the confirming BOS (D2). | APPROVED |
| **D2** | P-B. The origin of a bullish BOS at k against swing high SH_r is the lowest confirmed swing low with index in (SH_r.index, k]. The bearish case is the mirror. It must be an HL (LH) compared with the previous confirmed swing low (high), per A5. It becomes protected **only at its own L2/R2 confirmation**. Until then the previous valid protected swing is kept. A later qualifying BOS origin replaces it. A close beyond it consumes it (one CHoCH per protected id). A leg with no confirmed swing leaves the protected swing unchanged. | APPROVED |
| **D3** | **X1:** exactly one protected level is crossed by the close, so emit one CHoCH against it and record the other levels crossed on that candle as `levels_crossed` evidence. **COMPLEX_STRUCTURE_BREAK:** more than one competing protected level would be responsible. It is never forced into a bullish or bearish CHoCH. | APPROVED (modified) |
| **D4** | BOS reference = the latest confirmed swing of that kind. Once it is used there is no BOS of that kind until a new swing confirms. No fallback to older unbroken swings. | APPROVED |
| **D5** | At the close of candle k: (1) BOS from swings confirmed at or before k − 1; (2) CHoCH against the state and protected level as of k − 1; (3) state update; (4) swings confirmed at k are applied: P-B activation, and structure establishment by A2/A4. These take effect from candle k + 1. | APPROVED |
| FIX | Reversal fixtures CHD10 (bearish) and CHD11 (bullish) | APPROVED |

### 1.3 Still unresolved (not implemented as rules)

| ID | Open question | What the implementation does |
|---|---|---|
| O4 | Failed-CHoCH sequencing. Also: what an old-direction BOS during TRANSITION does. | **No event and no state change.** A diagnostic `O4_UNRESOLVED` is recorded. |
| O5 (residual) | The state **after** a COMPLEX_STRUCTURE_BREAK is not specified | It cannot occur with one protected level per direction. The guard sets the state to UNKNOWN and records the reason `O5_STATE_AFTER_COMPLEX_UNRESOLVED`. |
| O7 | History / session gaps | Candles are counted as given. No gap logic. |
| O8 | Duplicates, invalidation, stable event ids | Ids are deterministic (`choch:<dir>:<protected swing id>`, `state:<k>:<from>-><to>`). Invalidation is not modelled. |
| O9 | Initial structure chronology | The structure is established at the first candle close where the latest two confirmed highs and the latest two confirmed lows are HH + HL (or LH + LL). A diagnostic `O9_UNRESOLVED` is recorded when, at that moment, a close has already crossed the protected level. |
| CHU04 | Is a CHoCH close strictly beyond the level? | The implementation uses strict (the same as BOS). The case stays unscored until the owner decides. |
| CHU05 | Mixed HH + LL classification | The structure stays UNKNOWN (A3 default). Unscored. |
| A1 note | "External" has no executable definition | Every L2/R2 swing is treated as external. |

## 2. Phase 1 audit findings (unchanged from revision 1)

| # | Finding |
|---|---|
| F1 | Every protected HL in the pack confirms on the same candle as its BOS or one candle later, never before (the R = 2 delay). |
| F2 | 5 of the 9 C3 "latest unbroken" BOS would be emitted late (Medium 1 c21, Medium 2 c14, Hard 1 c17, Hard 2 c14, Extreme 1 c17). This is why D4 was approved. |
| F3 | No reversal confirmation exists in the pack: no swing forms after any CHoCH. Hence fixtures CHD10 and CHD11. |
| F4 | In the multi-level breaks of Hard 1 and Extreme 1, the extra level is the structure's first low, which is not protected. That is the X1 case. |
| F5 | Equal levels can leave a BOS leg without an origin swing (Medium 3 c16). |

## 3. D1: reversal, candle by candle

### 3.1 Bearish reversal (fixture CHD10)

Candles c1–c17 are the CHD01 data, then c18–c24 are added. A first draft of c20 / c21 closed back above 101 (an O4 case). The detector flagged it with O4_UNRESOLVED, so the candles were redrawn.

| Candle | O / H / L / C | (1) BOS | (2) CHoCH (pre-candle state) | (3) State after | (4) Swings confirmed at this close |
|---|---|---|---|---|---|
| c6 | | | | UNKNOWN | L 98 (c4) |
| c9 | | | | UNKNOWN | H 109 (c7) |
| c12 | 106/111/105/110 | **↑ BOS** against H 109; origin = L 101 (c10), not yet confirmed | – | UNKNOWN | L 101 (c10) confirms; it is an HL vs 98, so it is the active origin of BOS c12 |
| c16 | 111/112/106/107 | – | – | UNKNOWN | H 116 (c14). Highs 109 → 116 (HH), lows 98 → 101 (HL), so the state becomes **BULLISH** from c17, **protected low 101** |
| c18 | 104/105/99/100 | **↓ BOS** against L 101 (Option A) | Pre-state BULLISH, protected 101, close 100 < 101 → **BEARISH CHoCH** | **TRANSITION(bearish)**. The ↓ BOS on c18 does **not** confirm (same candle). | – |
| c19 | 100/101/97/98 | none: L 101 is used, and the older L 98 is not a reference (D4) | locked (A8) | TRANSITION | – |
| c20 | 98/100.5/97.5/100 | – | locked | TRANSITION | – |
| c21 | 100/103/99.5/100.5 | – | locked | TRANSITION | L 97 (c19). Note: no close after c18 returns above 101, so CHD10 does not depend on O4 (failed CHoCH). |
| c22 | 100.5/102.5/99/99.5 | – | locked | TRANSITION | – |
| c23 | 99.5/100/98/98.5 | – | locked | TRANSITION | H 103 (c21) |
| c24 | 98.5/99/95/96 | **↓ BOS** against L 97 (c19) | locked | **BEARISH (reversal confirmed)**. Protected high = 103, the origin of BOS c24 (confirmed at c23, before c24, so active at once). | – |

### 3.2 Bullish reversal (fixture CHD11)

This is the mirror of CHD10 (each price p becomes 200 − p).
- c18 closes 100 > protected LH 99 → **BULLISH CHoCH** → TRANSITION. The bullish BOS on c18 does not confirm.
- Swing high 103 (c19) confirms at c21, then swing low 97 (c21) at c23.
- c24 closes 104 > 103 → bullish BOS → **BULLISH confirmed**, with protected low 97.

## 4. D2: P-B activation timing, candle by candle

Fixture CHD16 (synthetic). c1–c14 are as in CHD01; then c15 115/115/110/111, c16 111/112/106/107, c17 107/117/107/116.5, c18 116.5/118/112/117, c19 117/117.5/110/111, c20 111/112/104/105.

| Candle | Event | Protected low **in force for the next candle** |
|---|---|---|
| c12 | ↑ BOS against 109. Origin L 101 (c10) confirms at the close of c12. | 101 (structure still UNKNOWN) |
| c16 | H 116 confirms, so the state becomes BULLISH | 101 |
| c17 | ↑ BOS against 116 (close 116.5). Origin = the lowest swing low in (c14, c17]; that is L 106 (c16), which is **not confirmed yet** | **101 (kept)** |
| c18 | L 106 confirms. It is an HL vs 101, so it is activated by the close of c18. | **106** |
| c19 | close 111 | 106 |
| c20 | close 105 < 106 → **BEARISH CHoCH** against 106 (101 is not crossed). Also a ↓ BOS against 106. The swing high 118 (c18) that confirms at c20 is not used on c20 (D5). | TRANSITION |

**What if c17 or c18 had closed below 101?** Then the CHoCH would be against 101, because 106 was not yet confirmed. A protected swing is never used before its confirmation.

## 5. D3: complex breaks

**X1, bearish example (fixture CHD12, formerly CHU02).** CHD01 c1–c17, then c18 104/105/96/97.
- Pre-state BULLISH, protected 101.
- Close 97 < 101 (protected) and < 98 (L c4, not protected).
- Result: **BEARISH CHoCH** against 101 with `levels_crossed` = [98], plus a ↓ BOS against 101. The state becomes TRANSITION.

**X1, bullish example.** The mirror: close 103 > protected LH 99 and > 102 → BULLISH CHoCH with `levels_crossed` = [102].

**COMPLEX_STRUCTURE_BREAK:**
- Emitted when the close crosses **more than one protected / competing structural level**, so that responsibility or direction is ambiguous.
- Under D2 there is at most one active protected level per direction, and only in the matching state. A single close cannot be beyond levels on both sides.
- So **no valid contiguous OHLC sequence reaches COMPLEX under the approved rules.**
- The guard is implemented and unit-tested directly, so an ambiguous case can never be forced into a CHoCH. The state after COMPLEX stays an open O5 item (§1.3).

## 6. D4: BOS reference, pack examples

| Chart | Approved (latest confirmed) | Not implemented (latest unbroken) |
|---|---|---|
| Medium 1 | ↓ c19 against 108.74 only | would add c20 (106.81) and c21 (105.02, crossed at c20, so late) |
| Hard 1 | ↓ c16 against 310.41 | would add c17 (307.47, crossed at c16, late) |
| Extreme 1 | ↓ c16 against 714.92 | would add c17 (711.19, late) |
| Synthetic CHD14 (formerly CHU06) | c19 close 97 < 98 (older L c4): **no BOS**, because L 101 is the latest and is already used | would be a BOS and would confirm the reversal |

**Pack BOS count:** 28. The 9 C3-only candidates are not events.

## 7. D5: same-candle order, worked examples

1. **CHD10 c18:** (1) ↓ BOS against 101; (2) CHoCH against 101 using the pre-candle BULLISH state; (3) TRANSITION. The c18 BOS cannot confirm, because confirmation needs the pre-state to be TRANSITION already.
2. **Structure not yet established (fixture CHD15).** CHD01 c1–c14, then c15 115/115/110/111, c16 111/112/99/100.
   - At c16, H 116 confirms, and close 100 < 101.
   - Step (2) uses the pre-candle state, which is UNKNOWN (only one high was known before c16), so there is **no CHoCH on c16**.
   - Step (4) then establishes BULLISH for c17 onward, with diagnostic `O9_UNRESOLVED` (the close is already below protected 101).
   - What happens at c17 and later is O9 and is **not scored**.
3. **D2 example c20:** swing high 118 confirms at the close of c20 and is not used on c20.

## 8. Fixture changes made under these decisions

| Fixture | Before | After |
|---|---|---|
| CHD01–CHD04 | PARTIAL (O1, O6 / O3) | SUPPORTED: D2 (protected 101 = origin of BOS c12, confirmed at c12) and D5 |
| CHD10, CHD11 | – | New: bearish and bullish full reversal (D1) |
| CHD12 | CHU02 (unscored: O5, O6) | Decidable under D3 X1 + D5 |
| CHD13 | CHU03 (unscored: O1, O2) | Decidable under D2: CHoCH c20 against 106 |
| CHD14 | CHU06 (unscored: O3, O8) | Decidable under D1 + D4: no BOS at c19, so TRANSITION is kept |
| CHD15 | – | New: D5 same-candle swing confirmation |
| CHD16 | – | New: P-B origin confirming one candle after its BOS (§4) |
| CHU01, CHU04, CHU05 | unscored | **still unscored** (O4, CHU04, O9 / CHU05) |

## 9. Revision 1 (22 Nov 2026, before approval): proposals and alternatives

These were the options shown for review:
- D2: P-A latest HL, P-B BOS origin, P-C confirmed at or before the BOS, P-D strictly before.
- D3: X1, X2, X3.
- D4: (a) latest confirmed, (b) latest unbroken, (b2) every unbroken level crossed.

**Effect on the pack:**
- P-C gives 1 CHoCH; P-D gives 0.
- X2 makes Hard 1 and Extreme 1 c16 COMPLEX.
- (b) gives 37 BOS, 5 of them late; (b2) gives 38.

The owner chose P-B, X1 with the COMPLEX guard, and (a).
