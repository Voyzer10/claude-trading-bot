"""Phase 0 Step 3: Prediction Contract v1.0.0 and the risk-assessment boundary (contract and validation only).

No model, inference, feature pipeline, risk engine, order or broker interaction lives in this package.
"""
from __future__ import annotations

from .exceptions import PredictionContractError, RiskAssessmentContractError
from .prediction import (
    CALENDARS_BY_SEGMENT,
    CALENDAR_ALIASES,
    COST_FIELDS,
    EXIT_FILL_MODEL_V1,
    INDIA_UNDERLYINGS,
    MAX_HORIZON,
    PREDICTION_CONTRACT_VERSION,
    PROBABILITY_MAX_DECIMALS,
    R_QUANTUM,
    SHORT_UNSUPPORTED_SEGMENTS,
    SUPPORTED_SEGMENTS,
    CalibrationRef,
    CostAssumptions,
    Direction,
    DirectionProbabilities,
    EntryAssumption,
    EntryReference,
    ExpectedNetR,
    HorizonSpec,
    InputProvenance,
    ModelProvenance,
    NetRStatus,
    NetRUnavailableReason,
    OutcomeProbabilities,
    Prediction,
    ProbabilityKind,
    ReferencePriceType,
    RiskLevels,
    SessionBoundaryPolicy,
    SessionKind,
    Uncertainty,
    UncertaintyKind,
    UncertaintyStatus,
    UncertaintyUnavailableReason,
    UsageClass,
    applicable_costs,
    check_instrument_scope,
    compute_expected_net_r,
)
from .reason_codes import (
    DataQualityCode,
    ExpiryReasonCode,
    InvalidationReasonCode,
    ModelReasonCode,
    RiskRejectionCode,
    ValidationFailureCode,
)
from .risk_assessment import (
    DEFAULT_MAX_STATE_AGE_SECONDS,
    HARD_CONTROLS,
    MAX_STATE_AGE_LIMIT_SECONDS,
    SessionVerification,
    derive_check_result,
    verify_session_with_calendar,
    MAX_OVERRIDE_DURATION,
    RISK_ASSESSMENT_CONTRACT_VERSION,
    CheckResult,
    LimitCheck,
    LimitKind,
    RiskAssessment,
    RiskOverride,
    RiskStatus,
    assess_prediction,
    is_execution_eligible,
    verify_risk_assessment,
)
from .state import PredictionState, PredictionStateRecord, evaluate_prediction_state, verify_prediction_state

__all__ = [n for n in dir() if not n.startswith("_") and n not in ("annotations",)]
