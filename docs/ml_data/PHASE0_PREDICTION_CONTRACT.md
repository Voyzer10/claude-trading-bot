# Phase 0 — Step 3: Prediction Contract

**Proposed Contract Version**: `1.0.0` (`PREDICTION_CONTRACT_VERSION = "1.0.0"`, `RISK_ASSESSMENT_CONTRACT_VERSION = "1.0.0"`)
**Status**: Proposed, with the independent-review remediation applied (P1-1…P1-4, P2-5…P2-7). Awaiting independent review. Not self-approved.
**Depends on (frozen, unchanged)**: Step 1 Canonical Market-Data Contract `1.0.0`; Step 2 Chart Contract `1.0.0`
**Implementation**: `ml_data/predictions/` (contract and validation only).
**Not included**: model training, features, inference, backtesting, labels, a Risk Engine, orders or broker calls.

---

## 1. Purpose and the three separate records

| Record | Who produces it | What it says | Module |
|---|---|---|---|
| `Prediction` | ML model + versioned decision policy | What the model predicts for one instrument at one decision time. **Never** permission to trade | `prediction.py` |
| `PredictionStateRecord` | Validity evaluator | Whether that prediction is `VALID`, `EXPIRED` or `INVALIDATED` at a given instant, **with the evidence it was derived from** | `state.py` |
| `RiskAssessment` | (Future) Risk Engine | Whether a directional prediction is `APPROVED`, `REJECTED` or `NOT_APPLICABLE` under a risk policy | `risk_assessment.py` |

All three are immutable, strictly validated and content-addressed: `prediction_id`, `state_id` and `risk_assessment_id` are each the SHA-256 of the record's own canonical JSON. The prediction is never rewritten by a later state or risk record. A `RiskAssessment` is bound to one exact `state_id`.

### 1.1 Existing code inspected (read only, unchanged)

- Step 1:
  - `docs/ml_data/PHASE0_CANONICAL_MARKET_DATA_CONTRACT.md`
  - `ml_data/instruments/` (identity v3, `InstrumentSpecVersion`, NIFTY/BANKNIFTY validation)
  - `ml_data/storage/canonical_schema.py`, `ml_data/storage/manifests.py`
  - `ml_data/calendars/`
- Step 2:
  - `docs/ml_data/PHASE0_CHART_CONTRACT.md`
  - `ml_data/charts/` (identities, `canonical_json`, availability modes)
- Phase 1/2:
  - `ml_data/simulator/` (`CostProfile`, versioned bps costs)
  - `ml_data/labels/` (`LabelRecord` with decision, cutoff and available timestamps)
- V4/V6 risk and execution (boundaries only):
  - `paper.py` (`rulebook_guards`, Risk/Broker agents, `setup_decision`)
  - `v6_runtime/portfolio.py` (daily-loss check, signal rejection reasons)
  - `us/trader-risk/check.py`

There is no existing ML prediction module. The repository-root `risk.py` named in CLAUDE.md is not present on this branch. Risk guards currently live in `paper.py`.

### 1.2 Reused identities and conventions (nothing re-invented)

| Concept | Reused from |
|---|---|
| `instrument_id` format | Step 1 identity v3, checked with Step 2 `INSTRUMENT_ID_RE` |
| Market / segment values | Step 1 `Market` / `Segment` enum values |
| `instrument_spec_version_id`, `instrument_spec_hash`, `instrument_spec_recorded_at_utc`, `instrument_specification` | Step 1 `InstrumentSpecVersion` (`specification` = `Instrument.spec_dict()`, hashed with Step 1 `compute_spec_hash`) |
| `data_snapshot_ids` | Step 2 `data_snapshot_id` values |
| `chart_snapshot_ids` | Step 2 `chart_snapshot_id` values |
| `availability_mode` | Step 2 `AS_KNOWN_AT_DECISION` / `EVENT_TIME` |
| Timeframes | Step 1 `STANDARD_TIMEFRAMES_MINUTES` (`1m`, `5m`, `15m`, `1h`) |
| Calendar / session ids and bounds | Step 1 calendars (`calendar_id`, `calendar_version`, `session_bounds()`, `trade_date_for()`) |
| Decimal strings | Step 1 `normalize_decimal_str` |
| Canonical JSON and SHA-256 | Step 2 `canonical_json` (float-rejecting) and `sha256_of_payload` |
| Cost model reference | `cost_model_id` / `cost_model_version` may name a Phase 1 `CostProfile` (`profile_id` / `version`) |

---

## 2. Design ambiguities and how v1.0.0 resolves them (conservatively)

| # | Ambiguity | v1.0.0 decision | Rationale |
|---|---|---|---|
| A1 | What do probabilities mean? | Two separate, explicit distributions. `direction_probabilities` is over the label classes {LONG, SHORT, NO_TRADE} of a versioned label definition. `outcome_probabilities` is over {target first, stop first, horizon exit}, conditional on taking the proposed trade | One number cannot serve both purposes. The label definition is versioned so the classes have a fixed meaning |
| A2 | Must direction equal the highest-probability class? | No. NO_TRADE is always allowed. LONG/SHORT requires P(selected) **>** P(opposite side). Ties never select a side | A policy can abstain. It must never pick the less-likely side |
| A3 | Confidence vs probability duplication | No stored `confidence` field. `Prediction.confidence` is derived as `direction_probabilities[direction]` | Avoids two names for one number |
| A4 | Uncertainty representation | One kind in v1: `NET_R_PREDICTIVE_INTERVAL` (lower, upper, coverage, method, version), or `UNAVAILABLE` with a reason | Units are net R, the same unit as the decision quantity |
| A5 | Who computes expected net R? | The contract **derives** it from levels, calibrated outcome probabilities and costs. A supplied value is rejected unless it equals the recomputation | A model cannot assert an R it cannot justify |
| A6 | R denominator | Initial risk = gross price distance \|E − SL\| per unit (no costs) | Matches standard trading R. Costs enter only the numerator, so gross R and net R share one denominator |
| A7 | Costs: required or optional? | Applicable costs depend on segment and direction (§7.2). Missing applicable costs make expected net R `UNAVAILABLE`, not zero. Inapplicable costs must be null | Never invent a cost; never report net R from incomplete costs |
| A8 | Session boundaries | Exchange-traded instruments: the horizon must start inside the session and end at or before the session close. Policy `REJECT_BEYOND_SESSION_CLOSE`, no truncation. Crypto: `CONTINUOUS`, no session fields, capped at 24 h | Intraday predictions never silently extend overnight |
| A9 | Supported segments | US_EQUITY, US_OPTIONS, US_FUTURES, IN_INDEX_FUTURES, IN_INDEX_OPTIONS (NIFTY/BANKNIFTY only), CRYPTO_SPOT, CRYPTO_PERPETUALS. Not supported: indices themselves (not tradable), dated crypto futures, single-stock Indian F&O | Agreed project scope |
| A10 | SHORT support | SHORT is **not supported** on options (no option writing: undefined risk) or crypto spot (no uncollateralized shorting). US equity SHORT requires a borrow cost | Conservative risk boundary |
| A11 | Options prices | For options, all prices (entry, stop, target) are **premiums**, and LONG means buying the contract | Keeps the price relationships of §7.1 well defined |
| A12 | Research / retrospective predictions | `EVENT_TIME` → `usage_class = RESEARCH_RETROSPECTIVE`. The prediction is valid as a research record, but a Risk Engine can never approve it | Never silently promoted to production |
| A13 | Leakage in research mode | Even `EVENT_TIME` requires event times, the feature snapshot, the model training cutoff and the calibration cutoff to be ≤ the decision time. Only *received/recorded* times may be later | Retrospective ≠ future-informed |
| A14 | NO_TRADE and risk | A NO_TRADE assessment is `NOT_APPLICABLE` (a justified third state), never `APPROVED` or `REJECTED` | Nothing to approve; rejection would conflate with model abstention |
| A16 | Cost currency | Read from the hashed Step 1 instrument specification (`price_currency`). Costs in another currency are rejected; no FX conversion. If the spec's currency is null, net R is `UNAVAILABLE` (`CURRENCY_UNVERIFIED`) | A currency is evidence, not a free string |
| A17 | Artifact time | Training-data cutoff, training completion and artifact availability are separate. Live-faithful requires every artifact (model, feature set, decision policy, calibrator, cost model) to be available or effective by the decision | A model that did not exist yet cannot have produced a live prediction |
| A18 | Calendar | Calendar must be allowed for the segment **and** equal the spec's `trading_calendar` (alias `XCME` = `XCME_GLOBEX`). `session_id` = `<calendar>_<exchange-local date>`. The Risk path re-verifies session bounds against the Step 1 calendar | No parallel calendar system; unverified sessions are never approvable |
| A19 | Bar alignment | `horizon_bars` counts **future canonical bars**, anchored at the session open (exchange) or UTC midnight (crypto). The first bar opens at the first boundary ≥ decision | Bar counts mean bars, not elapsed time |
| A20 | Exit fills | `exit_fill_model = LEVEL_FILLS_ROUND_TRIP_COSTS_V1` (§8.1) | Makes the conditional nature of expected net R machine-readable |
| A21 | State evidence | A state record carries its evidence and the prediction's expiry. It is self-checking and fully re-derived against the prediction before any risk use | A hand-made VALID record cannot be trusted |
| A22 | Limit evidence | Every `LimitCheck` carries typed evidence (numeric or flag). PASS/FAIL is derived from it and must match | Contradictory evidence can never approve |
| A15 | Override scope | Overrides are only for **soft** limits, named limit ids only, one instrument, ≤ 8 hours, and must be in force at assessment time. Hard controls can never be overridden | Hard safety controls are absolute |

---

## 3. `Prediction` fields

All fields are required in JSON (explicit `null` for absent optionals). Unknown fields are rejected.

| Field | Type | Rule |
|---|---|---|
| `contract_version` | str | `"1.0.0"` exactly |
| `prediction_id` | 64-hex | SHA-256 of the canonical JSON of every other field (derived; forging fails) |
| `usage_class` | enum | `LIVE_FAITHFUL` iff `inputs.availability_mode = AS_KNOWN_AT_DECISION`; `RESEARCH_RETROSPECTIVE` iff `EVENT_TIME` |
| `instrument_id`, `market`, `segment` | str | Step 1 identity v3. The prefix market and asset token must match the segment (§2 A9). For IN, the underlying must be NIFTY or BANKNIFTY |
| `direction` | enum | `LONG`, `SHORT`, `NO_TRADE` (§4) |
| `decision_timestamp_utc` | UTC datetime | The as-of instant. Everything the model used must be available by then |
| `inference_at_utc`, `created_at_utc` | UTC datetime | decision ≤ inference ≤ created; created − decision ≤ `max_decision_latency_seconds` |
| `expires_at_utc` | UTC datetime | created < expires ≤ horizon end |
| `max_decision_latency_seconds` | int > 0 | Staleness bound between decision and creation |
| `model` | `ModelProvenance` | `model_id`, `model_version`, `model_artifact_sha256`; `training_data_end_utc` ≤ `model_trained_at_utc` ≤ `model_available_at_utc`; `feature_set_id`/`version`/`available_at_utc`; `feature_snapshot_id` (64-hex); `decision_policy_id`/`version`/`effective_from_utc`; `label_definition_id`/`version` |
| `inputs` | `InputProvenance` | `availability_mode`; `data_snapshot_ids` (≥1, sorted, unique, 64-hex); `chart_snapshot_ids` (sorted, unique, may be empty); `max_input_event_time_utc`, `max_input_received_at_utc`, `feature_snapshot_as_of_utc`; Step 1 spec revision id, hash, `recorded_at` and **`instrument_specification`** (the Step 1 `spec_dict()` snapshot: must hash to `instrument_spec_hash` and contain `segment`, `asset_class`, `price_currency`, `trading_calendar`, `timezone`; read-only) |
| `horizon` | `HorizonSpec` | §5 |
| `direction_probabilities` | `DirectionProbabilities` | Always present (§6) |
| `model_reasons` | list of `ModelReasonCode` | Non-empty, unique. LONG/SHORT carry exactly `MODEL_DIRECTIONAL_EDGE`; NO_TRADE carries ≥1 `MODEL_NO_TRADE_*` and never `MODEL_DIRECTIONAL_EDGE` |
| `entry` | `EntryReference` or null | Required for LONG/SHORT, null for NO_TRADE |
| `levels` | `RiskLevels` or null | Required for LONG/SHORT, null for NO_TRADE |
| `costs` | `CostAssumptions` or null | Required for LONG/SHORT, null for NO_TRADE |
| `outcome_probabilities` | `OutcomeProbabilities` or null | Required for LONG/SHORT, null for NO_TRADE |
| `expected_horizon_exit_move_per_unit` | Decimal or null | Required for LONG/SHORT. The expected signed favourable move if the horizon ends first, in [−risk, +reward] |
| `expected_net_r` | `ExpectedNetR` | Derived (§8) |
| `uncertainty` | `Uncertainty` | §6.3 |
| `explanation` | str or null | Optional free text (≤ 500 chars). It never replaces reason codes |

---

## 4. Direction semantics

| Value | Meaning | Required payload |
|---|---|---|
| `LONG` | The model predicts a favourable **upward** move within the horizon and proposes buying the instrument (for options, buying the contract) | entry, levels (SL < E < TP), costs, outcome probabilities, exit move |
| `SHORT` | The model predicts a favourable **downward** move and proposes selling short. Not allowed on options or crypto spot | entry, levels (TP < E < SL), costs (US equity: incl. borrow), outcome probabilities, exit move |
| `NO_TRADE` | The model or policy proposes **no position** | entry, levels, costs, outcome probabilities and exit move must all be **null**. There is no executable setup |

A direction is a **prediction**, not permission. Only a `RiskAssessment` with status `APPROVED` for a `VALID`, `LIVE_FAITHFUL`, directional prediction makes it execution-eligible (`is_execution_eligible`). Approval can never turn NO_TRADE into LONG/SHORT.

---

## 5. Horizon (`HorizonSpec`)

| Field | Rule |
|---|---|
| `timeframe` | One of `1m`, `5m`, `15m`, `1h` (bar resolution) |
| `horizon_bars` | int in [1, 1440]; `horizon_bars × timeframe ≤ 24 h` |
| `start_utc` | Must equal `decision_timestamp_utc` |
| `alignment_anchor_utc` | Exchange: `session_open_utc`. Continuous: UTC midnight of the start date |
| `first_bar_open_utc` | The first canonical bar boundary `anchor + k × timeframe` (k ≥ 0) that is ≥ `start_utc` |
| `expected_end_utc` | Must equal `first_bar_open_utc + horizon_bars × timeframe` exactly |
| `session_kind` | `EXCHANGE_SESSION` for every non-crypto segment, `CONTINUOUS` for crypto (enforced per segment) |
| `boundary_policy` | `REJECT_BEYOND_SESSION_CLOSE` (only v1 value) |
| `calendar_id`, `calendar_version` | Step 1 calendar identity. Allowed per segment: US_EQUITY/US_OPTIONS `XNYS`/`XNAS`; US_FUTURES `XCME_GLOBEX`; IN_* `XNSE`; CRYPTO_* `CRYPTO_24_7`. Must equal the spec's `trading_calendar` (alias `XCME` = `XCME_GLOBEX`); an exchange-traded spec must name one |
| `session_id`, `session_open_utc`, `session_close_utc` | **Required** for `EXCHANGE_SESSION`, **null** for `CONTINUOUS`. `session_id` must be `<calendar_id>_<session date in the exchange's timezone>` |

**Bar alignment convention.** `horizon_bars` is a count of **future canonical bars**, not elapsed time:
- Bars are anchored at the session open for exchange sessions. For example, NSE 1h bars start at 09:15 IST.
- Bars are anchored at UTC midnight for crypto.
- The first counted bar is the first bar that opens at or after the decision.

Examples:
- A decision at 10:00:02 New York with 5m × 12 bars counts the bars 10:05 … 11:00, so it ends at **11:05**.
- A decision exactly at 10:00:00 counts from 10:00 and ends at 11:00.

Exchange session rules: `open ≤ start < close` and `expected_end ≤ close`. A horizon that would cross the close is rejected (`VALIDATION_SESSION_BOUNDARY_VIOLATION`). It is never shortened or carried overnight. Examples:
- A 5m × 2 horizon starting at 15:55 New York is rejected, because it would end at 16:05.
- 1 bar starting at 15:55:00 (or 15:54:59, whose next bar is 15:55) ends exactly at 16:00, the last valid bar, and is accepted.
- At 15:55:01 the next bar would open at the close, so it is rejected.

Crypto horizons may cross midnight (24/7) but never exceed 24 h.

**Prediction expiration** (`expires_at_utc`) is when the entry assumption stops being usable. It is at or before the horizon end. The horizon end is when the predicted outcome window closes.

---

## 6. Probabilities, confidence and uncertainty

### 6.1 Representation

- Each probability is a **Decimal string** in `[0, 1]` with at most **12 decimal places**.
- Each distribution must sum to **exactly 1**, with no tolerance. The producer quantizes and assigns any rounding remainder to one class before submitting.
- `NaN`, `±Infinity`, JSON floats and JSON constants are rejected.

| Distribution | Classes | Meaning | Present |
|---|---|---|---|
| `direction_probabilities` | `long`, `short`, `no_trade` | P(label class = c \| inputs) under `model.label_definition_id/version` | Always |
| `outcome_probabilities` | `target_first`, `stop_first`, `horizon_exit` | Conditional on entering the proposed trade at the expected entry: P(take-profit is reached first), P(stop-loss is reached first), P(neither before the horizon end) | LONG/SHORT only |

### 6.2 Calibration

Each distribution declares `kind`:
- **`CALIBRATED`**: requires a `calibration` reference: `method`, `method_version`, `artifact_sha256`, `fitted_on_dataset_id`, `fitted_until_utc` (≤ decision) and `available_at_utc` (≥ fitted_until; ≤ decision for live-faithful).
- **`UNCALIBRATED_SCORE`**: normalized model scores. These are **not** probabilities, and they must not carry a calibration reference.

Consequences of uncalibrated outcome scores:
- Expected net R is `UNAVAILABLE` (`UNCALIBRATED_OUTCOME_PROBABILITIES`). A score is never turned into an expected R.
- The Risk Engine contract rejects any prediction whose distributions are not all calibrated (`RISK_UNCALIBRATED_PROBABILITIES`).

### 6.3 Confidence and uncertainty

- **Confidence** (`Prediction.confidence`, derived, not serialized) is the selected direction's class probability. It is a probability only if `CALIBRATED`, and it is **never** a guarantee of profit.
- **Uncertainty** has one of two statuses:
  - **`COMPUTED`** (`NET_R_PREDICTIVE_INTERVAL`): `lower_net_r ≤ upper_net_r` (net R units), `coverage ∈ (0, 1)` (for example 0.8 = central 80% interval of the realized net R), `method`, `method_version`. Allowed only when expected net R is `AVAILABLE`.
  - **`UNAVAILABLE`**: exactly one `unavailable_reason`: `NOT_SUPPORTED_BY_MODEL`, `INSUFFICIENT_DATA`, `EXPECTED_NET_R_UNAVAILABLE` or `NO_TRADE_PREDICTION`. NO_TRADE must use `NO_TRADE_PREDICTION`.

---

## 7. Entry, levels and costs

### 7.1 Entry reference (not an order, not a fill)

`EntryReference` holds:
- `reference_price` (> 0)
- `reference_price_type` (`LAST_TRADE`, `MID_QUOTE`, `BID`, `ASK`, `BAR_CLOSE`, `MARK_PRICE`)
- `reference_observed_at_utc` (≤ decision) and `reference_received_at_utc` (≥ observed; ≤ decision when live-faithful)
- `max_reference_age_seconds` (decision − observed must not exceed it, else `DATA_STALE_REFERENCE_PRICE`)
- `expected_entry_price` (> 0): an **assumption**
- `entry_assumption` (`NEXT_BAR_OPEN`, `MARKETABLE_AT_DECISION`, `LIMIT_AT_EXPECTED_PRICE`)
- `entry_tolerance` (≥ 0; the price deviation beyond which the entry assumption is invalid)

There are no fill, order, quantity or broker fields anywhere in the contract.

`RiskLevels` holds `stop_loss_price` and `take_profit_price`, both > 0.
- **LONG:** `SL < E < TP`.
- **SHORT:** `TP < E < SL`.

Errors:
- `SL = E` gives `VALIDATION_INVALID_RISK_DISTANCE`.
- `TP = E` gives `VALIDATION_INVALID_REWARD_DISTANCE`.
- A stop or target on the wrong side gives `VALIDATION_INVALID_RISK_LEVELS`.
- v1 requires every price to be > 0. All v1 instruments, including option premiums, are positive-priced.

### 7.2 Cost assumptions

`CostAssumptions` holds `cost_model_id`, `cost_model_version`, `cost_model_effective_from_utc` (≤ decision for live-faithful), `price_currency` and round-trip costs **per one unit of quantity, in price units** (the contract multiplier is excluded and cancels in R). `null` means "not assessed".

| Cost | Sign | Applicable when |
|---|---|---|
| `spread_cost_per_unit` | ≥ 0 | always |
| `slippage_cost_per_unit` | ≥ 0 | always |
| `fee_cost_per_unit` (commission, exchange, regulatory) | ≥ 0 | always |
| `tax_cost_per_unit` (e.g. STT) | ≥ 0 | `IN_*` segments |
| `borrow_cost_per_unit` | ≥ 0 | SHORT on `US_EQUITY` |
| `funding_cost_per_unit` (expected over the horizon) | signed (negative = expected credit) | `CRYPTO_PERPETUALS` |

An applicable cost that is `null` makes expected net R `UNAVAILABLE` (`MISSING_COST_ASSUMPTION`). An inapplicable cost must be `null`; otherwise `VALIDATION_INVALID_COST`.

**Currency binding:**
- `costs.price_currency` must equal the hashed Step 1 specification's `price_currency`. Examples: USD for US instruments, INR for NIFTY/BANKNIFTY, the quote currency (e.g. USDT) for crypto.
- Any difference is `VALIDATION_COST_CURRENCY_MISMATCH`. **No FX conversion** is ever performed; that would need its own rate, source, timestamp and provenance contract.
- If the specification's `price_currency` is null, the currency cannot be verified. Expected net R is then `UNAVAILABLE` (`CURRENCY_UNVERIFIED`) and is never reported as verified.

---

## 8. Expected net R (exact formula)

Inputs:
- E = `expected_entry_price`
- SL = `stop_loss_price`
- TP = `take_profit_price`
- p_tp, p_sl, p_exit = `outcome_probabilities`
- m = `expected_horizon_exit_move_per_unit` (signed, favourable-positive, in [−risk, +reward])
- the applicable costs

| Quantity | LONG | SHORT |
|---|---|---|
| Initial risk per unit (R denominator) | `risk = E − SL` | `risk = SL − E` |
| Potential reward per unit | `reward = TP − E` | `reward = E − TP` |

```
reward_risk_ratio_gross = reward / risk
expected_gross_per_unit = p_tp × reward − p_sl × risk + p_exit × m
total_cost_per_unit     = Σ applicable costs (§7.2)
expected_net_per_unit   = expected_gross_per_unit − total_cost_per_unit
expected_gross_r        = expected_gross_per_unit / risk
expected_net_r          = expected_net_per_unit   / risk
```

- **Units.** Per-unit values are in the instrument's price currency per one unit of quantity. R values are unitless.
- **Precision.** Arithmetic is exact `Decimal` at 80 digits. Per-unit values are stored exactly as canonical decimal strings. The three ratios (`reward_risk_ratio_gross`, `expected_gross_r`, `expected_net_r`) are quantized to **1e-12, ROUND_HALF_EVEN**. Example: a ratio of 1/3 becomes `0.333333333333`.
- **Gross vs net.** `expected_gross_r` and `expected_net_r` are separate fields. The two are equal only when every applicable cost is zero. A gross value is never labelled net.
- **Unavailable.** `status = UNAVAILABLE` with `unavailable_reasons` (`NO_TRADE_PREDICTION`, `MISSING_COST_ASSUMPTION`, `UNCALIBRATED_OUTCOME_PROBABILITIES`) and **every expected field null**. Risk, reward and ratio stay populated for directional predictions. A partial or "best effort" net R is never returned.
- **Verification.** `Prediction` recomputes `expected_net_r` on construction (including `from_json`) and rejects any difference (`VALIDATION_NET_R_MISMATCH`).

### 8.1 Exit execution assumptions (`exit_fill_model = LEVEL_FILLS_ROUND_TRIP_COSTS_V1`)

Expected net R is a **model expectation conditional on fill assumptions**. It is **not** a guaranteed loss bound.

- **Exact level fills.** Target-first and stop-first outcomes are valued as exits **exactly at TP and SL**. A horizon exit is valued at `m`.
- **Slippage is a cost, not a fill price.** Exit slippage and the spread crossed on exit are included in the **round-trip** `slippage_cost_per_unit` and `spread_cost_per_unit`. They reduce the numerator; they do not move the exit price.
- **Gaps through the stop are not represented.** Gap-through-stop losses beyond the nominal stop (opening gaps, halts, limit moves, liquidations) are **not** modelled. A realized loss can exceed 1 R plus costs.
- **Conditional on entry and exit fills.** The metric assumes entry at `expected_entry_price` (§7.1) and exits per this model. Partial fills, rejected orders and queue position are outside it.
- **Other tail risks are excluded:** exchange outages, auto-deleveraging (perpetuals), early-exercise and assignment (options), and corporate actions inside the horizon.
- **Versioning.** The field is fixed to the v1 value. A gap-aware or slippage-distribution model would be a new contract version.

**Worked example — LONG** (US equity):
- Inputs: E = 100, SL = 99, TP = 102; p = (0.5, 0.3, 0.2); m = 0.4; costs: spread 0.02, slippage 0.01, fee 0.005.
- risk = 1, reward = 2, ratio = 2.
- gross = 0.5×2 − 0.3×1 + 0.2×0.4 = **0.78**
- cost = 0.035
- net = **0.745**
- gross R = 0.78, **net R = 0.745**

**Worked example — SHORT** (US equity):
- Inputs: E = 100, SL = 101, TP = 98; same p and m; costs as above plus borrow 0.003.
- risk = 101 − 100 = 1, reward = 100 − 98 = 2.
- gross = **0.78**
- cost = 0.038
- net = **0.742**
- gross R = 0.78, **net R = 0.742**
- The same edge as the LONG example, with the extra borrow cost. Without the borrow cost, net R is `UNAVAILABLE`.

---

## 9. No-lookahead and point-in-time rules

`d` = `decision_timestamp_utc`. Each violation raises a `DATA_*` code.

| Rule | Both modes | Additionally in `AS_KNOWN_AT_DECISION` (live-faithful) |
|---|---|---|
| `max_input_event_time_utc ≤ feature_snapshot_as_of_utc ≤ d` | ✔ | |
| `model.training_data_end_utc ≤ d` (data cutoff) | ✔ | |
| calibration `fitted_until_utc ≤ d` (data cutoff) | ✔ | |
| `model.model_available_at_utc ≤ d` (artifact existed) | | ✔ |
| `model.feature_set_available_at_utc ≤ d` | | ✔ |
| `model.decision_policy_effective_from_utc ≤ d` | | ✔ |
| calibration `available_at_utc ≤ d` | | ✔ |
| `costs.cost_model_effective_from_utc ≤ d` | | ✔ |
| `entry.reference_observed_at_utc ≤ d` and not older than `max_reference_age_seconds` | ✔ | |
| `d ≤ inference_at ≤ created_at`; `created_at − d ≤ max_decision_latency_seconds` | ✔ | |
| `max_input_received_at_utc ≤ d` | | ✔ |
| `instrument_spec_recorded_at_utc ≤ d` | | ✔ |
| `entry.reference_received_at_utc ≤ d` | | ✔ |

`EVENT_TIME` (Step 2 retrospective semantics) is labelled `RESEARCH_RETROSPECTIVE`.
- It may have later *received* times and later artifact availability. For example, a model trained later on data that ended before the decision can be replayed.
- It never has later *event* times or later training or calibration *data cutoffs*.
- It can never be risk-approved. AS_KNOWN and EVENT_TIME predictions should not be mixed in one dataset (Step 2 `require_single_availability_mode`).

---

## 10. Validity, expiry and invalidation (`PredictionStateRecord`)

`evaluate_prediction_state()` takes these explicit facts: `evaluated_at_utc` (≥ created), `latest_market_data_received_at_utc`, `max_market_data_age_seconds`, `instrument_tradable`, `last_price`, and optional explicit invalidations. It returns a **content-addressed** record.

The record holds:
- `state_id`
- `prediction_id`
- copies of `prediction_expires_at_utc` and `prediction_horizon_end_utc`
- **all of the evidence above**
- `state`, `expiry_reasons` and `invalidation_reasons`

Integrity (fail closed):
- **On construction**, the record re-derives everything its own fields determine:
  - Evaluated at or after the copied expiry means it **must** be `EXPIRED`, with exactly the right reasons.
  - Missing or stale data, untradable status and explicit invalidations **must** appear in `invalidation_reasons`. VALID is then impossible.
  - `state_id` must match the content.
- **`verify_prediction_state(record, prediction)`** re-runs the full derivation from the prediction and the recorded evidence, including session and price checks. It requires an exact match.
- A self-consistent forgery (for example, a later copied expiry, or VALID despite a price beyond the stop) is rejected there.
- `assess_prediction()` always calls it first.

| State | When | Reasons |
|---|---|---|
| `EXPIRED` | `evaluated_at ≥ expires_at`. **Checked first; takes precedence** | `EXPIRY_EXPIRATION_REACHED`, plus `EXPIRY_HORIZON_ELAPSED` once `evaluated_at ≥ horizon end` |
| `INVALIDATED` | Not expired and any condition below holds | One or more `InvalidationReasonCode` |
| `VALID` | Neither | none |

Invalidation conditions:

| Code | Condition |
|---|---|
| `INVALIDATION_MISSING_MARKET_DATA` | No market data timestamp, or (LONG/SHORT) no last price |
| `INVALIDATION_STALE_MARKET_DATA` | `evaluated_at − latest_received > max_market_data_age_seconds` |
| `INVALIDATION_INSTRUMENT_NOT_TRADABLE` | `instrument_tradable` is false (halt, suspension, delisting) |
| `INVALIDATION_SESSION_CLOSED` | Exchange session and `evaluated_at` is outside `[open, close)` |
| `INVALIDATION_PRICE_BEYOND_STOP` | LONG `last ≤ SL` / SHORT `last ≥ SL` |
| `INVALIDATION_PRICE_BEYOND_TARGET` | LONG `last ≥ TP` / SHORT `last ≤ TP` |
| `INVALIDATION_ENTRY_PRICE_DEVIATION` | `|last − E| > entry_tolerance` (entry assumption no longer valid) |
| `INVALIDATION_MANUAL`, `INVALIDATION_SUPERSEDED` | Supplied explicitly; the only codes that may be supplied by hand |

Market data received after `evaluated_at` raises `DATA_FUTURE_MARKET_DATA_OBSERVATION`.

These are four different things, never conflated:
- **Expired:** time ran out.
- **Invalidated:** facts changed before expiry.
- **Valid:** neither.
- **Risk-rejected:** a `RiskAssessment` decision, not a prediction state.

---

## 11. Reason-code families

All codes are stable string enums in `reason_codes.py`. **No value appears in two families** (tested).

| Family | Prefix | Used in |
|---|---|---|
| `ModelReasonCode` | `MODEL_` | `Prediction.model_reasons` |
| `ValidationFailureCode` | `VALIDATION_` | `PredictionContractError.code` (structural failures; raised, never stored) |
| `DataQualityCode` | `DATA_` | `PredictionContractError.code` (lookahead / staleness; raised) |
| `ExpiryReasonCode` / `InvalidationReasonCode` | `EXPIRY_` / `INVALIDATION_` | `PredictionStateRecord` |
| `RiskRejectionCode` | `RISK_` | `RiskAssessment.rejection_reasons` |

---

## 12. Risk Engine boundary (`RiskAssessment`)

`RiskAssessment` fields:
- `contract_version` and `risk_assessment_id` (content SHA-256)
- `prediction_id` and `instrument_id`
- **`prediction_state_id`**: the exact state record used
- Audited copies of the prediction facts it relied on: `prediction_direction`, `prediction_usage_class`, `prediction_expected_net_r_status`, `prediction_probabilities_calibrated`, `prediction_expires_at_utc`, `prediction_state`, `prediction_state_evaluated_at_utc` (≤ assessed)
- `max_state_age_seconds` (1–60, default 5)
- `session_verification` (`VERIFIED` / `NOT_REQUIRED` / `UNVERIFIED`)
- `risk_policy_id` / `risk_policy_version`
- `assessed_at_utc`
- `status`
- `rejection_reasons`
- `limit_checks`: `LimitCheck` = limit id, kind, version, PASS/FAIL, `is_hard_control`, observed and limit values
- `overrides`
- `notes`

**Status:**
- **`APPROVED`.** Only if *all* of the following hold, and the record re-checks them itself:
  - the prediction is LONG/SHORT, `LIVE_FAITHFUL` and `VALID`
  - `assessed_at < prediction.expires_at`, even if the state says VALID
  - the state was evaluated no more than `max_state_age_seconds` before the assessment
  - `session_verification` is `VERIFIED` (exchange markets) or `NOT_REQUIRED` (crypto)
  - its probabilities are calibrated and its expected net R is `AVAILABLE`
  - every hard control (`KILL_SWITCH`, `DAILY_LOSS_LIMIT`, `POSITION_LIMIT`, `EXPOSURE_LIMIT`, `RESTRICTED_INSTRUMENT`) was evaluated **and** passed
  - every failed soft check (`MIN_EXPECTED_NET_R`, `MAX_SPREAD`, `TRADING_WINDOW`, `MAX_TRADES_PER_DAY`) is covered by an in-force override
  - there are no rejection reasons
- **`REJECTED`.** One or more `RISK_*` reasons:
  - Expired at the assessment time: `RISK_PREDICTION_EXPIRED`.
  - Stale state: `RISK_STALE_PREDICTION_STATE`.
  - Session not calendar-verified: `RISK_SESSION_UNVERIFIED`.
  - A hard control not evaluated: `RISK_POLICY_REJECTION` (fail closed).
- **`NOT_APPLICABLE`.** NO_TRADE only. It carries no reasons or overrides, and is never executable.

Mandatory boundaries, and how they are enforced:
1. **Rejection never rewrites the prediction.** The prediction is frozen and separate. A test checks that its JSON is byte-identical after rejection.
2. **LONG/SHORT ≠ approved.** `is_execution_eligible()` requires an APPROVED assessment that `verify_risk_assessment()` confirms against the exact prediction and state.
3. **NO_TRADE never becomes executable.** Forging APPROVED (even with every other precondition faked) is rejected.
4. **Independently auditable.** The record is content-addressed, carries machine-readable reasons, and is recomputable by `verify_risk_assessment()`.
5. **Validity ≠ approval.** These are separate records. Approval requires a VALID state evaluated at or before the assessment.
6. **The model cannot bypass limits.** Hard controls must be present and PASS. The model has no field that affects them.
7. **Overrides** (`RiskOverride`) must be:
   - explicitly authorized: `authorized_by`, `authorization_reference`, `justification`
   - auditable: part of the content id
   - scoped: one `instrument_id` and named `overridden_limit_ids`, with no wildcards
   - time-limited: `expires_at − granted_at ≤ 8 h`, and in force at `assessed_at_utc`
8. **No override of hard controls.** Any override that names a hard-control check is rejected (`VALIDATION_HARD_CONTROL_OVERRIDE`), and a hard control cannot be relabelled as soft.

9. **The assessment is bound to the exact state.** `verify_risk_assessment(assessment, prediction, state, calendar=…)` re-verifies the state record, requires `prediction_state_id == state.state_id`, recomputes every copied fact and the session verification, and re-derives the status. `is_execution_eligible()` uses it and also requires `assessed_at < expires_at`.

### 12.1 Limit-check evidence and comparison semantics

`LimitCheck` holds `limit_id`, `limit_kind`, `limit_version`, `result`, `is_hard_control`, `observed_value`, `limit_value` and `observed_flag`.
- **Semantics come from `limit_kind` only.** A custom `limit_id` can never change hardness or comparison.
- **The result is derived from the evidence**, and a stored result that contradicts it is rejected (`VALIDATION_INCONSISTENT_LIMIT_EVIDENCE`) on construction and on JSON deserialization.
- **Missing evidence is an error, never a PASS** (`VALIDATION_MISSING_LIMIT_EVIDENCE`).

| `limit_kind` | Hard | Evidence | PASS iff | `observed_value` / `observed_flag` means |
|---|---|---|---|---|
| `DAILY_LOSS_LIMIT` | ✔ | numeric ≥ 0 | `observed < limit` | today's realized + open loss (positive = loss) |
| `POSITION_LIMIT` | ✔ | whole number ≥ 0 | `observed ≤ limit` | open positions **including** the proposed one |
| `EXPOSURE_LIMIT` | ✔ | numeric ≥ 0 | `observed ≤ limit` | gross exposure **including** the proposed trade |
| `KILL_SWITCH` | ✔ | flag | flag is `false` | kill switch engaged |
| `RESTRICTED_INSTRUMENT` | ✔ | flag | flag is `false` | instrument is restricted |
| `MIN_EXPECTED_NET_R` | | numeric (signed) | `observed ≥ limit` | must equal the prediction's `expected_net_r` (checked) |
| `MAX_SPREAD` | | numeric ≥ 0 | `observed ≤ limit` | current quoted spread (price units) |
| `MAX_TRADES_PER_DAY` | | whole number ≥ 0 | `observed ≤ limit` | trades today **including** the proposed one |
| `TRADING_WINDOW` | | flag | flag is `true` | assessment time is inside the permitted window |

Numeric kinds require both values and no flag. Flag kinds require the flag and no values.

### 12.2 Session verification

`verify_session_with_calendar(prediction, calendar)` returns:
- **`NOT_REQUIRED`** for continuous (crypto) horizons.
- **`VERIFIED`** only when all of these hold:
  - the supplied Step 1 calendar has the same (aliased) `calendar_id` and `calendar_version`
  - its `session_bounds(trade_date_for(session_open), require_verified=True)` equals the horizon's open and close exactly
  - `session_id` matches that date
- **`UNVERIFIED`** otherwise: no calendar, a wrong or unverified calendar (e.g. partially verified XNAS), or different bounds. An `UNVERIFIED` session is never approvable.

This is a contract only. There is no live risk enforcement, sizing, order, or execution.

---

## 13. Serialization rules

- **Constructors** validate every field and **do not coerce**:
  - Decimals must be `Decimal` (floats, ints and strings are rejected).
  - Datetimes must be timezone-aware (normalized to UTC).
  - Ints must be `int` (not `bool`).
  - Enums must be members or their exact string value.
  - Lists/tuples may be lists or tuples, but a string is **never** split into a tuple.
- **`from_dict` / `from_json`:**
  - The exact key set is required: unknown keys give `VALIDATION_UNKNOWN_FIELD`, missing keys give `VALIDATION_MISSING_FIELD`.
  - Decimals must be plain decimal **strings** (`^-?(0|[1-9]\d*)(\.\d+)?$`). No exponents, no `NaN`/`Infinity`.
  - Timestamps must be ISO-8601 **with an offset**.
  - JSON floats, `NaN` and `Infinity` constants are rejected by the parser.
  - Malformed JSON gives `VALIDATION_MALFORMED_PAYLOAD`.
  - Every invariant runs again after deserialization, so JSON cannot bypass the constructor.
- **`to_json`:** Step 2 `canonical_json` (sorted keys, compact, ASCII, float-rejecting). Decimals use Step 1 `normalize_decimal_str` (value-exact: `"100.00"` → `"100"`). Timestamps are UTC ISO-8601. The round trip is exact (`from_json(to_json(x)) == x`).
- **Immutability:** every record is a frozen dataclass, sequences are tuples, and `to_dict()` returns independent copies.
- **Identity:** `prediction_id`, `state_id` and `risk_assessment_id` are SHA-256 of the canonical JSON without the id field.
- **Spec snapshot:** `instrument_specification` accepts only JSON scalars (string, int, bool, null; no floats). It is stored read-only and serialized with sorted keys.

---

## 14. Examples (generated by the implementation; synthetic test data)

### 14.1 LONG prediction (AAPL, 5m × 12 future bars, worked example of §8)

```json
{
  "contract_version": "1.0.0",
  "costs": {
    "borrow_cost_per_unit": null,
    "cost_model_effective_from_utc": "2025-12-01T00:00:00+00:00",
    "cost_model_id": "us_equity_costs",
    "cost_model_version": "1.0.0",
    "fee_cost_per_unit": "0.005",
    "funding_cost_per_unit": null,
    "price_currency": "USD",
    "slippage_cost_per_unit": "0.01",
    "spread_cost_per_unit": "0.02",
    "tax_cost_per_unit": null
  },
  "created_at_utc": "2026-01-05T15:00:05+00:00",
  "decision_timestamp_utc": "2026-01-05T15:00:02+00:00",
  "direction": "LONG",
  "direction_probabilities": {
    "calibration": {
      "artifact_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "available_at_utc": "2026-01-01T00:00:00+00:00",
      "fitted_on_dataset_id": "calibration_ds_v1",
      "fitted_until_utc": "2025-12-31T00:00:00+00:00",
      "method": "ISOTONIC",
      "method_version": "1.0.0"
    },
    "kind": "CALIBRATED",
    "long": "0.6",
    "no_trade": "0.3",
    "short": "0.1"
  },
  "entry": {
    "entry_assumption": "NEXT_BAR_OPEN",
    "entry_tolerance": "0.1",
    "expected_entry_price": "100",
    "max_reference_age_seconds": 60,
    "reference_observed_at_utc": "2026-01-05T15:00:00+00:00",
    "reference_price": "100",
    "reference_price_type": "LAST_TRADE",
    "reference_received_at_utc": "2026-01-05T15:00:01+00:00"
  },
  "expected_horizon_exit_move_per_unit": "0.4",
  "expected_net_r": {
    "exit_fill_model": "LEVEL_FILLS_ROUND_TRIP_COSTS_V1",
    "expected_gross_per_unit": "0.78",
    "expected_gross_r": "0.78",
    "expected_net_per_unit": "0.745",
    "expected_net_r": "0.745",
    "initial_risk_per_unit": "1",
    "potential_reward_per_unit": "2",
    "reward_risk_ratio_gross": "2",
    "status": "AVAILABLE",
    "total_cost_per_unit": "0.035",
    "unavailable_reasons": []
  },
  "expires_at_utc": "2026-01-05T15:05:02+00:00",
  "explanation": "sweep + CHoCH confluence",
  "horizon": {
    "alignment_anchor_utc": "2026-01-05T14:30:00+00:00",
    "boundary_policy": "REJECT_BEYOND_SESSION_CLOSE",
    "calendar_id": "XNYS",
    "calendar_version": "2026.1",
    "expected_end_utc": "2026-01-05T16:05:00+00:00",
    "first_bar_open_utc": "2026-01-05T15:05:00+00:00",
    "horizon_bars": 12,
    "session_close_utc": "2026-01-05T21:00:00+00:00",
    "session_id": "XNYS_2026-01-05",
    "session_kind": "EXCHANGE_SESSION",
    "session_open_utc": "2026-01-05T14:30:00+00:00",
    "start_utc": "2026-01-05T15:00:02+00:00",
    "timeframe": "5m"
  },
  "inference_at_utc": "2026-01-05T15:00:04+00:00",
  "inputs": {
    "availability_mode": "AS_KNOWN_AT_DECISION",
    "chart_snapshot_ids": [],
    "data_snapshot_ids": [
      "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
    ],
    "feature_snapshot_as_of_utc": "2026-01-05T15:00:02+00:00",
    "instrument_spec_hash": "24421ba2ae1c9664dbcf6be2db10b6747dd629394c6c25f2a7ded313e8e1ccc3",
    "instrument_spec_recorded_at_utc": "2025-12-31T00:00:00+00:00",
    "instrument_spec_version_id": 1,
    "instrument_specification": {
      "asset_class": "EQUITY",
      "base_currency": null,
      "clearing_exchange": null,
      "contract_multiplier": "1",
      "contract_type": "EQUITY",
      "deliverable_shares": null,
      "deliverable_type": null,
      "exchange": "NASDAQ",
      "exchange_mic": "XNAS",
      "exercise_style": null,
      "expiry_date": null,
      "is_inverse": false,
      "last_trade_date": null,
      "lot_size": "1",
      "margin_type": "STANDARD",
      "minimum_order_quantity": "1",
      "option_right": null,
      "price_currency": "USD",
      "quantity_step": "1",
      "quote_currency": null,
      "segment": "US_EQUITY",
      "settlement_currency": null,
      "settlement_type": "PHYSICAL",
      "strike_price": null,
      "tick_size": "0.01",
      "timezone": "America/New_York",
      "trading_calendar": "XNYS",
      "underlying_instrument_id": null,
      "venue": "NASDAQ"
    },
    "max_input_event_time_utc": "2026-01-05T15:00:00+00:00",
    "max_input_received_at_utc": "2026-01-05T15:00:01+00:00"
  },
  "instrument_id": "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c",
  "levels": {
    "stop_loss_price": "99",
    "take_profit_price": "102"
  },
  "market": "US",
  "max_decision_latency_seconds": 30,
  "model": {
    "decision_policy_effective_from_utc": "2025-12-01T00:00:00+00:00",
    "decision_policy_id": "policy_v1",
    "decision_policy_version": "1.0.0",
    "feature_set_available_at_utc": "2025-12-01T00:00:00+00:00",
    "feature_set_id": "intraday_fs",
    "feature_set_version": "1",
    "feature_snapshot_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "label_definition_id": "tb_label",
    "label_definition_version": "1.0.0",
    "model_artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "model_available_at_utc": "2026-01-02T00:00:00+00:00",
    "model_id": "gbm_direction",
    "model_trained_at_utc": "2026-01-01T00:00:00+00:00",
    "model_version": "1.0.0",
    "training_data_end_utc": "2025-12-31T00:00:00+00:00"
  },
  "model_reasons": [
    "MODEL_DIRECTIONAL_EDGE"
  ],
  "outcome_probabilities": {
    "calibration": {
      "artifact_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "available_at_utc": "2026-01-01T00:00:00+00:00",
      "fitted_on_dataset_id": "calibration_ds_v1",
      "fitted_until_utc": "2025-12-31T00:00:00+00:00",
      "method": "ISOTONIC",
      "method_version": "1.0.0"
    },
    "horizon_exit": "0.2",
    "kind": "CALIBRATED",
    "stop_first": "0.3",
    "target_first": "0.5"
  },
  "prediction_id": "6b7e4513de9ee5096e443662acd7b9574ecbd882b79fb0862aab58f7df416a07",
  "segment": "US_EQUITY",
  "uncertainty": {
    "coverage": "0.8",
    "kind": "NET_R_PREDICTIVE_INTERVAL",
    "lower_net_r": "-0.5",
    "method": "split_conformal",
    "method_version": "1.0.0",
    "status": "COMPUTED",
    "unavailable_reason": null,
    "upper_net_r": "1.8"
  },
  "usage_class": "LIVE_FAITHFUL"
}
```

### 14.2 NO_TRADE prediction (directional fields only; other fields as in 14.1)

```json
{
  "costs": null,
  "direction": "NO_TRADE",
  "direction_probabilities": {
    "calibration": {
      "artifact_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "available_at_utc": "2026-01-01T00:00:00+00:00",
      "fitted_on_dataset_id": "calibration_ds_v1",
      "fitted_until_utc": "2025-12-31T00:00:00+00:00",
      "method": "ISOTONIC",
      "method_version": "1.0.0"
    },
    "kind": "CALIBRATED",
    "long": "0.35",
    "no_trade": "0.4",
    "short": "0.25"
  },
  "entry": null,
  "expected_horizon_exit_move_per_unit": null,
  "expected_net_r": {
    "exit_fill_model": "LEVEL_FILLS_ROUND_TRIP_COSTS_V1",
    "expected_gross_per_unit": null,
    "expected_gross_r": null,
    "expected_net_per_unit": null,
    "expected_net_r": null,
    "initial_risk_per_unit": null,
    "potential_reward_per_unit": null,
    "reward_risk_ratio_gross": null,
    "status": "UNAVAILABLE",
    "total_cost_per_unit": null,
    "unavailable_reasons": [
      "NO_TRADE_PREDICTION"
    ]
  },
  "levels": null,
  "model_reasons": [
    "MODEL_NO_TRADE_LOW_EDGE"
  ],
  "outcome_probabilities": null,
  "uncertainty": {
    "coverage": null,
    "kind": null,
    "lower_net_r": null,
    "method": null,
    "method_version": null,
    "status": "UNAVAILABLE",
    "unavailable_reason": "NO_TRADE_PREDICTION",
    "upper_net_r": null
  }
}
```

### 14.3 Prediction state record (content-addressed, with its evidence)

```json
{
  "evaluated_at_utc": "2026-01-05T15:00:12+00:00",
  "expiry_reasons": [],
  "explicit_invalidations": [],
  "instrument_tradable": true,
  "invalidation_reasons": [],
  "last_price": "100.02",
  "latest_market_data_received_at_utc": "2026-01-05T15:00:11+00:00",
  "max_market_data_age_seconds": 30,
  "prediction_expires_at_utc": "2026-01-05T15:05:02+00:00",
  "prediction_horizon_end_utc": "2026-01-05T16:05:00+00:00",
  "prediction_id": "6b7e4513de9ee5096e443662acd7b9574ecbd882b79fb0862aab58f7df416a07",
  "state": "VALID",
  "state_id": "7ded4f7b974aadafcb38c46063184c404399c23fdccebe322ce424e1cc006f1e"
}
```

### 14.4 Risk assessment (APPROVED; bound to the state id; session calendar-verified; all hard controls passed)

```json
{
  "assessed_at_utc": "2026-01-05T15:00:12+00:00",
  "contract_version": "1.0.0",
  "instrument_id": "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c",
  "limit_checks": [
    {
      "is_hard_control": true,
      "limit_id": "kill_switch",
      "limit_kind": "KILL_SWITCH",
      "limit_value": null,
      "limit_version": "1",
      "observed_flag": false,
      "observed_value": null,
      "result": "PASS"
    },
    {
      "is_hard_control": true,
      "limit_id": "daily_loss",
      "limit_kind": "DAILY_LOSS_LIMIT",
      "limit_value": "150",
      "limit_version": "1",
      "observed_flag": null,
      "observed_value": "120",
      "result": "PASS"
    },
    {
      "is_hard_control": true,
      "limit_id": "position",
      "limit_kind": "POSITION_LIMIT",
      "limit_value": "3",
      "limit_version": "1",
      "observed_flag": null,
      "observed_value": "1",
      "result": "PASS"
    },
    {
      "is_hard_control": true,
      "limit_id": "exposure",
      "limit_kind": "EXPOSURE_LIMIT",
      "limit_value": "5000",
      "limit_version": "1",
      "observed_flag": null,
      "observed_value": "2000",
      "result": "PASS"
    },
    {
      "is_hard_control": true,
      "limit_id": "restricted",
      "limit_kind": "RESTRICTED_INSTRUMENT",
      "limit_value": null,
      "limit_version": "1",
      "observed_flag": false,
      "observed_value": null,
      "result": "PASS"
    }
  ],
  "max_state_age_seconds": 5,
  "notes": null,
  "overrides": [],
  "prediction_direction": "LONG",
  "prediction_expected_net_r_status": "AVAILABLE",
  "prediction_expires_at_utc": "2026-01-05T15:05:02+00:00",
  "prediction_id": "6b7e4513de9ee5096e443662acd7b9574ecbd882b79fb0862aab58f7df416a07",
  "prediction_probabilities_calibrated": true,
  "prediction_state": "VALID",
  "prediction_state_evaluated_at_utc": "2026-01-05T15:00:12+00:00",
  "prediction_state_id": "7ded4f7b974aadafcb38c46063184c404399c23fdccebe322ce424e1cc006f1e",
  "prediction_usage_class": "LIVE_FAITHFUL",
  "rejection_reasons": [],
  "risk_assessment_id": "90ca200e16fad8f011d9effffda27b2e5a632407c86914e885d9228b63cecdb1",
  "risk_policy_id": "us_paper_risk",
  "risk_policy_version": "1.0.0",
  "session_verification": "VERIFIED",
  "status": "APPROVED"
}
```

---

## 15. Module map (`ml_data/predictions/`)

| Module | Contents |
|---|---|
| `prediction.py` | `PREDICTION_CONTRACT_VERSION`, enums, `ModelProvenance`, `InputProvenance`, `HorizonSpec`, `EntryReference`, `CostAssumptions`, `RiskLevels`, `CalibrationRef`, `DirectionProbabilities`, `OutcomeProbabilities`, `Uncertainty`, `ExpectedNetR`, `compute_expected_net_r`, `applicable_costs`, `check_instrument_scope`, `Prediction` (`create`, `to_json`, `from_json`, `confidence`) |
| `state.py` | `PredictionState`, `PredictionStateRecord` (content-addressed, with evidence), `evaluate_prediction_state`, `verify_prediction_state` |
| `risk_assessment.py` | `RISK_ASSESSMENT_CONTRACT_VERSION`, `RiskStatus`, `LimitKind`, `HARD_CONTROLS`, `LimitCheck`, `RiskOverride`, `RiskAssessment`, `SessionVerification`, `derive_check_result`, `verify_session_with_calendar`, `assess_prediction`, `verify_risk_assessment`, `is_execution_eligible` |
| `reason_codes.py` | The five reason-code families |
| `_records.py` | Strict record base: field kinds, no-coercion validation, strict JSON parsing, canonical serialization, content ids |
| `exceptions.py` | `PredictionContractError` / `RiskAssessmentContractError` (with `.code`) |

Standard library only. No new dependency.

---

## 16. Known limitations (v1.0.0)

- **Session verification is a separate step.** A `Prediction` validates calendar identity (segment, spec `trading_calendar`, `session_id` format) but cannot itself call the calendar. Exact session bounds are verified against the Step 1 calendar in the risk path (`verify_session_with_calendar`), so an unverified session can never be approved.
- **Calendar alias.** Step 1 instrument specs name the CME calendar `XCME`, while the Step 1 calendar adapter is `XCME_GLOBEX`. v1 declares them equivalent (`CALENDAR_ALIASES`). This is reported as a Step 1 naming inconsistency, and Step 1 was not changed.
- **XNAS is not yet verified.** XNAS is `PARTIALLY_VERIFIED` in Step 1, so XNAS-calendar sessions verify as `UNVERIFIED` until Step 1 verifies it.
- **Instrument records.** The contract checks the identity format, segment scope and NIFTY/BANKNIFTY prefix. It does not look up the instrument in the `InstrumentRegistry`, which is Step 1's registry boundary.
- **Single uncertainty kind.** Only `NET_R_PREDICTIVE_INTERVAL` exists. Other kinds need a new contract version.
- **Exit-move responsibility.** `expected_horizon_exit_move_per_unit` is a model output. The contract only bounds it to `[−risk, +reward]`.
