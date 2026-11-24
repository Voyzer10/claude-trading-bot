"""US F&O (US options) book: interfaces only. BLOCKED until the owner provides an independently verified options feed
(bid/ask), a contract mapping and an approved fee model. Nothing here invents a contract, strike, expiry, multiplier,
price or fill: `readiness()` reports BLOCKED and there is no execution path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Protocol

STATUS = "US F&O PAPER EXECUTION: BLOCKED / NOT READY"


@dataclass(frozen=True)
class OptionContract:
    """One listed contract, exactly as a verified provider reports it (never derived)."""
    contract_symbol: str
    underlying: str
    expiry: date
    strike: Decimal
    right: str               # "C" / "P"
    multiplier: Decimal
    tick_size: Decimal
    quantity_step: Decimal
    source: str


@dataclass(frozen=True)
class OptionQuote:
    contract_symbol: str
    bid: Decimal
    ask: Decimal
    ts_utc: str
    source: str


class OptionsProvider(Protocol):
    """Boundary for a future verified options provider. No implementation exists."""

    def contracts(self, underlying: str) -> Iterable[OptionContract]: ...

    def quotes(self, contract_symbols: Iterable[str]) -> Iterable[OptionQuote]: ...


REQUIREMENTS = ("independent options market-data provider (verified)", "contract mapping rule (owner-approved)",
                "bid/ask pricing reference", "options session calendar", "options fee model (IC-1)",
                "options slippage (B-10)", "quantity / lot grid (IC-2)", "MTM slippage (IC-7)")


def readiness(provider: Optional[OptionsProvider] = None, approvals: Optional[Dict[str, bool]] = None) -> Dict[str, object]:
    approvals = approvals or {}
    missing: List[str] = [r for r in REQUIREMENTS if not approvals.get(r)]
    if provider is None:
        missing.insert(0, "no options provider configured")
    return {"book_id": "USFNO", "ready": False, "status": STATUS, "blockers": missing or ["execution path not built"]}
