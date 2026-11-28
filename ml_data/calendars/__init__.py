"""Cross-market exchange calendar registry and verified schedules."""
from __future__ import annotations

from .audit import audit_calendar
from .base import CalendarMetadata, ExchangeCalendar
from .crypto import CryptoCalendarAdapter
from .india import IndiaNSECalendarAdapter
from .us_equity import USEquityCalendarAdapter
from .us_futures import USFuturesCalendarAdapter
from .verified_schedules import (
    VERIFICATION_STATUSES,
    VERIFIED_CALENDAR_SPECS,
    VerifiedCalendarSpec,
    build_verified_cme_globex_calendar,
    build_verified_nse_calendar,
    build_verified_us_equity_calendar,
)

__all__ = [
    "CalendarMetadata",
    "CryptoCalendarAdapter",
    "ExchangeCalendar",
    "IndiaNSECalendarAdapter",
    "USEquityCalendarAdapter",
    "USFuturesCalendarAdapter",
    "VERIFICATION_STATUSES",
    "VERIFIED_CALENDAR_SPECS",
    "VerifiedCalendarSpec",
    "audit_calendar",
    "build_verified_cme_globex_calendar",
    "build_verified_nse_calendar",
    "build_verified_us_equity_calendar",
]
