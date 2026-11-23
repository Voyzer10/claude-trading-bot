# BOS CONCEPT ANALYSIS (and BOS vs CHoCH): V6 Volume 1

**Source:** PDF §5, §6, §7, §8 (E4–E8), §10, §11. Analysis only.

The PDF's framing:
- *"BOS is commonly used for a break of a previously identified structural swing level, often in the direction of existing structure. **The term alone is not executable.**"*
- *"Do not label by direction alone."* SOURCE RULE.

## 1. Required elements of a BOS (the PDF's eight decisions, §5)

| Decision | PDF options | Consequence | Fixtures |
|---|---|---|---|
| Reference level (BOS-001) | Latest confirmed swing; protected swing; external or internal swing | Which breaks exist at all. RL (latest) vs RH (highest unbroken) differ in BOS12 and BOS10 | BOS12, BOS10, MS06 |
| Break evidence (BOS-002) | Wick; close; close + buffer | Wick fires earlier and more often (BOS03: wick only; BOS04: 21 vs 22). A buffer removes marginal closes (BOS06) | BOS03–BOS06 |
| Direction / state (BOS-003) | Continuation BOS; counter-structure; trend context | The label; needs the state model in MARKET_STRUCTURE_SPEC | BOS01, BOS02, BOS10, BOS12, BOS14, MS05 |
| Timing (BOS-004) | Emit on the break close, or wait for another confirmation bar | The confirmed index is k, or k+1 / k+n | all BOS |
| Repeated breaks (BOS-005) | One event per level; de-duplicate; or a cooldown | The number of events | BOS08, BOS11 |
| Invalidation (BOS-007) | Is the historical event kept? Is the setup invalidated on a close back through? | An emitted event must stay (INV); invalidation is a new event | BOS13 |
| Equal levels (part of BOS-001 / SW-004) | Cluster member, tolerance, reference selection | Which of two equal highs is "the" level | SW05, MS03 |
| Displacement | No minimum; ticks / points; ATR; body-size filter | Filters weak breaks. Not in the approval register list; noted in §5 as "Required" | none yet (needs a decision first) |

**Gap and exact level (BOS-006):** PDF §7 says to *"specify whether gap qualifies"* and *"define > / < or ≥ / ≤ and tick size"*. Fixtures BOS05, BOS06, BOS07 and BOS15.

## 2. Concepts in turn

### 2.1 Eligible reference swing

- **INV (PDF E6):** a level cannot be used **before its swing confirms**. The break candle index must be **greater than** the reference's `confirmed_index`.
- **Derived consequence:** under a strict fixed window, the right-window bars of a swing high all have highs below it. So no bar up to and including the confirmation bar can close or wick above the level. In other words, a "break before confirmation" shows up as the **candidate never confirming** (BOS09: bar 15 exceeds bar 14, so bar 14 never becomes a swing and no break of "bar 14's level" exists).
- **Options (OPEN):**
  - **RL:** the latest confirmed swing of that kind, if unbroken.
  - **RH:** the highest unbroken high (lowest unbroken low).
  - Internal vs external profile (SW-006).
  - The protected level (MARKET_STRUCTURE_SPEC §4).
- **Example BOS12** (bearish structure):
  - RL: price closes above the latest LH (106.7) at bar 17, which is a counter-structure break.
  - RH: nothing breaks, because the older high 110.7 holds.
- **Link to the V4 audit:** V4 broke the latest swing high regardless of whether it was lower than the prior one (52% of V4 BOS events). This decision decides whether V6 does the same.

### 2.2 Bullish and bearish

The definitions mirror each other. Mirror tests BOS01 ↔ BOS02 give identical indices in the scratch checker.

### 2.3 Wick vs close

| Profile | Rule |
|---|---|
| P1 | close > level |
| P2 | close ≥ level |
| P3 | high > level |
| P4 | close > level + 2 ticks |

- BOS03: a wick to 110.6, closes below. Only P3 fires.
- BOS05: close = 110.2 exactly. P2 and P3 fire; P1 does not.
- BOS06: close = 110.21. P1, P2 and P3 fire; P4 does not.

### 2.4 Protected swing levels

Needed only for CHoCH. Definitions in MARKET_STRUCTURE_SPEC §4; OPEN.

### 2.5 Internal vs external BOS

Under SW10's data, a 2/2 internal BOS fires at bar 8 and a 5/5 external BOS does not (MS06). If both levels exist, events need a `profile` / `scope` field (model gap G1).

### 2.6 Continuation BOS

Bullish state (HH + HL) and a close above the reference high is BOS (BOS01 at 22, BOS11 at 22 and 31). The state is taken as of close k−1 (PROPOSAL; see MARKET_STRUCTURE_SPEC §3).

### 2.7 Repeated breaks of the same level

- BOS08: closes above at 21, below at 22, above at 23 and 24.

  | Policy | Events |
  |---|---|
  | one per level | 21 |
  | per new cross | 21, 23 |
  | per close beyond | 21, 23, 24 |

- The PDF recommends *"Deduplicate by stable level ID"* (§7). That is a SOURCE suggestion, not approved.

### 2.8 Breaks before swing confirmation

See §2.1. BOS09.

### 2.9 Gap-through

- BOS07: the open at 110.6 is above the level (previous close 107.8), and the whole bar is above it.
- **Options:**
  - counts (event at 21, evidence `close; gap`)
  - excluded
  - flagged

  OPEN (BOS-006).

### 2.10 Exact level and tick size

- BOS15: the level is stored as `0.30000000000000004` and the close is `0.3`.
  - Raw floats: even ≥ fails.
  - Tick-rounded (0.01) with ≥: a break at 5.
  - Tick-rounded with >: no break.
- The models have no tick size: model gap G5.

### 2.11 Event confirmation and invalidation

- **INV:** a BOS emitted at k is immutable.
- BOS13: a close back below at 23. Under BOS-007, either nothing happens, or a separate *invalidation* event refers to the BOS. The BOS itself is **never** removed.

## 3. BOS vs CHoCH (PDF §6)

The PDF's common illustrative convention. ILLUSTRATIVE; **not** approved:

| Prior structure | Break | Label |
|---|---|---|
| HH then HL; close above prior swing high | Up, aligned | Bullish continuation BOS |
| LL then LH; close below prior swing low | Down, aligned | Bearish continuation BOS |
| Bullish; close below **protected HL** | Against | *Potential* bearish CHoCH |
| Bearish; close above **protected LH** | Against | *Potential* bullish CHoCH |

**Findings:**
- **Direction alone is not a label (SOURCE).** BOS10 is a down-close against bullish structure. Under RL/TS-A it is `CHOCH_CANDIDATE`, not "bearish BOS".
- **UNKNOWN state means no label.** MS05 and BOS14 must output `UNCLASSIFIED` (insufficient context), not BOS.
- **MSS:** used inconsistently (PDF §6). Not adopted.
- **CHoCH is defined only after a separate approved definition** (PDF §10: `structure/choch.py` *"Only after separate approved definition"*). The fixtures therefore label counter-structure breaks `CHOCH_CANDIDATE` and nothing more.
- **Open questions:**
  - Does a CHoCH flip the state immediately?
  - Is the next same-direction break the confirming BOS?
  - Which protected level applies: P-1, P-2 or P-3?

## 4. Proposed BOS event output (against the existing models)

| Required field (task) | Existing model | Gap |
|---|---|---|
| Direction | `StructureEvent.direction` | — |
| Reference swing ID | `broken_swing_id` (+ `related`) | — |
| Reference price | `level` | — |
| Reference swing event index | only by looking up the swing event | G1: add `reference_index` or require a lookup |
| Reference swing confirmation index | lookup | G1 |
| Break candle index / timestamp | `stamp.index` / `stamp.ts` | — |
| Confirmation index | `stamp.confirmed_index` | — |
| Evidence type | none | G1: `evidence` (close / wick / close_buffer / gap flag) |
| Rule profile used | none | G1: `profile` |
| Related event IDs | `related` | — |
| Classification (BOS / CHoCH candidate / unclassified) | separate classes `BOSEvent` / `CHoCHEvent` only | G11: no class for UNCLASSIFIED or candidate |

No schema change is made in this phase.
