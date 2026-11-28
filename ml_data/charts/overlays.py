"""Explicit, versioned overlay specifications (EMA, SMA, VWAP, Bollinger Bands).

This module only DEFINES overlays and their warm-up requirements. Indicator values are not computed here
(no renderer in Phase 0). The default overlay list is empty; nothing is added implicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Dict, Mapping

from ..instruments.identity import normalize_decimal_str
from .exceptions import ChartContractError

OVERLAY_TYPES = ("EMA", "SMA", "VWAP", "BOLLINGER")
PLACEMENTS = ("PRICE_PANEL",)  # v1: all overlays draw on the price panel; volume-panel overlays are not defined

# calculation_version per overlay type: changing any formula requires a new version.
CALCULATION_VERSIONS: Mapping[str, str] = MappingProxyType({
    "EMA": "ema_v1",           # alpha = 2/(period+1), seeded with the SMA of the first `period` closes
    "SMA": "sma_v1",           # arithmetic mean of the last `period` closes
    "VWAP": "vwap_session_v1", # cumulative sum(HLC3*volume)/sum(volume), reset at each session_id boundary
    "BOLLINGER": "bbands_v1",  # SMA(period) +/- multiplier * population stddev(period) of closes
})
PRICE_SOURCES = ("CLOSE",)
VWAP_PRICE_SOURCES = ("HLC3",)
VWAP_RESETS = ("SESSION",)
MIN_PERIOD, MAX_PERIOD = 2, 500
EMA_WARMUP_MULTIPLIER = 3  # ema_v1: warm-up = 3 * period bars so the SMA seed's weight has decayed


def _period(params: Mapping[str, Any]) -> int:
    p = params.get("period")
    if isinstance(p, bool) or not isinstance(p, int) or not MIN_PERIOD <= p <= MAX_PERIOD:
        raise ChartContractError(f"overlay period must be an int in [{MIN_PERIOD}, {MAX_PERIOD}] (got {p!r})")
    return p


def _exact_keys(params: Mapping[str, Any], allowed, otype: str) -> None:
    keys = set(params)
    if keys != set(allowed):
        raise ChartContractError(f"{otype} parameters must be exactly {sorted(allowed)} (got {sorted(keys)})")


def normalize_overlay_parameters(overlay_type: str, parameters: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and normalize parameters (Decimal multipliers become canonical strings). No defaults are filled."""
    if not isinstance(parameters, Mapping):
        raise ChartContractError("overlay parameters must be a mapping")
    if overlay_type in ("EMA", "SMA"):
        _exact_keys(parameters, ("period", "source"), overlay_type)
        if parameters["source"] not in PRICE_SOURCES:
            raise ChartContractError(f"{overlay_type} source must be one of {PRICE_SOURCES}")
        return {"period": _period(parameters), "source": parameters["source"]}
    if overlay_type == "BOLLINGER":
        _exact_keys(parameters, ("period", "source", "stddev_multiplier"), overlay_type)
        if parameters["source"] not in PRICE_SOURCES:
            raise ChartContractError(f"BOLLINGER source must be one of {PRICE_SOURCES}")
        m = parameters["stddev_multiplier"]
        if isinstance(m, (float, bool)) or not isinstance(m, (str, Decimal)):
            raise ChartContractError("BOLLINGER stddev_multiplier must be a Decimal or decimal string (no float)")
        try:
            md = Decimal(m) if isinstance(m, str) else m
        except InvalidOperation:
            raise ChartContractError(f"BOLLINGER stddev_multiplier is not a decimal: {m!r}") from None
        if not md.is_finite() or not Decimal("0") < md <= Decimal("10"):
            raise ChartContractError(f"BOLLINGER stddev_multiplier must be in (0, 10] (got {m!r})")
        return {"period": _period(parameters), "source": parameters["source"],
                "stddev_multiplier": normalize_decimal_str(md)}
    if overlay_type == "VWAP":
        _exact_keys(parameters, ("price_source", "reset"), overlay_type)
        if parameters["price_source"] not in VWAP_PRICE_SOURCES:
            raise ChartContractError(f"VWAP price_source must be one of {VWAP_PRICE_SOURCES}")
        if parameters["reset"] not in VWAP_RESETS:
            raise ChartContractError(f"VWAP reset must be one of {VWAP_RESETS}")
        return {"price_source": parameters["price_source"], "reset": parameters["reset"]}
    raise ChartContractError(f"Unsupported overlay_type {overlay_type!r}; supported: {OVERLAY_TYPES}")


def canonical_overlay_id(overlay_type: str, parameters: Mapping[str, Any]) -> str:
    """One overlay definition has exactly one id, e.g. 'ema_20_close', 'bollinger_20_close_2', 'vwap_hlc3_session'."""
    p = normalize_overlay_parameters(overlay_type, parameters)
    if overlay_type in ("EMA", "SMA"):
        parts = [str(p["period"]), p["source"]]
    elif overlay_type == "BOLLINGER":
        parts = [str(p["period"]), p["source"], p["stddev_multiplier"]]
    else:
        parts = [p["price_source"], p["reset"]]
    return "_".join([overlay_type.lower()] + [x.lower() for x in parts])


def required_warmup_bars(overlay_type: str, parameters: Mapping[str, Any]) -> int:
    """Bars needed BEFORE the first visible candle so the first visible value uses only past data."""
    p = normalize_overlay_parameters(overlay_type, parameters)
    if overlay_type == "EMA":
        return EMA_WARMUP_MULTIPLIER * p["period"]
    if overlay_type in ("SMA", "BOLLINGER"):
        return p["period"] - 1
    return 0  # VWAP is session-anchored (see OverlaySpec.session_anchored), not bar-count anchored


@dataclass(frozen=True)
class OverlaySpec:
    overlay_id: str
    overlay_type: str
    parameters: Mapping[str, Any]
    calculation_version: str
    placement: str
    visible: bool
    warmup_bars: int
    style_ref: str
    session_anchored: bool = False

    def __post_init__(self) -> None:
        if self.overlay_type not in OVERLAY_TYPES:
            raise ChartContractError(f"Unsupported overlay_type {self.overlay_type!r}; supported: {OVERLAY_TYPES}")
        params = normalize_overlay_parameters(self.overlay_type, self.parameters)
        object.__setattr__(self, "parameters", MappingProxyType(params))
        expected_id = canonical_overlay_id(self.overlay_type, params)
        if self.overlay_id != expected_id:
            raise ChartContractError(f"overlay_id must be {expected_id!r} for these parameters (got {self.overlay_id!r})")
        if self.calculation_version != CALCULATION_VERSIONS[self.overlay_type]:
            raise ChartContractError(
                f"{self.overlay_type} calculation_version must be {CALCULATION_VERSIONS[self.overlay_type]!r} "
                f"(got {self.calculation_version!r})")
        if self.placement not in PLACEMENTS:
            raise ChartContractError(f"placement must be one of {PLACEMENTS} (got {self.placement!r})")
        if not isinstance(self.visible, bool):
            raise ChartContractError("overlay visible must be a bool")
        need = required_warmup_bars(self.overlay_type, params)
        if isinstance(self.warmup_bars, bool) or not isinstance(self.warmup_bars, int) or self.warmup_bars != need:
            raise ChartContractError(f"{self.overlay_id} warmup_bars must be {need} (got {self.warmup_bars!r})")
        anchored = self.overlay_type == "VWAP"
        if self.session_anchored is not anchored:
            raise ChartContractError(f"{self.overlay_id} session_anchored must be {anchored}")
        if not isinstance(self.style_ref, str) or not self.style_ref:
            raise ChartContractError("overlay style_ref must be a non-empty string resolved through the theme")

    @classmethod
    def create(cls, overlay_type: str, parameters: Mapping[str, Any], *, style_ref: str, visible: bool = True) -> "OverlaySpec":
        """Build a fully explicit overlay spec from its type and parameters (ids/versions/warm-up derived)."""
        params = normalize_overlay_parameters(overlay_type, parameters)
        return cls(
            overlay_id=canonical_overlay_id(overlay_type, params), overlay_type=overlay_type, parameters=params,
            calculation_version=CALCULATION_VERSIONS[overlay_type], placement="PRICE_PANEL", visible=visible,
            warmup_bars=required_warmup_bars(overlay_type, params), style_ref=style_ref,
            session_anchored=overlay_type == "VWAP",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overlay_id": self.overlay_id, "overlay_type": self.overlay_type,
            "parameters": dict(sorted(self.parameters.items())), "calculation_version": self.calculation_version,
            "placement": self.placement, "visible": self.visible, "warmup_bars": self.warmup_bars,
            "style_ref": self.style_ref, "session_anchored": self.session_anchored,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OverlaySpec":
        if not isinstance(data, Mapping):
            raise ChartContractError("overlay spec must be a mapping")
        allowed = {"overlay_id", "overlay_type", "parameters", "calculation_version", "placement", "visible",
                   "warmup_bars", "style_ref", "session_anchored"}
        unknown = set(data) - allowed
        missing = allowed - set(data)
        if unknown or missing:
            raise ChartContractError(f"overlay spec keys mismatch: unknown={sorted(unknown)} missing={sorted(missing)}")
        return cls(**dict(data))
