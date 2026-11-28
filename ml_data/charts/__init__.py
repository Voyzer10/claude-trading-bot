"""Phase 0 Step 2: ML research Chart Contract v1.0.0 (specification and validation only; no renderer).

Separate from the V4/V6 trading dashboard charts (components/ChartView.tsx, api/_chart.py), which are unchanged.
"""
from __future__ import annotations

from .exceptions import ChartContractError, ImageValidationError, LookaheadError, ProvenanceError
from .hashing import canonical_json, is_sha256_hex, sha256_hex, sha256_of_payload
from .overlays import (
    CALCULATION_VERSIONS,
    OVERLAY_TYPES,
    OverlaySpec,
    canonical_overlay_id,
    required_warmup_bars,
)
from .png import validate_chart_png
from .profiles import CHART_CONTRACT_VERSION, DEFAULT_PROFILE_ID, INTRADAY_V1_200BAR, PROFILES, ChartProfile, get_profile
from .snapshot import (
    BASIS_AS_KNOWN,
    BASIS_RETROSPECTIVE,
    INCOMPLETE_REASONS,
    MODEL_READY_BLOCKERS,
    RENDER_STATUSES,
    STATUS_FAILED,
    STATUS_INCOMPLETE,
    STATUS_MODEL_READY,
    STATUS_PENDING_RENDER,
    STATUS_READY,
    AxisTimestamp,
    ChartSnapshotManifest,
    DataSnapshot,
    axis_timestamp,
    build_chart_snapshot_manifest,
    build_data_snapshot,
    compute_chart_snapshot_id,
    dataset_manifest_identity,
    derive_render_status,
    price_axis_bounds,
    require_single_availability_mode,
    verify_chart_image,
    verify_chart_snapshot,
)
from .spec import (
    AVAILABILITY_AS_KNOWN,
    AVAILABILITY_EVENT_TIME,
    DISPLAY_TIMEZONE_BY_SEGMENT,
    ChartSpec,
    RendererInfo,
    compute_font_fingerprint,
    display_timezone_for_segment,
)
from .themes import DARK_V1, DEFAULT_THEME_ID, LIGHT_V1, THEMES, ChartTheme, OverlayStyle, get_theme, require_single_theme

__all__ = [
    "BASIS_AS_KNOWN", "BASIS_RETROSPECTIVE", "INCOMPLETE_REASONS", "MODEL_READY_BLOCKERS",
    "derive_render_status", "price_axis_bounds", "require_single_availability_mode",
    "AVAILABILITY_AS_KNOWN", "AVAILABILITY_EVENT_TIME", "AxisTimestamp", "CALCULATION_VERSIONS",
    "CHART_CONTRACT_VERSION", "ChartContractError", "ChartProfile", "ChartSnapshotManifest", "ChartSpec",
    "ChartTheme", "DARK_V1", "DEFAULT_PROFILE_ID", "DEFAULT_THEME_ID", "DISPLAY_TIMEZONE_BY_SEGMENT",
    "DataSnapshot", "INTRADAY_V1_200BAR", "ImageValidationError", "LIGHT_V1", "LookaheadError", "OVERLAY_TYPES",
    "OverlaySpec", "OverlayStyle", "PROFILES", "ProvenanceError", "RENDER_STATUSES", "RendererInfo",
    "STATUS_FAILED", "STATUS_INCOMPLETE", "STATUS_MODEL_READY", "STATUS_PENDING_RENDER", "STATUS_READY",
    "THEMES", "axis_timestamp", "build_chart_snapshot_manifest", "build_data_snapshot", "canonical_json",
    "canonical_overlay_id", "compute_chart_snapshot_id", "compute_font_fingerprint", "dataset_manifest_identity",
    "display_timezone_for_segment", "get_profile", "get_theme", "is_sha256_hex", "require_single_theme",
    "required_warmup_bars", "sha256_hex", "sha256_of_payload", "validate_chart_png", "verify_chart_image",
    "verify_chart_snapshot",
]
