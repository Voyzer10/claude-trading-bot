"""Module E configuration: the CK-26 execution / account values, all explicit, none defaulted (PAPER ONLY).

Spec references (research/v6/specs/V6_TRADING_SPEC_v0.2.md):
  CK-26, CK-22  every execution value comes from explicit instrument / account configuration; a missing value is
                `EXECUTION_CONFIG_INCOMPLETE` (CK-13 #1); zero slippage is never assumed; no fee rate, rounding rule
                or broker specification is invented.
  Section 6/8   `target_exit_ticks` must be explicitly configured as 0.
  OQ-1          `max_gap_ticks` and tick size are mandatory.
  CK-20         SL buffer in ticks per instrument; CK-21 TP offset (one tick, configurable) in ticks.
  OQ-6, OQ-7    starting equity, session calendar and time zone are mandatory.
  ME-2          (owner decision 24 Nov 2026, spec 17.V) a CONTINUOUS (24/7) calendar needs an explicit
                `trading_day_start` (local time in the instrument time zone) for the daily-loss day boundary.
  ME-3          (owner decision 24 Nov 2026) required margin = entry_fill x qty x multiplier x `initial_margin_rate`.
  OQ-13         (OWNER APPROVED 24 Nov 2026) the estimated exit fill of an open position at the mark uses a configured
                adverse slippage, `mtm_exit_slippage_ticks`; when it is missing, MTM equity is UNSCORABLE (never 0).
                It is not a CK-13 entry requirement, so it is not part of `missing()`.
  IR-3, OQ-15   a synthetic fixture may declare a complete TEST-ONLY configuration (`ConfigOrigin.TEST_FIXTURE`); it is
                never production configuration and never a fallback.

Configuration SHAPE (implementation choice, documented in 17.V; the VALUES and their sources stay OPEN, B-7...B-13):
  * fee schedule: `LinearFeeSchedule` = rate x notional + per_unit x qty + per_order, per fill, rounded once per fill
    to `rounding_places` with `rounding_mode`. Every component must be given explicitly (0 is a value, not a default).
  * quantity grid: a quantity is permitted when it is a whole multiple of `quantity_step` and >= `min_quantity`;
    `quantity_step` must be a whole multiple of `lot_size`, and `min_quantity` a whole multiple of `quantity_step`.
  * `price_rounding_mode` rounds a computed price that is off the tick grid onto it (B-13 rule is OPEN; OQ-15 lets the
    configuration declare it). Prices built from on-grid data never change.

Owner decisions 24 Nov 2026 (PR #98, US Stocks intraday), all OPTIONAL fields: when absent the behaviour is unchanged.
  ME-5  fee schedules may be side-aware: `FeeSchedule.fee(price, qty, multiplier, fill_side=, at=)` gets the side of
        the FILL (BUY / SELL) and the fill time, so a sell-side-only regulatory fee (SEC Section 31, FINRA TAF) is never
        charged on a buy. `LinearFeeSchedule` ignores both (symmetric, as before).
  ME-6  intraday end-of-day flattening on EXCHANGE calendars: `eod_flatten_buffer` (time before the actual session
        close, early closes included, at which an open position is closed) and `entry_cutoff_buffer` (no entry whose
        entry candle opens at or after close - cutoff). Both or neither; cutoff >= flatten buffer.
  ME-7  side-specific short parameters: `short_margin_rate`, `short_quantity_step`, `short_min_quantity` (None = the
        long values); `shorts_enabled=False` makes every SELL setup NO_TRADE (SHORT_SIDE_DISABLED) before it can take
        the stream's single position.
  ME-6 timeframe rules (missing() -> EXECUTION_CONFIG_INCOMPLETE): eod_flatten_buffer >= timeframe, so the flatten
        candle always ends before the session close; entry_cutoff_buffer >= eod_flatten_buffer + timeframe, so an
        entry candle is never the flatten candle.

Nothing here holds a real value. Research only: no orders, no broker, no live routing.
"""
from __future__ import annotations

import decimal
from dataclasses import dataclass, fields
from datetime import time, timedelta
from decimal import Decimal
from typing import Any, Mapping, Optional, Tuple

from ..data.market_config import ConfigError, ConfigOrigin, MarketDataConfig, SessionKind

ROUNDING_MODES = ("ROUND_HALF_UP", "ROUND_HALF_EVEN", "ROUND_HALF_DOWN", "ROUND_UP", "ROUND_DOWN", "ROUND_CEILING",
                  "ROUND_FLOOR")


def dec(v: Any, name: str = "value") -> Decimal:
    """Exact Decimal from an int, Decimal, str or float (a float through its shortest repr, so 116.43 -> '116.43')."""
    if isinstance(v, bool):
        raise ConfigError("%s must be a number, got %r" % (name, v))
    if isinstance(v, Decimal):
        d = v
    elif isinstance(v, int):
        d = Decimal(v)
    elif isinstance(v, float):
        d = Decimal(repr(v))
    elif isinstance(v, str):
        try:
            d = Decimal(v)
        except decimal.InvalidOperation as e:
            raise ConfigError("%s: %r is not a number" % (name, v)) from e
    else:
        raise ConfigError("%s must be a number, got %r" % (name, v))
    if not d.is_finite():
        raise ConfigError("%s must be finite, got %r" % (name, v))
    return d


def _nonneg_int(v: Any, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ConfigError("%s must be a non-negative int (ticks), got %r" % (name, v))
    return v


def _positive(v: Any, name: str) -> Decimal:
    d = dec(v, name)
    if d <= 0:
        raise ConfigError("%s must be positive, got %r" % (name, v))
    return d


def _nonneg(v: Any, name: str) -> Decimal:
    d = dec(v, name)
    if d < 0:
        raise ConfigError("%s must be non-negative, got %r" % (name, v))
    return d


def _mode(v: Any, name: str) -> str:
    if v not in ROUNDING_MODES:
        raise ConfigError("%s must be one of %s, got %r" % (name, ", ".join(ROUNDING_MODES), v))
    return v


def is_multiple(x: Decimal, step: Decimal) -> bool:
    return (x / step) == (x / step).to_integral_value()


class FeeSchedule:
    """ME-5 interface. `fee` returns the total fee of ONE fill (Decimal, already rounded). `fill_side` is the side of
    the fill itself (a long exit is a SELL fill, a short entry is a SELL fill); `at` is the fill time (UTC)."""
    source: str
    side_aware: bool = False

    def fee(self, price: Decimal, qty: Decimal, multiplier: Decimal, *, fill_side: Optional[str] = None,
            at: Any = None) -> Decimal:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(frozen=True)
class LinearFeeSchedule(FeeSchedule):
    """Fee of ONE fill: rate x price x qty x multiplier + per_unit x qty + per_order, rounded once to `rounding_places`
    decimal places with `rounding_mode`. Every field is mandatory; `source` is the declared fee source metadata."""
    rate: Any
    per_unit: Any
    per_order: Any
    rounding_places: int
    rounding_mode: str
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate", _nonneg(self.rate, "fee rate"))
        object.__setattr__(self, "per_unit", _nonneg(self.per_unit, "fee per_unit"))
        object.__setattr__(self, "per_order", _nonneg(self.per_order, "fee per_order"))
        if isinstance(self.rounding_places, bool) or not isinstance(self.rounding_places, int) or self.rounding_places < 0:
            raise ConfigError("fee rounding_places must be a non-negative int")
        _mode(self.rounding_mode, "fee rounding_mode")
        if not isinstance(self.source, str) or not self.source:
            raise ConfigError("fee source must be a non-empty string")

    def fee(self, price: Decimal, qty: Decimal, multiplier: Decimal, *, fill_side: Optional[str] = None,
            at: Any = None) -> Decimal:
        """Symmetric: `fill_side` and `at` are accepted and ignored (ME-5)."""
        if qty <= 0:
            raise ValueError("a fee is computed for a positive quantity only")
        raw = self.rate * price * qty * multiplier + self.per_unit * qty + self.per_order
        return raw.quantize(Decimal(1).scaleb(-self.rounding_places), rounding=getattr(decimal, self.rounding_mode))


_FIELDS_REQUIRED = ("starting_equity", "entry_ticks", "stop_exit_ticks", "target_exit_ticks", "max_gap_ticks",
                    "sl_buffer_ticks", "tp_offset_ticks", "contract_multiplier", "lot_size", "quantity_step",
                    "min_quantity", "fee_schedule", "price_rounding_mode", "initial_margin_rate")


@dataclass(frozen=True)
class ExecutionConfig:
    """Module E configuration. `origin` is mandatory; every other field is None when it was not supplied (missing stays
    missing, CK-26). A malformed value raises ConfigError; a missing one is reported by `missing()`."""
    origin: ConfigOrigin
    starting_equity: Any = None
    entry_ticks: Optional[int] = None
    stop_exit_ticks: Optional[int] = None
    target_exit_ticks: Optional[int] = None
    max_gap_ticks: Optional[int] = None
    sl_buffer_ticks: Optional[int] = None
    tp_offset_ticks: Optional[int] = None
    contract_multiplier: Any = None
    lot_size: Any = None
    quantity_step: Any = None
    min_quantity: Any = None
    fee_schedule: Optional[LinearFeeSchedule] = None
    price_rounding_mode: Optional[str] = None
    initial_margin_rate: Any = None
    trading_day_start: Optional[time] = None        # ME-2: CONTINUOUS calendars only
    mtm_exit_slippage_ticks: Optional[int] = None   # OQ-13: adverse slippage of the estimated exit at the mark
    eod_flatten_buffer: Optional[timedelta] = None  # ME-6: flatten this long before the actual session close
    entry_cutoff_buffer: Optional[timedelta] = None  # ME-6: no entry candle opening at/after close - this
    short_margin_rate: Any = None                   # ME-7: SELL-side margin rate (None = initial_margin_rate)
    short_quantity_step: Any = None                 # ME-7: SELL-side quantity grid (None = quantity_step)
    short_min_quantity: Any = None                  # ME-7: SELL-side minimum (None = min_quantity)
    shorts_enabled: Optional[bool] = None           # ME-7: False = SELL setups are never entered (None = allowed)

    def __post_init__(self) -> None:
        if not isinstance(self.origin, ConfigOrigin):
            raise ConfigError("origin must be a ConfigOrigin")
        for n in ("entry_ticks", "stop_exit_ticks", "target_exit_ticks", "max_gap_ticks", "sl_buffer_ticks",
                  "tp_offset_ticks", "mtm_exit_slippage_ticks"):
            if getattr(self, n) is not None:
                _nonneg_int(getattr(self, n), n)
        for n in ("starting_equity", "contract_multiplier", "lot_size", "quantity_step", "min_quantity",
                  "initial_margin_rate"):
            if getattr(self, n) is not None:
                object.__setattr__(self, n, _positive(getattr(self, n), n))
        if self.fee_schedule is not None and not isinstance(self.fee_schedule, FeeSchedule):
            raise ConfigError("fee_schedule must be a FeeSchedule (e.g. LinearFeeSchedule) or None")
        for n in ("short_margin_rate", "short_quantity_step", "short_min_quantity"):
            if getattr(self, n) is not None:
                object.__setattr__(self, n, _positive(getattr(self, n), n))
        for n in ("eod_flatten_buffer", "entry_cutoff_buffer"):
            v = getattr(self, n)
            if v is not None and (not isinstance(v, timedelta) or v <= timedelta(0)):
                raise ConfigError("%s must be a positive timedelta, got %r" % (n, v))
        if (self.eod_flatten_buffer is None) != (self.entry_cutoff_buffer is None):
            raise ConfigError("eod_flatten_buffer and entry_cutoff_buffer are configured together (ME-6)")
        if self.eod_flatten_buffer is not None and self.entry_cutoff_buffer < self.eod_flatten_buffer:
            raise ConfigError("entry_cutoff_buffer must be >= eod_flatten_buffer (no entry after the flatten time)")
        if self.price_rounding_mode is not None:
            _mode(self.price_rounding_mode, "price_rounding_mode")
        if self.shorts_enabled is not None and not isinstance(self.shorts_enabled, bool):
            raise ConfigError("shorts_enabled must be True, False or None")
        if self.trading_day_start is not None and (not isinstance(self.trading_day_start, time)
                                                   or self.trading_day_start.tzinfo is not None):
            raise ConfigError("trading_day_start must be a naive datetime.time (local time of the instrument zone)")
        if self.lot_size is not None and self.quantity_step is not None and not is_multiple(self.quantity_step, self.lot_size):
            raise ConfigError("quantity_step must be a whole multiple of lot_size")
        if self.quantity_step is not None and self.min_quantity is not None and not is_multiple(self.min_quantity, self.quantity_step):
            raise ConfigError("min_quantity must be a whole multiple of quantity_step")
        if self.lot_size is not None and self.short_quantity_step is not None and not is_multiple(self.short_quantity_step, self.lot_size):
            raise ConfigError("short_quantity_step must be a whole multiple of lot_size")
        ss = self.short_quantity_step if self.short_quantity_step is not None else self.quantity_step
        if ss is not None and self.short_min_quantity is not None and not is_multiple(self.short_min_quantity, ss):
            raise ConfigError("short_min_quantity must be a whole multiple of the short quantity step")

    def missing(self, market: MarketDataConfig) -> Tuple[str, ...]:
        """Every mandatory value that is missing (or, for target_exit_ticks, not the approved explicit 0), in a fixed
        order. Empty tuple = complete. Never fills anything in."""
        out = [n for n in _FIELDS_REQUIRED if getattr(self, n) is None]
        if self.target_exit_ticks is not None and self.target_exit_ticks != 0:
            out.append("target_exit_ticks!=0")
        if market.tick_size is None:
            out.append("tick_size")
        if market.timeframe is None:
            out.append("timeframe")
        if market.session is None:
            out.append("session_calendar")
        elif market.session.kind is SessionKind.CONTINUOUS and self.trading_day_start is None:
            out.append("trading_day_start")
        if market.session is not None and market.session.kind is SessionKind.CONTINUOUS and self.eod_flatten_buffer:
            out.append("eod_flatten_needs_exchange_calendar")
        if self.eod_flatten_buffer is not None and market.timeframe is not None:
            if self.eod_flatten_buffer < market.timeframe:
                out.append("eod_flatten_buffer<timeframe")
            if self.entry_cutoff_buffer < self.eod_flatten_buffer + market.timeframe:
                out.append("entry_cutoff_buffer<eod_flatten_buffer+timeframe")
        return tuple(out)

    @classmethod
    def from_fixture(cls, d: Mapping[str, Any]) -> "ExecutionConfig":
        """TEST-ONLY configuration from a synthetic fixture (IR-3 / OQ-15). Every key optional; an omitted key stays
        None; an unknown key is an error. `fee_schedule` is a mapping of LinearFeeSchedule fields;
        `trading_day_start` is "HH:MM"."""
        if not isinstance(d, Mapping):
            raise ConfigError("fixture configuration must be a mapping")
        names = {f.name for f in fields(cls)} - {"origin"}
        unknown = sorted(set(d) - names)
        if unknown:
            raise ConfigError("unknown Module E fixture configuration keys: %s" % ", ".join(unknown))
        kw = dict(d)
        if kw.get("fee_schedule") is not None:
            fs = kw["fee_schedule"]
            if not isinstance(fs, Mapping):
                raise ConfigError("fee_schedule must be a mapping")
            try:
                kw["fee_schedule"] = LinearFeeSchedule(**fs)
            except TypeError as e:
                raise ConfigError("fee_schedule: %s" % e) from e
        for n in ("eod_flatten_buffer", "entry_cutoff_buffer"):     # fixtures give whole minutes
            v = kw.get(n)
            if v is not None and not isinstance(v, timedelta):
                if isinstance(v, bool) or not isinstance(v, int):
                    raise ConfigError("%s must be whole minutes, got %r" % (n, v))
                kw[n] = timedelta(minutes=v)
        if kw.get("trading_day_start") is not None:
            v = kw["trading_day_start"]
            try:
                kw["trading_day_start"] = time.fromisoformat(v)
            except (TypeError, ValueError) as e:
                raise ConfigError("trading_day_start must be 'HH:MM', got %r" % (v,)) from e
        return cls(ConfigOrigin.TEST_FIXTURE, **kw)
