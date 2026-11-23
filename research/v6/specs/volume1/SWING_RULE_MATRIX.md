# SWING RULE MATRIX: V6 Volume 1

**Approval status:**
- **INV**: invariant. Required regardless of strategy.
- **OPEN**: needs your decision.
- **ILL**: illustrative profile, used only to make fixtures testable.

Nothing here is approved as strategy.

Case ids refer to `synthetic_volume1.draft.json`.

## Swing rules

**SW-R01: Valid candle input (INV)**
- **Rule:** OHLC must be consistent; timestamps tz-aware UTC and strictly increasing; indices 0..n-1.
- **Source:** PDF §1.
- **Input:** candles.
- **Condition:** `H ≥ max(O,C)`, `L ≤ min(O,C)`, `H ≥ L`, `t[i] > t[i-1]`.
- **Output:** `CandleSeries` or `CandleError`.
- **Confirmation timing:** n/a.
- **Edge cases:** NaN or inf; naive datetime; duplicate or unsorted time.
- **Tests:** RB01, RB02, RB04. Existing `tests/scanner_v6/test_models.py`.

**SW-R02: Candidate ≠ confirmed swing (INV)**
- **Rule:** a candidate is never emitted as a swing event.
- **Source:** PDF §1, §3.
- **Input:** prefix 0..k.
- **Condition:** emit only if the confirmation evidence lies inside 0..k.
- **Output:** no event for candidates.
- **Confirmation timing:** n/a.
- **Edge cases:** a candidate rejected later (SW11).
- **Tests:** SW08, SW11, SW12 replay.

**SW-R03: Swing algorithm (OPEN, SW-001)**
- **Rule:** fixed left/right window, directional change, or other.
- **Source:** PDF §2.A and §2.C.
- **Input:** highs and lows (plus a threshold for directional change).
- **Condition:** —
- **Output:** —
- **Confirmation timing:**
  - fixed window: `i+R`
  - directional change: when the threshold is hit (path-dependent)
- **Edge cases:** the methods must not be mixed (PDF §2).
- **Tests:** all SW cases assume a fixed window (ILL).

**SW-R04: Window sizes L, R (OPEN, SW-002)**
- **Rule:** the number of left and right bars compared.
- **Source:** PDF §2.A (*"L=2,R=2 … not an approved setting"*).
- **Input:** L, R.
- **Condition:** —
- **Output:** —
- **Confirmation timing:** `confirmed_index = i + R`.
- **Edge cases:** R=0 is forbidden (it is not causal confirmation). PROPOSAL.
- **Tests:** SW12 (R = 1, 2, 3 give 4, 5, 6), SW10 (2/2 vs 3/3 vs 5/5).

**SW-R05: Swing high comparison (OPEN, SW-003)**
- **Rule:** the candidate high vs the left and right highs.
- **Source:** PDF §2.A, §2.B.
- **Input:** `H[i-L..i+R]`.
- **Condition:** per profile:

  | Profile | Left | Right |
  |---|---|---|
  | SP-A | `H[i] > H[j]` | `H[i] > H[j]` |
  | SP-B | `>` | `≥` |
  | SP-C | `≥` | `>` |
  | SP-D | `≥` | `≥` |

- **Output:** `SwingPoint(kind=HIGH, price=H[i])`.
- **Confirmation timing:** `i+R`.
- **Edge cases:** ties (SW04, SW13, SW14).
- **Tests:** SW01, SW04, SW13, SW14.

**SW-R06: Swing low comparison (OPEN, SW-003)**
- **Rule:** the exact mirror of SW-R05 on lows.
- **Source:** PDF §1 (*"mirrored local low"*).
- **Input:** `L[...]`.
- **Condition:** `L[i] < L[j]` (strict) or `≤` (inclusive).
- **Output:** `SwingPoint(kind=LOW)`.
- **Confirmation timing:** `i+R`.
- **Edge cases:** ties (SW06).
- **Tests:** SW03, SW06. Mirror test SW01 ↔ SW03 (passes in the scratch checker).

**SW-R07: Equality basis (OPEN, SW-004)**
- **Rule:** when two prices count as equal.
- **Source:** PDF §2.B, §7.
- **Input:** price, tick size, tolerance.
- **Condition:** exact; tick-rounded; `|a−b| ≤ N ticks`; or `≤ k·ATR`.
- **Output:** tie or no tie.
- **Confirmation timing:** —
- **Edge cases:** floating-point (BOS15), 1-tick gap (SW07).
- **Tests:** SW07, BOS15.

**SW-R08: Tie handling (OPEN, SW-004)**
- **Rule:** which bar becomes the swing when highs tie.
- **Source:** PDF §2.B.
- **Input:** tied bars.
- **Condition:** first (SP-B) / last (SP-C) / all (SP-D) / none (SP-A) / cluster.
- **Output:** one swing, several swings, or a cluster.
- **Confirmation timing:** a cluster confirms at the last member's `+R` (PROPOSAL).
- **Edge cases:** adjacent vs separated ties.
- **Tests:** SW04, SW05, SW06, SW13, SW14.

**SW-R09: Outside bar (OPEN, SW-005)**
- **Rule:** can one bar be both a swing high and a swing low?
- **Source:** PDF §7.
- **Input:** bar i.
- **Condition:** allow both / reject both / tie-break.
- **Output:** 0, 1 or 2 swings at index i.
- **Confirmation timing:** both at `i+R`.
- **Edge cases:** order of the two events (INV: must be deterministic).
- **Tests:** SW09.

**SW-R10: Hierarchy, internal / external (OPEN, SW-006)**
- **Rule:** one level of structure, or two.
- **Source:** PDF §7 (*"Define hierarchy and selection"*).
- **Input:** one or more profiles.
- **Condition:** —
- **Output:** tagged swings.
- **Confirmation timing:** differs per window.
- **Edge cases:** the same price event appears at two levels.
- **Tests:** SW10, MS06.

**SW-R11: Nested / overlapping pivots (OPEN, SW-007)**
- **Rule:** keep or suppress pivots inside a larger swing.
- **Source:** PDF §7.
- **Input:** swings.
- **Condition:** —
- **Output:** —
- **Confirmation timing:** —
- **Edge cases:** —
- **Tests:** SW10.

**SW-R12: Swing invalidation / replacement (OPEN, SW-008)**
- **Rule:** what happens after a confirmed swing is exceeded.
- **Source:** PDF §11.
- **Input:** later prices.
- **Condition:** permanent fact + separate "taken" event, **or** a status event.
- **Output:** a new event only. Never an edit (INV).
- **Confirmation timing:** at the close of the exceeding bar.
- **Edge cases:** an exceed caused by a wick vs a close.
- **Tests:** BOS13 (a break, then a return).

**SW-R13: Insufficient left history (OPEN, D-SW-START)**
- **Rule:** candidates at index < L.
- **Source:** PDF §10 (*"insufficient history"*).
- **Input:** index.
- **Condition:** ineligible, or a partial window.
- **Output:** none, or a swing.
- **Confirmation timing:** `i+R`.
- **Edge cases:** first bar of the data.
- **Tests:** SW15.

**SW-R14: Insufficient right bars at end of data (INV)**
- **Rule:** stays unconfirmed.
- **Source:** PDF §4, E2.
- **Input:** prefix.
- **Condition:** fewer than R bars after i ⇒ no event.
- **Output:** none.
- **Confirmation timing:** —
- **Edge cases:** the final bar is the lowest or highest.
- **Tests:** SW01, SW08. SW02 confirms later.

**SW-R15: Event fields (INV)**
- **Rule:** `event_index`, `event_time`, `confirmed_index`, `confirmed_time`, available after the close of `confirmed_index`.
- **Source:** PDF §3.
- **Input:** —
- **Condition:** `confirmed_index ≥ event_index`; times equal to those candles' times.
- **Output:** `EventStamp`.
- **Confirmation timing:** —
- **Edge cases:** —
- **Tests:** `check_stamp_against` (existing).

**SW-R16: Immutability / no repaint (INV)**
- **Rule:** an emitted swing never moves, changes or disappears.
- **Source:** PDF §3.
- **Input:** replay.
- **Condition:** the prefix-k events are a subset of the full-run events, with identical fields.
- **Output:** —
- **Confirmation timing:** —
- **Edge cases:** —
- **Tests:** harness `no_lookahead_violations` (existing). Parity gap: see TEST_CASE_CATALOG T-PAR.

**SW-R17: Deterministic output (INV)**
- **Rule:** the same input always gives the same events, ids and order.
- **Source:** PDF §10.
- **Input:** —
- **Condition:** run twice ⇒ equal.
- **Output:** —
- **Confirmation timing:** —
- **Edge cases:** dict / set ordering.
- **Tests:** T-DET.

**SW-R18: Bars vs time windows (OPEN, D-SW-GAPS)**
- **Rule:** do missing bars break a window?
- **Source:** not in the PDF.
- **Input:** timestamps.
- **Condition:** count bars, or require contiguous time.
- **Output:** —
- **Confirmation timing:** may delay or remove swings.
- **Edge cases:** session breaks (NSE / US overnight).
- **Tests:** RB03.

## Pseudocode (fixed-window family, profile-parameterised; for review only, not implemented)

```
detect_swings(prefix 0..k, L, R, left_cmp, right_cmp, eq):
    for i in L .. k-R:                                  # only candidates whose right window has closed
        for kind in (HIGH, LOW):                        # LOW mirrors HIGH (use -low)
            p = value(i, kind)
            if all(cmp_left(p, value(j, kind), eq)  for j in i-L .. i-1) and
               all(cmp_right(p, value(j, kind), eq) for j in i+1 .. i+R):
                emit SwingPoint(id=stable_id(kind, i), stamp=(i, t[i], i+R, t[i+R]), price=p)
    # order: by (confirmed_index, index, kind) -- deterministic; outside-bar policy applied here
```

At prefix k, the candidates `k−R+1 .. k` are not evaluated (their windows are open). This is what keeps the detector causal.
