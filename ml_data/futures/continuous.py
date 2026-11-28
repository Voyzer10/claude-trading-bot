"""Derived continuous futures research series builder with explicit rollover & adjustment provenance."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from .config import DATABENTO_DATASET
from .exceptions import FuturesInputError
from .historical import FuturesOHLCVBar

SUPPORTED_ROLL_RULES = ("calendar", "volume", "open_interest")
SUPPORTED_ADJUSTMENT_POLICIES = ("raw_unadjusted", "panama_back_adjusted", "ratio_back_adjusted")


@dataclass(frozen=True)
class ContinuousSeriesBar:
    """One observation in a derived continuous research series (never an execution instrument)."""

    series_id: str
    product_root: str
    actual_instrument_id: str
    actual_symbol: str
    effective_mapping_date: date
    roll_rule: str
    rollover_date: Optional[date]
    dataset: str
    adjustment_policy: str
    ts_utc: datetime
    raw_open: Decimal
    raw_high: Decimal
    raw_low: Decimal
    raw_close: Decimal
    adjusted_open: Decimal
    adjusted_high: Decimal
    adjusted_low: Decimal
    adjusted_close: Decimal
    volume: int
    open_interest: Optional[int] = None


class ContinuousContractBuilder:
    """Constructs reproducible continuous research series without mutating raw dated-contract bars."""

    def build(
        self,
        *,
        product_root: str,
        bars_by_contract: Dict[str, Sequence[FuturesOHLCVBar]],
        roll_schedule: Sequence[Tuple[date, str]],
        roll_rule: str = "calendar",
        adjustment_policy: str = "raw_unadjusted",
        dataset: str = DATABENTO_DATASET,
    ) -> List[ContinuousSeriesBar]:
        """Build a continuous series from sorted (effective_date, actual_symbol) roll schedule.

        Raw prices are always preserved alongside any back-adjusted prices.
        """
        if roll_rule not in SUPPORTED_ROLL_RULES:
            raise FuturesInputError(f"Unsupported roll_rule: {roll_rule!r}")
        if adjustment_policy not in SUPPORTED_ADJUSTMENT_POLICIES:
            raise FuturesInputError(f"Unsupported adjustment_policy: {adjustment_policy!r}")
        if not roll_schedule:
            raise FuturesInputError("roll_schedule must contain at least one (effective_date, actual_symbol) entry")

        schedule = sorted(roll_schedule, key=lambda x: x[0])
        root = product_root.strip().upper()
        series_id = f"CONTINUOUS:{root}:{roll_rule}:{adjustment_policy}"

        if roll_rule == "open_interest":
            # Verify at least one bar actually has exchange-reported OI before claiming OI-based roll
            has_oi = any(b.open_interest is not None for seq in bars_by_contract.values() for b in seq)
            if not has_oi:
                raise FuturesInputError("Cannot use open_interest roll_rule without verified open_interest data")

        # Collect raw segment bars per schedule window
        raw_points: List[Tuple[date, Optional[date], FuturesOHLCVBar]] = []
        for idx, (eff_date, sym) in enumerate(schedule):
            next_eff = schedule[idx + 1][0] if idx + 1 < len(schedule) else None
            roll_dt = next_eff
            for bar in bars_by_contract.get(sym, ()):
                b_date = bar.ts_ct.date()
                if b_date >= eff_date and (next_eff is None or b_date < next_eff):
                    raw_points.append((eff_date, roll_dt, bar))

        raw_points.sort(key=lambda x: x[2].ts_utc)
        if not raw_points:
            return []

        # Compute backward cumulative adjustments at roll transitions without altering raw prices
        n = len(raw_points)
        add_offsets = [Decimal("0")] * n
        mul_factors = [Decimal("1")] * n

        if adjustment_policy != "raw_unadjusted":
            cum_add = Decimal("0")
            cum_mul = Decimal("1")
            for i in range(n - 2, -1, -1):
                cur_bar = raw_points[i][2]
                nxt_bar = raw_points[i + 1][2]
                if cur_bar.raw_symbol != nxt_bar.raw_symbol:
                    diff = nxt_bar.close - cur_bar.close
                    ratio = (nxt_bar.close / cur_bar.close) if cur_bar.close > 0 else Decimal("1")
                    cum_add += diff
                    cum_mul *= ratio
                add_offsets[i] = cum_add
                mul_factors[i] = cum_mul

        out: List[ContinuousSeriesBar] = []
        for i, (eff_d, roll_d, b) in enumerate(raw_points):
            if adjustment_policy == "panama_back_adjusted":
                ao, ah, al, ac = b.open + add_offsets[i], b.high + add_offsets[i], b.low + add_offsets[i], b.close + add_offsets[i]
            elif adjustment_policy == "ratio_back_adjusted":
                ao, ah, al, ac = b.open * mul_factors[i], b.high * mul_factors[i], b.low * mul_factors[i], b.close * mul_factors[i]
            else:
                ao, ah, al, ac = b.open, b.high, b.low, b.close

            out.append(
                ContinuousSeriesBar(
                    series_id=series_id,
                    product_root=root,
                    actual_instrument_id=b.instrument_id,
                    actual_symbol=b.raw_symbol,
                    effective_mapping_date=eff_d,
                    roll_rule=roll_rule,
                    rollover_date=roll_d,
                    dataset=dataset,
                    adjustment_policy=adjustment_policy,
                    ts_utc=b.ts_utc,
                    raw_open=b.open,
                    raw_high=b.high,
                    raw_low=b.low,
                    raw_close=b.close,
                    adjusted_open=ao,
                    adjusted_high=ah,
                    adjusted_low=al,
                    adjusted_close=ac,
                    volume=b.volume,
                    open_interest=b.open_interest,
                )
            )
        return out
