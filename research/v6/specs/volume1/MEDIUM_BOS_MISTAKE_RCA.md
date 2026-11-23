# Medium-level BOS mistakes: root cause and correction (21 Nov 2026)

**Status:** no approved rule changed. Profile (unchanged):
- L2/R2 swings, strict comparison
- equal highs / lows are NOT swings
- BOS = a candle CLOSE beyond the latest confirmed swing
- wick-only is not BOS
- one BOS per reference swing id

## The two mistakes

| Case | Reported (wrong) | Correct |
|---|---|---|
| A: Medium Chart 1 | Bullish BOS at candle 11, reference 105 (candles 3 and 4) | **NO BOS.** 105 is an equal high (candle 3 high 105 = candle 4 high 105), so it is not a swing. Lows 99 at candles 5 and 6 are also an equal pair. The chart has no confirmed swing, so there is no BOS reference at all. |
| B: Medium Chart 2 | Bearish BOS at candle 9, reference 120 (candles 5 and 6) | **Not a BOS.** 120 is an equal low (candle 5 low 120 = candle 6 low 120), so it is not a swing. The **only** BOS is bearish at **candle 13** (close 116) below swing low **117** (candle 10, confirmed at candle 12). |

## Root cause: which layer failed

| Layer | Finding | Evidence |
|---|---|---|
| **Swing detector (code)** | **Not the cause.** `detect_swings` returned no swing for Chart 1 and listed 105 / 99 as `unresolved_equal_levels`. For Chart 2 it returned no swing at 120 and listed 120 as an equal level. | The first run in the session printed `Chart 1 swings: []`, with equal levels high 105 (candles 3, 4) and low 99 (5, 6). Chart 2 swings were SH4, SH8, SL10, SH12, with equal low 120 (5, 6). |
| **Strict comparison** | **Not the cause.** `_beats()` uses `>` / `<`. A tie goes to the diagnostics list, never to a swing. | `scanner_v6/structure/swings.py`; mutation test M1 (inclusive comparison) fails the fixtures. |
| **BOS reference selection** | **Not the cause in code.** There is no V6 BOS module. The scratch BOS check took its references only from detector swings, and it reported Chart 1 = no BOS and Chart 2 = candle 13 only, which is correct. | First exam answer: "Chart 1: no BOS; Chart 2: candle 13; Chart 3: candle 11". |
| **Fallback promoting an equal level** | **This was the cause, applied by hand.** For the second marking pass, the BOS list was **typed by hand** (`(3, 105, 11)`, `(5, 120, 9)`) under an unapproved "ties allowed (first of tie)" reading. The same reading had been offered earlier only as a labelled "not approved" alternative. | Scratch `draw.py`: hard-coded `BOS = {"chart1": [(3, 105, 11, "bull")], "chart2": [(5, 120, 9, "bear"), (10, 117, 13, "bear")], ...}` |
| **Visual reasoning** | The obvious resistance at 105 and support at 120 (a double top / bottom) was treated as "the" swing level. A visually clear support or resistance level is **not** a confirmed swing under strict comparison. | — |
| **Instruction following** | **Primary root cause.** The feedback was "BOS sahi, swing galat". It was read as permission to relax the approved strict rule so that more levels would qualify. The approved rule should have been held, and the feedback should have been questioned against it. That is answer-drift under feedback, not a detector defect. | Conversation history |
| **Evaluation harness** | **Gap.** No regression fixture existed for the exam charts, and the marking script did not take its BOS list from the detector. So nothing stopped a hand-typed answer that contradicted the detector. | — |

## Training / instruction changes (in force from now)

1. **Every marked answer comes from the detector output**, never from a hand-typed list. The marking script must take its swing references from `detect_swings()` and its breaks from the approved BOS rules (`approved_bos` in the regression test, until `bos.py` is approved).
2. **Equal high / low:** report it as `unresolved equal level (not a swing, not a BOS reference)`. Never promote it, even if it is the visually obvious support or resistance.
3. **Feedback does not change a rule.** If feedback seems to contradict an approved rule, keep the rule-based answer and ask which candle is wrong.
4. **Alternative readings are shown only as alternatives.** They are never drawn on a chart as the answer.
5. **New exam charts become fixtures.** Before marking a new set, run the existing regression fixtures. After a correction, add the charts as fixtures with exact reference ids, prices and break candles.

## Coverage added

- `tests/scanner_v6/fixtures/regression/easy_bos.json` (renamed 22 Nov 2026 from `medium_bos.json`, audit D-4: the charts were Easy Charts 1 and 2): EASY01 and EASY02 (formerly MED01 / MED02). Exact OHLC, candle numbers 1–14, expected swings, equal levels, expected BOS, and the rejected mistake with its reason.
- `tests/scanner_v6/test_regression_medium_bos.py`: 6 tests.
  - The swing detector, batch and streaming, replay-audited.
  - The equal levels are rejected.
  - No BOS in MED01; exactly the candle 13 / 117 BOS in MED02, compared by reference id, price, break candle and close, batch equal to streaming.
  - The two BOS-001 readings agree on these fixtures.
  - The mistake reproduced as code (an equal level promoted to a swing) gives candle 11 / 105 and candle 9 / 120, and the expectations reject it.
- **Blind retest:** `research/v6/experiments/medium_bos_retest.py`.
  - Unmarked charts in `research/v6/retest/medium/`.
  - The answer key is kept apart in `research/v6/retest/answer_keys/`.
  - The grader reads candles from the PNG pixels only, runs the detector and the approved BOS rules, and only then opens the key.
