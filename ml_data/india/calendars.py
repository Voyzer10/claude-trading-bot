"""Versioned, circular-backed NSE F&O trading calendar loader and validator."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time
from typing import Any, Dict, FrozenSet, Iterable, Optional, Tuple

from .exceptions import CalendarError

DEFAULT_NSE_FO_CALENDAR_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "calendar_data",
    "nse_fo_calendar_v1.json",
)


@dataclass(frozen=True)
class CalendarSourceMeta:
    """Official exchange circular provenance for a calendar year."""

    circular_ref: str
    exchange_circular_ref: str
    publication_date: date
    retrieved_at_utc: datetime
    url: str
    scope: str


def _parse_hhmm(val: Any, label: str) -> dt_time:
    if not isinstance(val, str) or ":" not in val:
        raise CalendarError(f"Invalid time {val!r} for {label} (expected HH:MM)")
    parts = val.strip().split(":")
    if len(parts) != 2:
        raise CalendarError(f"Invalid time {val!r} for {label}")
    try:
        return dt_time(int(parts[0]), int(parts[1]))
    except ValueError as e:
        raise CalendarError(f"Invalid time {val!r} for {label}: {e}") from e


def load_nse_fo_calendar_data(path: str = DEFAULT_NSE_FO_CALENDAR_PATH) -> Dict[str, Any]:
    """Load and validate the versioned NSE F&O JSON calendar document."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or not isinstance(doc.get("years"), dict):
        raise CalendarError(f"Malformed NSE F&O calendar JSON: {path}")
    if doc.get("timezone") != "Asia/Kolkata":
        raise CalendarError(f"Unexpected calendar timezone: {doc.get('timezone')!r}")
    return doc


def build_nse_fo_calendar(
    *,
    path: str = DEFAULT_NSE_FO_CALENDAR_PATH,
    years: Optional[Iterable[int]] = None,
) -> "NSECalendar":
    """Construct a verified NSECalendar from the versioned NSE F&O calendar dataset.

    Only years marked ``verification_status == 'VERIFIED'`` in the source dataset are added
    to ``verified_years``. Unverified or missing years are never promoted silently.
    """
    from .config import NSECalendar

    doc = load_nse_fo_calendar_data(path)
    reg = doc.get("regular_session") or {}
    reg_open = _parse_hhmm(reg.get("open", "09:15"), "regular_session.open")
    reg_close = _parse_hhmm(reg.get("close", "15:30"), "regular_session.close")
    if reg_close <= reg_open:
        raise CalendarError("regular_session.close must be after regular_session.open")

    requested_years = {int(y) for y in years} if years is not None else None
    holidays = set()
    holiday_descriptions: Dict[date, str] = {}
    special_sessions: Dict[date, Tuple[dt_time, dt_time]] = {}
    special_session_kinds: Dict[date, str] = {}
    pending_special: Dict[date, str] = {}
    verified_years = set()
    sources_by_year: Dict[int, Tuple[Dict[str, Any], ...]] = {}

    for yr_key, ydoc in doc["years"].items():
        yr = int(yr_key)
        if requested_years is not None and yr not in requested_years:
            continue
        if not isinstance(ydoc, dict):
            raise CalendarError(f"Invalid year entry {yr_key!r} in {path}")
        if str(ydoc.get("verification_status") or "").upper() == "VERIFIED":
            verified_years.add(yr)
        srcs = tuple(dict(s) for s in (ydoc.get("sources") or []) if isinstance(s, dict))
        sources_by_year[yr] = srcs

        for h in ydoc.get("trading_holidays") or ():
            d = date.fromisoformat(str(h["date"]))
            if d.year != yr:
                raise CalendarError(f"Holiday {d} does not belong to year {yr}")
            holidays.add(d)
            holiday_descriptions[d] = str(h.get("description") or "Trading Holiday")

        for s in ydoc.get("special_sessions") or ():
            d = date.fromisoformat(str(s["date"]))
            if d.year != yr:
                raise CalendarError(f"Special session {d} does not belong to year {yr}")
            o_t = _parse_hhmm(s.get("open"), f"special_sessions[{d}].open")
            c_t = _parse_hhmm(s.get("close"), f"special_sessions[{d}].close")
            if c_t <= o_t:
                raise CalendarError(f"Special session {d} close {c_t} must be after open {o_t}")
            special_sessions[d] = (o_t, c_t)
            special_session_kinds[d] = str(s.get("kind") or "SPECIAL_SESSION")
            # Keep normal full-day holidays strictly separate from special-session days.
            holidays.discard(d)

        for p in ydoc.get("pending_special_sessions") or ():
            d = date.fromisoformat(str(p["date"]))
            if d.year != yr:
                raise CalendarError(f"Pending special session {d} does not belong to year {yr}")
            if d not in special_sessions:
                pending_special[d] = str(p.get("description") or "Special session timings pending notification")
                holidays.discard(d)

    return NSECalendar(
        holidays=frozenset(holidays),
        special_sessions=special_sessions,
        verified_years=frozenset(verified_years),
        regular_open=reg_open,
        regular_close=reg_close,
        pending_special_sessions=pending_special,
        special_session_kinds=special_session_kinds,
        holiday_descriptions=holiday_descriptions,
        sources_by_year=sources_by_year,
        calendar_version=str(doc.get("calendar_version") or "1.0.0"),
        segment=str(doc.get("segment") or "NFO"),
    )
