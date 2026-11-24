"""Module E: structural stop-loss and stop fills (research paper simulation only; no order is ever sent).

Spec references (research/v6/specs/V6_TRADING_SPEC_v0.2.md):
  Section 5, CK-20  BUY SL = SSL sweep candle low - buffer; SELL SL = BSL sweep candle high + buffer; buffer in ticks
                    per instrument (configured, never defaulted); the setup's own sweep candle; no future-confirmed swing;
                    SL fixed after entry, never moved to force R:R or sizing.
  Section 5 / 9     stop fills: normal hit BUY SL - stop_exit_ticks x T, SELL SL + stop_exit_ticks x T; gap through the
                    stop BUY open - stop_exit_ticks x T, SELL open + stop_exit_ticks x T; no extra gap slippage.
"""
from __future__ import annotations

import decimal
from decimal import Decimal

BUY, SELL = "BUY", "SELL"


def to_grid(x: Decimal, tick: Decimal, mode: str) -> Decimal:
    """`x` itself when it is on the tick grid; otherwise rounded onto it with the configured mode (B-13 rule is
    configuration, OQ-15). Never clamps to a candle range."""
    q = x / tick
    if q == q.to_integral_value():
        return x
    return q.to_integral_value(rounding=getattr(decimal, mode)) * tick


def structural_sl(side: str, sweep_low: Decimal, sweep_high: Decimal, buffer_ticks: int, tick: Decimal,
                  mode: str) -> Decimal:
    if side == BUY:
        return to_grid(sweep_low - buffer_ticks * tick, tick, mode)
    if side == SELL:
        return to_grid(sweep_high + buffer_ticks * tick, tick, mode)
    raise ValueError("side must be BUY or SELL")


def stop_fill(side: str, sl: Decimal, stop_exit_ticks: int, tick: Decimal, mode: str) -> Decimal:
    """Fill of a normal stop hit (also the planned stop fill used for sizing, Section 7)."""
    return to_grid(sl - stop_exit_ticks * tick if side == BUY else sl + stop_exit_ticks * tick, tick, mode)


def gap_stop_fill(side: str, open_: Decimal, stop_exit_ticks: int, tick: Decimal, mode: str) -> Decimal:
    """Fill when the candle opens at or beyond the stop: the worse opening price plus the configured stop slippage."""
    return to_grid(open_ - stop_exit_ticks * tick if side == BUY else open_ + stop_exit_ticks * tick, tick, mode)
