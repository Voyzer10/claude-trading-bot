"""Backtest configuration (a JSON file supplied by whoever runs the backtest).

Every execution value is EXPLICIT: nothing is defaulted, nothing is copied from V4, and nothing here is an owner
approval. A backtest configuration is a research ASSUMPTION; its values are recorded verbatim in the run metadata
with `approval: "RESEARCH ASSUMPTION (not owner-approved)"`. The paper runtime never reads backtest configuration.

{
  "book_id": "US",                      # which V6 book's market / currency the simulation mirrors
  "starting_equity": "1000",            # optional; default = that book's owner-approved budget
  "timeframe": "5m",                    # 1m 5m 15m 30m 1h
  "session": {"calendar": "NYSE"}       # V6 NYSE calendar (2026-2027), or
             | {"kind": "continuous_24_7", "timezone": "UTC", "trading_day_start": "00:00"},
  "tick_size": 0.01,
  "half_spread_ticks": 1,               # spread model: added to entry_ticks and stop_exit_ticks (see below)
  "gap_policy": "interrupt",            # or "fail"
  "execution": {                        # Module E (CK-26) values, all mandatory
     "entry_ticks", "stop_exit_ticks", "target_exit_ticks" (must be 0), "max_gap_ticks", "sl_buffer_ticks",
     "tp_offset_ticks", "contract_multiplier", "lot_size", "quantity_step", "min_quantity",
     "fee_schedule": {"rate", "per_unit", "per_order", "rounding_places", "rounding_mode", "source"},
     "price_rounding_mode", "initial_margin_rate", "mtm_exit_slippage_ticks" },
  "label": "free text"
}

Spread model: Module E fills a market entry at open +/- entry_ticks and a stop exit at SL -/+ stop_exit_ticks, both
adverse. Crossing half the bid/ask spread on each of those fills is modelled by adding `half_spread_ticks` to both.
A target exit fills exactly at TP (spec Section 6/8, `target_exit_ticks` = 0, a resting limit order), so no spread is
charged there. Module E itself is unchanged.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional

from scanner_v6.data.market_config import ConfigError, ConfigOrigin, MarketDataConfig, SessionCalendar, SessionKind
from scanner_v6.exit.execution_config import ExecutionConfig

from .. import fees_us, us_stocks
from ..books import BOOKS

TIMEFRAMES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
EXEC_KEYS = ("entry_ticks", "stop_exit_ticks", "target_exit_ticks", "max_gap_ticks", "sl_buffer_ticks",
             "tp_offset_ticks", "contract_multiplier", "lot_size", "quantity_step", "min_quantity", "fee_schedule",
             "price_rounding_mode", "initial_margin_rate", "mtm_exit_slippage_ticks")
OPTIONAL_EXEC_KEYS = ("eod_flatten_buffer", "entry_cutoff_buffer", "short_margin_rate", "short_quantity_step",
                      "short_min_quantity")        # ME-6 (whole minutes) / ME-7
TOP_KEYS = {"book_id", "starting_equity", "timeframe", "session", "tick_size", "half_spread_ticks", "gap_policy",
            "execution", "label", "shorts_enabled"}
APPROVAL = "RESEARCH ASSUMPTION (not owner-approved)"


class BacktestConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BacktestConfig:
    raw: Dict[str, Any]
    book_id: str
    starting_equity: Decimal
    timeframe: str
    tf: timedelta
    tick_size: float
    half_spread_ticks: int
    gap_policy: str
    session_spec: Dict[str, Any]
    execution: Dict[str, Any]
    label: str
    shorts_enabled: bool = True

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def session(self, start: date, end: date) -> SessionCalendar:
        s = self.session_spec
        if s.get("calendar") == "NYSE":
            cal = us_stocks.load_calendar()
            return us_stocks.session_calendar(cal, start, end)
        return SessionCalendar(SessionKind.CONTINUOUS, s["timezone"])

    def calendar_note(self) -> Optional[str]:
        if self.session_spec.get("calendar") == "NYSE" and not us_stocks.load_calendar().get("verified"):
            return "NYSE calendar NOT VERIFIED by the owner: sessions/holidays used as listed in v6_runtime/calendars"
        return None

    def market_config(self, symbol: str, session: SessionCalendar) -> MarketDataConfig:
        return MarketDataConfig(origin=ConfigOrigin.INSTRUMENT_CONFIG, instrument_id=symbol, timeframe=self.tf,
                                tick_size=self.tick_size, session=session)

    def execution_config(self, session: SessionCalendar) -> ExecutionConfig:
        d = dict(self.execution)
        d["entry_ticks"] = d["entry_ticks"] + self.half_spread_ticks
        d["stop_exit_ticks"] = d["stop_exit_ticks"] + self.half_spread_ticks
        d["starting_equity"] = str(self.starting_equity)
        d["shorts_enabled"] = self.shorts_enabled
        if session.kind is SessionKind.CONTINUOUS:
            d["trading_day_start"] = self.session_spec["trading_day_start"]
        fee = d.pop("fee_schedule")
        us_fee = isinstance(fee, dict) and "model" in fee
        if not us_fee:
            d["fee_schedule"] = fee
        try:
            ec = ExecutionConfig.from_fixture(d)
            if us_fee:
                ec = dataclasses.replace(ec, fee_schedule=fees_us.from_config(fee))
        except (ConfigError, TypeError, ValueError) as e:
            raise BacktestConfigError("execution: %s" % e) from e
        return dataclasses.replace(ec, origin=ConfigOrigin.INSTRUMENT_CONFIG)


def _int(v: Any, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise BacktestConfigError("%s must be a non-negative integer, got %r" % (name, v))
    return v


def parse(raw: Dict[str, Any]) -> BacktestConfig:
    if not isinstance(raw, dict):
        raise BacktestConfigError("the backtest configuration must be a JSON object")
    unknown = sorted(set(raw) - TOP_KEYS)
    if unknown:
        raise BacktestConfigError("unknown configuration keys: %s" % ", ".join(unknown))
    book = raw.get("book_id")
    if book not in BOOKS:
        raise BacktestConfigError("book_id must be one of %s, got %r" % (", ".join(BOOKS), book))
    if book == "USFNO":
        raise BacktestConfigError("US F&O is BLOCKED: no verified options data, contract mapping or fee model; "
                                  "an underlying-stock backtest is never converted into an options backtest")
    try:
        eq = Decimal(str(raw.get("starting_equity", BOOKS[book].starting_budget)))
    except Exception as e:  # noqa: BLE001
        raise BacktestConfigError("starting_equity is not a number: %r" % raw.get("starting_equity")) from e
    if not eq.is_finite() or eq <= 0:
        raise BacktestConfigError("starting_equity must be positive")
    tf = raw.get("timeframe")
    if tf not in TIMEFRAMES:
        raise BacktestConfigError("timeframe must be one of %s, got %r" % (", ".join(TIMEFRAMES), tf))
    tick = raw.get("tick_size")
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) or not tick > 0:
        raise BacktestConfigError("tick_size must be a positive number, got %r" % (tick,))
    sess = raw.get("session")
    if not isinstance(sess, dict):
        raise BacktestConfigError("session must be {\"calendar\": \"NYSE\"} or a continuous_24_7 mapping")
    if sess.get("calendar") == "NYSE":
        if set(sess) != {"calendar"}:
            raise BacktestConfigError("session {\"calendar\": \"NYSE\"} takes no other keys")
        if book != "US":
            raise BacktestConfigError("the NYSE calendar is for the US book only")
    elif sess.get("kind") == "continuous_24_7":
        if set(sess) != {"kind", "timezone", "trading_day_start"}:
            raise BacktestConfigError("a continuous_24_7 session needs exactly kind, timezone and trading_day_start")
        try:
            SessionCalendar(SessionKind.CONTINUOUS, sess["timezone"])
            time.fromisoformat(sess["trading_day_start"])
        except (ConfigError, TypeError, ValueError) as e:
            raise BacktestConfigError("session: %s" % e) from e
    else:
        raise BacktestConfigError("session must be {\"calendar\": \"NYSE\"} or {\"kind\": \"continuous_24_7\", ...}")
    ex = raw.get("execution")
    if not isinstance(ex, dict):
        raise BacktestConfigError("execution must be a mapping of the Module E values")
    missing = [k for k in EXEC_KEYS if ex.get(k) is None]
    if missing:
        raise BacktestConfigError("execution values missing (nothing is defaulted): %s" % ", ".join(missing))
    extra = sorted(set(ex) - set(EXEC_KEYS) - set(OPTIONAL_EXEC_KEYS))
    if extra:
        raise BacktestConfigError("unknown execution keys: %s" % ", ".join(extra))
    if ex["target_exit_ticks"] != 0:
        raise BacktestConfigError("target_exit_ticks must be 0 (spec Section 6/8)")
    for k in ("entry_ticks", "stop_exit_ticks"):
        _int(ex[k], "execution.%s" % k)
    if book == "US":
        fs = ex["fee_schedule"]
        if not (isinstance(fs, dict) and fs.get("model") == fees_us.MODEL):
            raise BacktestConfigError("US backtests use the sell-side SEC/TAF fee model: fee_schedule.model must be %r"
                                      % fees_us.MODEL)
        if sess.get("calendar") == "NYSE" and (ex.get("eod_flatten_buffer") is None or ex.get("entry_cutoff_buffer") is None):
            raise BacktestConfigError("US intraday backtests flatten before the close: execution.eod_flatten_buffer and "
                                      "execution.entry_cutoff_buffer (minutes) are required")
    se = raw.get("shorts_enabled")
    if not isinstance(se, bool):
        raise BacktestConfigError("shorts_enabled must be true or false (explicit)")
    gp = raw.get("gap_policy", "interrupt")
    if gp not in ("interrupt", "fail"):
        raise BacktestConfigError("gap_policy must be 'interrupt' or 'fail'")
    cfg = BacktestConfig(raw=raw, book_id=book, starting_equity=eq, timeframe=tf,
                         tf=timedelta(minutes=TIMEFRAMES[tf]), tick_size=float(tick),
                         half_spread_ticks=_int(raw.get("half_spread_ticks"), "half_spread_ticks"),
                         gap_policy=gp, session_spec=dict(sess), execution=dict(ex), label=str(raw.get("label", "")),
                         shorts_enabled=se)
    # build once so a malformed Module E value fails now, with its own message
    probe = SessionCalendar(SessionKind.CONTINUOUS, "UTC") if sess.get("calendar") != "NYSE" else None
    if probe is not None:
        cfg.execution_config(probe)
    else:
        cfg.execution_config(cfg.session(date(2026, 1, 5), date(2026, 1, 5)))
    return cfg


def load(path: str) -> BacktestConfig:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        raise BacktestConfigError("configuration file %s does not exist" % path) from None
    except json.JSONDecodeError as e:
        raise BacktestConfigError("configuration file %s is not valid JSON: %s" % (path, e)) from None
    return parse(raw)


def describe(cfg: BacktestConfig) -> Dict[str, Any]:
    return {"approval": APPROVAL, "book_id": cfg.book_id, "starting_equity": str(cfg.starting_equity),
            "timeframe": cfg.timeframe, "tick_size": cfg.tick_size, "half_spread_ticks": cfg.half_spread_ticks,
            "gap_policy": cfg.gap_policy, "session": cfg.session_spec, "execution": cfg.execution, "label": cfg.label,
            "shorts_enabled": cfg.shorts_enabled,
            "config_sha256": cfg.digest(), "calendar_note": cfg.calendar_note()}

