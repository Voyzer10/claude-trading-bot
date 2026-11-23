# Reclaim rule analysis (research, NOT approved)

"Reclaim" = price returns to the original side of a level it went beyond. The sources use it in three different ways.

| Reading | Definition | Source | Event time | Interaction with approved rules |
|---|---|---|---|---|
| **R0: same-candle** | The candle that went beyond closes back inside | V1-art (grab: long wick, close back) | close of k | Built into S-wick (LS-S01). **No separate event is needed.** |
| **R1: later candle after a close beyond** | A close beyond at k, then a close back inside at j ∈ (k, k+N] | V1-AI ("a later close back inside may re-label as a slow sweep") | close of j | **The same situation as O4 (failed CHoCH), which is unresolved.** If the level was the protected HL, the close beyond already emitted a CHoCH and TRANSITION. The approved code records `O4_UNRESOLVED` at j and changes nothing (verified on LS03). |
| **R2: V3 confirmation** | After a wick sweep of a high, a close below the **trigger low** (the low of the leg that broke the high) | V3-art; V3-meta "Step 3" | close of the confirming candle | A different level from the swept one. It is closer to an early CHoCH or BOS. V3 says it comes before a CHoCH. It is a reversal-setup rule, not a sweep definition. |

**Verified examples (approved detector):**
- **LS01, R0:** c18 = 104 / 105 / 100 / 102 against SSL 101. A same-candle reclaim, a sweep under B0, and NO_CHOCH WICK_ONLY in the approved code.
- **LS03, R1:** c18 = 104 / 105 / 99 / 100.5 is a close beyond 101, so a BOS + CHoCH and TRANSITION. c19 = 100.5 / 103 / 100 / 102 closes back above 101. The approved code gives `O4_UNRESOLVED`: no event, state unchanged.

**Advantages and risks:**
- **R0** is causal, simple and needs no extra parameter. It misses multi-candle sweeps.
- **R1** catches "slow sweeps", but it needs N and turns an already-emitted BOS / CHoCH into something else. Emitting it at j is fine (no repaint), but it duplicates the O4 decision.
- **R2** is a strategy step, with extra levels (the trigger low) and an OTE context (V3-art). Overfitting risk if it is adopted into the event definition.

**Recommendation:**
- B0 = R0 only.
- R1 should be decided **together with O4**, so that one rule governs both "failed CHoCH" and "reclaim after a close beyond".
- R2 belongs to a later setup / entry layer (the `entry/` modules), not to `liquidity/reclaim.py`.

**Unresolved:** LQ-12 (R1 window N, and whether it is the same decision as O4), LQ-20 (where R2 lives).
