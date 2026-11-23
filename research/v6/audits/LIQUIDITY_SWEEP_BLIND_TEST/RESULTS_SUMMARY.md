# Results summary: V6 Liquidity Sweep blind examination

## Score (decidable items only)

| | PASS | FAIL | Total |
|---|---|---|---|
| **All** | **377** | **0** | **377** |
| Easy | 83 | 0 | 83 |
| Medium | 89 | 0 | 89 |
| Hard | 101 | 0 | 101 |
| Extreme | 104 | 0 | 104 |

| Category | PASS | FAIL |
|---|---|---|
| bos | 32 | 0 |
| bos_no_unexpected | 20 | 0 |
| checkpoints | 75 | 0 |
| harness | 40 | 0 |
| structure_events | 26 | 0 |
| structure_events_no_unexpected | 20 | 0 |
| swings | 107 | 0 |
| swings_no_unexpected | 20 | 0 |
| wick_only | 17 | 0 |
| wick_only_no_unexpected | 20 | 0 |

| Scenario | PASS | FAIL |
|---|---|---|
| LSB-E1 | 17 | 0 |
| LSB-E2 | 17 | 0 |
| LSB-E3 | 17 | 0 |
| LSB-E4 | 16 | 0 |
| LSB-E5 | 16 | 0 |
| LSB-H1 | 18 | 0 |
| LSB-H2 | 18 | 0 |
| LSB-H3 | 22 | 0 |
| LSB-H4 | 21 | 0 |
| LSB-H5 | 22 | 0 |
| LSB-M1 | 19 | 0 |
| LSB-M2 | 17 | 0 |
| LSB-M3 | 17 | 0 |
| LSB-M4 | 17 | 0 |
| LSB-M5 | 19 | 0 |
| LSB-X1 | 13 | 0 |
| LSB-X2 | 21 | 0 |
| LSB-X3 | 16 | 0 |
| LSB-X4 | 27 | 0 |
| LSB-X5 | 27 | 0 |

**Mismatches:** 0. 

**What the score means:**
- The current V6 structure layer (swings, BOS, CHoCH, protected swing, WICK_ONLY, state timeline, no-look-ahead,
  parity) matches the hand-written key on every decidable item, in liquidity-heavy scenarios: outside bars, repeated
  wicks, several levels on one candle, a freshly activated protected swing, D4 no-fallback, reversal confirmation, and
  all mirrors.
- It says **nothing** about liquidity detection: no liquidity rule is approved, and V6 has no detector.

## Provisional (B0) liquidity items: not scored

| | Count |
|---|---|
| Expected B0 pools | 106 |
| Expected B0 liquidity events (SWEEP / REPEAT_SWEEP / TAKEN / explicit no-event) | 58 |
| Bot answers for liquidity | 0 of 20 scenarios: `NOT_IMPLEMENTED` (stubs: {"liquidity_pools": "no callable detector", "sweep": "no callable detector"}) |

These key entries are ready to become scored expectations once B0 (or an alternative) is approved and a detector
exists.

## Unresolved items: never scored

| Scenario | Candle | Item |
|---|---|---|
| LSB-X1 | c17 | structure state / CHoCH at c17: close == protected 101 (CHU04) |
| LSB-X1 | c17 | SSL 101 sweep vs no-sweep when close == level (LQ-08 / CHU04 / LQ-09) |
| LSB-X1 | c18 | state at c18-c19 depends on the c17 decision (CHU04) |
| LSB-X2 | c18 | c18 high == 116 exactly (touch, not beyond): sweep depth / equality (LQ-09) |
| LSB-X2 | c18 | a second swing high at 116: separated equal highs as one pool or two (LQ-03) |
| LSB-X2 | c21 | c21 high 117 / close 115 pierces both 116 levels: one or two sweeps (LQ-03, LQ-14) |
| LSB-X3 | c18 | close back above the taken / consumed 101: reclaim (LQ-12) and failed CHoCH (O4) |
| LSB-X3 | c18 | state at c18-c19 (O4 unresolved) |

**Bot diagnostics on unresolved / unscored points** (recorded, not scored):
- X1 c17 `EXACT_LEVEL_CLOSE` (CHU04, current strict default);
- X3 c18–c19 `O4_UNRESOLVED`;
- `NOT_QUALIFIED` (A5) on H1 / H2 c19, M2 c18, X3 c17, X4 / X5 c19;
- `ACTIVATED` on E4 / E5 / H3 / H5 c18.

## Limitations
- The key was hand-derived by the same author who designed the scenarios. The bot is deterministic code that never
  saw the key, and the key was sealed before the bot ran. A wrong key entry would still show as a mismatch, and none
  did. The scenarios reuse the CHD01 base, so base items (4 swings, 1 BOS, ESTABLISHED c16) repeat in every scenario
  and make up part of the total.
- Synthetic data only: no market data, no profitability or edge claim.

