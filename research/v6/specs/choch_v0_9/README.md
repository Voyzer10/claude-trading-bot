# CHoCH v0.9: conceptual fixture drafts (21 Nov 2026)

**Status: DRAFT. Research only, PAPER ONLY.** There is no CHoCH detector and no protected-level code. Spec §9 blocks implementation until O1–O9 are resolved and approved.

## Files

- `choch_fixtures.draft.json`: 9 decidable cases (scored) and 6 unscored cases. Candles are numbered from 1; every `*_index` field is 0-based.
- `PHASE1_2_DECISIONS.md` (22 Nov 2026): Phase 1 audit and Phase 2 decision table, together with the **approval register** (previously approved vs newly proposed D1–D5). Nothing in it is implemented yet; it waits for owner approval.
- `AUDIT_CHD01-09.md`: independent audit of the decidable expectations. **CHD01 and CHD02 are not fully supported** (they depend on O1, O6 and O3). The `protected_swing_id` field of CHD03 and CHD04 depends on O1.
- `build_choch_drafts.py`: writes the JSON.
  - It checks the facts behind every expectation with the approved L2/R2 swing detector: the swings, the swing counts known before the candidate candle, the HH/HL and LH/LL comparisons, and the close or wick against the protected price.
  - It records BOS under the existing approved rules, for information only.
  - The CHoCH outcomes themselves are written by hand. The script does not compute them. **Passing it is not proof that they are correct.**

## Decisions applied

- A1–A10 from the spec.
- Owner decisions of 21 Nov 2026:
  - BOS is independent of structure direction (Option A). The existing BOS fixtures are unchanged.
  - WICK_ONLY means a rejected candidate with event NO_CHOCH.
  - Failed CHoCH, complex breaks and protected-swing lifecycle cases stay unscored.

## Decidable (scored)

| Case | Candles | State before → event → state after | Protected | Candidate candle |
|---|---|---|---|---|
| CHD01 | 18 | BULLISH → BEARISH_CHOCH → TRANSITION | low 101 (c10) | c18 (close 100) |
| CHD02 | 18 | BEARISH → BULLISH_CHOCH → TRANSITION (mirror of CHD01) | high 99 (c10) | c18 (close 100) |
| CHD03 | 18 | BULLISH → NO_CHOCH (WICK_ONLY) → BULLISH | low 101 | c18 (low 100, close 102) |
| CHD04 | 18 | BEARISH → NO_CHOCH (WICK_ONLY) → BEARISH (mirror of CHD03) | high 99 | c18 |
| CHD05 | 18 | BULLISH → NO_CHOCH → BULLISH (with-trend BOS above 116) | – | c18 |
| CHD06 | 18 | BEARISH → NO_CHOCH → BEARISH (mirror of CHD05) | – | c18 |
| CHD07 | 14 | UNKNOWN (1 low) → NO_CHOCH; still a bearish BOS at c14 | – | c14 |
| CHD08 | 14 | UNKNOWN (Easy Chart 1: equal levels only) → NO_CHOCH on every candle | – | – |
| CHD09 | 14 | UNKNOWN (Easy Chart 2: 1 confirmed low) → NO_CHOCH; the c13 BOS below 117 stays | – | c13 |

**Design:**
- Each structured case has exactly 2 confirmed highs and 2 confirmed lows before the candidate candle, and a single HL (or LH).
- Each is a clean zig-zag, so no swing can be "internal".
- The audit found that a single HL is **not** enough to remove the O1 dependency: whether it "qualifies" is itself open. See `AUDIT_CHD01-09.md`.

## Unresolved decisions O1–O9 (owner's list, 21 Nov 2026)

O3-core (the CHoCH → TRANSITION → separate BOS workflow) was adopted by the owner on 22 Nov 2026. Its details (D1) and O1/O2, O5, O6 and C3 have proposals in `PHASE1_2_DECISIONS.md`. They are not approved yet.

| ID | Open decision |
|---|---|
| O1 | Protected-swing lifecycle |
| O2 | Continuation BOS association |
| O3 | Transition completion |
| O4 | Failed CHoCH sequencing |
| O5 | Complex-break detection and state |
| O6 | Same-candle event ordering |
| O7 | History / session gaps |
| O8 | Duplicate, invalidation and stable event IDs |
| O9 | Initial structure chronology |

## Unscored (rule not finalised)

| Case | Open item(s) |
|---|---|
| CHU01 | O4: close back above 101 after the CHoCH |
| CHU02 | O5, O6: one close below both 101 and 98 |
| CHU03 | O1, O2: rising lows 98 / 101 / 106, then a close at 105 |
| CHU04 | Not in O1–O9: is "close beyond" strict for CHoCH? Close exactly at 101. Needs an owner decision. |
| CHU05 | O9; mixed HH + LL classification is not named in O1–O9 |
| CHU06 | O3, O8; BOS-001 reading C3 is a BOS question outside O1–O9 |

## Blocked

- **Medium Chart 1 / 2 (17 candles):** never uploaded in this session. The only exam charts received are Easy (14 candles), Hard (18 / 18 / 19) and Extreme (19 / 19 / 20). The original Medium OHLC is needed. Nothing has been substituted.
