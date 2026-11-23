# Sweep rule matrix (research, NOT approved)

The status codes are as in LIQUIDITY_POOL_RULE_MATRIX.md:
- **INV:** follows from approved rules.
- **B0:** proposed experimental baseline, NOT approved.
- **ALT:** alternative.
- **OPEN:** needs an owner decision.

Rows changed in the Phase 1.1 audit are marked *(P1.1)*.

**Naming:** events are named by the pool side:
- **BSL_SWEEP:** price went above a high and closed back (a potential bearish reaction).
- **SSL_SWEEP:** price went below a low and closed back (a potential bullish reaction).

This avoids the "bullish sweep" naming conflict (LQ-17, **OPEN**).

| ID | Rule | Status | Source / basis | Condition (BSL; SSL mirrored) | Output | Timing | Edge cases | Tests |
|---|---|---|---|---|---|---|---|---|
| LS-S01 *(P1.1)* | **S-wick:** wick strictly beyond and close not beyond | **B0** (LQ-08). Its depth part also depends on **LQ-09 (OPEN)**. | V1-art (long wick, close back), V3-meta / V3-art (the wick defines it) | pool ACTIVE as of k−1, `high_k > P` and `close_k ≤ P`. The strict `>` means a minimum depth of 0. **That zero depth is only the proposed B0 value, not an approved rule** (see LS-S05). | `BSL_SWEEP(pool, k)`, pool → SWEPT | close of k | close == P counts as a sweep, because it is not a strict close beyond (ties to CHU04, **OPEN**); high == P is no sweep | LT-01, LT-02, LT-10 |
| LS-S02 | Close strictly beyond → the pool is TAKEN, **not** swept | **B0** (LQ-06) | V1-art (a breakout closes beyond); same close test as the approved BOS rule | `close_k > P` | pool → TAKEN. This is computed by the liquidity layer itself. The BOS module evaluates its own rule separately (see LIQUIDITY_POOL_RULE_MATRIX §A). | close of k | Whether TAKEN is also emitted as an event (e.g. RUN) is **LQ-10 (OPEN)** | LT-03 |
| LS-S03 | S-any: any trade beyond the level | **ALT** | COMMON | `high_k > P` | – | – | double-counts BOS candles | – |
| LS-S04 | S-multi: a close beyond, then a close back inside within N candles | **ALT / OPEN** (LQ-08, O4) | V1-AI ("a later close back inside may re-label it a slow sweep") | – | – | needs look-back relabelling, so the event would be emitted late | conflicts with the approved CHoCH flow: O4 is unresolved | LT-11 (unscored) |
| LS-S05 *(P1.1)* | Minimum penetration depth d | **OPEN** (LQ-09) | none taught | `high_k − P > d` (BSL) / `P − low_k > d` (SSL); d in ticks, price or ATR fraction | – | – | **B0 proposes d = 0** (equivalent to the strict `>` in LS-S01). Not approved. A non-zero d would turn some B0 sweeps into "no event". | – |
| LS-S06 | One sweep event per pool | **B0** (LQ-15) | mirrors BOS-005 | the first S-wick on an ACTIVE pool | a repeat wick on a SWEPT pool → diagnostic `REPEAT_SWEEP` | – | ALT: an event per sweep | LT-06 |
| LS-S07 | Multiple pools on one candle → one event per pool, with a shared `group` id | **B0** (LQ-14) | INFERENCE | each pool independently | n events | – | ALT: deepest / nearest only | LT-05 |
| LS-S08 | Displacement is **not** required for a sweep | **B0** (LQ-13; also a task constraint) | V3 makes it a setup step, not part of the definition | – | – | – | a later annotation only | LT-04 |
| LS-S09 *(P1.1)* | The liquidity layer **never changes the structure state** and never emits BOS or CHoCH. A wick sweep of the **protected** swing gives two separate outputs, from two modules, about the same candle (see §B). | **B0** (LQ-22) | approved A6: wick-only = NO_CHOCH, recorded as the WICK_ONLY diagnostic | – | an SSL_SWEEP / BSL_SWEEP **event** from the liquidity layer, plus a WICK_ONLY **diagnostic** from the CHoCH layer (unchanged) | close of k | no state transition in either module; see §B for the asymmetry with REPEAT_SWEEP | LT-01, LT-09, LT-16 |
| LS-S10 | A sweep and a BOS on the **same level and candle** are impossible | **INV** given B0 | the S-wick close condition (`close ≤ P`) is the complement of the BOS close (`close > P`) | – | – | – | holds for any d ≥ 0 | LT-03 |
| LS-S11 *(P1.1)* | A sweep of one side plus a BOS of the other side on the same candle is allowed (an outside bar) | **B0** | INFERENCE | see the worked example in §C | e.g. SSL_SWEEP + bullish BOS + BSL pool TAKEN | close of k, in D5 order (§C) | – | LT-09 |
| LS-S12 *(P1.1)* | Whether instructor "grab" / "run" become **separate events or attributes** (by candle count, speed or momentum) | **OPEN** (LQ-10, LQ-11) | V1-art, V1-AI, V2-tx, V3 (they disagree) | – | – | – | B0 itself emits no GRAB or RUN event (§A); this row is the open question | – |

## §A. Terminology layers (LQ-10 vs LS-S12), added in Phase 1.1

Three different things were previously mixed under "grab is a synonym".

| Layer | What it is | Content | Status |
|---|---|---|---|
| **Instructor terminology** | Words used in the sources, recorded as-is | V1-art: sweep = the movement beyond a level; grab = pierce + reversal (long wick, close back). V1-AI: sweep = slower; grab = fast poke; run = a continuing break. V2-tx: sweep = grab. V3: "sweep / grab" used together. | Documentation only. **Not a rule.** |
| **Event naming** | The names a V6 detector would emit | B0 proposes **BSL_SWEEP / SSL_SWEEP** plus a pool state change to **TAKEN**. No GRAB event. Whether TAKEN is also emitted as a named event (e.g. RUN) is open. | B0 naming (LQ-17 OPEN); RUN event OPEN (LQ-10) |
| **Experimental detector behaviour** | What B0 would actually compute | One S-wick test (LS-S01), whatever the speed or candle count. In V1-art's words it would match a "grab"; in V2's, "sweep or grab". A close beyond → TAKEN (LS-S02). | B0 (LQ-08, LQ-06) |

**Still OPEN (LQ-10 / LQ-11):**
- whether to add a GRAB / SWEEP split, by candle count or speed;
- whether to add a RUN event or attribute (e.g. V1-AI's body ≥ 2× the previous).

Nothing in B0 resolves these. "Synonym" means only that B0 has **one** event type for the wick-and-close-back pattern.

## §B. Protected-swing wick sweep (LS-S09), added in Phase 1.1

Under B0, the protected swing (D2 / P-B origin) is a confirmed swing, so it also has a pool (LP-02).
- **Timing:** P-B activates the protected swing at its confirmation close, in force from the next candle. The pool is active from confirmation + 1. **The same candle.**
- **Example:** LS01, candle c18 = 104 / 105 / 100 / 102, pre-state BULLISH, protected HL 101.

| Module | Output on c18 | Changes state? | Status |
|---|---|---|---|
| CHoCH (approved, unchanged) | Diagnostic `WICK_ONLY` (NO_CHOCH), not an event | No | approved A6 (verified on LS01) |
| Liquidity (B0) | Event `SSL_SWEEP(pool:swing:low:9…)`; pool 101 ACTIVE → SWEPT | No (pool state only; structure untouched) | B0 |
| Structure state | stays BULLISH, protected 101 | – | approved |

**Rules for consistency (B0):**
1. Only the CHoCH layer owns the structure state. The liquidity layer reads nothing from it and writes nothing to it, so a contradiction is impossible.
2. **Asymmetry:** WICK_ONLY fires on **every** wick-only candle against the protected swing. SSL_SWEEP fires only on the **first** one (LS-S06); later ones give `REPEAT_SWEEP`.
   - Check LT-16: every sweep of the protected pool has a WICK_ONLY on the same candle.
   - A WICK_ONLY may also appear with a REPEAT_SWEEP instead of a sweep (LS06, c19).
3. A close beyond the protected swing gives a CHoCH (CHoCH layer) and the pool TAKEN (liquidity layer). Never a sweep (LS-S10).
4. **Edge, O9-linked:** CHD15 shows the structure can become BULLISH while the close is already below the protected level. Under B0 that pool was TAKEN by the earlier close, so a later wick below it is **not** a sweep (LP-06), even though the CHoCH layer still treats the level as protected. That is the O9 case; it is not scored.

## §C. Outside-bar example (LS-S11), candle by candle, added in Phase 1.1

**Data:** B17 (CHoCH fixture CHD01, c1–c17) + c18 = **104 / 117 / 100 / 116.5**.

**Facts from the approved detector:**
- Swings L 98 (c4, conf c6), H 109 (c7, conf c9), L 101 (c10, conf c12), H 116 (c14, conf c16).
- BOS ↑ c12 (ref 109) and BOS ↑ c18 (ref 116).
- WICK_ONLY at c18.
- State BULLISH, protected 101, both before and after c18.

The pool states are **B0 proposals**.

**Pool states before c18 (B0):**

| Pool | Active from | History | State before c18 |
|---|---|---|---|
| SSL 98 (L c4) | c7 | no candle low below 98 | ACTIVE |
| BSL 109 (H c7) | c10 | c12 close 110 > 109 | TAKEN at c12 |
| SSL 101 (L c10) | c13 | lows c13–c17 = 109, 112, 110, 106, 103 | ACTIVE |
| BSL 116 (H c14) | c17 | c17 high 108 | ACTIVE |

**At the close of c18 (D5 order + proposed step 2L):**

| Step | Uses | Result |
|---|---|---|
| (1) BOS | swings confirmed ≤ c17 | Latest high 116 (unused): close 116.5 > 116 → **BOS ↑ c18 (ref H c14)**. Latest low 101: close not < 101 → none. |
| (2) CHoCH | pre-state BULLISH, protected 101 | Close 116.5 is not < 101. Low 100 < 101 → **WICK_ONLY** diagnostic (NO_CHOCH). |
| (2L) Liquidity *(B0)* | pools ACTIVE as of c17 | **SSL 101:** low 100 < 101 and close 116.5 ≥ 101 → **SSL_SWEEP(101)**, pool → SWEPT. **BSL 116:** close 116.5 > 116 → pool → **TAKEN**, no sweep (LS-S10). **SSL 98:** low 100 is not < 98 → nothing. |
| (3) State | – | No change: BULLISH. (The BOS registers its P-B origin search, as approved.) |
| (4) Swings confirmed at c18 | – | None (candidate c16: low 106 is not below c17's 103, and high 112 is not above c14's 116) |

**Bearish mirror (LS07m).**
- **Data:** each price p becomes 200 − p (CHD02 c1–c17), and c18 = **96 / 100 / 83 / 83.5**.
- **Approved-code facts:** BOS ↓ c12 (ref 91) and BOS ↓ c18 (ref 84); WICK_ONLY at c18; state BEARISH, protected 99, before and after.

| Step | Result |
|---|---|
| (1) BOS | Latest low 84 (L c14): close 83.5 < 84 → **BOS ↓ c18**. Latest high 99: close not > 99 → none. |
| (2) CHoCH | Pre-state BEARISH, protected LH 99. Close 83.5 is not > 99; high 100 > 99 → **WICK_ONLY**. |
| (2L) Liquidity *(B0)* | **BSL 99:** high 100 > 99, close 83.5 ≤ 99 → **BSL_SWEEP(99)**. **SSL 84:** close 83.5 < 84 → **TAKEN**. **BSL 102** (H c4): high 100 is not > 102 → nothing. **SSL 91** was TAKEN at c12. |
| (3) State | No change: BEARISH. |
| (4) Swings | None. |

**Why the order within (1), (2), (2L) cannot change any outcome:**
- Step 2L reads only candle k's OHLC and the pre-candle pool states.
- Steps 1 and 2 read only the pre-candle swings and state.
- None reads another's output from the same candle.
- Changes take effect in steps 3 and 4.
