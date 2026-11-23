# V6 Liquidity Sweep: Phase 1 research (22 Nov 2026)

**Status:**
- Research and documentation only. **No liquidity pool, sweep or reclaim detector exists.**
- `scanner_v6/liquidity/*.py` are still the original NOT-IMPLEMENTED stubs.
- BOS / CHoCH behaviour is unchanged.
- PAPER ONLY. No V4, production, broker or deployment change.

| File | Content |
|---|---|
| `VIDEO_SOURCE_NOTES.md` | What was accessed. **Transcripts for V1 and V3 were not obtained; no video was watched.** V2 transcript read via the web tool. Source tags used everywhere. |
| `LIQUIDITY_CONCEPT_ANALYSIS.md` | The 18 concepts: definitions, sources, alternatives, OHLC examples, pros / cons, false positives, testability, B0, open questions; an instructor-difference table |
| `LIQUIDITY_POOL_RULE_MATRIX.md` | Pool rules LP-01…LP-12 |
| `SWEEP_RULE_MATRIX.md` | Sweep rules LS-S01…LS-S12 |
| `RECLAIM_RULE_ANALYSIS.md` | Readings R0 / R1 / R2; R1 tied to O4 |
| `EVENT_ORDERING_ANALYSIS.md` | Liquidity step 2L inside the approved D5 order; same-candle table |
| `SYNTHETIC_DATASET_PLAN.md` | LS01–LS12, EQ01 / EQ02 with OHLC and mirrors. BOS / CHoCH facts verified with the approved code. |
| `TEST_CASE_CATALOG.md` | LT-01…LT-16, no-look-ahead, parity, regression; each marked SCORABLE-IF-B0 / UNSCORED / APPROVED-CHECK |
| `UNRESOLVED_DECISIONS.md` | LQ-01…LQ-22 |

**Proposed experimental baseline B0 (NOT approved):**
- **Pools:** every confirmed L2/R2 swing (BSL at highs, SSL at lows), active from confirmation + 1.
- **Sweep:** a wick strictly beyond and a close not beyond (S-wick). It is the exact complement of the approved BOS / CHoCH close rule. Minimum depth 0 is only the **proposed** value (LQ-09 OPEN).
- **Close beyond:** the pool is TAKEN, not swept.
- **Events:** one sweep event per pool; several pools on one candle give one event each.
- **Excluded:** displacement, multi-candle reclaim, equal-level pools, internal / external, inducement and trendlines. They stay out until decided.
- **Structure:** sweeps never change the structure state.

## Phase 1.1 Consistency Audit (22 Nov 2026)

**Scope:** documentation only. Reviewed:
- SWEEP_RULE_MATRIX
- LIQUIDITY_POOL_RULE_MATRIX
- UNRESOLVED_DECISIONS
- VIDEO_SOURCE_NOTES
- EVENT_ORDERING_ANALYSIS
- TEST_CASE_CATALOG
- README

No code, test behaviour, BOS / CHoCH or git state was changed. Status labels are kept as before: **INV** (follows from approved rules), **B0** (proposed, not approved), **ALT**, **OPEN**.

### Issues found and corrections made

| # | Issue | Before | Correction (after) | Files |
|---|---|---|---|---|
| 1 | **LQ-10 vs LS-S12**: grab called a "synonym" while the taxonomy was OPEN | LQ-10 B0: "grab is a synonym"; LS-S12: grab vs sweep split OPEN, with no link between them | Three layers separated (SWEEP_RULE_MATRIX §A): **instructor terminology** (recorded, not a rule), **event naming** (B0: BSL_SWEEP / SSL_SWEEP + TAKEN state, no GRAB event; naming LQ-17 OPEN), **detector behaviour** (B0: one S-wick test). LQ-10 now states what B0 does and what stays OPEN (a GRAB split; a RUN event). LS-S12 is restated as that open question. LQ-11 is tied to LQ-10. | SWEEP_RULE_MATRIX, UNRESOLVED_DECISIONS |
| 2 | **LQ-09 vs LS-S01**: depth OPEN but used implicitly | LS-S01 used a strict `>` with no note; LQ-09 said "0 (strict >)" | LS-S01, LS-S05, LQ-09 and this README now say that d = 0 is **only the proposed B0 value, not approved**, and that LS-S01 depends on LQ-09 | SWEEP_RULE_MATRIX, UNRESOLVED_DECISIONS, README |
| 3 | **LP-05 vs LP-12**: BOS consumption and pool lifecycle merged | LP-12: "the pool of that swing becomes TAKEN by the same close" (reads as caused by the BOS) | LP-12 rewritten: **separate concepts**. BOS reference consumption is the approved BOS-005 / D4 rule; pool TAKEN is its own liquidity rule LS-S02. They coincide on the same close only because the conditions are identical. New transition table §A (T1–T8) covers: swept; swept then closed through; closed through directly; BOS on the same level; older non-reference pool closed through (TAKEN, no BOS); TAKEN pool; not-yet-active pool. | LIQUIDITY_POOL_RULE_MATRIX, EVENT_ORDERING_ANALYSIS |
| 4 | **LP-04**: requirements for EQ candidates undocumented | "exact tie", "from the tie window close + 1" | §B lists what is still needed: tie window (current L/R-window diagnostic vs separated double tops), number of observations, creation time (first vs last window close), SW-004 interaction (liquidity-only; merging with a strict swing at the same price), no-look-ahead (`window_closed_index ≤ k−1`, no repaint), equality / ticks. **No algorithm proposed.** | LIQUIDITY_POOL_RULE_MATRIX, UNRESOLVED_DECISIONS (LQ-03) |
| 5 | **LP-07**: no-expiry consequences unanalysed | "Pools do not expire by time" | §C analyses stale levels, similar-price pools, newer same-side swings, session boundaries (O7, BOS-006) and historical accumulation, with ALT remedies. LQ-07 and LT-13 stay OPEN / UNSCORED. | LIQUIDITY_POOL_RULE_MATRIX, UNRESOLVED_DECISIONS |
| 6 | **LS-S09**: protected-swing wick sweep vs WICK_ONLY vs state | "a sweep of the protected HL == the WICK_ONLY diagnostic" (implied a one-to-one match) | §B: two outputs from two modules (liquidity **event** + CHoCH **diagnostic**); neither changes state; only the CHoCH layer owns the state. Asymmetry documented: WICK_ONLY fires on every such candle, a sweep only once per pool (otherwise REPEAT_SWEEP). LT-16 rewritten as a one-directional check. O9 edge noted (unscored). LQ-22 updated. | SWEEP_RULE_MATRIX, TEST_CASE_CATALOG, UNRESOLVED_DECISIONS, EVENT_ORDERING_ANALYSIS |
| 7 | **LS-S11**: no worked outside-bar example | a one-line example | §C: candle-by-candle D5 walk-through of LS07 (c18 104 / 117 / 100 / 116.5: SSL_SWEEP 101, BOS ↑ 116, BSL 116 TAKEN, WICK_ONLY, state unchanged) and the bearish mirror LS07m (c18 96 / 100 / 83 / 83.5). The pool history before c18 is listed. BOS / CHoCH facts were re-verified with the approved code; the pool outcomes are B0. | SWEEP_RULE_MATRIX, EVENT_ORDERING_ANALYSIS, TEST_CASE_CATALOG |

**Reviewed, no change needed:** VIDEO_SOURCE_NOTES. Its source tags and access limits are consistent with the corrected documents.

**LIQUIDITY_CONCEPT_ANALYSIS §8 (updated in Phase 1.2):** §8 now documents three layers separately:
- instructor terminology (attributed to V1-art, V1-AI, V2-tx, V3);
- the proposed B0 detector event naming: BSL_SWEEP / SSL_SWEEP, no GRAB event;
- the proposed B0 detector behaviour: one S-wick test.

It no longer presents grab "as a synonym" as a decision. Still OPEN:
- **LQ-10:** the GRAB / SWEEP taxonomy;
- **LQ-10 / LQ-11:** the RUN taxonomy and its momentum criterion;
- **LQ-17:** event naming.

### Decisions still requiring human approval

All of LQ-01…LQ-22 remain **unapproved**. The ones this audit touched:

| Decision | What remains open |
|---|---|
| LQ-03 | Whether EQ pools exist; every §B item |
| LQ-06 | Whether SWEPT stays usable (B0) or the first sweep consumes the pool |
| LQ-07 | Expiry (B0 "none" is a placeholder) |
| LQ-08 | The S-wick definition itself |
| LQ-09 | Depth d (B0 proposes 0) |
| LQ-10 / LQ-11 | A GRAB split; a RUN event or attribute |
| LQ-17 | Naming |
| LQ-22 | The no-state-effect rule for protected-swing sweeps |

B0 rules without their own LQ id also need approval: LS-S02, LS-S09, LS-S11, LP-12 (pool part).

Still open from the CHoCH work: O4 (tied to LQ-12), O7 (sessions; §C), O9 (§B edge), CHU04 (close == P; LS-S01), and A1.
