"""Effective-dated instrument specification resolver and tick/step rounding helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Optional

from ..instruments import Instrument, InstrumentRegistry
from .models import OrderSide


@dataclass(frozen=True)
class EffectiveSpec:
    instrument_id: str
    spec_version_id: Optional[int]
    tick_size: Optional[Decimal]
    lot_size: Optional[Decimal]
    contract_multiplier: Decimal
    quantity_step: Decimal
    minimum_order_quantity: Decimal
    expiry_date: Optional[date]
    last_trade_date: Optional[date]
    is_inverse: bool


class EffectiveSpecResolver:
    """Resolves contract specifications as-of a given simulation timestamp from InstrumentRegistry."""

    def __init__(self, registry: InstrumentRegistry) -> None:
        self.registry = registry

    def resolve(self, instrument_id: str, as_of_utc: datetime) -> Optional[EffectiveSpec]:
        inst = self.registry.get(instrument_id)
        if inst is None:
            return None

        history = self.registry.get_spec_history(instrument_id)
        chosen_ver_id: Optional[int] = None
        spec_dict = None
        for ver in history:
            ef = ver.effective_from
            et = ver.effective_to
            if (ef is None or ef <= as_of_utc) and (et is None or as_of_utc < et):
                chosen_ver_id = ver.version_id
                spec_dict = ver.specification

        def _dec_or(key: str, default: Optional[Decimal]) -> Optional[Decimal]:
            if spec_dict and spec_dict.get(key) is not None:
                return Decimal(str(spec_dict[key]))
            return default

        tick = _dec_or("tick_size", inst.tick_size)
        lot = _dec_or("lot_size", inst.lot_size)
        mult = _dec_or("contract_multiplier", inst.contract_multiplier) or Decimal("1")
        q_step = _dec_or("quantity_step", inst.quantity_step) or lot or Decimal("1")
        min_q = _dec_or("minimum_order_quantity", inst.minimum_order_quantity) or q_step
        exp_raw = spec_dict.get("expiry_date") if spec_dict else None
        exp = date.fromisoformat(exp_raw) if isinstance(exp_raw, str) else inst.expiry_date
        ltd_raw = spec_dict.get("last_trade_date") if spec_dict else None
        ltd = date.fromisoformat(ltd_raw) if isinstance(ltd_raw, str) else inst.last_trade_date

        return EffectiveSpec(
            instrument_id=instrument_id,
            spec_version_id=chosen_ver_id,
            tick_size=tick,
            lot_size=lot,
            contract_multiplier=mult,
            quantity_step=q_step,
            minimum_order_quantity=min_q,
            expiry_date=exp,
            last_trade_date=ltd,
            is_inverse=inst.is_inverse,
        )


def round_price_to_tick(price: Decimal, tick_size: Optional[Decimal], side: OrderSide, *, adverse: bool = True) -> Decimal:
    if tick_size is None or tick_size <= 0:
        return price
    ratio = price / tick_size
    if adverse:
        # Conservative: BUY rounds up (pays more), SELL rounds down (receives less)
        rounding = ROUND_CEILING if side == OrderSide.BUY else ROUND_FLOOR
    else:
        rounding = ROUND_FLOOR if side == OrderSide.BUY else ROUND_CEILING
    return (ratio.to_integral_value(rounding=rounding)) * tick_size


def round_qty_to_step(qty: Decimal, step: Decimal, min_qty: Decimal) -> Decimal:
    if qty < min_qty or step <= 0:
        return Decimal("0")
    steps = (qty / step).to_integral_value(rounding=ROUND_FLOOR)
    rounded = steps * step
    return rounded if rounded >= min_qty else Decimal("0")
