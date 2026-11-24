"""US Stocks book configuration: instruments, NYSE calendar, Module E execution values and their approval status.

Nothing is defaulted. The owner's configuration lives in <V6 data root>/config/us_stocks.json (template:
v6_runtime/config/us_stocks.template.json). Each value carries an approval; only APPROVED values reach Module E, every
other value stays None, so Module E answers EXECUTION_CONFIG_INCOMPLETE and no trade is possible (fail closed).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from scanner_v6.data.market_config import (ConfigOrigin, MarketDataConfig, SessionCalendar, SessionKind,
                                           require_instrument_config, validate_timeframe)
from scanner_v6.exit.execution_config import ExecutionConfig, LinearFeeSchedule

from .books import spec as book_spec
from .paths import DataRoot
from .portfolio import InstrumentSpec

APPROVED = "APPROVED"
HERE = os.path.dirname(os.path.abspath(__file__))
CALENDAR_FILE = os.path.join(HERE, "calendars", "nyse.json")
TEMPLATE_FILE = os.path.join(HERE, "config", "us_stocks.template.json")

EXECUTION_KEYS = ("entry_ticks", "stop_exit_ticks", "target_exit_ticks", "max_gap_ticks", "sl_buffer_ticks",
                  "tp_offset_ticks", "contract_multiplier", "lot_size", "quantity_step", "min_quantity",
                  "fee_schedule", "price_rounding_mode", "initial_margin_rate", "mtm_exit_slippage_ticks")
FEED_KEYS = ("bar_settle_seconds", "stale_after_bars", "alignment_rule")


# Owner 2026-11-24 (initial allowlist): the only symbols whose IEX real-time regular-session 5-minute coverage was
# checked on the VPS (18-24 Nov 2026: 0 missing bars). A symbol is added only after the same check.
SYMBOL_ALLOWLIST = ("SPY", "QQQ", "AAPL", "MSFT")


class USConfigError(ValueError):
    pass


# ------------------------------------------------------------------ calendar
def load_calendar(path: str = CALENDAR_FILE) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        cal = json.load(fh)
    for k in ("timezone", "regular_open", "regular_close", "early_close", "holidays", "early_closes", "verified",
              "covered_years"):
        if k not in cal:
            raise USConfigError("calendar %s misses %s" % (path, k))
    return cal


def trading_sessions(cal: Dict[str, Any], start: date, end: date) -> Tuple[Tuple[datetime, datetime], ...]:
    """(open, close) per trading day in [start, end], from the calendar file only. Weekends and listed holidays are
    closed; listed early closes end at `early_close`. A date outside `covered_years` is an error (never guessed)."""
    tz = ZoneInfo(cal["timezone"])
    years = set(cal["covered_years"])
    hol, early = set(cal["holidays"]), set(cal["early_closes"])
    o_t, c_t, e_t = (time.fromisoformat(cal[k]) for k in ("regular_open", "regular_close", "early_close"))
    out, d = [], start
    while d <= end:
        if d.year not in years:
            raise USConfigError("the NYSE calendar file does not cover %d" % d.year)
        if d.weekday() < 5 and d.isoformat() not in hol:
            close_t = e_t if d.isoformat() in early else c_t
            out.append((datetime.combine(d, o_t, tz), datetime.combine(d, close_t, tz)))
        d += timedelta(days=1)
    return tuple(out)


def session_calendar(cal: Dict[str, Any], start: date, end: date) -> SessionCalendar:
    return SessionCalendar(SessionKind.EXCHANGE, cal["timezone"], trading_sessions(cal, start, end))


# ------------------------------------------------------------------ owner configuration
@dataclass(frozen=True)
class USStocksConfig:
    raw: Dict[str, Any]
    instruments: Tuple[str, ...]
    timeframe: str
    approved: Dict[str, Any]          # key -> value, APPROVED only
    not_approved: Tuple[str, ...]     # keys whose value is missing or not approved
    feed: Optional[str]
    feed_approved: bool


def load_config(root: DataRoot) -> Optional[USStocksConfig]:
    """None when the owner has not placed a configuration in the V6 data root yet."""
    raw = root.read_json("config", "us_stocks.json")
    if raw is None:
        return None
    return parse_config(raw)


def parse_config(raw: Dict[str, Any]) -> USStocksConfig:
    if raw.get("book_id") != "US":
        raise USConfigError("us_stocks.json must be for book US")
    vals = raw.get("values")
    if not isinstance(vals, dict):
        raise USConfigError("us_stocks.json: values must be a mapping")
    approved, missing = {}, []
    for k in ("tick_size",) + EXECUTION_KEYS + FEED_KEYS:
        item = vals.get(k)
        if not isinstance(item, dict):
            raise USConfigError("us_stocks.json: values.%s must be {value, approval, decision}" % k)
        if item.get("approval") == APPROVED and item.get("value") is not None:
            approved[k] = item["value"]
        else:
            missing.append(k)
    unknown = sorted(set(vals) - set(("tick_size",) + EXECUTION_KEYS + FEED_KEYS + ("exchange_day_rule",)))
    if unknown:
        raise USConfigError("us_stocks.json: unknown values %s" % unknown)
    edr = vals.get("exchange_day_rule") or {}
    if not (edr.get("approval") == APPROVED and edr.get("value") is not None):
        missing.append("exchange_day_rule")
    insts = raw.get("instruments")
    if not isinstance(insts, list) or not all(isinstance(s, str) and s and s.isupper() for s in insts):
        raise USConfigError("us_stocks.json: instruments must be a list of upper-case symbols")
    outside = sorted(set(insts) - set(SYMBOL_ALLOWLIST))
    if outside:
        raise USConfigError("us_stocks.json: %s not in the US Stocks allowlist %s (owner 2026-11-24: only symbols whose "
                            "IEX regular-session coverage was checked)" % (", ".join(outside), ", ".join(SYMBOL_ALLOWLIST)))
    if len(set(insts)) != len(insts):
        raise USConfigError("us_stocks.json: duplicate instruments")
    tf = raw.get("timeframe")
    validate_timeframe(_tf_delta(tf))
    dp = raw.get("data_provider") or {}
    if dp.get("name") != "alpaca":
        raise USConfigError("the US Stocks data provider is Alpaca (owner decision)")
    return USStocksConfig(raw, tuple(insts), tf, approved, tuple(missing), dp.get("feed"),
                          dp.get("approval") == APPROVED and dp.get("feed") in ("iex", "sip"))


def _tf_delta(tf: Any) -> timedelta:
    table = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
    if tf not in table:
        raise USConfigError("timeframe %r is not supported for US Stocks (%s)" % (tf, ", ".join(table)))
    return timedelta(minutes=table[tf])


def instrument_specs(cfg: USStocksConfig, cal: Dict[str, Any], start: date, end: date) -> List[InstrumentSpec]:
    """Module A / E configuration per instrument. Only APPROVED values are passed; the rest stay None."""
    a = cfg.approved
    fee = a.get("fee_schedule")
    fee_schedule = LinearFeeSchedule(**fee) if isinstance(fee, dict) else None
    session = session_calendar(cal, start, end)
    out = []
    for sym in cfg.instruments:
        market = require_instrument_config(MarketDataConfig(
            origin=ConfigOrigin.INSTRUMENT_CONFIG, instrument_id=sym, timeframe=_tf_delta(cfg.timeframe),
            tick_size=a.get("tick_size"), session=session))
        exe = ExecutionConfig(
            origin=ConfigOrigin.INSTRUMENT_CONFIG, starting_equity=book_spec("US").starting_budget,
            fee_schedule=fee_schedule, **{k: a.get(k) for k in EXECUTION_KEYS if k != "fee_schedule"})
        out.append(InstrumentSpec(sym, "US", cfg.timeframe, market, exe, data_source=feed_label(cfg.feed)))
    return out


# Owner decision 2026-11-24 (provisional): US Stocks intraday uses Alpaca IEX REAL-TIME 5-minute bars. Delayed SIP is
# never a fallback; real-time SIP is an optional future upgrade. IEX is ONE venue: never described as consolidated.
SELECTED_FEED = "iex"
FEED_LABELS = {"iex": "alpaca iex real-time (single venue IEX, not consolidated tape)",
               "sip": "alpaca sip (consolidated tape)"}


def feed_label(feed: Optional[str]) -> Optional[str]:
    return FEED_LABELS.get(feed) if feed else None


def readiness(cfg: Optional[USStocksConfig], cal: Dict[str, Any], credentials_present: bool) -> Dict[str, Any]:
    """Why the US Stocks book cannot trade yet. Empty `blockers` = configuration complete (activation still needs the
    owner)."""
    blockers: List[str] = []
    if cfg is None:
        blockers.append("no us_stocks.json in the V6 data root (owner configuration missing)")
    else:
        if not cfg.instruments:
            blockers.append("no US instruments configured")
        for k in cfg.not_approved:
            blockers.append("%s: NOT APPROVED" % k)
        if not cfg.feed_approved:
            blockers.append("Alpaca feed: NOT APPROVED (owner selected IEX real-time provisionally on 2026-11-24)")
        elif cfg.feed != SELECTED_FEED:
            blockers.append("Alpaca feed %r is not the selected feed: owner 2026-11-24 selected IEX real-time; delayed "
                            "SIP is never used and real-time SIP is a future upgrade (needs a paid subscription)" % cfg.feed)
    if not cal.get("verified"):
        blockers.append("NYSE holiday calendar: NOT VERIFIED")
    if not credentials_present:
        blockers.append("V6 Alpaca DATA-ONLY credential: not supplied")
    return {"book_id": "US", "ready": not blockers, "blockers": blockers}
