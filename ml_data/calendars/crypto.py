"""Crypto 24/7 UTC ExchangeCalendar wrapper."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from ..crypto.config import UTC_TZ, CryptoCalendar
from .base import CalendarMetadata, ExchangeCalendar


class CryptoCalendarAdapter(ExchangeCalendar):
    def __init__(
        self,
        calendar: Optional[CryptoCalendar] = None,
        *,
        calendar_id: str = "CRYPTO_24_7",
        calendar_version: str = "2026.1",
    ) -> None:
        self.inner = calendar or CryptoCalendar()
        self.calendar_id = calendar_id
        self.calendar_version = calendar_version

    @property
    def metadata(self) -> CalendarMetadata:
        return CalendarMetadata(
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            timezone="UTC",
            verified_years=self.inner.verified_years,
            verification_status="VERIFIED",
        )

    def is_trading_day(self, day: date, *, require_verified: bool = False) -> bool:
        return True

    def classify_session(self, ts: datetime, *, require_verified: bool = False) -> str:
        return "CONTINUOUS_24_7"

    def trade_date_for(self, ts: datetime) -> date:
        utc_dt = ts.astimezone(UTC_TZ) if ts.tzinfo else ts.replace(tzinfo=UTC_TZ)
        return utc_dt.date()
