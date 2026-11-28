"""Phase 0 Step 3 independent-review remediation: regression tests for every reproduced issue."""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from ml_data.calendars.us_equity import USEquityCalendarAdapter
from ml_data.instruments.identity import compute_spec_hash
from ml_data.predictions import (
    EXIT_FILL_MODEL_V1,
    CheckResult,
    DataQualityCode,
    Direction,
    ExpiryReasonCode,
    HorizonSpec,
    InvalidationReasonCode,
    LimitCheck,
    LimitKind,
    NetRStatus,
    NetRUnavailableReason,
    Prediction,
    PredictionContractError,
    PredictionState,
    PredictionStateRecord,
    RiskAssessment,
    RiskAssessmentContractError,
    RiskLevels,
    RiskRejectionCode,
    RiskStatus,
    SessionKind,
    SessionVerification,
    Uncertainty,
    UncertaintyUnavailableReason,
    UsageClass,
    ValidationFailureCode,
    is_execution_eligible,
    verify_prediction_state,
    verify_risk_assessment,
)
from ml_data.charts.hashing import sha256_of_payload
from ml_data.predictions._records import _check, content_id

from .test_prediction_contract import (
    AAPL,
    AAPL_CALL,
    BTC_PERP,
    CAL,
    DEC,
    HARD,
    KILL,
    MODEL,
    NIFTY_FUT,
    SPECS,
    XNYS,
    assess,
    costs,
    entry,
    inputs,
    long_kw,
    make,
    no_trade_kw,
    oprobs,
    short_kw,
    spec_inputs,
    state_at,
    us_horizon,
)

UTC = timezone.utc
V, DQ = ValidationFailureCode, DataQualityCode
T10 = DEC + timedelta(seconds=10)
BTC_SPOT = "CRYPTO:BINANCE:CRYPTO_SPOT:BTC/USDT#d43c4935a5026de1bbfdcb2315b4481b"
NIFTY_CE = "IN:NFO:OPTION:NIFTY:20261203:24500:CALL:NIFTY26D0324500CE#a1a5b08805071ef08bf557c5261d8922"
ES_FUT = "US:CME:FUTURE:SPX:20261218:ESZ26#142d3932688cf3af9dbb27b13a6f65e3"
IST_OPEN, IST_CLOSE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC), datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
D_IN = datetime(2026, 1, 5, 5, 0, 2, tzinfo=UTC)


def code(e) -> str:
    return e.value.code


def rehash_state(rec: PredictionStateRecord, **changes) -> PredictionStateRecord:
    """A forged state record with a correctly recomputed state_id (so only semantic checks can catch it)."""
    base = {n: getattr(rec, n) for n in PredictionStateRecord.FIELDS}
    base.update(changes)
    draft = object.__new__(PredictionStateRecord)
    for n, k in PredictionStateRecord.FIELDS.items():
        object.__setattr__(draft, n, _check(k, base[n], n))
    return PredictionStateRecord(**{**base, "state_id": content_id(draft, "state_id")})


def rehash_assessment(ra: RiskAssessment, **changes) -> dict:
    """A forged assessment JSON with a correctly recomputed content id (only semantic checks can catch it)."""
    d = json.loads(ra.to_json())
    d.update(changes)
    d.pop("risk_assessment_id")
    d["risk_assessment_id"] = sha256_of_payload(d)
    return d


def nifty_kw(**over):
    kw = long_kw(instrument_id=NIFTY_FUT, market="IN", segment="IN_INDEX_FUTURES", decision_timestamp_utc=D_IN,
                 inference_at_utc=D_IN, created_at_utc=D_IN + timedelta(seconds=1), expires_at_utc=D_IN + timedelta(minutes=5),
                 inputs=inputs(D_IN, **spec_inputs("nifty_fut")), entry=entry(D_IN, "24500"),
                 levels=RiskLevels(D("24450"), D("24600")),
                 horizon=us_horizon(D_IN, calendar_id="XNSE", calendar_version="1.0.0", session_id="XNSE_2026-01-05",
                                    session_open_utc=IST_OPEN, session_close_utc=IST_CLOSE),
                 costs=costs(price_currency="INR", tax_cost_per_unit=D("1.2")))
    kw.update(over)
    return kw


def crypto_horizon(start=DEC, bars=12):
    return HorizonSpec.build(timeframe="5m", horizon_bars=bars, start_utc=start, session_kind=SessionKind.CONTINUOUS,
                             calendar_id="CRYPTO_24_7", calendar_version="1.0.0")


def perp_kw(**over):
    kw = long_kw(instrument_id=BTC_PERP, market="CRYPTO", segment="CRYPTO_PERPETUALS", inputs=inputs(**spec_inputs("btc_perp")),
                 horizon=crypto_horizon(), costs=costs(price_currency="USDT", funding_cost_per_unit=D("0.001")))
    kw.update(over)
    return kw


# ================================================================================================ P1-1 state integrity

def test_original_unsafe_case_valid_state_after_expiry_cannot_approve() -> None:
    p = make(long_kw())
    valid = state_at(p, T10)
    after = p.expires_at_utc + timedelta(seconds=1)
    with pytest.raises(PredictionContractError):                    # the record itself refuses VALID after expiry
        rehash_state(valid, evaluated_at_utc=after, latest_market_data_received_at_utc=after)
    forged = rehash_state(valid, evaluated_at_utc=after, latest_market_data_received_at_utc=after,
                          prediction_expires_at_utc=p.expires_at_utc + timedelta(hours=1),
                          prediction_horizon_end_utc=p.expires_at_utc + timedelta(hours=1))   # self-consistent lie
    with pytest.raises(RiskAssessmentContractError) as e:           # ... but never matches the prediction
        assess(p, forged)
    assert code(e) == V.STATE_MISMATCH.value
    with pytest.raises(PredictionContractError):
        verify_prediction_state(forged, p)


def test_valid_state_assessed_after_expiry_is_rejected() -> None:
    p = make(long_kw())
    st = state_at(p, p.expires_at_utc - timedelta(seconds=2))
    assert st.state is PredictionState.VALID
    ra = assess(p, st, at=p.expires_at_utc + timedelta(seconds=1))
    assert ra.status is RiskStatus.REJECTED and ra.rejection_reasons == (RiskRejectionCode.PREDICTION_EXPIRED,)
    assert not is_execution_eligible(p, st, ra, calendar=XNYS)
    with pytest.raises(RiskAssessmentContractError, match="expiry"):
        RiskAssessment.from_dict(rehash_assessment(ra, status="APPROVED", rejection_reasons=[]))


def test_forged_state_with_inconsistent_expiry_reasons() -> None:
    p = make(long_kw())
    end = state_at(p, p.horizon.expected_end_utc)
    assert end.expiry_reasons == (ExpiryReasonCode.EXPIRATION_REACHED, ExpiryReasonCode.HORIZON_ELAPSED)
    for change in (dict(expiry_reasons=(ExpiryReasonCode.EXPIRATION_REACHED,)),
                   dict(expiry_reasons=(ExpiryReasonCode.HORIZON_ELAPSED,)),
                   dict(state=PredictionState.VALID, expiry_reasons=())):
        with pytest.raises(PredictionContractError):
            rehash_state(end, **change)
    with pytest.raises(PredictionContractError):
        rehash_state(state_at(p, T10), state=PredictionState.EXPIRED, expiry_reasons=(ExpiryReasonCode.EXPIRATION_REACHED,))


def test_stale_state_used_for_a_later_assessment() -> None:
    p = make(long_kw())
    st = state_at(p, T10)
    later = assess(p, st, at=T10 + timedelta(seconds=30))
    assert later.rejection_reasons == (RiskRejectionCode.STALE_PREDICTION_STATE,)
    with pytest.raises(RiskAssessmentContractError, match="older than"):
        RiskAssessment.from_dict(rehash_assessment(later, status="APPROVED", rejection_reasons=[]))
    assert assess(p, st, at=T10 + timedelta(seconds=5)).status is RiskStatus.APPROVED      # within 5 s
    with pytest.raises(RiskAssessmentContractError):                # evaluated after the assessment
        assess(p, state_at(p, T10 + timedelta(seconds=3)), at=T10)
    with pytest.raises(RiskAssessmentContractError):
        assess(p, st, max_state_age_seconds=61)


def test_invalidated_prediction_forged_as_valid() -> None:
    p = make(long_kw())
    inv = state_at(p, T10, last_price=D("98.9"))                    # beyond the stop
    assert inv.state is PredictionState.INVALIDATED and InvalidationReasonCode.PRICE_BEYOND_STOP in inv.invalidation_reasons
    forged = rehash_state(inv, state=PredictionState.VALID, invalidation_reasons=())  # evidence needs the prediction
    with pytest.raises(RiskAssessmentContractError) as e:
        assess(p, forged)
    assert code(e) == V.STATE_MISMATCH.value
    untradable = state_at(p, T10, instrument_tradable=False)
    with pytest.raises(PredictionContractError):                    # evidence alone contradicts VALID
        rehash_state(untradable, state=PredictionState.VALID, invalidation_reasons=())
    stale = state_at(p, T10, latest_market_data_received_at_utc=T10 - timedelta(minutes=5))
    with pytest.raises(PredictionContractError):
        rehash_state(stale, state=PredictionState.VALID, invalidation_reasons=())


def test_state_id_binding_and_altered_state_record() -> None:
    p = make(long_kw())
    st = state_at(p, T10)
    ok = assess(p, st)
    assert ok.prediction_state_id == st.state_id
    other = state_at(p, T10 + timedelta(seconds=1))
    with pytest.raises(RiskAssessmentContractError) as e:
        verify_risk_assessment(ok, p, other, calendar=XNYS)
    assert code(e) == V.STATE_MISMATCH.value
    assert not is_execution_eligible(p, other, ok, calendar=XNYS)
    with pytest.raises(PredictionContractError) as e:               # id no longer matches the content
        PredictionStateRecord.from_dict({**json.loads(st.to_json()), "last_price": "100.01"})
    assert code(e) == V.STATE_MISMATCH.value
    altered = rehash_state(st, last_price=D("100.05"))             # consistent id, different evidence
    with pytest.raises(PredictionContractError):
        verify_risk_assessment(ok, p, altered, calendar=XNYS)
    rebound = RiskAssessment.from_dict(rehash_assessment(ok, prediction_state_id=other.state_id))
    with pytest.raises(RiskAssessmentContractError) as e:           # assessment re-pointed at another state id
        verify_risk_assessment(rebound, p, st, calendar=XNYS)
    assert code(e) == V.STATE_MISMATCH.value


def test_valid_fresh_state_still_permits_approval() -> None:
    p = make(long_kw())
    st = state_at(p, T10)
    verify_prediction_state(st, p)
    ok = assess(p, st)
    assert ok.status is RiskStatus.APPROVED and ok.session_verification is SessionVerification.VERIFIED
    assert is_execution_eligible(p, st, ok, calendar=XNYS)
    assert PredictionStateRecord.from_json(st.to_json()) == st and RiskAssessment.from_json(ok.to_json()) == ok


# ================================================================================================ P1-2 limit evidence

@pytest.mark.parametrize("kind,observed,limit", [
    (LimitKind.DAILY_LOSS_LIMIT, "160", "150"),
    (LimitKind.DAILY_LOSS_LIMIT, "150", "150"),           # at the limit is already a breach (observed < limit)
    (LimitKind.POSITION_LIMIT, "4", "3"),
    (LimitKind.EXPOSURE_LIMIT, "9999", "5000"),
    (LimitKind.MIN_EXPECTED_NET_R, "0.5", "0.8"),
    (LimitKind.MAX_SPREAD, "0.05", "0.02"),
    (LimitKind.MAX_TRADES_PER_DAY, "4", "3"),
])
def test_contradictory_pass_is_rejected(kind, observed, limit) -> None:
    hard = kind in (LimitKind.DAILY_LOSS_LIMIT, LimitKind.POSITION_LIMIT, LimitKind.EXPOSURE_LIMIT)
    with pytest.raises(RiskAssessmentContractError) as e:
        LimitCheck("custom_id_x", kind, "1", CheckResult.PASS, hard, D(observed), D(limit), None)
    assert code(e) == V.INCONSISTENT_LIMIT_EVIDENCE.value
    d = {"limit_id": "custom_id_x", "limit_kind": kind.value, "limit_version": "1", "result": "PASS",
         "is_hard_control": hard, "observed_value": observed, "limit_value": limit, "observed_flag": None}
    with pytest.raises(RiskAssessmentContractError):                # same check on JSON deserialization
        LimitCheck.from_dict(d)
    assert LimitCheck.evaluate("c", kind, "1", observed_value=D(observed), limit_value=D(limit)).result is CheckResult.FAIL


def test_original_unsafe_case_exposure_9999_cannot_approve() -> None:
    p = make(long_kw())
    st = state_at(p, T10)
    ok = assess(p, st)
    d = json.loads(ok.to_json())
    exp = next(c for c in d["limit_checks"] if c["limit_kind"] == "EXPOSURE_LIMIT")
    exp["observed_value"] = "9999"                                 # still claims PASS against limit 5000
    with pytest.raises(RiskAssessmentContractError) as e:
        RiskAssessment.from_dict(rehash_assessment(ok, limit_checks=d["limit_checks"]))
    assert code(e) == V.INCONSISTENT_LIMIT_EVIDENCE.value
    honest = [c if c.limit_kind is not LimitKind.EXPOSURE_LIMIT else
              LimitCheck.evaluate("exposure", LimitKind.EXPOSURE_LIMIT, "1", observed_value=D("9999"), limit_value=D("5000"))
              for c in HARD]
    rej = assess(p, st, honest)
    assert rej.status is RiskStatus.REJECTED and rej.rejection_reasons == (RiskRejectionCode.EXPOSURE_LIMIT,)
    assert not is_execution_eligible(p, st, rej, calendar=XNYS)


def test_correct_pass_fail_and_boundaries() -> None:
    cases = [
        (LimitKind.DAILY_LOSS_LIMIT, "149.99", "150", CheckResult.PASS),
        (LimitKind.POSITION_LIMIT, "3", "3", CheckResult.PASS),
        (LimitKind.EXPOSURE_LIMIT, "5000", "5000", CheckResult.PASS),
        (LimitKind.MIN_EXPECTED_NET_R, "0.8", "0.8", CheckResult.PASS),
        (LimitKind.MIN_EXPECTED_NET_R, "-0.1", "-0.2", CheckResult.PASS),
        (LimitKind.MAX_SPREAD, "0.02", "0.02", CheckResult.PASS),
        (LimitKind.MAX_TRADES_PER_DAY, "3", "3", CheckResult.PASS),
    ]
    for kind, o, l, want in cases:
        assert LimitCheck.evaluate("x", kind, "1", observed_value=D(o), limit_value=D(l)).result is want
    flags = [(LimitKind.KILL_SWITCH, False, CheckResult.PASS), (LimitKind.KILL_SWITCH, True, CheckResult.FAIL),
             (LimitKind.RESTRICTED_INSTRUMENT, False, CheckResult.PASS), (LimitKind.RESTRICTED_INSTRUMENT, True, CheckResult.FAIL),
             (LimitKind.TRADING_WINDOW, True, CheckResult.PASS), (LimitKind.TRADING_WINDOW, False, CheckResult.FAIL)]
    for kind, flag, want in flags:
        assert LimitCheck.evaluate("x", kind, "1", observed_flag=flag).result is want
        with pytest.raises(RiskAssessmentContractError):
            LimitCheck("x", kind, "1", CheckResult.FAIL if want is CheckResult.PASS else CheckResult.PASS,
                       kind in (LimitKind.KILL_SWITCH, LimitKind.RESTRICTED_INSTRUMENT), None, None, flag)


def test_missing_or_mistyped_limit_evidence() -> None:
    bad = [
        (LimitKind.KILL_SWITCH, dict()),                                           # no observation is never a PASS
        (LimitKind.KILL_SWITCH, dict(observed_value=D("0"), limit_value=D("0"))),
        (LimitKind.RESTRICTED_INSTRUMENT, dict()),
        (LimitKind.TRADING_WINDOW, dict()),
        (LimitKind.EXPOSURE_LIMIT, dict(observed_value=D("1"))),
        (LimitKind.EXPOSURE_LIMIT, dict(limit_value=D("1"))),
        (LimitKind.EXPOSURE_LIMIT, dict(observed_value=D("1"), limit_value=D("2"), observed_flag=False)),
        (LimitKind.POSITION_LIMIT, dict(observed_value=D("1.5"), limit_value=D("3"))),
        (LimitKind.EXPOSURE_LIMIT, dict(observed_value=D("-1"), limit_value=D("5000"))),
    ]
    for kind, kw in bad:
        with pytest.raises(RiskAssessmentContractError) as e:
            LimitCheck.evaluate("x", kind, "1", **kw)
        assert code(e) in (V.MISSING_LIMIT_EVIDENCE.value, V.INCONSISTENT_LIMIT_EVIDENCE.value)
    for hard_kind in (LimitKind.KILL_SWITCH, LimitKind.DAILY_LOSS_LIMIT, LimitKind.POSITION_LIMIT,
                      LimitKind.EXPOSURE_LIMIT, LimitKind.RESTRICTED_INSTRUMENT):
        good = LimitCheck.evaluate("soft_looking_name", hard_kind, "1",
                                   **(dict(observed_flag=False) if hard_kind in (LimitKind.KILL_SWITCH, LimitKind.RESTRICTED_INSTRUMENT)
                                      else dict(observed_value=D("1"), limit_value=D("2"))))
        assert good.is_hard_control                                 # the id cannot make a hard control soft
        with pytest.raises(RiskAssessmentContractError):
            dataclasses.replace(good, is_hard_control=False)
    p = make(long_kw())
    with pytest.raises(RiskAssessmentContractError) as e:           # MIN_EXPECTED_NET_R must use the prediction's value
        assess(p, state_at(p, T10), HARD + [LimitCheck.evaluate("min_r", LimitKind.MIN_EXPECTED_NET_R, "1",
                                                                 observed_value=D("2"), limit_value=D("0.5"))])
    assert code(e) == V.PREDICTION_MISMATCH.value
    window = LimitCheck.evaluate("window", LimitKind.TRADING_WINDOW, "1", observed_flag=False)
    assert assess(p, state_at(p, T10), HARD + [window]).rejection_reasons == (RiskRejectionCode.TRADING_WINDOW,)


# ================================================================================================ P1-3 currency

def test_cost_currency_bound_to_instrument_specification() -> None:
    assert make(long_kw()).expected_net_r.status is NetRStatus.AVAILABLE              # AAPL + USD
    with pytest.raises(PredictionContractError) as e:                                   # AAPL + INR (reproduced)
        make(long_kw(costs=costs(price_currency="INR")))
    assert code(e) == V.COST_CURRENCY_MISMATCH.value
    assert make(nifty_kw()).expected_net_r.status is NetRStatus.AVAILABLE              # NIFTY futures + INR
    with pytest.raises(PredictionContractError) as e:
        make(nifty_kw(costs=costs(price_currency="USD", tax_cost_per_unit=D("1.2"))))
    assert code(e) == V.COST_CURRENCY_MISMATCH.value
    ce = nifty_kw(instrument_id=NIFTY_CE, segment="IN_INDEX_OPTIONS", inputs=inputs(D_IN, **spec_inputs("nifty_ce")),
                  entry=entry(D_IN, "120"), levels=RiskLevels(D("100"), D("160")))
    assert make(ce).expected_net_r.status is NetRStatus.AVAILABLE
    with pytest.raises(PredictionContractError):
        make({**ce, "costs": costs(price_currency="USDT", tax_cost_per_unit=D("0.1"))})
    assert make(perp_kw()).costs.price_currency == "USDT"                               # crypto quote currency
    with pytest.raises(PredictionContractError):
        make(perp_kw(costs=costs(price_currency="USD", funding_cost_per_unit=D("0.001"))))
    spot = make(perp_kw(instrument_id=BTC_SPOT, segment="CRYPTO_SPOT", inputs=inputs(**spec_inputs("btc_spot")),
                        costs=costs(price_currency="USDT")))
    assert spot.expected_net_r.status is NetRStatus.AVAILABLE


def test_unresolved_or_mismatched_specification() -> None:
    with pytest.raises(PredictionContractError) as e:               # hash does not match the supplied spec
        inputs(instrument_specification=SPECS["aapl"], instrument_spec_hash=compute_spec_hash(SPECS["nifty_fut"]))
    assert code(e) == V.INVALID_PROVENANCE.value
    no_currency = {k: v for k, v in SPECS["aapl"].items() if k != "price_currency"}
    with pytest.raises(PredictionContractError):                    # cannot resolve the Step 1 currency key
        inputs(instrument_specification=no_currency, instrument_spec_hash=compute_spec_hash(no_currency))
    null_currency = {**SPECS["aapl"], "price_currency": None}
    p = make(long_kw(inputs=inputs(instrument_specification=null_currency,
                                   instrument_spec_hash=compute_spec_hash(null_currency)),
                     uncertainty=Uncertainty.unavailable(UncertaintyUnavailableReason.EXPECTED_NET_R_UNAVAILABLE)))
    assert p.expected_net_r.status is NetRStatus.UNAVAILABLE
    assert NetRUnavailableReason.CURRENCY_UNVERIFIED in p.expected_net_r.unavailable_reasons   # never a verified net R
    with pytest.raises(PredictionContractError) as e:               # AAPL prediction with a NIFTY spec
        make(long_kw(inputs=inputs(**spec_inputs("nifty_fut"))))
    assert code(e) == V.INSTRUMENT_SCOPE_MISMATCH.value


def test_currency_relationship_survives_json_round_trip() -> None:
    p = make(nifty_kw())
    again = Prediction.from_json(p.to_json())
    assert again == p and again.spec_price_currency == "INR" == again.costs.price_currency
    d = json.loads(p.to_json())
    d["inputs"]["instrument_specification"]["price_currency"] = "USD"   # tampered spec in JSON
    with pytest.raises(PredictionContractError) as e:
        Prediction.from_dict(d)
    assert code(e) == V.INVALID_PROVENANCE.value
    d = json.loads(p.to_json())
    d["costs"]["price_currency"] = "USD"
    with pytest.raises(PredictionContractError):
        Prediction.from_dict(d)
    with pytest.raises(TypeError):                                   # the spec snapshot is read-only
        p.inputs.instrument_specification["price_currency"] = "USD"  # type: ignore[index]


# ================================================================================================ P1-4 artifacts

@pytest.mark.parametrize("change,expected", [
    (dict(model=dataclasses.replace(MODEL, model_trained_at_utc=DEC + timedelta(hours=1), model_available_at_utc=DEC + timedelta(hours=2))),
     DQ.LOOKAHEAD_MODEL_ARTIFACT),
    (dict(outcome_probabilities=oprobs(cal=dataclasses.replace(CAL, available_at_utc=DEC + timedelta(hours=1)))),
     DQ.LOOKAHEAD_CALIBRATION_ARTIFACT),
    (dict(model=dataclasses.replace(MODEL, decision_policy_effective_from_utc=DEC + timedelta(seconds=1))),
     DQ.LOOKAHEAD_DECISION_POLICY),
    (dict(model=dataclasses.replace(MODEL, feature_set_available_at_utc=DEC + timedelta(seconds=1))), DQ.LOOKAHEAD_FEATURE_SET),
    (dict(costs=costs(cost_model_effective_from_utc=DEC + timedelta(seconds=1))), DQ.LOOKAHEAD_COST_MODEL),
])
def test_artifacts_unavailable_at_decision_are_not_live_faithful(change, expected) -> None:
    assert MODEL.training_data_end_utc < DEC                        # the data cutoff alone is fine ...
    with pytest.raises(PredictionContractError) as e:               # ... but the artifact did not exist yet
        make(long_kw(**change))
    assert code(e) == expected.value
    research_inputs = inputs(availability_mode="EVENT_TIME")
    research = make(long_kw(**change, inputs=research_inputs))      # allowed only as retrospective research
    assert research.usage_class is UsageClass.RESEARCH_RETROSPECTIVE
    ra = assess(research, state_at(research, T10))
    assert ra.status is RiskStatus.REJECTED and RiskRejectionCode.RESEARCH_ONLY_PREDICTION in ra.rejection_reasons


def test_all_artifacts_available_before_decision_and_ordering() -> None:
    p = make(long_kw())
    assert p.is_live_faithful and p.model.model_available_at_utc <= DEC
    with pytest.raises(PredictionContractError):                    # trained before its data cutoff
        dataclasses.replace(MODEL, model_trained_at_utc=MODEL.training_data_end_utc - timedelta(days=1))
    with pytest.raises(PredictionContractError):                    # available before it was trained
        dataclasses.replace(MODEL, model_available_at_utc=MODEL.model_trained_at_utc - timedelta(seconds=1))
    with pytest.raises(PredictionContractError):                    # calibrator available before its data cutoff
        dataclasses.replace(CAL, available_at_utc=CAL.fitted_until_utc - timedelta(seconds=1))


# ================================================================================================ P2-5 calendar

def test_cross_market_wrong_calendars_rejected() -> None:
    wrong = [
        (long_kw(horizon=us_horizon(calendar_id="XNSE", calendar_version="1.0.0", session_id="XNSE_2026-01-05")), "AAPL on XNSE"),
        (long_kw(horizon=us_horizon(calendar_id="XNAS", session_id="XNAS_2026-01-05")), "AAPL spec says XNYS"),
        (nifty_kw(horizon=us_horizon(D_IN, calendar_id="XNYS", session_id="XNYS_2026-01-04",
                                     session_open_utc=IST_OPEN, session_close_utc=IST_CLOSE)), "NIFTY on XNYS"),
        (perp_kw(horizon=HorizonSpec.build(timeframe="5m", horizon_bars=12, start_utc=DEC, session_kind=SessionKind.CONTINUOUS,
                                            calendar_id="XNYS", calendar_version="2026.1")), "crypto on XNYS"),
    ]
    for kw, label in wrong:
        with pytest.raises(PredictionContractError) as e:
            make(kw)
        assert code(e) in (V.CALENDAR_MISMATCH.value, V.INVALID_HORIZON.value), label
    with pytest.raises(PredictionContractError) as e:               # session_id date must be the exchange-local date
        us_horizon(session_id="XNYS_2026-01-06")
    assert code(e) == V.CALENDAR_MISMATCH.value
    es_spec = SPECS["es_fut"]
    assert es_spec["trading_calendar"] == "XCME"                    # Step 1 spec id; adapter id is XCME_GLOBEX
    chi_open, chi_close = datetime(2026, 1, 5, 14, 30, tzinfo=UTC), datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
    es = make(long_kw(instrument_id=ES_FUT, segment="US_FUTURES", inputs=inputs(**spec_inputs("es_fut")),
                      entry=entry(price="5800"), levels=RiskLevels(D("5790"), D("5820")),
                      horizon=us_horizon(calendar_id="XCME_GLOBEX", session_id="XCME_GLOBEX_2026-01-05",
                                         session_open_utc=chi_open, session_close_utc=chi_close)))
    assert es.horizon.calendar_id == "XCME_GLOBEX"                  # documented alias XCME == XCME_GLOBEX


def test_session_evidence_must_be_calendar_verified_for_approval() -> None:
    p = make(long_kw())
    st = state_at(p, T10)
    unverified = assess(p, st, calendar=None)
    assert unverified.session_verification is SessionVerification.UNVERIFIED
    assert RiskRejectionCode.SESSION_UNVERIFIED in unverified.rejection_reasons
    xnas = USEquityCalendarAdapter(calendar_id="XNAS")              # wrong (and partially verified) calendar
    assert assess(p, st, calendar=xnas).session_verification is SessionVerification.UNVERIFIED
    wrong_bounds = make(long_kw(horizon=us_horizon(session_close_utc=datetime(2026, 1, 5, 20, 0, tzinfo=UTC))))
    st2 = state_at(wrong_bounds, T10)
    assert RiskRejectionCode.SESSION_UNVERIFIED in assess(wrong_bounds, st2).rejection_reasons
    ok = assess(p, st)
    assert ok.session_verification is SessionVerification.VERIFIED
    assert not is_execution_eligible(p, st, ok)                     # verification without the calendar fails closed
    perp = make(perp_kw())
    pst = state_at(perp, T10)
    crypto = assess(perp, pst, calendar=None)
    assert crypto.session_verification is SessionVerification.NOT_REQUIRED and crypto.status is RiskStatus.APPROVED
    assert is_execution_eligible(perp, pst, crypto)


# ================================================================================================ P2-6 alignment

def test_bar_alignment_convention() -> None:
    h = us_horizon()                                                # decision 10:00:02 New York
    assert h.first_bar_open_utc == datetime(2026, 1, 5, 15, 5, tzinfo=UTC)               # next canonical 5m bar 10:05
    assert h.expected_end_utc == datetime(2026, 1, 5, 16, 5, tzinfo=UTC)                 # 12 future bars -> 11:05
    aligned = us_horizon(start=datetime(2026, 1, 5, 15, 0, tzinfo=UTC))
    assert aligned.first_bar_open_utc == aligned.start_utc and aligned.expected_end_utc == datetime(2026, 1, 5, 16, 0, tzinfo=UTC)
    last = us_horizon(start=datetime(2026, 1, 5, 20, 55, tzinfo=UTC), bars=1)            # last valid bar 15:55-16:00
    assert last.expected_end_utc == datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
    just_before = us_horizon(start=datetime(2026, 1, 5, 20, 54, 59, tzinfo=UTC), bars=1)
    assert just_before.first_bar_open_utc == datetime(2026, 1, 5, 20, 55, tzinfo=UTC)
    with pytest.raises(PredictionContractError) as e:               # 15:55:01: the next bar would open at the close
        us_horizon(start=datetime(2026, 1, 5, 20, 55, 1, tzinfo=UTC), bars=1)
    assert code(e) == V.SESSION_BOUNDARY_VIOLATION.value
    nse_1h = us_horizon(start=datetime(2026, 1, 5, 4, 30, tzinfo=UTC), bars=2, timeframe="1h", calendar_id="XNSE",
                        calendar_version="1.0.0", session_id="XNSE_2026-01-05", session_open_utc=IST_OPEN,
                        session_close_utc=IST_CLOSE)
    assert nse_1h.first_bar_open_utc == datetime(2026, 1, 5, 4, 45, tzinfo=UTC)          # 10:15 IST: anchored at 09:15
    with pytest.raises(PredictionContractError):                    # a tampered first bar is rejected
        dataclasses.replace(h, first_bar_open_utc=h.start_utc, expected_end_utc=h.start_utc + timedelta(hours=1))
    perp_h = crypto_horizon(start=datetime(2026, 1, 5, 23, 58, tzinfo=UTC), bars=3)
    assert perp_h.alignment_anchor_utc == datetime(2026, 1, 5, 0, 0, tzinfo=UTC)          # UTC midnight anchor
    assert perp_h.first_bar_open_utc == datetime(2026, 1, 6, 0, 0, tzinfo=UTC)            # 23:58 -> next 5m bar 00:00
    assert perp_h.expected_end_utc == datetime(2026, 1, 6, 0, 15, tzinfo=UTC)


# ================================================================================================ P2-7 exit model

def test_exit_fill_model_is_explicit_and_fixed() -> None:
    p = make(long_kw())
    assert p.expected_net_r.exit_fill_model == EXIT_FILL_MODEL_V1 == "LEVEL_FILLS_ROUND_TRIP_COSTS_V1"
    assert make(no_trade_kw()).expected_net_r.exit_fill_model == EXIT_FILL_MODEL_V1
    d = json.loads(p.to_json())
    d["expected_net_r"]["exit_fill_model"] = "GAP_AWARE_V2"
    with pytest.raises(PredictionContractError) as e:
        Prediction.from_dict(d)
    assert code(e) == V.NET_R_MISMATCH.value
    with pytest.raises(PredictionContractError, match="exit_fill_model"):   # the record itself pins the v1 model
        dataclasses.replace(p.expected_net_r, exit_fill_model="GAP_AWARE_V2")


def test_valid_long_short_no_trade_still_work() -> None:
    for kw in (long_kw(), short_kw(), no_trade_kw(), nifty_kw(), perp_kw()):
        p = make(kw)
        assert Prediction.from_json(p.to_json()) == p
    assert make(long_kw()).expected_net_r.expected_net_r == D("0.745")
    assert make(short_kw()).expected_net_r.expected_net_r == D("0.742")
    nt = make(no_trade_kw())
    na = assess(nt, state_at(nt, T10, last_price=None))
    assert na.status is RiskStatus.NOT_APPLICABLE and not is_execution_eligible(nt, state_at(nt, T10, last_price=None), na, calendar=XNYS)
