# LIQUIDITY_SWEEP_DECISIONS: LQ Decision Register (created 22 Nov 2026; owner decisions recorded 22 Nov 2026; delegated MVP decisions recorded 23 Nov 2026)

**Documentation only. PAPER ONLY.**
- **LQ decisions (LQ-01…LQ-22):** 15 APPROVED, 4 PARTIALLY APPROVED, 1 PROPOSED, 2 OPEN.
  - Owner decisions of 22 Nov 2026: 11 APPROVED, 1 PARTIALLY APPROVED (LQ-10).
  - **Delegated MVP decisions of 23 Nov 2026** (OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT IMPLEMENTED):
    LQ-02, LQ-05, LQ-18, LQ-19 APPROVED; LQ-07, LQ-12, LQ-13 PARTIALLY APPROVED. MVP scope only.
- **External owner decisions (outside LQ):** 1 APPROVED (CHU04 STRICT). Counted separately from the LQ decisions.
- Approved supporting rules: LS-S02, LS-S09, LS-S11, LP-12 (pool part). Exact G-2 / G-6 id formats decided 23 Nov 2026
  (delegated, OQ-4): `pool:<swing_id>`, `sweep:<BSL|SSL>:<k>` (zero-based k), `liquidity:<pool_id>:<event_type>:<k>`. Approved definitions: G-1, G-2, G-4, G-5, G-6,
  G-7, G-8, G-11. Still open: G-3, G-9, G-10.
- Not approved: LQ-03 and LQ-11 (OPEN; MVP-scope notes only), LQ-20 (PROPOSED), the GRAB / RUN part of LQ-10 and
  the named open parts of LQ-07, LQ-12 and LQ-13.
- **No liquidity detector exists or was written.** No scanner code, test, specification, V4 or production file was
  changed. The source documents in `research/v6/specs/liquidity_sweep/` and the CHoCH specifications are unchanged; they
  still show the earlier state (traceability: `CONTRADICTIONS_AND_GAPS.md` §E).

| File | Content |
|---|---|
| `LQ_DECISION_REGISTER.md` | LQ-01…LQ-22. For each decision: status, the owner decision (verbatim, dated) where one exists, the verbatim source question, B0 proposal and alternatives, what each option changes, a minimal OHLC example, dependencies, the pre-approval research note and spec references. Also: supporting rules, supporting definitions (G-*), external owner decisions (CHU04), outside-LQ items, and what is not yet verified technically. |
| `DEPENDENCY_MAP.md` | Hard dependencies, overlaps, a dependency table with each dependency's status, and the decision order (tiers 0–3 decided, tiers 4–5 remaining). |
| `lq_dependency_map.mmd` / `.png` | The same map as Mermaid source and a rendered image (green = approved, light green dashed = partially approved, blue = proposed, orange = open, grey dashed = open outside LQ). |
| `CONTRADICTIONS_AND_GAPS.md` | 5 contradictions, 4 overlaps and 11 missing definitions, each with its status; source-vs-register traceability (§E); technical notes (§F). |
| `lq_decision_register.json` | Machine-readable form of the register (counts, statuses, owner decisions, supporting rules and definitions, edges, order). |
| `scripts/` | `register_data.py` (single source, including the verbatim owner decisions), `build_register.py` (generator; it checks verbatim source rows, allowed statuses, owner text for every approved item and none for any other, cycles and order before writing). |
| `SHA256SUMS` | Checksums of every file in this folder |

**Status meaning (LQ decisions):**
- **APPROVED:** explicit owner decision of 22 Nov 2026, recorded verbatim.
- **PARTIALLY APPROVED:** the approved part is recorded verbatim; the remaining part is named and stays OPEN.
- **OWNER APPROVED — DELEGATED DECISION:** an APPROVED or PARTIALLY APPROVED decision finalized under the owner's
  delegated authority for the initial PAPER-ONLY MVP (23 Nov 2026); marked per decision; documented, not implemented.
- **PROPOSED:** B0 has a concrete proposal; not approved.
- **OPEN:** no concrete proposal, or B0 is a placeholder, "not modelled" or "excluded"; not approved.

**Four layers kept apart:** existing approved structure rules (earlier phases); owner-approved liquidity decisions
(22 Nov 2026); still proposed / open decisions; technical implementation, which is **not yet verified** (no detector,
no liquidity tests). Implementing a detector needs separate owner authorization.

Regenerate: `python3 -B scripts/build_register.py .` (from this folder), then render `lq_dependency_map.png` from the
`.mmd` with `mmdc` and rewrite `SHA256SUMS`.
