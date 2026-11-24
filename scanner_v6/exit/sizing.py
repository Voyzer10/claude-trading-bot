"""Module E: risk-based position sizing, net R:R and margin (research paper simulation only).

Spec references (research/v6/specs/V6_TRADING_SPEC_v0.2.md):
  Section 7, CK-23  risk budget B = 0.01 x E (E = current mark-to-market paper equity, OQ-6);
                    Loss(q) = q x |entry_fill - stop_fill| x M + Fees(entry, q) + Fees(stop exit, q);
                    q = largest permitted quantity with Loss(q) <= B, rounded DOWN on the quantity grid, never up;
                    net R:R = (q x reward x M - Fees(entry, q) - Fees(target exit, q)) / Loss(q); minimum 1:1.
  CK-13, CK-14      minimum quantity above the budget -> MIN_QTY_EXCEEDS_RISK_BUDGET; margin shortfall -> reduce the
                    quantity, revalidate every constraint, else INSUFFICIENT_MARGIN; entry / SL / TP never change.
  ME-3              (owner decision 24 Nov 2026) required margin = entry_fill x q x M x initial_margin_rate; available
                    margin = current paper equity (the account is flat at every entry under the one-position limit).

Implementation choices (documented in 17.V, not trading rules):
  * reward and stop distance are DIRECTIONAL (BUY target - entry, SELL entry - target), so an entry at or beyond the TP
    gives a non-positive reward and fails the 1:1 check (CK-22 "revalidate"); in every normal case this equals the
    |target - entry| of Section 7.
  * the CK-13 #4 net R:R check is evaluated at the risk-sized quantity; when no permitted quantity fits the budget it is
    evaluated at `min_quantity` (fees may contain a per-order part, so R:R depends on q).
ME-5 (owner 24 Nov 2026): fees are computed per FILL with the fill's own side (entry = trade side, stop / target exit
= the opposite side) and the decision time, so a side-aware schedule charges sell-side fees only on SELL fills.
All arithmetic is exact Decimal (net_rr itself is a reported Decimal quotient; the 1:1 check compares exact
products). Nothing here touches an order path.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from typing import Optional

from .execution_config import FeeSchedule
from .stop_loss import BUY, SELL

RISK_FRACTION = Decimal("0.01")       # Section 7 / CK-23: 1% of paper equity (OWNER APPROVED)
MIN_NET_RR = Decimal("1")             # Section 7 / CK-21: 1:1 after fees and slippage (OWNER APPROVED)


@dataclass(frozen=True)
class Costs:
    side: str
    entry_fill: Decimal
    stop_fill: Decimal
    target_fill: Decimal
    multiplier: Decimal
    fees: FeeSchedule
    at: Optional[datetime] = None          # decision time, passed to the fee schedule (ME-5)

    def _fee(self, price: Decimal, q: Decimal, entry: bool) -> Decimal:
        exit_side = SELL if self.side == BUY else BUY
        return self.fees.fee(price, q, self.multiplier, fill_side=self.side if entry else exit_side, at=self.at)

    def stop_distance(self) -> Decimal:
        return self.entry_fill - self.stop_fill if self.side == BUY else self.stop_fill - self.entry_fill

    def reward_distance(self) -> Decimal:
        return self.target_fill - self.entry_fill if self.side == BUY else self.entry_fill - self.target_fill

    def loss(self, q: Decimal) -> Decimal:
        return (q * self.stop_distance() * self.multiplier + self._fee(self.entry_fill, q, True)
                + self._fee(self.stop_fill, q, False))

    def net_reward(self, q: Decimal) -> Decimal:
        return (q * self.reward_distance() * self.multiplier - self._fee(self.entry_fill, q, True)
                - self._fee(self.target_fill, q, False))

    def net_rr(self, q: Decimal) -> Optional[Decimal]:
        lo = self.loss(q)
        return None if lo <= 0 else self.net_reward(q) / lo

    def rr_ok(self, q: Decimal) -> bool:
        """net R:R >= 1:1, decided exactly as net_reward >= MIN_NET_RR x Loss (no rounded quotient is compared)."""
        lo = self.loss(q)
        return lo > 0 and self.net_reward(q) >= MIN_NET_RR * lo


def largest_quantity(costs: Costs, budget: Decimal, step: Decimal, min_q: Decimal) -> Optional[Decimal]:
    """Largest q = n x step (n >= 1), q >= min_q, with Loss(q) <= budget; None when even min_q does not fit.
    Loss is non-decreasing in q (non-negative fees, monotone rounding), so a binary search is exact."""
    if costs.stop_distance() <= 0:
        raise ValueError("stop distance must be positive (entry at or beyond SL is rejected earlier)")
    n_min = int(min_q / step)
    if budget <= 0 or costs.loss(min_q) > budget:
        return None
    per_step = step * costs.stop_distance() * costs.multiplier
    lo, hi = n_min, max(n_min, int(budget / per_step) + 1)          # Loss(q) >= q x dist x M, so n <= budget / per_step
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if costs.loss(mid * step) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return lo * step


def required_margin(entry_fill: Decimal, q: Decimal, multiplier: Decimal, rate: Decimal) -> Decimal:
    return entry_fill * q * multiplier * rate


def margin_quantity(costs: Costs, q_risk: Decimal, step: Decimal, min_q: Decimal, rate: Decimal,
                    available: Decimal) -> Optional[Decimal]:
    """CK-14: the largest permitted q <= q_risk whose margin fits and which still passes every check (risk budget holds
    for any q <= q_risk; minimum quantity by construction; net R:R >= 1:1). None -> INSUFFICIENT_MARGIN."""
    n = int(q_risk / step)
    n_min = int(min_q / step)
    per_step = costs.entry_fill * step * costs.multiplier * rate     # margin is linear in q: skip the steps that cannot fit
    if per_step > 0:
        n = min(n, int(available / per_step))
    while n >= n_min:
        q = n * step
        if required_margin(costs.entry_fill, q, costs.multiplier, rate) <= available and costs.rr_ok(q):
            return q
        n -= 1
    return None
