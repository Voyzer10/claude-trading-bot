# FIXTURE REVIEW: Volume 1 (39 draft cases + 1 new), against the APPROVED baseline profile

Reviewed 21 Nov 2026.
- **Approved profile:** fixed window L2/R2, strict comparison, equal levels unresolved, dual pivots allowed; MS-001; BOS-001…005 (BOS not implemented).
- **No existing expectation was changed.** Proposed corrections are listed in §3 for your approval.

## 1. Checks run and results (all executed)

| Check | How | Result |
|---|---|---|
| OHLC validity | Every case loaded through `CandleSeries` | 36 load. RB01, RB02 and RB04 are rejected, as intended. |
| Event index / confirmation index (swings) | `tests/scanner_v6/test_swing_fixtures.py`: detector vs hand oracle, all 40 cases | 36 asserted cases match. RB03 runs but its oracle is not asserted (gap policy unresolved). |
| Causality per case | `replay_audit` (batch + streaming) vs the oracle, plus the old `no_lookahead_violations` | No finding in any case |
| Reference event IDs (BOS expectations) | Scratch review script: each referenced swing exists under SP-A with the stated confirmation index and price | Match in every case **except BOS15** (§3, C1) |
| Expected non-events | Covered by the oracle: any extra event is reported as `unexpected` | No unexpected events |
| Approved vs alternative profiles | Scratch review script: SP-A vs SP-B/C/D/E/F; BOS P1 vs P2/P3/P4; RL vs RH vs "latest unbroken" | Table in §2 |
| Mutation check | `test_swing_mutants.py`: 7 faulty detectors | Every one fails in its expected category |

## 2. Does each case separate the approved profile from the alternatives?

| Cases | What they separate |
|---|---|
| SW04, SW06, SW13, SW14 | Strict (approved: no swing, plus equal-level diagnostics) vs SP-B / SP-C / SP-D |
| SW01–03, SW05, SW07, SW09–12, MS*, BOS* | L2/R2 vs larger windows (SP-E / SP-F) |
| SW12, SW08 | R value (confirmation delay) |
| BOS03, BOS04 | Close (approved) vs wick |
| BOS05 | Strict close (approved) vs inclusive close and wick |
| BOS06 | Close vs close + buffer |
| BOS10, BOS12 | Reference rule RL vs RH (BOS10 also separates the "latest unbroken" reading; §3, C3) |
| SW15 | Nothing under the approved swing profile: it tests the unresolved initial-history rule |
| SW07 | Nothing under the approved profile (a clear 1-tick pivot); it only matters once a tolerance is decided |
| RB03 | Nothing until the gap policy is decided |

## 3. Findings and proposed corrections (NOT applied)

| # | Case | Finding | Proposal |
|---|---|---|---|
| C1 | BOS15 | **Factual error.** The expected break's `reference_level` is written as `0.3`, but the swing's price is `0.30000000000000004`. The rounding belongs in the *comparison*, not in the stored level. | Set `reference_level` to `0.30000000000000004` and add a note "compared after tick rounding". |
| C2 | BOS10, BOS12 | The class label `CHOCH_CANDIDATE` gives the break CHoCH meaning. Approved BOS-003 says "Do not infer CHoCH semantics." | Rename to `COUNTER_STRUCTURE_UNCLASSIFIED`: a break against a known state, with no BOS / CHoCH label. |
| C3 | BOS10 | **Ambiguity in the approved BOS-001 wording** ("most recent eligible confirmed swing"). Two readings: (a) the latest confirmed swing, used only while it is unbroken (the fixtures' RL); (b) the latest confirmed swing *that is still unbroken*, falling back to an older one. In BOS10 they differ: (b) adds a bearish break of SL10 at bar 23. | You choose (a) or (b) before BOS is implemented. |
| C4 | BOS13 | Bars 21 and 22 have an **unintended equal high** (110.9 / 110.9). Under the approved profile neither is a swing, so the break expectations are unaffected. | Keep it: it adds tie coverage. It is now listed in the addendum's `equal_level_expected`. |
| C5 | all BOS | Reference ids are informal (`SH6`), not the detector's stable ids (`swing:high:6:fixed-window-strict:L2R2`). | When BOS is implemented, map `S<H|L><i>` to the stable id. No data change. |
| C6 | MS01–MS05 | The structure expectations use the illustrative EH / EL labels and the TS-A state. Approved MS-001 covers HH / LH / HL / LL and "unknown"; equal-level treatment is still open. | Keep EH / EL as alternatives until SW-004 / MS equality is decided. |

**Redundancy (no action):**
- MS06 reuses SW10's candles, by design.
- BOS11 contains BOS01's first break.
- BOS04 extends BOS03.

## 4. Additions (new files only; the draft JSON is untouched)

`swing_oracle_addendum.json` contains:
- **SP-A swing expectations** for BOS01–BOS13 and BOS15. The draft listed breaks only for these. The values are hand-derived from the zig-zag design pivots and the appended bars.
- **Equal-level diagnostic expectations** for SW04, SW06, SW13, SW14 and BOS13.
- **SW16:** a new dual-pivot companion to SW09. The outside bar at 2 is a swing **high only**, and bar 3 is an independent swing **low**. This shows SW-005 judges each kind separately.
