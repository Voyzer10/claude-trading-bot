"""Versioned chart themes. Every visual element resolves through a theme; nothing is styled implicitly."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Mapping, Tuple

from .exceptions import ChartContractError
from .hashing import sha256_of_payload

_HEX_RE = re.compile(r"^#[0-9A-F]{6}$")
_RATIO_RE = re.compile(r"^(0(\.[0-9]+)?|1(\.0+)?)$")

DEFAULT_THEME_ID = "dark_v1"
THEME_VERSION_1 = "1.0.0"


@dataclass(frozen=True)
class OverlayStyle:
    color: str
    line_width_px: int
    line_style: str  # "SOLID" | "DASHED"
    fill_opacity: str = "0"  # decimal string in [0, 1]; used by band overlays only

    def __post_init__(self) -> None:
        _require_hex(self.color, "overlay color")
        if isinstance(self.line_width_px, bool) or not isinstance(self.line_width_px, int) or not 1 <= self.line_width_px <= 4:
            raise ChartContractError(f"overlay line_width_px must be an int in [1, 4] (got {self.line_width_px!r})")
        if self.line_style not in ("SOLID", "DASHED"):
            raise ChartContractError(f"overlay line_style must be SOLID or DASHED (got {self.line_style!r})")
        _require_ratio(self.fill_opacity, "overlay fill_opacity")

    def to_dict(self) -> Dict[str, Any]:
        return {"color": self.color, "line_width_px": self.line_width_px, "line_style": self.line_style,
                "fill_opacity": self.fill_opacity}


@dataclass(frozen=True)
class ChartTheme:
    """A complete, versioned visual definition. Opacities are decimal strings (no floats in identities)."""

    theme_id: str
    theme_version: str
    background: str
    plot_panel: str
    grid: str
    grid_opacity: str
    text: str
    axis_line: str
    bullish: str
    bearish: str
    neutral: str
    candle_body_width_ratio: str      # fraction of one bar slot occupied by the candle body
    wick_width_px: int                # wicks use the candle's bullish/bearish/neutral colour
    volume_opacity: str               # volume bars use the candle's bullish/bearish/neutral colour
    font_family: str                  # the renderer records the exact font files in font_fingerprint
    font_size_px: int
    overlay_styles: Mapping[str, OverlayStyle] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.theme_id, str) or not re.match(r"^[a-z][a-z0-9_]*_v[0-9]+$", self.theme_id):
            raise ChartContractError(f"theme_id must look like '<name>_v<N>' (got {self.theme_id!r})")
        if not isinstance(self.theme_version, str) or not re.match(r"^[0-9]+\.[0-9]+\.[0-9]+$", self.theme_version):
            raise ChartContractError(f"theme_version must be semantic MAJOR.MINOR.PATCH (got {self.theme_version!r})")
        for name in ("background", "plot_panel", "grid", "text", "axis_line", "bullish", "bearish", "neutral"):
            _require_hex(getattr(self, name), name)
        for name in ("grid_opacity", "candle_body_width_ratio", "volume_opacity"):
            _require_ratio(getattr(self, name), name)
        for name, lo, hi in (("wick_width_px", 1, 4), ("font_size_px", 8, 32)):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                raise ChartContractError(f"{name} must be an int in [{lo}, {hi}] (got {v!r})")
        if not isinstance(self.font_family, str) or not self.font_family.strip():
            raise ChartContractError("font_family must be a non-empty string")
        styles = dict(self.overlay_styles)
        for k, v in styles.items():
            if not isinstance(k, str) or not k or not isinstance(v, OverlayStyle):
                raise ChartContractError(f"overlay_styles must map style_ref str -> OverlayStyle (bad entry {k!r})")
        object.__setattr__(self, "overlay_styles", MappingProxyType(styles))

    @property
    def key(self) -> Tuple[str, str]:
        return (self.theme_id, self.theme_version)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "theme_id": self.theme_id, "theme_version": self.theme_version, "background": self.background,
            "plot_panel": self.plot_panel, "grid": self.grid, "grid_opacity": self.grid_opacity, "text": self.text,
            "axis_line": self.axis_line, "bullish": self.bullish, "bearish": self.bearish, "neutral": self.neutral,
            "candle_body_width_ratio": self.candle_body_width_ratio, "wick_width_px": self.wick_width_px,
            "volume_opacity": self.volume_opacity, "font_family": self.font_family, "font_size_px": self.font_size_px,
            "overlay_styles": {k: v.to_dict() for k, v in sorted(self.overlay_styles.items())},
        }

    def theme_hash(self) -> str:
        """SHA-256 of the full theme definition: any style change is visible in chart identity."""
        return sha256_of_payload(self.to_dict())


def _require_hex(val: Any, name: str) -> None:
    if not isinstance(val, str) or not _HEX_RE.match(val):
        raise ChartContractError(f"{name} must be an uppercase #RRGGBB colour (got {val!r})")


def _require_ratio(val: Any, name: str) -> None:
    if not isinstance(val, str) or not _RATIO_RE.match(val):
        raise ChartContractError(f"{name} must be a decimal string in [0, 1] (got {val!r})")


def _styles(ema_fast: str, ema_slow: str, sma: str, vwap: str, bands: str) -> Dict[str, OverlayStyle]:
    return {
        "ema_fast": OverlayStyle(ema_fast, 2, "SOLID"),
        "ema_slow": OverlayStyle(ema_slow, 2, "SOLID"),
        "sma": OverlayStyle(sma, 2, "SOLID"),
        "vwap": OverlayStyle(vwap, 2, "DASHED"),
        "bollinger": OverlayStyle(bands, 1, "SOLID", fill_opacity="0.08"),
    }


DARK_V1 = ChartTheme(
    theme_id="dark_v1", theme_version=THEME_VERSION_1,
    background="#0B1220", plot_panel="#111827", grid="#273449", grid_opacity="0.6", text="#CBD5E1",
    axis_line="#273449", bullish="#22C55E", bearish="#EF4444", neutral="#94A3B8",
    candle_body_width_ratio="0.7", wick_width_px=1, volume_opacity="0.5",
    font_family="DejaVu Sans", font_size_px=12,
    overlay_styles=_styles("#38BDF8", "#F59E0B", "#A78BFA", "#F472B6", "#94A3B8"),
)

LIGHT_V1 = ChartTheme(
    theme_id="light_v1", theme_version=THEME_VERSION_1,
    background="#FFFFFF", plot_panel="#FFFFFF", grid="#E2E8F0", grid_opacity="0.8", text="#334155",
    axis_line="#CBD5E1", bullish="#15803D", bearish="#B91C1C", neutral="#64748B",
    candle_body_width_ratio="0.7", wick_width_px=1, volume_opacity="0.5",
    font_family="DejaVu Sans", font_size_px=12,
    overlay_styles=_styles("#0284C7", "#D97706", "#7C3AED", "#DB2777", "#64748B"),
)

THEMES: Mapping[Tuple[str, str], ChartTheme] = MappingProxyType({t.key: t for t in (DARK_V1, LIGHT_V1)})


def get_theme(theme_id: str, theme_version: str) -> ChartTheme:
    """Exact (theme_id, theme_version) lookup. No fallback, no 'latest' resolution."""
    try:
        return THEMES[(theme_id, theme_version)]
    except (KeyError, TypeError):
        raise ChartContractError(f"Unknown theme {theme_id!r} version {theme_version!r}") from None


def require_single_theme(theme_keys) -> Tuple[str, str]:
    """A model dataset must use exactly one (theme_id, theme_version). Mixing themes is rejected."""
    keys = {tuple(k) for k in theme_keys}
    if len(keys) != 1:
        raise ChartContractError(f"A model dataset must use exactly one theme; found {sorted(keys)}")
    return next(iter(keys))  # type: ignore[return-value]
