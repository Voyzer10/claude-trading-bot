# V6 Volume 1 specification set: swings, market structure, BOS (DRAFT)

Source: *V6 SMC Scanner Training Pack, Volume 1* (PDF supplied 21 Nov 2026). The PDF describes itself as a proposed research specification; nothing in it is an approved trading rule.

This folder holds analysis and specifications only. No detector is implemented. Nothing here is imported by `scanner_v6`, the runner or the broker.

| File | Content |
|---|---|
| `SWING_CONCEPT_ANALYSIS.md` | Concepts, timing, assumptions, gaps; each statement classified |
| `SWING_RULE_MATRIX.md` | Rule ids SW-R01..R18 with conditions, timing, edge cases, tests, status; pseudocode |
| `MARKET_STRUCTURE_SPEC.md` | HH / HL / LH / LL, state, protected levels, internal vs external |
| `BOS_CONCEPT_ANALYSIS.md` | BOS concepts, BOS vs CHoCH, required event fields vs the existing models |
| `BOS_RULE_MATRIX.md` | Rule ids BOS-R01..R13; pseudocode; batch vs streaming |
| `SYNTHETIC_DATASET_PLAN.md` | 39 hand-built cases with OHLC tables and expected events per illustrative profile |
| `synthetic_volume1.draft.json` | The same 39 cases, machine-readable (draft) |
| `TEST_CASE_CATALOG.md` | 100 test rows; each marked NOT RUN or EXECUTED with its result |
| `UNRESOLVED_DECISIONS.md` | Every open decision with alternatives, impact and fixtures; model gaps G1–G13 |

Labels used throughout:
- **SOURCE RULE**: stated in the PDF.
- **INVARIANT**: data or causality correctness.
- **ILLUSTRATIVE**: example only.
- **UNRESOLVED**: needs your decision.
- **PROPOSAL**: an implementation option.
