"""Conservative candle-based and quote-based fill model."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..storage.canonical_schema import CanonicalCandle, CanonicalQuote
from .models import OrderSide, OrderType, SimulatedOrder
from .specs import EffectiveSpec, round_price_to_tick


@dataclass(frozen=True)
class FillDecision:
    should_fill: bool
    raw_price: Optional[Decimal] = None
    execution_basis: str = ""
    is_ambiguous: bool = False
    apply_spread: bool = True


class FillModel:
    """Determines conservative fill prices from quotes or OHLCV candles."""

    def evaluate_order_on_quote(self, order: SimulatedOrder, quote: CanonicalQuote, spec: EffectiveSpec) -> FillDecision:
        if order.order_type == OrderType.MARKET:
            px = quote.ask_price if order.side == OrderSide.BUY else quote.bid_price
            return FillDecision(True, round_price_to_tick(px, spec.tick_size, order.side, adverse=True), "QUOTE_BBO", apply_spread=False)
        if order.order_type == OrderType.LIMIT and order.limit_price is not None:
            if order.side == OrderSide.BUY and quote.ask_price <= order.limit_price:
                return FillDecision(True, round_price_to_tick(quote.ask_price, spec.tick_size, order.side, adverse=True), "QUOTE_LIMIT", apply_spread=False)
            if order.side == OrderSide.SELL and quote.bid_price >= order.limit_price:
                return FillDecision(True, round_price_to_tick(quote.bid_price, spec.tick_size, order.side, adverse=True), "QUOTE_LIMIT", apply_spread=False)
            return FillDecision(False)
        if order.order_type == OrderType.STOP and order.stop_price is not None:
            if order.side == OrderSide.BUY and quote.ask_price >= order.stop_price:
                return FillDecision(True, round_price_to_tick(quote.ask_price, spec.tick_size, order.side, adverse=True), "QUOTE_STOP", apply_spread=False)
            if order.side == OrderSide.SELL and quote.bid_price <= order.stop_price:
                return FillDecision(True, round_price_to_tick(quote.bid_price, spec.tick_size, order.side, adverse=True), "QUOTE_STOP", apply_spread=False)
        return FillDecision(False)

    def evaluate_order_on_candle(self, order: SimulatedOrder, bar: CanonicalCandle, spec: EffectiveSpec) -> FillDecision:
        if order.order_type == OrderType.MARKET:
            px = round_price_to_tick(bar.open, spec.tick_size, order.side, adverse=True)
            return FillDecision(True, px, "CANDLE_NEXT_OPEN")

        if order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                return FillDecision(False)
            lim = order.limit_price
            if order.side == OrderSide.BUY:
                if bar.low <= lim:
                    # Conservative: fill at limit_price unless gapped strictly below at open
                    raw = min(bar.open, lim)
                    return FillDecision(True, round_price_to_tick(raw, spec.tick_size, order.side, adverse=True), "CANDLE_LIMIT")
            else:
                if bar.high >= lim:
                    raw = max(bar.open, lim)
                    return FillDecision(True, round_price_to_tick(raw, spec.tick_size, order.side, adverse=True), "CANDLE_LIMIT")
            return FillDecision(False)

        if order.order_type == OrderType.STOP:
            if order.stop_price is None:
                return FillDecision(False)
            stp = order.stop_price
            if order.side == OrderSide.BUY:
                if bar.high >= stp:
                    # Gap-up through stop fills at bar.open (adverse)
                    basis = "CANDLE_GAP_OPEN" if bar.open > stp else "CANDLE_STOP"
                    raw = max(bar.open, stp)
                    return FillDecision(True, round_price_to_tick(raw, spec.tick_size, order.side, adverse=True), basis)
            else:
                if bar.low <= stp:
                    # Gap-down through stop fills at bar.open (adverse)
                    basis = "CANDLE_GAP_OPEN" if bar.open < stp else "CANDLE_STOP"
                    raw = min(bar.open, stp)
                    return FillDecision(True, round_price_to_tick(raw, spec.tick_size, order.side, adverse=True), basis)
            return FillDecision(False)

        return FillDecision(False)

    def evaluate_bracket_exit_on_candle(
        self,
        *,
        position_qty: Decimal,
        stop_loss: Optional[Decimal],
        take_profit: Optional[Decimal],
        bar: CanonicalCandle,
        spec: EffectiveSpec,
    ) -> FillDecision:
        """Check SL/TP exit on a candle; when both are touched, apply conservative adverse SL priority."""
        if position_qty == 0:
            return FillDecision(False)
        is_long = position_qty > 0
        exit_side = OrderSide.SELL if is_long else OrderSide.BUY

        sl_hit = False
        tp_hit = False
        sl_px: Optional[Decimal] = None
        tp_px: Optional[Decimal] = None

        if stop_loss is not None:
            if is_long and bar.low <= stop_loss:
                sl_hit = True
                sl_px = min(bar.open, stop_loss)
            elif (not is_long) and bar.high >= stop_loss:
                sl_hit = True
                sl_px = max(bar.open, stop_loss)

        if take_profit is not None:
            if is_long and bar.high >= take_profit:
                tp_hit = True
                tp_px = max(bar.open, take_profit)
            elif (not is_long) and bar.low <= take_profit:
                tp_hit = True
                tp_px = min(bar.open, take_profit)

        if sl_hit and tp_hit:
            # Never silently choose TP when intrabar sequence is unknown
            assert sl_px is not None
            return FillDecision(
                True,
                round_price_to_tick(sl_px, spec.tick_size, exit_side, adverse=True),
                "AMBIGUOUS_ADVERSE",
                is_ambiguous=True,
            )
        if sl_hit and sl_px is not None:
            basis = "CANDLE_GAP_OPEN" if ((is_long and bar.open < stop_loss) or ((not is_long) and bar.open > stop_loss)) else "CANDLE_STOP_LOSS"
            return FillDecision(True, round_price_to_tick(sl_px, spec.tick_size, exit_side, adverse=True), basis)
        if tp_hit and tp_px is not None:
            return FillDecision(True, round_price_to_tick(tp_px, spec.tick_size, exit_side, adverse=True), "CANDLE_TAKE_PROFIT")
        return FillDecision(False)
