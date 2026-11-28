"""Phase 0 Step 3: Prediction Contract v1.0.0 and risk-assessment boundary tests (contract only)."""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from ml_data.predictions import (
    PREDICTION_CONTRACT_VERSION,
    CalibrationRef,
    CheckResult,
    CostAssumptions,
    DataQualityCode,
    Direction,
    DirectionProbabilities,
    EntryAssumption,
    EntryReference,
    ExpiryReasonCode,
    HorizonSpec,
    InputProvenance,
    InvalidationReasonCode,
    LimitCheck,
    LimitKind,
    ModelProvenance,
    ModelReasonCode,
    NetRStatus,
    NetRUnavailableReason,
    OutcomeProbabilities,
    Prediction,
    PredictionContractError,
    PredictionState,
    PredictionStateRecord,
    ProbabilityKind,
    ReferencePriceType,
    RiskAssessment,
    RiskAssessmentContractError,
    RiskLevels,
    RiskOverride,
    RiskRejectionCode,
    RiskStatus,
    SessionKind,
    Uncertainty,
    UncertaintyKind,
    UncertaintyStatus,
    UncertaintyUnavailableReason,
    UsageClass,
    ValidationFailureCode,
    assess_prediction,
    compute_expected_net_r,
    evaluate_prediction_state,
    is_execution_eligible,
    verify_risk_assessment,
)
from ml_data.calendars.us_equity import USEquityCalendarAdapter
from ml_data.instruments.identity import compute_spec_hash
from ml_data.predictions import reason_codes
from ml_data.tests.fixtures import build_all_fixtures

UTC = timezone.utc
V, DQ = ValidationFailureCode, DataQualityCode

AAPL = "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c"
BTC_PERP = "CRYPTO:BINANCE:PERPETUAL:BTCUSDT:BTC/USDT:USDT:LINEAR#fb0ae69540c587ab092116df95df0c1f"
NIFTY_FUT = "IN:NFO:FUTURE:NIFTY:20261231:NIFTY26DECFUT#d1ba65b97e3e7a6fa81c94ff392bd20c"
AAPL_CALL = "US:OPRA:OPTION:AAPL:20261218:220:CALL:AAPL261218C00220000#4c7a77f45f205fb0e5c8b9af7c4b7580"

DEC = datetime(2026, 1, 5, 15, 0, 2, tzinfo=UTC)          # 10:00:02 New York
CAL = CalibrationRef("ISOTONIC", "1.0.0", "c" * 64, "calibration_ds_v1", datetime(2025, 12, 31, tzinfo=UTC),
                     datetime(2026, 1, 1, tzinfo=UTC))
MODEL = ModelProvenance("gbm_direction", "1.0.0", "a" * 64, datetime(2025, 12, 31, tzinfo=UTC),
                        datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC), "intraday_fs", "1",
                        datetime(2025, 12, 1, tzinfo=UTC), "b" * 64, "policy_v1", "1.0.0",
                        datetime(2025, 12, 1, tzinfo=UTC), "tb_label", "1.0.0")
FIXTURES = build_all_fixtures()
SPECS = {k: FIXTURES[k].spec_dict() for k in ("aapl", "nifty_fut", "btc_perp", "aapl_call", "nifty_ce", "btc_spot", "es_fut")}
XNYS = USEquityCalendarAdapter(calendar_id="XNYS")


def spec_inputs(key: str, **over) -> dict:
    spec = SPECS[key]
    return dict(instrument_specification=spec, instrument_spec_hash=compute_spec_hash(spec), **over)


def code(exc_info) -> str:
    return exc_info.value.code


def inputs(decision=DEC, **over) -> InputProvenance:
    base = dict(availability_mode="AS_KNOWN_AT_DECISION", data_snapshot_ids=("d" * 64,), chart_snapshot_ids=(),
                max_input_event_time_utc=decision - timedelta(seconds=2),
                max_input_received_at_utc=decision - timedelta(seconds=1), feature_snapshot_as_of_utc=decision,
                instrument_spec_version_id=1, instrument_spec_recorded_at_utc=datetime(2025, 12, 31, tzinfo=UTC),
                **spec_inputs("aapl"))
    base.update(over)
    return InputProvenance(**base)


def us_horizon(start=DEC, bars=12, **over) -> HorizonSpec:
    kw = dict(timeframe="5m", horizon_bars=bars, start_utc=start, session_kind=SessionKind.EXCHANGE_SESSION,
              calendar_id="XNYS", calendar_version="2026.1", session_id="XNYS_2026-01-05",
              session_open_utc=datetime(2026, 1, 5, 14, 30, tzinfo=UTC), session_close_utc=datetime(2026, 1, 5, 21, tzinfo=UTC))
    kw.update(over)
    return HorizonSpec.build(**kw)


def entry(decision=DEC, price="100", **over) -> EntryReference:
    base = dict(reference_price=D(price), reference_price_type=ReferencePriceType.LAST_TRADE,
                reference_observed_at_utc=decision - timedelta(seconds=2),
                reference_received_at_utc=decision - timedelta(seconds=1), max_reference_age_seconds=60,
                expected_entry_price=D(price), entry_assumption=EntryAssumption.NEXT_BAR_OPEN, entry_tolerance=D("0.10"))
    base.update(over)
    return EntryReference(**base)


def costs(**over) -> CostAssumptions:
    base = dict(cost_model_id="us_equity_costs", cost_model_version="1.0.0",
                cost_model_effective_from_utc=datetime(2025, 12, 1, tzinfo=UTC), price_currency="USD",
                spread_cost_per_unit=D("0.02"), slippage_cost_per_unit=D("0.01"), fee_cost_per_unit=D("0.005"),
                tax_cost_per_unit=None, borrow_cost_per_unit=None, funding_cost_per_unit=None)
    base.update(over)
    return CostAssumptions(**base)


def dprobs(l="0.6", s="0.1", n="0.3", kind=ProbabilityKind.CALIBRATED, cal=CAL) -> DirectionProbabilities:
    return DirectionProbabilities(D(l), D(s), D(n), kind, cal)


def oprobs(tp="0.5", sl="0.3", ex="0.2", kind=ProbabilityKind.CALIBRATED, cal=CAL) -> OutcomeProbabilities:
    return OutcomeProbabilities(D(tp), D(sl), D(ex), kind, cal)


NO_UNC = Uncertainty.unavailable(UncertaintyUnavailableReason.EXPECTED_NET_R_UNAVAILABLE)
UNC = Uncertainty(UncertaintyStatus.COMPUTED, UncertaintyKind.NET_R_PREDICTIVE_INTERVAL, D("-0.5"), D("1.8"),
                  D("0.8"), "split_conformal", "1.0.0", None)


def long_kw(**over):
    kw = dict(instrument_id=AAPL, market="US", segment="US_EQUITY", direction=Direction.LONG,
              decision_timestamp_utc=DEC, inference_at_utc=DEC + timedelta(seconds=2),
              created_at_utc=DEC + timedelta(seconds=3), expires_at_utc=DEC + timedelta(minutes=5),
              max_decision_latency_seconds=30, model=MODEL, inputs=inputs(), horizon=us_horizon(),
              direction_probabilities=dprobs(), model_reasons=(ModelReasonCode.DIRECTIONAL_EDGE,), entry=entry(),
              levels=RiskLevels(D("99"), D("102")), costs=costs(), outcome_probabilities=oprobs(),
              expected_horizon_exit_move_per_unit=D("0.4"), uncertainty=UNC, explanation="sweep + CHoCH confluence")
    kw.update(over)
    return kw


def short_kw(**over):
    kw = long_kw(direction=Direction.SHORT, direction_probabilities=dprobs("0.1", "0.6", "0.3"),
                 levels=RiskLevels(D("101"), D("98")), costs=costs(borrow_cost_per_unit=D("0.003")))
    kw.update(over)
    return kw


def no_trade_kw(**over):
    kw = long_kw(direction=Direction.NO_TRADE, direction_probabilities=dprobs("0.35", "0.25", "0.4"),
                 model_reasons=(ModelReasonCode.NO_TRADE_LOW_EDGE,), entry=None, levels=None, costs=None,
                 outcome_probabilities=None, expected_horizon_exit_move_per_unit=None,
                 uncertainty=Uncertainty.unavailable(UncertaintyUnavailableReason.NO_TRADE_PREDICTION))
    kw.update(over)
    return kw


def make(kw) -> Prediction:
    return Prediction.create(**kw)


def raw(p: Prediction, **changes) -> dict:
    """The prediction's JSON dict with changes applied (for from_dict / tamper tests)."""
    d = json.loads(p.to_json())
    d.update(changes)
    return d


# ================================================================================================ core contract

def test_valid_long_prediction_and_worked_example() -> None:
    p = make(long_kw())
    n = p.expected_net_r
    assert p.contract_version == PREDICTION_CONTRACT_VERSION == "1.0.0" and p.usage_class is UsageClass.LIVE_FAITHFUL
    assert (n.initial_risk_per_unit, n.potential_reward_per_unit, n.reward_risk_ratio_gross) == (D("1"), D("2"), D("2.000000000000"))
    assert (n.expected_gross_per_unit, n.total_cost_per_unit, n.expected_net_per_unit) == (D("0.78"), D("0.035"), D("0.745"))
    assert (n.expected_gross_r, n.expected_net_r, n.status) == (D("0.78"), D("0.745"), NetRStatus.AVAILABLE)
    assert p.confidence == D("0.6") and p.is_directional and p.is_live_faithful


def test_valid_short_prediction_mirrors_long() -> None:
    p = make(short_kw())
    n = p.expected_net_r
    assert (n.initial_risk_per_unit, n.potential_reward_per_unit) == (D("1"), D("2"))
    assert (n.expected_gross_per_unit, n.total_cost_per_unit, n.expected_net_r) == (D("0.78"), D("0.038"), D("0.742"))


def test_valid_no_trade_has_no_executable_setup() -> None:
    p = make(no_trade_kw())
    assert (p.entry, p.levels, p.costs, p.outcome_probabilities, p.expected_horizon_exit_move_per_unit) == (None,) * 5
    assert p.expected_net_r.status is NetRStatus.UNAVAILABLE
    assert p.expected_net_r.unavailable_reasons == (NetRUnavailableReason.NO_TRADE_PREDICTION,)
    with pytest.raises(PredictionContractError) as e:
        make(no_trade_kw(levels=RiskLevels(D("99"), D("102"))))
    assert code(e) == V.NO_TRADE_HAS_DIRECTIONAL_FIELDS.value
    with pytest.raises(PredictionContractError) as e:
        make(no_trade_kw(model_reasons=(ModelReasonCode.DIRECTIONAL_EDGE,)))
    assert code(e) == V.INVALID_REASON_CODES.value
    assert make(no_trade_kw(direction_probabilities=dprobs("0.7", "0.1", "0.2"))).direction is Direction.NO_TRADE


def test_other_supported_markets() -> None:
    perp = make(long_kw(instrument_id=BTC_PERP, market="CRYPTO", segment="CRYPTO_PERPETUALS",
                        inputs=inputs(**spec_inputs("btc_perp")),
                        horizon=HorizonSpec.build(timeframe="5m", horizon_bars=12, start_utc=DEC,
                                                  session_kind=SessionKind.CONTINUOUS, calendar_id="CRYPTO_24_7",
                                                  calendar_version="1.0.0"),
                        costs=costs(price_currency="USDT", funding_cost_per_unit=D("-0.001"))))
    assert perp.expected_net_r.total_cost_per_unit == D("0.034")       # funding credit reduces cost
    ist_open, ist_close = datetime(2026, 1, 5, 3, 45, tzinfo=UTC), datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    d_in = datetime(2026, 1, 5, 5, 0, 2, tzinfo=UTC)
    nifty = make(long_kw(instrument_id=NIFTY_FUT, market="IN", segment="IN_INDEX_FUTURES", decision_timestamp_utc=d_in,
                         inference_at_utc=d_in, created_at_utc=d_in + timedelta(seconds=1),
                         expires_at_utc=d_in + timedelta(minutes=5), inputs=inputs(d_in, **spec_inputs("nifty_fut")),
                         entry=entry(d_in, "24500"),
                         levels=RiskLevels(D("24450"), D("24600")),
                         horizon=us_horizon(d_in, calendar_id="XNSE", calendar_version="1.0.0", session_id="XNSE_2026-01-05",
                                            session_open_utc=ist_open, session_close_utc=ist_close),
                         costs=costs(price_currency="INR", tax_cost_per_unit=D("1.2"))))
    assert nifty.market == "IN" and nifty.expected_net_r.status is NetRStatus.AVAILABLE
    assert make(long_kw(instrument_id=AAPL_CALL, segment="US_OPTIONS", entry=entry(price="5"),
                        inputs=inputs(**spec_inputs("aapl_call")),
                        levels=RiskLevels(D("4"), D("7")))).segment == "US_OPTIONS"


def test_invalid_direction_and_unsupported_direction_for_segment() -> None:
    for bad in ("BUY", "long", "", None, 1):
        with pytest.raises(PredictionContractError):
            make(long_kw(direction=bad))
    with pytest.raises(PredictionContractError) as e:
        make(short_kw(instrument_id=AAPL_CALL, segment="US_OPTIONS", entry=entry(price="5"),
                      inputs=inputs(**spec_inputs("aapl_call")), levels=RiskLevels(D("6"), D("3")), costs=costs()))
    assert code(e) == V.UNSUPPORTED_DIRECTION_FOR_SEGMENT.value


def test_missing_required_fields() -> None:
    p = make(long_kw())
    for key in ("instrument_id", "horizon", "direction_probabilities", "expected_net_r", "prediction_id"):
        d = raw(p)
        del d[key]
        with pytest.raises(PredictionContractError) as e:
            Prediction.from_dict(d)
        assert code(e) == V.MISSING_FIELD.value
    kw = long_kw()
    del kw["model"]
    with pytest.raises(PredictionContractError) as e:
        make(kw)
    assert code(e) == V.MISSING_FIELD.value
    with pytest.raises(PredictionContractError) as e:
        make(long_kw(outcome_probabilities=None))
    assert code(e) == V.DIRECTIONAL_MISSING_FIELDS.value


def test_unknown_contract_version() -> None:
    p = make(long_kw())
    for v in ("2.0.0", "1.0", "", None):
        with pytest.raises(PredictionContractError):
            Prediction.from_dict(raw(p, contract_version=v))
    with pytest.raises(PredictionContractError) as e:
        dataclasses.replace(p, contract_version="1.1.0")
    assert code(e) == V.INVALID_CONTRACT_VERSION.value


@pytest.mark.parametrize("iid,market,segment,expected", [
    ("AAPL", "US", "US_EQUITY", V.INVALID_INSTRUMENT_ID),
    ("US:NASDAQ:EQUITY:AAPL#XYZ", "US", "US_EQUITY", V.INVALID_INSTRUMENT_ID),
    (AAPL, "US", "US_INDEX", V.UNSUPPORTED_SEGMENT),
    (AAPL, "IN", "US_EQUITY", V.INSTRUMENT_SCOPE_MISMATCH),
    (AAPL, "US", "US_FUTURES", V.INSTRUMENT_SCOPE_MISMATCH),
    ("IN:NFO:FUTURE:RELIANCE:20261231:RELIANCE26DECFUT#" + "1" * 32, "IN", "IN_INDEX_FUTURES", V.INSTRUMENT_SCOPE_MISMATCH),
    ("CRYPTO:BINANCE:DATED_FUTURE:BTCUSDT_261225:BTC/USDT:USDT:LINEAR:20261225#" + "2" * 32, "CRYPTO", "CRYPTO_FUTURES", V.UNSUPPORTED_SEGMENT),
])
def test_invalid_instrument_identity_and_scope(iid, market, segment, expected) -> None:
    with pytest.raises(PredictionContractError) as e:
        make(long_kw(instrument_id=iid, market=market, segment=segment))
    assert code(e) == expected.value


def test_invalid_model_and_provenance_references() -> None:
    bad_models = [dict(model_artifact_sha256="A" * 64), dict(feature_snapshot_id="f" * 63), dict(model_id=""),
                  dict(decision_policy_version="  ")]
    for change in bad_models:
        with pytest.raises(PredictionContractError):
            dataclasses.replace(MODEL, **change)
    for change in (dict(data_snapshot_ids=()), dict(data_snapshot_ids=("2" * 64, "1" * 64)),
                   dict(data_snapshot_ids=("1" * 64, "1" * 64)), dict(chart_snapshot_ids=("zz",)),
                   dict(instrument_spec_hash="x"), dict(instrument_spec_hash="e" * 64),
                   dict(availability_mode="LIVE"), dict(instrument_spec_version_id=-1)):
        with pytest.raises(PredictionContractError):
            inputs(**change)
    p = make(long_kw())
    with pytest.raises(PredictionContractError) as e:              # content-addressed id cannot be forged
        Prediction.from_dict(raw(p, prediction_id="0" * 64))
    assert code(e) == V.INVALID_PREDICTION_ID.value
    with pytest.raises(PredictionContractError) as e:              # nor can usage_class contradict availability
        Prediction.from_dict(raw(p, usage_class="RESEARCH_RETROSPECTIVE"))
    assert code(e) == V.INVALID_PROVENANCE.value
    for derived in ("prediction_id", "expected_net_r", "usage_class", "contract_version"):
        with pytest.raises(PredictionContractError):
            make(long_kw(**{derived: "x"}))
    chart = make(long_kw(inputs=inputs(chart_snapshot_ids=("3" * 64,))))
    assert chart.inputs.chart_snapshot_ids == ("3" * 64,) and chart.prediction_id != p.prediction_id


# ================================================================================================ horizon and time

def test_naive_timestamps_rejected() -> None:
    naive = datetime(2026, 1, 5, 15, 0, 2)
    with pytest.raises(PredictionContractError) as e:
        make(long_kw(created_at_utc=naive))
    assert code(e) == V.INVALID_TIMESTAMP.value
    with pytest.raises(PredictionContractError):
        Prediction.from_dict(raw(make(long_kw()), created_at_utc="2026-01-05T15:00:05"))
    with pytest.raises(PredictionContractError):
        entry(reference_observed_at_utc=naive)


@pytest.mark.parametrize("change", [
    dict(inference_at_utc=DEC - timedelta(seconds=1)),
    dict(created_at_utc=DEC + timedelta(seconds=1)),                  # created before inference
    dict(expires_at_utc=DEC + timedelta(seconds=3)),                  # expires == created
    dict(expires_at_utc=DEC + timedelta(hours=2)),                    # after the horizon end
])
def test_incorrect_timestamp_ordering_rejected(change) -> None:
    with pytest.raises(PredictionContractError) as e:
        make(long_kw(**change))
    assert code(e) in (V.TIMESTAMP_ORDER.value, V.INVALID_HORIZON.value)


def test_invalid_horizons() -> None:
    with pytest.raises(PredictionContractError) as e:
        make(long_kw(horizon=us_horizon(bars=0)))
    assert code(e) == V.INVALID_HORIZON.value
    for tf in ("3m", "1d", "short-term"):
        with pytest.raises(PredictionContractError):
            us_horizon(timeframe=tf)
    with pytest.raises(PredictionContractError):                    # end must be start + bars * timeframe
        dataclasses.replace(us_horizon(), expected_end_utc=DEC + timedelta(minutes=61))
    with pytest.raises(PredictionContractError):                    # > 24h
        HorizonSpec.build(timeframe="1h", horizon_bars=25, start_utc=DEC, session_kind=SessionKind.CONTINUOUS,
                          calendar_id="C", calendar_version="1")
    with pytest.raises(PredictionContractError):                    # exchange session without session bounds
        us_horizon(session_id=None, session_open_utc=None, session_close_utc=None)
    with pytest.raises(PredictionContractError):                    # continuous horizon with session fields
        HorizonSpec.build(timeframe="5m", horizon_bars=1, start_utc=DEC, session_kind=SessionKind.CONTINUOUS,
                          calendar_id="C", calendar_version="1", session_id="X")
    with pytest.raises(PredictionContractError) as e:               # equity with a 24/7 horizon
        make(long_kw(horizon=HorizonSpec.build(timeframe="5m", horizon_bars=12, start_utc=DEC,
                                               session_kind=SessionKind.CONTINUOUS, calendar_id="CRYPTO_24_7",
                                               calendar_version="1")))
    assert code(e) in (V.INVALID_HORIZON.value, V.CALENDAR_MISMATCH.value)
    with pytest.raises(PredictionContractError):                    # horizon must start at the decision
        make(long_kw(horizon=us_horizon(start=DEC + timedelta(seconds=1))))


def test_session_boundary_violations() -> None:
    late = datetime(2026, 1, 5, 20, 55, tzinfo=UTC)                  # 15:55 New York
    with pytest.raises(PredictionContractError) as e:
        us_horizon(start=late, bars=2)                              # would end 16:05 New York
    assert code(e) == V.SESSION_BOUNDARY_VIOLATION.value
    assert us_horizon(start=late, bars=1).expected_end_utc == datetime(2026, 1, 5, 21, tzinfo=UTC)   # exactly the close
    with pytest.raises(PredictionContractError) as e:               # outside the session entirely
        us_horizon(start=datetime(2026, 1, 5, 13, 0, tzinfo=UTC))
    assert code(e) == V.SESSION_BOUNDARY_VIOLATION.value
    ist_close = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    with pytest.raises(PredictionContractError):                    # NIFTY past 15:30 IST
        us_horizon(start=ist_close - timedelta(minutes=10), bars=3, calendar_id="XNSE", session_id="XNSE_2026-01-05",
                   session_open_utc=datetime(2026, 1, 5, 3, 45, tzinfo=UTC), session_close_utc=ist_close)
    perp = HorizonSpec.build(timeframe="1h", horizon_bars=24, start_utc=late, session_kind=SessionKind.CONTINUOUS,
                             calendar_id="CRYPTO_24_7", calendar_version="1")
    assert perp.first_bar_open_utc == datetime(2026, 1, 5, 21, 0, tzinfo=UTC)          # next UTC-anchored 1h bar
    assert perp.expected_end_utc == perp.first_bar_open_utc + timedelta(hours=24)     # crosses midnight, no close


@pytest.mark.parametrize("change,expected", [
    (dict(inputs=inputs(max_input_event_time_utc=DEC + timedelta(seconds=1), feature_snapshot_as_of_utc=DEC + timedelta(seconds=1))), DQ.LOOKAHEAD_INPUT_EVENT_TIME),
    (dict(inputs=inputs(max_input_received_at_utc=DEC + timedelta(seconds=1))), DQ.LOOKAHEAD_INPUT_RECEIVED_AT),
    (dict(inputs=inputs(feature_snapshot_as_of_utc=DEC + timedelta(seconds=1))), DQ.LOOKAHEAD_FEATURE_SNAPSHOT),
    (dict(inputs=inputs(instrument_spec_recorded_at_utc=DEC + timedelta(days=1))), DQ.LOOKAHEAD_INSTRUMENT_SPEC),
    (dict(entry=entry(reference_observed_at_utc=DEC + timedelta(seconds=1), reference_received_at_utc=DEC + timedelta(seconds=1))), DQ.LOOKAHEAD_REFERENCE_PRICE),
    (dict(entry=entry(reference_received_at_utc=DEC + timedelta(seconds=1))), DQ.LOOKAHEAD_REFERENCE_PRICE),
    (dict(model=dataclasses.replace(MODEL, training_data_end_utc=DEC + timedelta(days=1), model_trained_at_utc=DEC + timedelta(days=1),
                                    model_available_at_utc=DEC + timedelta(days=1))), DQ.LOOKAHEAD_MODEL_TRAINING),
    (dict(outcome_probabilities=oprobs(cal=dataclasses.replace(CAL, fitted_until_utc=DEC + timedelta(days=1),
                                                               available_at_utc=DEC + timedelta(days=1)))), DQ.LOOKAHEAD_CALIBRATION),
    (dict(entry=entry(reference_observed_at_utc=DEC - timedelta(minutes=5), reference_received_at_utc=DEC - timedelta(minutes=5))), DQ.STALE_REFERENCE_PRICE),
    (dict(inference_at_utc=DEC + timedelta(seconds=40), created_at_utc=DEC + timedelta(seconds=41)), DQ.STALE_INFERENCE),
])
def test_future_and_stale_inputs_rejected_for_live_faithful(change, expected) -> None:
    with pytest.raises(PredictionContractError) as e:
        make(long_kw(**change))
    assert code(e) == expected.value


def test_retrospective_event_time_predictions_are_explicitly_research_only() -> None:
    late = inputs(availability_mode="EVENT_TIME", max_input_received_at_utc=DEC + timedelta(days=300),
                  instrument_spec_recorded_at_utc=DEC + timedelta(days=300))
    p = make(long_kw(inputs=late, entry=entry(reference_received_at_utc=DEC + timedelta(days=300))))
    assert p.usage_class is UsageClass.RESEARCH_RETROSPECTIVE and not p.is_live_faithful
    with pytest.raises(PredictionContractError) as e:               # event times are still never after the decision
        make(long_kw(inputs=inputs(availability_mode="EVENT_TIME", max_input_event_time_utc=DEC + timedelta(seconds=1),
                                   feature_snapshot_as_of_utc=DEC + timedelta(seconds=1))))
    assert code(e) == DQ.LOOKAHEAD_INPUT_EVENT_TIME.value
    with pytest.raises(PredictionContractError):                    # training cutoff leakage is rejected in research too
        make(long_kw(inputs=late, model=dataclasses.replace(MODEL, training_data_end_utc=DEC + timedelta(days=1),
                                                            model_trained_at_utc=DEC + timedelta(days=1),
                                                            model_available_at_utc=DEC + timedelta(days=1))))


# ================================================================================================ financial invariants

@pytest.mark.parametrize("kw_fn,sl,tp,expected", [
    (long_kw, "101", "102", V.INVALID_RISK_LEVELS),     # stop above entry
    (long_kw, "99", "98", V.INVALID_RISK_LEVELS),       # target below entry
    (long_kw, "100", "102", V.INVALID_RISK_DISTANCE),
    (long_kw, "99", "100", V.INVALID_REWARD_DISTANCE),
    (short_kw, "99", "98", V.INVALID_RISK_LEVELS),      # stop below entry
    (short_kw, "101", "102", V.INVALID_RISK_LEVELS),    # target above entry
    (short_kw, "100", "98", V.INVALID_RISK_DISTANCE),
    (short_kw, "101", "100", V.INVALID_REWARD_DISTANCE),
])
def test_direction_aware_level_ordering(kw_fn, sl, tp, expected) -> None:
    with pytest.raises(PredictionContractError) as e:
        make(kw_fn(levels=RiskLevels(D(sl), D(tp))))
    assert code(e) == expected.value


def test_non_positive_prices_rejected() -> None:
    for price in ("0", "-1"):
        with pytest.raises(PredictionContractError) as e:
            entry(price=price)
        assert code(e) == V.INVALID_PRICE.value
        with pytest.raises(PredictionContractError):
            RiskLevels(D(price), D("102"))
    with pytest.raises(PredictionContractError):
        entry(entry_tolerance=D("-0.01"))


def test_decimal_precision_and_serialization() -> None:
    p = make(long_kw(levels=RiskLevels(D("97"), D("101"))))         # risk 3, reward 1: thirds need rounding
    n = p.expected_net_r
    assert n.reward_risk_ratio_gross == D("0.333333333333")         # 12 dp, ROUND_HALF_EVEN
    d = json.loads(p.to_json())
    assert d["expected_net_r"]["reward_risk_ratio_gross"] == "0.333333333333"
    assert isinstance(d["entry"]["expected_entry_price"], str) and d["levels"]["stop_loss_price"] == "97"
    assert make(long_kw(entry=entry(price="100.00"))).entry.expected_entry_price == D("100")
    for bad in (100.0, 100, "100", True):
        with pytest.raises(PredictionContractError):
            dataclasses.replace(entry(), expected_entry_price=bad)
    with pytest.raises(PredictionContractError):                    # 13 decimal places
        dprobs("0.6000000000001", "0.0999999999999", "0.3")


def test_missing_and_inapplicable_cost_assumptions() -> None:
    p = make(long_kw(costs=costs(fee_cost_per_unit=None), uncertainty=NO_UNC))
    assert p.expected_net_r.status is NetRStatus.UNAVAILABLE
    assert p.expected_net_r.unavailable_reasons == (NetRUnavailableReason.MISSING_COST_ASSUMPTION,)
    assert p.expected_net_r.expected_net_r is None and p.expected_net_r.initial_risk_per_unit == D("1")
    short_no_borrow = make(short_kw(costs=costs(), uncertainty=NO_UNC))                 # US equity short needs a borrow cost
    assert short_no_borrow.expected_net_r.status is NetRStatus.UNAVAILABLE
    nifty_no_tax = compute_expected_net_r(direction=Direction.LONG, segment="IN_INDEX_FUTURES", entry=entry(),
                                          levels=RiskLevels(D("99"), D("102")), outcome=oprobs(),
                                          expected_horizon_exit_move_per_unit=D("0"), costs=costs())
    assert NetRUnavailableReason.MISSING_COST_ASSUMPTION in nifty_no_tax.unavailable_reasons
    with pytest.raises(PredictionContractError) as e:               # funding is not applicable to equities
        make(long_kw(costs=costs(funding_cost_per_unit=D("0"))))
    assert code(e) == V.INVALID_COST.value
    with pytest.raises(PredictionContractError):
        costs(spread_cost_per_unit=D("-0.01"))


def test_expected_net_r_consistency_and_no_gross_net_confusion() -> None:
    p = make(long_kw())
    n = p.expected_net_r
    assert n.expected_gross_r != n.expected_net_r and n.expected_net_r == (n.expected_net_per_unit / n.initial_risk_per_unit)
    assert n.expected_net_per_unit == n.expected_gross_per_unit - n.total_cost_per_unit
    for field, value in (("expected_net_r", "0.78"), ("expected_gross_r", "0.745"), ("total_cost_per_unit", "0")):
        d = raw(p)
        d["expected_net_r"][field] = value
        with pytest.raises(PredictionContractError) as e:
            Prediction.from_dict(d)
        assert code(e) == V.NET_R_MISMATCH.value
    d = raw(p)
    d["expected_net_r"]["status"] = "UNAVAILABLE"
    with pytest.raises(PredictionContractError):
        Prediction.from_dict(d)
    zero = make(long_kw(costs=costs(spread_cost_per_unit=D("0"), slippage_cost_per_unit=D("0"), fee_cost_per_unit=D("0"))))
    assert zero.expected_net_r.expected_net_r == zero.expected_net_r.expected_gross_r   # equal only when costs are zero
    with pytest.raises(PredictionContractError):                    # exit move outside [-risk, +reward]
        make(long_kw(expected_horizon_exit_move_per_unit=D("2.5")))


# ================================================================================================ probabilities

def test_valid_probabilities_and_selection_rules() -> None:
    assert make(long_kw(direction_probabilities=dprobs("0.4", "0.1", "0.5"))).confidence == D("0.4")
    with pytest.raises(PredictionContractError) as e:               # LONG while SHORT is more probable
        make(long_kw(direction_probabilities=dprobs("0.2", "0.5", "0.3")))
    assert code(e) == V.INCONSISTENT_DIRECTION_SELECTION.value
    with pytest.raises(PredictionContractError):                    # ties do not select a side
        make(long_kw(direction_probabilities=dprobs("0.3", "0.3", "0.4")))


@pytest.mark.parametrize("values,expected", [
    (("1.1", "-0.1", "0"), V.INVALID_PROBABILITY),
    (("0.5", "0.4", "0.2"), V.PROBABILITY_SUM),
    (("0.5", "0.4", "0.09999"), V.PROBABILITY_SUM),
])
def test_probability_range_and_sum(values, expected) -> None:
    with pytest.raises(PredictionContractError) as e:
        dprobs(*values)
    assert code(e) == expected.value
    with pytest.raises(PredictionContractError):
        oprobs(*values)


def test_nan_and_infinity_rejected() -> None:
    for bad in (D("NaN"), D("Infinity"), D("-Infinity"), D("sNaN")):
        with pytest.raises(PredictionContractError) as e:
            DirectionProbabilities(bad, D("0"), D("1"), ProbabilityKind.CALIBRATED, CAL)
        assert code(e) == V.NON_FINITE_NUMBER.value
    p = make(long_kw())
    for s in ("NaN", "Infinity", "-inf"):
        d = raw(p)
        d["direction_probabilities"]["long"] = s
        with pytest.raises(PredictionContractError) as e:
            Prediction.from_dict(d)
        assert code(e) == V.NON_FINITE_NUMBER.value
    with pytest.raises(PredictionContractError) as e:               # bare JSON NaN constant
        Prediction.from_json(p.to_json().replace('"long":"0.6"', '"long":NaN'))
    assert code(e) == V.NON_FINITE_NUMBER.value


def test_calibration_metadata_rules() -> None:
    with pytest.raises(PredictionContractError) as e:
        dprobs(cal=None)
    assert code(e) == V.MISSING_CALIBRATION.value
    with pytest.raises(PredictionContractError) as e:
        oprobs(kind=ProbabilityKind.UNCALIBRATED_SCORE)              # a score cannot claim a calibrator
    assert code(e) == V.MISSING_CALIBRATION.value
    uncal = oprobs(kind=ProbabilityKind.UNCALIBRATED_SCORE, cal=None)
    p = make(long_kw(outcome_probabilities=uncal, uncertainty=NO_UNC))
    assert p.expected_net_r.status is NetRStatus.UNAVAILABLE      # a score is never turned into an expected R
    assert p.expected_net_r.unavailable_reasons == (NetRUnavailableReason.UNCALIBRATED_OUTCOME_PROBABILITIES,)
    with pytest.raises(PredictionContractError) as e:               # an interval needs an available net R
        make(long_kw(outcome_probabilities=uncal, uncertainty=UNC))
    assert code(e) == V.INVALID_UNCERTAINTY.value


def test_confidence_and_uncertainty_representation() -> None:
    bad = [
        dict(lower_net_r=D("2"), upper_net_r=D("1")),
        dict(coverage=D("1")), dict(coverage=D("0")),
        dict(method=None),
        dict(unavailable_reason=UncertaintyUnavailableReason.INSUFFICIENT_DATA),
    ]
    for change in bad:
        with pytest.raises(PredictionContractError) as e:
            dataclasses.replace(UNC, **change)
        assert code(e) == V.INVALID_UNCERTAINTY.value
    with pytest.raises(PredictionContractError):
        Uncertainty(UncertaintyStatus.UNAVAILABLE, None, D("0"), None, None, None, None,
                    UncertaintyUnavailableReason.INSUFFICIENT_DATA)
    with pytest.raises(PredictionContractError):                    # NO_TRADE never reports a net-R interval
        make(no_trade_kw(uncertainty=Uncertainty.unavailable(UncertaintyUnavailableReason.INSUFFICIENT_DATA)))
    unavailable = make(long_kw(uncertainty=Uncertainty.unavailable(UncertaintyUnavailableReason.NOT_SUPPORTED_BY_MODEL)))
    assert unavailable.uncertainty.status is UncertaintyStatus.UNAVAILABLE
    assert "confidence" not in json.loads(unavailable.to_json())   # derived, never a second stored copy


# ================================================================================================ state and risk boundary

def state_at(p, at, **over):
    kw = dict(evaluated_at_utc=at, latest_market_data_received_at_utc=at - timedelta(seconds=1),
              max_market_data_age_seconds=30, instrument_tradable=True, last_price=D("100.02"))
    kw.update(over)
    return evaluate_prediction_state(p, **kw)


def test_valid_expired_and_invalidated_are_distinct() -> None:
    p = make(long_kw())
    t = DEC + timedelta(seconds=10)
    assert state_at(p, t).state is PredictionState.VALID
    exp = state_at(p, p.expires_at_utc)
    assert exp.state is PredictionState.EXPIRED and exp.expiry_reasons == (ExpiryReasonCode.EXPIRATION_REACHED,)
    end = state_at(p, p.horizon.expected_end_utc, latest_market_data_received_at_utc=DEC)   # stale too, still EXPIRED
    assert end.state is PredictionState.EXPIRED and ExpiryReasonCode.HORIZON_ELAPSED in end.expiry_reasons
    assert end.invalidation_reasons == ()
    cases = {
        InvalidationReasonCode.STALE_MARKET_DATA: dict(latest_market_data_received_at_utc=t - timedelta(minutes=1)),
        InvalidationReasonCode.MISSING_MARKET_DATA: dict(last_price=None),
        InvalidationReasonCode.INSTRUMENT_NOT_TRADABLE: dict(instrument_tradable=False),
        InvalidationReasonCode.PRICE_BEYOND_STOP: dict(last_price=D("98.9")),
        InvalidationReasonCode.ENTRY_PRICE_DEVIATION: dict(last_price=D("100.5")),
        InvalidationReasonCode.MANUAL_INVALIDATION: dict(explicit_invalidations=[InvalidationReasonCode.MANUAL_INVALIDATION]),
    }
    for reason, change in cases.items():
        rec = state_at(p, t, **change)
        assert rec.state is PredictionState.INVALIDATED and reason in rec.invalidation_reasons
    with pytest.raises(PredictionContractError):                    # derived reasons cannot be supplied by hand
        state_at(p, t, explicit_invalidations=[InvalidationReasonCode.STALE_MARKET_DATA])
    with pytest.raises(PredictionContractError):                    # market data from the future
        state_at(p, t, latest_market_data_received_at_utc=t + timedelta(seconds=1))
    valid = state_at(p, t)
    with pytest.raises(PredictionContractError):                    # EXPIRED before expiry
        dataclasses.replace(valid, state=PredictionState.EXPIRED, expiry_reasons=(ExpiryReasonCode.EXPIRATION_REACHED,))
    with pytest.raises(PredictionContractError):                    # VALID with an expiry reason
        dataclasses.replace(valid, expiry_reasons=(ExpiryReasonCode.EXPIRATION_REACHED,))


KILL = LimitCheck.evaluate("kill_switch", LimitKind.KILL_SWITCH, "1", observed_flag=False)
HARD = [KILL,
        LimitCheck.evaluate("daily_loss", LimitKind.DAILY_LOSS_LIMIT, "1", observed_value=D("120"), limit_value=D("150")),
        LimitCheck.evaluate("position", LimitKind.POSITION_LIMIT, "1", observed_value=D("1"), limit_value=D("3")),
        LimitCheck.evaluate("exposure", LimitKind.EXPOSURE_LIMIT, "1", observed_value=D("2000"), limit_value=D("5000")),
        LimitCheck.evaluate("restricted", LimitKind.RESTRICTED_INSTRUMENT, "1", observed_flag=False)]
KILLED = LimitCheck.evaluate("kill_switch", LimitKind.KILL_SWITCH, "1", observed_flag=True)
MIN_R = LimitCheck.evaluate("min_net_r", LimitKind.MIN_EXPECTED_NET_R, "1", observed_value=D("0.745"), limit_value=D("0.8"))


def assess(p, st, checks=HARD, overrides=(), at=None, calendar=XNYS, **kw):
    return assess_prediction(p, st, risk_policy_id="us_paper_risk", risk_policy_version="1.0.0",
                             assessed_at_utc=at or st.evaluated_at_utc, limit_checks=checks, overrides=overrides,
                             calendar=calendar, **kw)


def override(**over) -> RiskOverride:
    base = dict(override_id="ovr-1", authorized_by="ansh", authorization_reference="ticket-42",
                justification="paper experiment", instrument_id=AAPL, overridden_limit_ids=("min_net_r",),
                granted_at_utc=DEC, expires_at_utc=DEC + timedelta(hours=1))
    base.update(over)
    return RiskOverride(**base)


def test_approval_rejection_and_eligibility() -> None:
    p = make(long_kw())
    st = state_at(p, DEC + timedelta(seconds=10))
    ok = assess(p, st)
    assert ok.status is RiskStatus.APPROVED and is_execution_eligible(p, st, ok, calendar=XNYS)
    verify_risk_assessment(ok, p, st, calendar=XNYS)
    assert RiskAssessment.from_json(ok.to_json()) == ok


def test_risk_rejection_does_not_mutate_or_become_model_no_trade() -> None:
    p = make(long_kw())
    before = p.to_json()
    st = state_at(p, DEC + timedelta(seconds=10))
    killed = [KILLED] + HARD[1:]
    rej = assess(p, st, killed)
    assert rej.status is RiskStatus.REJECTED and rej.rejection_reasons == (RiskRejectionCode.KILL_SWITCH_ACTIVE,)
    assert p.direction is Direction.LONG and p.to_json() == before and rej.prediction_direction is Direction.LONG
    assert not is_execution_eligible(p, st, rej)
    model_codes = {c.value for c in ModelReasonCode}
    risk_codes = {c.value for c in RiskRejectionCode}
    assert not model_codes & risk_codes                              # rejection is never a model NO_TRADE reason
    families = [reason_codes.ModelReasonCode, reason_codes.ValidationFailureCode, reason_codes.DataQualityCode,
                reason_codes.ExpiryReasonCode, reason_codes.InvalidationReasonCode, reason_codes.RiskRejectionCode]
    values = [m.value for f in families for m in f]
    assert len(values) == len(set(values))                          # the five families never share a code
    with pytest.raises(RiskAssessmentContractError):                # REJECTED without a reason
        RiskAssessment.from_dict({**json.loads(rej.to_json()), "rejection_reasons": []})


def test_approval_cannot_make_no_trade_executable() -> None:
    p = make(no_trade_kw())
    st = state_at(p, DEC + timedelta(seconds=10), last_price=None)
    na = assess(p, st)
    assert na.status is RiskStatus.NOT_APPLICABLE and not is_execution_eligible(p, st, na)
    forged = {**json.loads(na.to_json()), "status": "APPROVED"}
    with pytest.raises(RiskAssessmentContractError):
        RiskAssessment.from_dict(forged)
    with pytest.raises(RiskAssessmentContractError):                # nor by relabelling the prediction direction
        RiskAssessment.from_dict({**forged, "prediction_direction": "LONG"})
    # Every other approval precondition faked as satisfied: the NO_TRADE rule alone still blocks approval.
    with pytest.raises(RiskAssessmentContractError, match="NO_TRADE"):
        dataclasses.replace(na, status=RiskStatus.APPROVED, prediction_expected_net_r_status=NetRStatus.AVAILABLE,
                            prediction_probabilities_calibrated=True)


def test_risk_approval_preconditions() -> None:
    p = make(long_kw())
    st = state_at(p, DEC + timedelta(seconds=10))
    exp = state_at(p, p.expires_at_utc)
    assert assess(p, exp).rejection_reasons == (RiskRejectionCode.PREDICTION_EXPIRED,)
    inv = state_at(p, DEC + timedelta(seconds=10), instrument_tradable=False)
    assert RiskRejectionCode.PREDICTION_INVALIDATED in assess(p, inv).rejection_reasons
    research = make(long_kw(inputs=inputs(availability_mode="EVENT_TIME", max_input_received_at_utc=DEC + timedelta(days=9))))
    r_st = state_at(research, DEC + timedelta(seconds=10))
    r_rej = assess(research, r_st)
    assert RiskRejectionCode.RESEARCH_ONLY_PREDICTION in r_rej.rejection_reasons
    with pytest.raises(RiskAssessmentContractError, match="research"):   # record-level rule, independent of derivation
        dataclasses.replace(r_rej, status=RiskStatus.APPROVED, rejection_reasons=())
    no_cost = make(long_kw(costs=costs(fee_cost_per_unit=None), uncertainty=Uncertainty.unavailable(
        UncertaintyUnavailableReason.EXPECTED_NET_R_UNAVAILABLE)))
    assert RiskRejectionCode.EXPECTED_NET_R_UNAVAILABLE in assess(no_cost, state_at(no_cost, DEC + timedelta(seconds=10))).rejection_reasons
    assert RiskRejectionCode.POLICY_REJECTION in assess(p, st, HARD[1:]).rejection_reasons   # kill switch not evaluated
    with pytest.raises(RiskAssessmentContractError):                # an APPROVED record skipping a hard control
        RiskAssessment.from_dict({**json.loads(assess(p, st).to_json()), "limit_checks": [c.to_dict() for c in HARD[1:]]})
    forged = {**json.loads(assess(p, exp).to_json()), "status": "APPROVED", "rejection_reasons": []}
    with pytest.raises(RiskAssessmentContractError):                # approving an expired prediction
        RiskAssessment.from_dict(forged)


def test_override_rules_and_hard_controls() -> None:
    p = make(long_kw())
    st = state_at(p, DEC + timedelta(seconds=10))
    rejected = assess(p, st, HARD + [MIN_R])
    assert rejected.rejection_reasons == (RiskRejectionCode.MIN_EXPECTED_NET_R,)
    approved = assess(p, st, HARD + [MIN_R], overrides=[override()])
    assert approved.status is RiskStatus.APPROVED and approved.overrides[0].authorized_by == "ansh"
    verify_risk_assessment(approved, p, st, calendar=XNYS)
    expired_ovr = override(granted_at_utc=DEC - timedelta(hours=2), expires_at_utc=DEC - timedelta(hours=1))
    assert assess(p, st, HARD + [MIN_R], overrides=[expired_ovr]).status is RiskStatus.REJECTED
    for bad in (dict(expires_at_utc=DEC), dict(expires_at_utc=DEC + timedelta(hours=9)), dict(overridden_limit_ids=()),
                dict(overridden_limit_ids=("*",)), dict(overridden_limit_ids="min_net_r"), dict(authorized_by=""),
                dict(justification=None)):
        with pytest.raises(PredictionContractError):
            override(**bad)
    with pytest.raises(RiskAssessmentContractError):                # override scoped to another instrument
        assess(p, st, HARD + [MIN_R], overrides=[override(instrument_id=BTC_PERP)])
    with pytest.raises(RiskAssessmentContractError):                # unknown limit id
        assess(p, st, HARD + [MIN_R], overrides=[override(overridden_limit_ids=("nope",))])
    killed = [KILLED] + HARD[1:]
    for lid in ("kill_switch", "daily_loss", "position", "exposure", "restricted"):
        with pytest.raises(RiskAssessmentContractError) as e:       # hard controls can never be overridden
            assess(p, st, killed, overrides=[override(overridden_limit_ids=(lid,))])
        assert code(e) == ValidationFailureCode.HARD_CONTROL_OVERRIDE.value
    with pytest.raises(PredictionContractError):                    # a hard control cannot be relabelled soft
        LimitCheck("kill_switch", LimitKind.KILL_SWITCH, "1", CheckResult.FAIL, False, None, None, True)
    forged = {**json.loads(assess(p, st, killed).to_json()), "status": "APPROVED", "rejection_reasons": []}
    with pytest.raises(RiskAssessmentContractError):
        RiskAssessment.from_dict(forged)


def test_verification_detects_forged_or_mismatched_assessments() -> None:
    p, q = make(long_kw()), make(short_kw())
    st = state_at(p, DEC + timedelta(seconds=10))
    ok = assess(p, st)
    with pytest.raises(RiskAssessmentContractError):
        verify_risk_assessment(ok, q, state_at(q, DEC + timedelta(seconds=10), last_price=D("99.98")), calendar=XNYS)
    later = state_at(p, DEC + timedelta(seconds=20))
    assert not is_execution_eligible(p, later, ok)                  # bound to the exact state it assessed
    min_r_rejected = assess(p, st, HARD + [MIN_R])
    d = json.loads(min_r_rejected.to_json())
    d.update(status="APPROVED", rejection_reasons=[], overrides=[override().to_dict()])
    d["risk_assessment_id"] = "0" * 64
    with pytest.raises(RiskAssessmentContractError):                # content id binds the record
        RiskAssessment.from_dict(d)


# ================================================================================================ serialization

@pytest.mark.parametrize("kw_fn", [long_kw, short_kw, no_trade_kw])
def test_json_round_trip(kw_fn) -> None:
    p = make(kw_fn())
    again = Prediction.from_json(p.to_json())
    assert again == p and again.to_json() == p.to_json() and again.prediction_id == p.prediction_id
    st = state_at(p, DEC + timedelta(seconds=10), last_price=None if p.direction is Direction.NO_TRADE else D("100"))
    assert PredictionStateRecord.from_json(st.to_json()) == st


@pytest.mark.parametrize("payload", ["", "{", "[]", "null", '"x"', "123", "{\"a\": 1.5}"])
def test_malformed_payloads_rejected(payload) -> None:
    with pytest.raises(PredictionContractError):
        Prediction.from_json(payload)


def test_wrong_types_and_no_silent_normalization() -> None:
    p = make(long_kw())
    cases = [
        ("max_decision_latency_seconds", "30"), ("max_decision_latency_seconds", 30.0),
        ("max_decision_latency_seconds", True), ("instrument_id", 123), ("direction", "long"),
        ("model_reasons", "MODEL_DIRECTIONAL_EDGE"),                # a string is never split into a tuple
        ("expected_horizon_exit_move_per_unit", 0.4), ("explanation", ["x"]), ("unknown_field", 1),
    ]
    for key, value in cases:
        with pytest.raises(PredictionContractError):
            Prediction.from_dict(raw(p, **{key: value}))
    d = raw(p)
    d["entry"]["expected_entry_price"] = 100
    with pytest.raises(PredictionContractError):
        Prediction.from_dict(d)
    d = raw(p)
    d["inputs"]["data_snapshot_ids"] = "d" * 64
    with pytest.raises(PredictionContractError):
        Prediction.from_dict(d)
    with pytest.raises(PredictionContractError):
        Prediction.from_json(p.to_json().replace('"long":"0.6"', '"long":0.6'))   # JSON float
    with pytest.raises(PredictionContractError) as e:
        make(long_kw(model_reasons="MODEL_DIRECTIONAL_EDGE"))
    assert code(e) == V.INVALID_TYPE.value                          # rejected as a string, not split into characters
    with pytest.raises(PredictionContractError) as e:
        inputs(data_snapshot_ids="d" * 64)
    assert code(e) == V.INVALID_TYPE.value
    with pytest.raises(PredictionContractError):
        make(long_kw(model_reasons=(ModelReasonCode.DIRECTIONAL_EDGE, ModelReasonCode.DIRECTIONAL_EDGE)))


def test_nested_structures_are_immutable() -> None:
    p = make(long_kw())
    for target, attr, value in ((p, "direction", Direction.SHORT), (p.levels, "stop_loss_price", D("1")),
                                (p.expected_net_r, "expected_net_r", D("9")), (p.inputs, "data_snapshot_ids", ()),
                                (p.direction_probabilities, "long", D("1"))):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(target, attr, value)
    assert isinstance(p.model_reasons, tuple) and isinstance(p.inputs.data_snapshot_ids, tuple)
    d = p.to_dict()
    d["levels"]["stop_loss_price"] = "1"                            # to_dict hands out an independent copy
    assert p.levels.stop_loss_price == D("99")
    src = [ModelReasonCode.DIRECTIONAL_EDGE]
    q = make(long_kw(model_reasons=src))
    src.append(ModelReasonCode.NO_TRADE_LOW_EDGE)                   # caller's list mutated afterwards
    assert q.model_reasons == (ModelReasonCode.DIRECTIONAL_EDGE,)
