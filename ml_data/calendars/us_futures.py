"""US CME Globex Futures ExchangeCalendar wrapper reusing ml_data.futures.config.CMEGlobexCalendar."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from ..futures.config import CMEGlobexCalendar
from .base import CalendarMetadata, ExchangeCalendar
from .verified_schedules import build_verified_cme_globex_calendar


class USFuturesCalendarAdapter(ExchangeCalendar):
    def __init__(
        self,
        calendar: Optional[CMEGlobexCalendar] = None,
        *,
        calendar_id: str = "XCME_GLOBEX",
        calendar_version: str = "2026.1",
    ) -> None:
        self.inner = calendar if calendar is not None else build_verified_cme_globex_calendar()
        self.calendar_id = calendar_id
        self.calendar_version = calendar_version

    @property
    def metadata(self) -> CalendarMetadata:
        return CalendarMetadata(
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            timezone="America/Chicago",
            verified_years=self.inner.verified_years,
            verification_status="VERIFIED" if self.inner.verified_years else "UNVERIFIED",
            source_url="https://www.cmegroup.com/trading-hours.html",
        )

    def is_trading_day(self, day: date, *, require_verified: bool = False) -> bool:
        return self.inner.is_trading_day(day, require_verified=require_verified)

    def classify_session(self, ts: datetime, *, require_verified: bool = False) -> str:
        return self.inner.classify_session(ts, require_verified=require_verified)

    def trade_date_for(self, ts: datetime) -> date:
        return self.inner.trade_date_for(ts)
