"""Deterministic, intraday-only ExecutionSimulator engine."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from ..calendars.base import ExchangeCalendar
from ..instruments import InstrumentRegistry
from ..storage.canonical_schema import CanonicalCandle, CanonicalQuote
from .config import SimulationConfig
from .costs import TransactionCostModel
from .exceptions import CalendarVerificationError
from .fills import FillModel
from .models import (
    EquityPoint,
    FillEvent,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionState,
    SimulatedOrder,
    SimulationEvent,
    SimulationMetrics,
    SimulationResult,
    TimeInForce,
)
from .specs import EffectiveSpec, EffectiveSpecResolver, round_qty_to_step


class ExecutionSimulator:
    """Replays CanonicalCandle (and optional CanonicalQuote) streams with strict no-lookahead and cost accounting."""

    def __init__(
        self,
        *,
        config: SimulationConfig,
        registry: InstrumentRegistry,
        calendar: Optional[ExchangeCalendar] = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.calendar = calendar
        self.spec_resolver = EffectiveSpecResolver(registry)
        self.cost_model = TransactionCostModel(config.cost_profile)
        self.fill_model = FillModel()

    def run(
        self,
        candles: Sequence[CanonicalCandle],
        order_intents: Sequence[OrderIntent],
        *,
        quotes: Optional[Sequence[CanonicalQuote]] = None,
    ) -> SimulationResult:
        ordered_bars = sorted(candles, key=lambda b: (b.timestamp_start_utc, b.instrument_id))
        warnings: List[str] = []

        if self.config.require_verified_calendar and self.calendar is not None and ordered_bars:
            d0, d1 = ordered_bars[0].trading_date, ordered_bars[-1].trading_date
            if not self.calendar.is_verified_for_range(d0, d1):
                cal_meta = getattr(self.calendar, "metadata", None)
                cal_id = cal_meta.calendar_id if cal_meta is not None else type(self.calendar).__name__
                raise CalendarVerificationError(
                    f"Calendar {cal_id} is not verified for range {d0.isoformat()}..{d1.isoformat()}"
                )

        if self.config.execution_mode == "CANDLE_ONLY":
            warnings.append("CANDLE_ONLY_SIMULATION: intrabar price sequence is unknown; conservative fill rules applied.")

        quotes_by_slot: Dict[tuple, CanonicalQuote] = {}
        for q in quotes or ():
            quotes_by_slot[(q.instrument_id, q.event_time_utc)] = q

        cash = self.config.initial_cash
        positions: Dict[str, PositionState] = {}
        orders_out: List[SimulatedOrder] = []
        active_orders: List[SimulatedOrder] = []
        fills_out: List[FillEvent] = []
        events_out: List[SimulationEvent] = []
        equity_curve: List[EquityPoint] = []
        last_close_by_inst: Dict[str, Decimal] = {}
        last_mult_by_inst: Dict[str, Decimal] = {}

        # Index intents by decision_ts_utc
        intents_sorted = sorted(order_intents, key=lambda o: (o.decision_ts_utc, o.order_id))
        intent_idx = 0
        fill_seq = 0
        ambiguous_count = 0
        partial_fill_count = 0
        peak_equity = cash
        max_dd = Decimal("0")

        # Group bars by timestamp_start_utc so multi-instrument equity snapshots are aligned
        bars_by_ts: Dict[datetime, List[CanonicalCandle]] = {}
        for b in ordered_bars:
            bars_by_ts.setdefault(b.timestamp_start_utc, []).append(b)
        sorted_timestamps = sorted(bars_by_ts.keys())

        for ts_idx, bar_ts in enumerate(sorted_timestamps):
            bar_list = bars_by_ts[bar_ts]

            # 1. Admit any intents whose decision_ts_utc <= bar_ts
            while intent_idx < len(intents_sorted) and intents_sorted[intent_idx].decision_ts_utc <= bar_ts:
                intent = intents_sorted[intent_idx]
                intent_idx += 1
                spec = self.spec_resolver.resolve(intent.instrument_id, bar_ts)
                if spec is None:
                    rej = SimulatedOrder(
                        order_id=intent.order_id,
                        instrument_id=intent.instrument_id,
                        side=intent.side,
                        order_type=intent.order_type,
                        requested_quantity=intent.quantity,
                        remaining_quantity=intent.quantity,
                        filled_quantity=Decimal("0"),
                        decision_ts_utc=intent.decision_ts_utc,
                        earliest_executable_utc=bar_ts,
                        status=OrderStatus.REJECTED,
                        rejection_reason="unknown_instrument",
                    )
                    orders_out.append(rej)
                    events_out.append(SimulationEvent(bar_ts, "ORDER_REJECTED", intent.instrument_id, {"order_id": intent.order_id, "reason": "unknown_instrument"}))
                    continue

                req_qty = round_qty_to_step(intent.quantity, spec.quantity_step, spec.minimum_order_quantity)
                if req_qty <= 0:
                    rej = SimulatedOrder(
                        order_id=intent.order_id,
                        instrument_id=intent.instrument_id,
                        side=intent.side,
                        order_type=intent.order_type,
                        requested_quantity=intent.quantity,
                        remaining_quantity=intent.quantity,
                        filled_quantity=Decimal("0"),
                        decision_ts_utc=intent.decision_ts_utc,
                        earliest_executable_utc=bar_ts,
                        status=OrderStatus.REJECTED,
                        rejection_reason="quantity_below_minimum_or_invalid_step",
                        spec_version_id=spec.spec_version_id,
                    )
                    orders_out.append(rej)
                    events_out.append(SimulationEvent(bar_ts, "ORDER_REJECTED", intent.instrument_id, {"order_id": intent.order_id, "reason": rej.rejection_reason}))
                    continue

                if spec.expiry_date is not None and bar_ts.date() > spec.expiry_date:
                    rej = SimulatedOrder(
                        order_id=intent.order_id,
                        instrument_id=intent.instrument_id,
                        side=intent.side,
                        order_type=intent.order_type,
                        requested_quantity=req_qty,
                        remaining_quantity=req_qty,
                        filled_quantity=Decimal("0"),
                        decision_ts_utc=intent.decision_ts_utc,
                        earliest_executable_utc=bar_ts,
                        status=OrderStatus.REJECTED,
                        rejection_reason="instrument_expired",
                        spec_version_id=spec.spec_version_id,
                    )
                    orders_out.append(rej)
                    continue

                exec_idx = ts_idx + self.config.latency_bars
                earliest_ts = sorted_timestamps[exec_idx] if exec_idx < len(sorted_timestamps) else bar_ts
                is_prior_bar_close = (
                    ts_idx > 0
                    and any(pb.timestamp_end_utc == intent.decision_ts_utc for pb in bars_by_ts.get(sorted_timestamps[ts_idx - 1], ()))
                )
                if (
                    self.config.next_bar_execution
                    and not is_prior_bar_close
                    and intent.decision_ts_utc >= bar_ts
                    and ts_idx + 1 < len(sorted_timestamps)
                ):
                    # Signal during current bar cannot execute on the signal bar itself
                    earliest_ts = max(earliest_ts, sorted_timestamps[ts_idx + 1])

                so = SimulatedOrder(
                    order_id=intent.order_id,
                    instrument_id=intent.instrument_id,
                    side=intent.side,
                    order_type=intent.order_type,
                    requested_quantity=req_qty,
                    remaining_quantity=req_qty,
                    filled_quantity=Decimal("0"),
                    decision_ts_utc=intent.decision_ts_utc,
                    earliest_executable_utc=earliest_ts,
                    status=OrderStatus.ACCEPTED,
                    limit_price=intent.limit_price,
                    stop_price=intent.stop_price,
                    stop_loss=intent.stop_loss,
                    take_profit=intent.take_profit,
                    time_in_force=intent.time_in_force,
                    expiry_at_utc=intent.expiry_at_utc,
                    spec_version_id=spec.spec_version_id,
                )
                orders_out.append(so)
                active_orders.append(so)
                events_out.append(SimulationEvent(bar_ts, "ORDER_ACCEPTED", intent.instrument_id, {"order_id": so.order_id}))

            # 2. Process each instrument bar at bar_ts
            for bar in bar_list:
                iid = bar.instrument_id
                spec = self.spec_resolver.resolve(iid, bar_ts)
                if spec is None:
                    continue
                last_close_by_inst[iid] = bar.close
                last_mult_by_inst[iid] = spec.contract_multiplier
                pos = positions.setdefault(iid, PositionState(instrument_id=iid))

                is_closed = bar.trading_session in ("CLOSED", "MAINTENANCE_BREAK")
                is_crypto_cutoff = (
                    bar.market == "CRYPTO"
                    and self.config.enforce_intraday_cutoff
                    and self.config.crypto_cutoff_utc is not None
                    and (
                        bar.timestamp_end_utc.time() >= self.config.crypto_cutoff_utc
                        or bar.timestamp_end_utc.date() > bar.timestamp_start_utc.date()
                    )
                )
                is_last_bar_next_closed = False
                if self.config.enforce_intraday_cutoff and bar.market != "CRYPTO":
                    if ts_idx + 1 >= len(sorted_timestamps):
                        is_last_bar_next_closed = True
                    else:
                        nxt_bars = [x for x in bars_by_ts[sorted_timestamps[ts_idx + 1]] if x.instrument_id == iid]
                        if not nxt_bars or nxt_bars[0].trading_date != bar.trading_date or nxt_bars[0].trading_session in ("CLOSED", "MAINTENANCE_BREAK"):
                            is_last_bar_next_closed = True
                is_expiry_cutoff = spec.expiry_date is not None and bar.trading_date >= spec.expiry_date and is_last_bar_next_closed

                # 2a. Check active orders for this instrument
                still_active: List[SimulatedOrder] = []
                for ord_obj in active_orders:
                    if ord_obj.instrument_id != iid:
                        still_active.append(ord_obj)
                        continue
                    if ord_obj.expiry_at_utc is not None and bar_ts >= ord_obj.expiry_at_utc:
                        ord_obj.status = OrderStatus.EXPIRED
                        events_out.append(SimulationEvent(bar_ts, "ORDER_EXPIRED", iid, {"order_id": ord_obj.order_id}))
                        continue
                    if is_closed or is_last_bar_next_closed or is_crypto_cutoff:
                        ord_obj.status = OrderStatus.EXPIRED
                        events_out.append(SimulationEvent(bar_ts, "ORDER_EXPIRED_SESSION_END", iid, {"order_id": ord_obj.order_id}))
                        continue
                    if bar.timestamp_start_utc < ord_obj.earliest_executable_utc:
                        still_active.append(ord_obj)
                        continue

                    q_match = quotes_by_slot.get((iid, bar.timestamp_start_utc))
                    if self.config.execution_mode == "QUOTE_OR_TRADE" and q_match is not None:
                        dec = self.fill_model.evaluate_order_on_quote(ord_obj, q_match, spec)
                    else:
                        dec = self.fill_model.evaluate_order_on_candle(ord_obj, bar, spec)

                    if not dec.should_fill or dec.raw_price is None:
                        if ord_obj.time_in_force == TimeInForce.IOC:
                            ord_obj.status = OrderStatus.CANCELLED
                            events_out.append(SimulationEvent(bar_ts, "ORDER_CANCELLED_IOC", iid, {"order_id": ord_obj.order_id}))
                        else:
                            still_active.append(ord_obj)
                        continue

                    # Participation limit
                    max_part_qty = round_qty_to_step(
                        bar.volume * self.config.max_participation_rate,
                        spec.quantity_step,
                        spec.minimum_order_quantity,
                    )
                    if max_part_qty <= 0:
                        still_active.append(ord_obj)
                        continue
                    exec_qty = min(ord_obj.remaining_quantity, max_part_qty) if self.config.allow_partial_fills else ord_obj.remaining_quantity
                    if exec_qty < ord_obj.remaining_quantity and not self.config.allow_partial_fills:
                        still_active.append(ord_obj)
                        continue

                    fill_seq += 1
                    cb = self.cost_model.compute(
                        side=ord_obj.side,
                        raw_price=dec.raw_price,
                        quantity=exec_qty,
                        multiplier=spec.contract_multiplier,
                        is_first_fill_for_order=(ord_obj.filled_quantity == 0),
                        apply_spread=dec.apply_spread,
                    )
                    fe = FillEvent(
                        fill_id=f"fill-{fill_seq:06d}",
                        order_id=ord_obj.order_id,
                        instrument_id=iid,
                        ts_utc=bar.timestamp_start_utc,
                        side=ord_obj.side,
                        quantity=exec_qty,
                        raw_price=dec.raw_price,
                        net_fill_price=cb.net_fill_price,
                        slippage_cost=cb.slippage_cost,
                        spread_cost=cb.spread_cost,
                        fee_cost=cb.fee_cost,
                        tax_cost=cb.tax_cost,
                        total_cost=cb.total_cost,
                        execution_basis=dec.execution_basis,
                        is_ambiguous=dec.is_ambiguous,
                        spec_version_id=spec.spec_version_id,
                    )
                    fills_out.append(fe)
                    cash = self._apply_fill_to_position(pos, fe, spec, cash, ord_obj.stop_loss, ord_obj.take_profit)
                    ord_obj.filled_quantity += exec_qty
                    ord_obj.remaining_quantity -= exec_qty
                    if ord_obj.remaining_quantity <= 0:
                        ord_obj.status = OrderStatus.FILLED
                    else:
                        ord_obj.status = OrderStatus.PARTIALLY_FILLED
                        partial_fill_count += 1
                        if ord_obj.time_in_force == TimeInForce.IOC:
                            ord_obj.status = OrderStatus.CANCELLED
                        else:
                            still_active.append(ord_obj)
                    events_out.append(SimulationEvent(bar_ts, "FILL", iid, {"fill_id": fe.fill_id, "qty": str(exec_qty), "basis": fe.execution_basis}))

                active_orders = still_active

                # 2b. Evaluate bracket SL/TP exits on open position
                if pos.quantity != 0 and (pos.active_stop_loss is not None or pos.active_take_profit is not None):
                    b_dec = self.fill_model.evaluate_bracket_exit_on_candle(
                        position_qty=pos.quantity,
                        stop_loss=pos.active_stop_loss,
                        take_profit=pos.active_take_profit,
                        bar=bar,
                        spec=spec,
                    )
                    if b_dec.should_fill and b_dec.raw_price is not None:
                        if b_dec.is_ambiguous:
                            ambiguous_count += 1
                            warnings.append(f"AMBIGUOUS_INTRABAR_SL_TP at {bar_ts.isoformat()} on {iid}; applied adverse SL exit.")
                        exit_side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
                        exit_qty = abs(pos.quantity)
                        fill_seq += 1
                        cb = self.cost_model.compute(
                            side=exit_side,
                            raw_price=b_dec.raw_price,
                            quantity=exit_qty,
                            multiplier=spec.contract_multiplier,
                        )
                        fe = FillEvent(
                            fill_id=f"fill-{fill_seq:06d}",
                            order_id=f"bracket-exit-{fill_seq}",
                            instrument_id=iid,
                            ts_utc=bar.timestamp_start_utc,
                            side=exit_side,
                            quantity=exit_qty,
                            raw_price=b_dec.raw_price,
                            net_fill_price=cb.net_fill_price,
                            slippage_cost=cb.slippage_cost,
                            spread_cost=cb.spread_cost,
                            fee_cost=cb.fee_cost,
                            tax_cost=cb.tax_cost,
                            total_cost=cb.total_cost,
                            execution_basis=b_dec.execution_basis,
                            is_ambiguous=b_dec.is_ambiguous,
                            spec_version_id=spec.spec_version_id,
                        )
                        fills_out.append(fe)
                        cash = self._apply_fill_to_position(pos, fe, spec, cash, None, None)

                # 2c. Enforce intraday-only / expiry auto-flatten
                if pos.quantity != 0 and (is_last_bar_next_closed or is_crypto_cutoff or is_expiry_cutoff):
                    exit_side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
                    exit_qty = abs(pos.quantity)
                    fill_seq += 1
                    cb = self.cost_model.compute(
                        side=exit_side,
                        raw_price=bar.close,
                        quantity=exit_qty,
                        multiplier=spec.contract_multiplier,
                    )
                    fe = FillEvent(
                        fill_id=f"fill-{fill_seq:06d}",
                        order_id=f"intraday-flatten-{fill_seq}",
                        instrument_id=iid,
                        ts_utc=bar.timestamp_end_utc,
                        side=exit_side,
                        quantity=exit_qty,
                        raw_price=bar.close,
                        net_fill_price=cb.net_fill_price,
                        slippage_cost=cb.slippage_cost,
                        spread_cost=cb.spread_cost,
                        fee_cost=cb.fee_cost,
                        tax_cost=cb.tax_cost,
                        total_cost=cb.total_cost,
                        execution_basis="INTRADAY_SESSION_FLATTEN",
                        spec_version_id=spec.spec_version_id,
                    )
                    fills_out.append(fe)
                    cash = self._apply_fill_to_position(pos, fe, spec, cash, None, None)
                    events_out.append(SimulationEvent(bar.timestamp_end_utc, "INTRADAY_FLATTEN", iid, {"qty": str(exit_qty)}))

            # 3. Mark-to-market equity point
            total_unrealized = Decimal("0")
            gross_exp = Decimal("0")
            for iid, p in positions.items():
                if p.quantity != 0 and iid in last_close_by_inst:
                    px = last_close_by_inst[iid]
                    mult = last_mult_by_inst[iid]
                    p.unrealized_pnl = (px - p.avg_entry_price) * p.quantity * mult
                    total_unrealized += p.unrealized_pnl
                    gross_exp += abs(p.quantity) * px * mult
                else:
                    p.unrealized_pnl = Decimal("0")

            total_realized = sum((p.realized_pnl for p in positions.values()), Decimal("0"))
            total_costs = sum((p.total_costs for p in positions.values()), Decimal("0"))
            equity = self.config.initial_cash + total_realized + total_unrealized - total_costs
            if equity > peak_equity:
                peak_equity = equity
            dd = peak_equity - equity
            if dd > max_dd:
                max_dd = dd
            equity_curve.append(EquityPoint(bar_ts, cash, total_unrealized, equity, gross_exp, dd))

        # Reject any intents submitted after the last bar
        while intent_idx < len(intents_sorted):
            intent = intents_sorted[intent_idx]
            intent_idx += 1
            orders_out.append(
                SimulatedOrder(
                    order_id=intent.order_id,
                    instrument_id=intent.instrument_id,
                    side=intent.side,
                    order_type=intent.order_type,
                    requested_quantity=intent.quantity,
                    remaining_quantity=intent.quantity,
                    filled_quantity=Decimal("0"),
                    decision_ts_utc=intent.decision_ts_utc,
                    earliest_executable_utc=intent.decision_ts_utc,
                    status=OrderStatus.REJECTED,
                    rejection_reason="no_subsequent_market_data",
                )
            )

        total_realized = sum((p.realized_pnl for p in positions.values()), Decimal("0"))
        total_unrealized = sum((p.unrealized_pnl for p in positions.values()), Decimal("0"))
        total_costs = sum((p.total_costs for p in positions.values()), Decimal("0"))
        gross_pnl = total_realized + total_unrealized
        net_pnl = gross_pnl - total_costs
        final_equity = self.config.initial_cash + net_pnl

        metrics = SimulationMetrics(
            initial_cash=self.config.initial_cash,
            final_equity=final_equity,
            gross_pnl=gross_pnl,
            total_costs=total_costs,
            net_pnl=net_pnl,
            max_drawdown=max_dd,
            total_orders=len(orders_out),
            filled_orders=sum(1 for o in orders_out if o.status == OrderStatus.FILLED),
            partial_fills=partial_fill_count,
            rejected_orders=sum(1 for o in orders_out if o.status == OrderStatus.REJECTED),
            expired_orders=sum(1 for o in orders_out if o.status == OrderStatus.EXPIRED),
            cancelled_orders=sum(1 for o in orders_out if o.status == OrderStatus.CANCELLED),
            ambiguous_fills=ambiguous_count,
        )

        return SimulationResult(
            config_id=self.config.config_id,
            execution_mode=self.config.execution_mode,
            dataset_id=self.config.dataset_id,
            dataset_version=self.config.dataset_version,
            manifest_sha256=self.config.manifest_sha256,
            metrics=metrics,
            orders=orders_out,
            fills=fills_out,
            positions=positions,
            equity_curve=equity_curve,
            event_log=events_out,
            warnings=warnings,
        )

    @staticmethod
    def _apply_fill_to_position(
        pos: PositionState,
        fe: FillEvent,
        spec: EffectiveSpec,
        cash: Decimal,
        sl: Optional[Decimal],
        tp: Optional[Decimal],
    ) -> Decimal:
        signed_qty = fe.quantity if fe.side == OrderSide.BUY else -fe.quantity
        mult = spec.contract_multiplier
        pos.total_costs += fe.total_cost
        cash -= fe.fee_cost + fe.tax_cost

        if pos.quantity == 0:
            pos.quantity = signed_qty
            pos.avg_entry_price = fe.raw_price
            pos.active_stop_loss = sl
            pos.active_take_profit = tp
        elif (pos.quantity > 0 and signed_qty > 0) or (pos.quantity < 0 and signed_qty < 0):
            total_abs = abs(pos.quantity) + abs(signed_qty)
            pos.avg_entry_price = ((abs(pos.quantity) * pos.avg_entry_price) + (abs(signed_qty) * fe.raw_price)) / total_abs
            pos.quantity += signed_qty
        else:
            close_qty = min(abs(pos.quantity), abs(signed_qty))
            if pos.quantity > 0:
                pos.realized_pnl += (fe.raw_price - pos.avg_entry_price) * close_qty * mult
            else:
                pos.realized_pnl += (pos.avg_entry_price - fe.raw_price) * close_qty * mult
            pos.quantity += signed_qty
            if pos.quantity == 0:
                pos.avg_entry_price = Decimal("0")
                pos.active_stop_loss = None
                pos.active_take_profit = None
            elif (pos.quantity > 0 and signed_qty > 0) or (pos.quantity < 0 and signed_qty < 0):
                pos.avg_entry_price = fe.raw_price
                pos.active_stop_loss = sl
                pos.active_take_profit = tp
        return cash
