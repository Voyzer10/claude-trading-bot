# UNRESOLVED DECISIONS: V6 Volume 1 (swings, structure, BOS)

Each item gives the alternatives, the impact on event timing and counts, and the fixtures that tell the options apart. **No default has been chosen.** Implementation waits until each item is decided.

- IDs SW-*, MS-* and BOS-* come from the PDF's approval register (§11).
- D-* items are additional decisions found during this analysis.

---

## Swings

### SW-001: Swing algorithm
- **Alternatives:**
  - **(a) Fixed L/R window (fractal).** Confirmation at `i+R`.
  - **(b) Directional change.** Confirmation when price moves a threshold from the extreme; path-dependent.
  - **(c) Volatility-adaptive.**
- **Impact:** (b) and (c) produce different swing sequences and confirmation times. The PDF says not to mix methods, and not to add (b) unless you select it.
- **Fixtures:** all SW cases are written for (a). (b) would need a new fixture set.

### SW-002: Window sizes L, R (or the threshold)
- **Alternatives:** any L ≥ 1, R ≥ 1 (R = 0 is not causal confirmation).
- **Impact:** R sets the delay (SW12: R = 1, 2, 3 give confirmation at 4, 5, 6). Larger windows mean fewer and more external swings (SW10: 2/2 gives 3 swings; 5/5 gives 1).
- **Fixtures:** SW08, SW10, SW12, SW15, RB03.

### SW-003: Strict vs inclusive comparison
- **Alternatives:** SP-A (strict / strict), SP-B (strict / inclusive), SP-C (inclusive / strict), SP-D (inclusive / inclusive).
- **Impact:** decides what happens on ties: no swing, the first bar, the last bar, or every bar.
- **Fixtures:** SW04, SW06, SW13, SW14.

### SW-004: Equality basis and tie handling
- **Alternatives:**
  - **Basis:** exact float, tick-rounded, N-tick tolerance, or ATR fraction.
  - **Result:** one swing (first / last / mid) or a cluster.
- **Impact:**
  - A cluster confirms when its last member's right window closes.
  - A tolerance turns near-equal into equal (SW07).
  - This choice feeds Equal Highs / Lows liquidity later.
- **Fixtures:** SW04, SW05, SW07, SW13, SW14, BOS15.

### SW-005: Outside bar as both swing high and swing low
- **Alternatives:** allow both; reject both; tie-break (by close direction, or by which extreme is larger relative to the window).
- **Impact:** 0, 1 or 2 events at one index. If both are allowed, a deterministic event order is needed (D-SW-ORDER).
- **Fixtures:** SW09.

### SW-006: Internal / external hierarchy
- **Alternatives:**
  - one level
  - two windows (internal + external)
  - external = swings that produced an internal BOS
  - a directional-change overlay
- **Impact:** which levels BOS can reference. MS06 has an internal BOS at 8 and no external one.
- **Fixtures:** SW10, MS06.

### SW-007: Nested / overlapping pivots
- **Alternatives:** keep all; suppress pivots inside a larger confirmed swing; alternate highs and lows (zig-zag filter).
- **Impact:** label sequences (MS-001 alternative (c)).
- **Fixtures:** SW10, SW11.

### SW-008: Swing invalidation / replacement
- **Alternatives:**
  - **(a)** Swings are permanent; "taken" is a separate event.
  - **(b)** A status event (consumed / broken).
- An emitted swing is never edited (INV).
- **Impact:** the record a later liquidity / sweep volume will need.
- **Fixtures:** SW11 (candidate replacement, not invalidation), BOS13.

### D-SW-START: Insufficient left history
- **Alternatives:** ineligible; or a partial window at the series start.
- **Impact:** SW15 has no swing under the first, and SH0 (confirmed at 2) under the second.
- **Fixtures:** SW15.

### D-SW-GAPS: Missing bars and session breaks
- **Alternatives:** windows count bars; or a time gap breaks the window, or invalidates the candidate.
- **Impact:** NSE / US sessions have overnight gaps. RB03 has a swing under bar counting, and none or a later one under time rules.
- **Fixtures:** RB03.

### D-SW-ORDER: Ordering of simultaneous events
- **Alternatives:** by (confirmed_index, index, kind = high first / low first), or by a declared priority.
- **Impact:** deterministic output, and which swing updates structure first.
- **Fixtures:** SW09.

## Market structure

### MS-001: HH / HL / LH / LL method
- **Alternatives** for "comparable swing":
  - **(a)** the previous confirmed swing of the same kind
  - **(b)** the same, within one hierarchy level
  - **(c)** after alternation filtering
  - **(d)** versus the swing that produced the last break
- **Also decide:** equal labels (EH / EL as HH, LH or neutral); and whether the state is evaluated as of k−1 or k.
- **Impact:** labels and the trend state used to classify every break.
- **Fixtures:** MS01, MS02, MS03, MS05, MS06.

### D-MS-STATE: Trend-state definition
- **Alternatives:**
  - TS-A: latest high label + latest low label.
  - The last N labels.
  - The state flips only on an approved CHoCH.
- **Impact:** BOS vs CHoCH labels; how "UNKNOWN" is defined.
- **Fixtures:** MS05, BOS10, BOS12, BOS14.

### D-MS-PROTECTED: Protected high / low
- **Alternatives:**
  - **P-1:** the latest confirmed HL / LH.
  - **P-2:** the swing that began the leg making the last HH / LL.
  - **P-3:** the extreme since the last BOS.
- **Impact:** the bar on which a counter-structure break happens. BOS10 gives 22 under P-1 and 23 under P-2.
- **Fixtures:** BOS10.

## BOS / CHoCH

### BOS-001: Eligible reference
- **Alternatives:** RL (latest confirmed, unbroken); RH (most extreme unbroken); a protected level; internal or external.
- **Impact:** BOS12 has a break at 17 under RL and none under RH. This is the V4 audit's "52% lower-high BOS" question.
- **Fixtures:** BOS10, BOS12, MS06.

### BOS-002: Evidence
- **Alternatives:** wick; close (strict); close (inclusive); close + buffer (N ticks, points or ATR).
- **Impact:**
  - BOS03: a break only under wick.
  - BOS04: bar 21 (wick) vs 22 (close).
  - BOS05: an exact-level close counts only under inclusive.
  - BOS06: a buffer removes a 1-tick close.
- **Fixtures:** BOS03, BOS04, BOS05, BOS06.

### BOS-003: Continuation vs counter-structure
- **Alternatives:** label by the state model (BOS / CHoCH candidate / unclassified); never by direction alone (SOURCE).
- **Impact:** labels in BOS10, BOS12, BOS14 and MS05.
- **Fixtures:** those cases.

### BOS-004: Timing
- **Alternatives:** at the break close (`confirmed_index` = k); or after N confirmation bars.
- **Impact:** a later `confirmed_index`, and possible cancellation (BOS13 under N = 2 would cancel the event before it is emitted).
- **Fixtures:** all BOS, BOS13.

### BOS-005: Repeated-break de-duplication
- **Alternatives:** one per reference; one per new cross; one per close beyond; a cooldown.
- **Impact:** BOS08 gives 1, 2 or 3 events.
- **Fixtures:** BOS08, BOS11.

### BOS-006: Gap and exact level
- **Alternatives:**
  - **Gap:** counts / excluded / flagged.
  - **Comparison:** raw float vs tick-rounded, `>` vs `≥`.
- **Impact:** BOS07; BOS15 (a floating-point false negative).
- **Fixtures:** BOS05, BOS06, BOS07, BOS15.

### BOS-007: Close back through
- **Alternatives:** no effect; or a separate INVALIDATION event (the BOS remains, INV).
- **Impact:** what later setup logic sees.
- **Fixtures:** BOS13.

### D-BOS-DISPLACEMENT
- **Alternatives:** no minimum; ticks / points; ATR; a body-size filter (PDF §5, "Required").
- **Impact:** fewer, stronger breaks.
- **Fixtures:** none yet; they are designed after the decision.

### D-CHOCH
- **Question:** is CHoCH defined in V6 now, or left as `CHOCH_CANDIDATE` until a separate approved definition (PDF §10)? Does it flip the state?
- **Impact:** `structure/choch.py` stays empty until then.

## Data, fixtures and schema

### D-DATA-1: Where approved synthetic fixtures live
- **Alternatives:**
  - `research/v6/data/synthetic/`, adding a `.gitignore` exception (the folder currently ignores everything).
  - `tests/scanner_v6/fixtures/volume1/`.
- **Impact:** whether the fixtures are versioned with the code.

### D-SCHEMA: Model changes needed (no change made)

| # | Gap in the existing models (`scanner_v6/models.py` @ 7f16f09) | Needed for |
|---|---|---|
| G1 | `BOSEvent` / `StructureEvent` have no `evidence`, `profile`, `reference_index` or `reference_confirmed_index`. The last two are reachable only by looking up the swing id. | BOS output requirements |
| G2 | No structure-label event or field (HH / HL / LH / LL / EH / EL / NONE) | MS-001 |
| G3 | No structure-state / UNKNOWN representation, and no state-change event | BOS-003, D-MS-STATE |
| G4 | No equal-high / low cluster type (members, cluster price) | SW-004 cluster option |
| G5 | No tick size in `Candle`, `CandleSeries` or `V6Config`; prices are floats | BOS-006, BOS15 |
| G6 | `SwingPoint` has no profile / scope (internal vs external) | SW-006 |
| G7 | No invalidation / "taken" event type | SW-008, BOS-007 |
| G8 | The detector contract is batch-only (`series → events`); no incremental (streaming) interface | T-PAR batch vs streaming parity |
| G9 | No stable-ID scheme defined (the harness relies on ids) | T-IMM, T-DET, de-duplication |
| G10 | `CandleSeries` cannot detect missing bars (the timeframe is a label only) | D-SW-GAPS |
| G11 | `CHoCHEvent` exists, but there is no class for `CHOCH_CANDIDATE` / `UNCLASSIFIED` breaks | BOS-003, D-CHOCH |
| G12 | `no_lookahead_violations` checks only one direction (every prefix event appears unchanged in the full run). It does **not** check that every full-run event with `confirmed_index ≤ k` was already emitted at prefix k (late or missing emission). | PDF invariant (4) |
| G13 | `EventStamp` has no explicit `available_from`. It is implied as "after the close of `confirmed_index`", which is sufficient if documented. | PDF §3 table |

G12 is the most important for the no-look-ahead guarantee. A detector could pass the current harness while emitting an event later than it should. This is a test-infrastructure fix, to be approved together with the swing detector.
