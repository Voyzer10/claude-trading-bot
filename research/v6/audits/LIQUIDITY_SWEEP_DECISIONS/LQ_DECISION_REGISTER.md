# LQ Decision Register: V6 Liquidity Sweep (LQ-01 to LQ-22)

**Decision register.** Owner decisions of **2026-11-22** and delegated MVP decisions are recorded here; the source documents in `research/v6/specs/liquidity_sweep/` are unchanged.

- **LQ decisions (LQ-01…LQ-22):** 15 APPROVED, 4 PARTIALLY APPROVED, 1 PROPOSED, 2 OPEN; of these, 4 APPROVED and 3 PARTIALLY APPROVED by delegated decision (2026-11-23).
- **External owner decisions (outside LQ):** 1 APPROVED (CHU04). Counted separately, never added to the LQ counts.

Status values:
- **APPROVED:** explicit owner decision, recorded verbatim with its date.
- **OWNER APPROVED — DELEGATED DECISION:** an APPROVED or PARTIALLY APPROVED decision finalized under the owner's
  delegated authority for the initial PAPER-ONLY MVP; documented, not implemented (marked per decision).
- **PARTIALLY APPROVED:** part of the decision is approved (stated verbatim); the remaining part is named and stays OPEN.
- **PROPOSED:** B0 has a concrete proposal; not approved.
- **OPEN:** no concrete proposal, or B0 is a placeholder, "not modelled" or "excluded"; not approved.

Question, B0 proposal and alternatives are copied **verbatim** from `UNRESOLVED_DECISIONS.md` (checked by the generator:
22 / 22 rows match). **No liquidity detector is implemented** (see "Technical implementation not yet verified").

## What is fixed and what is not

| Layer | Status | Content |
|---|---|---|
| Existing approved structure rules (earlier phases) | **APPROVED** | Swings SW-001…005 (L2/R2 strict, equal levels are not swings), BOS-001…005, Option A, D4, D5 order, CHoCH A1–A10 / D1–D3, D2 P-B, A5, no-look-ahead harness |
| External owner decision | **APPROVED** (2026-11-22) | CHU04 STRICT (see "External owner decisions") |
| Owner-approved liquidity decisions | **APPROVED** (2026-11-22) | LQ-01, LQ-04, LQ-06, LQ-08, LQ-09, LQ-14, LQ-15, LQ-16, LQ-17, LQ-21, LQ-22; supporting rules LS-S02, LS-S09, LS-S11, LP-12 pool part; definitions G-1, G-2, G-4, G-5, G-6, G-7, G-8, G-11 |
| Delegated MVP decisions | **OWNER APPROVED — DELEGATED DECISION** (2026-11-23) | APPROVED: LQ-02, LQ-05, LQ-18, LQ-19. PARTIALLY APPROVED: LQ-07, LQ-12, LQ-13 |
| Partially approved | **PARTIALLY APPROVED** | LQ-10 (GRAB / RUN taxonomy (a GRAB / SWEEP split, and whether TAKEN is also a named RUN event) remains OPEN.); LQ-07 (Expiry by any other rule (session, replacement by a newer same-side swing, cap per side, only pools near price) remains OPEN.); LQ-12 (R1 reclaim after a close beyond, as an event, to be decided together with O4, remains OPEN.); LQ-13 (Whether displacement becomes a separate later annotation (C-5) remains OPEN.) |
| Still proposed / open | **PROPOSED / OPEN** | LQ-03, LQ-11, LQ-20; definitions G-3, G-9, G-10 |
| Invariants derived from approved rules | INV (not new rules) | LP-01 (pool known only from swing confirmation + 1), LP-11 (no swing → no pool in the first L / last R candles), LS-S10 (S-wick sweep and BOS are mutually exclusive on one level / candle) |
| Technical implementation | **NOT VERIFIED** | No detector, no liquidity tests (see the last section) |

Base series used in examples: B17 = CHD01 c1-c17: swings L98 (c4, conf c6), H109 (c7, conf c9), L101 (c10, conf c12), H116 (c14, conf c16); BOS up c12; BULLISH from c17, protected HL 101. Bearish examples mirror prices (p → 200 − p).

## Summary

| ID | Decision | Status | B0 proposal (short) | Owner decision (short) |
|---|---|---|---|---|
| [LQ-01](#lq-01) | Which levels are pools | **APPROVED** | Every confirmed L2/R2 swing (BSL = highs, SSL = lows) | Every confirmed L2/R2 swing creates a liquidity pool. |
| [LQ-02](#lq-02) | Major vs minor pools | **APPROVED** | No distinction | (delegated) Initial V6 MVP does not distinguish major/minor pools. |
| [LQ-03](#lq-03) | Equal highs / lows as pools | **OPEN** | A separate exact-tie EQ pool type, unscored until decided | MVP note only |
| [LQ-04](#lq-04) | Pool price or zone | **APPROVED** | The wick extreme | Pool price equals the exact wick extreme, not a zone. |
| [LQ-05](#lq-05) | Internal vs external | **APPROVED** | Not modelled | (delegated) Initial V6 MVP does not separately classify internal/external liquidity. |
| [LQ-06](#lq-06) | Pool lifecycle | **APPROVED** | ACTIVE → SWEPT → TAKEN | ACTIVE → SWEPT → TAKEN. |
| [LQ-07](#lq-07) | Pool expiry | **PARTIALLY APPROVED** | None (placeholder only; expiry stays OPEN) | (delegated) Pools do not expire merely due to elapsed time. |
| [LQ-08](#lq-08) | Sweep definition | **APPROVED** | S-wick: `high > P` and `close ≤ P` (BSL; mirrored for SSL) | S-wick definition: BSL: high > P AND close <= P. SSL: low < P AND close >= P. LQ-08 equality sub-case: Wick penetrates P and close == P counts as SWEEP. Close s… |
| [LQ-09](#lq-09) | Minimum penetration depth | **APPROVED** | d = 0, i.e. a strict `>` / `<` beyond P | d = 0; strict penetration. |
| [LQ-10](#lq-10) | Sweep / grab / run taxonomy | **PARTIALLY APPROVED** | B0 detector behaviour: one sweep event type (BSL_SWEEP / SSL_SWEEP) for the wick-and-close-back patt… | B0 uses SWEEP and TAKEN only. GRAB/RUN taxonomy remains OPEN. |
| [LQ-11](#lq-11) | Run momentum criterion | **OPEN** | Not used (only relevant if LQ-10 adds a RUN event or attribute) | MVP note only |
| [LQ-12](#lq-12) | Reclaim after a close beyond (R1) | **PARTIALLY APPROVED** | Not in B0; decide together with O4 | (delegated) No additional reclaim condition is required beyond the approved LQ-08 sweep definition. |
| [LQ-13](#lq-13) | Displacement | **PARTIALLY APPROVED** | Not part of the sweep; optional later annotation | (delegated) Displacement is not required for initial setup qualification. |
| [LQ-14](#lq-14) | Several pools on one candle | **APPROVED** | One event per pool, shared group id | One event per pool, shared group ID for same-candle events. |
| [LQ-15](#lq-15) | Repeated sweeps | **APPROVED** | One SWEEP per pool, plus REPEAT_SWEEP diagnostics | One initial SWEEP event per pool; later qualifying candles emit REPEAT_SWEEP diagnostics. |
| [LQ-16](#lq-16) | Taken pools | **APPROVED** | Inactive | TAKEN pool becomes inactive; no automatic flip. |
| [LQ-17](#lq-17) | Event naming | **APPROVED** | BSL_SWEEP / SSL_SWEEP (by pool side) | Event names based on pool side: BSL_SWEEP / SSL_SWEEP. |
| [LQ-18](#lq-18) | Inducement | **APPROVED** | Not modelled (a composite pattern) | (delegated) Inducement, trendlines, ranges and channel liquidity are excluded from initial MVP. |
| [LQ-19](#lq-19) | Trendline / range / channel liquidity | **APPROVED** | Excluded | (delegated) Inducement, trendlines, ranges and channel liquidity are excluded from initial MVP. |
| [LQ-20](#lq-20) | Where V3's reversal confirmation lives | **PROPOSED** | A later entry / setup layer, not the sweep event | – |
| [LQ-21](#lq-21) | Late-reading rules | **APPROVED** | Emitted at their own candle, never back-dated | Emit events on their actual detection candle. Never backdate. |
| [LQ-22](#lq-22) | Protected-swing sweep and the CHoCH machine | **APPROVED** | No | Liquidity sweep does not change CHoCH/structure state. |

Counts, LQ decisions: 15 APPROVED, 4 PARTIALLY APPROVED, 1 PROPOSED, 2 OPEN.

Of which by delegated decision: 4 APPROVED and 3 PARTIALLY APPROVED by delegated decision (2026-11-23).

Counts, external owner decisions: 1 APPROVED (CHU04).

---

## LQ-01

**Which levels are pools** · Status: **APPROVED** · Evidence (source tags): V1-meta / V1-AI, V2-tx, V1-art

**Owner decision (2026-11-22, verbatim):**

> Every confirmed L2/R2 swing creates a liquidity pool.

**Unresolved question (verbatim, source):** Which levels are pools?

**Proposals / options in the source (verbatim):**
- B0: Every confirmed L2/R2 swing (BSL = highs, SSL = lows)
- Alternatives: Major only; round numbers; order-book data

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: every confirmed swing | Pool detection: one pool per confirmed swing (a dual-pivot candle gives two). Events: every swing level can produce SWEEP / TAKEN. Lifecycle: from conf + 1 (LP-01). Structure: none (pools reuse approved swings; no swing rule changes). |
| Major only | Pool detection: fewer pools, but 'major' has no definition yet (ties to LQ-02 / LQ-05). Events: fewer, larger events. |
| Round numbers | Pool detection: pools without a swing; needs a step size per instrument (LP-10 ALT). Events: sweeps of levels the structure layer never sees. |
| Order-book data | Not available from OHLC; not testable (concept §1 (d)). |

**Minimal OHLC example:** B17: BSL 116 (H c14) exists from c17; SSL 101 (L c10) from c13; SSL 98 (L c4) from c7 (concept §1, §2).

**Dependencies:** LQ-02 (major / minor) refines it; LQ-03 (EQ pools are a separate type); LQ-04 (what the pool price is); LQ-05 (internal / external labels); approved SW-001..005 and D5 (already fixed)

**Pre-approval research note (RESEARCH-SUPPORTED):** B0 option (a) every confirmed swing: the concept analysis rates it 'objective and causal' and the only fully testable option (§1 'Testable: (a) yes'). This is a restatement of the existing analysis, not an approval.

**Spec references:** UNRESOLVED_DECISIONS LQ-01; LIQUIDITY_POOL_RULE_MATRIX LP-02, LP-10; LIQUIDITY_CONCEPT_ANALYSIS §1, §2, §4

---

## LQ-02

**Major vs minor pools** · Status: **APPROVED** · Evidence (source tags): V1-AI (internal / external)

**Owner decision — DELEGATED DECISION (2026-11-23, verbatim; OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT IMPLEMENTED):**

> Initial V6 MVP does not distinguish major/minor pools.

Scope: Initial V6 PAPER-ONLY MVP. Exclusions are MVP scope decisions, not claims that the broader concepts are invalid.

**Unresolved question (verbatim, source):** Major vs minor pools

**Proposals / options in the source (verbatim):**
- B0: No distinction
- Alternatives: A size or age filter; higher-timeframe swings

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: no distinction | Pool detection: all swings equal. Events: minor highs inside consolidation also give sweeps (concept §1 false positives). |
| Size or age filter | Pool detection: a parameter removes pools; overlaps the expiry question (LQ-07). Events: fewer. Must be fixed before results (repo rule). |
| Higher-timeframe swings | Pool detection: needs a second timeframe and its own no-look-ahead alignment; not designed anywhere in the spec. |

**Minimal OHLC example:** B17: H109 (c7) and H116 (c14) would both be BSL pools under B0; nothing in the spec says which is 'major'.

**Dependencies:** LQ-01; LQ-05 (major ≈ external?); LQ-07 (age filter overlaps expiry)

**Pre-approval research note (NONE):** The research gives no criterion for 'major'; only V1-AI (unverified AI summary) mentions it.

**Spec references:** UNRESOLVED_DECISIONS LQ-02; LIQUIDITY_CONCEPT_ANALYSIS §1 (b)

---

## LQ-03

**Equal highs / lows as pools** · Status: **OPEN** · Evidence (source tags): V1-art, V1-AI, V2-tx (all teach EQ as strong liquidity)

**MVP scope note:** Equal-high/equal-low pools remain excluded from the initial MVP until separately specified (delegated, 2026-11-23). The B0 proposal (a separate EQ pool type) is not approved; LQ-03 stays OPEN.

**Unresolved question (verbatim, source):** Equal highs / lows as pools

**Proposals / options in the source (verbatim):**
- B0: A separate exact-tie EQ pool type, **unscored until decided**. It is never a swing (SW-004 unchanged). **No algorithm is proposed:** tie window, number of observations, creation time, SW-004 interaction and no-look-ahead are all open (LIQUIDITY_POOL_RULE_MATRIX §B).
- Alternatives: No pool; tolerance band; ≥ 2 swings in a band; a wider look-back for separated equal highs

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| No pool (concept (a)) | Pool detection: EQ levels ignored (consistent with SW-004). Events: the most-taught pool type produces nothing; separated equal highs that are each strict swings are still two LP-02 pools at one price. |
| Exact-tie EQ type (B0 candidate, (b)) | Pool detection: a liquidity-only object from the `unresolved_equal_levels` diagnostic; creation time, grouping, merge with a same-price swing all open (§B). Lifecycle: needs its own activation time. Structure: none (must never feed BOS / CHoCH). |
| Tolerance band (c) | Pool detection: merges near-equal levels; new free parameter (overfitting risk; fix before results). |
| ≥ 2 swings in a band (d) | Pool detection: causal (needs swings first); overlaps LQ-19 'repeated S/R'. |
| Wider look-back | Pool detection: detects separated double tops, which the L/R-window diagnostic cannot; a new parameter. |

**Minimal OHLC example:** EQ01 = MED01: equal highs 105 at c3 / c4 (tie windows close c5 / c6); c8 h106 c105, c9 h107 c104, c11 close 107. Under (b): c8, c9 sweeps (c9 repeat), c11 TAKEN; under (a): no liquidity event (concept §3).

**Dependencies:** LQ-01; LQ-07 (similar-price pools, §C); LQ-09 / BOS-006 C1 (equality, tick precision); LQ-14 (several pools on one candle); LQ-19 (repeated levels); approved SW-004 (fixed)

**Pre-approval research note (RESEARCH-SUPPORTED (procedural only)):** Keep EQ unscored until every §B item is decided; if a tolerance is chosen, fix it before looking at results (concept §3 'Testable', LP §B). No option is recommended.

**Spec references:** UNRESOLVED_DECISIONS LQ-03; LIQUIDITY_POOL_RULE_MATRIX LP-04, §B; LIQUIDITY_CONCEPT_ANALYSIS §3, §15; TEST_CASE_CATALOG LT-07, LT-08

---

## LQ-04

**Pool price or zone** · Status: **APPROVED** · Evidence (source tags): –

**Owner decision (2026-11-22, verbatim):**

> Pool price equals the exact wick extreme, not a zone.

**Unresolved question (verbatim, source):** Pool price or zone

**Proposals / options in the source (verbatim):**
- B0: The wick extreme
- Alternatives: Wick-to-body zone

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: wick extreme (single price) | Pool detection: P = the approved swing price, so pool and BOS reference share one number (needed for LP-12 / LS-S10). Events: S-wick and TAKEN are single comparisons. |
| Wick-to-body zone | Pool detection: a band [body edge, wick extreme]. Events: needs new definitions of 'beyond' and 'close back' relative to a zone; LS-S10 (sweep and BOS mutually exclusive) would no longer follow automatically. |

**Minimal OHLC example:** B17: SSL from L c10 = 101 (wick low); its body low is 102 (c10 o103 c102). Under a zone the pool would be 101-102.

**Dependencies:** LQ-08 and LQ-09 are defined relative to P; LP-12 / LS-S10 rely on P = swing price

**Pre-approval research note (RESEARCH-SUPPORTED):** Wick extreme: LP-03 bases it on the approved swing price, and LS-S10 / LP-12 consistency depends on P being that price. The only zone source (V2) is internally inconsistent (VIDEO_SOURCE_NOTES).

**Spec references:** UNRESOLVED_DECISIONS LQ-04; LIQUIDITY_POOL_RULE_MATRIX LP-03; LIQUIDITY_CONCEPT_ANALYSIS §4; VIDEO_SOURCE_NOTES V2 7:10-8:26 (zone inconsistency)

---

## LQ-05

**Internal vs external** · Status: **APPROVED** · Evidence (source tags): V1-AI only

**Owner decision — DELEGATED DECISION (2026-11-23, verbatim; OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT IMPLEMENTED):**

> Initial V6 MVP does not separately classify internal/external liquidity.

Scope: Initial V6 PAPER-ONLY MVP. Exclusions are MVP scope decisions, not claims that the broader concepts are invalid.

**Unresolved question (verbatim, source):** Internal vs external

**Proposals / options in the source (verbatim):**
- B0: Not modelled
- Alternatives: Tie to the CHoCH A1 "external" definition (still open)

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: not modelled | Pool detection: pools unlabelled. Events: no internal / external attribute; LQ-18 (inducement) impossible. |
| Tie to A1 | Pool detection: a label per pool from the external-structure definition, which does not exist yet (CHoCH A1 gap). Structure: shares one definition with CHoCH. |

**Minimal OHLC example:** Not useful until A1 exists (no executable definition of 'external structure').

**Dependencies:** CHoCH A1 (open, outside LQ); LQ-02; LQ-18 depends on it

**Pre-approval research note (RESEARCH-SUPPORTED (defer)):** Concept §5: testable only once 'external structure' is defined; keep not modelled until A1 is decided.

**Spec references:** UNRESOLVED_DECISIONS LQ-05; LIQUIDITY_POOL_RULE_MATRIX LP-08; LIQUIDITY_CONCEPT_ANALYSIS §5

---

## LQ-06

**Pool lifecycle** · Status: **APPROVED** · Evidence (source tags): INFERENCE

**Owner decision (2026-11-22, verbatim):**

> ACTIVE → SWEPT → TAKEN.

**Unresolved question (verbatim, source):** Pool lifecycle

**Proposals / options in the source (verbatim):**
- B0: ACTIVE → SWEPT → TAKEN
- Alternatives: First sweep consumes; flip after take

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: ACTIVE → SWEPT → TAKEN | Lifecycle: a swept pool stays usable; a later close beyond takes it (T3). Events: SWEEP once, REPEAT_SWEEP later (LQ-15), TAKEN by close. Structure: none; BOS consumption is a separate approved rule (LP-12). |
| First sweep consumes | Lifecycle: SWEPT = inactive. Events: no REPEAT_SWEEP; a later close beyond is no longer a TAKEN of that pool. T2 / T3 disappear. |
| Flip after take | Lifecycle: TAKEN pool becomes an opposite-side pool (same as LQ-16 ALT). Events: new sweeps of flipped levels; not taught in the sources. |

**Minimal OHLC example:** LS06: c18 104/105/100/102 then c19 102/103/100.5/102.5 on B17. B0: SSL101 SWEPT c18, REPEAT_SWEEP c19. 'First sweep consumes': SWEPT c18, nothing at c19.

**Dependencies:** LQ-08 (what a sweep is); LQ-10 (whether TAKEN is a named event); LQ-15, LQ-16 depend on it; LP-12 (BOS consumption is separate; approved BOS-005 / D4)

**Pre-approval research note (NONE):** Basis is INFERENCE only; no source decides it.

**Spec references:** UNRESOLVED_DECISIONS LQ-06; LIQUIDITY_POOL_RULE_MATRIX LP-05, LP-12, §A (T1-T8); LIQUIDITY_CONCEPT_ANALYSIS §6, §14

---

## LQ-07

**Pool expiry** · Status: **PARTIALLY APPROVED** · Evidence (source tags): none taught

**Owner decision — DELEGATED DECISION (2026-11-23, verbatim; OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT IMPLEMENTED):**

> Pools do not expire merely due to elapsed time.

Scope: Initial V6 PAPER-ONLY MVP. Exclusions are MVP scope decisions, not claims that the broader concepts are invalid.

**Still OPEN within this decision:** Expiry by any other rule (session, replacement by a newer same-side swing, cap per side, only pools near price) remains OPEN.

**Unresolved question (verbatim, source):** Pool expiry

**Proposals / options in the source (verbatim):**
- B0: None (**placeholder only; expiry stays OPEN**). The consequences of no expiry (stale levels, similar prices, newer same-side swings, sessions, accumulation) are analysed in LIQUIDITY_POOL_RULE_MATRIX §C.
- Alternatives: N candles; session; replaced by a newer same-side swing; cap per side; only pools near price

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| No expiry (placeholder) | Pool detection: unbounded growth; stale and similar-price pools stay ACTIVE. Events: one large candle can produce many sweeps. |
| N candles / session | Lifecycle: an EXPIRED-like end state the B0 state set does not have (ACTIVE/SWEPT/TAKEN only). Session option depends on O7 / BOS-006. |
| Replaced by newer same-side swing | Lifecycle: older pool removed when a newer swing confirms beyond it; interacts with D4 (BOS uses only the latest swing). |
| Cap per side / only pools near price | Pool detection: needs a cap or distance parameter (fix before results). |

**Minimal OHLC example:** B17 + a wick far later through SSL 98 (L c4): under no expiry it is a sweep however old (LT-13, case 'to be generated'; unscored).

**Dependencies:** LQ-06 (needs an end state); LQ-02 (age filter overlap); LQ-03 / LQ-14 (similar prices); O7 and BOS-006 (sessions, gaps; outside LQ)

**Pre-approval research note (RESEARCH-SUPPORTED (procedural only)):** Any expiry parameter must be fixed before looking at results (LP §C testing note). No option is recommended; 'none' is explicitly a placeholder.

**Spec references:** UNRESOLVED_DECISIONS LQ-07; LIQUIDITY_POOL_RULE_MATRIX LP-07, §C; TEST_CASE_CATALOG LT-13

---

## LQ-08

**Sweep definition** · Status: **APPROVED** · Evidence (source tags): V1-art, V3 (wick); V2 silent

**Owner decision (2026-11-22, verbatim):**

> S-wick definition:
> BSL: high > P AND close <= P.
> SSL: low < P AND close >= P.
> LQ-08 equality sub-case: Wick penetrates P and close == P counts as SWEEP.
> Close strictly beyond P means TAKEN, not SWEEP.

**Unresolved question (verbatim, source):** Sweep definition

**Proposals / options in the source (verbatim):**
- B0: **S-wick:** `high > P` and `close ≤ P` (BSL; mirrored for SSL)
- Alternatives: S-any; S-multi (close beyond, then back within N)

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: S-wick | Events: exact complement of the approved close-beyond BOS / CHoCH rule, so a sweep and a BOS on one level and candle are impossible (LS-S10). Lifecycle: close beyond → TAKEN. Structure: a sweep of the protected swing coincides with the approved WICK_ONLY diagnostic. |
| S-any | Events: every BOS candle is also a sweep (double count, LS-S03). Lifecycle: TAKEN / SWEPT distinction blurs. |
| S-multi | Events: needs look-back relabelling (emitted late); overlaps O4 failed CHoCH and LQ-12 R1. Structure: an already-emitted BOS / CHoCH would coexist with a later 'sweep'. |

**Minimal OHLC example:** LS01: B17 + c18 104/105/100/102 → S-wick sweep of SSL 101 (approved code: WICK_ONLY). LS02: c18 104/105/99/100 → close beyond: TAKEN + BOS + CHoCH, no sweep. LS09: c18 104/105/100/101 → close == P (see contradictions C-3).

**Dependencies:** LQ-04 (P); LQ-09 (depth); CHU04 (close == P; outside LQ; APPROVED external owner decision, STRICT, 2026-11-22); O4 and LQ-12 (S-multi); LQ-06, LQ-10, LQ-13, LQ-15, LQ-22 build on it

**Pre-approval research note (RESEARCH-SUPPORTED):** S-wick (= reclaim reading R0): taught by V1-art and V3 (wick defines the sweep), causal, no extra parameter (RECLAIM 'B0 = R0 only'). The close == P sub-case should follow CHU04, not be decided here.

**Spec references:** UNRESOLVED_DECISIONS LQ-08; SWEEP_RULE_MATRIX LS-S01, LS-S03, LS-S04, LS-S10; LIQUIDITY_CONCEPT_ANALYSIS §7, §10; RECLAIM_RULE_ANALYSIS R0 / R1

---

## LQ-09

**Minimum penetration depth** · Status: **APPROVED** · Evidence (source tags): none taught

**Owner decision (2026-11-22, verbatim):**

> d = 0; strict penetration.

**Unresolved question (verbatim, source):** Minimum penetration depth

**Proposals / options in the source (verbatim):**
- B0: d = 0, i.e. a strict `>` / `<` beyond P. **This is only the proposed B0 value, NOT an approved rule.** LS-S01 depends on it (SWEEP_RULE_MATRIX LS-S05).
- Alternatives: Ticks; price; ATR fraction

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: d = 0 (strict) | Events: a touch (high == P) is no sweep; any strict pierce is. Matches the approved strict BOS comparison. |
| Ticks / price / ATR fraction | Events: shallow pierces become 'no event'; adds a parameter (instrument- or volatility-dependent). LS-S10 still holds for any d ≥ 0. |

**Minimal OHLC example:** X2-type touch: high exactly 116 with close below (no sweep under d = 0). B17 + c18 104/105/100.9/102 vs SSL 101: a 0.1 pierce is a sweep under d = 0, not under d = 0.25.

**Dependencies:** LQ-04; BOS-006 / C1 tick precision (outside LQ); LQ-08 uses it; LQ-03 (equality); LQ-19 (tolerance)

**Pre-approval research note (NONE):** No source teaches a depth; d = 0 is only the proposed value.

**Spec references:** UNRESOLVED_DECISIONS LQ-09; SWEEP_RULE_MATRIX LS-S01, LS-S05

---

## LQ-10

**Sweep / grab / run taxonomy** · Status: **PARTIALLY APPROVED** · Evidence (source tags): V1-art vs V1-AI disagree; V2 and V3 use the words together

**Owner decision (2026-11-22, verbatim):**

> B0 uses SWEEP and TAKEN only. GRAB/RUN taxonomy remains OPEN.

**Still OPEN within this decision:** GRAB / RUN taxonomy (a GRAB / SWEEP split, and whether TAKEN is also a named RUN event) remains OPEN.

**MVP scope note:** GRAB/RUN taxonomy is excluded from initial MVP (delegated, 2026-11-23). The GRAB / RUN part stays OPEN.

**Unresolved question (verbatim, source):** Sweep / grab / run taxonomy

**Proposals / options in the source (verbatim):**
- B0: B0 **detector behaviour:** one sweep event type (BSL_SWEEP / SSL_SWEEP) for the wick-and-close-back pattern, plus a pool state change to TAKEN. No GRAB event. **Still OPEN:** whether to add a GRAB / SWEEP split, and whether TAKEN is also emitted as a named RUN event. Instructor terminology is recorded separately and is not a rule (SWEEP_RULE_MATRIX §A).
- Alternatives: Split by speed or candle count (LS-S12); a RUN event or attribute

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: one sweep type + TAKEN state | Event classification: a single wick-and-close-back event; a close beyond changes state only. |
| GRAB / SWEEP split (candle count or speed) | Event classification: two event types; 'speed' has no OHLC definition (concept §8 AMBIGUOUS); a candle-count split needs multi-candle look-back (overlaps S-multi / O4). |
| RUN event or attribute | Event classification: TAKEN becomes an emitted event or carries a momentum attribute (needs LQ-11). |

**Minimal OHLC example:** LS07: B17 + c18 104/117/100/116.5 → SSL_SWEEP 101 and BSL 116 TAKEN (+ BOS). Under a RUN event, c18 would also emit RUN(116).

**Dependencies:** LQ-08; LQ-06; LQ-11 depends on it; LQ-17 (naming)

**Pre-approval research note (NONE):** Sources disagree (V1-art vs V1-AI); the spec keeps the split open.

**Spec references:** UNRESOLVED_DECISIONS LQ-10; SWEEP_RULE_MATRIX LS-S12, §A; LIQUIDITY_CONCEPT_ANALYSIS §8

---

## LQ-11

**Run momentum criterion** · Status: **OPEN** · Evidence (source tags): V1-AI only (unverified)

**MVP scope note:** Its B0 makes it relevant only if LQ-10 adds a RUN event or attribute; GRAB/RUN is excluded from the initial MVP (delegated, 2026-11-23). LQ-11 stays OPEN.

**Unresolved question (verbatim, source):** Run momentum criterion

**Proposals / options in the source (verbatim):**
- B0: Not used (only relevant if LQ-10 adds a RUN event or attribute)
- Alternatives: Body ≥ 2× the previous (V1-AI)

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: not used | No effect. |
| Body ≥ 2× previous | Event classification: a RUN attribute on TAKEN candles; one parameter (2×) from an unverified AI summary. |

**Minimal OHLC example:** LS07 c18 body 12.5 (104 → 116.5) vs B17 c17 body 3 (107/108/103/104): ratio 4.2 → 'RUN' under the 2× rule.

**Dependencies:** LQ-10 (only relevant if RUN exists)

**Pre-approval research note (RESEARCH-SUPPORTED (defer)):** Decide only after LQ-10; the only source is unverified (V1-AI).

**Spec references:** UNRESOLVED_DECISIONS LQ-11; LIQUIDITY_CONCEPT_ANALYSIS §8 (c)

---

## LQ-12

**Reclaim after a close beyond (R1)** · Status: **PARTIALLY APPROVED** · Evidence (source tags): V1-AI; approved code gives O4_UNRESOLVED

**Owner decision — DELEGATED DECISION (2026-11-23, verbatim; OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT IMPLEMENTED):**

> No additional reclaim condition is required beyond the approved LQ-08 sweep definition.

Scope: Initial V6 PAPER-ONLY MVP. Exclusions are MVP scope decisions, not claims that the broader concepts are invalid.

**Still OPEN within this decision:** R1 reclaim after a close beyond, as an event, to be decided together with O4, remains OPEN.

**Unresolved question (verbatim, source):** Reclaim after a close beyond (R1)

**Proposals / options in the source (verbatim):**
- B0: Not in B0; decide **together with O4**
- Alternatives: Window N candles

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: not modelled | Events: none; the approved code records O4_UNRESOLVED and changes nothing. |
| Window N (R1) | Events: a RECLAIM at the close-back candle j ≤ k + N (emitted at j, no repaint). Lifecycle: a TAKEN pool would need a new transition. Structure: the earlier BOS / CHoCH stays; the same situation as O4 failed CHoCH. |

**Minimal OHLC example:** LS03: B17 + c18 104/105/99/100.5 (BOS + CHoCH, 101 TAKEN), c19 100.5/103/100/102 (close back above 101): approved code O4_UNRESOLVED; R1 would call c19 a reclaim.

**Dependencies:** O4 (outside LQ; must be decided together); LQ-08 (S-multi alternative); LQ-06 / LQ-16 (TAKEN state); LQ-21 (emission-time principle, decide first)

**Pre-approval research note (RESEARCH-SUPPORTED):** RECLAIM_RULE_ANALYSIS: R1 should be decided together with O4 so that one rule governs both.

**Spec references:** UNRESOLVED_DECISIONS LQ-12; RECLAIM_RULE_ANALYSIS R1; LIQUIDITY_CONCEPT_ANALYSIS §9; TEST_CASE_CATALOG LT-11

---

## LQ-13

**Displacement** · Status: **PARTIALLY APPROVED** · Evidence (source tags): V3 (setup step)

**Owner decision — DELEGATED DECISION (2026-11-23, verbatim; OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT IMPLEMENTED):**

> Displacement is not required for initial setup qualification.

Scope: Initial V6 PAPER-ONLY MVP. Exclusions are MVP scope decisions, not claims that the broader concepts are invalid.

**Still OPEN within this decision:** Whether displacement becomes a separate later annotation (C-5) remains OPEN.

**Unresolved question (verbatim, source):** Displacement

**Proposals / options in the source (verbatim):**
- B0: Not part of the sweep; optional later annotation
- Alternatives: Body or range multiple of ATR within M candles

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: not required | Events: the sweep is emitted at its own candle whatever follows. |
| Annotation (body / range multiple within M) | Events: an attribute added later (emitted at its own candle, LQ-21); parameters k, N, M fixed before any backtest. |

**Minimal OHLC example:** LS08: B17 + c18 104/105/100/102 (sweep), c19 102/112/101.5/111.5 (body 9.5 vs prior bodies 1-5).

**Dependencies:** LQ-08; LQ-21 (emission-time principle, decide first)

**Pre-approval research note (RESEARCH-SUPPORTED):** Not required for the sweep: a task constraint, and V3 treats displacement as a setup step (LS-S08). Annotation parameters only after a separate decision.

**Spec references:** UNRESOLVED_DECISIONS LQ-13; SWEEP_RULE_MATRIX LS-S08; LIQUIDITY_CONCEPT_ANALYSIS §11; TEST_CASE_CATALOG LT-04

---

## LQ-14

**Several pools on one candle** · Status: **APPROVED** · Evidence (source tags): INFERENCE

**Owner decision (2026-11-22, verbatim):**

> One event per pool, shared group ID for same-candle events.

**Unresolved question (verbatim, source):** Several pools on one candle

**Proposals / options in the source (verbatim):**
- B0: One event per pool, shared group id
- Alternatives: Deepest only; nearest only

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: one event per pool + group id | Events: n events with a shared group; counts inflate when pools cluster (LP §C). |
| Deepest only / nearest only | Events: one per candle; other pools' states must still be defined (swept or untouched?) - not specified. |

**Minimal OHLC example:** LS05: B17 + c18 104/105/96/102 → SSL_SWEEP 101 and SSL_SWEEP 98 (one group) under B0; deepest-only → 98 only; nearest-only → 101 only.

**Dependencies:** LQ-01; LQ-03 / LQ-07 (similar-price pools); LQ-08

**Pre-approval research note (NONE):** INFERENCE only. Note the missing group-id definition (gap G-2).

**Spec references:** UNRESOLVED_DECISIONS LQ-14; SWEEP_RULE_MATRIX LS-S07; LIQUIDITY_CONCEPT_ANALYSIS §12; TEST_CASE_CATALOG LT-05

---

## LQ-15

**Repeated sweeps** · Status: **APPROVED** · Evidence (source tags): INFERENCE

**Owner decision (2026-11-22, verbatim):**

> One initial SWEEP event per pool; later qualifying candles emit REPEAT_SWEEP diagnostics.

**Unresolved question (verbatim, source):** Repeated sweeps

**Proposals / options in the source (verbatim):**
- B0: One SWEEP per pool, plus REPEAT_SWEEP diagnostics
- Alternatives: An event per sweep; re-arm distance

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: one SWEEP + REPEAT_SWEEP diagnostics | Events: mirrors BOS-005 (one event per reference); repeats are diagnostics. Structure: asymmetric with WICK_ONLY, which fires every time (LS-S09 §B). |
| An event per sweep | Events: every wick-and-close-back is an event; WICK_ONLY and sweeps align one-to-one for the protected pool. |
| Re-arm distance | Events: a new event only after price left the level by X; a new parameter. |

**Minimal OHLC example:** LS06: c18 104/105/100/102, c19 102/103/100.5/102.5 → SWEEP c18, REPEAT_SWEEP c19 (B0).

**Dependencies:** LQ-06 (SWEPT stays usable); LQ-08; LQ-22 (WICK_ONLY asymmetry)

**Pre-approval research note (NONE):** INFERENCE ('mirrors BOS-005'); no source.

**Spec references:** UNRESOLVED_DECISIONS LQ-15; SWEEP_RULE_MATRIX LS-S06, §B; TEST_CASE_CATALOG LT-06, LT-16

---

## LQ-16

**Taken pools** · Status: **APPROVED** · Evidence (source tags): COMMON, not taught here

**Owner decision (2026-11-22, verbatim):**

> TAKEN pool becomes inactive; no automatic flip.

**Unresolved question (verbatim, source):** Taken pools

**Proposals / options in the source (verbatim):**
- B0: Inactive
- Alternatives: Flip to the opposite side

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: inactive | Lifecycle: TAKEN is terminal; later trades at P are nothing (T7). |
| Flip | Pool detection: a new opposite-side pool at P after a take; events against flipped levels. |

**Minimal OHLC example:** LS11: B17 + c18 104/105/99/100 (101 TAKEN), c19 100/101/99.5/100.5: no sweep of 101 (TAKEN; also high 101 not > 101).

**Dependencies:** LQ-06 (same 'flip' alternative appears there, see C-4); LQ-12 (reclaim after take)

**Pre-approval research note (NONE):** 'Flip' is COMMON, not taught in the inspected sources.

**Spec references:** UNRESOLVED_DECISIONS LQ-16; LIQUIDITY_POOL_RULE_MATRIX LP-06; LIQUIDITY_CONCEPT_ANALYSIS §14; TEST_CASE_CATALOG LT-12

---

## LQ-17

**Event naming** · Status: **APPROVED** · Evidence (source tags): sources conflict

**Owner decision (2026-11-22, verbatim):**

> Event names based on pool side: BSL_SWEEP / SSL_SWEEP.

**Unresolved question (verbatim, source):** Event naming

**Proposals / options in the source (verbatim):**
- B0: BSL_SWEEP / SSL_SWEEP (by pool side)
- Alternatives: "Bullish / bearish sweep"

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: by pool side | Event classification: unambiguous (side of the level). |
| Bullish / bearish | Event classification: ambiguous - V3 names an SSL sweep 'bullish' (expected reaction), others by wick direction. |

**Minimal OHLC example:** LS04 BSL_SWEEP(116) = a potential bearish reaction; LS04m SSL_SWEEP(84) = a potential bullish reaction.

**Dependencies:** LQ-10 (names of any GRAB / RUN events)

**Pre-approval research note (RESEARCH-SUPPORTED):** Name by pool side: concept §16 chooses it to avoid the documented bullish / bearish naming conflict.

**Spec references:** UNRESOLVED_DECISIONS LQ-17; SWEEP_RULE_MATRIX header; LIQUIDITY_CONCEPT_ANALYSIS §16

---

## LQ-18

**Inducement** · Status: **APPROVED** · Evidence (source tags): V1-AI only

**Owner decision — DELEGATED DECISION (2026-11-23, verbatim; OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT IMPLEMENTED):**

> Inducement, trendlines, ranges and channel liquidity are excluded from initial MVP.

Scope: Initial V6 PAPER-ONLY MVP. Exclusions are MVP scope decisions, not claims that the broader concepts are invalid.

**Unresolved question (verbatim, source):** Inducement

**Proposals / options in the source (verbatim):**
- B0: Not modelled (a composite pattern)
- Alternatives: Internal sweep + later BOS

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: not modelled | No effect. |
| Internal sweep + later BOS | Event classification: a multi-event pattern (needs internal labels LQ-05 and a continuation definition). |

**Minimal OHLC example:** Not useful until LQ-05 exists.

**Dependencies:** LQ-05; LQ-08; LQ-10

**Pre-approval research note (RESEARCH-SUPPORTED (defer)):** Concept §17: testable only once internal / external and 'trend continuation' are defined.

**Spec references:** UNRESOLVED_DECISIONS LQ-18; LIQUIDITY_CONCEPT_ANALYSIS §17

---

## LQ-19

**Trendline / range / channel liquidity** · Status: **APPROVED** · Evidence (source tags): V2-tx, V1-AI

**Owner decision — DELEGATED DECISION (2026-11-23, verbatim; OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT IMPLEMENTED):**

> Inducement, trendlines, ranges and channel liquidity are excluded from initial MVP.

Scope: Initial V6 PAPER-ONLY MVP. Exclusions are MVP scope decisions, not claims that the broader concepts are invalid.

**Unresolved question (verbatim, source):** Trendline / range / channel liquidity

**Proposals / options in the source (verbatim):**
- B0: Excluded
- Alternatives: A fitting rule with tolerance; N-bar range

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: excluded | No effect. |
| Fitting rule with tolerance / N-bar range | Pool detection: non-horizontal or range pools; choice explosion and a tolerance parameter (high overfitting risk). |

**Minimal OHLC example:** Not useful without a fixed fitting rule.

**Dependencies:** LQ-01; LQ-03 (d) covers the horizontal 'repeated level' variant; LQ-09 (tolerance)

**Pre-approval research note (RESEARCH-SUPPORTED (defer)):** Concept §18: testable only with a fixed fitting rule; high overfitting risk.

**Spec references:** UNRESOLVED_DECISIONS LQ-19; LIQUIDITY_POOL_RULE_MATRIX LP-09; LIQUIDITY_CONCEPT_ANALYSIS §18

---

## LQ-20

**Where V3's reversal confirmation lives** · Status: **PROPOSED** · Evidence (source tags): V3-art

**Unresolved question (verbatim, source):** Where V3's reversal confirmation (close beyond the trigger low) lives

**Proposals / options in the source (verbatim):**
- B0: A later entry / setup layer, not the sweep event
- Alternatives: Part of `liquidity/reclaim.py`

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: entry / setup layer | Event classification: the sweep stays a primitive event; R2 is a strategy step using another level (trigger low). |
| liquidity/reclaim.py | Event classification: reclaim mixes a strategy level with liquidity events; closer to an early CHoCH / BOS. |

**Minimal OHLC example:** V3: after a wick sweep of a high, a close below the trigger low (low of the leg that broke the high) confirms; no OHLC case in the spec.

**Dependencies:** LQ-12 (reclaim scope); entry/ layer design (not started)

**Pre-approval research note (RESEARCH-SUPPORTED):** RECLAIM_RULE_ANALYSIS: R2 belongs to a later setup / entry layer, not to liquidity/reclaim.py.

**Spec references:** UNRESOLVED_DECISIONS LQ-20; RECLAIM_RULE_ANALYSIS R2

---

## LQ-21

**Late-reading rules** · Status: **APPROVED** · Evidence (source tags): no-look-ahead harness

**Owner decision (2026-11-22, verbatim):**

> Emit events on their actual detection candle. Never backdate.

**Unresolved question (verbatim, source):** Late-reading rules (R1, displacement)

**Proposals / options in the source (verbatim):**
- B0: Emitted at their own candle, never back-dated
- Alternatives: –

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: emitted at own candle | Events: no repaint; consistent with the approved no-look-ahead harness and replay_audit. |

**Minimal OHLC example:** LS08: the displacement at c19 would be emitted at c19, never attached to the c18 sweep event.

**Dependencies:** constrains LQ-12 and LQ-13 (decide first: it fixes when any late-reading rule may emit)

**Pre-approval research note (RESEARCH-SUPPORTED):** Follows the approved no-look-ahead principle (engine harness, D5). No alternative is listed.

**Spec references:** UNRESOLVED_DECISIONS LQ-21; EVENT_ORDERING_ANALYSIS

---

## LQ-22

**Protected-swing sweep and the CHoCH machine** · Status: **APPROVED** · Evidence (source tags): approved A6

**Owner decision (2026-11-22, verbatim):**

> Liquidity sweep does not change CHoCH/structure state.

**Unresolved question (verbatim, source):** Does a sweep of the protected swing affect the CHoCH machine?

**Proposals / options in the source (verbatim):**
- B0: No. The CHoCH layer alone owns the state and records WICK_ONLY (approved). The liquidity layer emits its own sweep event and pool-state change and never writes the structure state. Asymmetry: WICK_ONLY fires on every such candle; the sweep fires only on the first, later ones are REPEAT_SWEEP (SWEEP_RULE_MATRIX §B).
- Alternatives: –

**What each option would change:**

| Option | Pool detection / event classification / lifecycle / structure |
|---|---|
| B0: no effect on state | Structure: unchanged (approved A6 already gives WICK_ONLY = NO_CHOCH). Events: a liquidity event and a CHoCH diagnostic on the same candle from two modules. |

**Minimal OHLC example:** LS01: B17 + c18 104/105/100/102 → WICK_ONLY (approved) + SSL_SWEEP 101 (B0); state stays BULLISH, protected 101.

**Dependencies:** LQ-08; LQ-15 (asymmetry); approved A6 (fixed); O9 edge (outside LQ)

**Pre-approval research note (RESEARCH-SUPPORTED):** Consistent with approved A6; only the CHoCH layer owns the state (LS-S09 §B rule 1).

**Spec references:** UNRESOLVED_DECISIONS LQ-22; SWEEP_RULE_MATRIX LS-S09, §B; TEST_CASE_CATALOG LT-16

---

## Supporting B0 rules without their own LQ id

| Rule | Content (spec) | Owner decision (2026-11-22, verbatim) | Status | Linked decisions |
|---|---|---|---|---|
| LS-S02 | Close strictly beyond → the pool is TAKEN, not swept | Close strictly beyond pool price means TAKEN. | APPROVED (owner, 2026-11-22) | LQ-06, LQ-10 |
| LS-S09 | The liquidity layer never changes the structure state and never emits BOS or CHoCH | Liquidity layer cannot modify structure state or emit BOS/CHoCH. | APPROVED (owner, 2026-11-22) | LQ-22 |
| LS-S11 | A sweep of one side plus a BOS of the other side on the same candle is allowed (outside bar) | Opposite-side sweep and BOS may occur on the same candle. | APPROVED (owner, 2026-11-22) | LQ-08, LQ-14 |
| LP-12 (pool part) | Pool TAKEN by its own rule LS-S02, separate from BOS reference consumption (BOS-005 / D4, approved) | Pool TAKEN and BOS reference consumption are separate concepts. | APPROVED (pool part: owner, 2026-11-22; consumption part: earlier, BOS-005 / D4) | LQ-06 |

## Supporting definitions (gaps G-1…G-11)

| ID | Status | Owner decision (2026-11-22, verbatim) | Note |
|---|---|---|---|
| G-1 | **APPROVED** | Evaluate pools confirmed before candle k; emit event at candle k close. | Settles the LS-S01 wording "ACTIVE as of k−1" in line with LP-01 (active from confirmation + 1). |
| G-2 | **APPROVED** | Shared group ID format "sweep:<side>:<k>". | Exact format decided 2026-11-23 (delegated decision, OQ-4): <side> is exactly BSL or SSL; k is the globally zero-based candle index (also CK-9). Group membership: several pools swept on the same candle and the same side share one id (LQ-14); opposite sides get different ids (the <side> component). Whether TAKEN events and REPEAT_SWEEP diagnostics belong to a sweep group is not settled: OPEN. Not implemented. |
| G-3 | **OPEN** | – | Pool ids for non-swing pools (EQ, round numbers, trendlines). Depends on LQ-03 (OPEN) and LQ-19 (APPROVED by delegated decision 2026-11-23 as excluded / not modelled for the MVP). Not needed for the initial MVP; stays OPEN beyond it. |
| G-4 | **APPROVED** | Open price has no role in B0 sweep classification. | – |
| G-5 | **APPROVED** | At most one REPEAT_SWEEP diagnostic per pool per qualifying candle. | – |
| G-6 | **APPROVED** | Stable, traceable pool and event identifiers. | Principle approved 2026-11-22. Exact formats decided 2026-11-23 (delegated decision, OQ-4): pool id pool:<swing_id>; liquidity event id liquidity:<pool_id>:<event_type>:<k> with event_type SWEEP, REPEAT_SWEEP or TAKEN; same inputs give identical ids, no random UUIDs. Not implemented. |
| G-7 | **APPROVED** | Pools exist independently of market structure state. | – |
| G-8 | **APPROVED** | Raw float comparisons for B0 pending BOS-006 resolution. | Interim: BOS-006 / C1 stays OPEN. |
| G-9 | **OPEN** | – | "High vs low resistance liquidity" (VIDEO_SOURCE_NOTES V1 53:58) has no LQ decision. |
| G-10 | **OPEN** | – | V2 zone inconsistency. Not separately decided; it only mattered if LQ-04 chose a zone, and LQ-04 approved the wick extreme. |
| G-11 | **APPROVED** | Liquidity and CHoCH layers report independently, including TAKEN pool vs protected structure-level coexistence. | – |

The full gap descriptions are in `CONTRADICTIONS_AND_GAPS.md` §C.

## External owner decisions (outside LQ)

Recorded here only. They are prerequisites of LQ decisions, not LQ decisions, and are not counted with them.

### CHU04: APPROVED — OWNER DECISION

- Decision ID: CHU04
- Decision: STRICT
- Approval date: 2026-11-22
- Scope: CHoCH close comparison against the protected level
- Rationale: consistency with BOS-001…005
- Equality: Equality ("close == protected_level") produces NO_CHOCH and does not consume the protected swing.

Owner decision (verbatim):

> - Bullish structure: CHoCH only when "close < protected_low".
> - Bearish structure: CHoCH only when "close > protected_high".
> - If "close == protected_level", emit "NO_CHOCH".
> - Equality does not consume or invalidate the protected swing.
> - Rationale: maintain consistency with approved BOS-001…005 strict-close semantics.

Recorded in: this review register only; the original CHoCH specifications are unchanged (source-vs-register traceability: `CONTRADICTIONS_AND_GAPS.md` §E).

## Items outside LQ that LQ decisions depend on

| Item | What it is |
|---|---|
| CHU04 | close == level strictness (CHoCH). **APPROVED** external owner decision (STRICT, 2026-11-22) |
| O4 | failed CHoCH (CHoCH) |
| O7 | sessions / gaps (CHoCH) |
| O9 | initial chronology (CHoCH) |
| A1 | external structure (CHoCH) |
| BOS-006 / C1 | gap / exact / tick precision (BOS) |

## Technical implementation not yet verified

- No liquidity detector exists: `scanner_v6/liquidity/*` are docstring-only stubs. Implementation needs separate owner authorization.
- No liquidity tests exist. TEST_CASE_CATALOG LT-* rows and the blind-test PROVISIONAL key entries are not yet executable or scored.
- G-2: format decided 2026-11-23 (delegated, OQ-4: <side> = BSL / SSL, zero-based k); group membership of TAKEN / REPEAT_SWEEP OPEN; not implemented.
- G-6: formats decided 2026-11-23 (delegated, OQ-4: `pool:<swing_id>`, `liquidity:<pool_id>:<event_type>:<k>`); not implemented.
- LQ-10 / LQ-17: TAKEN is emitted as a distinct event and changes the pool state to TAKEN (delegated, 2026-11-23, OQ-4); sweep event names stay BSL_SWEEP / SSL_SWEEP (LQ-17). Whether TAKEN is also a named RUN event stays with the open part of LQ-10. Not implemented.
- CHU04: the existing CHoCH code reports equality with the diagnostic `EXACT_LEVEL_CLOSE`; the decision text says NO_CHOCH. Behaviour matches (no CHoCH, protected swing kept); the label differs.
- G-8: comparisons are raw float until BOS-006 / C1 is decided; no tick size exists in the data model.
- Source documents are unchanged and still describe these items as proposed / open (see CONTRADICTIONS_AND_GAPS §E).
- Delegated MVP decisions of 2026-11-23 are documented only: NOT IMPLEMENTED, NOT TESTED.

