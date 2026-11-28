"""India NSE ExchangeCalendar wrapper reusing ml_data.india.config.NSECalendar."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from ..india.config import IST_TZ, NSECalendar
from .base import CalendarMetadata, ExchangeCalendar


class IndiaNSECalendarAdapter(ExchangeCalendar):
    def __init__(
        self,
        calendar: Optional[NSECalendar] = None,
        *,
        calendar_id: str = "XNSE",
        calendar_version: Optional[str] = None,
    ) -> None:
        self.inner = calendar or NSECalendar.official()
        self.calendar_id = calendar_id
        self.calendar_version = calendar_version or self.inner.calendar_version

    @property
    def metadata(self) -> CalendarMetadata:
        return CalendarMetadata(
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            timezone="Asia/Kolkata",
            verified_years=self.inner.verified_years,
            verification_status="VERIFIED" if self.inner.verified_years else "UNVERIFIED",
            source_url="https://www.nseindia.com/resources/exchange-communication-holidays",
        )

    def is_trading_day(self, day: date, *, require_verified: bool = False) -> bool:
        return self.inner.is_trading_day(day, require_verified=require_verified)

    def classify_session(self, ts: datetime, *, require_verified: bool = False) -> str:
        ist = ts.astimezone(IST_TZ) if ts.tzinfo else ts.replace(tzinfo=IST_TZ)
        if not self.inner.is_trading_day(ist.date(), require_verified=require_verified):
            return "CLOSED"
        if not self.inner.is_in_session(ist, require_verified=require_verified):
            return "CLOSED"
        if ist.date() in self.inner.special_sessions:
            return self.inner.special_session_kinds.get(ist.date(), "SPECIAL_SESSION")
        return "REGULAR"

    def trade_date_for(self, ts: datetime) -> date:
        return self.inner.session_date(ts)
