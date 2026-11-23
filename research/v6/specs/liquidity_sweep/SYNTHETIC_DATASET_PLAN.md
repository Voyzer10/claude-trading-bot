# Synthetic dataset plan: liquidity pools and sweeps (research, NOT implemented)

**Base series B17** = CHoCH fixture CHD01, candles c1–c17 (`research/v6/specs/choch_v0_9/choch_fixtures.draft.json`). Each case appends candles to it.

**Mirror rule:** each price p becomes 200 − p, and high and low swap. Every case has a mirror ("m"), so bullish and bearish are symmetric.

**Verified facts:**
- **Already checked (22 Nov 2026):** the swings, BOS, CHoCH and diagnostics below come from the approved `swings.py`, `bos.py` and `choch.py`.
- **Not checked, because nothing runs them yet:** the "Liquidity (B0)" outcomes. They are the **proposed** expectations and are only scorable after approval.

| Case | Appended candles (o / h / l / c) | Approved code (verified) | Liquidity expectation under B0 (proposed) | Covers |
|---|---|---|---|---|
| **LS01** | c18 104/105/100/102 | no BOS; NO_CHOCH, WICK_ONLY at c18; BULLISH, protected 101 | SSL_SWEEP(101) at c18; pool 101 SWEPT; pool 98 untouched | clean wick sweep + same-candle reclaim (bullish) |
| **LS02** | c18 104/105/99/100 | ↓ BOS (101) + BEARISH_CHOCH at c18 → TRANSITION | SSL 101 TAKEN at c18; **no sweep** | close beyond (no reclaim) |
| **LS03** | c18 104/105/99/100.5, c19 100.5/103/100/102 | BOS + CHoCH at c18; `O4_UNRESOLVED` at c19 | c18: 101 TAKEN. c19: **unscored** (R1 reclaim = LQ-12 / O4) | close beyond, then a close back |
| **LS04** | c17 107/117/106.5/115 (replaces B17's c17) | no BOS (close 115 < 116); BULLISH, protected 101 | BSL_SWEEP(116) at c17 | clean wick sweep of BSL (bearish) |
| **LS04m** | mirror of LS04: c17 93/93.5/83/85 | no BOS; BEARISH, protected 99 | SSL_SWEEP(84) at c17 | symmetry |
| **LS05** | c18 104/105/96/102 | WICK_ONLY at c18 | SSL_SWEEP(101) and SSL_SWEEP(98), one group | multiple pools, one candle |
| **LS06** | c18 104/105/100/102, c19 102/103/100.5/102.5 | WICK_ONLY at c18 and c19 | SSL_SWEEP(101) at c18 only; c19 → `REPEAT_SWEEP` diagnostic (LS-S06) | repeated sweep |
| **LS07** | c18 104/117/100/116.5 | ↑ BOS (116) at c18; WICK_ONLY vs 101 | SSL_SWEEP(101) + BSL 116 TAKEN at c18 | same-candle sweep + BOS |
| **LS08** | c18 104/105/100/102, c19 102/112/101.5/111.5 | WICK_ONLY at c18 | SSL_SWEEP(101) at c18. The displacement at c19 is an **annotation only** (LQ-13, unscored). | sweep followed by displacement |
| **LS09** | c18 104/105/100/101 | WICK_ONLY (close == 101 is not a strict close beyond) | SSL_SWEEP(101), because close ≤ P; **unscored until CHU04 / LQ-08** | exact-level close |
| **LS10** | c18 104/105/100/102, c19 102/104/101.5/103.5, c20 103.5/106/103/105.5 | new swing L 100 (c18, conf c20) | SSL_SWEEP(101) at c18; a **new SSL pool 100 active from c21** (not at c18–c20) | new swing / pool timing, no look-ahead |
| **LS11** | B17 + c18 104/105/99/100, c19 100/101/99.5/100.5 | BOS + CHoCH at c18 (101 TAKEN) | c19 high 101 is not > 101 (strict), so no sweep. In any case **101 is TAKEN, so a later wick is never a sweep of it** (LP-06). | previously invalidated pool |
| **LS12** | the first 6 candles of B17 only | no swing before c6 (L 98 confirms at c6) | no pool exists before c7, so no sweep is possible | insufficient history |
| **EQ01** | regression fixture MED01 (Easy chart 1), unchanged | equal highs 105 (c3 / c4) and equal lows 99 (c5 / c6) are diagnostics only, not swings | **unscored until LQ-03.** If EQ pools are approved: EQH 105 active from c7; c8 (h 106, c 105) and c9 (h 107, c 104) are sweeps (c9 a repeat); c11 close 107 TAKES it | equal highs |
| **EQ02** | mirror of EQ01 | – | as EQ01, mirrored | equal lows |

**Also planned (built from the same cases):**
- **No-look-ahead:** every case through `no_lookahead_violations` and through `replay_audit` with an oracle of the B0 events (premature / late / missing / unexpected).
- **Batch vs streaming:** `replay_audit` with both `detector` and `make_stream`, as for BOS and CHoCH.
- **Candle immutability:** feeding the same prefix twice gives the same events (repaint check).
- **Mirrors:** every LS case m-mirrored; expectations mirrored by side (BSL ↔ SSL).

**Data source:** synthetic only. A later real-data check (paper-trading candles) comes after approval, with a held-out split, and the numbers must be reported out-of-sample (repo rule).
