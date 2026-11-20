# Step 2 design: Exit agent and Trade Manager separation (proposal, not implemented)

Base: `feat/risk-gate` (`5fb8148`). Goal: the Exit agent **decides**, the Trade Manager **applies and records**, and
the Broker **executes** the close. Every trade must stay identical (the same exits, at the same prices and times,
with the same P&L). PARTIAL_EXIT exists as a type and stays **disabled by default**.

## Roles after Step 2

| Component | Owns | Never does |
|---|---|---|
| **Exit agent** (`exit_agent.py`, new) | Pure functions: given a position, a candle / price, the account's settings and the time, return a decision: HOLD, MOVE_TO_BREAKEVEN (new stop), TRAIL_STOP (new stop), PARTIAL_EXIT (qty), FULL_EXIT (price, reason). With a structured record: rule, inputs, old / new stop, R now, time. | Mutate positions, call the Broker, open or add to a position, widen a stop |
| **Trade Manager** (`paper.py`, today's `check_position` loop, slimmed) | Walks the candles in order. Enforces the approved SL / TP (resting orders: stop first, then target, gap fills). Asks the Exit agent. Validates each decision: a stop may only tighten; one action per position per step; no action on a closed position. Applies stop moves. Sends FULL / PARTIAL exits to the Broker. Logs every state change (same `tm_log` texts plus a structured record). | Invent rules, pick prices |
| **Broker** (`paper.close_position`) | Executes the close: journal line first, ledger, P&L, trade id | Decide anything |

SL / TP hits are the Trade Manager's job, not the Exit agent's: they are the levels Risk approved, already resting.
Enforcing them takes no decision.

## Every existing exit path

Defaults are `DEFAULT_CONFIG` values; the live config can differ per account. "Apply" means the Trade Manager
validates the decision and then either changes the stop or asks the Broker to close.

| # | Path | Current location | Trigger today | Decides (after) | Applies (after) | How it stays identical |
|---|---|---|---|---|---|---|
| 1 | **Stop hit** (also "breakeven stop", "profit lock stop", "trailing stop"; "(gapped past it)") | `paper.step_bar` | Per candle, first: long `low ≤ stop` (short `high ≥ stop`). Fill at the stop, or at the open if the candle opened past it. Reason from the flags trailing / locked / breakeven. Also logs a tm_event when a lock / BE stop is hit. | Trade Manager (approved resting order) | TM → Broker `close_position(fill, reason)` | Same code moved, not rewritten: same order (stop before target in one candle), same fill rule and reason strings |
| 2 | **Target hit** | `paper.step_bar` | Per candle, after the stop check: long `high ≥ target`. Limit fill at the target. | Trade Manager | TM → Broker | Same |
| 3 | **Breakeven + trailing** (Trade Manager) | `paper.tm_trail` ← `step_bar`, rule in `scanner_v4.trail_lock_r` (shared with the backtest) | After the SL / TP check, on the candle's best price: gain ≥ `tm_be_r` (1.0) → stop to the entry. With `tm_trail` (on), every `tm_trail_step` (1R) → stop `tm_trail_gap` (1R) behind. Moves only if tighter. Applies from the next candle. | **Exit agent**: MOVE_TO_BREAKEVEN / TRAIL_STOP (calls the same `trail_lock_r`) | TM: tighten-only check, set stop / flags, the same tm_event text | The rule function stays shared with the backtest (`scanner_v4`); same candle and same "next candle" timing |
| 4 | **Profit lock** | `paper.step_bar` | After the trail: `tm_lock_at` > 0 (default **0 = off**), best covered `tm_lock_at` of the way to the target → stop at `tm_lock_keep` (0.5) of the way. Once only (`locked`). | **Exit agent**: TRAIL_STOP (rule "lock") | TM | Same order after #3; same rounding (`round_px`) and once-only flag |
| 5 | **Crypto ATR trailing exits** (legacy crypto rules; positions with `trail_k`) | `paper.step_bar` (fields set at entry by `auto_crypto` run_smc / run_smcp / run_one) | Instead of the Trade Manager: peak ≥ entry + `trail_arm_r`·risk → stop to the entry; then stop = peak ∓ `trail_k`·`trail_atr`, tighten only | **Exit agent**: MOVE_TO_BREAKEVEN / TRAIL_STOP (rule "atr_trail") | TM | Same branch logic and order; the TM rules stay off for `trail_k` positions. Off on v4 accounts today |
| 6 | **Option exit on the underlying** (v4 options, `underlying_plan`) | `paper.underlying_exit` ← `check_position` | After the candle walk: the underlying's 1-minute candles / live price reached the v4 stop (first) or target → close the option at its price. Data errors never close. | **Exit agent**: FULL_EXIT (rule "underlying stop / target") | TM → Broker | The same function, called at the same point; the same messages |
| 7 | **Reversal take-profit** | `paper.tm_react` ← `check_position` | `tm_reversal` (default **off**), `mfe_r ≥ tm_rev_min_r` (1.0); on `tm_candle_min` (5) candles: bearish engulfing or upper-wick rejection (wick ≥ 60%, close in the low 40%) within 0.25R of the best → close | **Exit agent**: FULL_EXIT (rule "reversal") | TM → Broker | Same function, same `tm_seen` bookkeeping. The fixed 0.6 / 0.4 / 0.25 become optional config keys with these defaults (Risk pattern) |
| 8 | **No follow-through (stale)** | `paper.tm_react` | `tm_stale_min` > 0 (default **0 = off**), age ≥ it, `mfe_r` < 0.5 and \|R now\| < 0.3 → close | **Exit agent**: FULL_EXIT (rule "stale") | TM → Broker | Same; 0.5 / 0.3 become optional keys with these defaults |
| 9 | **Carried overnight** | `paper.check_position` | Intraday account (`flat_by` set, market has hours) and the entry day ≠ today → close at the price | **Exit agent**: FULL_EXIT (rule "overnight") | TM → Broker | Same condition, checked after #6–#8 as today |
| 10 | **Flat-by** | `paper.check_position` | Intraday and past `flat_by` local time (NSE 15:15, US 15:55 in defaults) → close | **Exit agent**: FULL_EXIT (rule "flat_by") | TM → Broker | Same; the same `elif` order after #9 |
| 11 | **Crypto time stop** | `auto_crypto.time_stops` (runs inside the crypto agent's cycle) | CRYPTO positions that are **not** v4 (`pdf_only`), age ≥ `max_hold_hours` (12) → fetch a price, close | **Exit agent**: FULL_EXIT (rule "max_hold") | TM → Broker | `auto_crypto` asks the Exit agent instead of closing itself. Same call site and moment in the cycle, the same price fetch and reason "time stop 12h". Off for v4 trades today |
| 12 | **Flip close** | `paper.setup_decision` (the **entry** path) | A v4 primary setup with the scanner's `flip` flag and an open opposite-side v4 primary on the chart → close it at the live price, save, then evaluate the new entry | **Exit agent**: FULL_EXIT (rule "opposite BOS flip"), triggered by the scanner's observation | TM → Broker, called from the same point in `setup_decision` | The entry path stops closing positions itself: it asks Exit, and the TM applies. Same order (close and save before the new entry), same price fetch, same reason text, same "blocked" result if the close fails |
| 13 | **Manual close** (dashboard Close / Close all; CLI `paper.py sell`) | `live.py` command handler; `paper.cmd_sell` | The owner's command | The owner (recorded as "manual") | TM → Broker | Same command flow and reason strings |
| — | Engine-simulated exits (not a live exit) | `scanner_v4._exit_step` / `sequence` | The backtest's exits, and the chart state the scanner uses to know whether "its" trade is closed | Unchanged in Step 2 (it is the scanner's model; Step 4) | — | Not touched |

**Findings, not changed in Step 2:**
- `breakeven_at_r` is only printed at entry ("Breakeven: the stop moves … at 1R"). The real breakeven is `tm_be_r`.
  The two show the same number by default, but they are separate settings.
- The crypto time stop (#11) and the ATR trailing exits (#5) apply only to legacy crypto trades. They do nothing for
  v4 accounts today.

## PARTIAL_EXIT
- Defined as an Exit-agent decision type with a quantity.
- The TM / Broker gain a partial close: same journal and ledger order, the trade id kept, a closed record per leg.
- **No rule emits it unless new keys are set** (`partial_exit_at_r`, `partial_exit_frac`, both unset by default).
- A partial is skipped if its charges exceed a configured share of its P&L. That key is also unset, so the rule
  stays off.
- Unit-tested with the keys set in tests only.

## Records
- Every Exit decision and TM application gets a structured line `{agent, decision, rule, setup_id, trade_id, ts,
  inputs, old_stop, new_stop, price, r_now, reason}`.
- Where:
  - appended to `trader/paper/management.jsonl` (new, append-only)
  - mirrored in the decision log
- The existing `tm_log` / `TM_EVENTS` texts stay exactly as they are (the dashboard reads them).
- Conflicts:
  - One position, one action per step: FULL_EXIT wins over stop moves.
  - A decision for a position that is no longer open is refused and recorded.
  - Re-entries after a full exit stay blocked by the client order id and the scanner's "no fresh signal after the
    last exit".

## Parity-testing plan
1. **Baseline first:** worktree at `5fb8148`, capture before any Step 2 code.
2. **Replay** (the Step 1 harness, extended):
   - Same 18 symbols × 3,000 candles.
   - Variants:
     - (a) default
     - (b) risk limits on
     - (c) **tm_all**: `tm_reversal` on, `tm_stale_min` 60, `tm_lock_at` 0.5, `tm_trail_step` 0.5. This exercises
       #4, #7 and #8, which are off by default.
   - The harness also records **every stop change** per position per candle (stop, flags, `mfe_r`, `tm_log`), not
     only the final exits.
   - Compared: decisions, every stop path, exit price / time / reason, P&L, R, cash, order journal.
   - Pass = 0 differences.
3. **Differential fuzz** of the per-candle logic:
   - 20,000 random positions (long / short, crypto / NSE / US, TM settings sampled from the documented ranges, legacy
     `trail_k` positions).
   - Random candle paths, gaps included.
   - Run through the old `check_position` (base worktree) and the new Trade Manager + Exit agent, in separate
     processes with the same seeds.
   - Compare the full position state after every candle, and the close.
4. **Targeted scenarios** for paths the replay cannot reach:
   - #5 ATR trailing (legacy crypto)
   - #6 option underlying (mocked underlying data)
   - #9 overnight carry
   - #11 time stop (mocked clock, non-v4 crypto position)
   - #12 flip close inside `setup_decision`, with a failing price fetch included
   - #13 dashboard close and CLI sell
   - Each one is checked old vs new.
5. **PARTIAL_EXIT off:** the full replay with default config shows 0 partial actions. A unit test with the keys set
   checks the partial accounting: cash, fees, P&L per leg, trade id.
6. **Report:** every difference with its exact cause. No threshold is adjusted to force parity.
