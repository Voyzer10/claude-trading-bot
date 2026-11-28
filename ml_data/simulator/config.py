"""Configuration and versioned transaction-cost profiles for the Execution Simulator."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dt_time
from decimal import Decimal
from typing import Optional

from .exceptions import SimulatorConfigError


@dataclass(frozen=True)
class CostProfile:
    """Explicit, versioned transaction-cost and slippage schedule (never hardcoded per-market)."""

    profile_id: str
    version: str
    fee_bps: Decimal = Decimal("0")
    fixed_fee_per_order: Decimal = Decimal("0")
    per_contract_fee: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("0")
    spread_half_bps: Decimal = Decimal("0")
    tax_bps: Decimal = Decimal("0")
    description: str = ""

    def __post_init__(self) -> None:
        for name in ("fee_bps", "fixed_fee_per_order", "per_contract_fee", "slippage_bps", "spread_half_bps", "tax_bps"):
            val = getattr(self, name)
            if isinstance(val, (float, bool)) or not isinstance(val, Decimal) or val < 0:
                raise SimulatorConfigError(f"CostProfile.{name} must be a non-negative Decimal")


@dataclass(frozen=True)
class SimulationConfig:
    """Reproducible configuration for an intraday execution simulation run."""

    config_id: str
    initial_cash: Decimal
    cost_profile: CostProfile
    execution_mode: str = "CANDLE_ONLY"            # "CANDLE_ONLY" | "QUOTE_OR_TRADE"
    next_bar_execution: bool = True
    latency_bars: int = 0
    max_participation_rate: Decimal = Decimal("0.25")
    ambiguous_intrabar_rule: str = "ADVERSE"       # "ADVERSE" | "MARK_AMBIGUOUS"
    allow_partial_fills: bool = True
    enforce_intraday_cutoff: bool = True
    crypto_cutoff_utc: Optional[dt_time] = dt_time(23, 55)
    require_verified_calendar: bool = True
    dataset_id: Optional[str] = None
    dataset_version: Optional[str] = None
    manifest_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        if self.execution_mode not in ("CANDLE_ONLY", "QUOTE_OR_TRADE"):
            raise SimulatorConfigError(f"Invalid execution_mode: {self.execution_mode!r}")
        if self.ambiguous_intrabar_rule not in ("ADVERSE", "MARK_AMBIGUOUS"):
            raise SimulatorConfigError(f"Invalid ambiguous_intrabar_rule: {self.ambiguous_intrabar_rule!r}")
        if isinstance(self.initial_cash, (float, bool)) or not isinstance(self.initial_cash, Decimal) or self.initial_cash <= 0:
            raise SimulatorConfigError("initial_cash must be a positive Decimal")
        if self.max_participation_rate <= 0 or self.max_participation_rate > Decimal("1"):
            raise SimulatorConfigError("max_participation_rate must be in (0, 1]")
        if self.latency_bars < 0:
            raise SimulatorConfigError("latency_bars must be >= 0")
