"""Time-dependent validity of a prediction (Prediction Contract v1.0.0).

A Prediction is immutable. Whether it is still usable at a given instant is a separate, content-addressed
PredictionStateRecord that carries the EVIDENCE it was derived from:
  VALID        not expired and no invalidation condition holds at evaluated_at_utc
  EXPIRED      evaluated_at >= expires_at (+ HORIZON_ELAPSED once the horizon end has passed); checked first and
               takes precedence: an expired prediction is never reported as invalidated or valid
  INVALIDATED  not expired, but at least one InvalidationReasonCode holds
Fail-closed integrity: the record re-derives everything it can from its own evidence on construction (expiry from
the copied prediction expiry, staleness / missing data / tradability / explicit invalidations), and
verify_prediction_state() re-derives the complete state from the prediction plus the recorded evidence.
A hand-made VALID record that contradicts its evidence or the prediction is rejected.
Risk rejection is NOT a prediction state; it lives only in RiskAssessment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Iterable, List, Optional, Tuple

from ._records import BOOL, DEC, DT, ENUM, INT, OPT, SHA, TUP, Record, _check, content_id, fail
from .prediction import Direction, Prediction, SessionKind
from .reason_codes import (
    EXPLICIT_INVALIDATIONS,
    DataQualityCode as D,
    ExpiryReasonCode,
    InvalidationReasonCode as I,
    ValidationFailureCode as V,
)


class PredictionState(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class PredictionStateRecord(Record):
    state_id: str
    prediction_id: str
    prediction_expires_at_utc: datetime
    prediction_horizon_end_utc: datetime
    evaluated_at_utc: datetime
    latest_market_data_received_at_utc: Optional[datetime]
    max_market_data_age_seconds: int
    instrument_tradable: bool
    last_price: Optional[Decimal]
    explicit_invalidations: Tuple[I, ...]
    state: PredictionState
    expiry_reasons: Tuple[ExpiryReasonCode, ...]
    invalidation_reasons: Tuple[I, ...]

    FIELDS = {"state_id": SHA, "prediction_id": SHA, "prediction_expires_at_utc": DT,
              "prediction_horizon_end_utc": DT, "evaluated_at_utc": DT,
              "latest_market_data_received_at_utc": OPT(DT), "max_market_data_age_seconds": INT,
              "instrument_tradable": BOOL, "last_price": OPT(DEC), "explicit_invalidations": TUP(ENUM(I)),
              "state": ENUM(PredictionState), "expiry_reasons": TUP(ENUM(ExpiryReasonCode)),
              "invalidation_reasons": TUP(ENUM(I))}

    def _validate(self) -> None:
        for name in ("expiry_reasons", "invalidation_reasons", "explicit_invalidations"):
            v = getattr(self, name)
            if len(set(v)) != len(v):
                raise fail(V.INVALID_STATE_RECORD, f"{name} must be unique")
        if any(x not in EXPLICIT_INVALIDATIONS for x in self.explicit_invalidations):
            raise fail(V.INVALID_STATE_RECORD, "only MANUAL / SUPERSEDED may be supplied as explicit invalidations")
        if self.max_market_data_age_seconds <= 0:
            raise fail(V.INVALID_STATE_RECORD, "max_market_data_age_seconds must be > 0")
        if self.prediction_expires_at_utc > self.prediction_horizon_end_utc:
            raise fail(V.INVALID_STATE_RECORD, "prediction expiry cannot be after the horizon end")
        latest = self.latest_market_data_received_at_utc
        if latest is not None and latest > self.evaluated_at_utc:
            raise fail(D.FUTURE_MARKET_DATA_OBSERVATION, "market data cannot be received after the evaluation time")
        # 1) expiry is fully determined by the record's own copied prediction times
        want_expiry: List[ExpiryReasonCode] = []
        if self.evaluated_at_utc >= self.prediction_expires_at_utc:
            want_expiry.append(ExpiryReasonCode.EXPIRATION_REACHED)
            if self.evaluated_at_utc >= self.prediction_horizon_end_utc:
                want_expiry.append(ExpiryReasonCode.HORIZON_ELAPSED)
        if want_expiry:
            if self.state is not PredictionState.EXPIRED or self.expiry_reasons != tuple(want_expiry) or self.invalidation_reasons:
                raise fail(V.INVALID_STATE_RECORD, f"evaluated at or after expiry: the state must be EXPIRED {[c.value for c in want_expiry]}")
        elif self.state is PredictionState.EXPIRED or self.expiry_reasons:
            raise fail(V.INVALID_STATE_RECORD, "EXPIRED is only possible at or after the prediction's expiry")
        # 2) evidence-only invalidations must be present; VALID requires none at all
        if not want_expiry:
            implied = set(self.explicit_invalidations)
            if latest is None:
                implied.add(I.MISSING_MARKET_DATA)
            elif (self.evaluated_at_utc - latest).total_seconds() > self.max_market_data_age_seconds:
                implied.add(I.STALE_MARKET_DATA)
            if not self.instrument_tradable:
                implied.add(I.INSTRUMENT_NOT_TRADABLE)
            if not implied <= set(self.invalidation_reasons):
                raise fail(V.INVALID_STATE_RECORD, "the recorded evidence implies invalidation reasons the record omits")
            if self.state is PredictionState.VALID and self.invalidation_reasons:
                raise fail(V.INVALID_STATE_RECORD, "VALID carries no invalidation reasons")
            if self.state is PredictionState.INVALIDATED and not self.invalidation_reasons:
                raise fail(V.INVALID_STATE_RECORD, "INVALIDATED carries at least one invalidation reason")
        if self.state_id != content_id(self, "state_id"):
            raise fail(V.STATE_MISMATCH, "state_id must be the SHA-256 of the state record content")


def _derive(prediction: Prediction, now: datetime, latest: Optional[datetime], max_age: int, tradable: bool,
            last_price: Optional[Decimal], explicit: Tuple[I, ...]) -> Tuple[PredictionState, Tuple[ExpiryReasonCode, ...], Tuple[I, ...]]:
    if now >= prediction.expires_at_utc:
        reasons = [ExpiryReasonCode.EXPIRATION_REACHED]
        if now >= prediction.horizon.expected_end_utc:
            reasons.append(ExpiryReasonCode.HORIZON_ELAPSED)
        return PredictionState.EXPIRED, tuple(reasons), ()
    inval: List[I] = list(dict.fromkeys(explicit))
    if latest is None:
        inval.append(I.MISSING_MARKET_DATA)
    elif (now - latest).total_seconds() > max_age:
        inval.append(I.STALE_MARKET_DATA)
    if not tradable:
        inval.append(I.INSTRUMENT_NOT_TRADABLE)
    h = prediction.horizon
    if h.session_kind is SessionKind.EXCHANGE_SESSION and not (h.session_open_utc <= now < h.session_close_utc):  # type: ignore[operator]
        inval.append(I.SESSION_CLOSED)
    if prediction.direction is not Direction.NO_TRADE:
        if last_price is None:
            if I.MISSING_MARKET_DATA not in inval:
                inval.append(I.MISSING_MARKET_DATA)
        else:
            sl = prediction.levels.stop_loss_price  # type: ignore[union-attr]
            tp = prediction.levels.take_profit_price  # type: ignore[union-attr]
            e = prediction.entry.expected_entry_price  # type: ignore[union-attr]
            long_ = prediction.direction is Direction.LONG
            if (last_price <= sl) if long_ else (last_price >= sl):
                inval.append(I.PRICE_BEYOND_STOP)
            if (last_price >= tp) if long_ else (last_price <= tp):
                inval.append(I.PRICE_BEYOND_TARGET)
            if abs(last_price - e) > prediction.entry.entry_tolerance:  # type: ignore[union-attr]
                inval.append(I.ENTRY_PRICE_DEVIATION)
    if inval:
        return PredictionState.INVALIDATED, (), tuple(inval)
    return PredictionState.VALID, (), ()


def evaluate_prediction_state(
    prediction: Prediction,
    *,
    evaluated_at_utc: datetime,
    latest_market_data_received_at_utc: Optional[datetime],
    max_market_data_age_seconds: int,
    instrument_tradable: bool,
    last_price: Optional[Decimal] = None,
    explicit_invalidations: Iterable[I] = (),
) -> PredictionStateRecord:
    """Deterministic, content-addressed state of `prediction` at `evaluated_at_utc` from explicit market evidence."""
    if not isinstance(prediction, Prediction):
        raise fail(V.INVALID_TYPE, "prediction must be a Prediction")
    now = _check(DT, evaluated_at_utc, "evaluated_at_utc")
    if now < prediction.created_at_utc:
        raise fail(V.TIMESTAMP_ORDER, "a prediction cannot be evaluated before it was created")
    tradable = _check(BOOL, instrument_tradable, "instrument_tradable")
    max_age = _check(INT, max_market_data_age_seconds, "max_market_data_age_seconds")
    latest = _check(OPT(DT), latest_market_data_received_at_utc, "latest_market_data_received_at_utc")
    px = _check(OPT(DEC), last_price, "last_price")
    explicit = tuple(_check(ENUM(I), x, "explicit_invalidations[]") for x in explicit_invalidations)
    for x in explicit:
        if x not in EXPLICIT_INVALIDATIONS:
            raise fail(V.INVALID_REASON_CODES, f"{x.value} is derived from market facts, not supplied explicitly")
    if latest is not None and latest > now:
        raise fail(D.FUTURE_MARKET_DATA_OBSERVATION, "market data cannot be received after the evaluation time")
    if max_age <= 0:
        raise fail(V.INVALID_TYPE, "max_market_data_age_seconds must be > 0")
    state, exp, inv = _derive(prediction, now, latest, max_age, tradable, px, explicit)
    base = dict(state_id="0" * 64, prediction_id=prediction.prediction_id,
                prediction_expires_at_utc=prediction.expires_at_utc,
                prediction_horizon_end_utc=prediction.horizon.expected_end_utc, evaluated_at_utc=now,
                latest_market_data_received_at_utc=latest, max_market_data_age_seconds=max_age,
                instrument_tradable=tradable, last_price=px, explicit_invalidations=explicit, state=state,
                expiry_reasons=exp, invalidation_reasons=inv)
    draft = object.__new__(PredictionStateRecord)
    for name, kind in PredictionStateRecord.FIELDS.items():
        object.__setattr__(draft, name, _check(kind, base[name], f"PredictionStateRecord.{name}"))
    return PredictionStateRecord(**{**base, "state_id": content_id(draft, "state_id")})


def verify_prediction_state(record: PredictionStateRecord, prediction: Prediction) -> None:
    """The record must be exactly what evaluate_prediction_state() derives for this prediction from its evidence."""
    if not isinstance(record, PredictionStateRecord) or not isinstance(prediction, Prediction):
        raise fail(V.INVALID_TYPE, "verify_prediction_state needs a PredictionStateRecord and a Prediction")
    if record.prediction_id != prediction.prediction_id:
        raise fail(V.STATE_MISMATCH, "the state record belongs to a different prediction")
    rebuilt = evaluate_prediction_state(
        prediction, evaluated_at_utc=record.evaluated_at_utc,
        latest_market_data_received_at_utc=record.latest_market_data_received_at_utc,
        max_market_data_age_seconds=record.max_market_data_age_seconds,
        instrument_tradable=record.instrument_tradable, last_price=record.last_price,
        explicit_invalidations=record.explicit_invalidations)
    if rebuilt != record:
        diff = sorted(k for k in record.FIELDS if getattr(rebuilt, k) != getattr(record, k))
        raise fail(V.STATE_MISMATCH, f"the state record does not match its re-derivation from the prediction: {diff}")
