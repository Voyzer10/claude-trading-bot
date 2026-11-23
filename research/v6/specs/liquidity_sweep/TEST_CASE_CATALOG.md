# Test case catalog: liquidity (planned, NOT implemented)

**Scoring rules:**
- **SCORABLE-IF-B0:** becomes pass / fail only if the owner approves B0.
- **UNSCORED:** depends on an open decision; the test may only assert that nothing is invented.
- **APPROVED-CHECK:** the expectation follows from already-approved rules. It can be tested now; nothing in it depends on a new liquidity rule.

| Test | Case(s) | What is asserted | Category |
|---|---|---|---|
| LT-01 | LS01 / LS01m | One SSL_SWEEP (BSL_SWEEP in the mirror) at c18 against pool 101; the pool goes SWEPT; structure state unchanged | SCORABLE-IF-B0 |
| LT-02 | LS04 / LS04m | BSL_SWEEP(116) at c17; SSL_SWEEP(84) in the mirror | SCORABLE-IF-B0 |
| LT-03 | LS02 / LS02m | No sweep; pool 101 TAKEN at c18; the BOS / CHoCH outputs equal those of the approved code (no change) | SCORABLE-IF-B0 + APPROVED-CHECK |
| LT-04 | LS08 / LS08m | Sweep at c18. The displacement is **not** required and must not alter the sweep event. | SCORABLE-IF-B0 (displacement part UNSCORED) |
| LT-05 | LS05 / LS05m | Two sweep events (101, 98) in one group | SCORABLE-IF-B0 |
| LT-06 | LS06 / LS06m | Exactly one sweep for pool 101, plus a REPEAT_SWEEP diagnostic at c19 | SCORABLE-IF-B0 |
| LT-07 | EQ01 | EQH pool behaviour | **UNSCORED** (LQ-03) |
| LT-08 | EQ02 | EQL pool behaviour | **UNSCORED** (LQ-03) |
| LT-09 | LS07 / LS07m | Same candle: SSL_SWEEP(101) + bullish BOS(116) + pool 116 TAKEN. Mirror: BSL_SWEEP(99) + bearish BOS(84) + pool 84 TAKEN. BOS / CHoCH equal to the approved code. Walk-through: SWEEP_RULE_MATRIX §C. | SCORABLE-IF-B0 |
| LT-10 | LS09 / LS09m | Close == level | **UNSCORED** (CHU04 / LQ-08) |
| LT-11 | LS03 / LS03m | Reclaim after a close beyond | **UNSCORED** (LQ-12 / O4). Only asserts no new structure event and no state change. |
| LT-12 | LS11 / LS11m | A TAKEN pool is never swept later | SCORABLE-IF-B0 |
| LT-13 | B17 + a far-later wick (to be generated) | No expiry under B0 | **UNSCORED** (LQ-07) |
| LT-14 | LS12 | No pool and no sweep before the first swing confirmation (c7) | APPROVED-CHECK (follows from the swing rule) |
| LT-15 | LS10 / LS10m | The new pool from swing L 100 is active from c21, not before | SCORABLE-IF-B0 (the timing follows D5) |
| LT-16 *(P1.1)* | all LS / EQ | One-directional check: every sweep event of the **protected** swing's pool has a WICK_ONLY diagnostic on the same candle. The reverse does **not** hold: a WICK_ONLY can come with a REPEAT_SWEEP instead (LS06, c19), because sweeps fire once per pool. Neither output changes the structure state. Excluded: the O9 case (structure established after its protected pool was TAKEN, see SWEEP_RULE_MATRIX §B item 4), which is unscored. | SCORABLE-IF-B0 |
| LT-NLA-1 | all | `no_lookahead_violations` = [] | SCORABLE-IF-B0 |
| LT-NLA-2 | all | `replay_audit` against a B0 oracle: no premature / early / late / missing / unexpected / duplicate / repaint | SCORABLE-IF-B0 |
| LT-PAR | all | Batch vs streaming parity (`replay_audit` with both modes) | SCORABLE-IF-B0 |
| LT-REG | CHD01–CHD16, MED01 / 02, Volume-1 BOS | The existing BOS and CHoCH outputs are byte-identical before and after any liquidity code is added | APPROVED-CHECK |
