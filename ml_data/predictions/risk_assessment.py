"""Risk-assessment contract v1.0.0: the boundary between an ML prediction and permission to trade.

This module defines and validates the RECORD a Risk Engine must produce. It is not a Risk Engine: it enforces no
live limits, sizes nothing and places nothing. Boundaries enforced here (fail closed):
  * A RiskAssessment references a prediction AND the exact content-addressed PredictionStateRecord it relied on;
    the prediction is never rewritten. The state is re-derived from the prediction and its evidence before use.
  * LONG/SHORT is not approval. NO_TRADE can never be approved (status NOT_APPLICABLE, always).
  * APPROVED needs: a LIVE_FAITHFUL, directional prediction, not expired AT THE ASSESSMENT TIME, with a VALID state
    evaluated no more than max_state_age_seconds before the assessment; calibrated probabilities; an AVAILABLE
    expected net R; a calendar-verified session (exchange markets); a PASS for every hard control (each evaluated);
    every failed soft check covered by an explicit, scoped, time-limited, in-force override.
  * Every LimitCheck carries the typed evidence its result is derived from; a contradictory PASS/FAIL is rejected.
  * Overrides can never target a hard control (kill switch, daily loss, position, exposure, restricted instrument).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ._records import BOOL, DEC, DT, ENUM, INT, OPT, REC, SHA, STR, TUP, Record, _check, content_id
from .exceptions import PredictionContractError, RiskAssessmentContractError
from .prediction import (
    Direction,
    NetRStatus,
    Prediction,
    ProbabilityKind,
    SessionKind,
    UsageClass,
    canonical_calendar,
)
from .reason_codes import RiskRejectionCode as R, ValidationFailureCode as V
from .state import PredictionState, PredictionStateRecord, verify_prediction_state

RISK_ASSESSMENT_CONTRACT_VERSION = "1.0.0"
MAX_OVERRIDE_DURATION = timedelta(hours=8)
DEFAULT_MAX_STATE_AGE_SECONDS = 5
MAX_STATE_AGE_LIMIT_SECONDS = 60


class RiskStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"   # NO_TRADE: there is nothing to approve; never executable


class SessionVerification(str, Enum):
    VERIFIED = "VERIFIED"            # horizon session bounds equal the Step 1 calendar's verified session_bounds
    NOT_REQUIRED = "NOT_REQUIRED"    # continuous (24/7) markets
    UNVERIFIED = "UNVERIFIED"        # no / wrong / unverified calendar, or bounds disagree: never approvable


class LimitKind(str, Enum):
    KILL_SWITCH = "KILL_SWITCH"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    POSITION_LIMIT = "POSITION_LIMIT"
    EXPOSURE_LIMIT = "EXPOSURE_LIMIT"
    RESTRICTED_INSTRUMENT = "RESTRICTED_INSTRUMENT"
    MIN_EXPECTED_NET_R = "MIN_EXPECTED_NET_R"
    MAX_SPREAD = "MAX_SPREAD"
    TRADING_WINDOW = "TRADING_WINDOW"
    MAX_TRADES_PER_DAY = "MAX_TRADES_PER_DAY"


HARD_CONTROLS = frozenset({LimitKind.KILL_SWITCH, LimitKind.DAILY_LOSS_LIMIT, LimitKind.POSITION_LIMIT,
                           LimitKind.EXPOSURE_LIMIT, LimitKind.RESTRICTED_INSTRUMENT})
REJECTION_FOR_LIMIT: Dict[LimitKind, R] = {
    LimitKind.KILL_SWITCH: R.KILL_SWITCH_ACTIVE, LimitKind.DAILY_LOSS_LIMIT: R.DAILY_LOSS_LIMIT,
    LimitKind.POSITION_LIMIT: R.POSITION_LIMIT, LimitKind.EXPOSURE_LIMIT: R.EXPOSURE_LIMIT,
    LimitKind.RESTRICTED_INSTRUMENT: R.RESTRICTED_INSTRUMENT, LimitKind.MIN_EXPECTED_NET_R: R.MIN_EXPECTED_NET_R,
    LimitKind.MAX_SPREAD: R.MAX_SPREAD, LimitKind.TRADING_WINDOW: R.TRADING_WINDOW,
    LimitKind.MAX_TRADES_PER_DAY: R.MAX_TRADES_PER_DAY,
}

# Comparison semantics (documented in the contract §12.1). observed/limit are Decimals in the stated units.
#   kind                 evidence          PASS iff                 observed means
#   DAILY_LOSS_LIMIT     numeric (>=0)     observed <  limit        today's realized + open loss, positive = loss
#   POSITION_LIMIT       integer (>=0)     observed <= limit        open positions INCLUDING the proposed one
#   EXPOSURE_LIMIT       numeric (>=0)     observed <= limit        gross exposure INCLUDING the proposed trade
#   MIN_EXPECTED_NET_R   numeric (signed)  observed >= limit        the prediction's expected_net_r (must match it)
#   MAX_SPREAD           numeric (>=0)     observed <= limit        current quoted spread, price units
#   MAX_TRADES_PER_DAY   integer (>=0)     observed <= limit        trades today INCLUDING the proposed one
#   KILL_SWITCH          flag              observed_flag is False   kill switch engaged
#   RESTRICTED_INSTRUMENT flag             observed_flag is False   instrument is on a restricted list
#   TRADING_WINDOW       flag              observed_flag is True    assessment time is inside the permitted window
_NUMERIC_RULES = {
    LimitKind.DAILY_LOSS_LIMIT: ("lt", False, True), LimitKind.POSITION_LIMIT: ("le", True, True),
    LimitKind.EXPOSURE_LIMIT: ("le", False, True), LimitKind.MIN_EXPECTED_NET_R: ("ge", False, False),
    LimitKind.MAX_SPREAD: ("le", False, True), LimitKind.MAX_TRADES_PER_DAY: ("le", True, True),
}
_FLAG_PASS = {LimitKind.KILL_SWITCH: False, LimitKind.RESTRICTED_INSTRUMENT: False, LimitKind.TRADING_WINDOW: True}


class CheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


def _rfail(code: Enum, msg: str) -> RiskAssessmentContractError:
    return RiskAssessmentContractError(code, msg)


def derive_check_result(kind: LimitKind, observed_value: Optional[Decimal], limit_value: Optional[Decimal],
                        observed_flag: Optional[bool]) -> CheckResult:
    """The only result consistent with the evidence. Missing evidence is an error, never a PASS."""
    if kind in _FLAG_PASS:
        if observed_flag is None or observed_value is not None or limit_value is not None:
            raise _rfail(V.MISSING_LIMIT_EVIDENCE, f"{kind.value} needs observed_flag only (no numeric values)")
        return CheckResult.PASS if observed_flag is _FLAG_PASS[kind] else CheckResult.FAIL
    op, integral, non_negative = _NUMERIC_RULES[kind]
    if observed_value is None or limit_value is None or observed_flag is not None:
        raise _rfail(V.MISSING_LIMIT_EVIDENCE, f"{kind.value} needs observed_value and limit_value (no flag)")
    for name, v in (("observed_value", observed_value), ("limit_value", limit_value)):
        if non_negative and v < 0:
            raise _rfail(V.INCONSISTENT_LIMIT_EVIDENCE, f"{kind.value} {name} must be >= 0")
        if integral and v != v.to_integral_value():
            raise _rfail(V.INCONSISTENT_LIMIT_EVIDENCE, f"{kind.value} {name} must be a whole number")
    ok = {"lt": observed_value < limit_value, "le": observed_value <= limit_value,
          "ge": observed_value >= limit_value}[op]
    return CheckResult.PASS if ok else CheckResult.FAIL


@dataclass(frozen=True)
class LimitCheck(Record):
    limit_id: str
    limit_kind: LimitKind
    limit_version: str
    result: CheckResult
    is_hard_control: bool
    observed_value: Optional[Decimal]
    limit_value: Optional[Decimal]
    observed_flag: Optional[bool]

    FIELDS = {"limit_id": STR, "limit_kind": ENUM(LimitKind), "limit_version": STR, "result": ENUM(CheckResult),
              "is_hard_control": BOOL, "observed_value": OPT(DEC), "limit_value": OPT(DEC), "observed_flag": OPT(BOOL)}

    def _validate(self) -> None:
        # semantics come from limit_kind only; a custom limit_id can never change hardness or comparison
        if self.is_hard_control != (self.limit_kind in HARD_CONTROLS):
            raise _rfail(V.INVALID_RISK_ASSESSMENT, f"{self.limit_kind.value} is_hard_control must be {self.limit_kind in HARD_CONTROLS}")
        want = derive_check_result(self.limit_kind, self.observed_value, self.limit_value, self.observed_flag)
        if self.result is not want:
            raise _rfail(V.INCONSISTENT_LIMIT_EVIDENCE,
                         f"{self.limit_id}: result {self.result.value} contradicts its evidence (derived {want.value})")

    @classmethod
    def evaluate(cls, limit_id: str, kind: LimitKind, limit_version: str, *, observed_value: Optional[Decimal] = None,
                 limit_value: Optional[Decimal] = None, observed_flag: Optional[bool] = None) -> "LimitCheck":
        k = _check(ENUM(LimitKind), kind, "LimitCheck.limit_kind")
        ov = _check(OPT(DEC), observed_value, "LimitCheck.observed_value")
        lv = _check(OPT(DEC), limit_value, "LimitCheck.limit_value")
        fl = _check(OPT(BOOL), observed_flag, "LimitCheck.observed_flag")
        return cls(limit_id, k, limit_version, derive_check_result(k, ov, lv, fl), k in HARD_CONTROLS, ov, lv, fl)


@dataclass(frozen=True)
class RiskOverride(Record):
    """An explicit, auditable, scoped and time-limited exception for SOFT limits only."""

    override_id: str
    authorized_by: str
    authorization_reference: str
    justification: str
    instrument_id: str
    overridden_limit_ids: Tuple[str, ...]
    granted_at_utc: datetime
    expires_at_utc: datetime

    FIELDS = {"override_id": STR, "authorized_by": STR, "authorization_reference": STR, "justification": STR,
              "instrument_id": STR, "overridden_limit_ids": TUP(STR), "granted_at_utc": DT, "expires_at_utc": DT}

    def _validate(self) -> None:
        ids = self.overridden_limit_ids
        if not ids or len(set(ids)) != len(ids):
            raise _rfail(V.INVALID_OVERRIDE, "an override names one or more distinct limit_ids (no blanket overrides)")
        if any(x.strip() in ("*", "ALL") for x in ids):
            raise _rfail(V.INVALID_OVERRIDE, "wildcard overrides are not allowed")
        if not self.granted_at_utc < self.expires_at_utc:
            raise _rfail(V.INVALID_OVERRIDE, "override expires_at must be after granted_at")
        if self.expires_at_utc - self.granted_at_utc > MAX_OVERRIDE_DURATION:
            raise _rfail(V.INVALID_OVERRIDE, f"overrides are limited to {MAX_OVERRIDE_DURATION}")


@dataclass(frozen=True)
class RiskAssessment(Record):
    contract_version: str
    risk_assessment_id: str
    prediction_id: str
    instrument_id: str
    prediction_direction: Direction
    prediction_usage_class: UsageClass
    prediction_expected_net_r_status: NetRStatus
    prediction_probabilities_calibrated: bool
    prediction_expires_at_utc: datetime
    prediction_state_id: str
    prediction_state: PredictionState
    prediction_state_evaluated_at_utc: datetime
    max_state_age_seconds: int
    session_verification: SessionVerification
    risk_policy_id: str
    risk_policy_version: str
    assessed_at_utc: datetime
    status: RiskStatus
    rejection_reasons: Tuple[R, ...]
    limit_checks: Tuple[LimitCheck, ...]
    overrides: Tuple[RiskOverride, ...]
    notes: Optional[str]

    FIELDS = {
        "contract_version": STR, "risk_assessment_id": SHA, "prediction_id": SHA, "instrument_id": STR,
        "prediction_direction": ENUM(Direction), "prediction_usage_class": ENUM(UsageClass),
        "prediction_expected_net_r_status": ENUM(NetRStatus), "prediction_probabilities_calibrated": BOOL,
        "prediction_expires_at_utc": DT, "prediction_state_id": SHA, "prediction_state": ENUM(PredictionState),
        "prediction_state_evaluated_at_utc": DT, "max_state_age_seconds": INT,
        "session_verification": ENUM(SessionVerification), "risk_policy_id": STR, "risk_policy_version": STR,
        "assessed_at_utc": DT, "status": ENUM(RiskStatus), "rejection_reasons": TUP(ENUM(R)),
        "limit_checks": TUP(REC(LimitCheck)), "overrides": TUP(REC(RiskOverride)), "notes": OPT(STR),
    }

    def _validate(self) -> None:
        if self.contract_version != RISK_ASSESSMENT_CONTRACT_VERSION:
            raise _rfail(V.INVALID_CONTRACT_VERSION, f"unsupported risk assessment contract_version {self.contract_version!r}")
        if self.prediction_state_evaluated_at_utc > self.assessed_at_utc:
            raise _rfail(V.TIMESTAMP_ORDER, "the prediction state must be evaluated at or before the assessment")
        if not 1 <= self.max_state_age_seconds <= MAX_STATE_AGE_LIMIT_SECONDS:
            raise _rfail(V.INVALID_RISK_ASSESSMENT, f"max_state_age_seconds must be in [1, {MAX_STATE_AGE_LIMIT_SECONDS}]")
        if self.prediction_state is PredictionState.VALID and self.prediction_state_evaluated_at_utc >= self.prediction_expires_at_utc:
            raise _rfail(V.STATE_MISMATCH, "a state evaluated at or after the prediction's expiry cannot be VALID")
        if len(set(self.rejection_reasons)) != len(self.rejection_reasons):
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "rejection_reasons must be unique")
        ids = [c.limit_id for c in self.limit_checks]
        if len(set(ids)) != len(ids):
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "limit_checks must have unique limit_ids")
        checks = {c.limit_id: c for c in self.limit_checks}
        for o in self.overrides:
            if o.instrument_id != self.instrument_id:
                raise _rfail(V.INVALID_OVERRIDE, "an override is scoped to the assessed instrument only")
            for lid in o.overridden_limit_ids:
                if lid not in checks:
                    raise _rfail(V.INVALID_OVERRIDE, f"override names unknown limit_id {lid!r}")
                if checks[lid].is_hard_control:
                    raise _rfail(V.HARD_CONTROL_OVERRIDE, f"{lid} is a hard control ({checks[lid].limit_kind.value}) and can never be overridden")
        st = self.status
        if self.prediction_direction is Direction.NO_TRADE:
            if st is not RiskStatus.NOT_APPLICABLE:
                raise _rfail(V.INVALID_RISK_ASSESSMENT, "a NO_TRADE prediction is NOT_APPLICABLE: it can never be approved or made executable")
            if self.rejection_reasons or self.overrides:
                raise _rfail(V.INVALID_RISK_ASSESSMENT, "NOT_APPLICABLE carries no rejection reasons or overrides")
        elif st is RiskStatus.NOT_APPLICABLE:
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "NOT_APPLICABLE is only for NO_TRADE predictions")
        if st is RiskStatus.REJECTED and not self.rejection_reasons:
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "REJECTED needs at least one machine-readable rejection reason")
        if st is RiskStatus.APPROVED:
            self._validate_approval(checks)
        if self.risk_assessment_id != content_id(self, "risk_assessment_id"):
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "risk_assessment_id must be the SHA-256 of the assessment content")

    def _validate_approval(self, checks: Dict[str, LimitCheck]) -> None:
        if self.rejection_reasons:
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "APPROVED carries no rejection reasons")
        if self.prediction_usage_class is not UsageClass.LIVE_FAITHFUL:
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "research/retrospective predictions can never be approved")
        if self.prediction_state is not PredictionState.VALID:
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "only a VALID prediction can be approved")
        if self.assessed_at_utc >= self.prediction_expires_at_utc:
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "a prediction cannot be approved at or after its expiry")
        if (self.assessed_at_utc - self.prediction_state_evaluated_at_utc).total_seconds() > self.max_state_age_seconds:
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "the prediction state is older than max_state_age_seconds")
        if self.session_verification is SessionVerification.UNVERIFIED:
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "the trading session was not verified against the exchange calendar")
        if self.prediction_expected_net_r_status is not NetRStatus.AVAILABLE or not self.prediction_probabilities_calibrated:
            raise _rfail(V.INVALID_RISK_ASSESSMENT, "approval needs calibrated probabilities and an AVAILABLE expected net R")
        kinds = {c.limit_kind for c in checks.values()}
        missing = sorted(k.value for k in HARD_CONTROLS - kinds)
        if missing:
            raise _rfail(V.INVALID_RISK_ASSESSMENT, f"approval requires every hard control to be evaluated; missing {missing}")
        for c in checks.values():
            if c.result is CheckResult.FAIL:
                if c.is_hard_control:
                    raise _rfail(V.HARD_CONTROL_OVERRIDE, f"hard control {c.limit_id} failed; approval is impossible")
                if not any(c.limit_id in o.overridden_limit_ids and o.granted_at_utc <= self.assessed_at_utc < o.expires_at_utc
                           for o in self.overrides):
                    raise _rfail(V.INVALID_RISK_ASSESSMENT, f"soft limit {c.limit_id} failed without an in-force override")

    @property
    def is_approved(self) -> bool:
        return self.status is RiskStatus.APPROVED


def _probabilities_calibrated(p: Prediction) -> bool:
    kinds = [p.direction_probabilities.kind]
    if p.outcome_probabilities is not None:
        kinds.append(p.outcome_probabilities.kind)
    return all(k is ProbabilityKind.CALIBRATED for k in kinds)


def verify_session_with_calendar(prediction: Prediction, calendar: Any) -> SessionVerification:
    """Compare the horizon's session with the Step 1 calendar's VERIFIED session_bounds. Fails closed to UNVERIFIED."""
    h = prediction.horizon
    if h.session_kind is SessionKind.CONTINUOUS:
        return SessionVerification.NOT_REQUIRED
    if calendar is None:
        return SessionVerification.UNVERIFIED
    md = getattr(calendar, "metadata", None)
    if md is None or canonical_calendar(md.calendar_id) != canonical_calendar(h.calendar_id) \
            or md.calendar_version != h.calendar_version:
        return SessionVerification.UNVERIFIED
    bounds_fn = getattr(getattr(calendar, "inner", None), "session_bounds", None)
    if bounds_fn is None:
        return SessionVerification.UNVERIFIED
    try:
        day = calendar.trade_date_for(h.session_open_utc)
        bounds = bounds_fn(day, require_verified=True)
    except Exception:  # noqa: BLE001 - unverified year / calendar error: cannot be proven
        return SessionVerification.UNVERIFIED
    if bounds is None or (bounds[0], bounds[1]) != (h.session_open_utc, h.session_close_utc):
        return SessionVerification.UNVERIFIED
    if h.session_id != f"{canonical_calendar(h.calendar_id)}_{day.isoformat()}":
        return SessionVerification.UNVERIFIED
    return SessionVerification.VERIFIED


def assess_prediction(
    prediction: Prediction,
    state: PredictionStateRecord,
    *,
    risk_policy_id: str,
    risk_policy_version: str,
    assessed_at_utc: datetime,
    limit_checks: Sequence[LimitCheck],
    overrides: Sequence[RiskOverride] = (),
    calendar: Any = None,
    max_state_age_seconds: int = DEFAULT_MAX_STATE_AGE_SECONDS,
    policy_rejections: Iterable[R] = (),
    notes: Optional[str] = None,
) -> RiskAssessment:
    """Derive the contract-correct status/reasons for externally evaluated limit checks. Does not alter the prediction."""
    if not isinstance(prediction, Prediction) or not isinstance(state, PredictionStateRecord):
        raise _rfail(V.INVALID_TYPE, "assess_prediction needs a Prediction and its PredictionStateRecord")
    try:
        verify_prediction_state(state, prediction)       # never trust a hand-made state record
    except PredictionContractError as exc:
        raise _rfail(V.STATE_MISMATCH, str(exc)) from None
    at = _check(DT, assessed_at_utc, "assessed_at_utc")
    checks = tuple(limit_checks)
    ovs = tuple(overrides)
    for c in checks:
        if c.limit_kind is LimitKind.MIN_EXPECTED_NET_R and c.observed_value != prediction.expected_net_r.expected_net_r:
            raise _rfail(V.PREDICTION_MISMATCH, "MIN_EXPECTED_NET_R observed_value must equal the prediction's expected_net_r")
    session = verify_session_with_calendar(prediction, calendar)
    reasons: List[R] = []
    if prediction.direction is Direction.NO_TRADE:
        status = RiskStatus.NOT_APPLICABLE
    else:
        if not prediction.is_live_faithful:
            reasons.append(R.RESEARCH_ONLY_PREDICTION)
        if state.state is PredictionState.EXPIRED or at >= prediction.expires_at_utc:
            reasons.append(R.PREDICTION_EXPIRED)
        elif state.state is PredictionState.INVALIDATED:
            reasons.append(R.PREDICTION_INVALIDATED)
        if state.evaluated_at_utc <= at and (at - state.evaluated_at_utc).total_seconds() > max_state_age_seconds:
            reasons.append(R.STALE_PREDICTION_STATE)
        if session is SessionVerification.UNVERIFIED:
            reasons.append(R.SESSION_UNVERIFIED)
        if not _probabilities_calibrated(prediction):
            reasons.append(R.UNCALIBRATED_PROBABILITIES)
        if prediction.expected_net_r.status is not NetRStatus.AVAILABLE:
            reasons.append(R.EXPECTED_NET_R_UNAVAILABLE)
        kinds = {c.limit_kind for c in checks}
        if HARD_CONTROLS - kinds:
            reasons.append(R.POLICY_REJECTION)       # a hard control was not evaluated: fail closed
        for c in checks:
            if c.result is CheckResult.FAIL:
                covered = (not c.is_hard_control) and any(
                    c.limit_id in o.overridden_limit_ids and o.granted_at_utc <= at < o.expires_at_utc for o in ovs)
                if not covered:
                    reasons.append(REJECTION_FOR_LIMIT[c.limit_kind])
        reasons.extend(policy_rejections)
        reasons = list(dict.fromkeys(reasons))
        status = RiskStatus.REJECTED if reasons else RiskStatus.APPROVED
    base = dict(contract_version=RISK_ASSESSMENT_CONTRACT_VERSION, risk_assessment_id="0" * 64,
                prediction_id=prediction.prediction_id, instrument_id=prediction.instrument_id,
                prediction_direction=prediction.direction, prediction_usage_class=prediction.usage_class,
                prediction_expected_net_r_status=prediction.expected_net_r.status,
                prediction_probabilities_calibrated=_probabilities_calibrated(prediction),
                prediction_expires_at_utc=prediction.expires_at_utc, prediction_state_id=state.state_id,
                prediction_state=state.state, prediction_state_evaluated_at_utc=state.evaluated_at_utc,
                max_state_age_seconds=max_state_age_seconds, session_verification=session,
                risk_policy_id=risk_policy_id, risk_policy_version=risk_policy_version,
                assessed_at_utc=at, status=status, rejection_reasons=tuple(reasons),
                limit_checks=checks, overrides=ovs if status is not RiskStatus.NOT_APPLICABLE else (), notes=notes)
    draft = object.__new__(RiskAssessment)
    for name, kind in RiskAssessment.FIELDS.items():
        object.__setattr__(draft, name, _check(kind, base[name], f"RiskAssessment.{name}"))
    return RiskAssessment(**{**base, "risk_assessment_id": content_id(draft, "risk_assessment_id")})


def verify_risk_assessment(assessment: RiskAssessment, prediction: Prediction, state: PredictionStateRecord,
                           *, calendar: Any = None) -> None:
    """The audited record must describe exactly this prediction and this (re-verified) state record, and carry the
    status the contract derives."""
    if not isinstance(assessment, RiskAssessment):
        raise _rfail(V.INVALID_TYPE, "assessment must be a RiskAssessment")
    if assessment.prediction_id != prediction.prediction_id or state.prediction_id != prediction.prediction_id:
        raise _rfail(V.PREDICTION_MISMATCH, "assessment, state and prediction ids differ")
    if assessment.prediction_state_id != state.state_id:
        raise _rfail(V.STATE_MISMATCH, "the assessment is bound to a different prediction state record")
    derived = assess_prediction(prediction, state, risk_policy_id=assessment.risk_policy_id,
                                risk_policy_version=assessment.risk_policy_version,
                                assessed_at_utc=assessment.assessed_at_utc, limit_checks=assessment.limit_checks,
                                overrides=assessment.overrides, calendar=calendar,
                                max_state_age_seconds=assessment.max_state_age_seconds, notes=assessment.notes)
    for name in ("instrument_id", "prediction_direction", "prediction_usage_class", "prediction_expected_net_r_status",
                 "prediction_probabilities_calibrated", "prediction_expires_at_utc", "prediction_state",
                 "prediction_state_evaluated_at_utc", "session_verification"):
        if getattr(assessment, name) != getattr(derived, name):
            raise _rfail(V.PREDICTION_MISMATCH, f"assessment.{name} does not match the prediction/state/calendar")
    recorded = set(assessment.rejection_reasons)
    if not set(derived.rejection_reasons) <= recorded:
        raise _rfail(V.INVALID_RISK_ASSESSMENT, "the assessment omits rejection reasons the contract derives")
    if derived.status is RiskStatus.NOT_APPLICABLE:
        expected = RiskStatus.NOT_APPLICABLE
    else:
        expected = RiskStatus.REJECTED if recorded else RiskStatus.APPROVED   # extra reasons = external policy rejections
    if assessment.status is not expected:
        raise _rfail(V.INVALID_RISK_ASSESSMENT, f"recorded status {assessment.status.value} is not the derived {expected.value}")


def is_execution_eligible(prediction: Prediction, state: PredictionStateRecord, assessment: RiskAssessment,
                          *, calendar: Any = None) -> bool:
    """True only for an APPROVED assessment of a VALID, LIVE_FAITHFUL, LONG/SHORT prediction, bound to the exact,
    re-verified state record. An eligibility predicate for a future execution layer; nothing here places orders."""
    try:
        verify_risk_assessment(assessment, prediction, state, calendar=calendar)
    except PredictionContractError:
        return False
    return (assessment.status is RiskStatus.APPROVED and prediction.direction is not Direction.NO_TRADE
            and state.state is PredictionState.VALID and prediction.is_live_faithful
            and assessment.assessed_at_utc < prediction.expires_at_utc)
