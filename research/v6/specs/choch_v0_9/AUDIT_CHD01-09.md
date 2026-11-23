# Independent audit of CHD01–CHD09 (21 Nov 2026)

**Method**
- The audit script reads only the candles in `choch_fixtures.draft.json`.
- It finds swings with its own plain L2/R2 strict code. It does not use the scanner_v6 detector or `build_choch_drafts.py`.
- Each expectation was then judged by hand against approved A1–A10, the owner's decisions (BOS Option A, WICK_ONLY = rejected candidate) and O1–O9.
- Passing the builder script is **not** treated as proof.
- The independent swings match the draft's `expected_swings` in all 9 cases.

Candles are numbered from 1. "conf" is the candle at whose close a swing is confirmed (index + R).

| Case | Confirmed swings before the candidate candle | Structure evidence | Protected swing and why | Candidate candle vs protected | Expected → state | Depends on O1–O9? |
|---|---|---|---|---|---|---|
| CHD01 | H 109 (c7, conf c9), H 116 (c14, conf c16); L 98 (c4, conf c6), L 101 (c10, conf c12) | HH 116>109, HL 101>98 → BULLISH (A2, A4). 2H+2L first known at c16. | L 101 (c10): the **only** HL (A5). L 98 is the first low, so it is not an HL. | c18 close 100 < 101 (also > 98). c13–c17 closes 113 / 115 / 111 / 107 / 104 all stay above 101. | BULLISH → BEARISH_CHOCH → TRANSITION | **Yes: O1, O6, O3** (see finding F1, F2) |
| CHD02 | Mirror: L 91 (c7, conf c9), L 84 (c14, conf c16); H 102 (c4, conf c6), H 99 (c10, conf c12) | LL 84<91, LH 99<102 → BEARISH | H 99 (c10): the only LH | c18 close 100 > 99 (< 102). c13–c17 closes all stay below 99. | BEARISH → BULLISH_CHOCH → TRANSITION | **Yes: O1, O6, O3** |
| CHD03 | As in CHD01 | BULLISH | Field set to L 101 (only HL) | c18 low 100 < 101, close 102 > 101: wick only | BULLISH → NO_CHOCH (WICK_ONLY) → BULLISH | The event does not depend on O1–O9: no close beyond any low. **The `protected_swing_id` field depends on O1.** |
| CHD04 | As in CHD02 | BEARISH | Field set to H 99 | c18 high 100 > 99, close 98 < 99: wick only | BEARISH → NO_CHOCH (WICK_ONLY) → BEARISH | As CHD03 |
| CHD05 | As in CHD01 (L 106 at c16 confirms only at c18, so it is not yet known) | BULLISH | None needed | c18 close 117 > H 116: a with-direction break (BOS under Option A), not counter-direction | BULLISH → NO_CHOCH → BULLISH | No |
| CHD06 | As in CHD02 | BEARISH | None needed | c18 close 83 < L 84: with-direction BOS | BEARISH → NO_CHOCH → BEARISH | No |
| CHD07 | H 109 (c3, conf c5), H 116 (c10, conf c12); L 101 (c6, conf c8) | Only 1 low → A4 minimum not met → UNKNOWN (A3) | None. The spec forbids inventing one. | c14 close 100 < 101: a BOS under Option A, but no structure to change | UNKNOWN → NO_CHOCH → UNKNOWN | No. One low is too few under any chronology (O9) |
| CHD08 | None (equal highs 105 and equal lows 99 are not swings) | UNKNOWN | None | No candidate candle | UNKNOWN → NO_CHOCH on every candle | No |
| CHD09 | H 127 (c4, conf c6), H 126 (c8, conf c10); L 117 (c10, conf c12). H 123 (c12) confirms only at c14. | Only 1 low → UNKNOWN | None | c13 close 116 < 117: the approved BOS stays, but it is not a CHoCH | UNKNOWN → NO_CHOCH → UNKNOWN | No |

## Findings: expectations not fully supported by approved rules

- **F1 (CHD01, CHD02): the protected swing rests on O1 and O6.**
  - A5 says the protected level is a *qualifying* HL, and what "qualifying" means is open (O1).
  - "Only one HL exists" leaves at most one candidate. It does not prove that this candidate qualifies.
  - The HL 101 is confirmed at the close of **c12**. That is the **same candle** whose close (110) breaks above H 109.
  - A lifecycle rule that requires the HL to be confirmed before the BOS that validates it would reject 101. With no protected swing left, c18 would be NO_CHOCH.
  - So the BEARISH_CHOCH (and the mirror BULLISH_CHOCH) is **not fully supported**.
  - **Proposed fix, not applied:** redraw the data so that the HL is confirmed at least one candle before the validating BOS. That removes the O6 coincidence, but O1 stays.
- **F2 (CHD01, CHD02): the state after the event rests on O3 and O6.**
  - c18 is both the CHoCH and a with-direction bearish BOS under Option A (reference L 101).
  - TRANSITION follows from A7 ("do not immediately declare a full reversal").
  - Whether a BOS on the same candle can count as the confirming new-direction BOS is O3 / O6.
  - The A7 reading is the stronger one, but it is not locked.
- **F3 (CHD03, CHD04): one field rests on O1.**
  - The NO_CHOCH event is fully supported.
  - The `protected_swing_id` (101 / 99) rests on O1.
  - **Proposed:** mark that field as "candidate, O1-dependent", or score only event, basis and state.
- **F4 (CHD01–CHD06): the state before the candidate candle has a minor O9 exposure.**
  - BULLISH / BEARISH follows from A2 + A4. With exactly 2 highs and 2 lows there is only one pair to compare.
  - O9 could still add a precondition, for example an ordering requirement.
  - Exposure is low.
- **Not exercised:**
  - O7: all series are contiguous 5-minute candles with no gaps.
  - O8: no event id is asserted; only stable swing ids are used.
  - O2: no continuation association is scored.
  - O4 and O5: those cases are unscored.

**Fully supported:** CHD05–CHD09, plus the event / basis / state of CHD03–CHD04.
**Not fully supported:** CHD01, CHD02 (F1, F2), and the `protected_swing_id` field of CHD03 and CHD04 (F3).

## Unscored cases: link to O1–O9

| Case | Open decision(s) |
|---|---|
| CHU01 | O4 |
| CHU02 | O5, O6 |
| CHU03 | O1, O2 |
| CHU04 | **None of O1–O9.** Is "close beyond" strict for CHoCH? This needs an owner decision. |
| CHU05 | O9; also mixed HH+LL classification, which is not named in O1–O9 |
| CHU06 | O3, O8; also BOS reading C3, which is a BOS question outside O1–O9 |
