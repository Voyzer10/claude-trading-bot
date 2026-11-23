# V6 existing structure scanner: 25 historical chart validation (23 Nov 2026)

**Validation only. PAPER ONLY. No source, test, fixture, spec or register change. NOT FULLY BLIND (see C).**
Artifacts: this folder (outside the repository). Checksums: `SHA256SUMS`.

## A. Preflight: PASS
- Branch `research/v6-smc-scanner`, HEAD `7f16f0953798a7b82e7cb595096487b66ab7ac3e`.
- Index `e7490c2c616620c0`, staged diff `f724a4ad7956d99c`, 37 staged paths (same list).
- Spec `835fc01360bb91563f1fa101b33e93f2147fc712e1a56522287a103ce38a2d8f`.
- Module A: `candle_models.py` `029fb170…`, `test_chart_ingestion.py` `52e450a3…`, `integrity.py` `d2e2c92e…`, `market_config.py` `695aaca2…`, `test_market_data.py` `66bc5f94…`.
- The seven git commands' output (`preflight_git.txt`) was identical to the previous Module A postflight.

## B. Dataset inventory
**Source.** User-uploaded Yahoo Finance chart cache: `/mnt/user-data/uploads/trader/trader/research/cache`, read only.
- 50 NSE stocks, 5m candles only, 60 trading days (5 Aug – 30 Oct 2026), 218,917 rows.
- 0 None, 0 duplicate, 0 out-of-order and 0 inconsistent OHLC rows.
- The RELIANCE file SHA matches the R1 audit manifest.

**Not used.** US / crypto copies in old scratchpad folders, because their provenance cannot be verified.

**Segment rule.**
- A segment is one complete trading day: at least 72 contiguous 5m candles from 09:15 IST. This cache mostly has 73 candles per day (09:15–15:15), not 75.
- So no overnight gap (O7, OPEN) falls inside a segment.
- 2,305 of 3,000 day-slices were complete.

**Selection.** Fixed, OHLC-only rules, written before any scanner run (`select_segments.py`):
- each category picked in rank order;
- one chart per instrument, at most two charts per date;
- no overlap between charts.

| Chart | Category | Symbol | Day (IST) | Candles | Source rows | Why (ret % / efficiency / range × median) |
|---|---|---|---|---|---|---|
| HV01 | HIGH_VOLATILITY | ADANIENT.NS | 2026-08-31 | 73 | 1308-1380 | -9.18 / 0.46 / 4.26× |
| HV02 | HIGH_VOLATILITY | ADANIPORTS.NS | 2026-08-31 | 72 | 1309-1380 | -6.79 / 0.59 / 4.31× |
| HV03 | HIGH_VOLATILITY | APOLLOHOSP.NS | 2026-09-30 | 73 | 2832-2904 | -5.26 / 0.38 / 4.05× |
| HV04 | HIGH_VOLATILITY | BAJAJ-AUTO.NS | 2026-10-01 | 73 | 2903-2975 | -5.42 / 0.25 / 4.24× |
| HV05 | HIGH_VOLATILITY | HDFCBANK.NS | 2026-10-05 | 73 | 2991-3063 | -3.69 / 0.39 / 3.55× |
| HV06 | STRONG_UPTREND | DRREDDY.NS | 2026-08-11 | 72 | 292-363 | +3.83 / 0.41 |
| HV07 | STRONG_UPTREND | HDFCLIFE.NS | 2026-09-17 | 73 | 2185-2257 | +4.77 / 0.40 |
| HV08 | STRONG_UPTREND | ITC.NS | 2026-10-09 | 73 | 3282-3354 | +4.17 / 0.45 |
| HV09 | STRONG_UPTREND | KOTAKBANK.NS | 2026-08-26 | 73 | 1095-1167 | +3.58 / 0.44 |
| HV10 | STRONG_UPTREND | TMPV.NS | 2026-09-17 | 73 | 2189-2261 | +4.69 / 0.40 |
| HV11 | STRONG_DOWNTREND | BEL.NS | 2026-09-15 | 73 | 2042-2114 | -5.05 / 0.49 |
| HV12 | STRONG_DOWNTREND | COALINDIA.NS | 2026-10-06 | 73 | 3061-3133 | -3.58 / 0.46 |
| HV13 | STRONG_DOWNTREND | HINDALCO.NS | 2026-08-27 | 73 | 1166-1238 | -3.32 / 0.44 |
| HV14 | STRONG_DOWNTREND | SHRIRAMFIN.NS | 2026-09-15 | 73 | 2039-2111 | -5.64 / 0.56 |
| HV15 | STRONG_DOWNTREND | SUNPHARMA.NS | 2026-08-17 | 73 | 582-654 | -3.19 / 0.45 |
| HV16 | REVERSAL_CHOPPY | EICHERMOT.NS | 2026-09-02 | 73 | 1455-1527 | halves -4.50 / +2.54 |
| HV17 | REVERSAL_CHOPPY | GRASIM.NS | 2026-08-25 | 72 | 1019-1090 | halves -1.61 / +1.90 |
| HV18 | REVERSAL_CHOPPY | TATASTEEL.NS | 2026-09-01 | 72 | 1385-1456 | halves +1.77 / -1.28 |
| HV19 | REVERSAL_CHOPPY | TECHM.NS | 2026-08-25 | 73 | 1021-1093 | halves -1.58 / +2.20 |
| HV20 | REVERSAL_CHOPPY | TITAN.NS | 2026-08-12 | 73 | 365-437 | halves -2.28 / +1.77 |
| HV21 | SIDEWAYS | CIPLA.NS | 2026-08-18 | 73 | 656-728 | +0.01 / 0.003 / 0.37× |
| HV22 | SIDEWAYS | MAXHEALTH.NS | 2026-09-10 | 73 | 1893-1965 | -0.14 / 0.02 / 0.46× |
| HV23 | SIDEWAYS | NTPC.NS | 2026-09-10 | 73 | 1896-1968 | +0.03 / 0.007 / 0.44× |
| HV24 | SIDEWAYS | POWERGRID.NS | 2026-08-14 | 73 | 511-583 | -0.11 / 0.03 / 0.39× |
| HV25 | SIDEWAYS | RELIANCE.NS | 2026-08-21 | 73 | 875-947 | +0.15 / 0.04 / 0.45× |

Every row is in `selection.csv`, with each chart's SHA.

## C. Blind protocol: NOT FULLY BLIND
| Question | Answer |
|---|---|
| Who annotated? | Claude, using an independent reference implementation of the approved rules (`annotate_reference.py`). It is written from the spec documents, never imports `scanner_v6` (asserted), and runs isolated. The same agent has seen the scanner code in earlier sessions, so this is **not an independent human annotator**. |
| Second reviewer? | **No.** |
| Key frozen | 2026-11-23 09:23:00 UTC, before the first scanner run (`SEAL_MANIFEST.txt`). |
| Key SHA-256 | Approved-rule key `dcd8d619f295fa09a3c8960b7f90ee5a14b22c5ad3c247eff71106ecd61b88c7`. Conditional variant B `7b720fd01879798c90b64ab6ec461829d106f4b39b04a1b2e9f7526a5d720c4a`. |
| Scanner isolated from the key? | Partly. The scanner process got only the charts folder. An audit hook logged all 78 files it opened; the key was never opened. Same machine, though, so there is no OS-level isolation. |
| Outputs frozen before scoring? | Yes. Raw v1 `06738f01…` (09:23:47 UTC). Raw v2 `39734013…` (09:24:17 UTC), identical except that event timestamps were added for the backdating check. |
| Key revised after seeing output? | **No.** One key error was found during scoring. A separately labelled POST-HOC (non-blind) key was made to adjudicate it; the sealed results are unchanged. |

## D. Results
Two keys were scored:
- **Approved-rule key (primary):** every UNRESOLVED case is excluded.
- **Variant B (conditional, NOT approved):** applies the O9 "latest two swings" reading that `PHASE1_2_DECISIONS.md` §1.3 documents as the implementation behaviour.

Swings and BOS do not depend on structure state (Option A), so they are fully scored on all 25 charts.

**Aggregate, approved-rule key (TP / FP / FN, precision, recall):**

| Category | TP | FP | FN | Precision | Recall | Notes |
|---|---|---|---|---|---|---|
| Swing High | 188 | 0 | 0 | 1.00 | 1.00 | Exact candle, price and confirmation (index + 2) |
| Swing Low | 196 | 0 | 0 | 1.00 | 1.00 | Same |
| BOS | 147 | 0 | 0 | 1.00 | 1.00 | Exact candle, direction, reference swing and level |
| CHoCH | 1 | 0 | 0 | 1.00 | 1.00 | Only 1 decidable CHoCH (HV16) |
| WICK_ONLY | 0 | 0 | 0 | – | – | None decidable |
| Equality NO_CHOCH (CHU04) | 0 | 0 | 0 | – | – | No equality case in the data |
| State changes | 3 | 0 | 0 | 1.00 | 1.00 | HV16 |
| State checkpoints | 601 of 601 scorable agree (state and protected level) | | | | | 1,220 of 1,821 checkpoints UNRESOLVED |
| No-look-ahead / parity | 0 violations | | | | | Library check, replay_audit (batch and stream) and an independent prefix replay of every candle |
| Duplicates / unexpected / out-of-order / invalid index / premature | 0 | | | | | Scorer validation |

**Variant B, sealed (conditional):**

| Category | TP / FP / FN |
|---|---|
| CHoCH | 3 / 1 / 1 |
| WICK_ONLY | 2 / 1 / 0 |
| State changes | 10 / 2 / 1 |
| Checkpoints | 696 of 743 agree |

Every mismatch traces to key error F1 (see E).

**Post-hoc key (F1, F2 fixed; NOT BLIND):**

| Key | CHoCH | WICK_ONLY | State changes | Checkpoints |
|---|---|---|---|---|
| Approved | 1 / 0 / 0 | – | – | 602 of 602 |
| Variant B | 5 / 0 / 0 | 3 / 0 / 0 | 14 / 0 / 0 | 814 of 815 (the one difference is UNRESOLVED, see E) |

**By chart category (approved key; swing high / swing low / BOS as TP/FP/FN; checkpoints):**

| Category | Swing High | Swing Low | BOS | CHoCH | Checkpoints |
|---|---|---|---|---|---|
| Strong uptrend | 44/0/0 | 35/0/0 | 25/0/0 | 0 | 114/114 |
| Strong downtrend | 38/0/0 | 43/0/0 | 35/0/0 | 0 | 119/119 |
| Sideways | 31/0/0 | 36/0/0 | 25/0/0 | 0 | 107/107 |
| High volatility | 40/0/0 | 46/0/0 | 33/0/0 | 0 | 99/99 |
| Reversal / choppy | 35/0/0 | 36/0/0 | 29/0/0 | 1/0/0 | 162/162 |

Per-chart detail: `results/PER_CHART.csv` and `results/SCORES_*.json`.

**Mutation tests** (on copies; frozen outputs re-hashed unchanged): **22 of 22 detected.**
- one-candle shift; flipped direction; wrong price; wrong BOS reference; wrong CHoCH protected reference;
- duplicate actual and duplicate expected events; missing event; extra and missing checkpoints; out-of-order events; invalid index;
- future-confirmation leakage; confirmed before its candle; late confirmation; backdated timestamp;
- state change one candle early; wrong protected level; TRANSITION mislabelled; injected CHoCH; injected WICK_ONLY.

## E. Failures
**Scanner: no false positive, false negative, timing, direction, price, reference, state, duplicate or look-ahead failure** in any scored item.

**Key error F1 (expected-key defect, found after freezing):**
- When a P-B origin swing had confirmed *before* its BOS candle, the key scheduled the activation on a past candle, so it never happened.
- The spec says it activates at once (`PHASE1_2_DECISIONS.md` §3.1 c24).
- Cases: HV09 (BOS c57, origin L51 confirmed c53) and HV20 (BOS c34, origin H30 confirmed c32).
- **The scanner is correct.**
- Effect: the variant-B HV20 mismatches (CHoCH c60 vs c68, WICK_ONLY c58, state changes c60/c61 vs c68) and the HV09 protected level at checkpoints c57–c66.
- No effect on the approved-key scores.

**F2 (key over-conservatism):** the "earlier-confirming candidate" ambiguity was applied even when every candidate had confirmed by the BOS candle. Fixed in the post-hoc key only.

**UNRESOLVED (neither side is shown wrong):** HV20 c61. After the D1 reversal is confirmed, and before the confirming BOS's origin activates (c62):
- the post-hoc key keeps the previously tracked low L56;
- the scanner has no protected level.

The spec ("previous valid protected swing is retained") does not say whether a P-B low tracked during the BEARISH phase is "valid" for the new structure.

## F. Limitations
1. **NOT FULLY BLIND:** no independent human annotator, no second reviewer, no OS-level isolation (see C).
2. **CHoCH, WICK_ONLY and state coverage under approved rules is thin:**
   - 1 CHoCH, 0 WICK_ONLY, 3 state changes;
   - 601 of 1,821 checkpoints scorable;
   - 24 of 25 charts become UNRESOLVED at establishment.
3. **Spec gaps found on real data (owner decisions needed):**
   - **O9:** 12 charts have more than two swings of one kind when establishment first becomes possible; 4 charts establish after an earlier mixed classification. The scanner gives no `O9_UNRESOLVED` diagnostic in these cases (it covers only the crossed-level case) and silently applies the latest-two reading.
   - **Directional state with no protected level:** the scanner establishes BULLISH or BEARISH with protected = None in 19 charts, and 432 directional checkpoints in 22 charts have no protected level, so no CHoCH is possible there. The spec does not define this case.
   - The D1 protected level between confirmation and origin activation (HV20 c61).
   - P-B origin ambiguity: 15 of 147 BOS (tie, no previous swing for the A5 test, earlier-confirming candidate).
4. **Data:** a single market (NSE), single timeframe (5m), single period (Aug–Oct 2026) and single provider.
   - All five HIGH_VOLATILITY picks are down days.
   - No equality close (CHU04) occurs, so equality handling is untested on real data; it is covered only by unit tests.
   - Swings at index 0 and 1 are unscored (D-SW-START is open); the scanner emitted none.
5. **Scorer weaknesses:**
   - Events in UNRESOLVED (tainted) regions are not scored semantically. An injected CHoCH there was caught only through its wrong timestamp.
   - Diagnostics (WICK_ONLY, etc.) get no structural validation: duplicate diagnostics in a tainted region went undetected.
   - The scanner's unscored output is counted (68 events after taint) but not judged.
6. **Not tested (as instructed):** liquidity, candlesticks, confirmation, entries, execution, profitability.

## G. Postflight
See the final chat report. Recorded in `postflight_git.txt`.

## H. Verdict
**PARTIAL — CHART VALIDATION HAS ISSUES**

- Swings, BOS and no-look-ahead: perfect agreement on 25 real charts.
- No scanner defect found.
- But the test is not fully blind, approved-rule coverage of CHoCH, WICK_ONLY and state is far too thin to call the structure scanner validated on real data, and real data exposed unresolved spec items (O9, a directional state with no protected level, the D1 protected gap) that need owner decisions.

Not a profitability claim, not a trading edge, not liquidity validation, not live-trading authorization.

---

## Addendum (23 Nov 2026, owner-approved re-run): independent spec-only annotator
The owner asked for the key to be rebuilt by a separate agent that had never seen the scanner. The sections above are unchanged.

**Protocol**
- Isolated input folder `hv25_indep/input/` (manifest `INPUT_MANIFEST.sha`, unchanged afterwards):
  - the 25 chart files;
  - 7 spec documents: SWING / BOS rule matrices, MARKET_STRUCTURE_SPEC, UNRESOLVED_DECISIONS, PHASE1_2_DECISIONS, the CHoCH v0.9 README and V6_TRADING_SPEC_v0.2.
  - No scanner code, tests, audits, earlier key or scanner output.
- The agent was told to read only that folder. Its notes list exactly those files, and its script opens only `input/charts/HV*.json`. This is self-reported plus a code audit, **not OS-enforced**.
- Key sealed 2026-11-23 09:55:25 UTC: `INDEPENDENT_KEY.json` SHA-256 `23f143fe8610091bd0a1ddf74135f0348cb6809774248b195205002bed71138e`.
- Scored against the scanner output frozen earlier (v2 `39734013…`, unchanged), with the same scorer.
- Blind status: **substantially stronger, still NOT FULLY BLIND**. The annotator is a model, not a human. Isolation is instruction-based. No second reviewer adjudicated, but two independently built keys now exist (see "Inter-annotator").

**Results vs the independent key (TP / FP / FN)**

| Category | TP / FP / FN |
|---|---|
| Swing High | 188 / 0 / 0 |
| Swing Low | 196 / 0 / 0 |
| BOS | 147 / 0 / 0 |
| CHoCH | 7 / 0 / 0 (HV05, HV06, HV13, HV15, HV16, HV19, HV22) |
| WICK_ONLY | 9 / 0 / 0 |
| Equality | 0 cases |
| State changes | 24 / 0 / 0 |

**Checkpoints:** 989 scorable. State agrees on 989 of 989; state + protected level on 968 of 989.

**Other checks:** 0 validation issues, 0 look-ahead problems. Mutations 22 of 22 detected.

**The 21 protected-level differences** are all HV06 c51–c71, one decision point:
- The D1-confirming bullish BOS at c51 (ref H45) has two swing lows in its leg: L47 1192.40 (confirmed c49) and L50 1191.50 (confirmed c52).
- **Independent key:** origin = the eventual lowest = L50. It fails the A5 HL test, so protected = null.
- **Scanner:** activates L47, the lowest *confirmed* swing at the BOS candle, then marks L50 NOT_QUALIFIED at c52 and keeps L47.
- D2's wording ("lowest confirmed swing low…") and the CHD16 example do not decide the case of a confirmed candidate plus a lower candidate that confirms later.
- **UNRESOLVED: P-B origin selection.** Not shown to be a scanner error. Claude's sealed key had marked this same pattern ambiguous.

**Inter-annotator** (Claude sealed key vs independent key)
- Swings and BOS are identical (384 / 147).
- On the 601 checkpoints both keys score, they agree 601 / 601.
- The independent key scores 388 more:
  - it treats established states with no P-B protected level as scorable (protected = null);
  - it does not treat "more than two swings at first availability" as O9.
- The annotators disagree on *what is unresolved*:
  - Claude: O9 in 16 charts.
  - Independent: CHU05 in 9 charts, O4 in 5, "no P-B protected level + close beyond the opposite swing" in 5, equal lows in 1. O9 never triggered.
- That disagreement is itself evidence that the establishment / protected-level rules need owner decisions.

**Independent annotator's main doubt:** candles 0–1 are excluded as swings (D-SW-START is OPEN). If they were allowed, state or protected level would change in 20 charts and 2 BOS would be added (HV05, HV18).

**Updated verdict: PARTIAL — CHART VALIDATION HAS ISSUES (unchanged)**
- No scanner defect was found against either key: every decidable swing, BOS, CHoCH, WICK_ONLY and state change matches, and every look-ahead check passes.
- The remaining issues are about the test and the spec, not the scanner:
  - not fully blind;
  - the annotators disagree on the unresolved scope;
  - owner decisions are still open: O9 / establishment chronology, a directional state with no protected level, P-B origin when a confirmed and a later lower candidate coexist, D1 protected gap, D-SW-START.
