# Event ordering: liquidity events inside the approved D5 order (proposal, NOT implemented)

**Approved D5 (22 Nov), unchanged.** At the close of candle k:
1. BOS from the swings confirmed at or before k−1.
2. CHoCH against the pre-candle state.
3. State update.
4. Swings confirmed at k (P-B activation, structure establishment), in force from k+1.

## Proposed extension (B0)

At the close of candle k:

| Step | What | Uses | Note |
|---|---|---|---|
| 1 | BOS (unchanged) | swings ≤ k−1 | – |
| 2 | CHoCH (unchanged) | state and protected swing as of k−1 | – |
| **2L** | **Liquidity:** for every pool ACTIVE as of k−1, evaluate S-wick → SWEEP, or a close beyond → TAKEN | pools active from conf + 1 ≤ k | Reads only candle k's OHLC and pre-candle pool states. It does **not** read the BOS or CHoCH results of the same candle, so the order of 1 / 2 / 2L cannot change any outcome. |
| 3 | State update (unchanged) | – | **Sweeps never change the structure state** (LS-S09) |
| 4 | Swings confirmed at k → new pools (active from k+1); P-B activation; establishment | – | A sweep wick that later becomes a swing creates its pool only after confirmation (LT-15) |

**Why no ordering conflict exists under B0 (INFERENCE):**
- For a given level and candle, BOS needs `close > P`, while a sweep needs `high > P` and `close ≤ P`. They are mutually exclusive.
- CHoCH is the same close condition against the protected swing.
- So the only same-candle combinations are:
  - BOS / CHoCH on one side plus a sweep on the other side (an outside bar, LS07);
  - a sweep of the protected HL together with the CHoCH `WICK_ONLY` diagnostic (LS01);
  - several sweeps (LS05).

## Same-candle interaction table (verified with the approved BOS / CHoCH code)

| Case | Candle k (o / h / l / c) | BOS / CHoCH (approved code) | Liquidity (B0 proposal) |
|---|---|---|---|
| LS01 | 104 / 105 / 100 / 102 | NO_CHOCH, WICK_ONLY diagnostic at c18 | SSL_SWEEP of 101 (two outputs from two modules; no state change in either; SWEEP_RULE_MATRIX §B) |
| LS02 | 104 / 105 / 99 / 100 | bearish BOS (101) + BEARISH_CHOCH → TRANSITION | SSL 101 TAKEN, no sweep |
| LS05 | 104 / 105 / 96 / 102 | WICK_ONLY | SSL_SWEEP of 101 and of 98 (same group) |
| LS07 | 104 / 117 / 100 / 116.5 | bullish BOS (116); WICK_ONLY vs 101 | SSL_SWEEP of 101 **and** BSL 116 TAKEN. Full step-by-step D5 walk-through and the bearish mirror LS07m (c18 96 / 100 / 83 / 83.5): SWEEP_RULE_MATRIX §C |
| LS09 | 104 / 105 / 100 / 101 | WICK_ONLY (close not strictly below 101) | SSL_SWEEP of 101 (close == P; CHU04-related) |

**Phase 1.1 note:** BOS reference consumption (BOS module) and pool TAKEN (liquidity step 2L) are separate rules evaluated independently on the same close. The exact transitions are in LIQUIDITY_POOL_RULE_MATRIX §A.

**Unresolved ordering questions:**
- **LQ-21:** if a later reclaim rule (R1) or displacement annotation is added, it reads **earlier** candles' events, and must be emitted at its own candle (never back-dated).
- **LQ-22:** should a SWEEP of the protected swing have any effect on the CHoCH state machine? B0 says no.

**Streaming:** a future `LiquidityStream` would wrap the existing `StructureStream`, so batch and stream share one code path, as with BOS and CHoCH. Parity is checked with `replay_audit`.
