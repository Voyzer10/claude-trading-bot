"""ChartSpec: the validated, machine-readable request for ONE chart snapshot (Chart Contract v1.0.0)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..instruments.identity import normalize_decimal_str
from ..storage.canonical_schema import STANDARD_TIMEFRAMES_MINUTES
from .exceptions import ChartContractError
from .hashing import require_sha256_hex, sha256_of_payload
from .overlays import OverlaySpec
from .profiles import CHART_CONTRACT_VERSION, get_profile
from .themes import get_theme

UTC = timezone.utc

# Canonical identity v3: "<prefix>#<32 lowercase hex>" (ml_data.instruments.identity.build_instrument_id)
INSTRUMENT_ID_RE = re.compile(r"^(US|IN|CRYPTO):[^#\s]+#[0-9a-f]{32}$")

SESSION_POLICY_ALLOWLIST = "ALLOWLIST"
SESSION_POLICIES = (SESSION_POLICY_ALLOWLIST,)
_SESSION_LABEL_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
FORBIDDEN_SESSIONS = ("CLOSED", "MAINTENANCE")

AVAILABILITY_AS_KNOWN = "AS_KNOWN_AT_DECISION"   # received_at_utc <= decision (default; live-faithful)
AVAILABILITY_EVENT_TIME = "EVENT_TIME"           # event/close time <= decision only (research reconstruction)
AVAILABILITY_MODES = (AVAILABILITY_AS_KNOWN, AVAILABILITY_EVENT_TIME)

# Default display zones (Chart Contract v1.0.0). v1 has no per-chart override: the display zone must match.
DISPLAY_TIMEZONE_BY_SEGMENT: Mapping[str, str] = MappingProxyType({
    "US_EQUITY": "America/New_York",
    "US_INDEX": "America/New_York",
    "US_OPTIONS": "America/New_York",
    "US_FUTURES": "America/Chicago",
    "IN_INDEX": "Asia/Kolkata",
    "IN_INDEX_FUTURES": "Asia/Kolkata",
    "IN_INDEX_OPTIONS": "Asia/Kolkata",
    "CRYPTO_SPOT": "UTC",
    "CRYPTO_FUTURES": "UTC",
    "CRYPTO_PERPETUALS": "UTC",
})


def display_timezone_for_segment(segment: str) -> str:
    try:
        return DISPLAY_TIMEZONE_BY_SEGMENT[segment]
    except KeyError:
        raise ChartContractError(f"No display timezone defined for segment {segment!r}") from None


def require_utc_datetime(val: Any, name: str) -> datetime:
    if not isinstance(val, datetime) or val.tzinfo is None or val.utcoffset() is None:
        raise ChartContractError(f"{name} must be a timezone-aware datetime")
    return val.astimezone(UTC)


def parse_utc(val: Any, name: str, *, required: bool = True) -> Optional[datetime]:
    if val is None:
        if required:
            raise ChartContractError(f"{name} is required")
        return None
    if isinstance(val, datetime):
        return require_utc_datetime(val, name)
    if not isinstance(val, str):
        raise ChartContractError(f"{name} must be an ISO-8601 string (got {type(val).__name__})")
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError:
        raise ChartContractError(f"Invalid ISO-8601 datetime for {name}: {val!r}") from None
    return require_utc_datetime(dt, name)


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def require_iana_timezone(name: Any, field: str = "display_timezone") -> str:
    if not isinstance(name, str) or not name:
        raise ChartContractError(f"{field} must be a non-empty IANA timezone name")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ChartContractError(f"{field} is not a valid IANA timezone: {name!r}") from None
    return name


MAX_PRICE_AXIS_PADDING_RATIO = Decimal("0.25")


def _padding_ratio(val: Any) -> str:
    """price_axis_padding_ratio: a decimal string (or Decimal) in (0, 0.25]; floats rejected; canonical string."""
    if isinstance(val, (float, bool)) or not isinstance(val, (str, Decimal)):
        raise ChartContractError("price_axis_padding_ratio must be a decimal string (no float)")
    try:
        d = Decimal(val) if isinstance(val, str) else val
    except InvalidOperation:
        raise ChartContractError(f"price_axis_padding_ratio is not a decimal: {val!r}") from None
    if not d.is_finite() or not Decimal("0") < d <= MAX_PRICE_AXIS_PADDING_RATIO:
        raise ChartContractError(f"price_axis_padding_ratio must be in (0, {MAX_PRICE_AXIS_PADDING_RATIO}] (got {val!r})")
    return normalize_decimal_str(d)


def _int(val: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(val, bool) or not isinstance(val, int) or val < minimum:
        raise ChartContractError(f"{name} must be an int >= {minimum} (got {val!r})")
    return val


@dataclass(frozen=True)
class ChartSpec:
    chart_contract_version: str
    chart_profile_id: str
    instrument_id: str
    timeframe: str
    width_px: int
    height_px: int
    image_format: str
    color_mode: str
    color_space: str
    visible_candle_count: int
    warmup_candle_count: int
    session_policy: str
    allowed_sessions: Tuple[str, ...]
    display_timezone: str
    x_axis_mode: str
    price_scale: str
    price_axis_policy: str
    price_axis_padding_ratio: str
    volume_panel_enabled: bool
    theme_id: str
    theme_version: str
    overlay_specs: Tuple[OverlaySpec, ...]
    decision_timestamp_utc: datetime
    availability_mode: str
    data_snapshot_id: str

    def __post_init__(self) -> None:
        if self.chart_contract_version != CHART_CONTRACT_VERSION:
            raise ChartContractError(f"Unsupported chart_contract_version {self.chart_contract_version!r}")
        prof = get_profile(self.chart_profile_id)
        if not isinstance(self.instrument_id, str) or not INSTRUMENT_ID_RE.match(self.instrument_id):
            raise ChartContractError(f"instrument_id is not a canonical v3 identity: {self.instrument_id!r}")
        if self.timeframe not in STANDARD_TIMEFRAMES_MINUTES:
            raise ChartContractError(f"Unsupported timeframe {self.timeframe!r}; supported: {sorted(STANDARD_TIMEFRAMES_MINUTES)}")
        # The spec must match its versioned profile exactly (no implicit resizing / variants).
        for name in ("width_px", "height_px", "image_format", "color_mode", "color_space", "visible_candle_count",
                     "x_axis_mode", "price_scale", "price_axis_policy", "volume_panel_enabled"):
            got, want = getattr(self, name), getattr(prof, name)
            if type(got) is not type(want) or got != want:
                raise ChartContractError(f"{name}={got!r} does not match profile {prof.profile_id} ({want!r})")
        object.__setattr__(self, "price_axis_padding_ratio", _padding_ratio(self.price_axis_padding_ratio))
        _int(self.warmup_candle_count, "warmup_candle_count")
        if self.session_policy not in SESSION_POLICIES:
            raise ChartContractError(f"Unsupported session_policy {self.session_policy!r}")
        sessions = self.allowed_sessions
        if isinstance(sessions, str) or not isinstance(sessions, (tuple, list)) or not sessions:
            raise ChartContractError("allowed_sessions must be a non-empty list of session labels")
        for s in sessions:
            if not isinstance(s, str) or not _SESSION_LABEL_RE.match(s) or s in FORBIDDEN_SESSIONS:
                raise ChartContractError(f"Invalid allowed session label {s!r}")
        if len(set(sessions)) != len(sessions):
            raise ChartContractError("allowed_sessions contains duplicates")
        object.__setattr__(self, "allowed_sessions", tuple(sorted(sessions)))
        require_iana_timezone(self.display_timezone)
        theme = get_theme(self.theme_id, self.theme_version)
        ovs = self.overlay_specs
        if isinstance(ovs, (str, bytes)) or not isinstance(ovs, (tuple, list)):
            raise ChartContractError("overlay_specs must be a list (default: empty)")
        ovs = tuple(OverlaySpec.from_dict(o) if isinstance(o, Mapping) else o for o in ovs)
        ids = []
        for o in ovs:
            if not isinstance(o, OverlaySpec):
                raise ChartContractError("overlay_specs entries must be OverlaySpec")
            if o.style_ref not in theme.overlay_styles:
                raise ChartContractError(f"overlay {o.overlay_id} style_ref {o.style_ref!r} is not defined by theme {theme.theme_id}")
            ids.append(o.overlay_id)
        if len(set(ids)) != len(ids):
            raise ChartContractError("overlay_specs contains duplicate overlay_id values")
        object.__setattr__(self, "overlay_specs", tuple(sorted(ovs, key=lambda o: o.overlay_id)))
        need = self.required_warmup_bars
        if self.warmup_candle_count < need:
            raise ChartContractError(f"warmup_candle_count {self.warmup_candle_count} < overlay requirement {need}")
        object.__setattr__(self, "decision_timestamp_utc", require_utc_datetime(self.decision_timestamp_utc, "decision_timestamp_utc"))
        if self.availability_mode not in AVAILABILITY_MODES:
            raise ChartContractError(f"availability_mode must be one of {AVAILABILITY_MODES}")
        require_sha256_hex(self.data_snapshot_id, "data_snapshot_id")

    @property
    def required_warmup_bars(self) -> int:
        return max((o.warmup_bars for o in self.overlay_specs), default=0)

    @classmethod
    def create(
        cls,
        *,
        instrument_id: str,
        timeframe: str,
        decision_timestamp_utc: datetime,
        data_snapshot_id: str,
        display_timezone: str,
        allowed_sessions: Sequence[str] = ("REGULAR",),
        overlay_specs: Sequence[OverlaySpec] = (),
        warmup_candle_count: Optional[int] = None,
        profile_id: str = "intraday_v1_200bar",
        theme_id: Optional[str] = None,
        theme_version: Optional[str] = None,
        availability_mode: str = AVAILABILITY_AS_KNOWN,
        price_axis_padding_ratio: Optional[str] = None,
    ) -> "ChartSpec":
        """Spec filled from the versioned profile. Every value is still written explicitly into the spec.

        Default allowed_sessions is REGULAR only; PRE_MARKET / POST_MARKET must be listed explicitly.
        """
        prof = get_profile(profile_id)
        ovs = tuple(overlay_specs)
        return cls(
            chart_contract_version=CHART_CONTRACT_VERSION, chart_profile_id=prof.profile_id,
            instrument_id=instrument_id, timeframe=timeframe, width_px=prof.width_px, height_px=prof.height_px,
            image_format=prof.image_format, color_mode=prof.color_mode, color_space=prof.color_space,
            visible_candle_count=prof.visible_candle_count,
            warmup_candle_count=max((o.warmup_bars for o in ovs), default=0) if warmup_candle_count is None else warmup_candle_count,
            session_policy=SESSION_POLICY_ALLOWLIST, allowed_sessions=tuple(allowed_sessions),
            display_timezone=display_timezone, x_axis_mode=prof.x_axis_mode, price_scale=prof.price_scale,
            price_axis_policy=prof.price_axis_policy,
            price_axis_padding_ratio=prof.default_price_axis_padding_ratio if price_axis_padding_ratio is None else price_axis_padding_ratio,
            volume_panel_enabled=prof.volume_panel_enabled,
            theme_id=theme_id or prof.default_theme_id, theme_version=theme_version or prof.default_theme_version,
            overlay_specs=ovs, decision_timestamp_utc=decision_timestamp_utc, availability_mode=availability_mode,
            data_snapshot_id=data_snapshot_id,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chart_contract_version": self.chart_contract_version, "chart_profile_id": self.chart_profile_id,
            "instrument_id": self.instrument_id, "timeframe": self.timeframe, "width_px": self.width_px,
            "height_px": self.height_px, "image_format": self.image_format, "color_mode": self.color_mode,
            "color_space": self.color_space, "visible_candle_count": self.visible_candle_count,
            "warmup_candle_count": self.warmup_candle_count, "session_policy": self.session_policy,
            "allowed_sessions": list(self.allowed_sessions), "display_timezone": self.display_timezone,
            "x_axis_mode": self.x_axis_mode, "price_scale": self.price_scale,
            "price_axis_policy": self.price_axis_policy, "price_axis_padding_ratio": self.price_axis_padding_ratio,
            "volume_panel_enabled": self.volume_panel_enabled, "theme_id": self.theme_id,
            "theme_version": self.theme_version, "overlay_specs": [o.to_dict() for o in self.overlay_specs],
            "decision_timestamp_utc": utc_iso(self.decision_timestamp_utc),
            "availability_mode": self.availability_mode, "data_snapshot_id": self.data_snapshot_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChartSpec":
        if not isinstance(data, Mapping):
            raise ChartContractError("ChartSpec must be a mapping")
        fields = set(cls.__dataclass_fields__)
        unknown, missing = set(data) - fields, fields - set(data)
        if unknown or missing:
            raise ChartContractError(f"ChartSpec keys mismatch: unknown={sorted(unknown)} missing={sorted(missing)}")
        d = dict(data)
        d["decision_timestamp_utc"] = parse_utc(d["decision_timestamp_utc"], "decision_timestamp_utc")
        if isinstance(d["allowed_sessions"], list):
            d["allowed_sessions"] = tuple(d["allowed_sessions"])
        return cls(**d)

    def spec_hash(self) -> str:
        """chart_spec_hash: SHA-256 of the canonical ChartSpec JSON."""
        return sha256_of_payload(self.to_dict())


@dataclass(frozen=True)
class RendererInfo:
    """Identity of the (future) renderer build. font_fingerprint covers the exact font files used."""

    renderer_name: str
    renderer_version: str
    renderer_build_id: str
    font_fingerprint: str

    def __post_init__(self) -> None:
        for name in ("renderer_name", "renderer_version", "renderer_build_id"):
            v = getattr(self, name)
            if not isinstance(v, str) or not v.strip():
                raise ChartContractError(f"{name} must be a non-empty string")
        require_sha256_hex(self.font_fingerprint, "font_fingerprint")

    def to_dict(self) -> Dict[str, Any]:
        return {"renderer_name": self.renderer_name, "renderer_version": self.renderer_version,
                "renderer_build_id": self.renderer_build_id, "font_fingerprint": self.font_fingerprint}


def compute_font_fingerprint(fonts: Mapping[str, str]) -> str:
    """SHA-256 over {font file name -> SHA-256 of the font file bytes} (sorted)."""
    if not fonts:
        raise ChartContractError("font fingerprint needs at least one font file")
    for k, v in fonts.items():
        if not isinstance(k, str) or not k:
            raise ChartContractError("font file names must be non-empty strings")
        require_sha256_hex(v, f"sha256 of font {k}")
    return sha256_of_payload({"fonts": sorted([k, v] for k, v in fonts.items())})
