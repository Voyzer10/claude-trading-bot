# V6 Module A — Final Verification and GitHub Push (23 Nov 2026)

## Result: **BLOCKED. Nothing committed, nothing pushed.** Every required test passes; the isolation proof fails.

## 1. Preflight

| Item | Value |
|---|---|
| Branch / HEAD | research/v6-smc-scanner / 7f16f0953798a7b82e7cb595096487b66ab7ac3e |
| Remote | origin = https://github.com/Voyzer10/claude-trading-bot |
| Upstream of the local branch | **origin/main** (not a branch of the same name) |
| Remote `research/v6-smc-scanner` | **does not exist** (ls-remote shows only main = 22039ecb…); HEAD 7f16f09 is not an ancestor of origin/main |
| Index | e7490c2c616620c0 (byte copy saved) |
| Staged diff | f724a4ad7956d99c |
| 37 protected entries | path + mode + blob recorded; identical to the reconciliation-preflight record |
| Status / worktree diff | f17cc47ecf32038e / f17ea99e76c1ad70 |

**Module A files in the worktree** (no other file belongs to Module A):

| File | Git status | SHA-256 |
|---|---|---|
| scanner_v6/data/candle_models.py | ` M` (not staged) | 024fd326… |
| scanner_v6/data/integrity.py | `??` | fcd9ad4f… |
| scanner_v6/data/market_config.py | `??` | 12fb9135… |
| tests/scanner_v6/test_chart_ingestion.py | `??` | 9961bf0b… |
| tests/scanner_v6/test_market_data.py | `??` | 87d2383e… |

`scanner_v6/data/__init__.py` and `tests/scanner_v6/_util.py` are unchanged from HEAD. None of the 5 files is one of the 37 staged entries.

## 2. Required tests (current worktree, all executed now)

| Check | Command | Result |
|---|---|---|
| Module A focused | `pytest tests/scanner_v6/test_chart_ingestion.py tests/scanner_v6/test_market_data.py` | 86 passed |
| 30 adversarial cases + D1–D4 + calendar cal1–cal5 | same files, `-k` on M/D/cal tests | 29 passed (the 30 cases are grouped into 22 tests) |
| Ingestion / provenance / gap-stream parity | `pytest tests/scanner_v6 -k "parity or provenance or stream …"` | 26 passed |
| No look-ahead / replay audit | `test_no_lookahead.py test_replay_audit.py` | 17 passed |
| Full suite | `pytest -q -p no:cacheprovider tests/scanner_v6` | **233 passed, 0 skipped** |
| Script mode | `python3 -B tests/scanner_v6/<file>` ×13 | 233 ok, all 13 files "all passed" |

**Historical 25-chart replay against the frozen baseline (`a6d0d856…`):**

| State | Integrity reports | Scanner output |
|---|---|---|
| Module A only (structure reconciliation reverted, temp copy) | only `gaps.status` OK → `UNKNOWN / SESSION_CALENDAR_MISSING` in 25/25 (calendar reconciliation, intended); findings identical | **identical**, 25/25 files. Raw SHA 2829da6d… differs only in the `scanner_head` field, which is empty because the temp copy is not a git repo |
| Current worktree (includes uncommitted SR-1…SR-6) | same as above | 20 files differ, all attributed to SR-2/3/5/6 (previous report); not Module A, and not part of this push |

## 3. Isolation proof: FAILED → STOP

**Method:** `git archive HEAD` was exported to a temp folder (read-only; no repo objects written), the 5 Module A files were laid on top, and the tests were run. This is exactly the tree an isolated Module A commit would have.

```
$ pytest tests/scanner_v6/test_chart_ingestion.py tests/scanner_v6/test_market_data.py   (isolated tree)
E   ImportError: cannot import name 'StructureStream' from 'scanner_v6.structure.choch'
1 error during collection
$ pytest tests/scanner_v6/test_chart_ingestion.py   (isolated tree)
50 passed
```

**Exact blocker:**
- **The dependency:** `tests/scanner_v6/test_market_data.py` lines 26–27 import `StructureStream` and `detect_structure` (`scanner_v6/structure/choch.py`) and `SwingStream` (`scanner_v6/structure/swings.py`).
- **Who uses it:** `test_a2_no_lookahead_at_candle_boundaries` and `test_deterministic_replay_through_the_provider_boundary`.
- **Why it fails in isolation:** in HEAD both files are "NOT IMPLEMENTED" stubs; the implementations exist only in the 37 protected staged entries.
- **Effect:** a Module A-only commit is not self-contained. Its test module fails to import, and CI (`ci.yml`: `push: branches: ["**"]`) would run on the pushed branch and fail.
- **The only ways around it:** include protected structure content in the commit, or edit approved Module A tests. Both are excluded ("STOP … Do not improvise").

**Secondary findings for the push itself (not reached):**
- The local branch's upstream is `origin/main`, so a bare `git push` would target main. Any push needs the explicit refspec `HEAD:refs/heads/research/v6-smc-scanner`.
- The remote branch does not exist; the push would create it, and with it the local research history (7f16f09 and its ancestors) that is not on main.
- `deploy.yml` runs only after CI succeeds on main, so a research-branch push does not deploy.

**Index handling had it been safe (planned, not executed):**
- Commit through a temporary index (HEAD tree + 5 files), then compare-and-swap the branch ref.
- Then set only the 5 Module A index entries to the committed blobs (`update-index --cacheinfo`).
- Effect: the 37 protected entries and the staged diff (f724a4ad…) stay identical. The index file hash would change, because 5 non-protected entries are updated.

## 4. Owner options

- **(a) Approve a test split.** Move the two structure-dependent tests out of `test_market_data.py` into a later structure-layer test file. The Module A commit is then self-contained: the isolated run would be `test_chart_ingestion` 50 plus the rest of `test_market_data`.
- **(b) Commit the staged structure layer first** (owner action or explicit authorization). Module A can then be committed as one isolated commit on top.
- **(c) Authorize a combined commit** of the staged set + Module A (+ SR-1…SR-6 if wanted).

## 5. Postflight

| Check | Result |
|---|---|
| HEAD | unchanged, 0 new commits |
| Index | byte-identical (e7490c2c616620c0) |
| 37 entries | identical |
| Staged diff | f724a4ad7956d99c |
| Status / worktree diff | identical (f17cc47ecf32038e / f17ea99e76c1ad70) |
| Repo files touched | 0 new or modified |
| `.pyc` / stash | 0 / 0 |
| Remote | unchanged (only main 22039ecb…); nothing pushed |
| V4 / production / merge / deploy | untouched / none |
| Scope | PAPER ONLY; no Modules B–I |
