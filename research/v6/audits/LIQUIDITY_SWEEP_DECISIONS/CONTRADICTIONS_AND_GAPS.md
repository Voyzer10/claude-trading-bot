# Contradictions and missing definitions in the liquidity spec

Every item names the exact places that disagree or are silent, and the decision that settles it.

**Status update, 22 Nov 2026.** Owner decisions recorded in `LQ_DECISION_REGISTER.md` settle some items **in this register**.
The source documents in `research/v6/specs/liquidity_sweep/` and the CHoCH specifications are unchanged, so they still show
the old state; that is traceability (§E), not a new contradiction.

**Status update, 23 Nov 2026.** Delegated MVP decisions (OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT
IMPLEMENTED; trading spec Section 17, CK-15) settle some items **for the initial PAPER-ONLY MVP only**; the broader
questions stay open where stated. Item status values:
- **RESOLVED IN REGISTER:** settled by an owner decision; the decision is named.
- **APPROVED:** a missing definition supplied by an owner decision (verbatim text in the register).
- **PARTLY SETTLED:** part settled, the rest named and open.
- **RESOLVED FOR MVP SCOPE:** settled for the initial MVP by a delegated decision (23 Nov 2026); the broader question
  may stay open (named).
- **OPEN:** not settled. Nothing is resolved silently.

## A. Contradictions (two documents say different things)

| ID | Item | Where | The disagreement | Settled by | Status |
|---|---|---|---|---|---|
| **C-1** | Are equal-level pools part of B0? | README "Proposed experimental baseline B0" vs UNRESOLVED_DECISIONS LQ-03 and LIQUIDITY_CONCEPT_ANALYSIS §3 | README lists "equal-level pools" under **Excluded** from B0. LQ-03 gives as its B0 proposal "A separate exact-tie EQ pool type, unscored until decided", and concept §3 has a "B0:" line describing that candidate. | LQ-03 | **RESOLVED FOR MVP SCOPE** (delegated, 23 Nov 2026): equal-high / equal-low pools are excluded from the initial MVP until separately specified. LQ-03 itself stays OPEN |
| **C-2** | When does an EQ candidate exist? | LIQUIDITY_CONCEPT_ANALYSIS §3 and §15 vs LIQUIDITY_POOL_RULE_MATRIX LP-04 §B and LQ-03 | Concept §3: the candidate "confirms when the tie window closes (the `window_closed_index`)"; §15: "Under LQ-03 it would be usable from c7" (the **last** window close, c6, + 1). LP §B lists **first vs last** window close as an open question, and LQ-03 says "No algorithm is proposed: … creation time … open". | LQ-03 (creation-time item) | **OPEN** (LQ-03 OPEN) |
| **C-3** | Is close == P a B0 sweep or unresolved? | SWEEP_RULE_MATRIX LS-S01 edge column, EVENT_ORDERING table (LS09), SYNTHETIC_DATASET_PLAN LS09, concept §7 vs TEST_CASE_CATALOG LT-10 and UNRESOLVED LQ-08 / CHU04 | LS-S01: "close == P counts as a sweep, because it is not a strict close beyond (ties to CHU04, OPEN)"; LS09 lists `SSL_SWEEP(101)` as the B0 outcome. LT-10 calls the same case UNSCORED (CHU04 / LQ-08). So B0 takes a position on a sub-case that it also declares dependent on an open CHoCH decision. | CHU04, then LQ-08 | **RESOLVED IN REGISTER** (2026-11-22): CHU04 STRICT (close == protected level → NO_CHOCH, protected swing not consumed) and the LQ-08 equality sub-case ("Wick penetrates P and close == P counts as SWEEP"). LS-S01 and LS09 agree; LT-10 in the source still says UNSCORED (§E). |
| **C-4** | "Flip after take" appears in two decisions | UNRESOLVED LQ-06 (alternatives: "First sweep consumes; flip after take") and LQ-16 (alternative: "Flip to the opposite side") | The same option is listed under two decision IDs, so it could be approved in one and rejected in the other. | LQ-06 and LQ-16 together | **RESOLVED IN REGISTER** (2026-11-22): LQ-06 "ACTIVE → SWEPT → TAKEN" and LQ-16 "TAKEN pool becomes inactive; no automatic flip". Both reject the flip. |
| **C-5** | Status of the displacement annotation | UNRESOLVED LQ-13 vs LIQUIDITY_CONCEPT_ANALYSIS §11 | LQ-13 B0: "Not part of the sweep; **optional** later annotation". Concept §11 B0: "(a) for the event; (b) as a separate, later annotation". So it is unclear whether the annotation is part of B0 or only a possible extension. | LQ-13 | **OPEN** (LQ-13 now PARTIALLY APPROVED by delegated decision: displacement is not required for setup qualification; whether it becomes a separate later annotation is still open) |

## B. Overlaps (one question spread over several decisions)

| ID | Overlap | Decisions | Risk | Status |
|---|---|---|---|---|
| **O-1** | An age filter for "major" pools is also an expiry rule | LQ-02 (alternative "A size or age filter") and LQ-07 ("N candles") | Two parameters for one effect | **RESOLVED FOR MVP SCOPE** (delegated, 23 Nov 2026): no major / minor distinction (LQ-02) and no expiry merely due to elapsed time (LQ-07); other expiry forms stay OPEN |
| **O-2** | Repeated levels | LQ-03 (d) "≥ 2 swings in a band" and LQ-19 "repeated S/R" (concept §18 says LQ-03 (d) covers the horizontal variant) | One rule approved twice under different names | **RESOLVED FOR MVP SCOPE** (delegated, 23 Nov 2026): equal-level pools and range / repeated-level liquidity are both excluded from the initial MVP (LQ-03 note, LQ-19); LQ-03 stays OPEN |
| **O-3** | Naming of new event types | LQ-10 (whether GRAB / RUN exist) and LQ-17 (naming) | Naming approved before the event set exists | **PARTLY SETTLED**: LQ-17 approves the sweep names (BSL_SWEEP / SSL_SWEEP); names for any GRAB / RUN event wait for the open part of LQ-10. GRAB / RUN is excluded from the initial MVP (delegated, 23 Nov 2026) |
| **O-4** | Reclaim vs failed CHoCH | LQ-12 (R1) and O4 (CHoCH) | The research itself says to decide them together (RECLAIM_RULE_ANALYSIS) | **PARTLY SETTLED** (MVP scope, delegated, 23 Nov 2026): no reclaim condition beyond LQ-08 is required (LQ-12 PARTIALLY APPROVED); R1 reclaim semantics and O4 stay OPEN |

## C. Missing definitions (no source document defines them)

Owner text for every APPROVED row is recorded verbatim in `LQ_DECISION_REGISTER.md` ("Supporting definitions").

| ID | Missing definition | Where it is needed | Notes | Status |
|---|---|---|---|---|
| **G-1** | Exact meaning of "ACTIVE as of k−1" | LS-S01 ("pool ACTIVE as of k−1") vs LP-01 (`active_from = confirmed_index + 1`) and EVENT_ORDERING ("pools active from conf + 1 ≤ k") | The intent seems to be that a pool whose swing confirmed at k−1 is evaluated on k. The wording "ACTIVE as of k−1" could be read as excluding it. | **APPROVED**: "Evaluate pools confirmed before candle k; emit event at candle k close." |
| **G-2** | The **group id** of same-candle events | LQ-14 / LS-S07 ("shared group id") | No format or scope: does it cover only sweeps or also TAKEN on the same candle (an outside bar), and one side or both sides? | **APPROVED**: format "sweep:<side>:<k>". ~~Not specified: the <side> token and the base of k (§F).~~ Resolved 23 Nov 2026 (delegated, OQ-4): `<side>` is exactly `BSL` or `SSL`; `k` is the globally zero-based candle index. Group membership: same-candle same-side sweeps share one id (LQ-14); opposite sides get different ids (the `<side>` component); whether TAKEN events and REPEAT_SWEEP diagnostics belong to a group stays **OPEN** |
| **G-3** | Pool id for non-swing pools | LP-02 defines `"pool:" + swing_id` | No id for EQ candidates (LQ-03), round-number pools (LP-10) or trendline pools (LQ-19) | **OPEN** (depends on LQ-03, which is OPEN; LQ-19 is APPROVED by delegated decision as excluded / not modelled for the MVP). Not needed for the initial MVP: EQ, trendline and range pools are excluded (delegated, 23 Nov 2026) |
| **G-4** | Gap opens beyond a pool | LP §C ("a gap open beyond a pool is neither a wick sweep nor a clean close-through test") | B0 classifies only by high / low / close, so a gap through a level is just TAKEN (close beyond) or a sweep. Whether the open matters is undefined (BOS-006, O7). | **APPROVED**: "Open price has no role in B0 sweep classification." |
| **G-5** | Frequency of REPEAT_SWEEP | LS-S06 / LQ-15 | One diagnostic per repeat candle, or once per episode? (The CHoCH side has a known "O4 diagnostic spam" issue, audit R-3.) | **APPROVED**: "At most one REPEAT_SWEEP diagnostic per pool per qualifying candle." |
| **G-6** | Liquidity event ids and invalidation | none | No stable-id / invalidation rule for liquidity events, the counterpart of CHoCH O8 | **APPROVED** (principle): "Stable, traceable pool and event identifiers." ~~No format specified (§F).~~ Formats decided 23 Nov 2026 (delegated, OQ-4): pool `pool:<swing_id>`; liquidity event `liquidity:<pool_id>:<event_type>:<k>` (`SWEEP`, `REPEAT_SWEEP`, `TAKEN`). Invalidation of liquidity events: not covered, stays OPEN |
| **G-7** | Pools while the structure is UNKNOWN / TRANSITION | implicit in B0 (pools depend only on swings) | No document states it explicitly. Under B0, pools exist in every state, because LS-S09 keeps the layers independent. | **APPROVED**: "Pools exist independently of market structure state." |
| **G-8** | Equality and precision of `P` comparisons | LQ-03 §B ("exact equality vs tick-rounded vs tolerance"), LQ-09 | Raw float comparison is used by the approved code; tick rounding (BOS-006 / C1) is open | **APPROVED** (interim): "Raw float comparisons for B0 pending BOS-006 resolution." BOS-006 / C1 stays OPEN. |
| **G-9** | Concept not in the register | VIDEO_SOURCE_NOTES V1 53:58 "high vs low resistance liquidity" (V1-AI) | No LQ decision covers it. Either add one or record it as out of scope. | **OPEN** |
| **G-10** | Pool zone sources disagree | VIDEO_SOURCE_NOTES V2 7:10–8:26 (one POI zone uses high / low, another open / close) | Relevant only if LQ-04 picks a zone | **OPEN**, not separately decided. LQ-04 approved the wick extreme, so it does not affect B0. |
| **G-11** | O9 edge | SWEEP_RULE_MATRIX §B item 4 | A pool already TAKEN while the CHoCH layer still treats its level as protected. It is documented and unscored, but no rule says how the two layers should report it. | **APPROVED**: "Liquidity and CHoCH layers report independently, including TAKEN pool vs protected structure-level coexistence." O9 itself (initial chronology) stays OPEN. |

## D. Not contradictions (checked)

- **BOS consumption vs pool TAKEN** (LP-12 / LP-05): the spec separates the two concepts explicitly, with §A T1–T8. This
  is consistent, and the owner approved the pool part of LP-12 (2026-11-22).
- **Sweep vs BOS on one level / candle** (LS-S10): mutually exclusive for any d ≥ 0. This is consistent with the
  approved strict BOS close, LQ-09 (d = 0) and CHU04 STRICT.
- **WICK_ONLY vs sweep** (LS-S09 §B): the asymmetry (WICK_ONLY every time, the sweep once, REPEAT_SWEEP after) is
  documented, and LT-16 is one-directional. This is consistent with LQ-15 and G-5.
- **LQ-21 vs the approved harness:** consistent. Emission at the reading candle is what `no_lookahead_violations`
  requires.

## E. Source-vs-register traceability (22 Nov 2026)

The owner decisions are recorded **in this review register only**. The documents below were intentionally not changed, so
they still show the earlier state. This is expected traceability, not an inconsistency in any approved decision.

| ID | Source location (unchanged) | What it still shows | Register state |
|---|---|---|---|
| T-1 | `specs/liquidity_sweep/UNRESOLVED_DECISIONS.md` | "Nothing here is approved"; every LQ row as unresolved | LQ-01, 04, 06, 08, 09, 14, 15, 16, 17, 21, 22 APPROVED; LQ-10 PARTIALLY APPROVED. Since 23 Nov 2026 (delegated, MVP scope): LQ-02, 05, 18, 19 APPROVED; LQ-07, 12, 13 PARTIALLY APPROVED |
| T-2 | `specs/liquidity_sweep/README.md` | B0 described as a proposed experimental baseline | Tier 1–3 B0 decisions approved |
| T-3 | `specs/liquidity_sweep/SWEEP_RULE_MATRIX.md` LS-S01 edge column, LS-S05 | "(ties to CHU04, **OPEN**)"; d = 0 "only the proposed B0 value" | CHU04 APPROVED; LQ-08 equality sub-case and LQ-09 APPROVED |
| T-4 | `specs/liquidity_sweep/TEST_CASE_CATALOG.md` | LT-10 UNSCORED (CHU04 / LQ-08); B0 rows SCORABLE-IF-B0 | LT-10 decided in the register; B0 rows decided, not yet executable (no detector) |
| T-5 | `specs/choch_v0_9/PHASE1_2_DECISIONS.md` lines 5, 24, 58, 161; `specs/choch_v0_9/README.md` and `AUDIT_CHD01-09.md` CHU04 rows | CHU04 unresolved / "needs an owner decision" | CHU04 APPROVED (external owner decision, STRICT) |
| T-6 | `scanner_v6/structure/choch.py` docstring and the `EXACT_LEVEL_CLOSE` diagnostic text | "CHU04 unresolved" | CHU04 APPROVED; see N-1 |
| T-7 | `research/v6/audits/LIQUIDITY_SWEEP_BLIND_TEST/` (historical audit, preserved) | Liquidity items PROVISIONAL (B0) or UNRESOLVED | Historical record of the state before 22 Nov 2026 |

## F. Technical implementation notes (not yet verified; they do not change any decision)

| ID | Note |
|---|---|
| N-1 | CHU04: the existing CHoCH code already compares strictly and, on equality, emits no CHoCH and leaves the protected swing unconsumed. Its diagnostic is named `EXACT_LEVEL_CLOSE`; the decision text says NO_CHOCH. |
| N-2 | Equality is raw-float `==` (G-8, interim). The comparison basis (raw float vs tick-rounded) is BOS-006 / C1, still OPEN; the data model has no tick size. |
| N-3 | A candle with close == protected level **and** a wick beyond: the CHoCH code reports `EXACT_LEVEL_CLOSE` only, not also `WICK_ONLY`. Under LQ-08 the liquidity layer records it as a SWEEP. |
| N-4 | LQ-10 "B0 uses SWEEP and TAKEN only": ~~whether TAKEN is an emitted event or only a pool-state change, and its event name, are not specified (LQ-17 names the sweep events only).~~ Resolved 23 Nov 2026 (delegated, OQ-4): TAKEN is emitted as a distinct event (event type `TAKEN`, with pool side and pool id) and changes the pool state to TAKEN; sweep names stay `BSL_SWEEP` / `SSL_SWEEP`. Whether TAKEN is also a named RUN event stays with the open part of LQ-10. Not implemented. |
| N-5 | G-2 "sweep:<side>:<k>": ~~the <side> token and whether k is 0- or 1-based are not specified.~~ Resolved 23 Nov 2026 (delegated, OQ-4): `BSL` / `SSL`, zero-based `k`. Group membership of TAKEN / REPEAT_SWEEP: OPEN. Not implemented. |
| N-6 | G-6: ~~no format for liquidity event ids; pool ids exist only as LP-02 `"pool:" + swing_id`.~~ Resolved 23 Nov 2026 (delegated, OQ-4): `pool:<swing_id>` and `liquidity:<pool_id>:<event_type>:<k>`; identical ids for identical inputs, no random UUIDs. Not implemented. |
| N-7 | No liquidity detector or liquidity test exists (`scanner_v6/liquidity/*` are docstring-only stubs). Implementation needs separate owner authorization. |
