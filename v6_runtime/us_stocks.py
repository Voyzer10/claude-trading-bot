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
from scanner_v6.exit.execution_config import ExecutionConfig

from . import fees_us
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
EOD_KEYS = ("eod_flatten_buffer_minutes", "entry_cutoff_minutes")          # ME-6 (owner: EOD flat is mandatory)
FEED_KEYS = ("bar_settle_seconds", "stale_after_bars", "alignment_rule")
# Short side (owner 2026-11-24: long AND short paper trades). Every short assumption must be APPROVED, otherwise SELL
# entries are refused at the book (BOOK_SHORT_NOT_READY) while the long side may still trade.
SHORT_KEYS = ("short_margin_rate", "short_quantity_step", "short_min_quantity", "short_borrow_assumption")
REQUIRED_KEYS = ("tick_size",) + EXECUTION_KEYS + EOD_KEYS + FEED_KEYS


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


def calendar_range(cal: Dict[str, Any]) -> Tuple[date, date]:
    """The full supported range of the calendar file (1 Jan of the first covered year .. 31 Dec of the last)."""
    years = sorted(cal["covered_years"])
    if years != list(range(years[0], years[-1] + 1)):
        raise USConfigError("covered_years must be contiguous, got %s" % years)
    return date(years[0], 1, 1), date(years[-1], 12, 31)


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
    short_approved: Dict[str, Any] = None          # type: ignore[assignment]
    short_not_approved: Tuple[str, ...] = ()


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
    approved, missing, s_ok, s_missing = {}, [], {}, []
    for k in REQUIRED_KEYS + SHORT_KEYS:
        item = vals.get(k)
        if not isinstance(item, dict):
            raise USConfigError("us_stocks.json: values.%s must be {value, approval, decision}" % k)
        ok = item.get("approval") == APPROVED and item.get("value") is not None
        if k in SHORT_KEYS:
            (s_ok.__setitem__(k, item["value"]) if ok else s_missing.append(k))
        elif ok:
            approved[k] = item["value"]
        else:
            missing.append(k)
    if "fee_schedule" in approved:
        try:
            fees_us.from_config(approved["fee_schedule"])
        except ValueError as e:
            raise USConfigError("us_stocks.json: values.fee_schedule: %s" % e) from None
    for k in EOD_KEYS:
        v = approved.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v <= 0):
            raise USConfigError("us_stocks.json: values.%s must be a positive whole number of minutes" % k)
    unknown = sorted(set(vals) - set(REQUIRED_KEYS + SHORT_KEYS + ("exchange_day_rule",)))
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
                          dp.get("approval") == APPROVED and dp.get("feed") in ("iex", "sip"), s_ok, tuple(s_missing))


def _tf_delta(tf: Any) -> timedelta:
    table = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
    if tf not in table:
        raise USConfigError("timeframe %r is not supported for US Stocks (%s)" % (tf, ", ".join(table)))
    return timedelta(minutes=table[tf])


def instrument_specs(cfg: USStocksConfig, cal: Dict[str, Any], start: Optional[date] = None,
                     end: Optional[date] = None) -> List[InstrumentSpec]:
    """Module A / E configuration per instrument. Only APPROVED values are passed; the rest stay None. The session
    calendar spans the calendar file's full supported range unless a narrower range is given (tests)."""
    a = cfg.approved
    fee = a.get("fee_schedule")
    fee_schedule = fees_us.from_config(fee) if isinstance(fee, dict) else None
    lo, hi = calendar_range(cal)
    session = session_calendar(cal, start or lo, end or hi)
    eod = {"eod_flatten_buffer": timedelta(minutes=a["eod_flatten_buffer_minutes"]) if "eod_flatten_buffer_minutes" in a else None,
           "entry_cutoff_buffer": timedelta(minutes=a["entry_cutoff_minutes"]) if "entry_cutoff_minutes" in a else None}
    if (eod["eod_flatten_buffer"] is None) != (eod["entry_cutoff_buffer"] is None):
        eod = {"eod_flatten_buffer": None, "entry_cutoff_buffer": None}       # both or neither (readiness blocks)
    short = cfg.short_approved or {}
    shorts_ready = not cfg.short_not_approved
    short_kw = {k: short.get(k) for k in ("short_margin_rate", "short_quantity_step", "short_min_quantity")} \
        if shorts_ready else {}
    out = []
    for sym in cfg.instruments:
        market = require_instrument_config(MarketDataConfig(
            origin=ConfigOrigin.INSTRUMENT_CONFIG, instrument_id=sym, timeframe=_tf_delta(cfg.timeframe),
            tick_size=a.get("tick_size"), session=session))
        exe = ExecutionConfig(
            origin=ConfigOrigin.INSTRUMENT_CONFIG, starting_equity=book_spec("US").starting_budget,
            fee_schedule=fee_schedule, **{k: a.get(k) for k in EXECUTION_KEYS if k != "fee_schedule"}, **eod,
            **short_kw, shorts_enabled=shorts_ready)
        out.append(InstrumentSpec(sym, "US", cfg.timeframe, market, exe, data_source=feed_label(cfg.feed),
                                  shorts_enabled=shorts_ready))
    return out


# Owner decision 2026-11-24 (provisional): US Stocks intraday uses Alpaca IEX REAL-TIME 5-minute bars. Delayed SIP is
# never a fallback; real-time SIP is an optional future upgrade. IEX is ONE venue: never described as consolidated.
SELECTED_FEED = "iex"
FEED_LABELS = {"iex": "alpaca iex real-time (single venue IEX, not consolidated tape)",
               "sip": "alpaca sip (consolidated tape)"}


def feed_label(feed: Optional[str]) -> Optional[str]:
    return FEED_LABELS.get(feed) if feed else None


def readiness(cfg: Optional[USStocksConfig], cal: Dict[str, Any], credentials_present: bool,
              today: Optional[date] = None) -> Dict[str, Any]:
    """Why the US Stocks book cannot trade yet. Empty `blockers` = configuration complete (activation still needs the
    owner). `short_blockers` lists why SELL (short) entries are refused; they do not block the long side."""
    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    blockers: List[str] = []
    short_blockers: List[str] = []
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
        short_blockers += ["%s: NOT APPROVED" % k for k in cfg.short_not_approved]
    if not cal.get("verified"):
        blockers.append("NYSE holiday calendar: NOT VERIFIED")
    lo, hi = calendar_range(cal)
    if not lo <= today <= hi:
        blockers.append("NYSE calendar covers %s..%s only; today %s is not covered" % (lo, hi, today))
    if cfg is not None and not blockers and cfg.instruments:
        # build exactly what the runner builds: a value that Module E refuses (e.g. an invalid EOD pair) is a readiness
        # blocker here, never a crash-looping runner
        try:
            for sp in instrument_specs(cfg, cal):
                miss = sp.execution.missing(sp.market)
                if miss:
                    blockers.append("%s: Module E configuration incomplete: %s" % (sp.instrument_id, ", ".join(miss)))
                    break
        except (ValueError, TypeError) as e:
            blockers.append("configuration rejected by Module E: %s" % e)
    due = fees_us.reverify_due(today)
    if due:
        blockers.append(due)
    if not credentials_present:
        blockers.append("V6 Alpaca DATA-ONLY credential: not supplied")
    return {"book_id": "US", "ready": not blockers, "blockers": blockers,
            "shorts_ready": not blockers and not short_blockers, "short_blockers": short_blockers}
