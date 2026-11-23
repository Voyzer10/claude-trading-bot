"""Liquidity pools (LiquidityPool events): where resting stops are assumed to sit.

Implemented from OWNER APPROVED rules only (liquidity register LQ-01, LQ-04, LQ-06, LQ-16, G-1 / LP-01, G-6, G-7;
spec CK-15 and OQ-4 in 17.O):
  - every confirmed L2/R2 swing creates exactly one pool (LQ-01, CK-15.1); a dual-pivot candle gives two pools
  - BSL = swing high (pool ABOVE price), SSL = swing low (pool BELOW price) (CK-15.2-3)
  - pool price = the exact wick extreme, i.e. the swing price; no zone (LQ-04)
  - pool id = "pool:<swing_id>" (OQ-4); stable and deterministic, no UUIDs (G-6)
  - a pool is created at the close of its swing's confirmation candle and is evaluated from the NEXT candle on
    (G-1 / LP-01: "evaluate pools confirmed before candle k")
  - lifecycle ACTIVE -> SWEPT -> TAKEN (LQ-06); TAKEN is final and never flips side (LQ-16)
  - pools exist independently of the market-structure state (G-7); no major / minor, internal / external, equal-level
    or trendline / range pools (CK-15.6-8, 16; LQ-02, LQ-03 MVP exclusion, LQ-05, LQ-18, LQ-19)
  - no expiry by elapsed time (LQ-07 approved part). Other expiry forms are OPEN, so none is implemented: a pool stays
    until TAKEN.
Comparisons are raw floats (G-8, pending BOS-006 / C1): no tick-size epsilon is applied.
"""
from __future__ import annotations

from scanner_v6.models import LiquidityPool, PoolSide, SwingKind, SwingPoint

BSL = "BSL"
SSL = "SSL"
ACTIVE = "ACTIVE"
SWEPT = "SWEPT"
TAKEN = "TAKEN"
POOL_STATES = (ACTIVE, SWEPT, TAKEN)


def pool_id(swing_id: str) -> str:
    """OQ-4: pool:<swing_id>."""
    if not isinstance(swing_id, str) or not swing_id:
        raise ValueError("swing_id must be a non-empty string")
    return "pool:%s" % swing_id


def pool_from_swing(swing: SwingPoint) -> LiquidityPool:
    """The pool of a confirmed swing. Its stamp is the swing's: source candle = swing candle, known at the swing's
    confirmation candle. It is evaluated from confirmation + 1 (G-1)."""
    if not isinstance(swing, SwingPoint) or swing.confirmed_index is None:
        raise ValueError("a pool needs a confirmed SwingPoint")
    side = PoolSide.ABOVE if swing.kind is SwingKind.HIGH else PoolSide.BELOW
    return LiquidityPool(pool_id(swing.id), swing.stamp, related=(swing.id,), side=side, price=swing.price)


def pool_side(pool: LiquidityPool) -> str:
    """BSL for a pool above price (swing high), SSL for a pool below price (swing low)."""
    return BSL if pool.side is PoolSide.ABOVE else SSL
