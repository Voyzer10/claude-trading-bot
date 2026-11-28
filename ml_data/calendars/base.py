"""Cross-market exchange calendar base interface and verification metadata."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import FrozenSet, Optional, Tuple


@dataclass(frozen=True)
class CalendarMetadata:
    calendar_id: str
    calendar_version: str
    timezone: str
    verified_years: FrozenSet[int]
    verification_status: str  # "VERIFIED" | "UNVERIFIED"
    source_url: str = ""
    retrieved_date: Optional[str] = None
    holiday_list_version: Optional[str] = None


class ExchangeCalendar(ABC):
    """Abstract market-aware calendar interface."""

    @property
    @abstractmethod
    def metadata(self) -> CalendarMetadata:
        """Return calendar verification and provenance metadata."""

    @abstractmethod
    def is_trading_day(self, day: date, *, require_verified: bool = False) -> bool:
        """Return True if day is a valid trading day."""

    @abstractmethod
    def classify_session(self, ts: datetime, *, require_verified: bool = False) -> str:
        """Classify timestamp into market-specific session label."""

    @abstractmethod
    def trade_date_for(self, ts: datetime) -> date:
        """Return exchange trading date for a UTC or local timestamp."""

    def is_verified_for_range(self, start_day: date, end_day: date) -> bool:
        if end_day < start_day:
            start_day, end_day = end_day, start_day
        vy = self.metadata.verified_years
        return all(y in vy for y in range(start_day.year, end_day.year + 1))
