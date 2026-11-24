"""Module E: take-profit pool selection and target price (research paper simulation only).

Spec references (research/v6/specs/V6_TRADING_SPEC_v0.2.md):
  Section 6, CK-16  BUY TP: nearest eligible ACTIVE BSL pool above the actual entry; SELL TP: nearest eligible ACTIVE
                    SSL pool below the actual entry; SWEPT / TAKEN pools are ineligible; only pools known at the entry
                    decision time; ties at one price: earliest confirmed pool, then stable pool-id ordering (pool id
                    `pool:<swing_id>`, OQ-4); a farther pool is never tried; no eligible pool -> NO_TRADE with
                    disposition_reason NO_ELIGIBLE_OPPOSING_POOL (OQ-2).
  CK-21, OQ-8       TP price = pool price offset by the configured tick offset toward the entry (BUY pool - n ticks,
                    SELL pool + n ticks); touch triggers; fill at the exact TP (target_exit_ticks = 0); a gap beyond TP
                    fills at TP.
"Actual entry" is the entry FILL (Section 4: sizing and R:R use the actual entry fill); a pool qualifies only when it is
strictly beyond it.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional, Tuple

from .stop_loss import BUY, SELL, to_grid

ACTIVE = "ACTIVE"


@dataclass(frozen=True)
class PoolView:
    """A pool as known at the entry decision time: id, side (BSL / SSL), price, confirmation index, lifecycle state."""
    pool_id: str
    side: str
    price: Decimal
    confirmed_index: int
    state: str


def select_target_pool(side: str, entry_fill: Decimal, pools: Iterable[PoolView]) -> Optional[PoolView]:
    if side == BUY:
        cand = [p for p in pools if p.side == "BSL" and p.state == ACTIVE and p.price > entry_fill]
        cand.sort(key=lambda p: (p.price, p.confirmed_index, p.pool_id))
    elif side == SELL:
        cand = [p for p in pools if p.side == "SSL" and p.state == ACTIVE and p.price < entry_fill]
        cand.sort(key=lambda p: (-p.price, p.confirmed_index, p.pool_id))
    else:
        raise ValueError("side must be BUY or SELL")
    return cand[0] if cand else None


def target_price(side: str, pool_price: Decimal, offset_ticks: int, tick: Decimal, mode: str) -> Decimal:
    return to_grid(pool_price - offset_ticks * tick if side == BUY else pool_price + offset_ticks * tick, tick, mode)


def tie_info(side: str, entry_fill: Decimal, pools: Iterable[PoolView]) -> Tuple[str, ...]:
    """Ids of the eligible pools at the selected price (traceability of the CK-16 tie-break)."""
    sel = select_target_pool(side, entry_fill, list(pools))
    if sel is None:
        return ()
    return tuple(sorted(p.pool_id for p in pools if p.side == sel.side and p.state == ACTIVE and p.price == sel.price))
