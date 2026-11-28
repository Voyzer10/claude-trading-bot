"""Decimal-safe transaction cost, slippage, and spread calculator."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .config import CostProfile
from .models import OrderSide

_BPS_DIV = Decimal("10000")


@dataclass(frozen=True)
class CostBreakdown:
    slippage_cost: Decimal
    spread_cost: Decimal
    fee_cost: Decimal
    tax_cost: Decimal
    total_cost: Decimal
    net_fill_price: Decimal


class TransactionCostModel:
    """Computes explicit slippage, spread, fee, and tax costs from a versioned CostProfile."""

    def __init__(self, profile: CostProfile) -> None:
        self.profile = profile

    def compute(
        self,
        *,
        side: OrderSide,
        raw_price: Decimal,
        quantity: Decimal,
        multiplier: Decimal,
        is_first_fill_for_order: bool = True,
        apply_spread: bool = True,
    ) -> CostBreakdown:
        notional = raw_price * quantity * multiplier
        slip_per_unit = raw_price * (self.profile.slippage_bps / _BPS_DIV)
        spr_per_unit = (raw_price * (self.profile.spread_half_bps / _BPS_DIV)) if apply_spread else Decimal("0")

        if side == OrderSide.BUY:
            net_px = raw_price + slip_per_unit + spr_per_unit
        else:
            net_px = max(Decimal("0"), raw_price - slip_per_unit - spr_per_unit)

        slippage_cost = slip_per_unit * quantity * multiplier
        spread_cost = spr_per_unit * quantity * multiplier
        fee_cost = (notional * (self.profile.fee_bps / _BPS_DIV)) + (self.profile.per_contract_fee * quantity)
        if is_first_fill_for_order:
            fee_cost += self.profile.fixed_fee_per_order
        tax_cost = notional * (self.profile.tax_bps / _BPS_DIV)
        total_cost = slippage_cost + spread_cost + fee_cost + tax_cost
        return CostBreakdown(
            slippage_cost=slippage_cost,
            spread_cost=spread_cost,
            fee_cost=fee_cost,
            tax_cost=tax_cost,
            total_cost=total_cost,
            net_fill_price=net_px,
        )
