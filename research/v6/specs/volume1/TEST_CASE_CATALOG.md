# TEST CASE CATALOG: V6 Volume 1

**Nothing in this catalog has been run against a V6 detector.** None exists yet; implementation awaits approval.

**Status column:**
- **NOT RUN:** designed, waiting for an implementation.
- **EXECUTED:** run during this analysis against existing code or the scratch checker; the result is given.
- **Actual output** is empty until it is run against the V6 detector.

## A. Fixture-driven tests (one per case per profile)

| Test id | Category | Input | Expected | Actual | Status | Explanation |
|---|---|---|---|---|---|---|
| T-SW01-1 | unit | `SW01` | **SP-A:** SH2 (conf 4, 15) |  | NOT RUN | PDF p4: 'swing high at i=2, confirmed at i=4. No confirmed swing low in this truncated sample.' |
| T-SW02-1 | unit | `SW02` | **SP-A:** SH2 (conf 4, 15); SL7 (conf 9, 6) |  | NOT RUN | PDF p4: 'Append two later bars with lows above 6.0 to test confirmation of i=7.' |
| T-SW03-1 | unit | `SW03` | **SP-A:** SL2 (conf 4, 5) |  | NOT RUN | High/low symmetry: same indices as SW01 with kinds swapped. |
| T-SW04-1 | boundary | `SW04` | **SP-A:** none |  | NOT RUN | Strict > rejects ties (PDF 2.B). The outcome depends on the tie policy; cluster policy would give ONE cluster {2,3} confirmed at 5. |
| T-SW04-2 | boundary | `SW04` | **SP-B:** SH2 (conf 4, 14) |  | NOT RUN | Strict > rejects ties (PDF 2.B). The outcome depends on the tie policy; cluster policy would give ONE cluster {2,3} confirmed at 5. |
| T-SW04-3 | boundary | `SW04` | **SP-C:** SH3 (conf 5, 14) |  | NOT RUN | Strict > rejects ties (PDF 2.B). The outcome depends on the tie policy; cluster policy would give ONE cluster {2,3} confirmed at 5. |
| T-SW04-4 | boundary | `SW04` | **SP-D:** SH2 (conf 4, 14); SH3 (conf 5, 14) |  | NOT RUN | Strict > rejects ties (PDF 2.B). The outcome depends on the tie policy; cluster policy would give ONE cluster {2,3} confirmed at 5. |
| T-SW05-1 | boundary | `SW05` | **SP-A:** SH2 (conf 4, 14, NONE); SL4 (conf 6, 10.5, NONE); SH6 (conf 8, 14, EH) |  | NOT RUN | Each peak is a strict pivot in its own window. The second high equals the first: HH/LH label undefined (EH). |
| T-SW06-1 | boundary | `SW06` | **SP-A:** none |  | NOT RUN | Mirror of SW04. |
| T-SW06-2 | boundary | `SW06` | **SP-B:** SL2 (conf 4, 6) |  | NOT RUN | Mirror of SW04. |
| T-SW06-3 | boundary | `SW06` | **SP-C:** SL3 (conf 5, 6) |  | NOT RUN | Mirror of SW04. |
| T-SW06-4 | boundary | `SW06` | **SP-D:** SL2 (conf 4, 6); SL3 (conf 5, 6) |  | NOT RUN | Mirror of SW04. |
| T-SW07-1 | boundary | `SW07` | **SP-A:** SH2 (conf 4, 14) |  | NOT RUN | Under raw-price strict comparison the 1-tick-higher bar is the pivot. A tolerance of >=1 tick turns this into a tie case. |
| T-SW07-2 | boundary | `SW07` | **SP-A + tolerance >= 1 tick:** same as SW04 (treated as equal) |  | NOT RUN | Under raw-price strict comparison the 1-tick-higher bar is the pivot. A tolerance of >=1 tick turns this into a tie case. |
| T-SW08-1 | unit | `SW08` | **SP-A:** none |  | NOT RUN | PDF E2 / end-of-dataset: insufficient right-side evidence -> unconfirmed. Must not be forced. |
| T-SW08-2 | unit | `SW08` | **SP-H (R=1):** SH3 (conf 4, 14) |  | NOT RUN | PDF E2 / end-of-dataset: insufficient right-side evidence -> unconfirmed. Must not be forced. |
| T-SW09-1 | boundary | `SW09` | **SP-A (both allowed):** SH2 (conf 4, 13); SL2 (conf 4, 8) |  | NOT RUN | PDF 7: outside bar -> allow both, reject both, or tie-break. |
| T-SW09-2 | boundary | `SW09` | **alt: reject both:** none |  | NOT RUN | PDF 7: outside bar -> allow both, reject both, or tie-break. |
| T-SW09-3 | boundary | `SW09` | **alt: tie-break:** one of H2 / L2 |  | NOT RUN | PDF 7: outside bar -> allow both, reject both, or tie-break. |
| T-SW10-1 | unit | `SW10` | **SP-A:** SH5 (conf 7, 12, NONE); SL7 (conf 9, 10, NONE); SH10 (conf 12, 15, HH) |  | NOT RUN | Different windows give different structure; with 5/5 only the external top exists and it confirms 3 bars later. |
| T-SW10-2 | unit | `SW10` | **SP-F (3/3):** SL7 (conf 10, 10); SH10 (conf 13, 15) |  | NOT RUN | Different windows give different structure; with 5/5 only the external top exists and it confirms 3 bars later. |
| T-SW10-3 | unit | `SW10` | **SP-E (5/5):** SH10 (conf 15, 15) |  | NOT RUN | Different windows give different structure; with 5/5 only the external top exists and it confirms 3 bars later. |
| T-SW11-1 | replay | `SW11` | **SP-A:** SH4 (conf 6, 14) |  | NOT RUN | A candidate is not an event: its rejection is not a repaint because it was never emitted. |
| T-SW12-1 | replay | `SW12` | **SP-A:** SH3 (conf 5, 15) |  | NOT RUN | PDF section 3: event_index 3, confirmed_index = 3 + R. Replay must emit at k=5. |
| T-SW12-2 | replay | `SW12` | **SP-G (R=3):** SH3 (conf 6, 15) |  | NOT RUN | PDF section 3: event_index 3, confirmed_index = 3 + R. Replay must emit at k=5. |
| T-SW12-3 | replay | `SW12` | **SP-H (R=1):** SH3 (conf 4, 15) |  | NOT RUN | PDF section 3: event_index 3, confirmed_index = 3 + R. Replay must emit at k=5. |
| T-SW13-1 | boundary | `SW13` | **SP-A:** none |  | NOT RUN | First / last / all / cluster: each tie policy gives a different answer. |
| T-SW13-2 | boundary | `SW13` | **SP-B:** SH2 (conf 4, 14) |  | NOT RUN | First / last / all / cluster: each tie policy gives a different answer. |
| T-SW13-3 | boundary | `SW13` | **SP-C:** SH4 (conf 6, 14) |  | NOT RUN | First / last / all / cluster: each tie policy gives a different answer. |
| T-SW13-4 | boundary | `SW13` | **SP-D:** SH2 (conf 4, 14); SH3 (conf 5, 14); SH4 (conf 6, 14) |  | NOT RUN | First / last / all / cluster: each tie policy gives a different answer. |
| T-SW14-1 | boundary | `SW14` | **SP-A:** none |  | NOT RUN | Non-adjacent tie inside one window. |
| T-SW14-2 | boundary | `SW14` | **SP-B:** SH2 (conf 4, 14) |  | NOT RUN | Non-adjacent tie inside one window. |
| T-SW14-3 | boundary | `SW14` | **SP-C:** SH4 (conf 6, 14) |  | NOT RUN | Non-adjacent tie inside one window. |
| T-SW14-4 | boundary | `SW14` | **SP-D:** SH2 (conf 4, 14); SH4 (conf 6, 14) |  | NOT RUN | Non-adjacent tie inside one window. |
| T-SW15-1 | unit | `SW15` | **SP-A:** none |  | NOT RUN | Insufficient left history: either ineligible or a relaxed start rule. |
| T-SW15-2 | unit | `SW15` | **alt: partial left window at series start:** SH0 (conf 2, 14) |  | NOT RUN | Insufficient left history: either ineligible or a relaxed start rule. |
| T-MS01-1 | unit | `MS01` | **SP-A + ML-A:** SL2 (conf 4, 98.8, NONE); SH6 (conf 8, 107.2, NONE); SL10 (conf 12, 101.8, HL); SH14 (conf 16, 110.2, HH); SL18 (conf 20, 103.8, HL) |  | NOT RUN | Labels compare each swing with the previous confirmed swing of the same kind; labels exist from that swing's confirmation. |
| T-MS01-2 | unit | `MS01` | **TS-A state:** k<16: UNKNOWN; 16..20: BULLISH (HH@16 + HL@12, then HL@20) |  | NOT RUN | Labels compare each swing with the previous confirmed swing of the same kind; labels exist from that swing's confirmation. |
| T-MS01-3 | unit | `MS01` | **BOS-P1 (close>, RL):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED) |  | NOT RUN | Labels compare each swing with the previous confirmed swing of the same kind; labels exist from that swing's confirmation. |
| T-MS02-1 | unit | `MS02` | **SP-A + ML-A:** SH2 (conf 4, 111.2, NONE); SL6 (conf 8, 102.8, NONE); SH10 (conf 12, 108.2, LH); SL14 (conf 16, 99.8, LL); SH18 (conf 20, 106.2, LH) |  | NOT RUN | Mirror symmetry. |
| T-MS02-2 | unit | `MS02` | **BOS-P1 (close<, RL):** bearish break @13 of SL6 102.8 (ref conf 8, close, UNCLASSIFIED) |  | NOT RUN | Mirror symmetry. |
| T-MS03-1 | unit | `MS03` | **SP-A + ML-A:** SL2 (conf 4, 98.8, NONE); SH6 (conf 8, 107.2, NONE); SL10 (conf 12, 101.8, HL); SH14 (conf 16, 107.2, EH); SL18 (conf 20, 102.8, HL) |  | NOT RUN | Equal-structure labelling must be decided (EH treated as HH, LH, or neutral). |
| T-MS03-2 | unit | `MS03` | **TS-A state:** UNKNOWN (EH is neither HH nor LH) |  | NOT RUN | Equal-structure labelling must be decided (EH treated as HH, LH, or neutral). |
| T-MS03-3 | unit | `MS03` | **BOS-P1:** none |  | NOT RUN | Equal-structure labelling must be decided (EH treated as HH, LH, or neutral). |
| T-MS05-1 | unit | `MS05` | **SP-A + ML-A:** SL2 (conf 4, 100.8, NONE); SH6 (conf 8, 107.2, NONE); SL10 (conf 12, 98.8, LL); SH14 (conf 16, 109.2, HH); SL18 (conf 20, 96.8, LL) |  | NOT RUN | Every sequence of pivots is not a trend; breaks exist but cannot be labelled. |
| T-MS05-2 | unit | `MS05` | **TS-A state:** UNKNOWN throughout |  | NOT RUN | Every sequence of pivots is not a trend; breaks exist but cannot be labelled. |
| T-MS05-3 | unit | `MS05` | **BOS-P1 (RL):** bearish break @9 of SL2 100.8 (ref conf 4, close, UNCLASSIFIED); bullish break @14 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bearish break @18 of SL10 98.8 (ref conf 12, close, UNCLASSIFIED) |  | NOT RUN | Every sequence of pivots is not a trend; breaks exist but cannot be labelled. |
| T-MS06-1 | unit | `MS06` | **SP-A:** SH5 (conf 7, 12, NONE); SL7 (conf 9, 10, NONE); SH10 (conf 12, 15, HH) |  | NOT RUN | The same candles produce an internal BOS under 2/2 and none under 5/5. |
| T-MS06-2 | unit | `MS06` | **SP-E:** SH10 (conf 15, 15, NONE) |  | NOT RUN | The same candles produce an internal BOS under 2/2 and none under 5/5. |
| T-MS06-3 | unit | `MS06` | **BOS-P1 on SP-A:** bullish break @8 of SH5 12 (ref conf 7, close, UNCLASSIFIED) |  | NOT RUN | The same candles produce an internal BOS under 2/2 and none under 5/5. |
| T-MS06-4 | unit | `MS06` | **BOS-P1 on SP-E:** none |  | NOT RUN | The same candles produce an internal BOS under 2/2 and none under 5/5. |
| T-BOS01-1 | unit | `BOS01` | **SP-A + BOS-P1/P2/P3/P4 (RL):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @22 of SH14 110.2 (ref conf 16, close, BOS) |  | NOT RUN | Bullish state (HH@14, HL@18) + close above the latest confirmed high. |
| T-BOS02-1 | unit | `BOS02` | **SP-A + BOS-P1 (RL):** bearish break @13 of SL6 102.8 (ref conf 8, close, UNCLASSIFIED); bearish break @22 of SL14 99.8 (ref conf 16, close, BOS) |  | NOT RUN | Mirror symmetry. |
| T-BOS03-1 | negative | `BOS03` | **BOS-P1/P2/P4 (close):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED) |  | NOT RUN | PDF E4: depends on the wick/close policy. |
| T-BOS03-2 | negative | `BOS03` | **BOS-P3 (wick):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, wick, BOS) |  | NOT RUN | PDF E4: depends on the wick/close policy. |
| T-BOS03-3 | negative | `BOS03` | **side effect:** new swing high H21 (110.6) confirmed at 23 under SP-A |  | NOT RUN | PDF E4: depends on the wick/close policy. |
| T-BOS04-1 | unit | `BOS04` | **BOS-P1/P2/P4:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @22 of SH14 110.2 (ref conf 16, close, BOS) |  | NOT RUN | Wick and close profiles give different event candles for the same level. |
| T-BOS04-2 | unit | `BOS04` | **BOS-P3 (wick):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, wick, BOS) |  | NOT RUN | Wick and close profiles give different event candles for the same level. |
| T-BOS05-1 | boundary | `BOS05` | **BOS-P1 (close >):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED) |  | NOT RUN | PDF section 7: strict vs inclusive comparison. |
| T-BOS05-2 | boundary | `BOS05` | **BOS-P2 (close >=):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, close, BOS) |  | NOT RUN | PDF section 7: strict vs inclusive comparison. |
| T-BOS05-3 | boundary | `BOS05` | **BOS-P3 (wick):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, wick, BOS) |  | NOT RUN | PDF section 7: strict vs inclusive comparison. |
| T-BOS06-1 | boundary | `BOS06` | **BOS-P1/P2/P3:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, close, BOS) |  | NOT RUN | PDF E5: depends on strictness, tick size and buffer. |
| T-BOS06-2 | boundary | `BOS06` | **BOS-P4 (close > level + 2 ticks):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED) |  | NOT RUN | PDF E5: depends on strictness, tick size and buffer. |
| T-BOS07-1 | boundary | `BOS07` | **BOS-P1..P4 (gap counts):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, close; gap, BOS) |  | NOT RUN | PDF section 7: specify whether a gap qualifies. |
| T-BOS07-2 | boundary | `BOS07` | **alt: gap excluded:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED) |  | NOT RUN | PDF section 7: specify whether a gap qualifies. |
| T-BOS07-3 | boundary | `BOS07` | **alt: gap flagged:** same event with evidence 'gap' |  | NOT RUN | PDF section 7: specify whether a gap qualifies. |
| T-BOS08-1 | duplicate | `BOS08` | **BOS-P1 + one event per level:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, close, BOS) |  | NOT RUN | PDF E7 / section 7: deduplicate by stable level ID. |
| T-BOS08-2 | duplicate | `BOS08` | **alt: event per new cross:** 21 and 23 |  | NOT RUN | PDF E7 / section 7: deduplicate by stable level ID. |
| T-BOS08-3 | duplicate | `BOS08` | **alt: event per close beyond:** 21, 23, 24 |  | NOT RUN | PDF E7 / section 7: deduplicate by stable level ID. |
| T-BOS09-1 | no-look-ahead | `BOS09` | **SP-A + BOS-P1:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED) |  | NOT RUN | PDF E6: a level cannot be used before its swing confirms. Under a fixed strict window the candidate is simply never confirmed. |
| T-BOS10-1 | negative | `BOS10` | **BOS-P1 + RL (latest confirmed low):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bearish break @22 of SL18 103.8 (ref conf 20, close, CHOCH_CANDIDATE) |  | NOT RUN | PDF section 6: counter-structure break = potential CHoCH only with a state model. |
| T-BOS10-2 | negative | `BOS10` | **alt: protected low = low that started the last HH leg (SL10):** bearish counter-structure break at 23 |  | NOT RUN | PDF section 6: counter-structure break = potential CHoCH only with a state model. |
| T-BOS10-3 | negative | `BOS10` | **BOS-P1 + RH (lowest unbroken low):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED) |  | NOT RUN | PDF section 6: counter-structure break = potential CHoCH only with a state model. |
| T-BOS10-4 | negative | `BOS10` | **side effect:** new swing high H20 (LH) confirmed at 22 |  | NOT RUN | PDF section 6: counter-structure break = potential CHoCH only with a state model. |
| T-BOS11-1 | unit | `BOS11` | **SP-A + BOS-P1 (RL):** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @22 of SH14 110.2 (ref conf 16, close, BOS); bullish break @31 of SH24 113.2 (ref conf 26, close, BOS) |  | NOT RUN | PDF section 10: a new reference level creates a distinct event. |
| T-BOS12-1 | unit | `BOS12` | **BOS-P1 + RL:** bearish break @13 of SL6 100.8 (ref conf 8, close, UNCLASSIFIED); bullish break @17 of SH10 106.7 (ref conf 12, close, CHOCH_CANDIDATE) |  | NOT RUN | Which confirmed swing is the reference changes the result (V4 audit B1: 52% of V4 BOS broke a lower high). |
| T-BOS12-2 | unit | `BOS12` | **BOS-P1 + RH (highest unbroken high):** bearish break @13 of SL6 100.8 (ref conf 8, close, UNCLASSIFIED) |  | NOT RUN | Which confirmed swing is the reference changes the result (V4 audit B1: 52% of V4 BOS broke a lower high). |
| T-BOS13-1 | immutability | `BOS13` | **BOS-P1:** bullish break @13 of SH6 107.2 (ref conf 8, close, UNCLASSIFIED); bullish break @21 of SH14 110.2 (ref conf 16, close, BOS) |  | NOT RUN | PDF section 3 replay contract + BOS-007. |
| T-BOS13-2 | immutability | `BOS13` | **alt invalidation:** BOS stays (immutable); an optional separate INVALIDATION event at 23 referencing it |  | NOT RUN | PDF section 3 replay contract + BOS-007. |
| T-BOS14-1 | negative | `BOS14` | **SP-A:** SH2 (conf 4, 15, NONE); SL4 (conf 6, 10, NONE) |  | NOT RUN | PDF section 6: return insufficient-context/unknown. |
| T-BOS14-2 | negative | `BOS14` | **BOS-P1:** bullish break @5 of SH2 15 (ref conf 4, close, UNCLASSIFIED) |  | NOT RUN | PDF section 6: return insufficient-context/unknown. |
| T-BOS15-1 | boundary | `BOS15` | **raw float, any profile:** none |  | NOT RUN | PDF section 7 'Precision': tick-aware boundary tests. |
| T-BOS15-2 | boundary | `BOS15` | **tick-rounded (0.01), BOS-P2 (>=):** bullish break @5 of SH2 0.3 (ref conf 4, close, UNCLASSIFIED) |  | NOT RUN | PDF section 7 'Precision': tick-aware boundary tests. |
| T-BOS15-3 | boundary | `BOS15` | **tick-rounded, BOS-P1 (>):** none |  | NOT RUN | PDF section 7 'Precision': tick-aware boundary tests. |
| T-RB01-1 | invalid input | `RB01` | **loader:** REJECT (CandleError: timestamps must strictly increase) | rejected with CandleError | EXECUTED: PASS (existing CandleSeries) | PDF section 1: timestamps strictly increasing. |
| T-RB02-1 | invalid input | `RB02` | **loader:** REJECT (CandleError: inconsistent OHLC) | rejected with CandleError | EXECUTED: PASS (existing CandleSeries) | PDF section 1: H >= max(O,C). |
| T-RB03-1 | invalid input | `RB03` | **SP-A (window counts bars):** SH3 (conf 5, 15) | series loads (7 candles) | loader part EXECUTED: PASS; swing part NOT RUN | Missing bars: the window definition (bars vs time) must be declared. |
| T-RB03-2 | invalid input | `RB03` | **alt: window counts time / gap breaks window:** no swing or later confirmation |  | NOT RUN | Missing bars: the window definition (bars vs time) must be declared. |
| T-RB04-1 | invalid input | `RB04` | **loader:** REJECT | rejected with CandleError | EXECUTED: PASS (existing CandleSeries) | Ordering invariant. |

## B. Property and harness tests (designed)

| Test id | Category | Input | Expected | Actual | Status | Explanation |
|---|---|---|---|---|---|---|
| T-REPLAY | candle-by-candle replay | every case | at each prefix k, emitted events = full-run events with `confirmed_index ≤ k` | — | NOT RUN | PDF §3 replay contract |
| T-PAR | batch vs streaming parity | every case | the streaming detector's events at k == the batch detector on prefix k (both directions: nothing missing, nothing extra) | — | NOT RUN | PDF invariant (4). **Gap:** the existing harness checks only one direction (prefix ⊆ full). See model gap G12. |
| T-NLA | no-look-ahead | every case, detector given `series.upto(k)` | `no_lookahead_violations == []` | — | NOT RUN (harness itself EXECUTED: PASS, 5 tests) | the existing harness catches an early report, a future candle and repainting |
| T-IMM | event immutability | every case | events are frozen dataclasses; ids are stable across runs | — | NOT RUN | PDF §3 |
| T-DUP | duplicate events | BOS08, SW13 / SW04 under SP-D | no duplicate ids; de-dup policy honoured | — | NOT RUN | PDF E7 |
| T-SYM | high / low mirror | SW01↔SW03, SW04↔SW06, MS01↔MS02, BOS01↔BOS02 | the same indices with kinds and directions swapped | scratch checker: identical (SW01/SW03, MS01/MS02, BOS01/BOS02) | EXECUTED on the scratch checker only; NOT RUN on V6 | PDF §10 |
| T-DET | determinism | every case | two runs give identical lists, including order | — | NOT RUN | SW-R17 |
| T-OHLC | invalid OHLC | RB02 + existing unit tests | `CandleError` | rejected | EXECUTED: PASS | PDF §1 |
| T-TIME | timestamp integrity | RB01, RB04, naive and tz-aware inputs | reject duplicate / unsorted / naive; convert to UTC | rejected / converted | EXECUTED: PASS (existing `test_models.py`, 12 tests) | PDF §1 |
| T-STAMP | event-candle consistency | every emitted event | `check_stamp_against(series, ev)` passes | — | NOT RUN | PDF invariant (5) |
| T-FUTURE | future-read attempt fails | detector given a prefix | the harness flags `index > k` | flagged | EXECUTED on a toy detector: PASS | PDF §10 *"Future-read attempt fails"* |

## C. Executed during this analysis (exact)

- `CandleSeries` load of all 39 draft cases:
  - 35 normal cases loaded.
  - RB01 rejected (duplicate time); RB02 rejected (high < close); RB04 rejected (unsorted).
  - RB03 loaded: gaps are allowed by the loader; whether windows count bars or time is OPEN.
- Scratch checker over all computable expectations: 0 mismatches. This checks the *fixtures*, not V6.
- Existing V6 tests: run in the foundation task (17 passed). Not re-run here because no V6 code changed in this phase.

