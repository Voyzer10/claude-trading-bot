# BOS RULE MATRIX: V6 Volume 1

**Approval status:**
- **INV**: invariant.
- **OPEN**: needs your decision.
- **ILL**: illustrative profile used for the fixtures.

Nothing here is approved as strategy.

## BOS rules

**BOS-R01: Causal reference (INV)**
- **Rule:** only a confirmed swing can be a reference.
- **Source:** PDF E6, §10.
- **Input:** swings, break candle k.
- **Condition:** `k > reference.confirmed_index`.
- **Output:** no event otherwise.
- **Confirmation timing:** —
- **Edge cases:** the candidate is exceeded before it confirms.
- **Tests:** BOS09.

**BOS-R02: Reference selection (OPEN, BOS-001)**
- **Rule:** which confirmed swing is the level.
- **Source:** PDF §5.
- **Input:** swings, state.
- **Condition:**
  - **RL:** the latest confirmed swing of that kind, if unbroken.
  - **RH:** the highest unbroken high / lowest unbroken low.
  - A protected level (P-1 / P-2 / P-3).
  - Internal or external.
- **Output:** reference id.
- **Confirmation timing:** —
- **Edge cases:** an equal-high cluster (SW05); several unbroken levels.
- **Tests:** BOS12, BOS10, MS06.

**BOS-R03: Bullish break evidence (OPEN, BOS-002)**
- **Rule:** what counts as a break up.
- **Source:** PDF §5, E4, E5.
- **Input:** close, high, level, tick.
- **Condition:**

  | Profile | Condition |
  |---|---|
  | P1 | `C > lvl` |
  | P2 | `C ≥ lvl` |
  | P3 | `H > lvl` |
  | P4 | `C > lvl + n·tick` |

- **Output:** break at k.
- **Confirmation timing:** close of k (see BOS-R06).
- **Edge cases:** wick-only; exact; one tick; floating-point.
- **Tests:** BOS03, BOS04, BOS05, BOS06, BOS15.

**BOS-R04: Bearish break evidence (OPEN, BOS-002)**
- **Rule:** the mirror of BOS-R03.
- **Source:** PDF §5.
- **Input:** close, low.
- **Condition:** `C < lvl` / `≤` / `L < lvl` / buffer.
- **Output:** —
- **Confirmation timing:** —
- **Edge cases:** —
- **Tests:** BOS02 (mirror of BOS01).

**BOS-R05: Classification (OPEN, BOS-003)**
- **Rule:** continuation BOS, counter-structure (CHoCH candidate), or unclassified.
- **Source:** PDF §6.
- **Input:** state as of k−1, direction.
- **Condition:**
  - aligned → `BOS`
  - against → `CHOCH_CANDIDATE`
  - UNKNOWN → `UNCLASSIFIED`
- **Output:** label.
- **Confirmation timing:** —
- **Edge cases:** conflicting state (MS05); insufficient context (BOS14).
- **Tests:** BOS01, BOS02, BOS10, BOS12, BOS14, MS05.

**BOS-R06: Event timing (OPEN, BOS-004)**
- **Rule:** when the event exists.
- **Source:** PDF §5.
- **Input:** k.
- **Condition:** emit at the close of k, or after the close of k+n with the condition still true.
- **Output:** `confirmed_index` = k or k+n.
- **Confirmation timing:** k / k+n.
- **Edge cases:** a confirmation bar that closes back inside.
- **Tests:** BOS13 (decides whether a "k+1" rule would cancel the event).

**BOS-R07: De-duplication (OPEN, BOS-005)**
- **Rule:** the number of events per level.
- **Source:** PDF §7, E7.
- **Input:** reference id.
- **Condition:** one per reference / per new cross / per close beyond / cooldown.
- **Output:** 1 to n events.
- **Confirmation timing:** —
- **Edge cases:** a new level must give a distinct event.
- **Tests:** BOS08, BOS11.

**BOS-R08: Gap-through (OPEN, BOS-006)**
- **Rule:** an open beyond the level.
- **Source:** PDF §7.
- **Input:** open, previous close.
- **Condition:** counts / excluded / flagged.
- **Output:** event with evidence `gap`.
- **Confirmation timing:** —
- **Edge cases:** the whole bar is beyond the level.
- **Tests:** BOS07.

**BOS-R09: Exact level and tick (OPEN, BOS-006)**
- **Rule:** the comparison basis.
- **Source:** PDF §7 ("Precision").
- **Input:** tick size.
- **Condition:** raw float vs tick-rounded; strict vs inclusive.
- **Output:** —
- **Confirmation timing:** —
- **Edge cases:** floating-point representation.
- **Tests:** BOS05, BOS06, BOS15.

**BOS-R10: Close back through (OPEN, BOS-007)**
- **Rule:** invalidation semantics.
- **Source:** PDF §5, §11.
- **Input:** later closes.
- **Condition:** none, or a separate INVALIDATION event referencing the BOS.
- **Output:** new event only.
- **Confirmation timing:** close of the return bar.
- **Edge cases:** —
- **Tests:** BOS13.

**BOS-R11: Immutability (INV)**
- **Rule:** an emitted BOS never moves, changes or disappears.
- **Source:** PDF §3.
- **Input:** replay.
- **Condition:** the prefix events are a subset of the full-run events, identical.
- **Output:** —
- **Confirmation timing:** —
- **Edge cases:** —
- **Tests:** harness plus T-PAR.

**BOS-R12: Displacement filter (OPEN, not in the register)**
- **Rule:** minimum break size.
- **Source:** PDF §5 ("Displacement … Required").
- **Input:** ticks, points, ATR, body size.
- **Condition:** —
- **Output:** —
- **Confirmation timing:** —
- **Edge cases:** —
- **Tests:** none until decided.

**BOS-R13: Scope (OPEN)**
- **Rule:** BOS emits no liquidity, sweep or trade signal.
- **Source:** PDF §10, §13.
- **Input:** —
- **Condition:** structural events only.
- **Output:** —
- **Confirmation timing:** —
- **Edge cases:** —
- **Tests:** independence test (exists).

## Pseudocode (illustrative profile: RL + P1 + one event per reference; for review, not implemented)

```
detect_breaks(prefix 0..k, swings_known_at(k-1), state_at(k-1)):
    for kind, dir in ((HIGH, bullish), (LOW, bearish)):
        ref = latest swing of kind with confirmed_index < k           # BOS-R01, RL
        if ref is None or ref.id in broken: continue                  # BOS-R07 (one per reference)
        if evidence(bar k, ref.price, dir, profile):                  # BOS-R03 / R04, tick-aware compare
            broken.add(ref.id)
            label = classify(state_at(k-1), dir)                      # BOS-R05
            emit Break(id=stable_id(dir, ref.id), stamp=(k, t[k], k, t[k]),
                       ref=ref.id, level=ref.price, evidence=..., profile=..., label=label)
```

**Batch vs streaming:** a streaming detector keeps `broken` and the state between candles. The batch version recomputes them from the prefix. Both must give the same events at every k (T-PAR).
