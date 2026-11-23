# V6 Trading Specification

## 1. Document metadata

| Field | Value |
|---|---|
| Title | V6 Trading Specification |
| Version | 0.2 (revised 23 Nov 2026: Candlestick Formation Rules v0.1 recorded as Section 16; clarifications CS-1…CS-10 recorded in Section 16.J; decisions CK-1…CK-10 recorded in Section 16.L; decisions CK-11…CK-13 (with the CK-11 overlap clarification) recorded in Section 16.M; decision CK-14 recorded in Section 16.N; delegated MVP decisions CK-15…CK-27 recorded in Section 17; OQ-1…OQ-7 resolved in Section 17.O; implementation-readiness clarifications IR-1…IR-3 (CHU04 labels, candlestick pattern count, synthetic test tick size) recorded in Section 17.P; OQ-14 (canonical `<pattern_type>` tokens) and OQ-15 (test-only synthetic fixture configuration) resolved in Section 17.Q; structure reconciliation decisions SR-1…SR-6 (U1, U2, U5, U6, O4 opposite-BOS part, O9) recorded and implemented in Section 17.R) |
| Scope | V6 only (`research/v6-smc-scanner`) |
| Mode | **PAPER ONLY**. No broker, no live trading, no real orders |
| Status | **Owner decisions recorded; implementation not authorized by this document** |
| Approval dates | 22–23 November 2026 (conversation-level owner decisions) |
| Supersedes | Draft "V6 Trading Engine — Entry & Exit Rule Specification v0.1" (owner draft supplied in conversation, not stored in the repository) for every item decided here; items still open there stay open |

**What this document is.** It records decisions the owner gave in Claude sessions on 22–23 November 2026. A
conversation-level approval means the rule is decided; it does **not** mean any code exists. Section 14 gives the
implementation status found by a read-only audit.

**Status labels used**

| Label | Meaning |
|---|---|
| **OWNER APPROVED** | Explicit owner decision recorded in conversation |
| **PARTIALLY APPROVED** | Part approved (stated); the remaining part is named and is OPEN |
| **OPEN** | Not decided. Must not be filled in by an implementer |
| **PROPOSED** | An agent or draft proposal awaiting owner approval; not a rule |
| **IMPLEMENTED** / **NOT IMPLEMENTED** | Repository state reported by the read-only audit of 23 Nov 2026 |
| **UNVERIFIED** | Could not be confirmed from the repository |
| **TESTED** / **NOT TESTED** | Whether repository tests for the rule exist and pass (reported from the repository, never assumed from approval) |
| **OWNER APPROVED — DELEGATED DECISION** | A decision finalized under the owner's delegated authority for the initial PAPER-ONLY MVP (Section 17, 23 Nov 2026); documented, not implemented |

Related documents (unchanged by this one):
- `research/v6/specs/choch_v0_9/PHASE1_2_DECISIONS.md`: approved swing, BOS and CHoCH rules (SW-001…005,
  BOS-001…005, Option A, A1–A10 approved parts, D1–D5, D2 P-B, A5).
- `research/v6/audits/LIQUIDITY_SWEEP_DECISIONS/`: the liquidity decision register (LQ-01…LQ-22, supporting rules,
  G-* definitions, CHU04).
- `research/v6/specs/liquidity_sweep/`: the original liquidity specification (source documents).

## 2. Strategy sequence — OWNER APPROVED

```
CHoCH → BOS → Liquidity Sweep → Candlestick Formation → Confirmation → Entry
```

This is the owner's **selected** V6 strategy sequence. It is not a universal trading rule and not a claim that this
order is how markets work. A later stage may not create or assume an earlier stage that has not been confirmed, and
every stage is evaluated only with candles closed at that time (no look-ahead, no backdating; LQ-21, D5).

The Candlestick Formation and Confirmation stages are specified in Section 16 (OWNER APPROVED 23 Nov 2026; NOT
IMPLEMENTED; NOT TESTED).

How the stages map to the approved structure rules is partly OPEN (Section 12, B-1 to B-5): for example whether "BOS"
is always the D1 confirming BOS after the CHoCH, and whether the sweep must come after that BOS.

## 3. Liquidity direction — OWNER APPROVED

| Sweep | Setup |
|---|---|
| SSL sweep (sell-side liquidity below a swing low) | BUY setup |
| BSL sweep (buy-side liquidity above a swing high) | SELL setup |

- A sweep alone never triggers an entry. The candlestick formation and confirmation stages must follow.
- Sweep, SWEPT, TAKEN and REPEAT_SWEEP have the meaning in the liquidity register (LQ-06, LQ-08, LQ-15, LS-S02).
- Which pools count as "relevant" for a setup is OPEN (Section 12, B-5).
- Pattern bias after the sweep (CS-9, Section 16.J): an SSL sweep requires a bullish-bias pattern and a BSL sweep a
  bearish-bias pattern; neutral patterns alone cannot qualify a directional setup.
- Pattern biases are listed in CK-5; one sweep generates at most one trade setup (CK-7, Section 16.L). A
  context-labelled pattern without its required trend context (for example SIDEWAYS, CK-4) cannot qualify a
  directional setup.

## 4. Entry — OWNER APPROVED (details OPEN where stated)

| Rule | Status |
|---|---|
| Entry at the **open of the next candle** after the confirmation candle C, i.e. candle C+1 | OWNER APPROVED |
| Entry slippage: configurable **fixed ticks per instrument** (`entry_ticks`) | OWNER APPROVED |
| Final position sizing and Net R:R are recalculated with the **actual entry fill** | OWNER APPROVED |
| Maximum entry gap: configurable **ticks per instrument** | OWNER APPROVED |
| If the entry gap exceeds the configured maximum: `NO_TRADE` | OWNER APPROVED |
| If the next open is **at or beyond the planned SL**: `NO_TRADE` (BUY: open ≤ SL; SELL: open ≥ SL) | OWNER APPROVED |
| The entry candle C+1 itself is checked for SL / TP **after** the entry fill | OWNER APPROVED |

Entry fill (from Model A, Section 8), with `T` = tick size of the instrument:
- BUY: `entry_fill = open(C+1) + entry_ticks × T`
- SELL: `entry_fill = open(C+1) − entry_ticks × T`

**OPEN entry details** (Section 12):
- The reference price for the entry gap (for example the close of C, or a planned entry price) and whether only an
  adverse gap counts or a gap in either direction.
- The maximum entry gap values per instrument.
- Rounding of the fill to the tick grid and its precision.

**Update 23 Nov 2026 (delegated, CK-19, Section 17):** entry method `NEXT_OPEN`; no chasing; no delayed entry after a
missing, incomplete or out-of-session next candle. The gap reference is the confirmation close and only the adverse
gap counts; the maximum adverse gap is 0.25 × planned_risk_distance. This **revises** the "ticks per instrument" row
above; owner confirmation requested (17.N, OQ-1). Fill rounding and precision stay OPEN (instrument precision, CK-26).
*[Superseded 23 Nov 2026 by the OQ-1 resolution (17.O): not a replacement; both limits apply and the stricter wins:
`max_adverse_gap = min(configured_max_gap_ticks * tick_size, 0.25 * planned_risk_distance)`. Missing configured maximum ticks or tick size → `EXECUTION_CONFIG_INCOMPLETE`.]*

## 5. Stop-loss — OWNER APPROVED (values OPEN)

| Rule | Status |
|---|---|
| BUY SL: **below the relevant sweep candle's low** | OWNER APPROVED |
| SELL SL: **above the relevant sweep candle's high** | OWNER APPROVED |
| A configurable buffer beyond the sweep candle extreme | OWNER APPROVED (rule); **values OPEN** |
| SL is fixed after entry | OWNER APPROVED |
| Separate configurable stop-exit slippage, `stop_exit_ticks`, per instrument | OWNER APPROVED |

Planned SL: BUY `SL = sweep_candle_low − buffer`; SELL `SL = sweep_candle_high + buffer`.

Stop fills:

| Case | BUY position | SELL position |
|---|---|---|
| Normal stop hit (BUY: low ≤ SL; SELL: high ≥ SL) | `SL − stop_exit_ticks × T` | `SL + stop_exit_ticks × T` |
| Gap through the stop (candle opens beyond SL) | `open − stop_exit_ticks × T` | `open + stop_exit_ticks × T` |

There is **no additional gap slippage** beyond the configured `stop_exit_ticks`.

No buffer default exists. Which sweep candle is "relevant" when several sweeps occur is OPEN (Section 12, B-4).

**Update 23 Nov 2026 (delegated, CK-20, Section 17):** the SL references the SSL (BUY) / BSL (SELL) sweep candle of
the setup; the buffer is configured in ticks per instrument; missing buffer configuration gives
`EXECUTION_CONFIG_INCOMPLETE`; no future-confirmed swing is used; the SL is never moved to force R:R or sizing.
Buffer values stay OPEN (B-12).

## 6. Take-profit — OWNER APPROVED

| Rule | Status |
|---|---|
| BUY TP: the **nearest eligible ACTIVE BSL pool** | OWNER APPROVED |
| SELL TP: the **nearest eligible ACTIVE SSL pool** | OWNER APPROVED |
| SWEPT and TAKEN pools are **ineligible** as targets | OWNER APPROVED |
| TP is fixed after entry | OWNER APPROVED |
| A **touch** of the TP price is sufficient to trigger the exit (BUY: high ≥ TP; SELL: low ≤ TP) | OWNER APPROVED |
| BUY and SELL target fill at the **exact TP price** | OWNER APPROVED |
| `target_exit_ticks` must be **explicitly configured as 0** | OWNER APPROVED |
| A gap beyond TP still fills **at TP**, not at the better opening price | OWNER APPROVED |
| If the nearest eligible pool cannot achieve **Net R:R ≥ 1:1**: `NO_TRADE` | OWNER APPROVED |
| A farther pool is **not** tried unless separately approved | OWNER APPROVED |

> **Simplified paper limit-order assumption.** Exact-TP fills on touch and on gaps are a deliberate paper-simulation
> simplification. They are not a guarantee of real-world fills (queue position, partial fills and gap behaviour of a
> real limit order are not modelled).

OPEN (Section 12): from which candle a pool must be active to be a TP candidate (the pools known at entry time),
how "nearest" is measured (from the actual fill or a planned price), and tie-breaking between equally near pools.

**Update 23 Nov 2026 (delegated, CK-16 and CK-21, Section 17):** the TP pool is the nearest eligible ACTIVE opposing
pool above (BUY) / below (SELL) the **actual entry**, using only pools known at the entry decision time; ties at one
price go to the earliest confirmed pool, then stable pool-ID ordering (pool id `pool:<swing_id>`, OQ-4 resolved, 17.O); no eligible pool gives
`NO_TRADE`. The TP price is placed one tick (configurable) before the pool on the entry side (17.N, OQ-8).

## 7. Risk and position sizing — OWNER APPROVED (policies OPEN where stated)

| Rule | Status |
|---|---|
| Maximum risk per trade: **1% of paper account equity** | OWNER APPROVED |
| Sizing includes price risk, fees and slippage | OWNER APPROVED |
| Entry fees and expected exit fees are included | OWNER APPROVED |
| Entry slippage and stop-exit slippage are included in the stop-risk calculation | OWNER APPROVED |
| Quantity rounds **down** by lot size and quantity step; **never upward** | OWNER APPROVED |
| The final estimated loss at the stop must not exceed the 1% budget | OWNER APPROVED |
| Minimum **Net R:R 1:1**, after fees and slippage | OWNER APPROVED |
| Minimum tradable quantity exceeding the risk budget | `NO_TRADE` with `MIN_QTY_EXCEEDS_RISK_BUDGET`: OWNER APPROVED (CK-13, CK-14; reconciled 23 Nov 2026) |
| Insufficient paper margin | Reduce quantity, revalidate, else `NO_TRADE`: OWNER APPROVED (CK-14; reconciled 23 Nov 2026) |
| Paper equity basis (realized cash vs mark-to-market) | Mark-to-market: `cash + unrealized P&L - applicable fees and slippage`; OWNER APPROVED — DELEGATED DECISION (OQ-6 resolved, 17.O). Costs already in cash are not deducted twice; the estimated exit-cost convention is OPEN (OQ-13) |
| Operating limits: one open position; daily loss 2% of start-of-day paper equity; no martingale, averaging down or automatic re-entry | OWNER APPROVED — DELEGATED DECISION (CK-23, Section 17) |

Definitions used by the rules above (multiplier `M` per instrument; fees from the instrument's fee schedule):

```
risk budget          B = 0.01 × E
stop loss estimate   Loss(q) = q × |entry_fill − stop_fill| × M + Fees(entry, q) + Fees(stop exit, q)
quantity             largest q on the lot / step grid with Loss(q) ≤ B
net R:R              (q × |target_fill − entry_fill| × M − Fees(entry, q) − Fees(target exit, q)) / Loss(q)
```

Fee rates, their sources, fee rounding and the instrument master are OPEN (Section 12). No fee value is approved by
this document.

## 8. Slippage — OWNER APPROVED: Model A, FIXED TICKS

Three separate configurable parameters per instrument:

| Parameter | Used for |
|---|---|
| `entry_ticks` | Entry fill at the next open (adverse) |
| `stop_exit_ticks` | Stop exit, normal and gap (adverse) |
| `target_exit_ticks` | Target exit; must be explicitly configured as 0 (Section 6) |

- **No default values are approved.**
- Missing execution configuration must **never** be treated as zero. Proposed safe behaviour (**PROPOSED**, not yet
  approved): `NO_TRADE("execution config incomplete")`.
  **Update 23 Nov 2026:** now approved as reason code `EXECUTION_CONFIG_INCOMPLETE` (CK-13) and required for every
  missing mandatory value (delegated, CK-22 and CK-26). Zero slippage is never assumed.
- Configuration schema, versioning, source and effective date of the values: OPEN (Section 12).

## 9. Execution rules — OWNER APPROVED

| Rule | Status |
|---|---|
| SL and TP both touched in one candle: **STOP_FIRST** | OWNER APPROVED |
| STOP_FIRST applies to historical backtesting **and** paper simulation | OWNER APPROVED |
| STOP_FIRST applies to the entry candle after the entry fill | OWNER APPROVED |
| Target gap fills at the exact TP | OWNER APPROVED |
| Stop gap fills at the opening price with the configured stop slippage | OWNER APPROVED |
| No additional gap slippage | OWNER APPROVED |
| **Never clamp** a calculated fill to the candle's high / low | OWNER APPROVED |
| Keep the calculated fill and record an **out-of-range diagnostic** | OWNER APPROVED |

Backtest and paper simulation must use the same deterministic fill and cost functions; this follows from STOP_FIRST
applying to both, and the single shared implementation is an agent recommendation (**PROPOSED**).

**Update 23 Nov 2026 (delegated, CK-22, Section 17):** `SL_FIRST` there is the same rule as `STOP_FIRST`; entry at or
beyond SL is rejected before entry; entry at or beyond TP is revalidated (net R:R) and rejected if invalid; partial
fills are not simulated; ambiguous intrabar ordering takes the adverse outcome first.

**Update 23 Nov 2026 (OQ-3, 17.O):** data interruptions are tracked in a separate `data_state` field (`NORMAL`,
`DATA_INTERRUPTED`, `DATA_RESUMED`); no candle, fill or exit is fabricated, and no SL / TP execution is claimed for an
unobserved interval.

## 10. Trade management — OWNER APPROVED: FIXED_SL_TP

- No trailing stop.
- No breakeven.
- No partial profit.
- No modification of SL or TP after entry.

## 11. Liquidity decision references

The full text lives in `research/v6/audits/LIQUIDITY_SWEEP_DECISIONS/LQ_DECISION_REGISTER.md`; it is referenced here,
not restated or changed.

| Item | Status |
|---|---|
| LQ-01, LQ-04, LQ-06, LQ-08 (incl. close == P sub-case), LQ-09, LQ-14, LQ-15, LQ-16, LQ-17, LQ-21, LQ-22 | OWNER APPROVED (22 Nov 2026) |
| LQ-10: B0 uses SWEEP and TAKEN only | PARTIALLY APPROVED; GRAB / RUN taxonomy OPEN |
| LS-S02, LS-S09, LS-S11, LP-12 (pool part) | OWNER APPROVED (22 Nov 2026) |
| G-1, G-4, G-5, G-7, G-8 (interim raw float), G-11 | OWNER APPROVED (22 Nov 2026) |
| G-2 (group id `sweep:<side>:<k>`), G-6 (stable, traceable ids) | Principle OWNER APPROVED; `k` is zero-based (CK-9). Exact formats decided 23 Nov 2026 (delegated, OQ-4, 17.O; also in the register): pool `pool:<swing_id>`; group `sweep:<side>:<k>` with `<side>` = `BSL` or `SSL`; liquidity event `liquidity:<pool_id>:<event_type>:<k>`. Group-membership scope partly OPEN (OQ-12) |
| CHU04 STRICT (CHoCH close comparison; equality → NO_CHOCH, protected swing not consumed). Exact rule: bullish structure → CHoCH only when `close < protected_low`; bearish structure → CHoCH only when `close > protected_high`; `close == protected_level` → `NO_CHOCH`; equality does not consume or invalidate the protected swing; consistent with the strict-close BOS rule (BOS-002). Stale code / test labels: 17.P IR-1 | OWNER APPROVED external decision (22 Nov 2026) |

Unresolved liquidity details, preserved as OPEN:
- ~~G-2: the exact `<side>` token.~~ Resolved 23 Nov 2026 (OQ-4): `BSL` or `SSL`; `k` zero-based (CK-9).
- ~~G-6: exact pool and event identifier formats.~~ Resolved 23 Nov 2026 (OQ-4): see the row above.
- LQ-10: GRAB / RUN taxonomy. (TAKEN is emitted as a distinct event since OQ-4; whether it is also a named RUN event stays
  with the open part of LQ-10.)
- G-3 (ids for non-swing pools), G-9 (high vs low resistance liquidity), G-10 (zone sources).
- LQ-03 and LQ-11 (OPEN) and LQ-20 (PROPOSED); the open parts of LQ-07, LQ-12 and LQ-13 (below).

**Update 23 Nov 2026 (delegated MVP scope, CK-15, Section 17; register reconciled):**

| Item | Status |
|---|---|
| LQ-02 (no major / minor distinction), LQ-05 (not modelled), LQ-18 (not modelled), LQ-19 (excluded) | OWNER APPROVED — DELEGATED DECISION (MVP scope) |
| LQ-07: no expiry merely due to elapsed time | PARTIALLY APPROVED (delegated); other expiry forms OPEN |
| LQ-12: no reclaim condition beyond LQ-08 for the MVP | PARTIALLY APPROVED (delegated); R1 reclaim semantics with O4 OPEN |
| LQ-13: displacement not required for setup qualification | PARTIALLY APPROVED (delegated); the later annotation (C-5) OPEN |
| LQ-03 (EQ pools excluded from the MVP), LQ-10 (GRAB / RUN excluded from the MVP), LQ-11 | Status unchanged; MVP-scope note only |
- Outside LQ: O4 (opposite-BOS part resolved by SR-5, 17.R; close-back part OPEN), O7, ~~O9~~ (resolved by SR-6, 17.R), A1, CHU05, BOS-006 / C1 (B0 uses raw float meanwhile, G-8).

## 12. Open decisions

None of these may be filled in by an implementer.

### Blockers (needed before an end-to-end trade can be implemented and scored)

| ID | Open decision | Notes |
|---|---|---|
| B-1 | Candlestick numeric thresholds | **OWNER APPROVED 23 Nov 2026** (Section 16.C–16.E), clarified by CS-1…CS-6 (OWNER APPROVED, Section 16.J). Remaining items: Section 16.K |
| B-2 | Confirmation formulas | **OWNER APPROVED 23 Nov 2026** (Section 16.F), clarified by CS-7 and CS-8 (OWNER APPROVED). Remaining items: Section 16.K |
| B-3 | Pattern expiry and setup expiry | **OWNER APPROVED 23 Nov 2026**: confirmation window of 3 completed candles (Section 16.G, CS-7) and sweep-to-pattern window of 5 completed candles (CS-9). Remaining items (window counting for multi-candle patterns): Section 16.K |
| B-4 | Setup invalidation, and relevant sweep selection | **PARTIALLY APPROVED**: pattern-level invalidation before confirmation is OWNER APPROVED (Section 16.G). Still OPEN: structure-level invalidation (e.g. CHoCH or opposite BOS before entry, O4); which sweep candle defines the SL when several occur; whether the sweep must follow the BOS. **Update 23 Nov 2026 (delegated):** opposite confirmed CHoCH / BOS before entry invalidates (CK-18); the sweep must be strictly after the BOS confirmation candle (CK-17); the SL uses the setup's sweep candle (CK-20). Several sweep groups after one BOS: resolved (OQ-5, 17.O) |
| B-5 | Relevant pool selection | Which SSL / BSL sweeps count for a setup (ties to LQ-02 / LQ-05). **Update 23 Nov 2026 (delegated, CK-15, CK-16):** BUY requires an SSL sweep and SELL a BSL sweep; the MVP makes no major / minor or internal / external distinction |
| B-6 | TP candidate timing and tie-breaking | Pools active at which candle; "nearest" from the fill or a planned price; equal distances. **Update 23 Nov 2026 (delegated, CK-16):** pools known at the entry decision time; nearest to the actual entry; earliest confirmed, then stable pool-ID ordering. Pool-ID format resolved (OQ-4, 17.O) |
| B-7 | Tick-size source and instrument master snapshot | Dated snapshot; lot size, quantity step, minimum quantity, multiplier. Also needed by CK-1 (tick-based epsilon and trend threshold) and CK-2 (canonical instrument and timeframe identifiers). A synthetic fixture's test-only tick size (17.P IR-3) does not fill this item |
| B-8 | Fee rates and sources | Per market / instrument, with source and effective date |
| B-9 | Fee rounding | Per component or total; currency precision |
| B-10 | Slippage values | `entry_ticks`, `stop_exit_ticks` per instrument; `target_exit_ticks` = 0 |
| B-11 | Maximum entry gap values and reference | Reference price and adverse-only vs both directions. **Update 23 Nov 2026 (delegated, CK-19):** reference = confirmation close; adverse gap only; maximum = 0.25 × planned_risk_distance (configurable). Combined with the Section 4 tick limit: both apply, the stricter wins (OQ-1 resolved, 17.O) |
| B-12 | SL buffer values | Per instrument; ticks or price. **Update 23 Nov 2026 (delegated, CK-20):** ticks per instrument; values still OPEN (configuration, CK-26) |
| B-13 | Fill-price rounding and precision | Tick-grid rounding direction. Instrument precision must be configured (CK-26); rounding rule still OPEN |
| B-14 | Minimum quantity behaviour | Proposed `NO_TRADE`; not approved. **Update 23 Nov 2026:** decided: `NO_TRADE` with `MIN_QTY_EXCEEDS_RISK_BUDGET` (CK-13, CK-14) |
| B-15 | Margin insufficiency | Reduce quantity or reject. **Update 23 Nov 2026:** decided by CK-14 (reduce quantity, revalidate, else `NO_TRADE`) |
| B-16 | Paper equity basis | Realized cash vs mark-to-market; refresh timing. Resolved: mark-to-market (OQ-6, 17.O); account-level day boundary across different sessions OPEN (OQ-11) |
| B-17 | G-2 and G-6 exact formats | Needed for deterministic ids and scoring. **Partly decided:** `k` in G-2 is zero-based (CK-9). Candlestick pattern, confirmation and setup id formats are decided (CK-2); the `<pattern_type>` token set is decided by OQ-14 (17.Q). **Resolved 23 Nov 2026 (delegated, OQ-4, 17.O):** `<side>` = `BSL` / `SSL`; pool id `pool:<swing_id>`; liquidity event id `liquidity:<pool_id>:<event_type>:<k>`. Group-membership scope partly OPEN (OQ-12) |
| B-18 | Open positions at the end of historical data | How a trade still open at the last candle is closed or scored. **Update 23 Nov 2026 (delegated, CK-25):** decided: `OPEN_UNRESOLVED`, not force-closed, excluded from win rate and realized P&L |
| B-19 | Session boundaries and next-open semantics | Next open across a session break (O7). **Update 23 Nov 2026 (delegated, CK-24):** instrument-specific session calendar and time zone; no normal next-open entry on a first post-session candle without session rules. Session rules resolved (OQ-7, 17.O); O7 (CHoCH sessions / gaps in the structure layer) remains OPEN |
| B-20 | Missing execution configuration | Proposed `NO_TRADE("execution config incomplete")`; not approved. **Update 23 Nov 2026:** decided: `EXECUTION_CONFIG_INCOMPLETE` (CK-13; delegated CK-26) |

### Deferrable refinements (not needed for a single-trade correctness test)

| ID | Open decision |
|---|---|
| R-1 | Maximum concurrent positions. **Update 23 Nov 2026 (delegated, CK-23):** one open position across the initial paper account |
| R-2 | Daily loss limit and total exposure. **Update 23 Nov 2026 (delegated, CK-23):** 2% of start-of-day paper equity; equity basis resolved (OQ-6, 17.O) |
| R-3 | Market-data interruption behaviour (live / paper forward running). **Update 23 Nov 2026 (delegated, CK-24):** decided; interruptions tracked in `data_state` (OQ-3, 17.O) |
| R-4 | Funding, overnight charges and currency conversion scope |
| R-5 | GRAB / RUN taxonomy (LQ-10) and the other PROPOSED / OPEN LQ items. **Update 23 Nov 2026:** GRAB / RUN excluded from the MVP (CK-15); see Section 11 for the reconciled LQ statuses |
| R-6 | Remaining outside-LQ items: A1, CHU05, BOS-006 / C1 (raw float meanwhile). O9 resolved by SR-6 (17.R, 23 Nov 2026) |

## 13. Historical blind-test requirements (test philosophy)

- Four difficulty levels: Easy, Medium, Hard, Extreme.
- Expected answers are prepared and **sealed before** the bot runs; the bot receives fixture data only and never
  the answer key.
- No look-ahead: no future-confirmed swing at an earlier candle, no backdated events.
- Deterministic: the same input and configuration give byte-identical output.
- BUY and SELL mirror cases; gap, outside-bar, multiple-pool and same-candle SL / TP cases.
- **Separate scorecards per layer**: structure, liquidity, candlestick and confirmation, entry, risk and sizing,
  execution and exit, end-to-end lifecycle, no-look-ahead and determinism. No single combined percentage.
- Item results: **PASS / FAIL / UNSCORABLE** (pending rule) / **NOT_IMPLEMENTED** / **BLOCKED_UPSTREAM**.
- Only approved rules are scored.
- Correctness is **not** proof of profitability. A high pass rate establishes no trading edge.

Scenario counts per level are **proposals only**, not approved values.

The ten mandatory candlestick test cases are listed in Section 16.I (required future tests; NOT TESTED).

The required initial validation coverage of the whole MVP pipeline and its eight scorecards are listed in CK-27
(Section 17; delegated decision; NOT TESTED).

## 14. Implementation status (findings of the read-only audit of 23 Nov 2026)

These are the audit's reported findings, not independently re-verified by this document.

| Area | Status |
|---|---|
| Structure layer (swings, BOS, protected swing, CHoCH, CHU04 strict behaviour) | IMPLEMENTED in staged / working-tree changes; **not committed in HEAD** (`7f16f09`); 126 tests reported passing |
| Liquidity detector | NOT IMPLEMENTED (`scanner_v6/liquidity/*` stubs); data models (`LiquidityPool`, `SweepEvent`, `ReclaimEvent`) only partially present |
| Candlestick patterns and confirmation | NOT IMPLEMENTED; NOT TESTED (`scanner_v6/entry/candlesticks.py` and `scanner_v6/entry/confirmation.py` are "NOT IMPLEMENTED" stubs). The rules, clarifications CS-1…CS-10 and decisions CK-1…CK-10 (including the setup lifecycle statuses) were OWNER APPROVED on 23 Nov 2026 (Section 16); approval does not change this status |
| Entry, SL, TP, sizing, costs, slippage and execution | NOT IMPLEMENTED |
| Delegated MVP decisions CK-15…CK-27 (Section 17) | NOT IMPLEMENTED; NOT TESTED (documented 23 Nov 2026) |
| `PAPER_ONLY = True`, `PLACES_ORDERS = False` (`scanner_v6/config.py`) | IMPLEMENTED |
| Isolation from V4 (forbidden-import test) | IMPLEMENTED |
| V4 / shared cost and fill behaviour (`paper.py`, `research_costs.py`, `scanner_v4.py`) | **Not approved for V6**; reference only |

Documentation conflicts reported by the audit (not changed by this document): the `scanner_v6/README.md` status
paragraph contradicts itself; the `SweepEvent` docstring describes a sweep as a pool "taken out" (LQ-06 / LS-S02
separate SWEEP and TAKEN); `PoolSide` uses ABOVE / BELOW while LQ-17 names BSL / SSL. CHU04 is OWNER APPROVED
(STRICT, Section 11) and the `choch.py` behaviour matches it (no CHoCH on equality, protected swing kept); only its
labels are stale: the `choch.py` docstring and the `EXACT_LEVEL_CLOSE` diagnostic text still call CHU04 unresolved, and
the test `tests/scanner_v6/test_defect_fixes.py::test_d2_exact_level_close_is_not_wick_only_and_chu04_stays_open`
asserts that text. These labels are **not fixed**; changing them needs a separately authorized code and test change
(17.P IR-1).

## 15. Safety and authorization

- **This document does not authorize implementation.**
- No live trading, no broker connection, no real orders. PAPER ONLY.
- No changes to V4 or production.
- No commits, pushes, merges or deployments are authorized by this document.
- Any future code implementation requires **separate, explicit owner authorization**.

## 16. Candlestick Formation Rules v0.1 — OWNER APPROVED (23 Nov 2026)

| Item | Status |
|---|---|
| Approval | **OWNER APPROVED**: conversation-level owner approval, 23 November 2026 |
| Clarifications CS-1…CS-10 (Section 16.J) | **OWNER APPROVED — CONVERSATION-LEVEL — 23 NOVEMBER 2026** |
| Decisions CK-1…CK-10 (Section 16.L) | **OWNER APPROVED — CONVERSATION-LEVEL — 23 NOVEMBER 2026** |
| Decisions CK-11…CK-13 (Section 16.M) | **OWNER APPROVED — DOCUMENTED, NOT IMPLEMENTED** (conversation-level, 23 Nov 2026) |
| CK-11 overlap clarification (16.M) and decision CK-14 (Section 16.N) | **OWNER APPROVED — DOCUMENTED, NOT IMPLEMENTED** (conversation-level, 23 Nov 2026) |
| Implementation | Detection (16.A–16.E, 16.H DETECTED events) **IMPLEMENTED** 24 Nov 2026 in `scanner_v6/entry/candlesticks.py` (17.T). Confirmation, expiry and invalidation (16.F, 16.G) **NOT IMPLEMENTED** (`scanner_v6/entry/confirmation.py` is a stub) |
| Tests | Detection **TESTED** (`tests/scanner_v6/test_candlesticks.py`, 17.T). Confirmation rows of 16.I **NOT TESTED** |
| Authorization to implement | **None.** Approval of these rules does not authorize implementation (Section 15) |

The thresholds below are the approved **initial configurable V6 baseline**. They are not claimed to be universally
optimal or profitable. Configuration parameter names are not yet defined (OPEN).

### 16.A Pattern scope (10 canonical pattern families)

| # | Pattern | Candles |
|---|---|---|
| 1 | Classic Doji | 1 |
| 2 | Gravestone Doji | 1 |
| 3 | Long-legged Doji | 1 |
| 4 | Inverted Hammer | 1 |
| 5 | Dragonfly Doji | 1 |
| 6 | Hammer / Hanging Man | 1 |
| 7 | Bullish / Bearish Engulfing | 2 |
| 8 | Shooting Star | 1 |
| 9 | Morning Star | 3 |
| 10 | Evening Star | 3 |

*[Counting clarified 23 Nov 2026 (17.P IR-2; scope unchanged): the 10 rows are canonical geometric pattern families.
Row 6 is one family with two contextual labels (Hammer, Hanging Man); row 7 is one two-candle family with two
directional variants (Bullish Engulfing, Bearish Engulfing). Labels and variants are not extra families.]*

### 16.B OHLC calculations

For each candle (O, H, L, C):

```
R  = H - L                 range
B  = abs(C - O)            body
UW = H - max(O, C)         upper wick
LW = min(O, C) - L         lower wick

BodyRatio     = B / R
UpperRatio    = UW / R
LowerRatio    = LW / R
CloseLocation = (C - L) / R
```

If **R = 0**, the candle is **invalid / UNSCORABLE** for pattern detection: no ratio is computed (no division by
zero).

### 16.C Common thresholds

| Term | Rule |
|---|---|
| Doji | BodyRatio <= 0.10 |
| Small body | BodyRatio <= 0.30 |
| Large body | BodyRatio >= 0.60 |
| Dominant wick | wick >= 2 × body |
| Small opposite wick | opposite wick <= 0.10 × range |

### 16.D Individual pattern rules

#### 16.D.1 Classic Doji
- BodyRatio <= 0.10.
- Both upper and lower wick present (a wick is present only when wick > 0; CS-4).
- Bias: NEUTRAL (CS-3).

#### 16.D.2 Gravestone Doji
- BodyRatio <= 0.10.
- UpperRatio >= 0.60.
- LowerRatio <= 0.10.
- Bias: BEARISH_BIAS (CS-3).

#### 16.D.3 Long-legged Doji
- BodyRatio <= 0.10.
- UpperRatio >= 0.25.
- LowerRatio >= 0.25.
- Bias: NEUTRAL (CS-3).

#### 16.D.4 Inverted Hammer
- BodyRatio <= 0.30.
- Upper wick >= 2 × body.
- Lower wick <= 0.10 × range.
- Required preceding trend: **DOWNTREND** (CS-1). This supersedes the original wording "Bullish context required
  for this label".
- Bias: BULLISH_BIAS (CK-5).

#### 16.D.5 Dragonfly Doji
- BodyRatio <= 0.10.
- LowerRatio >= 0.60.
- UpperRatio <= 0.10.
- Bias: BULLISH_BIAS (CS-3).

#### 16.D.6 Hammer / Hanging Man
- BodyRatio <= 0.30.
- Lower wick >= 2 × body.
- Upper wick <= 0.10 × range.
- Same shape; the preceding trend determines Hammer vs Hanging Man (CS-1): **Hammer** after a **DOWNTREND**,
  **Hanging Man** after an **UPTREND**.
- Bias: Hammer BULLISH_BIAS; Hanging Man BEARISH_BIAS (CK-5).

#### 16.D.7 Bullish / Bearish Engulfing
- Two-candle pattern.
- Bullish: previous candle bearish, current candle bullish, current body fully engulfs previous body.
- Bearish: the reverse.
- Wick engulfment is not compulsory.
- Equal body boundaries are allowed (inclusive comparison); a Doji candle (C == O) is neither bullish nor bearish
  for Engulfing; no additional trend-context condition (CS-6).
- Pattern range: `pattern_high = max(previous_high, current_high)`, `pattern_low = min(previous_low, current_low)`,
  used for confirmation and invalidation (CS-8).

#### 16.D.8 Shooting Star
- BodyRatio <= 0.30.
- Upper wick >= 2 × body.
- Lower wick <= 0.10 × range.
- Required preceding trend: **UPTREND** (CS-1). This supersedes the original wording "Bearish context required".
- Bias: BEARISH_BIAS (CK-5).

#### 16.D.9 Morning Star
- Three candles.
- First candle large bearish: BodyRatio >= 0.60.
- Middle candle small: BodyRatio <= 0.30.
- Third candle large bullish: BodyRatio >= 0.60.
- Third candle closes above the midpoint of the first candle's body.
- A gap is not compulsory.
- Bias: BULLISH_BIAS (CK-5).

#### 16.D.10 Evening Star
- Three candles.
- First candle large bullish.
- Middle candle small.
- Third candle large bearish.
- Third candle closes below the midpoint of the first candle's body.
- A gap is not compulsory.
- Bias: BEARISH_BIAS (CK-5).

("Large" and "small" use the common thresholds of 16.C.)

### 16.E Trend context (approved initial method, as clarified by CS-5)

- Inspect the last 5 completed candles.
- Compare their average close with the previous 5 completed candles' average close.
- Higher average = bullish context.
- Lower average = bearish context.
- Negligible difference = sideways (`SIDEWAYS`, CS-5). Fewer than the ten required candles = `UNKNOWN` (CS-5).
- The pattern candles are **not** included in the calculation (CS-5).
- If context cannot be identified reliably, do not force a directional label: use `UNCLASSIFIED_SHAPE`.
- Candlestick context must **not** overwrite the CHoCH / BOS structure state.

The negligible-difference threshold is configurable per instrument; its approved default is
`TREND_NEUTRAL_THRESHOLD = 2 × TickSize` (CK-1, 16.L). Terminology mapping: CK-3. SIDEWAYS labels: CK-4.

### 16.F Confirmation rules

Pattern detection and confirmation are **separate layers**.

- Bullish pattern: a completed candle closes **strictly above** the pattern high (CS-7).
- Bearish pattern: a completed candle closes **strictly below** the pattern low (CS-7).
- Window: any of the next three completed candles after pattern detection; the first qualifying candle emits the
  confirmation event (CS-7). This supersedes the original wording "the next completed candle".
- Pattern high / low: the pattern candle's high / low for single-candle patterns; the full pattern formation high /
  low for three-candle patterns; the combined two-candle range for Engulfing (CS-8).
- Neutral patterns such as Classic Doji and Long-legged Doji do not independently create directional confirmation.
- A pattern alone must **never** trigger BUY, SELL or an order.
- The confirmation event is emitted only after the confirmation candle closes.
- After confirmation, the existing V6 next-open entry rule applies (Section 4).

### 16.G Expiry and invalidation

- Maximum confirmation window: 3 subsequent completed candles.
- No confirmation within the window = `EXPIRED`.
- A bullish setup is invalidated if a candle closes below the pattern low before confirmation.
- A bearish setup is invalidated if a candle closes above the pattern high before confirmation.
- One pattern can emit at most one confirmation event.
- No look-ahead: candle k's pattern is available only after candle k closes.
- Pattern statuses: `DETECTED`, `CONFIRMED`, `EXPIRED`, `INVALIDATED`. Each pattern has at most one terminal event:
  `CONFIRMED`, `EXPIRED` or `INVALIDATED` (CS-10).

### 16.H Pattern event output (logical shape)

```json
{
  "pattern": "BULLISH_ENGULFING",
  "direction": "BULLISH",
  "start_candle": 120,
  "end_candle": 121,
  "detection_candle": 121,
  "body_ratio": 0.72,
  "upper_wick_ratio": 0.08,
  "lower_wick_ratio": 0.20,
  "context": "BEARISH",
  "status": "DETECTED",
  "confirmation_status": "PENDING"
}
```

`direction` is a **potential pattern direction, not a trade instruction**. The values are an example of the shape.

Schema rules (CS-10):
- Candle indexing is **zero-based**.
- Confirmation is a **separate event** containing `pattern_id`, `confirmation_candle`, `direction`, `timestamp`.
- Event ids must be stable and deterministic. The approved id formats are given in CK-2 (16.L).
- `status` takes the values listed in 16.G.

### 16.I Mandatory test cases (required future tests; NOT TESTED)

| # | Required test | Status |
|---|---|---|
| 1 | Exact threshold boundary | NOT TESTED |
| 2 | Just below / above a threshold | NOT TESTED |
| 3 | Zero-range candle | NOT TESTED |
| 4 | Same shape with a different trend context | NOT TESTED |
| 5 | Bullish / bearish mirrored fixtures | NOT TESTED |
| 6 | Correct confirmation event | NOT TESTED |
| 7 | Confirmation expiry | NOT TESTED |
| 8 | Invalidation before confirmation | NOT TESTED |
| 9 | An incomplete candle must not be detected | NOT TESTED |
| 10 | No-look-ahead verification | NOT TESTED |

### 16.J Clarifications CS-1…CS-10 — OWNER APPROVED — CONVERSATION-LEVEL — 23 NOVEMBER 2026

The ten interpretation questions recorded earlier on 23 Nov 2026 were answered by the owner. Each decision below is
**OWNER APPROVED**, **NOT IMPLEMENTED** and **NOT TESTED**. Where a decision supersedes earlier wording, the affected
rule in 16.D–16.H says so.

#### CS-1 — Trend context labels

| Pattern | Required preceding trend |
|---|---|
| Inverted Hammer | DOWNTREND |
| Shooting Star | UPTREND |
| Hammer | DOWNTREND |
| Hanging Man | UPTREND |

- Pattern shape is determined using OHLC. The preceding trend determines the contextual label.
- If context is unavailable, use `UNCLASSIFIED_SHAPE` rather than forcing a directional label.
- This clarification supersedes the contradictory original context wording for these four patterns (16.D.4, 16.D.8).

#### CS-2 — Multiple overlapping patterns

- One candle may satisfy multiple pattern definitions.
- Retain all valid pattern labels.
- Do not impose automatic priority.
- Do not suppress one pattern merely because another pattern also matches.
- Example: a candle can qualify as both Dragonfly Doji and Hammer.

#### CS-3 — Doji directional classification

| Pattern | Classification |
|---|---|
| Gravestone Doji | BEARISH_BIAS |
| Dragonfly Doji | BULLISH_BIAS |
| Classic Doji | NEUTRAL |
| Long-legged Doji | NEUTRAL |

These are pattern biases, not BUY / SELL signals.

#### CS-4 — Wick presence and floating-point precision

- A wick is present only when wick > 0.
- Zero wick means absent.
- Use a configurable floating-point tolerance for threshold comparisons (**no numeric default is approved**).
  *[Superseded 23 Nov 2026 by CK-1 (16.L): the default is `OHLC_COMPARISON_EPSILON = TickSize × 0.000001`.]*
- Preserve original OHLC prices.
- The tolerance must not modify original prices or artificially create a wick.

#### CS-5 — Trend-context calculation

1. Calculate the average close of the last five completed candles.
2. Calculate the average close of the five completed candles immediately preceding those.
3. Compare the two averages.
4. Higher recent average = `BULLISH`.
5. Lower recent average = `BEARISH`.
6. Difference within the configured negligible-difference threshold = `SIDEWAYS`.
7. Pattern candles must not be included in the trend-context calculation.
8. If all ten required historical candles are unavailable, context = `UNKNOWN`.

The negligible-difference threshold remains configurable; **no numeric default is approved**.
*[Superseded 23 Nov 2026 by CK-1 (16.L): the default is `TREND_NEUTRAL_THRESHOLD = 2 × TickSize`.]*

#### CS-6 — Engulfing boundaries

- The current candle body must fully engulf the previous candle body.
- Equal body boundaries are allowed; use inclusive comparisons.
- A Doji (C == O) is neither bullish nor bearish for Engulfing classification.
- Engulfing does not require an additional trend-context condition.
- Wick engulfment is not compulsory.

#### CS-7 — Confirmation window

- Confirmation can occur in any of the next three completed candles after pattern detection.
- Bullish confirmation: close strictly above the pattern high.
- Bearish confirmation: close strictly below the pattern low.
- The first qualifying candle emits the confirmation event.
- If none qualifies within three candles, status = `EXPIRED`.
- Never emit confirmation before the qualifying candle closes.
- For multi-candle patterns, use the approved full pattern range defined in CS-8 where applicable.

#### CS-8 — Engulfing pattern range

For Bullish / Bearish Engulfing:

```
pattern_high = max(previous_high, current_high)
pattern_low  = min(previous_low, current_low)
```

- Both candles contribute to the combined pattern range.
- Confirmation and invalidation use this combined range.
- Do not use only the second candle's high / low for Engulfing confirmation or invalidation.

#### CS-9 — Sweep-to-pattern window

- The sweep candle itself cannot count as the subsequent candlestick pattern.
- The pattern must form within the next five completed candles after the sweep.
- If no eligible pattern forms within five candles, setup status = `EXPIRED`.
- An SSL sweep requires a bullish-bias pattern.
- A BSL sweep requires a bearish-bias pattern.
- Neutral patterns alone cannot qualify a directional setup.
- The strategy sequence is unchanged: CHoCH → BOS → Liquidity Sweep → Candlestick Formation → Confirmation → Entry.
  Liquidity rules are unchanged.

#### CS-10 — Event schema and candle indexing

- Candle indexing is zero-based.
- Pattern statuses: `DETECTED`, `CONFIRMED`, `EXPIRED`, `INVALIDATED`.
- Confirmation is represented by a separate event.
- The confirmation event includes `pattern_id`, `confirmation_candle`, `direction`, `timestamp`.
- Event ids must be stable and deterministic.
- Each pattern may have at most one terminal event: `CONFIRMED`, `EXPIRED` or `INVALIDATED`.
- The exact event id format is not defined here: **OPEN** (16.K).
  *[Superseded 23 Nov 2026 by CK-2 (16.L): the pattern, confirmation and setup id formats are approved.]*

### 16.K Remaining OPEN items (CK-1…CK-13 resolved in 16.L and 16.M)

No CK item is open. CK-1…CK-10 were answered by the owner on 23 Nov 2026 (Section 16.L); CK-11, CK-12 and CK-13
were answered later the same day (Section 16.M). Open decisions outside the CK series remain in Section 12.

### 16.L Decisions CK-1…CK-10 — OWNER APPROVED — CONVERSATION-LEVEL — 23 NOVEMBER 2026

Each decision below is **OWNER APPROVED**, **NOT IMPLEMENTED** and **NOT TESTED**. They add to CS-1…CS-10 (16.J).
CK-1 and CK-2 supersede three notes in 16.J ("no numeric default is approved" in CS-4 and CS-5, and "id format OPEN"
in CS-10); those notes are kept and marked as superseded. No other CS wording changed. No implementation
authorization is granted.

#### CK-1 — Numeric tolerance and trend neutral threshold

OHLC comparison epsilon:

```
OHLC_COMPARISON_EPSILON = TickSize × 0.000001
```

- Instrument-specific.
- Applies to strict and inclusive OHLC comparisons.
- Original OHLC values remain unchanged.
- Tick size unavailable → pattern evaluation UNSCORABLE.
- No arbitrary fallback value.

Trend neutral threshold:

```
TREND_NEUTRAL_THRESHOLD = 2 × TickSize

D = recent five-candle average close - previous five-candle average close
```

- D > threshold → BULLISH.
- D < -threshold → BEARISH.
- Otherwise → SIDEWAYS.
- Ten required candles unavailable → UNKNOWN.
- Tick size unavailable → context UNKNOWN.
- Both parameters configurable per instrument.

Suggested configuration representation (**documentation only**; not added to any application or configuration file):

```yaml
candlestick:
  comparison:
    epsilon_multiplier: 0.000001
  trend_context:
    neutral_threshold_ticks: 2
    recent_window: 5
    previous_window: 5
```

Both parameters depend on the instrument's tick size, whose source is still OPEN (Section 12, B-7).

*[Synthetic test fixtures may declare a test-only tick size (17.P IR-3). That value is never a production instrument
configuration and never a fallback for a missing one; this decision and its formulas are unchanged.]*

#### CK-2 — Deterministic event id formats

```
Pattern:       pattern:<instrument>:<timeframe>:<start_candle>:<pattern_type>
Confirmation:  confirmation:<pattern_id>:<confirmation_candle>
Setup:         setup:<sweep_group_id>:<pattern_id>
```

- Deterministic ids.
- Same input produces the same id.
- Candle indices are zero-based.
- No random UUID.
- Canonical instrument and timeframe identifiers.
- Duplicate event generation must be preventable.

No additional id components are defined. Dependencies still OPEN elsewhere: the canonical instrument and timeframe
identifier set (instrument master, B-7) and the G-2 `<side>` token inside `<sweep_group_id>` (Section 11, B-17).

*[Noted 23 Nov 2026 (17.P IR-2): ~~the set of `<pattern_type>` token values is not enumerated, in particular whether
the token carries the family, the contextual label (Hammer / Hanging Man / `UNCLASSIFIED_SHAPE`) or the directional
variant (Bullish / Bearish Engulfing). Recorded as OQ-14 (OPEN, 17.N); no format is invented here.~~ Resolved 23 Nov
2026 (OQ-14, 17.Q; OWNER APPROVED — DELEGATED MVP DECISION — DOCUMENTED, NOT IMPLEMENTED).]*

`<pattern_type>` = the canonical geometric family token (one per 16.A family; 17.Q OQ-14):

| Canonical family (16.A) | `<pattern_type>` |
|---|---|
| Classic Doji | `CLASSIC_DOJI` |
| Gravestone Doji | `GRAVESTONE_DOJI` |
| Long-legged Doji | `LONG_LEGGED_DOJI` |
| Inverted Hammer | `INVERTED_HAMMER` |
| Dragonfly Doji | `DRAGONFLY_DOJI` |
| Hammer / Hanging Man | `HAMMER_HANGING_MAN` |
| Engulfing | `ENGULFING` |
| Shooting Star | `SHOOTING_STAR` |
| Morning Star | `MORNING_STAR` |
| Evening Star | `EVENING_STAR` |

The contextual label (Hammer / Hanging Man / `UNCLASSIFIED_SHAPE`) and the direction (Bullish / Bearish Engulfing)
are separate event attributes and never part of the id. The id structure above is unchanged.

#### CK-3 — Trend terminology mapping

| Trend context | Direction terminology |
|---|---|
| UPTREND | BULLISH |
| DOWNTREND | BEARISH |
| SIDEWAYS | NEUTRAL |
| UNKNOWN | UNKNOWN |

These terms represent the same context and must not use separate calculations.

#### CK-4 — SIDEWAYS contextual labels

For Hammer, Hanging Man, Inverted Hammer and Shooting Star:
- Geometric shape detection still occurs.
- The contextual directional label becomes `UNCLASSIFIED_SHAPE`.
- No bullish / bearish contextual label is assigned.
- The original pattern bias is preserved.
- Without the required trend context, the pattern cannot qualify a directional setup.

#### CK-5 — Non-Doji pattern directional bias

| Pattern | Approved bias |
|---|---|
| Inverted Hammer | BULLISH_BIAS |
| Hammer | BULLISH_BIAS |
| Morning Star | BULLISH_BIAS |
| Dragonfly Doji | BULLISH_BIAS |
| Shooting Star | BEARISH_BIAS |
| Hanging Man | BEARISH_BIAS |
| Evening Star | BEARISH_BIAS |
| Gravestone Doji | BEARISH_BIAS |
| Classic Doji | NEUTRAL |
| Long-legged Doji | NEUTRAL |

- Pattern bias and preceding trend are separate properties.
- Inverted Hammer: bullish bias, preceding DOWNTREND required.
- Hammer: bullish bias, preceding DOWNTREND required.
- Shooting Star: bearish bias, preceding UPTREND required.
- Hanging Man: bearish bias, preceding UPTREND required.
- Bias is not a BUY / SELL signal.
- Confirmation remains mandatory.

(The four Doji rows repeat CS-3 unchanged. Bullish / Bearish Engulfing direction is given by its own rule, 16.D.7.)

#### CK-6 — Sweep-to-pattern window and multi-candle patterns

- The first candle of the pattern must occur after the sweep candle.
- The sweep candle itself cannot be part of a multi-candle pattern.
- The complete pattern must finish within the five-candle window after the sweep.
- Counting begins with the first completed candle after the sweep.

Example:
- Candle 100: SSL sweep.
- Candles 101–102: Bullish Engulfing may qualify.
- Candles 103–105: Morning Star may qualify if it completes by candle 105.
- A pattern completing at candle 106 is outside the window and is ineligible.

#### CK-7 — Multiple patterns in the sweep window

- Retain all valid pattern labels under CS-2.
- Each pattern has its own `pattern_id` and event.
- An SSL sweep qualifies only bullish-bias patterns.
- A BSL sweep qualifies only bearish-bias patterns.
- The first valid qualifying pattern advances the setup to the Confirmation stage.
- One sweep can generate at most one trade setup.
- Later valid patterns may be recorded, but must not generate duplicate setups from the same sweep.

This does not suppress pattern labels.

#### CK-8 — Floating-point tolerance scope

The configurable floating-point tolerance applies to:
1. Common OHLC threshold comparisons.
2. Engulfing body-boundary comparisons.
3. Confirmation close versus pattern high / low comparisons.

- Original OHLC values must remain unchanged.
- Do not invent a numeric default beyond the CK-1 formula.
- The tolerance must not artificially create a wick or alter original market prices.

#### CK-9 — Global zero-based candle indexing

- V6 candle indexing is globally zero-based.
- The liquidity event group id `sweep:<side>:<k>` uses a zero-based candle index for `k`.
- Do not change existing pool ID or event ID formats without separate approval.
- Preserve the existing G-2 group ID structure.

This is a conversation-level decision. The liquidity decision register
(`research/v6/audits/LIQUIDITY_SWEEP_DECISIONS/`) is **not** modified by it and still lists the base of `k` as
unspecified; this is source-vs-register traceability, not a conflict in the decision. The `<side>` token of G-2
remains OPEN (Section 11, B-17).

#### CK-10 — Setup lifecycle statuses

| Stage | Status |
|---|---|
| CHoCH detected | CHOCH_DETECTED |
| BOS confirmed | BOS_CONFIRMED |
| Liquidity sweep | SWEEP_DETECTED |
| Pattern detected | PATTERN_DETECTED |
| Confirmation received | CONFIRMED |
| Paper entry executed | ENTERED |
| Stop-loss hit | STOPPED_OUT |
| Target hit | TARGET_HIT |
| Window expired | EXPIRED |
| Setup invalidated | INVALIDATED |
| Risk check rejected | NO_TRADE |

- Every transition records a timestamp and candle index.
- The candle index is zero-based.
- A terminal status cannot reactivate the same setup.
- Keep setup lifecycle status separate from individual pattern-event status (CS-10). The word `CONFIRMED` occurs in
  both sets; each set is read in its own layer.
- Do not imply these states are already implemented: they are **not implemented**.

### 16.M Decisions CK-11…CK-13 — OWNER APPROVED — DOCUMENTED, NOT IMPLEMENTED

| Decision | Status |
|---|---|
| CK-11 | **OWNER APPROVED — DOCUMENTED, NOT IMPLEMENTED** |
| CK-12 | **OWNER APPROVED — DOCUMENTED, NOT IMPLEMENTED** |
| CK-13 | **OWNER APPROVED — DOCUMENTED, NOT IMPLEMENTED** |

These are conversation-level owner approvals of 23 November 2026, transcribed into this specification. They are NOT
TESTED. Documentation approval does **not** authorize code implementation. No profitability or trading-edge claim is
implied. PAPER ONLY. CS-1…CS-10 (16.J) and CK-1…CK-10 (16.L) are unchanged.

#### CK-11 — Multiple qualifying patterns in one sweep window

- If the first qualifying candlestick pattern expires or becomes invalidated, the next qualifying pattern within the
  same original sweep window may be considered.
- Each subsequent qualifying pattern receives its own independent confirmation window of up to 3 subsequent
  completed candles.
- The original sweep-to-pattern eligibility window remains fixed at 5 completed candles after the sweep. It must
  never be extended.
- A later pattern must itself qualify within that original 5-candle sweep window.
- The first pattern that successfully confirms advances the setup.
- One sweep can generate at most one trade setup.
- Once the setup reaches `CONFIRMED`, no other pattern from that sweep can create another setup.

**Overlap clarification — OWNER APPROVED — DOCUMENTED, NOT IMPLEMENTED** (conversation-level, 23 Nov 2026):

- Multiple qualifying patterns within the same original 5-candle sweep-to-pattern window may be tracked concurrently.
- A later qualifying pattern does not have to wait for an earlier pattern's confirmation window to expire.
- Each qualifying pattern has its own independent confirmation window of up to 3 subsequent completed candles.
- The original sweep-to-pattern eligibility window remains fixed at 5 completed candles after the sweep. It never
  extends.
- Every pattern must itself qualify within that original 5-candle window.
- The first pattern that successfully confirms advances the setup.
- If one pattern expires or becomes invalidated, other eligible patterns continue to be tracked within their own
  confirmation windows.
- Once a setup reaches `CONFIRMED`, no other pattern from that sweep may create a duplicate setup.
- One sweep can create at most one trade setup.

**Two different windows** (they must not be confused):

| Window | Rule |
|---|---|
| Sweep-to-pattern eligibility | Fixed 5 completed candles after sweep; never extended |
| Pattern confirmation | Each qualifying pattern independently receives up to 3 subsequent completed candles |

A later pattern's own 3-candle confirmation window does not lengthen the 5-candle sweep window; only the pattern's
qualification must fall inside the sweep window. No pattern-priority rule beyond "the first pattern that successfully
confirms" is defined, and no further expiry or invalidation rule is added here.

#### CK-12 — Pattern invalidation tolerance

```
Bullish pattern invalidation:  close < pattern_low  - OHLC_COMPARISON_EPSILON
Bearish pattern invalidation:  close > pattern_high + OHLC_COMPARISON_EPSILON
```

- `OHLC_COMPARISON_EPSILON` is the already-approved instrument-specific tolerance from CK-1 (definition unchanged).
- Original OHLC values must never be modified.
- Equality within the tolerance does not trigger invalidation.

This makes the invalidation rule of 16.G epsilon-aware; `pattern_low` / `pattern_high` are as defined in 16.F
(CS-8 for Engulfing).

#### CK-13 — NO_TRADE reason codes

| Condition | Reason code |
|---|---|
| Entry gap exceeds configured maximum | `ENTRY_GAP_EXCEEDED` |
| Entry open is at or beyond stop-loss | `ENTRY_AT_OR_BEYOND_SL` |
| Net reward-to-risk is below 1:1 | `NET_RR_BELOW_MINIMUM` |
| Minimum permitted quantity exceeds the risk budget | `MIN_QTY_EXCEEDS_RISK_BUDGET` |
| Required execution configuration is missing | `EXECUTION_CONFIG_INCOMPLETE` |
| Available margin is insufficient | `INSUFFICIENT_MARGIN` |

- `NO_TRADE` is a terminal setup status.
- A rejection record must include `reason_code`, timestamp and zero-based candle index.
- Exactly one final rejection reason is recorded per setup.
- If multiple conditions fail, select the first applicable reason using the approved deterministic priority order
  below.

Approved priority order (the first applicable condition wins):

1. `EXECUTION_CONFIG_INCOMPLETE`
2. `ENTRY_AT_OR_BEYOND_SL`
3. `ENTRY_GAP_EXCEEDED`
4. `NET_RR_BELOW_MINIMUM`
5. `MIN_QTY_EXCEEDS_RISK_BUDGET`
6. `INSUFFICIENT_MARGIN`

**Not reconciled in this update (awaiting owner confirmation):** Sections 7, 8 and 12 still list the minimum-quantity
behaviour (B-14), margin insufficiency (B-15) and missing execution configuration (B-20) as OPEN or PROPOSED. CK-13
defines reason codes for these conditions; whether it also approves NO_TRADE as the behaviour in each case (for
example rejecting rather than reducing quantity on insufficient margin) has not been written into those sections,
because this update was authorized for the CK-11…CK-13 sections only.

Cross-reference: the margin-shortfall policy (B-15) is now recorded as CK-14 (Section 16.N). The CK-13 reason codes
and priority order above are unchanged. Sections 7 and 12 are still not updated.
*[Update 23 Nov 2026: Sections 7, 8 and 12 now carry dated cross-references for B-14, B-15 and B-20 (Section 17).]*
*[Update 23 Nov 2026 (OQ-2, 17.O): operational skips and expiries use a separate `disposition_reason` field. The six
CK-13 `reason_code` values and their priority order are unchanged and reserved for CK-13 rejections.]*

### 16.N Decision CK-14 — OWNER APPROVED — DOCUMENTED, NOT IMPLEMENTED

Conversation-level owner decision of 23 November 2026, transcribed into this specification. **NOT IMPLEMENTED**, NOT
TESTED and not validated by this documentation change. Documentation approval does not authorize code
implementation. PAPER ONLY.

#### CK-14 — Margin shortfall handling

Owner decision: **APPROVED — DOCUMENTED, NOT IMPLEMENTED.**

1. Calculate initial position quantity using the approved risk-budget sizing rules.
2. If required margin exceeds available margin, reduce quantity and recalculate.
3. Revalidate all constraints after reducing quantity:
   - Risk must remain within the approved risk budget.
   - Minimum permitted quantity must be satisfied.
   - Required margin must fit available margin.
   - Net reward-to-risk must meet the approved minimum of 1:1.
4. Do not change entry, stop-loss, target, or per-unit risk to force a position through the checks.
5. If no valid quantity satisfies all constraints, reject the setup with terminal status `NO_TRADE`.

Final rejection reason:
- If minimum permitted quantity exceeds the risk budget, use `MIN_QTY_EXCEEDS_RISK_BUDGET`.
- If minimum permitted quantity is within the risk budget but available margin remains insufficient, use
  `INSUFFICIENT_MARGIN`.

The CK-13 deterministic reason-code priority order is preserved exactly as approved; no reason code is added or
reordered.

Quantity reduction is permitted only to satisfy margin constraints. It must never bypass the risk budget, minimum
quantity, or minimum net R:R checks.

## 17. Delegated MVP decisions CK-15…CK-27 — OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT IMPLEMENTED

| Item | Status |
|---|---|
| Decisions CK-15…CK-27 | **OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT IMPLEMENTED** |
| Date | 23 November 2026 |
| Basis | The owner delegated authority to finalize the remaining technical and operational decisions for the initial V6 PAPER-ONLY MVP; the resulting decisions were given to Claude as approved decisions and are transcribed here |
| Implementation / tests | **NOT IMPLEMENTED; NOT TESTED.** Documentation does not authorize implementation |
| Scope | Initial V6 PAPER-ONLY MVP. Exclusions are MVP scope decisions, not claims that the broader concepts are invalid |

Earlier decisions (Sections 2–16, CS-1…CS-10, CK-1…CK-14, CHU04 and the liquidity register) are not silently
revised. Where a delegated decision refines or revises earlier text, the earlier section carries a dated
cross-reference and the change is listed in 17.N.

#### CK-15 — Pool creation and classification (MVP liquidity scope)

1. Every confirmed L2/R2 swing creates a liquidity pool.
2. BSL = swing high.
3. SSL = swing low.
4. Pool price = exact wick extreme.
5. Pool becomes eligible after its swing confirmation.
6. Initial V6 MVP does not distinguish major/minor pools.
7. Initial V6 MVP does not separately classify internal/external liquidity.
8. Equal-high/equal-low pools remain excluded from the initial MVP until separately specified.
9. Pools do not expire merely due to elapsed time.
10. Pool lifecycle remains ACTIVE → SWEPT → TAKEN.
11. One initial SWEEP per pool; subsequent qualifying sweeps emit REPEAT_SWEEP diagnostics.
12. No automatic liquidity flip after TAKEN.
13. GRAB/RUN taxonomy is excluded from initial MVP.
14. No additional reclaim condition is required beyond the approved LQ-08 sweep definition.
15. Displacement is not required for initial setup qualification.
16. Inducement, trendlines, ranges and channel liquidity are excluded from initial MVP.

Register reconciliation (Section 11 and the liquidity register): items 1–5 and 10–12 restate LQ-01, LQ-04, G-1 /
LP-01, LQ-06, LQ-15 and LQ-16 (already approved). Items 6, 7, 16 match the B0 proposals of LQ-02, LQ-05, LQ-18 and
LQ-19. Items 9, 14, 15 cover part of LQ-07, LQ-12 and LQ-13. Items 8 and 13 are MVP exclusions; LQ-03 and the GRAB /
RUN part of LQ-10 stay OPEN as broader questions.

#### CK-16 — BUY and SELL pool selection

BUY:
- Requires an SSL sweep.
- TP is the nearest eligible ACTIVE BSL above actual entry.

SELL:
- Requires a BSL sweep.
- TP is the nearest eligible ACTIVE SSL below actual entry.

Additional rules:
- SWEPT and TAKEN pools are not eligible TP targets.
- If multiple eligible pools exist at the same price, select the earliest confirmed pool.
- If still tied, use stable pool ID ordering as the deterministic tie-break.
- If no eligible opposing pool exists, reject with `NO_TRADE`.
- Do not use future-confirmed pools.
- Target selection must use information available at the entry decision time.

The exact stable pool-ID format remains an existing unresolved implementation detail (G-6; Section 11, B-17). No new
format is defined here.
*[Superseded 23 Nov 2026 by the OQ-4 resolution (17.O): pool id `pool:<swing_id>`. No eligible opposing pool: `NO_TRADE`
with `disposition_reason` `NO_ELIGIBLE_OPPOSING_POOL` (OQ-2).]*

#### CK-17 — Strict setup sequence

The selected V6 trading sequence is: CHoCH → BOS → Liquidity Sweep → Candlestick Formation → Confirmation → Entry.

1. CHoCH enters TRANSITION.
2. The next subsequent BOS in the same direction confirms reversal.
3. The qualifying sweep must occur strictly after the BOS confirmation candle.
4. A same-candle BOS and opposite-side sweep may still be independently recorded under LS-S11.
5. Such a same-candle sweep cannot qualify for this trading setup.
6. Pattern detection begins after the sweep candle.
7. Existing five-candle sweep-to-pattern window and CK-11 concurrent pattern confirmation rules remain unchanged.

Rules 1–2 restate the approved D1; the CHoCH and BOS detection rules are unchanged. **Update 23 Nov 2026:** SR-3 adds the reference-age condition to rule 2, and SR-4 gives the structure-layer BOS role that makes rule 2 deterministic: only a `REVERSAL_CONFIRMING` BOS may start a setup (17.R).

#### CK-18 — Setup invalidation and expiry

- An opposite-direction confirmed CHoCH or BOS before paper entry invalidates the pending setup.
- If no qualifying pattern forms within the original five-candle sweep window, setup becomes EXPIRED.
- If all eligible patterns expire without confirmation, setup becomes EXPIRED.
- If all eligible patterns are invalidated, setup becomes INVALIDATED.
- One sweep group can create at most one setup and one trade.
- A terminal setup cannot reactivate.

#### CK-19 — Entry rules and maximum adverse entry gap

- Entry method: `NEXT_OPEN`.
- Enter at the next valid candle's open after the confirmation candle closes.
- Never enter at confirmation candle close.
- Do not chase a missed entry.
- Missing, incomplete or out-of-session next candle means no delayed entry.
- Entry calculations must use actual entry open, not planned entry price.

Maximum adverse entry gap:

```
BUY:   adverse_gap = entry_open - confirmation_close
SELL:  adverse_gap = confirmation_close - entry_open

maximum allowed adverse gap = 0.25 × planned_risk_distance
planned_risk_distance       = abs(confirmation_close - structural_SL)
```

- If adverse gap exceeds this limit, use `ENTRY_GAP_EXCEEDED`.
- If entry opens at or beyond SL, use `ENTRY_AT_OR_BEYOND_SL` according to CK-13 priority.
- Recalculate actual risk and net R:R using actual entry price.
- The 25% value is the initial configurable MVP limit. It is not a universal market rule.

Relation to Section 4: Section 4 records an earlier owner approval "Maximum entry gap: configurable ticks per
instrument". CK-19 defines the limit as a ratio of the planned risk distance instead. This is a **revision**, listed
in 17.N (OQ-1) for owner confirmation.
*[Clarified 23 Nov 2026 (OQ-1 resolved, 17.O): a combined constraint, not a replacement: `max_adverse_gap = min(configured_max_gap_ticks * tick_size, 0.25 * planned_risk_distance)`;
the stricter limit wins; missing configured maximum ticks or tick size → `EXECUTION_CONFIG_INCOMPLETE`.]*

#### CK-20 — Structural stop-loss

BUY:
- SL is below the SSL sweep candle low.

SELL:
- SL is above the BSL sweep candle high.

Additional rules:
- Add a configurable instrument-specific SL buffer in ticks beyond the sweep extreme.
- Do not use a swing that becomes confirmed only in the future.
- Do not move SL after entry.
- Do not modify SL to force R:R or sizing checks to pass.
- If mandatory buffer configuration is missing, use `EXECUTION_CONFIG_INCOMPLETE`.

No numeric buffer is defined without instrument-specific configuration.

#### CK-21 — Take-profit and reward-to-risk

- TP = nearest eligible opposing ACTIVE liquidity pool.
- Place target one tick before the pool, on the entry side.
- The one-tick offset is configurable.
- Minimum net R:R = 1:1 after estimated fees and slippage.
- If net R:R is below 1:1, reject with `NET_RR_BELOW_MINIMUM`.
- Never select a farther target merely to force minimum R:R.
- No trailing stop.
- No breakeven adjustment.
- No partial profit.
- SL and TP remain fixed after entry.

Relation to Section 6: the TP **price** becomes the pool price offset by one tick toward the entry (BUY: pool − 1
tick; SELL: pool + 1 tick). The approved fill rules of Section 6 (touch triggers; fill at the exact TP price; gaps
fill at TP) apply to that TP price.

#### CK-22 — Paper execution rules

| Situation | Behaviour |
|---|---|
| SL and TP touched in same candle | SL_FIRST |
| Entry candle touches both | SL_FIRST |
| Open gaps beyond SL | Fill at worse opening price plus configured slippage |
| Open gaps beyond TP | Fill at TP; no favourable improvement |
| Entry at or beyond SL | Reject before entry |
| Entry at or beyond TP | Recalculate validity and net R:R; reject if invalid |
| Partial fills | Not simulated in initial MVP |
| Ambiguous intrabar ordering | Adverse outcome first |

Fees and slippage:
- Fees must come from explicit instrument/broker configuration.
- Slippage must be explicitly configured.
- Zero slippage must not be silently assumed.
- Missing mandatory fee/slippage configuration means `EXECUTION_CONFIG_INCOMPLETE`.
- Do not invent fee rates, rounding rules or broker specifications.

`SL_FIRST` is the same rule as `STOP_FIRST` in Section 9.

#### CK-23 — Risk and account protection

- Risk per trade: 1% of paper account equity.
- Round quantity down to the permitted lot/quantity step.
- Include fees and estimated slippage in risk validation.
- Margin shortfall follows CK-14.
- Do not increase risk to recover losses.
- No martingale.
- No averaging down.
- No automatic re-entry after a stopped-out setup.

Initial MVP operating limits:
- Maximum one open position across the initial paper account.
- Maximum daily loss: 2% of start-of-day paper equity.
- Once daily loss limit is reached, reject new setups.
- Existing positions continue to follow their fixed SL/TP.
- Do not force-close existing positions solely because the daily entry limit was reached.

The one-position and 2% daily loss limits are initial configurable operating limits, not profitability claims.
*[Clarified 23 Nov 2026 (17.O): equity basis and daily-loss measurement (OQ-6); dispositions when the position limit or
daily loss limit blocks a setup (OQ-2); several sweep groups after one BOS (OQ-5).]*

#### CK-24 — Market data and session rules

- Only completed candles may generate structure, liquidity, patterns and confirmation.
- No look-ahead.
- Zero-based candle indexing.
- Reject duplicate, out-of-order or invalid OHLC candles.
- Do not fabricate candles or fills for missing intervals.
- Stale/disconnected market data suspends new entries.
- On reconnection, process available completed candles chronologically.
- Existing positions must be marked as data-interrupted while valid exit data is unavailable.
- Do not claim an exit occurred during an unobserved interval.
- Session calendar and time zone must be instrument-specific.
- Do not treat the first post-session candle as a normal next-open entry without applying session rules.
- Missing mandatory session configuration means `EXECUTION_CONFIG_INCOMPLETE`.

*[Clarified 23 Nov 2026 (17.O): the data-interrupted marking is the `data_state` field (OQ-3); session rules (OQ-7).]*

#### CK-25 — End-of-data handling

At the end of a historical dataset:
- Do not force-close open trades.
- Mark them `OPEN_UNRESOLVED`.
- Exclude them from closed-trade win rate and realized P&L.
- Report last available mark separately.
- Do not count unresolved trades as wins or losses.

Lifecycle note: `OPEN_UNRESOLVED` is an additional setup lifecycle status for this end-of-data case. It extends the
CK-10 status list; CK-10 itself is not changed. It is documentation only, not implemented.

#### CK-26 — Configuration dependencies (no invented values)

The following require explicit instrument/account configuration:
- Tick size.
- Lot size and quantity step.
- Contract multiplier.
- Fee rate and fee rounding.
- Slippage.
- SL buffer.
- Session calendar and time zone.
- Paper account starting equity.
- Margin requirements.
- Instrument precision.

Missing mandatory values must result in `EXECUTION_CONFIG_INCOMPLETE`. Do not create arbitrary fallback values.

The **values and their sources** remain OPEN (Section 12: B-7…B-10, B-12, B-13).

*[Synthetic tests: a fixture may declare an explicit, test-only configuration object (17.P IR-3, 17.Q OQ-15). It is
isolated test input, never production or live configuration and never a fallback; this decision is unchanged.]*

#### CK-27 — Required initial validation coverage

1. Complete BUY and SELL lifecycle.
2. CHoCH → BOS → later sweep.
3. Same-candle BOS/sweep not qualifying for this sequence.
4. Multiple pools and deterministic target selection.
5. Sweep, repeat sweep and TAKEN transitions.
6. All ten candlestick patterns.
   *[Clarified 23 Nov 2026 (17.P IR-2): "ten" counts the canonical pattern families of 16.A, not labels or
   variants. Item unchanged.]*
7. Concurrent pattern confirmation windows.
8. Expiry and invalidation.
9. Next-open entry and adverse-gap rejection.
10. Structural SL and opposing-pool TP.
11. Quantity sizing, lot rounding, fees, slippage and margin reduction.
12. All CK-13 reason codes and priority.
13. Same-candle SL/TP and gap-through handling.
14. Daily loss and one-position limits.
15. Missing, stale and out-of-order data.
16. End-of-data open positions.
17. Mirrored BUY/SELL fixtures.
18. No-look-ahead and deterministic repeated runs.

Separate scorecards: Structure; Liquidity; Candlestick; Confirmation; Entry; Risk; Execution; End-to-end lifecycle.
They are not combined into one pass percentage. A structure PASS is not a complete trading-system PASS. Correctness
does not prove profitability. All items above are **NOT TESTED**.

### 17.N Reconciliation notes and remaining OPEN questions (not resolved here)

| ID | Item | Status |
|---|---|---|
| OQ-1 | **Entry-gap basis revision.** Section 4 (owner approved) says "Maximum entry gap: configurable ticks per instrument"; CK-19 (delegated) sets the maximum adverse gap to 0.25 × planned_risk_distance. Recorded as a revision; owner confirmation is requested whether the ratio replaces the tick-based limit or both apply. | **RESOLVED** (23 Nov 2026, 17.O) |
| OQ-2 | **Rejection reasons outside the CK-13 set.** CK-16 (no eligible opposing pool → `NO_TRADE`), CK-23 (one-position limit; daily loss limit reached), CK-24 (stale / disconnected data suspends entries) and CK-19 (missing or out-of-session next candle: no delayed entry) reject or skip setups, but CK-13's six reason codes do not name these cases and CK-13 forbids adding codes. The reason code and the lifecycle status (`NO_TRADE` or `EXPIRED`) for these cases are not defined. | **RESOLVED** (23 Nov 2026, 17.O) |
| OQ-3 | **Data-interrupted marker.** CK-24 requires open positions to be "marked as data-interrupted"; the exact status token and its relation to the CK-10 lifecycle are not defined. | **RESOLVED** (23 Nov 2026, 17.O) |
| OQ-4 | **Pool-ID tie-break.** CK-16's final tie-break uses stable pool ID ordering, which depends on the unresolved pool-ID format (G-6). | **RESOLVED** (23 Nov 2026, 17.O) |
| OQ-5 | **Several sweep groups after one BOS.** CK-18 limits each sweep group to one setup and one trade; whether a later sweep group may start a new setup while an earlier setup from the same BOS is pending (and how this interacts with the one-position limit) is not defined. | **RESOLVED** (23 Nov 2026, 17.O) |
| OQ-6 | **Paper equity basis.** CK-23 uses "paper account equity" for the 1% risk and "start-of-day paper equity" for the daily loss; the basis (realized cash vs mark-to-market, B-16), what counts toward the 2% (realized only or including open positions) and the start of the day per instrument time zone are not defined. | **RESOLVED** (23 Nov 2026, 17.O) |
| OQ-7 | **Session rules.** CK-24 requires session rules before a first post-session candle can be a next-open entry; the rules themselves (B-19, O7) are not defined. | **RESOLVED** (23 Nov 2026, 17.O) |
| OQ-8 | **TP offset and earlier wording.** CK-21 places the TP one tick before the pool; Section 6 rows say "nearest eligible ACTIVE BSL / SSL pool" and "exact TP price". Read together: the TP price is the offset price, filled exactly. Recorded as a refinement, not a conflict. | Recorded |
| OQ-9 | **LQ-03 not approved.** CK-15 item 8 excludes equal-high / equal-low pools from the MVP, but LQ-03's B0 proposal is a separate EQ pool type. The register keeps LQ-03 OPEN with an MVP-scope note instead of approving it. | Recorded |
| OQ-10 | **Disposition vs CK-13 reason on one setup.** CK-13 orders only its six `reason_code` values, and OQ-2 keeps operational `disposition_reason` values outside that order. Which one is recorded when both apply to the same setup (for example a position limit and missing execution configuration), and whether CK-13's "a rejection record must include `reason_code`" applies only to CK-13 rejections, are not stated. | OPEN |
| OQ-11 | **Account-level trading day.** OQ-6 snapshots start-of-day equity at the configured instrument trading-session start; for one paper account with instruments on different calendars (for example an exchange session and a 24/7 instrument), which session defines the account's day is not stated. | OPEN |
| OQ-12 | **G-2 group-membership scope.** The group id format is RESOLVED (OQ-4), and same-candle same-side sweeps share a group (LQ-14). Whether `TAKEN` events and `REPEAT_SWEEP` diagnostics belong to a sweep group is not settled by any approved decision. | OPEN |
| OQ-13 | **Estimated exit-cost convention in mark-to-market equity.** Costs already in cash or fill prices are not deducted twice (17.O, OQ-6). How the estimated closing costs of an open position are computed (mark price, exit fee schedule, slippage figure at the mark) was not approved. | OPEN |
| OQ-14 | **`<pattern_type>` token values (CK-2).** CK-2 defines `pattern:<instrument>:<timeframe>:<start_candle>:<pattern_type>` but not the token set: whether `<pattern_type>` names the canonical family (16.A), the contextual label (Hammer / Hanging Man, or the shape when CK-4 gives `UNCLASSIFIED_SHAPE`) or the directional variant (Bullish / Bearish Engulfing). Raised 23 Nov 2026 (17.P IR-2). | **RESOLVED** (23 Nov 2026, 17.Q) |
| OQ-15 | **Other fixture-declared execution values.** 17.P IR-3 lets a synthetic fixture declare a test-only tick size. Whether a fixture may also declare the other CK-26 values (lot size, fees, slippage, SL buffer, session calendar, starting equity, margin, precision) for synthetic end-to-end tests is not decided. Raised 23 Nov 2026. | **RESOLVED** (23 Nov 2026, 17.Q) |

### 17.O Resolutions of OQ-1…OQ-7 — OWNER APPROVED — DELEGATED DECISION — DOCUMENTED, NOT IMPLEMENTED

Follow-up to the delegated MVP decisions of Section 17 (23 November 2026), on the same basis and with the same label.
**NOT IMPLEMENTED; NOT TESTED.** Documentation does not authorize implementation. PAPER ONLY. Earlier wording that
these resolutions supersede is kept in place and marked with a dated note.

#### OQ-1 — Entry gap: both limits apply (RESOLVED)

Both constraints apply. The stricter limit wins:

```
max_adverse_gap = min(configured_max_gap_ticks * tick_size, 0.25 * planned_risk_distance)
```

- Gap is adverse-only and measured from confirmation close.
- BUY and SELL formulas remain as already recorded in CK-19.
- Missing configured maximum ticks or tick size means `EXECUTION_CONFIG_INCOMPLETE`.
- This is a combined constraint, not replacement of the earlier tick-based approval.

#### OQ-2 — Operational disposition reasons (RESOLVED)

The six CK-13 `reason_code` values and their priority order are preserved exactly. Operational skips and expiries use
a separate `disposition_reason` field:

| Situation | Lifecycle status | disposition_reason |
|---|---|---|
| No eligible opposing TP pool | `NO_TRADE` | `NO_ELIGIBLE_OPPOSING_POOL` |
| One position already open | `NO_TRADE` | `POSITION_LIMIT_REACHED` |
| Daily loss limit reached | `NO_TRADE` | `DAILY_LOSS_LIMIT_REACHED` |
| Next candle unavailable | `EXPIRED` | `NEXT_CANDLE_UNAVAILABLE` |
| Next candle outside configured session | `EXPIRED` | `SESSION_CLOSED` |

- These are operational dispositions, not CK-13 risk/configuration rejections.
- CK-13 `reason_code` remains reserved for its six approved reasons.
- Operational disposition records include timestamp and zero-based candle index.
- Do not place operational dispositions into the CK-13 priority order.
- Stale/disconnected data suspends new entries; it is not an automatic CK-13 rejection.
- If the missed next-open deadline passes, the setup expires and is not entered later.

#### OQ-3 — Data interruption (RESOLVED)

A separate `data_state` field, not a new lifecycle status:
- `NORMAL`
- `DATA_INTERRUPTED`
- `DATA_RESUMED`

Interruption and recovery timestamps are recorded.

- An open trade retains its existing lifecycle status.
- New entries are suspended while data is stale or disconnected.
- Do not fabricate candles, fills or exits.
- Do not claim that SL or TP executed during an unobserved interval.
- If a pending setup misses its required next-open entry deadline, it becomes `EXPIRED` with `NEXT_CANDLE_UNAVAILABLE`.

#### OQ-4 — Deterministic pool, event and group IDs (RESOLVED)

```
Pool ID:             pool:<swing_id>
Group ID:            sweep:<side>:<k>
Liquidity event ID:  liquidity:<pool_id>:<event_type>:<k>
```

- `<side>` is exactly `BSL` or `SSL`.
- `k` is the globally zero-based candle index.
- Deterministic event types: `SWEEP`, `REPEAT_SWEEP`, `TAKEN`.
- Event records must include pool ID, side, event type, candle index and timestamp.
- Initial sweep event names remain `BSL_SWEEP` and `SSL_SWEEP`, as approved under LQ-17.
- `TAKEN` is emitted as a distinct event and also changes the pool lifecycle state to TAKEN. Its event record includes
  the pool side and pool ID.
- Repeat sweeps remain diagnostics under the already approved LQ-15 / G-5 rules.
- Same inputs must produce identical IDs. No random UUIDs.

This fixes G-2 (`<side>` token) and G-6 (pool and liquidity event id formats) in the liquidity register. With it, the
CK-2 setup id `setup:<sweep_group_id>:<pattern_id>` is fully defined. Other identifiers are unchanged. The GRAB / RUN
part of LQ-10 (including whether TAKEN is also a named RUN event) stays OPEN.

**Group-membership scope (clarified 23 Nov 2026; G-2).** The OQ-4 decision fixes the id string; it does not by itself
define everything a group contains:
- Several pools swept on the same candle and the same side share one group id: LQ-14 ("one event per pool, shared
  group ID for same-candle events") together with the `<side>` component.
- Opposite-side sweeps on the same candle receive different group ids, because `<side>` is part of the id. This follows
  from the approved format; it is not a new rule.
- Whether `TAKEN` events and `REPEAT_SWEEP` diagnostics belong to a sweep group is not settled by any approved decision:
  **OPEN** (OQ-12).

#### OQ-5 — Multiple sweep groups after one BOS (RESOLVED)

1. The first eligible sweep group after a BOS starts the candidate setup.
2. Only one candidate setup may be pending per BOS at a time.
3. If the candidate reaches `EXPIRED`, `INVALIDATED` or `NO_TRADE` before reaching `CONFIRMED`, a later qualifying sweep
   group may start another candidate while that BOS remains current.
4. Once any candidate reaches `CONFIRMED`, that BOS cannot create another setup.
5. An opposite confirmed CHoCH or BOS ends the BOS eligibility.
6. Each sweep group remains subject to the one-setup-per-sweep rule.
7. The account-wide one-open-position limit remains independently enforced.

#### OQ-6 — Paper equity and daily loss (RESOLVED)

Current mark-to-market paper equity:

```
cash + unrealized P&L - applicable fees and slippage
```

- The 1% per-trade risk budget uses current mark-to-market equity.
- Daily loss is calculated as start-of-day equity minus current mark-to-market equity.
- Include realized and unrealized P&L and applicable transaction costs.
- Snapshot start-of-day equity at the configured instrument trading-session start.
- When daily loss reaches 2% of start-of-day equity, reject new setups for the remainder of that trading day.
- Existing positions continue following their fixed SL/TP.
- Do not force-close existing positions solely because the daily loss limit is reached.
- Missing equity or session configuration means `EXECUTION_CONFIG_INCOMPLETE`.

(Which session defines the day for an account with instruments on different calendars: OQ-11, OPEN.)

**Cost accounting (clarified 23 Nov 2026).** The approved mark-to-market policy above is unchanged.
- Fees and slippage already reflected in cash, or in an actual fill price, are counted once and must not be deducted
  again. This covers realized costs of closed trades and the realized entry costs of an open position.
- `applicable fees and slippage` in the formula is therefore limited to the estimated costs of closing the open
  position(s), which are not yet in cash.
- The exact convention for that estimate (the mark price used, the exit fee schedule applied, and which slippage figure
  applies at the mark) was not approved: **OPEN** (OQ-13), an implementation / configuration clarification.

#### OQ-7 — Session rules (RESOLVED)

1. Use the configured instrument's official exchange calendar and timezone.
2. The confirmation candle and next-open entry candle must belong to the same continuous tradable session.
3. Do not delay entry across overnight, weekend, holiday or session breaks.
4. If confirmation occurs on the final candle of a session, expire the setup. Do not enter at the next session's open.
5. 24/7 instruments must explicitly configure a continuous session calendar.
6. Missing mandatory session calendar or timezone means `EXECUTION_CONFIG_INCOMPLETE`.

Instruments do not share one assumed set of session hours. O7 (sessions and gaps in the CHoCH / structure layer) is a
separate structure item and stays OPEN.

### 17.P Implementation-readiness clarifications IR-1…IR-3 — OWNER APPROVED — DOCUMENTATION ONLY, NOT IMPLEMENTED (23 Nov 2026)

These clarify terminology, counting and test design after the read-only implementation audit of 23 Nov 2026. No rule,
threshold, bias, trend-context rule, overlap rule, confirmation rule or id format is changed. No code, test, fixture or
configuration file is changed, and nothing here authorizes implementation (Section 15).

#### IR-1 — CHU04 STRICT: approved behaviour vs stale code labels

Approved rule (OWNER APPROVED, 22 Nov 2026; Section 11 and the liquidity register):
- Bullish structure: CHoCH only when `close < protected_low`.
- Bearish structure: CHoCH only when `close > protected_high`.
- `close == protected_level` → `NO_CHOCH`.
- Equality does not consume or invalidate the protected swing.
- Consistent with the approved strict-close BOS semantics (BOS-002).

CHU04 is **not** an open question. Repository state (from the audit; unchanged by this document):

| Item | State |
|---|---|
| CHoCH behaviour (`scanner_v6/structure/choch.py`, strict comparison; equality → no CHoCH, protected swing kept) | Matches the approved rule |
| `choch.py` module docstring ("strictness of the CHoCH close is UNRESOLVED") | **Stale label**, not fixed |
| `EXACT_LEVEL_CLOSE` diagnostic text ("CHU04 unresolved") | **Stale label**, not fixed. The diagnostic itself is a neutral record, not a CHoCH |
| `tests/scanner_v6/test_defect_fixes.py::test_d2_exact_level_close_is_not_wick_only_and_chu04_stays_open` (name, and its assertion on the text "CHU04 unresolved") | **Stale label**, not fixed |

Updating these labels needs a separately authorized code and test change; the label, the diagnostic text and the test
assertion must change together. That change must not alter CHoCH behaviour.

#### IR-2 — Canonical candlestick pattern count and naming

Canonical geometric pattern families (16.A; scope unchanged):
1. Classic Doji
2. Gravestone Doji
3. Long-legged Doji
4. Inverted Hammer
5. Dragonfly Doji
6. Hammer / Hanging Man — one geometric family, two context-dependent labels
7. Engulfing — one two-candle family, bullish and bearish variants
8. Shooting Star
9. Morning Star
10. Evening Star

Contextual and directional labels:
- Hammer and Hanging Man are separate output labels for one geometric family (CS-1, CK-5).
- Bullish Engulfing and Bearish Engulfing are separate directional variants of one family (16.D.7).
- Contextual labels and directional variants are not counted as extra geometric families.
- `UNCLASSIFIED_SHAPE` (CS-1, CK-4) is a context outcome, not a pattern name, and is not counted.

Counts:
- **10** canonical pattern families.
- **11** named pattern labels if Hammer and Hanging Man are split but Engulfing remains one family.
- **12** directional / contextual labels if Bullish and Bearish Engulfing are also counted separately.

"Ten" in 16.A and CK-27 item 6 means the 10 canonical families. (The "ten mandatory candlestick test cases" in
Section 13 / 16.I are test cases, not patterns.) Every pattern rule, threshold, bias (CK-5), trend-context rule (16.E,
CS-5, CK-1, CK-3, CK-4), overlap rule (CS-2, CK-7, CK-11) and confirmation rule (16.F, CS-7, CS-8) is unchanged.

ID note: ~~the token set of `<pattern_type>` in CK-2 is not enumerated (family vs label vs variant). This is OPEN as
OQ-14 (17.N); no format is invented.~~ Resolved 23 Nov 2026 (OQ-14, 17.Q): `<pattern_type>` is the canonical family
token; labels and variants are separate attributes.

#### IR-3 — Synthetic test tick size (MVP test design)

1. A synthetic test fixture **may** declare an explicit tick size in its fixture metadata / configuration.
2. The fixture tick size is **test-only input**. It is never a production instrument configuration and never a
   fallback for missing live instrument configuration (CK-26, B-7).
3. The same fixture and configuration must produce deterministic, identical results.
4. Tests must not silently assume a universal tick size.
5. A fixture that omits tick size gets the existing spec-defined outcomes, with no fallback:
   - pattern evaluation → `UNSCORABLE` (CK-1);
   - trend context → `UNKNOWN` (CK-1);
   - any execution step that needs tick size → `EXECUTION_CONFIG_INCOMPLETE` (CK-13, CK-26, OQ-1).
6. Production and live-data evaluation still require an explicit, instrument-specific tick size; its source stays OPEN
   (B-7).
7. CK-1 is unchanged: `OHLC_COMPARISON_EPSILON = TickSize × 0.000001`.
8. The trend neutral threshold is unchanged: `TREND_NEUTRAL_THRESHOLD = 2 × TickSize`.
9. Original OHLC values are never changed.

Scope: tick size only. ~~Whether a fixture may also declare other CK-26 values is OPEN (OQ-15, 17.N).~~ Resolved 23 Nov
2026 (OQ-15, 17.Q): a fixture may declare a complete, explicit, test-only configuration object; this IR-3 tick-size
rule is unchanged and is one part of it.

Status: **DOCUMENTED, NOT IMPLEMENTED; NOT TESTED.** No candlestick test or fixture exists yet (Section 14).

### 17.Q Resolutions of OQ-14 and OQ-15 — OWNER APPROVED — DELEGATED MVP DECISION — DOCUMENTED, NOT IMPLEMENTED (23 Nov 2026)

These decisions complete CK-2 and IR-3. No pattern rule, threshold, bias, trend context, confirmation, overlap,
risk, sizing, fee, slippage, execution or session formula changes. No code, test, fixture or configuration file is
changed, and nothing here authorizes implementation (Section 15).

#### OQ-14 — Canonical `<pattern_type>` token (RESOLVED)

`<pattern_type>` in `pattern:<instrument>:<timeframe>:<start_candle>:<pattern_type>` (CK-2) is the **canonical
geometric family token**, never the contextual label or the directional variant. One token per 16.A family:

| Canonical family | Canonical token |
|---|---|
| Classic Doji | `CLASSIC_DOJI` |
| Gravestone Doji | `GRAVESTONE_DOJI` |
| Long-legged Doji | `LONG_LEGGED_DOJI` |
| Inverted Hammer | `INVERTED_HAMMER` |
| Dragonfly Doji | `DRAGONFLY_DOJI` |
| Hammer / Hanging Man | `HAMMER_HANGING_MAN` |
| Engulfing | `ENGULFING` |
| Shooting Star | `SHOOTING_STAR` |
| Morning Star | `MORNING_STAR` |
| Evening Star | `EVENING_STAR` |

Rules:
1. The canonical family token is used in the `pattern_id`.
2. Hammer and Hanging Man share `HAMMER_HANGING_MAN`; the contextual label (CS-1, CK-4) is a separate event attribute.
3. Bullish and Bearish Engulfing share `ENGULFING`; the direction (16.D.7) is a separate event attribute.
4. `UNCLASSIFIED_SHAPE` is never a pattern type and never creates a pattern id by itself. A Hammer / Hanging Man shape
   in SIDEWAYS context is still a detected shape (CK-4), so it has a `HAMMER_HANGING_MAN` id with the attribute
   `UNCLASSIFIED_SHAPE`.
5. When a candle matches several valid patterns, each canonical family gets its own pattern id, under the existing
   overlap rules (CS-2, CK-7, CK-11).
6. The exact CK-2 structure, zero-based candle indexing (CK-9), canonical instrument / timeframe identifiers and
   deterministic ids are unchanged. No random UUID, no extra id component.

Examples. `<instrument>` and `<timeframe>` stay placeholders, because the canonical identifier set is OPEN (B-7):

| Pattern seen | `pattern_id` | Separate attributes |
|---|---|---|
| Hammer, start candle 57, after a DOWNTREND | `pattern:<instrument>:<timeframe>:57:HAMMER_HANGING_MAN` | label Hammer; bias BULLISH_BIAS |
| Hanging Man, start candle 57, after an UPTREND | `pattern:<instrument>:<timeframe>:57:HAMMER_HANGING_MAN` | label Hanging Man; bias BEARISH_BIAS |
| Bullish Engulfing, candles 120–121 | `pattern:<instrument>:<timeframe>:120:ENGULFING` | direction BULLISH |
| Bearish Engulfing, candles 120–121 | `pattern:<instrument>:<timeframe>:120:ENGULFING` | direction BEARISH |

The Hammer and Hanging Man rows (and the two Engulfing rows) are alternatives for the same candles, never
simultaneous: one candle has one preceding trend (CS-1, CK-3), and an Engulfing pair is either bearish-then-bullish
or bullish-then-bearish (16.D.7). Each id is
therefore unique per family and start candle.

The 16.H example field `"pattern": "BULLISH_ENGULFING"` is the label / variant attribute of the event. It is not the id
token and is unchanged. The attribute's field names and value set are not further defined here.

#### OQ-15 — Test-only synthetic fixture configuration (RESOLVED)

For deterministic synthetic MVP tests, a fixture **may** declare a complete, explicit, **test-only configuration
object** with the values the module under test needs. It may include:
- canonical test instrument identifier and timeframe;
- tick size (IR-3);
- lot size, quantity step, minimum quantity and contract multiplier;
- price / quantity precision and rounding rule;
- fee rates, fee source metadata and fee rounding;
- entry and exit slippage assumptions;
- maximum entry gap ticks;
- stop-loss buffer;
- session calendar and time zone;
- starting paper equity;
- margin requirements;
- any other mandatory CK-26 value the specific test needs.

Rules:
1. Fixture configuration is isolated test input, not production configuration.
2. **Required:** every value the module under test needs must be declared explicitly by the fixture. **Optional:** a
   value the module under test does not use may be omitted; it is then absent, never defaulted.
3. No universal defaults, silent assumptions or hidden fallbacks.
4. A missing mandatory value gives the existing spec-defined outcome:
   - `EXECUTION_CONFIG_INCOMPLETE` for missing CK-26 / execution values (CK-13, CK-26, OQ-1, OQ-7);
   - pattern evaluation `UNSCORABLE` and trend context `UNKNOWN` for a missing tick size (CK-1, IR-3).
5. The same fixture and configuration must give deterministic, reproducible results.
6. Test-only configuration is never silently promoted into live or production configuration.
7. Production instrument configuration stays subject to CK-26 and B-7…B-13; their values and sources remain OPEN.
8. No risk, sizing, fee, slippage, execution or session formula changes.
9. OQ-13 stays OPEN. A fixture cannot supply the estimated exit-cost convention for mark-to-market equity, because no
   approved convention exists. Items that depend on it stay `UNSCORABLE` (pending rule, Section 13).
10. OQ-10, OQ-11, OQ-12 and OQ-13 are not resolved by this decision.

No naming convention for test instrument identifiers is defined here.

Status: **DOCUMENTED, NOT IMPLEMENTED; NOT TESTED.**

### 17.R Structure reconciliation decisions SR-1…SR-6 — OWNER APPROVED — DELEGATED DECISION — IMPLEMENTED (23 Nov 2026)

**Source.** The owner authorized these on 23 Nov 2026, resolving the final structure-sequence audit findings U1, U2,
U5, U6, O4 (the opposite-BOS part) and O9. They are **delegated owner-approved decisions**. They refine D1 / D2 / A5 /
D5 (PHASE1_2_DECISIONS.md) without changing BOS-001…005, Option A, SW-001…005, CHU04 STRICT, D3 or D4.

**Candle order.** All candle indices are zero-based (CK-9). "At close k" means step (3) or (4) of D5 for candle k; "in
force from k + 1" means usable by the evaluation of candle k + 1.

#### SR-1 — Sticky protected origin (resolves U1)

1. **Origin selection and timing are unchanged (D2).** A BOS's origin is the extreme confirmed swing of the needed kind
   with index in `(reference.index, k]`. It is re-evaluated at every close up to `k + R` as further swings in that range
   confirm, and activated at the close where the candidate qualifies, in force from the next candle (PHASE1_2 §4, CHD16).
2. **A5 comparison base.** A5 compares the candidate with the **immediately previous confirmed swing of the same kind**
   (highest index below the candidate's index among confirmed swings). That swing may lie inside the same BOS leg.
3. **Sticky rule.** Once an origin is activated for a BOS, it stays protected when a later candidate in the same leg
   fails A5. A later candidate that confirms after an earlier one in the same leg is always below it (bullish), so it
   always fails A5 against it; it is recorded as `NOT_QUALIFIED` and never deactivates the earlier origin.
4. Replacement by the origin of a later BOS (higher k) and consumption by a CHoCH are unchanged.

#### SR-2 — Protected fallback at establishment (resolves U2 for establishment only)

1. **When.** At the close k where the structure is established (A2–A4) in direction d, and **no qualifying P-B origin is
   active for d** (`ProtectedTracker` has none).
2. **Fallback level.** The establishing swing: for BULLISH the latest confirmed swing low (the HL of the HH + HL pair);
   for BEARISH the latest confirmed swing high (the LH of the LH + LL pair). "Latest" uses the establishment ordering
   (confirmation index, then index).
3. **Activation.** In force from k + 1, together with the new state. It is already confirmed by construction.
4. **Replacement.** The first qualifying P-B origin activated for d after establishment (by any BOS whose origin is
   activated later, including one from before the establishment) replaces the fallback **permanently**. The fallback
   never returns.
5. **Consumption.** A CHoCH against the fallback consumes it exactly like a P-B protected swing (CHU04 strict close; one
   CHoCH per protected id). Any CHoCH ends the fallback.
6. **Scope.** Establishment only. After REVERSAL_CONFIRMED (D1) or REVERSAL_INVALIDATED (SR-5) there is no fallback: the
   protected level is the origin of that BOS or of a later one, activated by D2 timing. If that origin is missing or
   NOT_QUALIFIED, no protected level is in force until a later same-direction BOS supplies one (still OPEN beyond
   establishment).

#### SR-3 — Reversal-confirming BOS must break a post-CHoCH swing (resolves U5)

1. During TRANSITION(d) entered by a CHoCH at candle c, a BOS in direction d at candle j > c confirms the reversal
   **only if its reference swing was confirmed at or after c** (`reference.confirmed_index >= c`).
2. A swing confirmed at the close of the CHoCH candle c is usable from c + 1 (D5). The earliest possible confirming
   candle is therefore c + 1.
3. A same-direction BOS whose reference was confirmed before c is still a BOS event (Option A). It does **not** confirm
   the reversal; it is recorded with role `TRANSITION_REF_BEFORE_CHOCH` and the diagnostic
   `CONFIRMATION_REF_BEFORE_CHOCH`. Its reference is used (BOS-005), so a newer swing is needed.
4. A same-candle BOS on the CHoCH candle never confirms (D1, unchanged).

#### SR-4 — BOS roles and setup eligibility (resolves U6)

Every BOS gets exactly one role at its own close, from the pre-candle state and step (3):

| Role | Condition |
|---|---|
| `REVERSAL_CONFIRMING` | confirms a TRANSITION(d) under D1 + SR-3 |
| `REVERSAL_INVALIDATING` | opposite-direction BOS that invalidates a TRANSITION (SR-5) |
| `CONTINUATION` | pre-candle state is the established structure in the BOS direction |
| `COUNTER_STRUCTURE` | pre-candle state is the established opposite structure (with or without a same-candle CHoCH) |
| `TRANSITION_REF_BEFORE_CHOCH` | same-direction BOS in TRANSITION that SR-3 rejects |
| `TRANSITION_AMBIGUOUS` | both directions break on one candle during TRANSITION (SR-5 rule 5) |
| `PRE_STRUCTURE` | pre-candle state UNKNOWN |

**Setup eligibility.** Only a `REVERSAL_CONFIRMING` BOS may start a reversal setup (CK-17: CHoCH → subsequent
same-direction reversal-confirming BOS → qualifying sweep strictly after it). A `CONTINUATION` BOS never starts a
reversal setup. The sweep, pattern and confirmation stages are not part of the structure layer (not implemented).

#### SR-5 — Opposite BOS during TRANSITION invalidates the pending reversal (resolves the opposite-BOS part of O4)

1. **Trigger.** In TRANSITION(d), entered by a CHoCH at candle c from the established structure opposite to d, a BOS in
   the **opposite** direction at candle j > c.
2. **Effect at close j (D5 step 3).** The pending reversal is invalidated. The state returns to the prior established
   direction: TRANSITION(bearish) → BULLISH, TRANSITION(bullish) → BEARISH. One `StructureStateChange` is emitted with
   cause `REVERSAL_INVALIDATED`, related = (BOS id, CHoCH id). The BOS role is `REVERSAL_INVALIDATING`.
3. **Protected level after restoration.** The protected swing consumed by the CHoCH stays consumed and is never
   restored. The protected level is the P-B origin of the invalidating BOS, or of a later BOS in the restored
   direction, activated by D2 timing (its own confirmation, in force from the next candle). There is no SR-2 fallback;
   until such an origin is active, no protected level is in force.
4. **No reference-age condition.** Any opposite BOS invalidates, whatever its reference's confirmation time.
5. **Both directions on one candle.** A qualifying confirming BOS and an opposite BOS on the same candle are
   ambiguous. No state change; both BOS get role `TRANSITION_AMBIGUOUS`; diagnostic `TRANSITION_BOS_BOTH_DIRECTIONS`.
   A same-direction BOS that SR-3 rejects does not count as confirming here, so the opposite BOS invalidates.
6. **Still OPEN (O4 remainder).** A close back across the consumed level **without** an opposite BOS changes nothing; it
   stays the `O4_UNRESOLVED` diagnostic.

#### SR-6 — Establishment rejected when the close is already beyond the candidate protected level (resolves O9)

1. **Candidate protected level** at an establishment check at close k: the active P-B origin for d if there is one,
   otherwise the SR-2 fallback.
2. **Rejection.** If the close of candle k is strictly beyond it (BULLISH: close < level; BEARISH: close > level), the
   establishment is rejected. The state stays UNKNOWN. No state change, no protected level, and no CHoCH on k or later
   from this candidate. The diagnostic `ESTABLISHMENT_REJECTED_O9` replaces the former `O9_UNRESOLVED`. A close equal to
   the level is not beyond (CHU04 STRICT) and does not reject.
3. **Re-evaluation.** Establishment is checked again only at a later close where new swings confirm (the existing
   trigger), with the same rules.

#### Implementation and tests

- **Implemented in:** `scanner_v6/structure/choch.py` (SR-2…SR-6; SR-1 needed no code change). No change to BOS, swings,
  `protected_levels.py`, the engine or Module A.
- **Tests:** `tests/scanner_v6/test_structure_reconciliation.py`.
- **Superseded fixture expectations:** documented in that test file and in `test_choch.py`.
- **Status:** IMPLEMENTED; TESTED (23 Nov 2026). Not committed.

### 17.S Module B — liquidity pools, sweeps and the sweep-candidate link — IMPLEMENTED FROM APPROVED RULES (23 Nov 2026)

**Scope.** Owner authorization of 23 Nov 2026 ("Module B — Liquidity Pool & Sweep Detection") and the owner decisions of
23 Nov 2026 below (MB-1…MB-4). This section records what was implemented from the approved rules (Section 3, Section 11
and the liquidity register, CK-15…CK-18, OQ-4, OQ-5, SR-4, MB-1…MB-4) and the items left OPEN.

**Owner decisions MB-1…MB-4 — OWNER APPROVED (23 Nov 2026):**

| ID | Decision |
|---|---|
| MB-1 | A bullish `REVERSAL_CONFIRMING` BOS → BUY setup → requires an SSL sweep. |
| MB-2 | A bearish `REVERSAL_CONFIRMING` BOS → SELL setup → requires a BSL sweep. |
| MB-3 | **BOS eligibility duration.** A `REVERSAL_CONFIRMING` BOS is eligible from its own candle j (sweeps only from j + 1, CK-17) until the first of: (a) a `CHoCHBreak` in the opposite direction, or (b) a BOS in the opposite direction, any role. A same-direction BOS (`CONTINUATION`) does **not** end the eligibility. When it ends at candle k, the pending candidate of **that** BOS (if any) becomes INVALIDATED at k (CK-18), with `closed_by` = the terminating event id. No other event ends it. |
| MB-4 | `REPEAT_SWEEP` and `TAKEN` never start a candidate while OQ-12 stays OPEN. |

**Implemented** (`scanner_v6/liquidity/liquidity_pools.py`, `sweep.py`, `setup_sweep.py`):

| Rule | Implementation |
|---|---|
| LQ-01, LQ-04, CK-15.1-5 | one pool per confirmed L2/R2 swing; BSL = high, SSL = low; price = swing price; a dual-pivot candle gives two pools |
| G-1 / LP-01 | a pool is created at its swing's confirmation close and evaluated from the next candle |
| LQ-08, LQ-09, LS-S02, G-4 | BSL: close > P → TAKEN, else high > P → sweep; SSL mirrored; close == P after a strict wick = sweep; open ignored |
| LQ-06, LQ-15, G-5, LQ-16 | ACTIVE → SWEPT (SWEEP) → REPEAT_SWEEP per later qualifying candle (one per pool per candle) → TAKEN; TAKEN is final, no flip |
| LQ-14, G-2, OQ-4 | one event per pool; SWEEP events of one side on one candle share `sweep:<side>:<k>` (record `SweepGroup`) |
| OQ-4, G-6, LQ-17 | pool `pool:<swing_id>`; event `liquidity:<pool_id>:<SWEEP\|REPEAT_SWEEP\|TAKEN>:<k>`; names BSL_SWEEP / SSL_SWEEP, REPEAT_SWEEP, TAKEN; each record carries pool id, side, event type, k and timestamp |
| LQ-21 | every event at its own detection candle (index = confirmed index = k) |
| LQ-22, LS-S09, G-7, G-11, LP-12, LS-S11 | the liquidity layer never reads or changes structure state and never emits BOS / CHoCH; pools are independent of structure; same-candle opposite-side sweep + BOS are both recorded |
| G-8 | raw float comparisons; **no tick-size epsilon** (BOS-006 / C1 OPEN); the liquidity layer needs no instrument configuration |
| LQ-07 (approved part) | no expiry by elapsed time; no other expiry (other forms OPEN) |
| CK-17, SR-4, MB-1, MB-2 | only a `REVERSAL_CONFIRMING` BOS opens eligibility; BUY (bullish) needs an SSL sweep group, SELL (bearish) a BSL group; the group must be strictly after the BOS candle (same-candle: diagnostic `SWEEP_ON_BOS_CANDLE`); a continuation BOS never starts a candidate |
| OQ-5 r1-r6, CK-18, MB-3 | first eligible group starts the candidate; one pending candidate **per BOS** (`CANDIDATE_ALREADY_PENDING`); after EXPIRED / INVALIDATED / NO_TRADE a later group may start another; after CONFIRMED none for that BOS (`BOS_ALREADY_CONFIRMED`); an opposite CHoCH or opposite BOS ends that BOS's eligibility and invalidates only its pending candidate (`BOS_ELIGIBILITY_ENDED`, status INVALIDATED); a continuation BOS keeps it; one candidate per group |
| MB-4, OQ-12 | sweep groups contain SWEEP events only; REPEAT_SWEEP and TAKEN never start a candidate |

**Implementation choices (not trading rules):**
- Within a candle, pools are evaluated in creation order (swing confirmation index, then swing index, then high before
  low). Group records follow their SWEEP events; new pools come last.
- In the candidate link, structure events at close k are applied before the sweep groups of k. An opposite CHoCH or BOS
  on the same candle therefore ends the eligibility first (conservative).
- MB-3 terminator on a tie: when an opposite BOS and an opposite CHoCH occur at the same close, the terminating event
  (`closed_by`, `ended_by`) is taken in the canonical D5 order (PHASE1_2_DECISIONS D5: (1) BOS evaluation, (2) CHoCH
  evaluation, (3) state update): the opposite BOS first (BOS-stream emission order), then the opposite CHoCH. This only
  orders events MB-3 already names; it does not change which events end eligibility.
- A candidate is keyed by (BOS id, group id). No setup id is created: CK-2's `setup:<sweep_group_id>:<pattern_id>` needs
  a pattern id (Module C).
- All candidate bookkeeping is per BOS and per candidate key; nothing is selected globally. EXPIRED, NO_TRADE and
  CONFIRMED are set only by later modules, through `SetupSweepStream.close_candidate(key, status, k, reason)`. It changes
  exactly that candidate, only at the candle just processed; CONFIRMED marks exactly that candidate's BOS.
- At most one BOS is eligible at a time. A new reversal confirmation needs a CHoCH first, which is an opposite event for
  the previous BOS. The code asserts this.

**Still OPEN (not implemented; no behaviour invented):**
- OQ-12: whether TAKEN / REPEAT_SWEEP belong to a sweep group. They carry no group id and, by MB-4, never start a
  candidate while OQ-12 is OPEN.
- LQ-03: equal-high / equal-low pools. Two separate strict swings at one price are two pools under LQ-01, consistent with
  the register's LQ-03 text.
- LQ-10 GRAB / RUN; LQ-07 other expiry; LQ-12 R1 reclaim (`reclaim.py` stays NOT IMPLEMENTED); LQ-11; LQ-13
  annotation; G-3, G-9, G-10; BOS-006 / C1 tick epsilon.
- The sweep-to-pattern window, EXPIRED by pattern, confirmation, entry and TP selection (CK-16 uses these pools; Modules
  C+).

**Tests:** `tests/scanner_v6/test_liquidity.py`.
**Status:** IMPLEMENTED; TESTED (23 Nov 2026). MB-1…MB-4 recorded and implemented on the same day, with the setup
lifecycle made per-BOS and per-candidate. Not committed.

### 17.T Module C — candlestick formation detection — IMPLEMENTED FROM APPROVED RULES (24 Nov 2026)

Scope: detection only (16.A–16.E, 16.H with status `DETECTED`). Not implemented here: confirmation, expiry and
invalidation (16.F, 16.G; Module D), setup lifecycle (CK-10), sweep-to-pattern window (CS-9, CK-6, CK-7, CK-11),
entry, stop, target, risk, broker. No rule, threshold, bias or id format was changed.

| Rule | Implementation |
|---|---|
| 16.B geometry | `geometry()`: R, B, UW, LW and the four ratios; zero range is **R == 0 exactly** → `UNSCORABLE` / `ZERO_RANGE`, ratios `None`, no division. A positive R smaller than the epsilon is a valid, scored candle |
| 16.C / 16.D | the 10 families with the baseline thresholds in `CandlestickConfig` (configurable per instrument) |
| CS-1, CK-4 | Inverted Hammer, Shooting Star, Hammer, Hanging Man need the preceding trend; otherwise label `UNCLASSIFIED_SHAPE`, `context_qualified = False` |
| CS-2 | every valid family is emitted; no priority or suppression (Dragonfly Doji + Hammer + Classic Doji can share a candle) |
| CS-3, CK-5 | `bias` BULLISH_BIAS / BEARISH_BIAS / NEUTRAL; `direction` is the CK-3 term of the bias; neither is a trade instruction |
| CS-4 | a wick is present only when **wick > 0, compared exactly** (no epsilon: the tolerance never creates or removes a wick) |
| CS-5, CK-1, CK-3 | context from the 5 + 5 candles before the pattern's first candle (pattern candles excluded); threshold 2 × TickSize; < 10 candles or no tick size → `UNKNOWN` |
| CS-6, CS-8 | Engulfing with inclusive body boundaries, Doji neither bullish nor bearish, no trend condition; `pattern_high` / `pattern_low` = full pattern range |
| CK-1, CK-8, IR-3 | epsilon = TickSize × 0.000001 from the instrument's `MarketDataConfig`, applied to the threshold, candle-colour, Engulfing body-boundary, Star midpoint and (UQ-C3) trend-threshold comparisons; **not** to wick presence or zero range; missing tick size → every candle `UNSCORABLE` (`MISSING_TICK_SIZE`), no fallback |
| CK-2, OQ-14 | `pattern:<instrument>:<timeframe>:<start_candle>:<pattern_type>`, family token only, zero-based; duplicates raise |
| CS-10 | events carry status `DETECTED` only; `stamp.index` = start candle, `stamp.confirmed_index` = end (detection) candle |

API: `CandlestickStream(instrument, timeframe, market: MarketDataConfig, config=CandlestickConfig()).on_candle(c)` returns
the `PatternEvent`s whose last candle is `c`; `detect_candlestick_patterns(series, …)` is the same stream run in batch.
`EvaluationRecord`s list every family that could not be evaluated (`ZERO_RANGE`, `ZERO_RANGE_IN_WINDOW`,
`MISSING_TICK_SIZE`). Within one candle the events follow the 16.A family order. `<instrument>` and `<timeframe>` are
passed by the caller (canonical identifier set still OPEN, B-7); a `:` is rejected.

Delegated decisions UQ-C1…UQ-C4 — **OWNER APPROVED — DELEGATED DECISION — IMPLEMENTED (24 Nov 2026)**. They fill
gaps in 16.D / CK-4 / CK-5 / CK-8; no approved pattern definition or threshold changes.
- **UQ-C1 — Inverted Hammer / Shooting Star share one shape.** DOWNTREND → `INVERTED_HAMMER`; UPTREND → `SHOOTING_STAR`;
  SIDEWAYS / UNKNOWN → **both** upper-shape family candidates are retained, each with label `UNCLASSIFIED_SHAPE` and its
  own family bias (CK-4 "bias preserved"; OQ-14 rule 4 covered only `HAMMER_HANGING_MAN`).
- **UQ-C2 — Hammer / Hanging Man unclassified bias.** `HAMMER_HANGING_MAN` with `UNCLASSIFIED_SHAPE` has bias
  `UNDETERMINED` (the family has two approved biases).
- **UQ-C3 — trend neutral-threshold epsilon.** The CK-1 epsilon applies to the CS-5 comparison: D > threshold + eps →
  UPTREND, D < −threshold − eps → DOWNTREND, else SIDEWAYS. (Without it a decimal D exactly equal to 2 × TickSize is
  classified by floating-point noise; 34 such windows in the randomized oracle test.)
- **UQ-C4 — Engulfing bias.** Bullish Engulfing → BULLISH_BIAS, Bearish Engulfing → BEARISH_BIAS (direction from 16.D.7;
  CK-5 has no Engulfing row).

Implementation choice (not a trading rule): thresholds are compared in price units (e.g. B ≤ 0.10 × R + eps), which
equals BodyRatio ≤ 0.10 without dividing.

Correction (24 Nov 2026, owner review): the first implementation compared wick presence and zero range with the
epsilon (wick > eps, R > eps). Corrected to the exact CS-4 / 16.B conditions (wick > 0, R == 0); every other epsilon
comparison is unchanged. Consequence noted, not changed: a positive range below the epsilon is scored, and every
inclusive ratio threshold is then satisfied within the tolerance (such candles do not occur on a real tick grid).

Final review (24 Nov 2026): code unchanged; three tests added that assert the EXACT event sets (type, label, bias,
status, context, qualification), not containment: (1) sub-epsilon upper / lower wick present, exact-zero upper / lower
wick absent, exact zero range `UNSCORABLE` / `ZERO_RANGE` for every single-candle family (and `ZERO_RANGE_IN_WINDOW`
for Engulfing), positive sub-epsilon range scored; (2) normal tick-grid range and wicks in both directions; (3) CK-1 /
CK-8 epsilon still applied, inside (5e-9) vs outside (2e-8) the tolerance, to the Doji threshold, both candle colours,
the Engulfing body boundary and the Star midpoint. The exact set pins the noted consequence: a positive range of
5e-9 at tick 0.01 yields Gravestone, Long-legged and Dragonfly Doji plus the unclassified upper and lower shapes (no
Classic Doji, one wick is exactly 0). Mutation check for these tests: 10 of 10 mutants caught (epsilon on wick presence,
epsilon on zero range, zero wick counted as present, epsilon removed, epsilon removed from each candle colour /
Engulfing boundary / Star midpoint / Doji threshold, unclassified Hammer bias changed).

Tests: `tests/scanner_v6/test_candlesticks.py` (24 tests): hand-derived positive / negative / boundary fixtures for all
10 families with mirrored variants, context UPTREND / DOWNTREND / SIDEWAYS / UNKNOWN, exact-binary and decimal
threshold boundaries, pattern-candle exclusion, zero range / zero body / zero wick, missing tick size, invalid OHLC,
configurable thresholds, overlap and ids, DETECTED-only, determinism, stream / batch parity, prefix replay,
future-perturbation no-look-ahead, OHLC unchanged, adversarial sub-epsilon wick / range and exact zero wick /
range cases, and a randomized exact-rational oracle (Fractions, written from the
spec text) over 40 × 250 candles (9 765 expected patterns, every family). Mutation check: 14 of 14 mutants caught (including epsilon on wick presence and on zero range).
**Status:** IMPLEMENTED; TESTED (24 Nov 2026). Not committed.
