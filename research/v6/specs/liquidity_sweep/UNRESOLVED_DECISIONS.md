# Unresolved liquidity decisions (need owner approval)

**B0** = the proposed experimental baseline. Nothing here is approved. Rows changed in the Phase 1.1 audit are marked *(P1.1)*.

| ID | Question | B0 proposal | Alternatives | Evidence / sources |
|---|---|---|---|---|
| LQ-01 | Which levels are pools? | Every confirmed L2/R2 swing (BSL = highs, SSL = lows) | Major only; round numbers; order-book data | V1-meta / V1-AI, V2-tx, V1-art |
| LQ-02 | Major vs minor pools | No distinction | A size or age filter; higher-timeframe swings | V1-AI (internal / external) |
| LQ-03 *(P1.1)* | Equal highs / lows as pools | A separate exact-tie EQ pool type, **unscored until decided**. It is never a swing (SW-004 unchanged). **No algorithm is proposed:** tie window, number of observations, creation time, SW-004 interaction and no-look-ahead are all open (LIQUIDITY_POOL_RULE_MATRIX §B). | No pool; tolerance band; ≥ 2 swings in a band; a wider look-back for separated equal highs | V1-art, V1-AI, V2-tx (all teach EQ as strong liquidity) |
| LQ-04 | Pool price or zone | The wick extreme | Wick-to-body zone | – |
| LQ-05 | Internal vs external | Not modelled | Tie to the CHoCH A1 "external" definition (still open) | V1-AI only |
| LQ-06 | Pool lifecycle | ACTIVE → SWEPT → TAKEN | First sweep consumes; flip after take | INFERENCE |
| LQ-07 *(P1.1)* | Pool expiry | None (**placeholder only; expiry stays OPEN**). The consequences of no expiry (stale levels, similar prices, newer same-side swings, sessions, accumulation) are analysed in LIQUIDITY_POOL_RULE_MATRIX §C. | N candles; session; replaced by a newer same-side swing; cap per side; only pools near price | none taught |
| LQ-08 | Sweep definition | **S-wick:** `high > P` and `close ≤ P` (BSL; mirrored for SSL) | S-any; S-multi (close beyond, then back within N) | V1-art, V3 (wick); V2 silent |
| LQ-09 *(P1.1)* | Minimum penetration depth | d = 0, i.e. a strict `>` / `<` beyond P. **This is only the proposed B0 value, NOT an approved rule.** LS-S01 depends on it (SWEEP_RULE_MATRIX LS-S05). | Ticks; price; ATR fraction | none taught |
| LQ-10 *(P1.1)* | Sweep / grab / run taxonomy | B0 **detector behaviour:** one sweep event type (BSL_SWEEP / SSL_SWEEP) for the wick-and-close-back pattern, plus a pool state change to TAKEN. No GRAB event. **Still OPEN:** whether to add a GRAB / SWEEP split, and whether TAKEN is also emitted as a named RUN event. Instructor terminology is recorded separately and is not a rule (SWEEP_RULE_MATRIX §A). | Split by speed or candle count (LS-S12); a RUN event or attribute | V1-art vs V1-AI disagree; V2 and V3 use the words together |
| LQ-11 *(P1.1)* | Run momentum criterion | Not used (only relevant if LQ-10 adds a RUN event or attribute) | Body ≥ 2× the previous (V1-AI) | V1-AI only (unverified) |
| LQ-12 | Reclaim after a close beyond (R1) | Not in B0; decide **together with O4** | Window N candles | V1-AI; approved code gives O4_UNRESOLVED |
| LQ-13 | Displacement | Not part of the sweep; optional later annotation | Body or range multiple of ATR within M candles | V3 (setup step) |
| LQ-14 | Several pools on one candle | One event per pool, shared group id | Deepest only; nearest only | INFERENCE |
| LQ-15 | Repeated sweeps | One SWEEP per pool, plus REPEAT_SWEEP diagnostics | An event per sweep; re-arm distance | INFERENCE |
| LQ-16 | Taken pools | Inactive | Flip to the opposite side | COMMON, not taught here |
| LQ-17 | Event naming | BSL_SWEEP / SSL_SWEEP (by pool side) | "Bullish / bearish sweep" | sources conflict |
| LQ-18 | Inducement | Not modelled (a composite pattern) | Internal sweep + later BOS | V1-AI only |
| LQ-19 | Trendline / range / channel liquidity | Excluded | A fitting rule with tolerance; N-bar range | V2-tx, V1-AI |
| LQ-20 | Where V3's reversal confirmation (close beyond the trigger low) lives | A later entry / setup layer, not the sweep event | Part of `liquidity/reclaim.py` | V3-art |
| LQ-21 | Late-reading rules (R1, displacement) | Emitted at their own candle, never back-dated | – | no-look-ahead harness |
| LQ-22 *(P1.1)* | Does a sweep of the protected swing affect the CHoCH machine? | No. The CHoCH layer alone owns the state and records WICK_ONLY (approved). The liquidity layer emits its own sweep event and pool-state change and never writes the structure state. Asymmetry: WICK_ONLY fires on every such candle; the sweep fires only on the first, later ones are REPEAT_SWEEP (SWEEP_RULE_MATRIX §B). | – | approved A6 |

**Kept open from the CHoCH work:** O4 (closely tied to LQ-12), O7, O8, O9, CHU04 (exact-level close; affects LS09), CHU05, and A1 (external).
