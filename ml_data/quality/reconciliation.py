"""Cross-market reconciliation between provider records, canonical registry, and multi-provider quotes/bars."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from ..instruments import InstrumentRegistry
from ..storage.canonical_schema import CanonicalCandle


@dataclass(frozen=True)
class PriceDiscrepancy:
    instrument_id: str
    timestamp_start_utc: str
    provider_a: str
    feed_a: str
    close_a: Decimal
    provider_b: str
    feed_b: str
    close_b: Decimal
    abs_diff: Decimal


@dataclass
class ReconciliationReport:
    total_checked: int
    unregistered_instruments: List[str] = field(default_factory=list)
    timestamp_mismatches: List[Dict[str, Any]] = field(default_factory=list)
    price_discrepancies: List[PriceDiscrepancy] = field(default_factory=list)
    missing_vs_expected: int = 0


class CrossMarketReconciler:
    """Reconciles canonical candles against registry instruments and multi-provider observations."""

    def __init__(self, *, registry: InstrumentRegistry) -> None:
        self.registry = registry

    def reconcile_candles(
        self,
        candles: Sequence[CanonicalCandle],
        *,
        expected_count: Optional[int] = None,
    ) -> ReconciliationReport:
        unreg = set()
        ts_mismatches: List[Dict[str, Any]] = []
        by_slot: Dict[tuple, List[CanonicalCandle]] = {}

        for c in candles:
            if self.registry.get(c.instrument_id) is None:
                unreg.add(c.instrument_id)
            if c.timestamp_start_utc.tzinfo is None or str(c.timestamp_start_utc.tzinfo) != "UTC":
                ts_mismatches.append({"instrument_id": c.instrument_id, "ts": c.timestamp_start_utc.isoformat()})
            by_slot.setdefault((c.instrument_id, c.timeframe, c.timestamp_start_utc), []).append(c)

        discrepancies: List[PriceDiscrepancy] = []
        for (iid, _tf, ts), grp in sorted(by_slot.items()):
            if len(grp) < 2:
                continue
            ref = grp[0]
            for other in grp[1:]:
                if other.close != ref.close:
                    discrepancies.append(
                        PriceDiscrepancy(
                            instrument_id=iid,
                            timestamp_start_utc=ts.isoformat(),
                            provider_a=ref.provider,
                            feed_a=ref.provider_feed,
                            close_a=ref.close,
                            provider_b=other.provider,
                            feed_b=other.provider_feed,
                            close_b=other.close,
                            abs_diff=abs(other.close - ref.close),
                        )
                    )

        missing = max(0, expected_count - len(by_slot)) if expected_count is not None else 0
        return ReconciliationReport(
            total_checked=len(candles),
            unregistered_instruments=sorted(unreg),
            timestamp_mismatches=ts_mismatches,
            price_discrepancies=discrepancies,
            missing_vs_expected=missing,
        )
