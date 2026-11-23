# V6 Liquidity Sweep: blind examination

**Date:** 22 Nov 2026. **Research only.** No liquidity detector was implemented; no scanner, test, spec, V4 or production
file was changed. **PAPER ONLY.**

## 1. What is approved and what is not

From `research/v6/specs/liquidity_sweep/`:
- **No liquidity rule is approved.** LQ-01…LQ-22 are open, and the B0 baseline is only a proposal.
- B0 proposes: pools = confirmed L2/R2 swings, active from confirmation + 1; sweep = wick strictly beyond with the
  close not beyond (S-wick, d = 0); close beyond → TAKEN; lifecycle ACTIVE → SWEPT → TAKEN; one event per pool;
  REPEAT_SWEEP diagnostics; no expiry; sweeps never change the structure state.
- `scanner_v6/liquidity/*` are docstring-only stubs.

**Consequences for this exam:**
- **Scored (decidable):** only facts that follow from approved rules, inside liquidity contexts:
  - swing levels and their confirmation candle (the would-be pool levels; SW-001…005);
  - BOS (BOS-001…005, D4, D5);
  - CHoCH, establishment and reversal (A1–A10, D1–D3);
  - WICK_ONLY at the protected swing (A6);
  - state and protected swing after each tail candle (D2 P-B);
  - no-look-ahead and batch / stream parity.
- **PROVISIONAL (B0):** every pool, every SWEEP / REPEAT_SWEEP / TAKEN event and every pool state. Written in the key,
  **not scored**.
- **UNRESOLVED:** never forced:
  - close == level (CHU04 / LQ-08);
  - equal / separated equal highs (LQ-03);
  - a touch at exactly the level (LQ-09);
  - reclaim after a close beyond (LQ-12 / O4);
  - the state after an O4 close-back.
- **The bot is the current V6 implementation, unchanged.** For liquidity it can only answer NOT_IMPLEMENTED.

## 2. Blind protocol (hashes and UTC times in `PROTOCOL.txt`)

1. **Fixtures:** 20 scenarios, OHLC only, built and hashed (`LIQUIDITY_SWEEP_BLIND_FIXTURES.json`). Only candle
   validity was checked; no structure was computed.
2. **Answer key:** written by hand from the rules and sealed **before the bot ran**:
   - `EXPECTED_RESULTS.json`, file made read-only, SHA-256 recorded;
   - mirrors derived mechanically (p → 200 − p);
   - candle values read only to quote evidence.
3. **Bot:** run in a separate process that received **only** the fixtures path (`BOT_ANSWERS.json`).
4. **Scoring** (`SCORES.json`, `SCORE_ITEMS.csv`).
5. **Scorer mutation test:** 6 injected bot errors were each detected (§5).

```
fixtures/LIQUIDITY_SWEEP_BLIND_FIXTURES.json 20 scenarios, sha256 fb0df27ed6786606320b9ae3630c97b97f320e5ef2a61f6032f89a3fcd760959
2026-11-22T11:26:21Z
sealed key sealed/EXPECTED_RESULTS.json sha256 dbd54b7208e90c3c63df784a4bc1d46f53f05eb81100cebf831a991b13db598e
dbd54b7208e90c3c63df784a4bc1d46f53f05eb81100cebf831a991b13db598e  sealed/EXPECTED_RESULTS.json
49827e455b35331ac5032ecab3143fc67b76ed334aeafeb883ae605be819de58  sealed/build_expected.py
2026-11-22T11:27:59Z
bot answers bot/BOT_ANSWERS.json sha256 9d6b6a4d23e37f4b052379e0e79bf057d41ee2bf430ca8af3a2999d526abad40
2026-11-22T11:28:29Z
scoring run: 2026-11-22T11:28:55Z (after the bot)
```

## 3. Scenarios

**Base for every scenario** (candles 1–16, CHD01 c1–c16; mirrored scenarios use p → 200 − p):

| c | O | H | L | C |
|---|---|---|---|---|
| 1 | 104 | 105 | 102 | 103 |
| 2 | 103 | 104 | 101 | 102 |
| 3 | 102 | 103 | 100 | 101 |
| 4 | 101 | 102 | 98 | 99 |
| 5 | 99 | 103 | 99 | 102 |
| 6 | 102 | 106 | 101 | 105 |
| 7 | 105 | 109 | 104 | 108 |
| 8 | 108 | 108 | 104 | 105 |
| 9 | 105 | 106 | 102 | 103 |
| 10 | 103 | 104 | 101 | 102 |
| 11 | 102 | 107 | 102 | 106 |
| 12 | 106 | 111 | 105 | 110 |
| 13 | 110 | 114 | 109 | 113 |
| 14 | 113 | 116 | 112 | 115 |
| 15 | 115 | 115 | 110 | 111 |
| 16 | 111 | 112 | 106 | 107 |

**Scenario tails** (candle 17 onward; full candles for every scenario in the fixtures JSON):

| Scenario | Difficulty | Covers | Tail candles c17… (O / H / L / C) |
|---|---|---|---|
| LSB-E1 | Easy | BSL pool, wick beyond vs close back inside, new pools from new swings | c17 107/117/106.5/108 · c18 108/109/107/108.5 · c19 108.5/110/107.5/109.5 |
| LSB-E2 | Easy | SSL pool at the protected swing, wick beyond vs close back inside | c17 107/108/100/104 · c18 104/106/103/105.5 · c19 105.5/107/104.5/106.5 |
| LSB-E3 | Easy | bearish mirror of E2 (BSL at the protected swing) (mirror of LSB-E2) | c17 93/100/92/96 · c18 96/97/94/94.5 · c19 94.5/95.5/93/93.5 |
| LSB-E4 | Easy | close beyond a BSL level together with a bullish BOS; protected-swing update | c17 107/117.5/106.5/117 · c18 117/118/116/117.5 |
| LSB-E5 | Easy | bearish mirror of E4 (mirror of LSB-E4) | c17 93/93.5/82.5/83 · c18 83/84/82/82.5 |
| LSB-M1 | Medium | repeated wicks at one SSL level on consecutive candles | c17 107/108/100/104 · c18 104/105/100.5/103.5 · c19 103.5/106/103/105.5 · c20 105.5/107/104.5/106.5 |
| LSB-M2 | Medium | wick beyond, then a close beyond on the next candle (lifecycle + CHoCH) | c17 107/108/100/104 · c18 104/104.5/99/99.5 |
| LSB-M3 | Medium | two SSL levels pierced by one candle (multiple pools on one candle) | c17 107/108/97/103 · c18 103/105/102/104.5 · c19 104.5/106/103.5/105.5 |
| LSB-M4 | Medium | bearish mirror of M3 (mirror of LSB-M3) | c17 93/103/92/97 · c18 97/98/95/95.5 · c19 95.5/96.5/94/94.5 |
| LSB-M5 | Medium | bearish mirror of M1 (mirror of LSB-M1) | c17 93/100/92/96 · c18 96/99.5/95/96.5 · c19 96.5/97/94/94.5 · c20 94.5/95.5/93/93.5 |
| LSB-H1 | Hard | outside bar: SSL wick + BSL close beyond + BOS on one candle; P-B origin re-selection | c17 107/117/100.5/116.5 · c18 116.5/118/115/117.5 · c19 117.5/119/116/118.5 |
| LSB-H2 | Hard | bearish mirror of H1 (mirror of LSB-H1) | c17 93/99.5/83/83.5 · c18 83.5/85/82/82.5 · c19 82.5/84/81/81.5 |
| LSB-H3 | Hard | liquidity at a freshly activated protected swing; D5 timing of activation | c17 107/117.5/106.5/117 · c18 117/118/116/117.5 · c19 117.5/118.5/105.5/108 · c20 108/109/107/108.5 · c21 108.5/110/107.5/109 |
| LSB-H4 | Hard | no-look-ahead: a level pierced BEFORE it becomes a swing; pools only after confirmation | c17 107/108/102/104 · c18 104/106/103.5/105.5 · c19 105.5/107/104/106 · c20 106/106.5/103/104 · c21 104/105.5/103.5/105 · c22 105/107/104.5/106.5 · c23 106.5/106.8/102.5/105.5 |
| LSB-H5 | Hard | bearish mirror of H3 (mirror of LSB-H3) | c17 93/93.5/82.5/83 · c18 83/84/82/82.5 · c19 82.5/94.5/81.5/92 · c20 92/93/91/91.5 · c21 91.5/92.5/90/91 |
| LSB-X1 | Extreme | close exactly at the level (CHU04 / LQ-08) | c17 107/108/100/101 · c18 101/104/100.5/103.5 · c19 103.5/105/103/104.5 |
| LSB-X2 | Extreme | separated equal highs as two levels (LQ-03), touch at exactly the level, double pierce | c17 107/113/106.5/112 · c18 112/116/111/114 · c19 114/115/110/111 · c20 111/112/108/109 · c21 109/117/108.5/115 · c22 115/116/110/112 |
| LSB-X3 | Extreme | close beyond then close back inside (reclaim, LQ-12 / O4) | c17 107/107.5/99.5/100 · c18 100/104/99.8/103.5 · c19 103.5/105/103/104.5 |
| LSB-X4 | Extreme | long chain: repeated wicks, close beyond + CHoCH, D4 no-fallback, later wick/close at older levels, reversal BOS | c17 107/108/100/104 · c18 104/105/100.5/103.5 · c19 103.5/104/99/99.5 · c20 99.5/101/97.5/98.5 · c21 98.5/99/96/96.5 · c22 96.5/99/96.5/98.5 · c23 98.5/100/97/99.5 · c24 99.5/99.8/95/95.5 |
| LSB-X5 | Extreme | bearish mirror of X4 (mirror of LSB-X4) | c17 93/100/92/96 · c18 96/99.5/95/96.5 · c19 96.5/101/96/100.5 · c20 100.5/102.5/99/101.5 · c21 101.5/104/101/103.5 · c22 103.5/103.5/101/101.5 · c23 101.5/103/100/100.5 · c24 100.5/105/100.2/104.5 |

**Coverage:**
- BSL and SSL: E1, E3, E4, E5, H1, H2, X2 / E2, M1–M5, H3–H5, X3–X5.
- Wick vs close beyond: E1, E2 vs E4, M2, X3.
- Lifecycle ACTIVE → SWEPT → TAKEN: M2, X4.
- Repeated sweeps: M1, M5, X4.
- Several pools on one candle: M3, M4, H1, X2.
- Several levels: H3, H4, X4.
- BOS / CHoCH interaction: E4, M2, H1–H3, X3–X5.
- Protected-swing liquidity: E2, E3, M1, H3, H5.
- No-look-ahead / ordering: H4, H3 (D5 activation).
- Mirrors: E3, E5, M4, M5, H2, H5, X5.

## 4. Answer format

Each item in the key and in the bot answers carries:
- pool id + side (`SSL@101(c10)`);
- event type;
- candle (1-based);
- pool state before → after;
- close / wick evidence;
- BOS / CHoCH interaction;
- status: APPROVED / PROVISIONAL (with the B0 / LQ reference) / UNRESOLVED (with the reason).

The bot's liquidity answer is `NOT_IMPLEMENTED`, with the stub status as the reason.

## 5. Scorer check

The scorer was run on six deliberately corrupted copies of the bot answers. Each was detected:
- drop a swing → 1 FAIL;
- wrong BOS level → 2 FAIL (missing + unexpected);
- extra CHoCH → 1 FAIL;
- wrong checkpoint → 1 FAIL;
- missing WICK_ONLY → 1 FAIL;
- harness failure → 1 FAIL.

So a perfect score is not an artefact of a lenient scorer.

