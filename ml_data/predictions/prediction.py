"""Phase 0 Step 3: Prediction Contract v1.0.0 (contract and validation only; no model, inference or execution).

A Prediction is what an ML model + versioned decision policy SAY about one instrument at one decision time.
It never grants permission to trade: that is a separate RiskAssessment (risk_assessment.py), and the
time-dependent validity of a prediction is a separate PredictionStateRecord (state.py).

Reused identities (never re-invented):
  instrument_id                Step 1 canonical identity v3 (format check = Step 2 INSTRUMENT_ID_RE)
  instrument_spec_version_id / instrument_spec_hash / recorded_at    Step 1 InstrumentSpecVersion
  data_snapshot_ids            Step 2 data_snapshot_id values (64-hex)
  chart_snapshot_ids           Step 2 chart_snapshot_id values (64-hex), only when charts are model inputs
  availability_mode            Step 2 AS_KNOWN_AT_DECISION / EVENT_TIME semantics
  timeframe                    Step 1 STANDARD_TIMEFRAMES_MINUTES
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ..charts.spec import AVAILABILITY_AS_KNOWN, AVAILABILITY_EVENT_TIME, AVAILABILITY_MODES, INSTRUMENT_ID_RE
from ..instruments.identity import compute_spec_hash
from ..storage.canonical_schema import STANDARD_TIMEFRAMES_MINUTES
from ._records import DEC, DT, ENUM, INT, OPT, REC, SCALAR_MAP, SHA, STR, TUP, Record, _check, content_id, decimal_places, fail
from .reason_codes import NO_TRADE_MODEL_REASONS, DataQualityCode as D, ModelReasonCode, ValidationFailureCode as V

PREDICTION_CONTRACT_VERSION = "1.0.0"
PROBABILITY_MAX_DECIMALS = 12
R_QUANTUM = Decimal("1e-12")            # expected R values: 12 decimal places, ROUND_HALF_EVEN
R_ROUNDING = ROUND_HALF_EVEN
MAX_HORIZON = timedelta(hours=24)
MAX_HORIZON_BARS = 1440
MAX_EXPLANATION_CHARS = 500
_EXACT_PREC = 80                        # Decimal precision for exact intermediate arithmetic


class Direction(str, Enum):
    LONG = "LONG"            # model expects a favourable move up; proposes buying the instrument (options: buying the contract)
    SHORT = "SHORT"          # model expects a favourable move down; proposes selling short
    NO_TRADE = "NO_TRADE"    # model/policy proposes no position; carries NO executable setup


class UsageClass(str, Enum):
    LIVE_FAITHFUL = "LIVE_FAITHFUL"                      # availability_mode AS_KNOWN_AT_DECISION
    RESEARCH_RETROSPECTIVE = "RESEARCH_RETROSPECTIVE"    # availability_mode EVENT_TIME; never production evidence


USAGE_BY_AVAILABILITY = {AVAILABILITY_AS_KNOWN: UsageClass.LIVE_FAITHFUL,
                         AVAILABILITY_EVENT_TIME: UsageClass.RESEARCH_RETROSPECTIVE}


class SessionKind(str, Enum):
    EXCHANGE_SESSION = "EXCHANGE_SESSION"    # listed markets: horizon must end at or before the session close
    CONTINUOUS = "CONTINUOUS"                # 24/7 crypto: no session close; horizon capped at MAX_HORIZON


class SessionBoundaryPolicy(str, Enum):
    REJECT_BEYOND_SESSION_CLOSE = "REJECT_BEYOND_SESSION_CLOSE"   # the only v1 policy: never extend, never truncate


class ReferencePriceType(str, Enum):
    LAST_TRADE = "LAST_TRADE"
    MID_QUOTE = "MID_QUOTE"
    BID = "BID"
    ASK = "ASK"
    BAR_CLOSE = "BAR_CLOSE"
    MARK_PRICE = "MARK_PRICE"


class EntryAssumption(str, Enum):
    NEXT_BAR_OPEN = "NEXT_BAR_OPEN"
    MARKETABLE_AT_DECISION = "MARKETABLE_AT_DECISION"
    LIMIT_AT_EXPECTED_PRICE = "LIMIT_AT_EXPECTED_PRICE"


class ProbabilityKind(str, Enum):
    CALIBRATED = "CALIBRATED"                        # requires a CalibrationRef
    UNCALIBRATED_SCORE = "UNCALIBRATED_SCORE"        # normalized model scores; NOT probabilities of anything


class UncertaintyStatus(str, Enum):
    COMPUTED = "COMPUTED"
    UNAVAILABLE = "UNAVAILABLE"


class UncertaintyKind(str, Enum):
    NET_R_PREDICTIVE_INTERVAL = "NET_R_PREDICTIVE_INTERVAL"   # central interval of realized net R, given coverage


class UncertaintyUnavailableReason(str, Enum):
    NOT_SUPPORTED_BY_MODEL = "NOT_SUPPORTED_BY_MODEL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NO_TRADE_PREDICTION = "NO_TRADE_PREDICTION"
    EXPECTED_NET_R_UNAVAILABLE = "EXPECTED_NET_R_UNAVAILABLE"


class NetRStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class NetRUnavailableReason(str, Enum):
    NO_TRADE_PREDICTION = "NO_TRADE_PREDICTION"
    MISSING_COST_ASSUMPTION = "MISSING_COST_ASSUMPTION"
    UNCALIBRATED_OUTCOME_PROBABILITIES = "UNCALIBRATED_OUTCOME_PROBABILITIES"
    CURRENCY_UNVERIFIED = "CURRENCY_UNVERIFIED"


# ---------------------------------------------------------------------------------------------- scope (Step 1 enums)

# Directional predictions are allowed only on these Step 1 segments; the identity-prefix asset token must match.
SUPPORTED_SEGMENTS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "US_EQUITY": ("US", ("EQUITY", "ETF")),
    "US_OPTIONS": ("US", ("OPTION",)),
    "US_FUTURES": ("US", ("FUTURE",)),
    "IN_INDEX_FUTURES": ("IN", ("FUTURE",)),
    "IN_INDEX_OPTIONS": ("IN", ("OPTION",)),
    "CRYPTO_SPOT": ("CRYPTO", ("CRYPTO_SPOT",)),
    "CRYPTO_PERPETUALS": ("CRYPTO", ("PERPETUAL",)),
}
INDIA_UNDERLYINGS = ("NIFTY", "BANKNIFTY")   # no single-stock Indian F&O (Step 1 validation enforces the same)
# v1 does not support short option writing (undefined risk) or uncollateralized spot-crypto shorting.
SHORT_UNSUPPORTED_SEGMENTS = ("US_OPTIONS", "IN_INDEX_OPTIONS", "CRYPTO_SPOT")
# Calendar identities allowed per segment (Step 1 calendar ids). The instrument specification's trading_calendar, when
# set, must name the same calendar. Step 1 instrument specs use "XCME" while the Step 1 CME calendar adapter is
# "XCME_GLOBEX": the two are declared equivalent here (documented alias, not a new calendar system).
CALENDARS_BY_SEGMENT: Dict[str, Tuple[str, ...]] = {
    "US_EQUITY": ("XNYS", "XNAS"), "US_OPTIONS": ("XNYS", "XNAS"), "US_FUTURES": ("XCME_GLOBEX",),
    "IN_INDEX_FUTURES": ("XNSE",), "IN_INDEX_OPTIONS": ("XNSE",),
    "CRYPTO_SPOT": ("CRYPTO_24_7",), "CRYPTO_PERPETUALS": ("CRYPTO_24_7",),
}
CALENDAR_ALIASES: Dict[str, str] = {"XCME": "XCME_GLOBEX"}
# Exchange timezone of each exchange calendar (Step 1 calendar metadata.timezone); used for session_id dates.
CALENDAR_TIMEZONES: Dict[str, str] = {"XNYS": "America/New_York", "XNAS": "America/New_York",
                                      "XCME_GLOBEX": "America/Chicago", "XNSE": "Asia/Kolkata", "CRYPTO_24_7": "UTC"}
SPEC_REQUIRED_KEYS = ("segment", "asset_class", "price_currency", "trading_calendar", "timezone")
EXIT_FILL_MODEL_V1 = "LEVEL_FILLS_ROUND_TRIP_COSTS_V1"


def canonical_calendar(calendar_id: Optional[str]) -> Optional[str]:
    return None if calendar_id is None else CALENDAR_ALIASES.get(calendar_id, calendar_id)


SEGMENT_SESSION_KIND = {s: (SessionKind.CONTINUOUS if s.startswith("CRYPTO_") else SessionKind.EXCHANGE_SESSION)
                        for s in SUPPORTED_SEGMENTS}


def check_instrument_scope(instrument_id: str, market: str, segment: str) -> None:
    if not isinstance(instrument_id, str) or not INSTRUMENT_ID_RE.match(instrument_id):
        raise fail(V.INVALID_INSTRUMENT_ID, f"instrument_id is not a Step 1 canonical v3 identity: {instrument_id!r}")
    if segment not in SUPPORTED_SEGMENTS:
        raise fail(V.UNSUPPORTED_SEGMENT, f"segment {segment!r} is outside the v1 prediction scope {sorted(SUPPORTED_SEGMENTS)}")
    want_market, tokens = SUPPORTED_SEGMENTS[segment]
    parts = instrument_id.split("#")[0].split(":")
    if market != want_market or parts[0] != market or len(parts) < 4 or parts[2] not in tokens:
        raise fail(V.INSTRUMENT_SCOPE_MISMATCH, f"{instrument_id} does not match market {market!r} / segment {segment!r}")
    if market == "IN" and parts[3] not in INDIA_UNDERLYINGS:
        raise fail(V.INSTRUMENT_SCOPE_MISMATCH, f"Indian scope is NIFTY / BANKNIFTY only (got underlying {parts[3]!r})")


# ---------------------------------------------------------------------------------------------- nested records

@dataclass(frozen=True)
class ModelProvenance(Record):
    """Versioned artifacts behind a prediction. Data cutoff, training completion and availability are distinct:
    training_data_end_utc <= model_trained_at_utc <= model_available_at_utc."""

    model_id: str
    model_version: str
    model_artifact_sha256: str
    training_data_end_utc: datetime
    model_trained_at_utc: datetime
    model_available_at_utc: datetime
    feature_set_id: str
    feature_set_version: str
    feature_set_available_at_utc: datetime
    feature_snapshot_id: str
    decision_policy_id: str
    decision_policy_version: str
    decision_policy_effective_from_utc: datetime
    label_definition_id: str
    label_definition_version: str

    FIELDS = {"model_id": STR, "model_version": STR, "model_artifact_sha256": SHA, "training_data_end_utc": DT,
              "model_trained_at_utc": DT, "model_available_at_utc": DT, "feature_set_id": STR,
              "feature_set_version": STR, "feature_set_available_at_utc": DT, "feature_snapshot_id": SHA,
              "decision_policy_id": STR, "decision_policy_version": STR, "decision_policy_effective_from_utc": DT,
              "label_definition_id": STR, "label_definition_version": STR}

    def _validate(self) -> None:
        if not self.training_data_end_utc <= self.model_trained_at_utc <= self.model_available_at_utc:
            raise fail(V.TIMESTAMP_ORDER, "require training_data_end <= model_trained_at <= model_available_at")


@dataclass(frozen=True)
class InputProvenance(Record):
    availability_mode: str
    data_snapshot_ids: Tuple[str, ...]
    chart_snapshot_ids: Tuple[str, ...]
    max_input_event_time_utc: datetime
    max_input_received_at_utc: datetime
    feature_snapshot_as_of_utc: datetime
    instrument_spec_version_id: int
    instrument_spec_hash: str
    instrument_spec_recorded_at_utc: datetime
    instrument_specification: Mapping[str, Any]

    FIELDS = {"availability_mode": STR, "data_snapshot_ids": TUP(SHA), "chart_snapshot_ids": TUP(SHA),
              "max_input_event_time_utc": DT, "max_input_received_at_utc": DT, "feature_snapshot_as_of_utc": DT,
              "instrument_spec_version_id": INT, "instrument_spec_hash": SHA, "instrument_spec_recorded_at_utc": DT,
              "instrument_specification": SCALAR_MAP}

    def _validate(self) -> None:
        if self.availability_mode not in AVAILABILITY_MODES:
            raise fail(V.INVALID_ENUM, f"availability_mode must be one of {AVAILABILITY_MODES}")
        if not self.data_snapshot_ids:
            raise fail(V.INVALID_PROVENANCE, "at least one data_snapshot_id is required")
        for name in ("data_snapshot_ids", "chart_snapshot_ids"):
            v = getattr(self, name)
            if len(set(v)) != len(v) or list(v) != sorted(v):
                raise fail(V.INVALID_PROVENANCE, f"{name} must be unique and sorted")
        if self.instrument_spec_version_id < 0:
            raise fail(V.INVALID_PROVENANCE, "instrument_spec_version_id must be >= 0")
        # The Step 1 specification snapshot must hash (Step 1 compute_spec_hash) to the referenced spec_hash,
        # so currency / segment / calendar are read from a validated specification, never from free strings.
        try:
            actual = compute_spec_hash(dict(self.instrument_specification))
        except (TypeError, ValueError):
            raise fail(V.INVALID_PROVENANCE, "instrument_specification is not canonically hashable") from None
        if actual != self.instrument_spec_hash:
            raise fail(V.INVALID_PROVENANCE, "instrument_specification does not hash to instrument_spec_hash")
        missing = [k for k in SPEC_REQUIRED_KEYS if k not in self.instrument_specification]
        if missing:
            raise fail(V.INVALID_PROVENANCE, f"instrument_specification lacks Step 1 keys {missing}")


@dataclass(frozen=True)
class HorizonSpec(Record):
    timeframe: str
    horizon_bars: int
    start_utc: datetime
    alignment_anchor_utc: datetime
    first_bar_open_utc: datetime
    expected_end_utc: datetime
    session_kind: SessionKind
    boundary_policy: SessionBoundaryPolicy
    calendar_id: str
    calendar_version: str
    session_id: Optional[str]
    session_open_utc: Optional[datetime]
    session_close_utc: Optional[datetime]

    FIELDS = {"timeframe": STR, "horizon_bars": INT, "start_utc": DT, "alignment_anchor_utc": DT,
              "first_bar_open_utc": DT, "expected_end_utc": DT,
              "session_kind": ENUM(SessionKind), "boundary_policy": ENUM(SessionBoundaryPolicy), "calendar_id": STR,
              "calendar_version": STR, "session_id": OPT(STR), "session_open_utc": OPT(DT), "session_close_utc": OPT(DT)}

    def _validate(self) -> None:
        if self.timeframe not in STANDARD_TIMEFRAMES_MINUTES:
            raise fail(V.INVALID_HORIZON, f"timeframe must be one of {sorted(STANDARD_TIMEFRAMES_MINUTES)}")
        if not 1 <= self.horizon_bars <= MAX_HORIZON_BARS:
            raise fail(V.INVALID_HORIZON, f"horizon_bars must be in [1, {MAX_HORIZON_BARS}]")
        tf = timedelta(minutes=STANDARD_TIMEFRAMES_MINUTES[self.timeframe])
        span = tf * self.horizon_bars
        if span > MAX_HORIZON:
            raise fail(V.INVALID_HORIZON, f"horizon {span} exceeds the v1 maximum {MAX_HORIZON}")
        # Bar alignment: the horizon is a count of FUTURE canonical bars. Bars are anchored at the session open
        # (exchange sessions) or UTC midnight (continuous). The first counted bar opens at the first boundary >= start.
        if self.session_kind is SessionKind.EXCHANGE_SESSION:
            if self.alignment_anchor_utc != self.session_open_utc:
                raise fail(V.INVALID_HORIZON, "exchange-session bars are anchored at session_open_utc")
        elif self.alignment_anchor_utc != self.start_utc.replace(hour=0, minute=0, second=0, microsecond=0):
            raise fail(V.INVALID_HORIZON, "continuous bars are anchored at UTC midnight of the start date")
        if self.start_utc < self.alignment_anchor_utc:
            raise fail(V.SESSION_BOUNDARY_VIOLATION if self.session_kind is SessionKind.EXCHANGE_SESSION
                       else V.INVALID_HORIZON, "start_utc precedes the session open / alignment anchor")
        if self.first_bar_open_utc != _next_boundary(self.alignment_anchor_utc, self.start_utc, tf):
            raise fail(V.INVALID_HORIZON, "first_bar_open_utc must be the first canonical bar boundary at or after start_utc")
        if self.expected_end_utc != self.first_bar_open_utc + span:
            raise fail(V.INVALID_HORIZON, "expected_end_utc must equal first_bar_open_utc + horizon_bars * timeframe")
        tz = CALENDAR_TIMEZONES.get(canonical_calendar(self.calendar_id) or "")
        if tz is None:
            raise fail(V.CALENDAR_MISMATCH, f"unknown calendar_id {self.calendar_id!r}")
        sess = (self.session_id, self.session_open_utc, self.session_close_utc)
        if self.session_kind is SessionKind.EXCHANGE_SESSION:
            if any(x is None for x in sess):
                raise fail(V.INVALID_HORIZON, "an exchange-session horizon needs session_id, session_open_utc and session_close_utc")
            if not self.session_open_utc < self.session_close_utc:  # type: ignore[operator]
                raise fail(V.INVALID_HORIZON, "session_open_utc must be before session_close_utc")
            if not self.session_open_utc <= self.start_utc < self.session_close_utc:  # type: ignore[operator]
                raise fail(V.SESSION_BOUNDARY_VIOLATION, "the horizon must start inside its trading session")
            if self.expected_end_utc > self.session_close_utc:  # type: ignore[operator]
                raise fail(V.SESSION_BOUNDARY_VIOLATION,
                           f"horizon ends {self.expected_end_utc.isoformat()} after the session close "
                           f"{self.session_close_utc.isoformat()}; intraday predictions never extend past the close")
            local_day = self.session_open_utc.astimezone(ZoneInfo(tz)).date().isoformat()  # type: ignore[union-attr]
            if self.session_id != f"{canonical_calendar(self.calendar_id)}_{local_day}":
                raise fail(V.CALENDAR_MISMATCH, f"session_id must be '<calendar_id>_<exchange-local session date>' "
                                                f"({canonical_calendar(self.calendar_id)}_{local_day})")
        elif any(x is not None for x in sess):
            raise fail(V.INVALID_HORIZON, "a continuous (24/7) horizon has no session_id / open / close")

    @classmethod
    def build(cls, *, timeframe: str, horizon_bars: int, start_utc: datetime, session_kind: SessionKind,
              calendar_id: str, calendar_version: str, session_id: Optional[str] = None,
              session_open_utc: Optional[datetime] = None, session_close_utc: Optional[datetime] = None) -> "HorizonSpec":
        if timeframe not in STANDARD_TIMEFRAMES_MINUTES:
            raise fail(V.INVALID_HORIZON, f"timeframe must be one of {sorted(STANDARD_TIMEFRAMES_MINUTES)}")
        if isinstance(horizon_bars, bool) or not isinstance(horizon_bars, int):
            raise fail(V.INVALID_TYPE, "horizon_bars must be an int")
        tf = timedelta(minutes=STANDARD_TIMEFRAMES_MINUTES[timeframe])
        start = _check(DT, start_utc, "HorizonSpec.start_utc")
        if session_kind is SessionKind.EXCHANGE_SESSION:
            anchor = _check(DT, session_open_utc, "HorizonSpec.session_open_utc")
        else:
            anchor = start.replace(hour=0, minute=0, second=0, microsecond=0)
        first = _next_boundary(anchor, start, tf)
        end = first + tf * horizon_bars
        return cls(timeframe=timeframe, horizon_bars=horizon_bars, start_utc=start_utc, alignment_anchor_utc=anchor,
                   first_bar_open_utc=first, expected_end_utc=end,
                   session_kind=session_kind, boundary_policy=SessionBoundaryPolicy.REJECT_BEYOND_SESSION_CLOSE,
                   calendar_id=calendar_id, calendar_version=calendar_version, session_id=session_id,
                   session_open_utc=session_open_utc, session_close_utc=session_close_utc)


def _next_boundary(anchor: datetime, t: datetime, tf: timedelta) -> datetime:
    """Smallest anchor + k*tf (k >= 0) that is >= t."""
    if t <= anchor:
        return anchor
    k, rem = divmod(t - anchor, tf)
    return anchor + tf * (k + (1 if rem else 0))


@dataclass(frozen=True)
class EntryReference(Record):
    """Observed reference and the ASSUMED entry. Not an order and not a fill: there are no fill fields."""

    reference_price: Decimal
    reference_price_type: ReferencePriceType
    reference_observed_at_utc: datetime
    reference_received_at_utc: datetime
    max_reference_age_seconds: int
    expected_entry_price: Decimal
    entry_assumption: EntryAssumption
    entry_tolerance: Decimal

    FIELDS = {"reference_price": DEC, "reference_price_type": ENUM(ReferencePriceType),
              "reference_observed_at_utc": DT, "reference_received_at_utc": DT, "max_reference_age_seconds": INT,
              "expected_entry_price": DEC, "entry_assumption": ENUM(EntryAssumption), "entry_tolerance": DEC}

    def _validate(self) -> None:
        for name in ("reference_price", "expected_entry_price"):
            if getattr(self, name) <= 0:
                raise fail(V.INVALID_PRICE, f"{name} must be > 0 for every v1-supported instrument")
        if self.entry_tolerance < 0:
            raise fail(V.INVALID_PRICE, "entry_tolerance must be >= 0")
        if self.max_reference_age_seconds <= 0:
            raise fail(V.INVALID_TYPE, "max_reference_age_seconds must be > 0")
        if self.reference_received_at_utc < self.reference_observed_at_utc:
            raise fail(V.TIMESTAMP_ORDER, "reference_received_at_utc must not precede reference_observed_at_utc")


COST_FIELDS = ("spread_cost_per_unit", "slippage_cost_per_unit", "fee_cost_per_unit", "tax_cost_per_unit",
               "borrow_cost_per_unit", "funding_cost_per_unit")


@dataclass(frozen=True)
class CostAssumptions(Record):
    """Round-trip ASSUMED costs per one unit of quantity, in the instrument's price currency (multiplier excluded).

    None means "not assessed". funding_cost_per_unit is signed (a negative value is an expected funding credit);
    every other cost is >= 0. Which costs are applicable depends on segment and direction (applicable_costs()).
    """

    cost_model_id: str
    cost_model_version: str
    cost_model_effective_from_utc: datetime
    price_currency: str
    spread_cost_per_unit: Optional[Decimal]
    slippage_cost_per_unit: Optional[Decimal]
    fee_cost_per_unit: Optional[Decimal]
    tax_cost_per_unit: Optional[Decimal]
    borrow_cost_per_unit: Optional[Decimal]
    funding_cost_per_unit: Optional[Decimal]

    FIELDS = {"cost_model_id": STR, "cost_model_version": STR, "cost_model_effective_from_utc": DT, "price_currency": STR,
              **{n: OPT(DEC) for n in COST_FIELDS}}

    def _validate(self) -> None:
        for n in COST_FIELDS[:-1]:
            v = getattr(self, n)
            if v is not None and v < 0:
                raise fail(V.INVALID_COST, f"{n} must be >= 0")


def applicable_costs(segment: str, direction: Direction) -> Tuple[str, ...]:
    out = ["spread_cost_per_unit", "slippage_cost_per_unit", "fee_cost_per_unit"]
    if segment.startswith("IN_"):
        out.append("tax_cost_per_unit")                       # STT / exchange taxes
    if segment == "US_EQUITY" and direction is Direction.SHORT:
        out.append("borrow_cost_per_unit")                    # stock borrow
    if segment == "CRYPTO_PERPETUALS":
        out.append("funding_cost_per_unit")                   # expected funding over the horizon
    return tuple(out)


@dataclass(frozen=True)
class RiskLevels(Record):
    stop_loss_price: Decimal
    take_profit_price: Decimal

    FIELDS = {"stop_loss_price": DEC, "take_profit_price": DEC}

    def _validate(self) -> None:
        for name in ("stop_loss_price", "take_profit_price"):
            if getattr(self, name) <= 0:
                raise fail(V.INVALID_PRICE, f"{name} must be > 0")


@dataclass(frozen=True)
class CalibrationRef(Record):
    method: str
    method_version: str
    artifact_sha256: str
    fitted_on_dataset_id: str
    fitted_until_utc: datetime
    available_at_utc: datetime

    FIELDS = {"method": STR, "method_version": STR, "artifact_sha256": SHA, "fitted_on_dataset_id": STR,
              "fitted_until_utc": DT, "available_at_utc": DT}

    def _validate(self) -> None:
        if self.available_at_utc < self.fitted_until_utc:
            raise fail(V.TIMESTAMP_ORDER, "a calibrator cannot be available before its fitting data cutoff")


def _check_probabilities(values: Sequence[Tuple[str, Decimal]], kind: ProbabilityKind,
                         calibration: Optional[CalibrationRef], what: str) -> None:
    for name, p in values:
        if not Decimal("0") <= p <= Decimal("1"):
            raise fail(V.INVALID_PROBABILITY, f"{what}.{name} must be in [0, 1] (got {p})")
        if decimal_places(p) > PROBABILITY_MAX_DECIMALS:
            raise fail(V.INVALID_PROBABILITY, f"{what}.{name} has more than {PROBABILITY_MAX_DECIMALS} decimal places")
    total = sum((p for _, p in values), Decimal("0"))
    if total != Decimal("1"):
        raise fail(V.PROBABILITY_SUM, f"{what} must sum to exactly 1 (got {total})")
    if kind is ProbabilityKind.CALIBRATED and calibration is None:
        raise fail(V.MISSING_CALIBRATION, f"{what} declared CALIBRATED without a calibration reference")
    if kind is ProbabilityKind.UNCALIBRATED_SCORE and calibration is not None:
        raise fail(V.MISSING_CALIBRATION, f"{what} UNCALIBRATED_SCORE must not carry a calibration reference")


@dataclass(frozen=True)
class DirectionProbabilities(Record):
    """P(label class = c | inputs) for the label definition in ModelProvenance.label_definition_*; sums to 1."""

    long: Decimal
    short: Decimal
    no_trade: Decimal
    kind: ProbabilityKind
    calibration: Optional[CalibrationRef]

    FIELDS = {"long": DEC, "short": DEC, "no_trade": DEC, "kind": ENUM(ProbabilityKind),
              "calibration": OPT(REC(CalibrationRef))}

    def _validate(self) -> None:
        _check_probabilities((("long", self.long), ("short", self.short), ("no_trade", self.no_trade)),
                             self.kind, self.calibration, "direction_probabilities")

    def of(self, d: Direction) -> Decimal:
        return {Direction.LONG: self.long, Direction.SHORT: self.short, Direction.NO_TRADE: self.no_trade}[d]


@dataclass(frozen=True)
class OutcomeProbabilities(Record):
    """Conditional on entering the proposed trade: exactly one outcome happens first within the horizon."""

    target_first: Decimal
    stop_first: Decimal
    horizon_exit: Decimal
    kind: ProbabilityKind
    calibration: Optional[CalibrationRef]

    FIELDS = {"target_first": DEC, "stop_first": DEC, "horizon_exit": DEC, "kind": ENUM(ProbabilityKind),
              "calibration": OPT(REC(CalibrationRef))}

    def _validate(self) -> None:
        _check_probabilities((("target_first", self.target_first), ("stop_first", self.stop_first),
                              ("horizon_exit", self.horizon_exit)), self.kind, self.calibration, "outcome_probabilities")


@dataclass(frozen=True)
class Uncertainty(Record):
    status: UncertaintyStatus
    kind: Optional[UncertaintyKind]
    lower_net_r: Optional[Decimal]
    upper_net_r: Optional[Decimal]
    coverage: Optional[Decimal]
    method: Optional[str]
    method_version: Optional[str]
    unavailable_reason: Optional[UncertaintyUnavailableReason]

    FIELDS = {"status": ENUM(UncertaintyStatus), "kind": OPT(ENUM(UncertaintyKind)), "lower_net_r": OPT(DEC),
              "upper_net_r": OPT(DEC), "coverage": OPT(DEC), "method": OPT(STR), "method_version": OPT(STR),
              "unavailable_reason": OPT(ENUM(UncertaintyUnavailableReason))}

    def _validate(self) -> None:
        body = (self.kind, self.lower_net_r, self.upper_net_r, self.coverage, self.method, self.method_version)
        if self.status is UncertaintyStatus.COMPUTED:
            if any(x is None for x in body) or self.unavailable_reason is not None:
                raise fail(V.INVALID_UNCERTAINTY, "COMPUTED uncertainty needs kind, bounds, coverage, method and version, and no unavailable_reason")
            if self.lower_net_r > self.upper_net_r:  # type: ignore[operator]
                raise fail(V.INVALID_UNCERTAINTY, "lower_net_r must be <= upper_net_r")
            if not Decimal("0") < self.coverage < Decimal("1"):  # type: ignore[operator]
                raise fail(V.INVALID_UNCERTAINTY, "coverage must be in (0, 1)")
        elif any(x is not None for x in body) or self.unavailable_reason is None:
            raise fail(V.INVALID_UNCERTAINTY, "UNAVAILABLE uncertainty carries only an unavailable_reason")

    @classmethod
    def unavailable(cls, reason: UncertaintyUnavailableReason) -> "Uncertainty":
        return cls(UncertaintyStatus.UNAVAILABLE, None, None, None, None, None, None, reason)


@dataclass(frozen=True)
class ExpectedNetR(Record):
    """Derived, never asserted: Prediction recomputes it from levels, outcome probabilities and costs."""

    status: NetRStatus
    unavailable_reasons: Tuple[NetRUnavailableReason, ...]
    exit_fill_model: str
    initial_risk_per_unit: Optional[Decimal]
    potential_reward_per_unit: Optional[Decimal]
    reward_risk_ratio_gross: Optional[Decimal]
    expected_gross_per_unit: Optional[Decimal]
    total_cost_per_unit: Optional[Decimal]
    expected_net_per_unit: Optional[Decimal]
    expected_gross_r: Optional[Decimal]
    expected_net_r: Optional[Decimal]

    FIELDS = {"status": ENUM(NetRStatus), "unavailable_reasons": TUP(ENUM(NetRUnavailableReason)),
              "exit_fill_model": STR, "initial_risk_per_unit": OPT(DEC), "potential_reward_per_unit": OPT(DEC),
              "reward_risk_ratio_gross": OPT(DEC), "expected_gross_per_unit": OPT(DEC),
              "total_cost_per_unit": OPT(DEC), "expected_net_per_unit": OPT(DEC), "expected_gross_r": OPT(DEC),
              "expected_net_r": OPT(DEC)}

    def _validate(self) -> None:
        if self.exit_fill_model != EXIT_FILL_MODEL_V1:
            raise fail(V.NET_R_MISMATCH, f"exit_fill_model must be {EXIT_FILL_MODEL_V1!r} in v1")
        expected = ("expected_gross_per_unit", "total_cost_per_unit", "expected_net_per_unit", "expected_gross_r",
                    "expected_net_r")
        if self.status is NetRStatus.AVAILABLE:
            if self.unavailable_reasons or any(getattr(self, n) is None for n in self.FIELDS if n not in ("status", "unavailable_reasons", "exit_fill_model")):
                raise fail(V.NET_R_MISMATCH, "AVAILABLE expected net R needs every value and no unavailable reasons")
        else:
            if not self.unavailable_reasons or any(getattr(self, n) is not None for n in expected):
                raise fail(V.NET_R_MISMATCH, "UNAVAILABLE expected net R carries reasons and no expected values")


def _q(x: Decimal) -> Decimal:
    return x.quantize(R_QUANTUM, rounding=R_ROUNDING)


def compute_expected_net_r(
    *, direction: Direction, segment: str, entry: Optional[EntryReference], levels: Optional[RiskLevels],
    outcome: Optional[OutcomeProbabilities], expected_horizon_exit_move_per_unit: Optional[Decimal],
    costs: Optional[CostAssumptions], spec_price_currency: Optional[str] = None,
) -> ExpectedNetR:
    """Expected net R (Decimal, direction-aware). See docs/ml_data/PHASE0_PREDICTION_CONTRACT.md §8.

    risk   = |E - SL|            reward = |TP - E|          (gross price distances per unit)
    E_gross = p_tp * reward - p_sl * risk + p_exit * m_exit   (m_exit: expected signed favourable move at horizon exit)
    C = sum of applicable round-trip costs per unit         E_net = E_gross - C
    gross_R = E_gross / risk     net_R = E_net / risk       (quantized to 1e-12, ROUND_HALF_EVEN)
    """
    if direction is Direction.NO_TRADE:
        return ExpectedNetR(NetRStatus.UNAVAILABLE, (NetRUnavailableReason.NO_TRADE_PREDICTION,), EXIT_FILL_MODEL_V1,
                            None, None, None, None, None, None, None, None)
    assert entry is not None and levels is not None and outcome is not None and expected_horizon_exit_move_per_unit is not None
    e, sl, tp = entry.expected_entry_price, levels.stop_loss_price, levels.take_profit_price
    with localcontext() as ctx:
        ctx.prec = _EXACT_PREC
        risk = (e - sl) if direction is Direction.LONG else (sl - e)
        reward = (tp - e) if direction is Direction.LONG else (e - tp)
        if risk == 0:
            raise fail(V.INVALID_RISK_DISTANCE, "initial risk per unit is zero (stop_loss == expected_entry)")
        if reward == 0:
            raise fail(V.INVALID_REWARD_DISTANCE, "potential reward per unit is zero (take_profit == expected_entry)")
        if risk < 0 or reward < 0:
            raise fail(V.INVALID_RISK_LEVELS, f"{direction.value} stop/target are on the wrong side of the entry")
        ratio = _q(reward / risk)
        reasons = []
        if outcome.kind is not ProbabilityKind.CALIBRATED:
            reasons.append(NetRUnavailableReason.UNCALIBRATED_OUTCOME_PROBABILITIES)
        needed = applicable_costs(segment, direction)
        if costs is None or any(getattr(costs, n) is None for n in needed):
            reasons.append(NetRUnavailableReason.MISSING_COST_ASSUMPTION)
        if costs is not None and (spec_price_currency is None or costs.price_currency != spec_price_currency):
            reasons.append(NetRUnavailableReason.CURRENCY_UNVERIFIED)
        if reasons:
            return ExpectedNetR(NetRStatus.UNAVAILABLE, tuple(reasons), EXIT_FILL_MODEL_V1, risk, reward, ratio,
                                None, None, None, None, None)
        gross = (outcome.target_first * reward - outcome.stop_first * risk
                 + outcome.horizon_exit * expected_horizon_exit_move_per_unit)
        cost = sum((getattr(costs, n) for n in needed), Decimal("0"))
        net = gross - cost
        return ExpectedNetR(NetRStatus.AVAILABLE, (), EXIT_FILL_MODEL_V1, risk, reward, ratio, gross, cost, net,
                            _q(gross / risk), _q(net / risk))


# ---------------------------------------------------------------------------------------------- the prediction

@dataclass(frozen=True)
class Prediction(Record):
    contract_version: str
    prediction_id: str
    usage_class: UsageClass
    instrument_id: str
    market: str
    segment: str
    direction: Direction
    decision_timestamp_utc: datetime
    inference_at_utc: datetime
    created_at_utc: datetime
    expires_at_utc: datetime
    max_decision_latency_seconds: int
    model: ModelProvenance
    inputs: InputProvenance
    horizon: HorizonSpec
    direction_probabilities: DirectionProbabilities
    model_reasons: Tuple[ModelReasonCode, ...]
    entry: Optional[EntryReference]
    levels: Optional[RiskLevels]
    costs: Optional[CostAssumptions]
    outcome_probabilities: Optional[OutcomeProbabilities]
    expected_horizon_exit_move_per_unit: Optional[Decimal]
    expected_net_r: ExpectedNetR
    uncertainty: Uncertainty
    explanation: Optional[str]

    FIELDS = {
        "contract_version": STR, "prediction_id": SHA, "usage_class": ENUM(UsageClass), "instrument_id": STR,
        "market": STR, "segment": STR, "direction": ENUM(Direction), "decision_timestamp_utc": DT,
        "inference_at_utc": DT, "created_at_utc": DT, "expires_at_utc": DT, "max_decision_latency_seconds": INT,
        "model": REC(ModelProvenance), "inputs": REC(InputProvenance), "horizon": REC(HorizonSpec),
        "direction_probabilities": REC(DirectionProbabilities), "model_reasons": TUP(ENUM(ModelReasonCode)),
        "entry": OPT(REC(EntryReference)), "levels": OPT(REC(RiskLevels)), "costs": OPT(REC(CostAssumptions)),
        "outcome_probabilities": OPT(REC(OutcomeProbabilities)), "expected_horizon_exit_move_per_unit": OPT(DEC),
        "expected_net_r": REC(ExpectedNetR), "uncertainty": REC(Uncertainty), "explanation": OPT(STR),
    }

    # -- invariants ------------------------------------------------------------------------------------------
    def _validate(self) -> None:
        if self.contract_version != PREDICTION_CONTRACT_VERSION:
            raise fail(V.INVALID_CONTRACT_VERSION, f"unsupported contract_version {self.contract_version!r}")
        check_instrument_scope(self.instrument_id, self.market, self.segment)
        self._validate_spec_binding()
        self._validate_time_and_lookahead()
        self._validate_direction_payload()
        self._validate_selection()
        self._validate_derived()
        if self.prediction_id != content_id(self, "prediction_id"):
            raise fail(V.INVALID_PREDICTION_ID, "prediction_id must be the SHA-256 of the prediction content")

    @property
    def spec_price_currency(self) -> Optional[str]:
        v = self.inputs.instrument_specification.get("price_currency")
        return v if isinstance(v, str) and v else None

    def _validate_spec_binding(self) -> None:
        spec = self.inputs.instrument_specification
        if spec.get("segment") != self.segment:
            raise fail(V.INSTRUMENT_SCOPE_MISMATCH, f"instrument_specification.segment {spec.get('segment')!r} != {self.segment}")
        cal = canonical_calendar(self.horizon.calendar_id)
        if cal not in CALENDARS_BY_SEGMENT[self.segment]:
            raise fail(V.CALENDAR_MISMATCH, f"calendar {self.horizon.calendar_id!r} is not valid for {self.segment} "
                                            f"(allowed {CALENDARS_BY_SEGMENT[self.segment]})")
        spec_cal = canonical_calendar(spec.get("trading_calendar"))
        if spec_cal is not None and spec_cal != cal:
            raise fail(V.CALENDAR_MISMATCH, f"horizon calendar {cal} differs from the instrument spec's trading_calendar {spec_cal}")
        if spec_cal is None and self.horizon.session_kind is SessionKind.EXCHANGE_SESSION:
            raise fail(V.CALENDAR_MISMATCH, "an exchange-traded instrument spec must name its trading_calendar")
        if self.costs is not None:
            cur = self.spec_price_currency
            if cur is not None and self.costs.price_currency != cur:
                raise fail(V.COST_CURRENCY_MISMATCH, f"costs are in {self.costs.price_currency} but the instrument is priced "
                                                     f"in {cur}; v1 never converts currencies")

    def _validate_time_and_lookahead(self) -> None:
        d, i = self.decision_timestamp_utc, self.inputs
        if USAGE_BY_AVAILABILITY[i.availability_mode] is not self.usage_class:
            raise fail(V.INVALID_PROVENANCE, f"usage_class must be {USAGE_BY_AVAILABILITY[i.availability_mode].value} "
                                            f"for availability_mode {i.availability_mode}")
        if not d <= self.inference_at_utc <= self.created_at_utc < self.expires_at_utc:
            raise fail(V.TIMESTAMP_ORDER, "require decision <= inference_at <= created_at < expires_at")
        if self.max_decision_latency_seconds <= 0:
            raise fail(V.INVALID_TYPE, "max_decision_latency_seconds must be > 0")
        if (self.created_at_utc - d).total_seconds() > self.max_decision_latency_seconds:
            raise fail(D.STALE_INFERENCE, "the prediction was created later than max_decision_latency_seconds after the decision")
        if self.horizon.start_utc != d:
            raise fail(V.INVALID_HORIZON, "horizon.start_utc must equal decision_timestamp_utc")
        if self.expires_at_utc > self.horizon.expected_end_utc:
            raise fail(V.INVALID_HORIZON, "expires_at_utc must not be after the horizon end")
        if self.horizon.session_kind is not SEGMENT_SESSION_KIND[self.segment]:
            raise fail(V.INVALID_HORIZON, f"segment {self.segment} requires a {SEGMENT_SESSION_KIND[self.segment].value} horizon")
        # point-in-time: event times and training/calibration cutoffs never after the decision (both modes)
        if i.max_input_event_time_utc > d:
            raise fail(D.LOOKAHEAD_INPUT_EVENT_TIME, "an input event time is after the decision timestamp")
        if not i.max_input_event_time_utc <= i.feature_snapshot_as_of_utc <= d:
            raise fail(D.LOOKAHEAD_FEATURE_SNAPSHOT, "require max_input_event_time <= feature_snapshot_as_of <= decision")
        if self.model.training_data_end_utc > d:
            raise fail(D.LOOKAHEAD_MODEL_TRAINING, "the model was trained on data after the decision timestamp")
        calibs = [x.calibration for x in (self.direction_probabilities, self.outcome_probabilities)
                  if x is not None and x.calibration is not None]
        for probs in (self.direction_probabilities, self.outcome_probabilities):
            if probs is not None and probs.calibration is not None and probs.calibration.fitted_until_utc > d:
                raise fail(D.LOOKAHEAD_CALIBRATION, "the calibrator was fitted on data after the decision timestamp")
        if self.entry is not None:
            if self.entry.reference_observed_at_utc > d:
                raise fail(D.LOOKAHEAD_REFERENCE_PRICE, "the reference price was observed after the decision timestamp")
            if (d - self.entry.reference_observed_at_utc).total_seconds() > self.entry.max_reference_age_seconds:
                raise fail(D.STALE_REFERENCE_PRICE, "the reference price is older than max_reference_age_seconds")
        # live-faithful only: everything must also have been RECEIVED by the decision time
        if self.usage_class is UsageClass.LIVE_FAITHFUL:
            if i.max_input_received_at_utc > d:
                raise fail(D.LOOKAHEAD_INPUT_RECEIVED_AT, "an input was received after the decision timestamp")
            if i.instrument_spec_recorded_at_utc > d:
                raise fail(D.LOOKAHEAD_INSTRUMENT_SPEC, "the instrument spec revision was recorded after the decision")
            if self.entry is not None and self.entry.reference_received_at_utc > d:
                raise fail(D.LOOKAHEAD_REFERENCE_PRICE, "the reference price was received after the decision timestamp")
            # every versioned artifact must have EXISTED and been AVAILABLE by the decision time
            m = self.model
            if m.model_available_at_utc > d:
                raise fail(D.LOOKAHEAD_MODEL_ARTIFACT, "the model artifact became available after the decision timestamp")
            if m.feature_set_available_at_utc > d:
                raise fail(D.LOOKAHEAD_FEATURE_SET, "the feature-set version became available after the decision timestamp")
            if m.decision_policy_effective_from_utc > d:
                raise fail(D.LOOKAHEAD_DECISION_POLICY, "the decision policy became effective after the decision timestamp")
            if any(c.available_at_utc > d for c in calibs):
                raise fail(D.LOOKAHEAD_CALIBRATION_ARTIFACT, "a calibrator became available after the decision timestamp")
            if self.costs is not None and self.costs.cost_model_effective_from_utc > d:
                raise fail(D.LOOKAHEAD_COST_MODEL, "the cost model became effective after the decision timestamp")

    def _validate_direction_payload(self) -> None:
        directional = (self.entry, self.levels, self.costs, self.outcome_probabilities,
                       self.expected_horizon_exit_move_per_unit)
        if self.direction is Direction.NO_TRADE:
            if any(x is not None for x in directional):
                raise fail(V.NO_TRADE_HAS_DIRECTIONAL_FIELDS,
                           "NO_TRADE must not carry entry, levels, costs, outcome probabilities or exit-move fields")
            return
        if any(x is None for x in directional):
            raise fail(V.DIRECTIONAL_MISSING_FIELDS,
                       f"{self.direction.value} needs entry, levels, costs, outcome_probabilities and expected_horizon_exit_move_per_unit")
        if self.direction is Direction.SHORT and self.segment in SHORT_UNSUPPORTED_SEGMENTS:
            raise fail(V.UNSUPPORTED_DIRECTION_FOR_SEGMENT, f"SHORT is not supported on {self.segment} in v1")
        e = self.entry.expected_entry_price  # type: ignore[union-attr]
        sl, tp = self.levels.stop_loss_price, self.levels.take_profit_price  # type: ignore[union-attr]
        long_ = self.direction is Direction.LONG
        risk = (e - sl) if long_ else (sl - e)          # signed in the trade's adverse direction
        reward = (tp - e) if long_ else (e - tp)        # signed in the trade's favourable direction
        if risk == 0:
            raise fail(V.INVALID_RISK_DISTANCE, "initial risk per unit is zero (stop_loss == expected_entry)")
        if reward == 0:
            raise fail(V.INVALID_REWARD_DISTANCE, "potential reward per unit is zero (take_profit == expected_entry)")
        if risk < 0 or reward < 0:
            raise fail(V.INVALID_RISK_LEVELS, "LONG requires stop_loss < expected_entry < take_profit"
                       if long_ else "SHORT requires take_profit < expected_entry < stop_loss")
        m = self.expected_horizon_exit_move_per_unit
        if not -risk <= m <= reward:  # type: ignore[operator]
            raise fail(V.INVALID_PROBABILITY, "expected_horizon_exit_move_per_unit must lie in [-risk, +reward]")
        needed = set(applicable_costs(self.segment, self.direction))
        for n in COST_FIELDS:
            if n not in needed and getattr(self.costs, n) is not None:
                raise fail(V.INVALID_COST, f"{n} is not applicable to {self.direction.value} on {self.segment}; it must be null")

    def _validate_selection(self) -> None:
        reasons = set(self.model_reasons)
        if not reasons or len(reasons) != len(self.model_reasons):
            raise fail(V.INVALID_REASON_CODES, "model_reasons must be non-empty and unique")
        if self.direction is Direction.NO_TRADE:
            if ModelReasonCode.DIRECTIONAL_EDGE in reasons:
                raise fail(V.INVALID_REASON_CODES, "NO_TRADE cannot carry MODEL_DIRECTIONAL_EDGE")
        else:
            if reasons != {ModelReasonCode.DIRECTIONAL_EDGE}:
                raise fail(V.INVALID_REASON_CODES, "LONG/SHORT carry exactly MODEL_DIRECTIONAL_EDGE")
            dp = self.direction_probabilities
            opposite = Direction.SHORT if self.direction is Direction.LONG else Direction.LONG
            if not dp.of(self.direction) > dp.of(opposite):
                raise fail(V.INCONSISTENT_DIRECTION_SELECTION,
                           f"{self.direction.value} requires P({self.direction.value}) > P({opposite.value})")
        if self.explanation is not None and len(self.explanation) > MAX_EXPLANATION_CHARS:
            raise fail(V.INVALID_TYPE, f"explanation is limited to {MAX_EXPLANATION_CHARS} characters")

    def _validate_derived(self) -> None:
        want = compute_expected_net_r(
            direction=self.direction, segment=self.segment, entry=self.entry, levels=self.levels,
            outcome=self.outcome_probabilities,
            expected_horizon_exit_move_per_unit=self.expected_horizon_exit_move_per_unit, costs=self.costs,
            spec_price_currency=self.spec_price_currency)
        if self.expected_net_r != want:
            raise fail(V.NET_R_MISMATCH, "expected_net_r does not match its recomputation from levels, probabilities and costs")
        u = self.uncertainty
        if self.direction is Direction.NO_TRADE and u.unavailable_reason is not UncertaintyUnavailableReason.NO_TRADE_PREDICTION:
            raise fail(V.INVALID_UNCERTAINTY, "NO_TRADE uncertainty is UNAVAILABLE with reason NO_TRADE_PREDICTION")
        if u.status is UncertaintyStatus.COMPUTED and self.expected_net_r.status is not NetRStatus.AVAILABLE:
            raise fail(V.INVALID_UNCERTAINTY, "a net-R interval requires an AVAILABLE expected net R")

    # -- derived views ------------------------------------------------------------------------------------------
    @property
    def is_live_faithful(self) -> bool:
        return self.usage_class is UsageClass.LIVE_FAITHFUL

    @property
    def is_directional(self) -> bool:
        return self.direction is not Direction.NO_TRADE

    @property
    def confidence(self) -> Decimal:
        """Model confidence = direction_probabilities of the selected direction. Derived, not stored (no duplicate).
        Meaningful as a probability only when direction_probabilities.kind is CALIBRATED; never a profit guarantee."""
        return self.direction_probabilities.of(self.direction)

    @classmethod
    def create(cls, **kw: Any) -> "Prediction":
        """Build a prediction, deriving expected_net_r, usage_class and prediction_id (never trusted from callers)."""
        for derived in ("prediction_id", "expected_net_r", "usage_class", "contract_version"):
            if derived in kw:
                raise fail(V.INVALID_TYPE, f"{derived} is derived by Prediction.create() and cannot be supplied")
        optional = ("entry", "levels", "costs", "outcome_probabilities", "expected_horizon_exit_move_per_unit",
                    "explanation")
        for name in optional:
            kw.setdefault(name, None)
        unknown = sorted(set(kw) - set(cls.FIELDS))
        missing = sorted(set(cls.FIELDS) - set(kw) - {"prediction_id", "expected_net_r", "usage_class", "contract_version"})
        if unknown:
            raise fail(V.UNKNOWN_FIELD, f"Prediction has unknown fields {unknown}")
        if missing:
            raise fail(V.MISSING_FIELD, f"Prediction is missing fields {missing}")
        direction = _check(ENUM(Direction), kw["direction"], "Prediction.direction")
        _check(STR, kw["segment"], "Prediction.segment")
        inputs = _check(REC(InputProvenance), kw["inputs"], "Prediction.inputs")
        if direction is Direction.NO_TRADE:
            enr = compute_expected_net_r(direction=direction, segment=kw["segment"], entry=None, levels=None,
                                         outcome=None, expected_horizon_exit_move_per_unit=None, costs=None)
        else:
            for need in ("entry", "levels", "outcome_probabilities", "expected_horizon_exit_move_per_unit"):
                if kw.get(need) is None:
                    raise fail(V.DIRECTIONAL_MISSING_FIELDS, f"{direction.value} needs {need}")
            cur = inputs.instrument_specification.get("price_currency")
            enr = compute_expected_net_r(direction=direction, segment=kw["segment"], entry=kw["entry"],
                                         levels=kw["levels"], outcome=kw["outcome_probabilities"],
                                         expected_horizon_exit_move_per_unit=kw["expected_horizon_exit_move_per_unit"],
                                         costs=kw["costs"], spec_price_currency=cur if isinstance(cur, str) and cur else None)
        base = dict(kw, contract_version=PREDICTION_CONTRACT_VERSION, prediction_id="0" * 64,
                    usage_class=USAGE_BY_AVAILABILITY.get(getattr(inputs, "availability_mode", None), UsageClass.LIVE_FAITHFUL),
                    expected_net_r=enr)
        draft = cls._draft(base)
        return cls(**{**base, "prediction_id": content_id(draft, "prediction_id")})

    @classmethod
    def _draft(cls, base: Dict[str, Any]) -> "Prediction":
        """A field-checked (not yet invariant-checked) instance used only to compute the content id."""
        obj = object.__new__(cls)
        for name, kind in cls.FIELDS.items():
            object.__setattr__(obj, name, _check(kind, base[name], f"Prediction.{name}"))
        return obj
