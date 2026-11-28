"""Configuration for the Phase 2B Leakage-Safe Label Engine."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from ..simulator.config import CostProfile


@dataclass(frozen=True)
class LabelConfig:
    config_id: str
    config_version: str
    method: str = "FIXED_HORIZON"                # "FIXED_HORIZON" | "TRIPLE_BARRIER"
    horizons_bars: Tuple[int, ...] = (1, 3, 5, 15)
    neutral_threshold_bps: Decimal = Decimal("5")
    take_profit_bps: Optional[Decimal] = None
    stop_loss_bps: Optional[Decimal] = None
    side: str = "LONG"                           # "LONG" | "SHORT"
    cost_profile: Optional[CostProfile] = None
    require_same_session: bool = True
    dataset_id: Optional[str] = None
    dataset_version: Optional[str] = None
    manifest_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        if self.method not in ("FIXED_HORIZON", "TRIPLE_BARRIER"):
            raise ValueError(f"Unsupported label method: {self.method!r}")
        if self.side not in ("LONG", "SHORT"):
            raise ValueError(f"Unsupported side: {self.side!r}")
        if not self.horizons_bars or any(h < 1 for h in self.horizons_bars):
            raise ValueError("horizons_bars must contain positive integers")
        if self.method == "TRIPLE_BARRIER" and (self.take_profit_bps is None or self.stop_loss_bps is None):
            raise ValueError("TRIPLE_BARRIER requires take_profit_bps and stop_loss_bps")
