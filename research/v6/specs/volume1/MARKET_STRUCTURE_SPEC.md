# MARKET STRUCTURE SPECIFICATION (HH / HL / LH / LL): V6 Volume 1

Status: **draft. Every rule is OPEN (MS-001)** unless it is marked INV.

## 1. What the PDF says

- **HH / LH:** *"Higher / Lower High vs prior comparable confirmed high. Requires sequence and comparison policy."* SOURCE RULE: a comparison against a *prior comparable confirmed* swing is required; the policy is open.
- **HL / LL:** the same for lows.
- *"Do not assume that every sequence of pivots automatically creates a valid trend"* (the task prompt). PDF §6: *"If prior state or protected level is unavailable, return an explicit insufficient-context/unknown state rather than guessing."* SOURCE RULE.

## 2. Classification (illustrative profile ML-A)

| Item | Definition | Class |
|---|---|---|
| Comparable swing | The previous **confirmed** swing of the **same kind** (high vs high, low vs low), in confirmation order | ILL (ML-A); alternatives below |
| Label available | At the label's `confirmed_index` = the **newer** swing's `confirmed_index` | INV (a label needs both swings, so it cannot exist before the newer one confirms) |
| No previous swing | `NONE` (not HH / LH) | INV + SOURCE (insufficient context) |
| Equal | `EH` / `EL`. Treatment is OPEN: count as HH, as LH, or neutral | OPEN |
| Comparison basis | Same equality basis as SW-R07 (exact, tick or tolerance) | OPEN |

**Alternatives for "comparable" (MS-001):**
- **(a) ML-A:** previous confirmed swing of the same kind.
- **(b)** Previous swing of the same kind **on the same hierarchy level** (internal or external, SW-006).
- **(c)** Only swings that alternate, i.e. a high must be followed by a low (a zig-zag filter). Consecutive highs keep only the more extreme one. This changes labels when two highs confirm without a low between them.
- **(d)** Highs compared only with the high that produced the last structural break.

These give different label sequences. For example, under (c) the swings in SW10 (H5, L7, H10) alternate, but other data can produce H, H, L.

## 3. Structure state (illustrative TS-A)

| State | Condition at close of k−1 (ILL) |
|---|---|
| BULLISH | latest high label HH **and** latest low label HL |
| BEARISH | latest high label LH **and** latest low label LL |
| UNKNOWN | anything else: no labels yet, `NONE`, `EH` / `EL`, or conflicting (HH + LL, LH + HL) |

- **Why "as of k−1":** the state used to classify a break on candle k must not include information created by candle k itself. That is a PROPOSAL. It is causal either way, because labels confirmed at k are known at k's close. It must be decided, because it changes the label of a break on the same candle on which a swing confirms.
- **Conflicting structure (MS05, broadening):** HH and LL alternate, so the state is UNKNOWN throughout. Breaks still occur (at 9, 14 and 18) but cannot be labelled BOS or CHoCH. INV (no guessing).
- **Insufficient context:** in MS01 the first break (13, above SH6) happens before any HH exists, so it is UNCLASSIFIED. BOS14 is the same.

## 4. Protected levels (needed for CHoCH; all OPEN)

The PDF uses *"protected HL"* and *"protected LH"* (§6) **without a definition**. Candidates:

| Option | Protected low in a bullish structure | Example (BOS10) |
|---|---|---|
| P-1 | The latest confirmed HL | SL18 (103.8): counter-structure close at 22 |
| P-2 | The low that started the leg which made the latest HH, i.e. the HL before the break that created the HH | SL10 (101.8): close at 23 |
| P-3 | The lowest low since the last bullish BOS | depends on the BOS rule |

Mirror for the protected high in a bearish structure. **UNRESOLVED.**

## 5. Internal vs external state

- Two hierarchy levels need **separate state**, otherwise labels mix scales.
- MS06: under 2/2 the internal structure has H5 → H10 = HH. Under 5/5 the external structure has only H10 (`NONE`).
- PROPOSAL: one state object per profile. Events carry the profile id.

## 6. Ambiguous cases to decide

| Case | Issue | Fixture |
|---|---|---|
| Missing previous swing | `NONE`, state UNKNOWN | MS01 (first H / L), BOS14 |
| Equal highs / lows | EH / EL treatment | MS03, SW05 |
| Several pivots close together | Depends on the swing profile and the alternation filter | SW10, SW11 |
| Conflict | HH + LL | MS05 |
| Outside bar | High and low swing at one index: which updates the state first? | SW09 |

## 7. Required outputs (PROPOSAL; schema decisions in UNRESOLVED_DECISIONS.md)

**Structure label event:**
- `id`
- `swing_id`
- `compared_with_swing_id`
- `label` (HH / LH / EH / HL / LL / EL / NONE)
- `stamp`: source index = the swing's index, `confirmed_index` = the swing's `confirmed_index`
- `profile`

**State change event:**
- `id`
- `from_state` / `to_state`
- `cause_ids`
- `stamp`

## 8. Tests (designed, not executed)

- Label correctness: MS01, MS02, MS03, MS05.
- Mirror: MS01 ↔ MS02.
- Label timing: no label before the newer swing confirms.
- State UNKNOWN when it should be.
- State replay parity.

Details: `TEST_CASE_CATALOG.md`.
