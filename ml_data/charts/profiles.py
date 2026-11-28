"""Versioned chart profiles. A ChartSpec must match its profile exactly: no implicit resizing or variants."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, Mapping

from .exceptions import ChartContractError

CHART_CONTRACT_VERSION = "1.0.0"
DEFAULT_PROFILE_ID = "intraday_v1_200bar"

X_AXIS_TRADING_BAR_INDEX = "TRADING_BAR_INDEX"
PRICE_SCALE_LINEAR = "LINEAR"
# Price-axis bounds policy v1: [visible_low - pad, visible_high + pad], pad = range * padding_ratio (Decimal only);
# for a flat window (range 0) pad = (|visible_high| or 1) * padding_ratio. See snapshot.price_axis_bounds().
PRICE_AXIS_POLICY_PADDED_RANGE_V1 = "PADDED_RANGE_V1"


@dataclass(frozen=True)
class ChartProfile:
    profile_id: str
    profile_version: str
    width_px: int
    height_px: int
    image_format: str
    color_mode: str
    color_space: str
    bit_depth: int
    visible_candle_count: int
    x_axis_mode: str
    price_scale: str
    price_axis_policy: str
    default_price_axis_padding_ratio: str
    volume_panel_enabled: bool
    price_panel_ratio: str   # share of the plot area (decimal string)
    volume_panel_ratio: str
    default_theme_id: str
    default_theme_version: str

    def __post_init__(self) -> None:
        from decimal import Decimal
        if Decimal(self.price_panel_ratio) + Decimal(self.volume_panel_ratio) != Decimal("1"):
            raise ChartContractError("price_panel_ratio + volume_panel_ratio must equal 1")
        if self.width_px <= 0 or self.height_px <= 0 or self.visible_candle_count <= 0:
            raise ChartContractError("profile dimensions and visible_candle_count must be positive")

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


INTRADAY_V1_200BAR = ChartProfile(
    profile_id=DEFAULT_PROFILE_ID, profile_version="1.0.0",
    width_px=1280, height_px=720, image_format="PNG", color_mode="RGB", color_space="sRGB", bit_depth=8,
    visible_candle_count=200, x_axis_mode=X_AXIS_TRADING_BAR_INDEX, price_scale=PRICE_SCALE_LINEAR,
    price_axis_policy=PRICE_AXIS_POLICY_PADDED_RANGE_V1, default_price_axis_padding_ratio="0.05",
    volume_panel_enabled=True, price_panel_ratio="0.78", volume_panel_ratio="0.22",
    default_theme_id="dark_v1", default_theme_version="1.0.0",
)

PROFILES: Mapping[str, ChartProfile] = MappingProxyType({INTRADAY_V1_200BAR.profile_id: INTRADAY_V1_200BAR})


def get_profile(profile_id: str) -> ChartProfile:
    try:
        return PROFILES[profile_id]
    except (KeyError, TypeError):
        raise ChartContractError(f"Unknown chart profile {profile_id!r}; supported: {sorted(PROFILES)}") from None
