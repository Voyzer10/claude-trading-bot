"""US Equity & Options ExchangeCalendar wrapper reusing ml_data.us.config.USCalendar."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from ..us.config import NY_TZ, USCalendar
from ..us.exceptions import USCalendarError
from .base import CalendarMetadata, ExchangeCalendar
from .verified_schedules import VERIFIED_CALENDAR_SPECS, build_verified_us_equity_calendar


class USEquityCalendarAdapter(ExchangeCalendar):
    def __init__(
        self,
        calendar: Optional[USCalendar] = None,
        *,
        calendar_id: str = "XNYS",
        calendar_version: Optional[str] = None,
        effective_year: Optional[int] = None,
        options_late_close: bool = False,
    ) -> None:
        self.calendar_id = calendar_id.strip().upper()
        self._market_key = "nasdaq" if self.calendar_id == "XNAS" else "us_equity"
        self.inner = calendar if calendar is not None else build_verified_us_equity_calendar(calendar_id=self.calendar_id)
        self.options_late_close = options_late_close
        target_yr = effective_year if effective_year is not None else 2026
        spec = VERIFIED_CALENDAR_SPECS.get((self._market_key, target_yr))
        if effective_year is not None and spec is None:
            raise USCalendarError(f"{self.calendar_id} calendar is not verified for year {effective_year}")
        self.calendar_version = calendar_version or (spec.calendar_version if spec is not None else f"{target_yr}.0-unverified")
        self.source_url = (
            spec.source_url
            if spec is not None
            else (
                "https://www.nasdaq.com/market-activity/stock-market-holiday-schedule"
                if self._market_key == "nasdaq"
                else "https://www.nyse.com/trade/hours-calendars"
            )
        )

    def version_for_year(self, year: int, *, require_verified: bool = False) -> str:
        spec = VERIFIED_CALENDAR_SPECS.get((self._market_key, int(year)))
        if spec is None or int(year) not in self.inner.verified_years:
            if require_verified:
                raise USCalendarError(f"{self.calendar_id} calendar is not verified for year {year}")
            return f"{int(year)}.0-unverified"
        return spec.calendar_version

    @property
    def metadata(self) -> CalendarMetadata:
        if self.inner.verified_years:
            status = "VERIFIED"
        elif any(
            (sp := VERIFIED_CALENDAR_SPECS.get((self._market_key, y))) is not None
            and sp.verification_status == "PARTIALLY_VERIFIED"
            for y in (2026, 2027)
        ):
            status = "PARTIALLY_VERIFIED"
        else:
            status = "UNVERIFIED"
        return CalendarMetadata(
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            timezone="America/New_York",
            verified_years=self.inner.verified_years,
            verification_status=status,
            source_url=self.source_url,
        )

    def is_trading_day(self, day: date, *, require_verified: bool = False) -> bool:
        return self.inner.is_trading_day(day, require_verified=require_verified)

    def classify_session(self, ts: datetime, *, require_verified: bool = False) -> str:
        return self.inner.classify_session(ts, options_late_close=self.options_late_close, require_verified=require_verified)

    def trade_date_for(self, ts: datetime) -> date:
        ny = ts.astimezone(NY_TZ) if ts.tzinfo else ts.replace(tzinfo=NY_TZ)
        return ny.date()
