# SWING CONCEPT ANALYSIS: V6 Volume 1

**Source:** *V6 SMC Scanner Training Pack, Volume 1: Swings & BOS* (8 pages), read in full.
**Branch:** `research/v6-smc-scanner` @ `7f16f09`. Analysis only; no code changed.

**About the source.** The PDF calls itself a *"Proposed research specification"* and says: *"Examples and conventions here are educational proposals, not final approved trading rules."* Every item in its approval register (§11) is **OPEN**.

**Labels used:**
- **SOURCE RULE**: the PDF states it. It is still unapproved as strategy unless it is a data or causality requirement.
- **INVARIANT**: a correctness or data-integrity requirement.
- **ILLUSTRATIVE**: an example, not a rule.
- **UNRESOLVED**: needs your decision.
- **PROPOSAL**: an implementation option.

---

## 1. Vocabulary (PDF §1)

| Term | PDF meaning | Class |
|---|---|---|
| Candle | O, H, L, C. Valid when H ≥ max(O,C), L ≤ min(O,C), H ≥ L. Timestamps strictly increasing and timezone-normalised. | SOURCE RULE + INVARIANT |
| Pivot candidate | A bar that satisfies the local-extreme comparison under the chosen algorithm. *"May not yet be confirmed."* | SOURCE RULE |
| Confirmed swing | A candidate whose required later evidence has arrived. *"Store event index and confirmation index separately."* | SOURCE RULE + INVARIANT |
| Swing High / Low | A confirmed local high / low. *"Not every wick peak/trough is a swing."* | SOURCE RULE |
| Equal Highs / Lows | Prices treated as equal *"under declared tolerance"*. Exact, tick and ATR tolerance differ. | SOURCE RULE (that it must be declared); the value is UNRESOLVED |

## 2. Concept by concept

For each concept below:
- **Meaning**
- **Price data**
- **Candle sequence**
- **Detectable when**
- **Assumptions**
- **Gaps**
- **Testable conditions**
- **Examples** (case ids from `synthetic_volume1.draft.json`)

### 2.1 Pivot candidate vs confirmed swing

- **Meaning:** a candidate is a *possible* extreme. A swing exists only once the evidence after it has closed. SOURCE RULE (§1, §2.A).
- **Price data:** highs (swing high) or lows (swing low) of the candidate and its comparison bars. Opens and closes are not used by the fixed-window method.
- **Candle sequence:** candidate bar `i`; left bars `i−L..i−1`; right bars `i+1..i+R`.
- **Detectable when:** at the **close of bar i+R** (fixed window). SOURCE RULE (§2.A: *"knowable only after bar i+R closes … event_index=i and confirmed_index=i+R"*).
- **Assumption:** a candidate is never emitted as an event, so its rejection is not repainting (case SW11). PROPOSAL, consistent with the §3 replay contract.
- **Gap:** the PDF does not say whether a rejected candidate is recorded anywhere (for audit or liquidity later). UNRESOLVED (SW-008).
- **Testable:**
  - an event is emitted only at the prefix that ends at `i+R`
  - `event_index = i`, `confirmed_index = i+R`
  - nothing is emitted for `k < i+R`
- **Examples:** SW01, SW02, SW11, SW12 (positive). SW08 and the final bar of SW01 (negative).

### 2.2 Left-side comparison window (L)

- **Meaning:** how many earlier bars the candidate must exceed.
- **Detectable when:** L does not change the confirmation time. It decides which bars are **eligible** at all: bars `0..L−1` have no full left window.
- **Gap:** what happens at the series start (insufficient left history). UNRESOLVED.
  - Option A: ineligible. Consistent with the PDF's *"insufficient history"* acceptance test (§10).
  - Option B: a partial window. Case SW15: Option A gives no swing; Option B gives SH0, confirmed at 2.
- **Testable:** a candidate at an index `< L` never becomes a swing under Option A.

### 2.3 Right-side confirmation window (R)

- **Meaning:** how many later bars must stay below a high (or above a low). R alone sets the confirmation delay.
- **Consequence:** a larger R means fewer and later swings and fewer false pivots. Example, SW12 (candidate at 3):

  | R | Confirmed at |
  |---|---|
  | 1 | 4 |
  | 2 | 5 |
  | 3 | 6 |

- **Value:** ILLUSTRATIVE only. The PDF example L=2, R=2 *"is not an approved setting"*. UNRESOLVED (SW-002).

### 2.4 Strict vs inclusive comparisons

- **PDF:** *"A strict swing high may require Hᵢ greater than every compared high in both windows."* An equal neighbour makes *"strict greater-than logic reject it as a unique pivot."* SOURCE RULE: this **describes** strict logic; it is not mandated.
- **Alternatives** (all mirrored for lows):

  | Profile | Left | Right | Effect on a tie |
  |---|---|---|---|
  | SP-A | strict | strict | rejects both bars of a tie |
  | SP-B | strict | inclusive | keeps the first bar of a tie |
  | SP-C | inclusive | strict | keeps the last bar of a tie |
  | SP-D | inclusive | inclusive | keeps every tied bar (several swings at one price) |

- **Consequences:**
  - SP-A removes every flat top or double-bar top, which are common on 5m data and on tick-rounded prices.
  - SP-B and SP-C pick one representative.
  - SP-D creates duplicate levels, which BOS de-duplication then has to handle.
- **Examples:** SW04, SW06, SW13, SW14. The expected results differ per profile and are recorded per profile in the dataset.

### 2.5 Equal Highs / Equal Lows

- **PDF:** specify the equality basis (raw price, tick-rounded, or tolerance), the tie-break rule, and whether the result is one swing or a cluster. SOURCE RULE: these must be declared.
- **Options:**
  - **Equality basis:** exact float, tick-rounded, N ticks, or a fraction of ATR.
  - **Representation:** one swing (first, last or midpoint) or a cluster with members.
- **Consequences:**
  - SW07 (one tick apart) is a *unique* pivot under exact comparison, but a *tie* under a ≥1-tick tolerance.
  - SW05 (a double top 4 bars apart) has two strict swings with equal price. That affects structure labels (EH) and later liquidity (an "equal highs" pool). Liquidity is out of scope here (§13), but the representation chosen now affects it.
- **Status:** UNRESOLVED (SW-004).

### 2.6 Tie-breaking

The tie-breaking options are the SP-B, SP-C and SP-D rows above, plus "cluster". UNRESOLVED.
- **If a cluster is chosen:**
  - **Timing:** a cluster can be **confirmed only when its last member's right window closes.** In SW04, the cluster {2,3} confirms at 5, not 4.
  - **Price:** a cluster needs its own level price (all members are equal by definition; with a tolerance, which one?).
- PROPOSAL: if a cluster is chosen, its price is the extreme member's price, and its members are listed in `related`.

### 2.7 Outside candles

- **Meaning:** one bar makes both a new high and a new low (SW09: bar 2, high 13 and low 8).
- **Options** (PDF §7, SW-005): allow both, reject both, or tie-break (for example by close direction).
- **Consequences:** if both are allowed, one index carries a swing high and a swing low, both confirmed at 4. Structure labelling then has two events at the same `confirmed_index`, and their **order** must be defined: INVARIANT, deterministic ordering is required.
- **Status:** UNRESOLVED.

### 2.8 Nested swings: internal vs external structure

- **Meaning:** small pivots inside a larger move (SW10 and MS06).

  | Window | Swings found |
  |---|---|
  | 2/2 | H5, L7, H10 |
  | 3/3 | L7 (confirmed 10), H10 (confirmed 13) |
  | 5/5 | H10 only, confirmed at 15 |

- **PDF:** internal and external pivots *"coexist"*; *"Define hierarchy and selection."* UNRESOLVED (SW-006, SW-007).
- **Options:**
  - **(a)** One window: no hierarchy.
  - **(b)** Two windows run in parallel: internal (small) and external (large).
  - **(c)** External = the swings that produced a BOS on internal structure.
  - **(d)** A directional-change threshold (PDF §2.C). *"Do not add it unless explicitly selected."*
- **Consequence:** the BOS reference (BOS-001) depends on this choice. MS06 shows an internal BOS at 8 under 2/2 and no BOS under 5/5.

### 2.9 Consecutive candidates and replacement

- **Example:** SW11. Candidate 2 is beaten inside its right window by bar 4, so bar 2 never confirms and bar 4 confirms at 6.
- This is **not** invalidation of a swing. It is a candidate failing (no event was emitted). INVARIANT.
- **Swing invalidation after confirmation** (e.g. a confirmed high later exceeded): the PDF lists it as OPEN (SW-008). Options:
  - **(a)** Swings are permanent historical facts. Being exceeded is a **separate** event, which later becomes a break.
  - **(b)** The swing is marked broken or consumed through a separate event.

  Under the §3 replay contract, an emitted swing may **never** be edited or deleted. A "consumed" state must be a new event. INVARIANT.

### 2.10 Confirmation delay and causality

- **PDF fields:** `event_index`, `event_time`, `confirmed_index`, `confirmed_time`, `available_from` (= after the close of `confirmed_index`). SOURCE RULE + INVARIANT.
- **The five no-look-ahead invariants** (PDF §3). INVARIANT:
  1. No event before `confirmed_index`.
  2. No read of a candle index greater than the current replay index.
  3. Confirmed events do not repaint.
  4. Batch and streaming modes agree at equivalent availability times.
  5. Event times match their indices.

### 2.11 End of dataset

- **PDF §4 and E2:** a candidate without R right bars **remains unconfirmed**. *"Do not force-label the final lowest candle as a swing low."* SOURCE RULE + INVARIANT.
- **Examples:** SW01 (low at 7), SW08 (high at 3 with one right bar). SW02 shows the same low confirming once two bars are appended.

### 2.12 Directional-change and adaptive methods (PDF §2.C)

- Described as an alternative that is *"path-dependent"*. *"Do not add it unless explicitly selected."* SOURCE RULE (an exclusion).
- No fixture is designed for it. If you select it, a separate fixture set is needed, because its confirmation timing is threshold-dependent and not `i+R`.

## 3. Summary of swing decisions needed

The **swing** items from the PDF's approval register are **SW-001 … SW-008**. They are expanded with options and consequences in `UNRESOLVED_DECISIONS.md`.

Three additional decisions came up during this analysis:
- **D-SW-START:** left-history rule at the series start.
- **D-SW-GAPS:** whether windows count bars or time when bars are missing. Case RB03.
- **D-SW-ORDER:** the ordering of a swing high and a swing low with the same index (outside bar).
