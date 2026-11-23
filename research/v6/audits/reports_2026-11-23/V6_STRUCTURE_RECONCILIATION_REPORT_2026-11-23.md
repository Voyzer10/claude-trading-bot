# V6 Structure Reconciliation SR-1…SR-6 — Implementation Report (23 Nov 2026)

## Result: implemented and verified; **commit / push BLOCKED (not done)**

- **Decisions:** all six are documented in the spec (Section 17.R) and implemented in `choch.py`. SR-1 needed no code change.
- **Tests:** 233/233 pass under pytest and in script mode (212 before, +21 new).
- **Independent check:** an oracle written from the 17.R text equals the new V6 on all 75 corpus charts.
- **Output changes:** every change against the frozen baseline is attributed to a decision (0 unexplained).
- **Git:** the index and all 37 staged entries are byte-identical.
- **Commit / push:** NOT done. A safe isolated commit is impossible without touching the protected staged state (section 8).

## 1. Preflight (before any edit)

| Item | Expected | Found |
|---|---|---|
| Branch | research/v6-smc-scanner | same |
| HEAD | 7f16f0953798a7b82e7cb595096487b66ab7ac3e | same |
| Index hash | e7490c2c616620c0 | same; a byte copy of the index was saved |
| Staged diff hash | f724a4ad7956d99c | same |
| Staged paths | 37 | 37, identical list; `ls-files -s` of the 37 entries saved |
| Spec SHA-256 | 835fc01360bb9156… | same |
| Status (`--porcelain=v1 -uall`) | 8551dac70c90c7d2 | same |
| Worktree diff | 207c7e9b9c789a3c | same |

## 2. Decisions implemented (exact semantics in spec 17.R)

| ID | Resolves | Rule as implemented | Code |
|---|---|---|---|
| SR-1 | U1 | An activated P-B origin stays protected when a later same-leg candidate fails A5. A5 base = the immediately previous confirmed same-kind swing. Activation timing unchanged (own confirmation, in force next candle). | none (already the behaviour of `ProtectedTracker.on_close`); pinned by tests |
| SR-2 | U2 (establishment) | No qualifying P-B origin at establishment → the establishing HL (BULLISH) / LH (BEARISH) is protected from k + 1. The first qualifying P-B origin for that direction replaces it permanently. Consumed by a CHoCH like any protected level. Any CHoCH ends it. Not used after a reversal or a restoration. | `_establish`, `protected_in_force`, step 4 replacement |
| SR-3 | U5 | A reversal-confirming BOS must break a swing confirmed at or after the CHoCH candle. One confirmed on the CHoCH candle is usable from CHoCH + 1 (D5). Otherwise role `TRANSITION_REF_BEFORE_CHOCH` + diagnostic `CONFIRMATION_REF_BEFORE_CHOCH`, no confirmation. | TRANSITION block |
| SR-4 | U6 | Every BOS gets exactly one role: `REVERSAL_CONFIRMING`, `REVERSAL_INVALIDATING`, `CONTINUATION`, `COUNTER_STRUCTURE`, `TRANSITION_REF_BEFORE_CHOCH`, `TRANSITION_AMBIGUOUS`, `PRE_STRUCTURE`. `SETUP_ELIGIBLE_BOS_ROLES = (REVERSAL_CONFIRMING,)`; a continuation BOS never starts a reversal setup. Exposed as `StructureStream.bos_roles` and `StructureReport.bos_roles`. | roles block, `StructureReport.bos_roles` |
| SR-5 | O4 (opposite-BOS part) | An opposite BOS in TRANSITION → the prior structure is restored. Event `StructureStateChange(cause="REVERSAL_INVALIDATED", related=(bos_id, choch_id))`. The consumed protected swing is never restored. Protected = P-B origin of that BOS or a later one (D2 timing), no fallback. Both directions on one candle → no change, role `TRANSITION_AMBIGUOUS`, diagnostic `TRANSITION_BOS_BOTH_DIRECTIONS`. A close-back without a BOS stays `O4_UNRESOLVED` (still OPEN). | TRANSITION block |
| SR-6 | O9 | At an establishment check, a close strictly beyond the candidate protected level (P-B origin, else the SR-2 fallback) → rejected, state stays UNKNOWN, diagnostic `ESTABLISHMENT_REJECTED_O9`, no CHoCH. Equality does not reject (CHU04). Re-checked at the next swing confirmation. | `_establish` |

**Event ordering within a candle** (D5, unchanged):
1. BOS;
2. CHoCH against the pre-candle state;
3. state update (CHoCH, or the TRANSITION outcome: confirm / invalidate / ambiguous; then roles);
4. P-B activation, SR-2 replacement, then establishment with the SR-6 check.

## 3. Files changed

**Worktree only; no index change.**

| File | Git status | Lines | SHA-256 before → after |
|---|---|---|---|
| `research/v6/specs/V6_TRADING_SPEC_v0.2.md` | untracked | +109 / −4 (17.R plus 4 cross-references) | 835fc01360bb91563f1fa101b33e93f2147fc712e1a56522287a103ce38a2d8f → 945180de90dd56fa72e43bf786e17b62a961fafbe5ec671861eb5d2e1af14a78 |
| `scanner_v6/structure/choch.py` | staged entry `M`, worktree edited (`MM`) | +100 / −23 | 7e674f4954db631938d23ae4699bbdb1f5cdccf23262446ccb773dc34297ec3a → 561f66e2deea1dfa84282537eb4c817439195be2690eac19c1a7539b438c2692 |
| `tests/scanner_v6/test_choch.py` | staged entry `A`, worktree edited (`A` → `AM`) | +14 / −4 (CHD15 superseded by SR-6) | 4ebc3706451df5666b9146581c693b89f920c7c39dd42bdb72a244b75bfa7119 → f3d6296b8e78b989c75cb32494837ee824460b79006a6fa54b82e1f862f9044e |
| `tests/scanner_v6/test_structure_reconciliation.py` | new, untracked | 349 lines, 21 tests | → 43729e28eff21c30e8687967af6bf9b56f7b8b7f438ab2976a2ef1863a660219 |

**Not changed:**
- `bos.py`, `swings.py`, `protected_levels.py`, `engine.py`, all Module A files;
- `choch_fixtures.draft.json` (historical spec artifact). The superseded CHD15 expectation lives in `test_choch.py` with its decision.

**Decision register.** The structure decisions are recorded in the governing spec (17.R; Sections 1, 11, 12 R-6 and CK-17 cross-referenced). `PHASE1_2_DECISIONS.md` is a staged file and was deliberately not edited; 17.R states that it refines D1 / D2 / A5 / D5.

**Review patch:** `V6_structure_reconciliation_SR1-SR6_2026-11-23.patch`, SHA `0ed4f18302e62e36df897de981369d032fd8dadf120ed9eb2a40ce3592736005`.

**Backups:** all pre-change files, in the scratchpad (`recon/backup/`).

## 4. Tests (all executed in this task)

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/scanner_v6/test_structure_reconciliation.py
21 passed
$ … tests/scanner_v6/test_choch.py test_defect_fixes.py test_bos.py test_regression_medium_bos.py test_replay_audit.py test_no_lookahead.py
53 passed
$ PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests/scanner_v6
233 passed            (before: 212; +21)
```

Script mode, `python3 -B tests/scanner_v6/<file>`, gives "all passed" for every file:

| File | Tests |
|---|---|
| test_bos | 7 |
| test_chart_ingestion | 50 |
| test_choch | 11 |
| test_defect_fixes | 12 |
| test_market_data | 36 |
| test_models | 12 |
| test_no_lookahead | 5 |
| test_regression_medium_bos | 6 |
| test_replay_audit | 12 |
| test_structure_reconciliation | 21 |
| test_swing_fixtures | 41 |
| test_swing_mutants | 8 |
| test_swings | 12 |
| **Total** | **233** |

**Focused coverage (`test_structure_reconciliation.py`).**

Every case runs in both directions (mirror p → 200 − p) and through `causal()`:
- `no_lookahead_violations`;
- `replay_audit` (batch + stream);
- a prefix replay at every candle (timeline, events, roles).

| Decision | Tests |
|---|---|
| SR-1 | sticky origin on the S-1 base variant (CHoCH against the kept 106); A5 base is the immediately previous swing |
| SR-2 | fallback in force from k + 1 with the establishing swing id; consumed by a CHoCH (same-candle BOS = COUNTER_STRUCTURE); equality does not consume it; first qualifying origin replaces it for good (CHoCH then against 102.8, not 101.5); not applied when an origin exists (CHD01) |
| SR-6 | rejection (UNKNOWN, no protected level, no CHoCH); boundary close == level establishes; rejection by the P-B origin (CHD15) |
| SR-3 | BOS on a pre-CHoCH swing does not confirm (role + diagnostic), then a post-CHoCH swing confirms; swing confirmed exactly on the CHoCH candle confirms at CHoCH + 1 (boundary); CHD10 |
| SR-5 | restoration with event, related ids, role, consumed swing never restored, no protected level after it (restoring origin NOT_QUALIFIED); no CHoCH without a new protected level; both-directions ambiguity (injected BOS, since no plausible candles produce it); close-back stays O4_UNRESOLVED |
| SR-4 | every BOS has exactly one valid role; setup-eligible = exactly the confirming BOS; continuation never eligible; stream equals batch roles |

**Mutation check.** The new tests were run against a copy holding the pre-change `choch.py`:
- 18 fail, as intended;
- SR-1's behavioural assertions pass on the old code (the behaviour was unchanged) and stop only at the new `bos_roles` field;
- the 2 baseline-shape tests pass.

## 5. Independent verification

`oracle2` was written from the 17.R text, on top of the audited D1–D5 / P-B oracle, with each decision switchable.

| Check | Result |
|---|---|
| oracle (all decisions off) == audited pre-change behaviour | **75/75** charts |
| New V6 events == oracle (all on) | **75/75** |
| New V6 timeline (state + protected id) == oracle | **75/75** |
| New V6 BOS roles == oracle | **75/75** |
| Changed charts with no attributable decision | **0** |

## 6. Historical 25-chart replay against the frozen baseline

- **Tool:** `run_v6.py`, the same as the visual validation.
- **New raw output SHA:** `b5df10bc0687c89d5f9623feaf5e3822b124e90b9a2a274dbb26472e81387123` (frozen: `a6d0d856…`).
- **Unchanged:** swings 25/25 and BOS 25/25 identical (BOS is structure-independent). 0 errors, 0 look-ahead, 0 replay-audit findings, 0 prefix-replay issues.
- **Changed:** 20 of 25 charts. Every difference is attributed by leave-one-out (turning off one decision removes that chart's change):

| Chart | Decision(s) | Change |
|---|---|---|
| HV01 | SR-2, SR-5 | fallback HL 3076 → **CHoCH bearish c42** (the audit's U2 example); bullish BOS c54 → REVERSAL_INVALIDATED (BULLISH restored, no protected level) |
| HV02, HV10, HV21, HV23, HV24, HV25 | SR-2, SR-5 | new CHoCH against the fallback, later invalidated by an opposite BOS |
| HV04 | SR-5 | bearish BOS c48 invalidates TRANSITION(bullish) (BEARISH restored); the old c63 "confirmation" becomes a CHoCH c63 |
| HV05, HV15 | SR-2, SR-5 | the TRANSITION that formerly ran to the end is now invalidated (c65, c46) |
| HV11 | SR-2 | new CHoCH c28 against the fallback and REVERSAL_CONFIRMED c46 |
| HV14 | SR-2, SR-3 | new CHoCH c44; confirmation c61 by a post-CHoCH swing |
| HV19 | SR-2, SR-3 | the old c53 confirmation (pre-CHoCH swing 1568.10) is now `CONFIRMATION_REF_BEFORE_CHOCH`; confirmation moves to **c61** |
| HV03, HV06, HV08, HV12, HV13, HV17, HV18 | SR-2 | protected level only (fallback present where formerly none); no event change |

Event totals over the 20 historical charts:

| Event | Added | Removed |
|---|---|---|
| CHoCH | 11 | 0 |
| REVERSAL_INVALIDATED | 10 | — |
| REVERSAL_CONFIRMED | 5 | 2 |

**Other corpora.** Every change is attributed:

| Corpus | Charts changed | Decisions involved |
|---|---|---|
| Synthetic difficulty pack | 21 / 25 | SR-2 / SR-3 / SR-5 / SR-6 (e.g. EX04: O9 establishment rejected) |
| `choch_fixtures` | 1 / 22 | CHD15, SR-6 |
| `synthetic_5m` | 1 / 1 | SR-5 |
| `easy_bos` | 0 / 2 | — |

Timelines: `timelines_after.md` (HV01, HV19).

## 7. Observations for owner review (decision-faithful; flagged, not changed)

1. **SR-5 restores the prior structure after any opposite BOS, even far from the original trend.**
   - **HV01:** BULLISH is restored at c54 by breaking a minor swing high (3018.1) formed during a roughly 100-point decline. The restored BULLISH has no protected level (the consumed 3076 is not restored; the restoring origin fails A5), so no CHoCH can follow until a later bullish BOS supplies an origin.
   - **Your call:** this is exactly SR-5 rules 3–4. If unwanted, a reference-age or protected-fallback rule for restoration would be a new decision.
2. **The "no protected level" gap remains after REVERSAL_CONFIRMED and REVERSAL_INVALIDATED.** This happens when that BOS's origin is missing or NOT_QUALIFIED. SR-2 covers establishment only, as instructed; recorded as OPEN in 17.R rule 6.
3. **CHU04 stale labels (IR-1) are still not fixed.** They were not part of this authorization. Behaviour is unchanged and correct.

## 8. Commit / push: BLOCKED

**Why no safe isolated commit exists:**
1. **HEAD lacks the structure layer.** HEAD `7f16f09` has `choch.py` as a "NOT IMPLEMENTED" stub, and only 4 files in `tests/scanner_v6`. The structure layer, its tests and the engine changes exist only in the 37 staged entries (and in the further worktree edits on top of them).
2. **Any working commit would carry protected content.** A commit containing this change must also carry the staged content of `choch.py`, `test_choch.py`, `engine.py`, `bos.py`, `protected_levels.py`, `swings.py` and others, plus the uncommitted Module A files the tests import. Even through a temporary index, that commits the protected staged work, which was not authorized.
3. **Moving HEAD changes the staged state.** Moving the branch head changes what `git diff --cached` means (`f724a4ad…` would no longer hold). Staged entries identical to the new HEAD would drop out of the staged list, and `choch.py` would become a staged *reversion* of this change. That alters the protected staged state even though the index file stays byte-identical.
4. **No remote branch.** No remote-tracking branch `origin/research/v6-smc-scanner` exists locally.

Per the instruction ("If a safe isolated commit cannot be made without changing the protected index, STOP and report the blocker"), nothing was committed or pushed.

**Options for the owner:**
- **(a)** Commit the 37 staged entries yourself (and decide on the uncommitted Module A work). I then commit this change as one isolated commit on top.
- **(b)** Authorize a single commit of the staged set + the uncommitted work + this change.
- **(c)** Keep it uncommitted. The review patch above applies cleanly to the current worktree state.

## 9. Postflight

| Check | Result |
|---|---|
| Branch / HEAD | unchanged, 0 new commits |
| Index file | **byte-identical** to the preflight copy (e7490c2c616620c0) |
| 37 staged entries (`git ls-files -s`: mode + blob) | **identical** |
| Staged diff hash | f724a4ad7956d99c (unchanged) |
| Staged paths | 37, identical list |
| Protected engine / replay-audit / fixture files | unchanged |
| Spec | 945180de… (authorized 17.R update) |
| Status (`-uall`) | 8551dac70c90c7d2 → f17cc47ecf32038e. Expected: `test_choch.py` `A ` → `AM`, plus the new untracked test file. No other status line changed |
| Worktree diff | 207c7e9b9c789a3c → f17ea99e76c1ad70. Expected: the `choch.py` / `test_choch.py` worktree edits |
| Other uncommitted files | unchanged (only the 3 listed files differ from the 177-file baseline) |
| `.pyc` / stash / push / merge / deploy | 0 / 0 / none / none / none |
| V4 / production | untouched |
| Scope | PAPER ONLY; Modules B–I not started |

Stopping here for owner review.
