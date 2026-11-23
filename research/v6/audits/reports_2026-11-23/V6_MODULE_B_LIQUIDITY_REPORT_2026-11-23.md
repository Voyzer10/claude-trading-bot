# V6 Module B — Liquidity Pool & Sweep Detection — Report (23 Nov 2026)

## Result: implemented from approved rules and verified; **not committed** (isolation impossible, section 8)

| Item | Result |
|---|---|
| Tests | 262 / 262 pass under pytest and in script mode (233 before, +29 new) |
| Sealed 22-Nov liquidity key | 106 / 106 pools match; 0 real event mismatches on candles the key could decide |
| Independent brute-force oracle | 75 / 75 corpus charts match (events and groups) |
| No look-ahead / replay | 0 / 0 on 75 charts |
| Structure output | byte-identical to the pre-Module B state; Module A untouched |
| One owner confirmation needed | derived setup-side mapping (section 3) |

## 1. Preflight

| Item | Value |
|---|---|
| Branch / HEAD | research/v6-smc-scanner / 7f16f0953798a7b82e7cb595096487b66ab7ac3e |
| Index | e7490c2c616620c0 (byte copy saved) |
| Staged diff / paths | f724a4ad7956d99c / 37; entries identical to the recorded mode + blob list |
| Spec | 945180de… (post SR-1…SR-6) |
| Status / worktree diff | f17cc47ecf32038e / f17ea99e76c1ad70 |
| Liquidity files | HEAD stubs, not staged and not modified (backed up) |

## 2. Specification audit: approved vs open (what Module B relies on)

**OWNER APPROVED (implemented):**
- LQ-01, LQ-04, LQ-06, LQ-08 (including close == P), LQ-09, LQ-14, LQ-15, LQ-16, LQ-17, LQ-21, LQ-22.
- LS-S02, LS-S09, LS-S11, LP-12.
- G-1, G-2 (format), G-4, G-5, G-6, G-7, G-8 (raw float), G-11.
- Delegated: LQ-02, LQ-05, LQ-18, LQ-19 (not modelled); LQ-07 (no time expiry); LQ-12 (no extra reclaim); LQ-13 (no displacement).
- CK-15, CK-16 (sides), CK-17, CK-18 (opposite CHoCH / BOS invalidation), OQ-4 (ids), OQ-5 (groups per BOS), SR-4 (BOS roles).

**OPEN / PROPOSED (not implemented, nothing invented):**
- OQ-12: TAKEN / REPEAT_SWEEP group membership.
- LQ-03: EQ pools.
- LQ-10: GRAB / RUN.
- LQ-07: other expiry.
- LQ-11.
- LQ-12: R1 reclaim (`reclaim.py` stays a stub).
- LQ-13: annotation.
- LQ-20.
- G-3, G-9, G-10.
- BOS-006 / C1: tick epsilon.
- When a BOS stops being "current" (OQ-5 r3) apart from an opposite CHoCH / BOS.
- Everything after the sweep: patterns, confirmation, entry, TP.

## 3. Architecture

| File | Status | Content |
|---|---|---|
| `scanner_v6/liquidity/liquidity_pools.py` | ` M` (was a stub), 48 lines | `pool_id` (`pool:<swing_id>`); `pool_from_swing` (the existing `LiquidityPool` model; ABOVE = BSL, BELOW = SSL; stamp = swing stamp); states ACTIVE / SWEPT / TAKEN |
| `scanner_v6/liquidity/sweep.py` | ` M` (was a stub), 196 lines | `classify` (LQ-08 / LS-S02); `LiquidityEvent` (id `liquidity:<pool_id>:<type>:<k>`, name, side, level, extreme, close, group id, state before / after); `SweepGroup` (`sweep:<side>:<k>`); `LiquidityStream` (streaming); `analyze_liquidity`, `detect_liquidity` (batch / harness) |
| `scanner_v6/liquidity/setup_sweep.py` | new, 174 lines | `SetupSweepStream`: CHoCH → REVERSAL_CONFIRMING BOS → sweep candidate (CK-17, OQ-5, CK-18, SR-4); `close_candidate` for later modules |
| `scanner_v6/liquidity/__init__.py` | ` M`, docstring only | — |
| `tests/scanner_v6/test_liquidity.py` | new, 381 lines | 29 tests |
| `research/v6/specs/V6_TRADING_SPEC_v0.2.md` | untracked | new Section 17.S (implemented scope, derived mapping, OPEN items) |

**Unchanged:** Module A, the whole structure layer (`choch.py` / `bos.py` / `swings.py` / `protected_levels.py`), `engine.py`, `models.py` (the existing `LiquidityPool` container is reused), and `reclaim.py`.

**Timing and order:**
- Candle k evaluates only pools confirmed by k − 1 (G-1). Swings confirmed at k create pools that are evaluated from k + 1.
- Within a candle: pool events in creation order, then the group records, then the new pools. This is an implementation choice, not a rule.
- In the setup link, structure events at k are applied before the sweep groups of k (conservative).

**Derived mapping (please confirm).** Bullish reversal-confirming BOS → BUY → requires an SSL sweep; bearish → SELL → requires a BSL sweep. It is not written verbatim anywhere. It follows from Section 3 + CK-16 + CK-18 / OQ-5 ("opposite-direction").

## 4. Tests (all executed now)

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/scanner_v6/test_liquidity.py
29 passed
$ PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/scanner_v6
262 passed                (before: 233)
script mode: 13 + 1 files, 262 ok, every file "all passed"
```

Every test covers BSL and SSL through mirroring (p → 200 − p).

| Area | Tests |
|---|---|
| Pools | ids, price, side and stamp; activation (absent before confirmation, present from it; the first evaluable candle k + 1 sweeps, LS04); dual pivot gives two pools |
| Wick sweep vs TAKEN | LS01 / LS02; equality (close == P → SWEEP; low == P → nothing; close below → TAKEN); no tick epsilon (P ± 1e-9 counts; no config parameter); open ignored |
| Lifecycle | SWEEP → REPEAT ×2 → TAKEN → inactive, no flip; ACTIVE → TAKEN directly (LS11) |
| Groups | two pools, one group (LS05); opposite-side sweep + TAKEN + BOS on one candle (LS07, LS-S11); BSL + SSL on one candle gives two groups; TAKEN / REPEAT carry no group (OQ-12) |
| Ids and order | deterministic ids and timestamps; stream order within a candle |
| Causality | `no_lookahead_violations`, `replay_audit`, prefix replay; stream == batch |
| Data | forming candles never leak (CompletedCandleGate); a timestamp gap creates no events and Module A reports it; missing market config changes nothing |
| LQ-22 | structure timeline and BOS identical with or without liquidity; WICK_ONLY sweep keeps BULLISH 101 |
| Strategy link | candidate after a reversal-confirming BOS (SELL and BUY mirror); REPEAT does not qualify; one pending per BOS; EXPIRED → new candidate (r3); CONFIRMED → no more (r4); opposite BOS → INVALIDATED and eligibility ended (CK-18, r5); same-candle sweep → `SWEEP_ON_BOS_CANDLE`; continuation BOS never; prefix replay of the candidate snapshots; bad `close_candidate` calls rejected |

## 5. Independent checks

**Sealed key** (`LIQUIDITY_SWEEP_BLIND_TEST/EXPECTED_RESULTS.json`, SHA dbd54b72…, hand-written and sealed on 22 Nov, before this code existed; 20 scenarios):
- **Pools:** 106 / 106 match (side, level, source candle, active-from).
- **Events:** 53 of 58 match exactly.
- **The other 5 are label-only:** 4 × "REPEAT_SWEEP (diagnostic)" vs "REPEAT_SWEEP" for the same event, and 1 "NO_EVENT" assertion that V6 also satisfies (no event).

**Candles the key left UNRESOLVED** (V6 now follows the later approvals):
- **X1:** close == 101 after a wick gives SWEEP (LQ-08 equality sub-case, approved after the key was sealed).
- **X2:** two separate strict swings at 116 give two pools (LQ-01; consistent with the register's own LQ-03 text: "still two LP-02 pools"). c21 sweeps both in one group (LQ-14).
- **X3:** no reclaim event (LQ-12 delegated).

**Brute-force oracle:** written from the register text, with its own swing detection; it recomputes each pool's life independently. Result: 75 / 75 corpus charts identical (events, states, groups).

## 6. Replay (historical and synthetic)

**Structure output** (25 historical, `run_v6.py`):
- Raw SHA b5df10bc…, **identical** to the post-reconciliation, pre-Module B output.
- Module B changes no existing output; liquidity output is new.

**Liquidity output** (new):

| Corpus | Pools | SWEEP | REPEAT_SWEEP | TAKEN | Groups | Look-ahead / replay |
|---|---|---|---|---|---|---|
| Historical (25) | 384 | 114 | 76 | 244 | 107 | 0 / 0 |
| Synthetic difficulty pack (25) | 736 | 393 | 557 | 463 | 357 | 0 / 0 |
| `choch_fixtures` (22) | 95 | 6 | 2 | 50 | 6 | 0 / 0 |
| `synthetic_5m` + `easy_bos` | 30 | 4 | 2 | 18 | 3 | 0 / 0 |

**Setup candidates:**

| Corpus | Reversal-confirming BOS | Candidates | Detail |
|---|---|---|---|
| Historical | 10 | 1 | HV22 BUY: BOS k60 → SSL sweep group k69, PENDING. The other 9 had no eligible same-side sweep before an opposite event or the end of the session (2 ended by an opposite CHoCH / BOS) |
| Synthetic | 16 | 10 | 8 INVALIDATED by an opposite CHoCH / BOS, 2 PENDING; 6 later groups blocked as `CANDIDATE_ALREADY_PENDING` |

The candidate snapshots pass the prefix replay at every candle (0 mismatches).

## 7. Remaining limitations

1. **Candidates stay PENDING** until Modules C+ (pattern window, confirmation, entry) call `close_candidate`. EXPIRED by the 5-candle pattern window is not decidable without patterns.
2. **Derived setup-side mapping** awaits owner confirmation (section 3).
3. **OQ-12:** REPEAT_SWEEP / TAKEN never start a candidate.
4. **BOS currency:** a BOS stays current until an opposite CHoCH / BOS; whether anything else ends it is not defined.
5. **No tick epsilon** (G-8 / BOS-006 OPEN). No expiry other than TAKEN (LQ-07). No EQ / GRAB / RUN / reclaim.
6. **Same-candle order:** the structure-before-liquidity order inside one candle (for eligibility) is an implementation choice, documented in 17.S.

## 8. Commit / push: NOT done (isolation impossible)

Proof: `git archive HEAD` plus only the Module B files fails at collection with `ModuleNotFoundError: No module named 'scanner_v6.data.integrity'`. Module B depends on:
- Module A, which is uncommitted (blocked earlier by `test_market_data`'s structure imports);
- the staged structure layer (`swings.py` and `choch.py`, which HEAD has as stubs);
- the uncommitted SR-4 roles in `choch.py`.

A self-contained Module B commit is impossible without committing protected or uncommitted work. Per the instruction, nothing was committed or pushed. The owner options are as in the earlier reports: commit the staged layer first, or authorize a combined commit.

**Review patch:** `V6_ModuleB_liquidity_2026-11-23.patch`, SHA `a1e0a1deaacac40138be5187dbe0853e641ad25b00b8dfcbcb1e29c2f67746ed`.

## 9. Postflight

| Check | Result |
|---|---|
| HEAD / commits | unchanged / 0 |
| Index | byte-identical (e7490c2c616620c0) |
| 37 entries | identical |
| Staged diff | f724a4ad7956d99c |
| Status | f17cc47ecf32038e → 29b9fd7fdcff544f. Expected: 3 liquidity files ` M`, 2 new untracked files |
| Worktree diff | f17ea99e76c1ad70 → 48de0a66c22f2481. Expected: the liquidity stubs were replaced |
| Spec | 945180de… → 432a337c… (17.S added) |
| Module A / structure / engine / models | unchanged (hashes in the run log) |
| `.pyc` / stash | 0 / 0 |
| Remote | unchanged (only main) |
| V4 / production / merge / deploy | untouched / none |
| Scope | PAPER ONLY; no Modules C–I |

## 10. Changed files (SHA-256)

| File | Before | After |
|---|---|---|
| `scanner_v6/liquidity/__init__.py` | 60770e67… | 59ed413a5996a3db951eef4de45b6aa529d91e348a9ace2cbe2d8ca48b05a790 |
| `scanner_v6/liquidity/liquidity_pools.py` | b14a86ec… | 863615baec8e9f73cc2898c7fecc9ea257f2503b2dbe93942eb4cc9c442f2d95 |
| `scanner_v6/liquidity/sweep.py` | a88cac98… | 00aee45b95782ecd49644f3d72ebae637a151ad9b5a9363e3fe85a19eb53fdc8 |
| `scanner_v6/liquidity/setup_sweep.py` | new | 0dc2d00964c3edefeb80e7d1b93504bce1cddfe52d41d347e89bf332d09e4258 |
| `tests/scanner_v6/test_liquidity.py` | new | 4868ccd8839e4135de5363fccb10d2805ed38b9aecf52249a83a73ef85b070fb |
| `research/v6/specs/V6_TRADING_SPEC_v0.2.md` | 945180de… | 432a337c2170815ac7b2af54f511901c891875b5be9ad5579f533f25034ab352 |

Stopping here for owner review.
