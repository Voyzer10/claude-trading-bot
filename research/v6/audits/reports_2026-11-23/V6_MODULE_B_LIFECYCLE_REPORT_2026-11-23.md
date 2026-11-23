# V6 Module B: Owner Decisions + Setup Lifecycle Corrections (23 Nov 2026)

V6 PAPER ONLY. Nothing touched in V4 or production, and no work on Modules C–I. No commit, push, merge or deploy.

## 1. Spec 17.S changes (`research/v6/specs/V6_TRADING_SPEC_v0.2.md`, SHA 432a337c… → 70cf672b…)

Owner decisions are recorded as OWNER APPROVED (23 Nov 2026):

| ID | Rule |
|---|---|
| MB-1 | A bullish REVERSAL_CONFIRMING BOS gives a BUY setup, which requires an SSL sweep. |
| MB-2 | A bearish REVERSAL_CONFIRMING BOS gives a SELL setup, which requires a BSL sweep. |
| MB-3 | The BOS is eligible from its own candle j; sweeps count only from j+1. Eligibility ends at the **first opposite CHoCHBreak** or the **first opposite BOS (any role)**. A same-direction (CONTINUATION) BOS does not end it. When it ends at candle k, only that BOS's pending candidate becomes INVALIDATED at k, with closed_by set to the terminating event id. No other event ends eligibility. |
| MB-4 | REPEAT_SWEEP and TAKEN never start a candidate while OQ-12 is OPEN. |

Other spec changes:
- The "Derived mapping (owner confirmation requested)" paragraph is removed.
- The OPEN BOS-currency bullet is replaced by an OQ-12 + MB-4 note.
- The rows in the implemented table are updated.
- OQ-12, LQ-03/07-other/10/11/12-R1/13-annotation/20, G-3/9/10 and BOS-006/C1 are all **still OPEN**.

## 2. `setup_sweep.py` review: findings and fixes

| Item reviewed | Before | After |
|---|---|---|
| Pending check | A global check: any PENDING candidate blocked a new one | Per BOS: `pending_for(bos_id)`, which raises an assertion if a BOS has more than one pending candidate |
| `_close()` | Closed **every** pending candidate | Removed. `close_candidate(key, status, k, reason)` closes **exactly one** candidate, keyed by (bos_id, group_id). It validates: terminal status, known key, candidate still PENDING, k equal to the candle just processed, and k ≥ the sweep candle. |
| CONFIRMED → OQ-5 r4 | Set a flag on the "current" BOS | Sets `bos_states[c.bos_id].confirmed_setup`, i.e. on the candidate's own BOS |
| Opposite CHoCH / BOS | Closed all pending candidates | Invalidates only `pending_for(cur.bos_id)`, records ended_index and ended_by, and emits the diagnostic `BOS_ELIGIBILITY_ENDED` |
| Continuation BOS | Did not end eligibility (correct) | Unchanged, and now tested explicitly |
| Bookkeeping | `_CurrentBOS` | `_BOSState` per BOS (`bos_states`) plus `current_bos_id`. A new eligible BOS while another is current raises an assertion (structurally impossible, because a new reversal needs a CHoCH first). |
| Side-map comment | "derived" | "17.S MB-1 / MB-2, OWNER APPROVED" |

Rules kept as they were:
- one candidate per group; OQ-5 r1–r6;
- deterministic ordering: structure first at candle k, then liquidity groups;
- prefix snapshots: `close_candidate` overwrites `snapshots[-1]` with the post-close state.

**Honest note on impact:** the old global logic was a latent defect. It did not produce wrong output in any reachable state, because at most one BOS can be eligible at a time. That is why the corpus before/after comparison is identical (section 4). The fix makes the isolation explicit and asserted. It also gives Module C a way to close an exact candidate by its key.

**Not changed:**
- `liquidity_pools.py`, `sweep.py`, `__init__.py` and `reclaim.py` (SHA-identical to the pre-task files);
- pool lifecycle, sweep classification, event and group ids;
- Module A and the structure layer.

## 3. Tests (`tests/scanner_v6/test_liquidity.py`: 29 → 40 tests)

- All existing assertions are kept. Two tests were adapted only for the new `close_candidate` signature:
  - the `setup_run` helper;
  - `test_close_candidate_rejects_bad_calls` keeps its original assertions and adds a KeyError case and a wrong-k case.
- 11 new tests, each run mirrored for BUY/SELL where a direction applies:
  1. owner side mapping (MB-1/2)
  2. dual-pivot pool creation
  3. within-candle event and group ordering
  4. lifecycle PENDING / EXPIRED / CONFIRMED / INVALIDATED
  5. one pending candidate per BOS, and close isolation by key
  6. a continuation BOS keeps eligibility (a candidate at k26 after a continuation BOS at k25)
  7. an opposite CHoCH **alone** ends eligibility (k28)
  8. an opposite BOS **alone** (COUNTER_STRUCTURE) ends eligibility (k30)
  9. REPEAT_SWEEP / TAKEN never start a candidate, checked with injected events and with real k25/k28 events
  10. same-candle BOS/sweep rejection, plus the lifecycle afterwards
  11. prefix replay + stream/batch parity for the new scenarios
- Mutation check: all 4 mutants are caught.

| Mutant | Change | Tests failing |
|---|---|---|
| m1 | eligibility ends on any BOS | 1 |
| m2 | REPEAT/TAKEN start candidates | 5 |
| m3 | side mapping flipped | 15 |
| m4 | same-candle sweep allowed | 2 |

## 4. Verification (exact commands, run from the repo root)

```
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/scanner_v6/test_liquidity.py   -> 40 passed
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/scanner_v6                     -> 273 passed (0 skipped)
for f in tests/scanner_v6/test_*.py; do python3 -B $f; done                                                -> 273 ok, every file "all passed"
python3 -B scratchpad/modB2/tools/dump.py after.json  (75 charts) vs before.json                           -> 0 differences in pools,
     events, groups, candidates, diagnostics, snapshots, structure, bos, roles
python3 -B scratchpad/modB/tools/corpus_replay.py                                                          -> lookahead 0 and
     replay_findings 0 in all 5 corpus sets
python3 -B scratchpad/modB/tools/liq_oracle.py                                                             -> 75/75 events match,
     75/75 groups match
run_v6.py (historical 25 charts)                                                                           -> raw sha256 b5df10bc…7123
     (unchanged), forbidden_opened [], integrity reports differing 0, scanner events differing 0
```

**Before/after replay:** identical across all 75 charts. There are **no intentional output changes**: the corrections are structural (per-BOS and per-key isolation, plus the close API), and the corpus never reaches a state where two BOS candidates coexist. Candidate counts are unchanged:

| Corpus set | Candidates |
|---|---|
| difficulty_synthetic | 8 INVALIDATED, 2 PENDING |
| historical | 1 PENDING |

Structure output is unchanged, and so are the Module A outputs (integrity reports and raw SHA).

## 5. Git and safety

- Preflight and postflight:
  - the index is byte-identical (`cmp` against the preflight copy);
  - all 37 staged entries (mode/blob/stage/path) are identical;
  - the staged diff is `f724a4ad7956d99c`;
  - `git status --porcelain -uall` is identical (the changed files were already untracked);
  - HEAD is `7f16f0953798a7b82e7cb595096487b66ab7ac3e`;
  - remote: main is `22039ec…` and has no v6 branch;
  - no new `.pyc` files (the existing ones in api/ and tests/ predate this task).
- **Isolation proof FAILED (same blocker as before):** `git archive HEAD` plus the liquidity files gives `ModuleNotFoundError: No module named 'scanner_v6.data.integrity'`. Module B depends on the structure layer and Module A, which live only in the staged entries and the worktree. **No commit and no push were made.**

## 6. Hashes

| File | SHA-256 (first 16 hex) |
|---|---|
| `setup_sweep.py` | 0dc2d00964c3edef → 18b354acfe3e1642 |
| `test_liquidity.py` | 4868ccd8839e4135 → e1b25d99f7386626 |
| spec | 432a337c2170815a → 70cf672b73e6ed82 |
| patch `V6_ModuleB_lifecycle_2026-11-23.patch` | 9fba7406a4fdba30 (reverse-applies cleanly) |

## 7. Unresolved (still OPEN; nothing was invented)

- OQ-12: whether REPEAT_SWEEP / TAKEN belong to a group.
- LQ-03, LQ-07 (other expiry forms), LQ-10 (GRAB/RUN), LQ-11, LQ-12 R1 reclaim, LQ-13 annotation, LQ-20.
- G-3, G-9, G-10; BOS-006 / C1 tick epsilon.
- Module C onwards: pattern window, EXPIRED / NO_TRADE / CONFIRMED triggers, entry. These modules will call `close_candidate(key, …)`.
- Commit blocker: the isolated commit is impossible while the structure layer and Module A remain only in the protected staged entries or the worktree. Owner options (a), (b) and (c) are still pending.
- Pending owner answer: whether to push only 7f16f09 to `research/v6-smc-scanner`.
