"""Scanner V6 configuration.

Only neutral settings live here for now. Strategy parameters (swing size, sweep rules, patterns, confirmation, stop,
target...) are added one concept at a time, each with its definition and tests, never in advance.

V6 is research-only: PAPER_ONLY and PLACES_ORDERS are constants, not settings, and there is no switch that connects
V6 to a broker or to the live runner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

VERSION = "v6-dev"
PAPER_ONLY = True        # research branch: never real money
PLACES_ORDERS = False    # V6 has no order path at all


@dataclass(frozen=True)
class V6Config:
    """Run settings that do not encode a trading rule."""
    symbol: Optional[str] = None
    timeframe: Optional[str] = None          # label only (e.g. "5m"); V6 does not resample yet

    def __post_init__(self) -> None:
        if self.timeframe is not None and not isinstance(self.timeframe, str):
            raise ValueError("timeframe must be a string label such as '5m'")
