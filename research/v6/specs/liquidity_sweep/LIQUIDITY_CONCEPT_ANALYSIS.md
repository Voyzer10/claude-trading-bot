# Liquidity concept analysis (research, 22 Nov 2026)

**Status:** research only. Nothing here is an approved rule. "B0" means the **proposed** experimental baseline, which needs owner approval (UNRESOLVED_DECISIONS.md).

**Source tags** are defined in VIDEO_SOURCE_NOTES.md. Each claim is also labelled:
- **TEACHES:** what the source says.
- **COMMON:** a common SMC reading (general knowledge, not from these sources).
- **INFERENCE:** my own technical reasoning.
- **AMBIGUOUS:** sources disagree or are silent.

**OHLC examples** use the base series **B17** = CHoCH fixture CHD01, candles c1–c17. Its facts, checked with the approved detector:
- Swing L 98 (c4, conf c6), H 109 (c7, conf c9), L 101 (c10, conf c12), H 116 (c14, conf c16).
- Bullish BOS at c12 (close 110 > 109).
- BULLISH structure from c17, with protected HL 101.

The LS-numbered cases are in SYNTHETIC_DATASET_PLAN.md.

---

## 1. Buy-side liquidity (BSL)
- **Definition:**
  - TEACHES (V1-meta chapter title; V1-AI): resting orders, mainly buy stops of shorts and buy-stop breakout entries, **above** highs.
  - V1-art only describes the order book's ask side.
- **Alternatives:**
  - (a) every confirmed swing high
  - (b) only "obvious" highs (repeated, equal, or major)
  - (c) round numbers (V1-art lists them as a pool location)
  - (d) order-book data
- **Example (B17):** BSL at 116 (H c14) exists from c17; it is first usable at candle 17 (conf c16).
- **Pros / cons:**
  - (a) objective and causal, but includes minor highs.
  - (b) closer to the teaching, but "obvious" is undefined.
  - (c) is objective but instrument-specific.
  - (d) is not available from OHLC.
- **False positives:** minor highs with little real order flow; highs inside consolidation.
- **Testable:** (a) yes; (b) only with a definition; (c) yes, given a step size; (d) no.
- **B0:** (a), every L2/R2 confirmed swing high, active from its confirmation candle + 1.
- **Unresolved:** LQ-01 (pool sources), LQ-02 (major vs minor).

## 2. Sell-side liquidity (SSL)
The mirror of BSL: sell stops of longs and breakdown entries **below** lows (V1-meta, V1-AI; V2-tx at 5:54: "maximum liquidity" below equal lows).
- **Example:** SSL at 101 (L c10) usable from c13; SSL at 98 (L c4) usable from c7.
- **B0:** every confirmed swing low.
- **Symmetry:** item 16.

## 3. Equal highs and equal lows (EQH / EQL)
- **Definition:**
  - TEACHES: V1-art (double tops / bottoms are pool locations), V1-AI (stacked stops make a deeper pool, a stronger reaction), V2-tx 5:54 (equal lows = maximum liquidity).
  - Under the **approved** swing rule, equal highs / lows are **not swings** (SW-004). They exist only as the `unresolved_equal_levels` diagnostic.
- **Alternatives:**
  - (a) exact equality, no pool
  - (b) exact-equality cluster as a pool
  - (c) a tolerance band (ticks, ATR %, or bps) cluster as a pool
  - (d) a cluster of two or more confirmed swings within a tolerance
- **Example (regression fixture MED01 = Easy chart 1):**
  - Equal highs 105 at c3 / c4. The tie window closes at c5 / c6.
  - c8: high 106, close 105 (the close equals the level). c9: high 107, close 104. c11: close 107 > 105.
  - Under (b): c8 and c9 are wick sweeps of the EQH and c11 takes it by close. Under (a): none of these is a liquidity event at all.
- **Pros / cons:**
  - (a) is consistent with the approved swing rule, but ignores the most-taught pool type.
  - (b) is objective, but exact floating equality is rare in real data.
  - (c) matches the teaching, but adds a free parameter (overfitting risk).
  - (d) needs swings, so it is causal, but swings must already exist.
- **False positives:** tolerance bands that merge unrelated highs; very wide or old clusters.
- **Testable:** yes for (a), (b) and (d); (c) only after the tolerance is fixed **before** looking at results.
- **B0:** an exact-equality EQH / EQL **pool candidate**, kept as a **separate pool type**, scored only after LQ-03 is approved. It confirms when the tie window closes (the `window_closed_index` of the diagnostic). The approved swing rule is unchanged: they are still not swings.
- **Unresolved:** LQ-03 (whether EQ levels are pools at all, tolerance, confirmation time).

## 4. Liquidity around confirmed swing highs / lows
- **Definition:** INFERENCE combining V1 and V2. A pool level = the price of a confirmed swing. In V6 that means the L2/R2 swing, known only from index + R.
- **Example:** in LS10, the sweep wick low 100 at c18 is itself a swing low, confirmed at c20. It becomes a **new** SSL pool usable from c21, never earlier (no look-ahead).
- **B0:** the pool id is derived from the swing id; the pool is active from confirmation + 1.
- **Unresolved:** LQ-04 (zone vs single price: wick extreme vs body).

## 5. Internal vs external liquidity
- **Definition:**
  - TEACHES: V1-AI only. External = outside the current range (major highs / lows); internal = minor swings inside it. Internal tends to be taken first.
  - V1-meta has the chapter (48:55); the video's own words were not seen.
- **Alternatives:**
  - (a) external = the swings that define the external structure (CHoCH spec A1, which has **no executable definition yet**)
  - (b) range = between the latest protected swing and the latest BOS reference
  - (c) higher-timeframe swings
- **Testable:** only once "external structure" is defined. The same open gap exists in the CHoCH spec (A1).
- **B0:** **not modelled.** Every pool is unlabelled.
- **Unresolved:** LQ-05.

## 6. Liquidity pool creation and lifecycle
- **Definition:** INFERENCE; the sources only imply that a pool exists until it is taken.
- **Proposed states (B0):**
  - **ACTIVE** from swing confirmation + 1.
  - **SWEPT:** a wick beyond and a close not beyond. The pool stays usable by a later close.
  - **TAKEN:** a close beyond. Inactive from then on.
- **Alternatives:**
  - the first sweep consumes the pool
  - the pool expires after N candles or a session
  - the pool is replaced by a newer swing on the same side
  - a pool that is not the latest swing never expires (relevant to D4: BOS uses only the latest swing)
- **Example:** in LS05, c18 has low 96 (< 101 and < 98) and close 102. Both SSL pools become SWEPT at c18, neither is TAKEN, and the BOS module emits nothing (no close beyond).
- **Testable:** yes, once the states are fixed.
- **Unresolved:** LQ-06 (lifecycle), LQ-07 (expiry).

## 7. Wick penetration vs candle-close penetration
- **TEACHES:**
  - V1-art: a grab is a long wick beyond the level with the close back on the original side; a real break closes beyond and follows through.
  - V3-meta: judge the sweep by the wick, not the close. V3-art: the sweep is a wick; the confirmation is a later close beyond the trigger low.
  - V2-tx: silent.
- **Alternatives:**
  - **S-wick:** high > level and close ≤ level (bearish sweep of BSL)
  - **S-any:** any trade beyond, whatever the close
  - **S-multi:** a close beyond, then a close back inside within N candles
- **Approved-rule interaction (INFERENCE, verified):**
  - BOS and CHoCH require a **close strictly beyond**. S-wick is the exact complement: on a given level and candle, a sweep and a BOS never both occur.
  - LS01: c18 has low 100 and close 102 against protected 101. The approved CHoCH code already records **WICK_ONLY** (NO_CHOCH) there, which is exactly an S-wick sweep of the protected SSL.
  - LS02: close 100 < 101 gives a BOS and a CHoCH; under S-wick it is **not** a sweep (a run / take).
- **Exact equality:** LS09 has low 100 and close exactly 101. Not a BOS (strict close). Under S-wick it is a sweep, since close ≤ level. That ties to CHU04 (strictness), which is open.
- **B0:** S-wick.
- **Unresolved:** LQ-08 (S-multi, which overlaps O4 failed CHoCH), LQ-09 (minimum penetration depth).

## 8. Liquidity sweep vs grab vs run

*(Phase 1.2: this section was aligned with SWEEP_RULE_MATRIX §A, UNRESOLVED_DECISIONS LQ-10 / LQ-11 / LQ-17 and README "Phase 1.1 Consistency Audit". It keeps three layers apart.)*

**Layer 1: instructor terminology.** Recorded as-is, with disagreements kept. This is **not a rule.**
- **V1-art (TEACHES):** sweep = the movement beyond a level (neutral); grab = a deliberate pierce plus reversal, with a long wick and a close back inside; a real breakout closes beyond and follows through.
- **V1-AI (TEACHES per an unverified AI summary):** sweep = a slower break that traps breakout traders, then a reversal; grab = a fast wick poke; run = a continuing break, ideally with a momentum candle whose body is ≥ 2× the previous one.
- **V2-tx (TEACHES):** "sweep" and "grab" are used as the same thing. The trainer prefers "grab" to "trap". No "run" is defined.
- **V3-meta / V3-art (TEACHES):** "sweep / grab" are used together; the wick defines the sweep. No "run" is defined.
- **AMBIGUOUS:** "sweep" means the generic move in V1-art but the slow reversal pattern in V1-AI. Speed (slow vs fast) has no OHLC definition.

**Layer 2: proposed detector event naming (B0, NOT approved).**
- Event names: **BSL_SWEEP / SSL_SWEEP**, named by pool side. The naming itself is LQ-17, **OPEN**.
- A close beyond changes the pool state to **TAKEN**. Whether TAKEN is also emitted as a named event, such as RUN, is **OPEN** (LQ-10).
- **No separate GRAB event is proposed.**
- The existing BOS covers only the latest swing (D4). So a close through an **older** pool makes it TAKEN without any BOS.

**Layer 3: proposed detector behaviour (B0, NOT approved).**
- One S-wick test (LS-S01, LQ-08), whatever the speed or the number of candles.
- In V1-art's vocabulary that pattern corresponds to a "grab"; in V2's, to a "sweep" or "grab".
- That correspondence describes what B0 computes. **It is not a decision that grab and sweep are the same concept.**

**Alternatives for the open taxonomy (none chosen):**
- (a) one sweep event type (wick, close back) plus the TAKEN state, with no separate GRAB event; this is what B0 computes for now
- (b) three events, with grab vs sweep separated by candle count (1 candle = grab, more = sweep)
- (c) a RUN event or attribute, following V1-AI's body ≥ 2× rule

**Unresolved (OPEN, owner approval needed):**
- **LQ-10:** is GRAB a synonym for SWEEP or a distinct concept / event? Should RUN be a separate event?
- **LQ-11:** the RUN momentum criterion (relevant only if LQ-10 adds RUN).
- **LQ-17:** event naming.

## 9. Sweep followed by reclaim
- **TEACHES:**
  - V1-art: entry at the close back inside.
  - V3-art: confirmation is a close beyond the **trigger low**. That is a *different* level from the swept one: the low of the move that broke the high.
- **Alternatives:**
  - (a) the same-candle close back inside (built into S-wick)
  - (b) a close back inside within N candles after a close beyond (S-multi)
  - (c) V3: a close beyond the opposite trigger level
- **Example:** LS03 has c18 close 100 (< 101, so BOS + CHoCH), then c19 close 102 (> 101). Under (b) this is a reclaim. Under the approved CHoCH code it is **O4_UNRESOLVED** (failed CHoCH), because the code has no rule for it.
- **B0:** (a) only. Reclaim is analysed in RECLAIM_RULE_ANALYSIS.md.
- **Unresolved:** LQ-12.

## 10. Sweep without reclaim
- Under S-wick, a wick beyond **with a close beyond** is not a sweep. It is a TAKE / RUN, and a BOS if the pool is the latest swing (LS02).
- Under S-multi, a close beyond that never returns within N candles is also a TAKE.
- **INFERENCE:** a sweep "without reclaim" only exists under S-any or S-multi. Under B0 the phrase describes a TAKE.
- **Unresolved:** LQ-08.

## 11. Sweep followed by displacement
- **TEACHES:** V3-meta: displacement = buyers / sellers took control; this is the reversal setup's confirmation step. Neither V1-art nor V2 requires it.
- **Task constraint:** do not make displacement mandatory for the sweep.
- **Alternatives:**
  - (a) none
  - (b) an attribute measured after the sweep: body ≥ k × median body of the previous N candles, or range ≥ k × ATR, within M candles
  - (c) V3-art: a close beyond the trigger level (a structural break)
- **Example:** LS08 has the sweep at c18 (low 100, close 102), then c19 = 102 / 112 / 101.5 / 111.5, a body of 9.5 vs prior bodies of 1–5.
- **B0:** (a) for the event; (b) as a **separate, later annotation**, with parameters chosen before any backtest.
- **Unresolved:** LQ-13.

## 12. Multiple pools swept by one candle
- **INFERENCE:** in LS05, one wick crosses SSL 101 and SSL 98.
- **Alternatives:**
  - (a) one sweep event per pool, sharing a group id
  - (b) one event against the deepest pool
  - (c) one event against the nearest pool
- **Relation to D3:** for CHoCH, the protected level is responsible and other levels are evidence. For sweeps there is no "protected" role.
- **B0:** (a).
- **Unresolved:** LQ-14.

## 13. Repeated sweeps of the same pool
- **Example:** LS06 wicks below 101 at c18 (close 102) and again at c19 (low 100.5, close 102.5).
- **Alternatives:**
  - (a) one SWEEP per pool (as BOS-005); later wicks are diagnostics
  - (b) an event per sweep
  - (c) an event per sweep only after the pool was "re-armed" (price left it by X)
- **B0:** (a).
- **Unresolved:** LQ-15.

## 14. Invalidated or consumed pools
- **B0:** a TAKEN pool (close beyond) is inactive. A later wick through its price is **not** a sweep of that pool.
- **Example:** in LS02, 101 is TAKEN at c18. Wicks back above 101 afterwards are the O4 / reclaim question, not sweeps.
- **Alternative:** "flip": a taken SSL becomes resistance (BSL-like). That is not taught in the inspected sources (COMMON).
- **Unresolved:** LQ-06, LQ-16.

## 15. Newly confirmed swings and liquidity pools
- **D5 already decides one part:** a swing confirmed at candle k is not usable on candle k.
- **B0:** a pool from a swing confirmed at k is active from k + 1.
- **Example:** in LS10 the sweep wick at c18 becomes swing low 100 (confirmed at c20), so it is a pool from c21.
- **Example:** in MED01 an EQH candidate's tie window closes at c6. Under LQ-03 it would be usable from c7.

## 16. Bullish and bearish symmetry
- **INFERENCE:** every rule must mirror (p → 200 − p in the fixtures, as for CHD02 and CHD11).
- **Example:** LS04m, the mirror of LS04, is a sweep of SSL 84 (low 83, close 85) in a bearish structure.
- **Naming (AMBIGUOUS):** "bullish sweep" = an SSL sweep (a potential bullish reversal) in V3, but some authors name it by the wick direction.
- **B0:** name events by **pool side** (BSL_SWEEP / SSL_SWEEP) to avoid this.
- **Unresolved:** LQ-17 (naming).

## 17. Liquidity inducement
- **TEACHES:**
  - V1-AI only: a counter-trend move takes internal liquidity, then the trend continues.
  - V1-art: small bounces bait early entries.
- **Testable:** only once internal / external (LQ-05) and "trend continuation" are defined. It is a multi-event pattern (sweep of an internal pool + later BOS), not a primitive event.
- **B0:** not modelled.
- **Unresolved:** LQ-18.

## 18. Trendline and range-based liquidity
- **TEACHES:**
  - V2-tx 5:05: trendlines and channels.
  - V1-AI: trendline liquidity is harder to read.
  - V2-tx 3:47: repeated support / resistance.
- **Alternatives:**
  - (a) a trendline through two or more confirmed swings of one kind, with a tolerance
  - (b) a range = the high / low of N candles
  - (c) a repeated S/R = two or more swings in a band
- **False positives:** many possible lines per chart (choice explosion); the tolerance is arbitrary.
- **Testable:** only with a fixed fitting rule. High overfitting risk.
- **B0:** excluded. The plain-horizontal "repeated level" variant is covered by LQ-03(d).
- **Unresolved:** LQ-19.

---

## Where the three instructors differ (do not merge)

| Point | V1 (Mind Math Money) | V2 (Quantsapp) | V3 (Justin Bennett) |
|---|---|---|---|
| Sweep vs grab | V1-art: sweep = the movement; grab = pierce + reversal. V1-AI: slow vs fast. | Same thing ("grab", not "trap") | Used together |
| Wick vs close | Wick + close back = grab; close beyond + follow-through = breakout | **Not stated** | Wick = sweep; a **later close beyond the trigger low** = confirmation |
| Reversal requirement | Implied by "grab" | Rejection candle at a POI (engulfing) | Mandatory for the setup (step 3) |
| Where liquidity sits | Swing highs / lows, round numbers, equal levels, trendlines | Repeated S/R, trendlines, channels, equal lows | Highs inside the OTE zone, "established" highs |
| Relation to CHoCH | – | – | A sweep reversal confirms **before** a CHoCH |
| Evidence offered | Examples | Garbled examples, no prices | Two R-multiples (anecdotal) |
