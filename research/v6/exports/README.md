# V6 BOS + CHoCH test pack (`V6_BOS_CHOCH_TEST_PACK.zip`), 22 Nov 2026

**Purpose:** a self-contained bundle of the **existing, verified** V6 BOS + CHoCH test artifacts, as the regression baseline for the next research phase (Liquidity Sweep). Research only, PAPER ONLY.
- Nothing in this pack is new expected data.
- Every file is a byte-for-byte copy of an existing artifact. The source paths and SHA-256 are in `PACK_MANIFEST.json`.

## Contents

| Folder | What | Source | Status |
|---|---|---|---|
| `fixtures/volume1/` | `synthetic_volume1.draft.json` (swing / BOS / structure drafts), `swing_oracle_addendum.json` | `research/v6/specs/volume1/` | Draft fixtures. BOS cases are scored under the **approved-profile key** of each case (see `tests/scanner_v6/test_bos.py`, `APPROVED_KEY`). |
| `fixtures/choch_v0_9/` | `choch_fixtures.draft.json`: CHD01–CHD16 (decidable) and CHU01–CHU06 (unscored or superseded) | `research/v6/specs/choch_v0_9/` | `approved_rules_expected` = hand-written expectations under the owner-approved D1–D5 (22 Nov 2026). **CHU01, CHU04, CHU05 are UNSCORED.** CHU02, CHU03, CHU06 are superseded by CHD12, CHD13, CHD14. |
| `fixtures/regression/` | `medium_bos.json` (MED01 / MED02) | `tests/scanner_v6/fixtures/regression/` | Permanent BOS regression. **Note:** the content is Easy charts 1 / 2 despite the name (audit D-4). |
| `catalog/volume1/` | `TEST_CASE_CATALOG.md`, `SYNTHETIC_DATASET_PLAN.md`, `FIXTURE_REVIEW.md` | `research/v6/specs/volume1/` | Volume-1 catalogue and dataset plan (the dataset "manifest"). These are **draft documents**: approved status comes from the approval register below. |
| `catalog/choch_v0_9/` | `PHASE1_2_DECISIONS.md` (approval register: approved D1–D5, still-open items), `AUDIT_CHD01-09.md`, `README.md` | `research/v6/specs/choch_v0_9/` | Approval register, rev. 2 |
| `visual_regression/inputs/` | The **original** 12-chart pack: 12 PNG + 12 OHLC JSON + its `MANIFEST.json` + `MASTER_PROMPT_BOS_CHOCH.md` | The user's `V6_BOS_CHOCH_Visual_Test_Pack.zip` (unchanged) | PNG hashes match the pack's own MANIFEST |
| `visual_regression/marked/` | 12 marked PNG (original filenames), `RESULTS_SUMMARY.md`, `EVENTS.csv`, `MANIFEST.json` | Delivered `V6_BOS_CHOCH_BOT_MARKED_IMAGES.zip` (Phase 4 retest, detector-driven) | 12 / 12 matched the spec-derived expectation: 28 BOS, 5 CHoCH, 2 wick-only, 0 COMPLEX |
| `audit/` | `V6_BOS_CHOCH_CODE_AUDIT.md` | `research/v6/audits/` | Read-only code audit, 22 Nov 2026 |
| root | `README.md`, `TEST_INSTRUCTIONS.md`, `PACK_MANIFEST.json` | `research/v6/exports/` | – |

## Limitations

- **Unresolved items are not scored:** O4, O7, O8, O9, CHU04, CHU05, A1 and audit spec gap S-1. The pack contains **no** expected results for them.
- **Liquidity Sweep:** no fixture, no expected result and no implementation. Its research docs are separate (`research/v6/specs/liquidity_sweep/`).
- **Synthetic only.** The 12-chart pack is synthetic OHLC from the owner. Nothing here is evidence of profitability.
- **The marked PNGs are a visual record, not an oracle.** The oracle is the rules plus `approved_rules_expected` and the test suite.
- **Tests not included.** The tests themselves (`tests/scanner_v6/`) are in the repository, not in this pack. See `TEST_INSTRUCTIONS.md`.
- **Whitespace (audit D-5).** Two Volume-1 docs carry a trailing blank line at EOF. They are copied as-is, not fixed.
- **No secrets.** No credentials, `.env`, logs or production data are included.
