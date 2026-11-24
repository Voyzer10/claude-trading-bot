"""Module E: FIXED_SL_TP trade management, one completed candle at a time (research paper simulation only).

Spec references (research/v6/specs/V6_TRADING_SPEC_v0.2.md):
  Section 10        FIXED_SL_TP: no trailing stop, no breakeven, no partial profit, no SL / TP change after entry.
  Section 9, CK-22  SL and TP touched in one candle -> STOP_FIRST (also on the entry candle, after the entry fill);
                    ambiguous intrabar order -> adverse outcome first; a stop gap fills at the open plus stop slippage;
                    a target gap fills at the exact TP; a fill is never clamped to the candle range: the calculated
                    fill is kept and an out-of-range diagnostic is recorded.
  Section 4         the entry candle C+1 is checked for SL / TP after the entry fill (its open is the entry, so no gap
                    rule can apply to it).
  OQ-3, CK-24       nothing is evaluated for an unobserved interval: exits are only ever derived from an observed
                    completed candle.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from .stop_loss import BUY, SELL, gap_stop_fill, stop_fill

STOPPED_OUT, TARGET_HIT = "STOPPED_OUT", "TARGET_HIT"


@dataclass(frozen=True)
class ExitFill:
    status: str              # STOPPED_OUT / TARGET_HIT
    fill: Decimal
    gap: bool                # the candle opened at or beyond the level
    diagnostics: Tuple[str, ...]


def evaluate_exit(side: str, o: Decimal, h: Decimal, l: Decimal, sl: Decimal, tp: Decimal, stop_exit_ticks: int,
                  tick: Decimal, mode: str, entry_candle: bool) -> Optional[ExitFill]:
    """The exit on this completed candle, or None. Order: stop gap, stop touch, target gap, target touch (STOP_FIRST)."""
    if side == BUY:
        stop_gap, stop_touch = (not entry_candle and o <= sl), l <= sl
        tgt_gap, tgt_touch = (not entry_candle and o >= tp), h >= tp
    elif side == SELL:
        stop_gap, stop_touch = (not entry_candle and o >= sl), h >= sl
        tgt_gap, tgt_touch = (not entry_candle and o <= tp), l <= tp
    else:
        raise ValueError("side must be BUY or SELL")
    diags = []
    if stop_gap or stop_touch:
        fill = gap_stop_fill(side, o, stop_exit_ticks, tick, mode) if stop_gap else stop_fill(side, sl, stop_exit_ticks, tick, mode)
        if tgt_touch or tgt_gap:
            diags.append("SL_TP_SAME_CANDLE_STOP_FIRST")
        st, gap = STOPPED_OUT, stop_gap
    elif tgt_gap or tgt_touch:
        fill, st, gap = tp, TARGET_HIT, tgt_gap
    else:
        return None
    if fill < l or fill > h:
        diags.append("FILL_OUTSIDE_CANDLE_RANGE")
    return ExitFill(st, fill, gap, tuple(diags))
