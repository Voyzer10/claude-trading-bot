# Paper broker and Risk gate: four safety checks (20 Nov 2026)

Branch `feat/risk-gate` (`5fb8148`), on top of `feat/paper-only-broker`. This document describes what the code does
today. Every behaviour marked **verified** was run against that commit (probe script in the session; it is reproduced
by the tests named here, or listed as a gap). Nothing in this document changes trading behaviour. The gaps listed
are proposals waiting for approval.

---

## 1. Risk configuration validation

**What exists.** Risk reads every limit from the account config (`trader/paper/config.json`, `accounts.<NAME>`).
- Keys the old code used with a fixed number fall back to that same number when the key is absent:
  - `max_fee_risk_frac` 0.5
  - `min_fill_frac` 0.25
  - `max_fee_r` 0.25
- `min_net_rr` is not enforced while unset.
- `load_config()` merges new default keys into the file, so the keys the code reads directly normally exist.
- `margin_x()` clamps `intraday_leverage` to [1, 5].

**There is no explicit validation of types or ranges.** Verified outcomes:

| Config value | What Risk does today | Safe? |
|---|---|---|
| `min_reward_risk` missing / `None` / `"1.0"` (string) | Python exception (KeyError / TypeError) in `risk_check`. No order is filled, but the error is not a Risk decision: `cmd_buy` callers catch `PaperError` only, so the agent's cycle for that setup crashes. | Fails closed, not cleanly |
| `max_loss_per_trade` missing | KeyError, as above | Fails closed, not cleanly |
| `risk_limits` on with `daily_loss_limit` missing | KeyError, as above | Fails closed, not cleanly |
| `max_fee_risk_frac = "abc"`, `min_net_rr = "x"` | ValueError, as above | Fails closed, not cleanly |
| `max_loss_per_trade = 0` or `-30` | REJECTED ("0 units fit", shows the negative max loss) | Safe, message odd |
| `min_reward_risk = -5` | APPROVED: the R:R floor is effectively off | **Not safe** |
| `max_fee_risk_frac = 99` | APPROVED: the charges check is effectively off | **Not safe** |
| `max_position_pct = 1000` | APPROVED with a bigger size (max loss and cash still cap it) | **Not safe** |
| `fee_pct = -0.5` | APPROVED, and costs are understated | **Not safe** |
| `slippage_pct = -1` | Stop and target maths go wrong (NEEDS_REVISION here; can approve elsewhere) | **Not safe** |
| `intraday_leverage = 0` / `50` | Clamped to 1 / 5 | Safe |

**Proposal (Step 1.1, no change for valid configs):** a `risk.validate_account(acc)` run at the start of
`risk_check`.
- Required keys present and numeric.
- Ranges enforced:
  - `max_loss_per_trade` > 0
  - 0 < `max_position_pct` ≤ 100
  - `min_reward_risk` ≥ 0
  - 0 < `max_fee_risk_frac` ≤ 1
  - `fee_pct`, `slippage_pct` ≥ 0
  - `daily_loss_limit` > 0 when `risk_limits` is on
- Anything invalid returns a clean **REJECTED "invalid risk config: …"**: never an exception, never an approval.
- Settings could run the same validator before saving.

---

## 2. Approval lifecycle and restart behaviour

**What exists.**
1. `risk_check` issues an APPROVED decision with an `approval_id` and a `fingerprint` (SHA-256 of the order's
   binding parameters):
   - symbol (resolved to its paper key), side, order type, limit price
   - stop and target as requested, qty / lots, price, force, allow_second
   - setup id, client order id
2. The id is registered in an in-process table (`risk._ISSUED`).
3. `paper.execute_order` (the Broker) checks, in order:
   - paper mode
   - simulator ready
   - `risk.consume()`: the decision is APPROVED, the fingerprint equals the current order's, and the id is in the
     table. The id is then removed: **single use** (tested in `test_risk_gate.py`).
4. A refused *modified* copy does not use the approval up; the unmodified order can still fill (tested).
5. A forged approval (never issued), an edited decision, or no approval: refused (tested).

**Restart.** The table lives in memory only. After a process restart every earlier approval is unknown and refused
("already used or never issued"). Nothing is queued between processes: `cmd_buy` runs Risk and the Broker in one
synchronous call, so a restart can only lose an approval, never execute one. **Verified by design** (no
persistence code exists).

**Gaps found (verified):**
- **Approvals never expire.** If the Broker refuses *before* `consume()` (paper mode wrong, simulator unavailable),
  the approval stays in the table. Verified: an approval refused under `TRADER_EXECUTION_MODE=LIVE` was later
  executed with a clock set to 2030, at the original 2026 quote, with no revalidation.
  - Today no caller keeps an approval object (`cmd_buy` drops it), so this is not reachable in the running bot.
  - It is a gap at the API boundary.
- **The table grows** with approvals that are issued but never executed (refused before consume). Small, but
  unbounded in a long-running process.

**Proposal (Step 1.1):**
- Consume the approval on *any* Broker attempt that passes the fingerprint check: a refusal burns it, and a retry
  needs a new Risk decision.
- Add an approval lifetime. Every agent today executes in the same call, so a config key `risk_approval_ttl_s`
  could default to a few seconds without changing behaviour. **The value is yours to set; I have not picked one.**

---

## 3. Fill-price revalidation

**What exists.**
- `execute_order(req, approval, ..., fill_quote=None)`: when `fill_quote` differs from the quote Risk approved, the
  Broker calls `risk_check` again at that price (not registered: used immediately).
- It executes only if the new decision is APPROVED **and** allows at least the approved size.
- It then fills the **approved** quantity: never more, never a silently smaller one.

Verified (tests in `test_risk_gate.py`):
- Small move: fills at the new price with the approved size.
- Fill beyond the stop: NEEDS_REVISION, refused.
- Risk per unit up: the approved size now breaks the max loss, refused.
- R:R under the minimum at the new price: refused.

**Limits of what it covers today:**
- **Live paper fills never trigger it.** `cmd_buy` passes no `fill_quote`, so the Broker fills at the quote Risk
  saw. That is the old behaviour (one quote per order), and the reason parity is exact. The check matters only when
  a real fill price differs, for example a future fill model with latency or spread.
- **Percent / R specs move with the fill.** Verified: stop "2%" and target "2R" approved at 2,940 / 3,120 (quote
  3,000) were filled at 2,930.20 / 3,109.61 when the fill was 2,990: revalidated, but not the approved levels.
  - Every agent today sends absolute prices (`str(stop)`), so their stop and target never move.
  - Only a manual CLI order with a percent stop can show this.
- **Exact float comparison** (`quote != approved quote`): any difference at all triggers revalidation. That is
  conservative, and fine.
- **Same clock.** Revalidation uses the approval's `now`, so time rules (session, flat-by, trades per day) are
  re-checked at the same moment, not at the fill moment.

**Proposal (Step 1.1, no change to today's fills):**
- On revalidation, keep the *approved* stop and target prices (absolute) instead of recomputing percent / R specs
  from the new fill, or refuse when they would move.
- Pass the fill time to revalidation.

---

## 4. Journal failure and ledger consistency

**What exists.**
- **Order of writes:** the journal line is written before the in-memory ledger changes.
- **Journal write fails** (disk full, folder not writable): `PaperModeError`, the ledger is untouched (tested,
  entries and exits).
- **Rejected / cancelled orders:** the journal line is best-effort. A journal failure there does not change the
  outcome, because nothing was executed.

**The ledger file is saved by the caller after the call:**
- `live.py` after the whole `check_once` loop
- `setup_decision` / `auto_*` after each fill

**Gaps found:**
- **Crash window (verified).** After the journal line and before the caller's `save_json`, a crash leaves a
  PAPER_FILLED journal line with no position in `ledger.json`. The duplicate guard reads the ledger only, so after a
  reload the **same client order id can fill again**: two FILLED lines for one id were verified.
  - Exits have the same window, by the same code (not separately probed): `live.py` saves only after all positions
    are checked.
  - So a crash mid-loop can leave EXIT lines whose positions reopen on reload and are exited again: two EXIT lines
    for one trade id.
- **The ledger save can fail** while the journal says FILLED. The in-memory position is then lost on the next load.
- **No reconciliation:** nothing compares `orders.jsonl` with `ledger.json`.
- **Fail-closed also blocks exits.** Paper mode misconfigured or simulator unavailable: `close_position` refuses, and
  `check_once` logs the error and keeps the position open, so **stops are not honoured while the box is
  misconfigured**. That is acceptable in paper (no money), but it must be visible. Today it is only one log line per
  position per cycle.

**Proposal (Step 1.1):**
- The duplicate guard also checks the journal: a client order id with a PAPER_FILLED line is never filled again,
  even if the ledger lost it.
- A `reconcile()` run at runner start:
  - lists FILLED-entry lines without a ledger position (or a closed record), and EXIT lines whose position is still
    open
  - reports them on the dashboard
  - never "fixes" by trading
- A loud dashboard notice when exits are blocked by fail-closed.
