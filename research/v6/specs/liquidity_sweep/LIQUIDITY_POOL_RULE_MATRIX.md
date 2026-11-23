# Liquidity pool rule matrix (research, NOT approved)

**Status codes:**
- **INV:** invariant that follows from approved rules.
- **B0:** proposed experimental baseline, NOT approved.
- **ALT:** alternative.
- **OPEN:** needs an owner decision (UNRESOLVED_DECISIONS.md).

Rows changed in the Phase 1.1 audit are marked *(P1.1)*.

| ID | Rule | Status | Source / basis | Input | Condition | Output | Timing | Edge cases | Tests |
|---|---|---|---|---|---|---|---|---|---|
| LP-01 | A pool is built only from information known at or before candle k−1 when it is used on candle k | **INV** | D5 (approved 22 Nov); no-look-ahead harness | swings | `pool.active_from = swing.confirmed_index + 1` | – | – | a swing confirmed on the sweep candle | LT-NLA-*, LT-15 |
| LP-02 | BSL pool at each confirmed swing **high**; SSL pool at each confirmed swing **low** | **B0** (LQ-01) | V1-meta / V1-AI, V2-tx; INFERENCE | swings | every L2/R2 swing | `pool(id = "pool:" + swing_id, side, price = swing price)` | active from conf + 1 | dual-pivot candle → two pools | LT-01…LT-06 |
| LP-03 | Pool price = the wick extreme (high / low) | **B0** (LQ-04) | approved swing price | swing | – | single price | – | ALT: a zone from the wick to the body | – |
| LP-04 *(P1.1)* | Equal highs / lows (exact tie) as an **EQ pool candidate**, a separate type, never a swing | **OPEN** (LQ-03). The open items are listed in §B. **No algorithm is proposed.** | V1-art, V1-AI, V2-tx; approved SW-004 forbids treating them as swings | `unresolved_equal_levels` diagnostic | exact tie (see §B) | `pool(type = EQH / EQL)` | see §B | ALT: tolerance band, ≥ 2 swings in a band | LT-07, LT-08 (unscored) |
| LP-05 *(P1.1)* | Pool states: ACTIVE → SWEPT → TAKEN. The exact transitions are in §A. | **B0** (LQ-06) | INFERENCE | candles | §A | state | at the candle close, step 2L (EVENT_ORDERING) | a pool cannot be swept and taken on one candle under S-wick (the close is either beyond or not) | LT-01…LT-12 |
| LP-06 | A TAKEN pool is inactive; later trades through its price are not sweeps of it | **B0** (LQ-16) | INFERENCE | – | – | – | – | ALT: "flip" to the opposite side | LT-12 |
| LP-07 *(P1.1)* | Pools do not expire by time | **B0** (LQ-07), **expiry still OPEN**. The consequences are analysed in §C. | none taught | – | – | – | – | ALT: N-candle / session expiry; replacement by a newer same-side swing | LT-13 (unscored) |
| LP-08 | Internal / external label | **OPEN** (LQ-05) | V1-AI only | structure | needs the external-structure definition (CHoCH A1 gap) | – | – | – | – |
| LP-09 | Trendline / range / channel pools | **OPEN** (LQ-19), excluded from B0 | V2-tx, V1-AI | swings | needs a fitting rule and a tolerance | – | – | many candidate lines | – |
| LP-10 | Round-number pools | **ALT** | V1-art | price grid | step size | – | – | instrument-specific | – |
| LP-11 | The first L candles and the last R candles never create swings, so no swing-based pool exists there | **INV** | approved swing rule | – | – | – | – | "insufficient history" | LT-14 |
| LP-12 *(P1.1)* | **BOS reference consumption and pool lifecycle are separate concepts.** A BOS consumes the latest swing as a **BOS reference** (approved BOS-005 / D4; BOS module). A pool becomes TAKEN under its **own** liquidity rule LS-S02 (`close > P`). When the BOS reference and the pool belong to the same swing, both happen on the same close **because the two conditions coincide**, not because one causes the other. | consumption: approved. Pool rule: **B0** (LQ-06). The separation is a documentation clarification, not a new rule. | approved BOS-005 / D4; LS-S02 | – | – | – | – | an older pool (not the BOS reference) closed through → TAKEN with no BOS (D4) | LT-03, LT-09 |

## §A. Exact state transitions (LP-05 / LP-12), added in Phase 1.1

The B0 liquidity layer (step 2L) is evaluated on candle k against pools that are ACTIVE or SWEPT as of k−1. The BOS module is listed beside it only to show that the two are independent.

| # | Situation on candle k (BSL; SSL mirrored) | Pool state before → after (B0, liquidity layer) | Liquidity output (B0) | BOS module (approved, independent) |
|---|---|---|---|---|
| T1 | Pool ACTIVE; `high_k > P`, `close_k ≤ P` (**swept**) | ACTIVE → **SWEPT** | `BSL_SWEEP` event | Nothing (BOS needs a close beyond) |
| T2 | Pool SWEPT; `high_k > P`, `close_k ≤ P` again | SWEPT → SWEPT | `REPEAT_SWEEP` diagnostic (LS-S06) | Nothing |
| T3 | Pool **SWEPT**, then later `close_k > P` (**previously swept pool closed through**) | SWEPT → **TAKEN** | TAKEN; whether it is also a named event is LQ-10 | If this swing is still the **latest** unused high, a BOS (independent rule). A sweep does not consume the BOS reference. |
| T4 | Pool ACTIVE; `close_k > P` (**closed through directly**) | ACTIVE → **TAKEN** | TAKEN, no sweep (LS-S10) | Same as T3 |
| T5 | **A BOS occurs on the same level** (the pool's swing is the latest unused swing) | ACTIVE or SWEPT → TAKEN (by LS-S02, not by the BOS) | TAKEN | BOS emitted; the reference is consumed (BOS-005). Two outputs, two rules, one close. |
| T6 | **An older pool that is not the BOS reference** is closed through (a newer same-side swing exists) | ACTIVE or SWEPT → TAKEN | TAKEN | **No BOS** (D4: older swings are never BOS references) |
| T7 | Pool TAKEN; any later trade at P | TAKEN → TAKEN | nothing (LP-06) | – |
| T8 | Pool not yet active (its swing confirms at k or later) | – | the pool is not evaluated on k (LP-01) | the swing is not a reference on k (D5) |

**Why no contradiction can arise between the two concepts (INFERENCE, from the approved rules):**
- Before its swing confirms, no candle can close beyond the swing price: the right-window candles have lower highs (or higher lows). So a pool and its BOS reference always start together at confirmation + 1.
- After that, the only way to consume the BOS reference is `close > P`, which is also exactly T4 / T5 for the pool.
- The only asymmetric case is **T6**: the pool is TAKEN but there is no BOS. That is intended, and comes from the approved D4.

**Not decided by B0:** whether a SWEPT pool should instead become inactive (ALT "first sweep consumes", LQ-06), and whether TAKEN is a separate emitted event (LQ-10).

## §B. What an exact EQH / EQL candidate would still need (LP-04), added in Phase 1.1

**This is not an algorithm.** These are the open items that must be decided before LT-07 / LT-08 can be scored.

| Item | Current fact (approved code) | Open question |
|---|---|---|
| Tie window | `unresolved_equal_levels` reports bar i when its value **equals** at least one bar in i−L … i+R (L = R = 2), and no bar there is more extreme. | (a) Is this window enough? Taught "equal highs" (double tops) are usually **many candles apart**, outside any L/R window. Two separated equal highs that are each a strict swing are already **two LP-02 pools at the same price**; separated equal highs where one is not a strict swing are not detected at all. (b) Should a wider look-back be added? That is a new parameter. |
| Number of observations | The diagnostic returns one record per tied bar (bar 3 tied with 4, and bar 4 tied with 3, in MED01). | Is a candidate one pool per tie group or per bar? Minimum 2 bars, or 3 or more for a "stronger" pool (V1-AI's "stacked")? |
| Candidate creation time | Each record has `window_closed_index = i + R`. In MED01: bar 3 → c5, bar 4 → c6. | Is the candidate created at the **first** record's window close (c5) or the **last** (c6)? Under LP-01 it would be usable from the chosen candle + 1. |
| Interaction with SW-004 | SW-004 (approved): equal levels are **not** swings. They feed no BOS, CHoCH, protected-swing or structure logic. | An EQ pool must stay a liquidity-only object. Should a strict swing at the same price as an EQ candidate be merged with it or kept as two pools? (This links to §C, similar prices.) |
| No-look-ahead | Every record is known only after its window has fully closed (`window_closed_index`). | Any cluster rule must use only records with `window_closed_index ≤ k−1` when evaluating candle k. A later tie must not change an already-emitted candidate (repaint). |
| Equality | Raw floats are compared exactly; no tick rounding (BOS-006 / C1 precision issue is open). | Exact equality vs tick-rounded equality vs a tolerance (the tolerance alternative of LQ-03). |

## §C. Consequences of "no expiry" (LP-07), added in Phase 1.1

LQ-07 stays **OPEN**. B0 (no expiry) is only a placeholder. Under B0 these effects would occur:

| Effect | What happens under no expiry | Why it matters | Possible remedies (all ALT, undecided) |
|---|---|---|---|
| **Stale levels** | A swing from hundreds of candles ago stays ACTIVE until a close goes beyond it. | Old sweeps get the same weight as fresh ones. Instructors talk about "obvious" or "established" levels (V1, V3-meta 2:18), not arbitrary old ones. | N-candle age limit; session / day limit; a weight attribute instead of expiry |
| **Several pools at similar prices** | Each swing is its own pool (LP-02), even 0.01 apart, so one wick can sweep many of them (LS-S07). | Event counts inflate; "one sweep" in teaching terms becomes n events. | Merge within a tolerance (overlaps LQ-03); keep only the most extreme of a cluster; group id only (B0 LS-S07) |
| **Newer same-side swings** | When a newer, higher swing high forms, the older, lower high stays ACTIVE if it was never closed through. A newer swing above it does **not** imply the older one was taken, because a wick-only touch leaves it SWEPT at most. | Older pools under price can be "swept" long after they stop mattering. | Replace an older pool when a newer same-side swing confirms beyond it (LQ-07 alternative); keep only the latest k pools per side |
| **Session boundaries** | Candles are counted as given; there is no session logic (O7 is open). Overnight or weekend gaps can jump over many pools in one open. | A gap open beyond a pool is neither a wick sweep nor a clean close-through test. It interacts with BOS-006 (gap policy, open). | Expire at session end; mark gap-crossed pools separately; decide together with O7 / BOS-006 |
| **Historical accumulation** | The pool list grows with every confirmed swing that is never closed through, without bound. | Per-candle work grows with history; on a long series one large candle can produce dozens of events. | Cap the number of active pools per side; age limit; only the pools within X of the price |

**Testing note:** LT-13 (no expiry) stays **UNSCORED** until LQ-07 is decided. Any expiry parameter must be fixed **before** looking at results (repo rule: no tuning on out-of-sample data).
