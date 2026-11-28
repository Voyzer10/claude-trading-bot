"""Tests for verified production exchange calendars and audit CLI."""
from __future__ import annotations

from datetime import date, datetime, time as dt_time

import pytest

from ml_data.calendars import (
    CryptoCalendarAdapter,
    VERIFIED_CALENDAR_SPECS,
    audit_calendar,
    build_verified_cme_globex_calendar,
    build_verified_nse_calendar,
    build_verified_us_equity_calendar,
)
from ml_data.futures.config import CME_TZ
from ml_data.india.config import IST_TZ
from ml_data.india.exceptions import CalendarError
from ml_data.us.config import NY_TZ


def test_verified_calendars_nse_nyse_nasdaq_cme_and_crypto():
    # NSE 2026 verified with Muhurat Trading on 2026-11-08; 2027 UNVERIFIED
    nse_2026 = audit_calendar("india", 2026)
    nse_2027 = audit_calendar("india", 2027)
    assert nse_2026["verification_status"] == "VERIFIED_OFFICIAL_WITH_UPDATES"
    assert nse_2026["calendar_version"] == "1.0.0"
    assert nse_2027["verification_status"] == "UNVERIFIED"

    nse_cal = build_verified_nse_calendar()
    assert nse_cal.is_trading_day(date(2026, 1, 26), require_verified=True) is False  # Republic Day
    assert nse_cal.is_trading_day(date(2026, 1, 15), require_verified=True) is False  # Election Holiday
    muhurat = nse_cal.session_bounds(date(2026, 11, 8), require_verified=True)
    assert muhurat is not None and (muhurat[0].hour, muhurat[0].minute) == (14, 20) and (muhurat[1].hour, muhurat[1].minute) == (15, 40)
    with pytest.raises(CalendarError):
        nse_cal.is_trading_day(date(2027, 1, 4), require_verified=True)

    # NYSE 2026/2027/2028 & NASDAQ 2026/2027
    assert audit_calendar("us_equity", 2027)["verification_status"] == "VERIFIED_OFFICIAL"
    assert audit_calendar("us_equity", 2028)["verification_status"] == "VERIFIED_OFFICIAL"
    assert audit_calendar("nasdaq", 2027)["calendar_id"] == "XNAS"

    us_cal = build_verified_us_equity_calendar()
    assert us_cal.is_trading_day(date(2027, 12, 24), require_verified=True) is False
    ec_bounds = us_cal.session_bounds(date(2026, 11, 27), require_verified=True)
    assert ec_bounds is not None and ec_bounds[1].hour == 13

    # CME Globex 2026/2027 maintenance break & early close
    assert audit_calendar("us_futures", 2026)["verification_status"] == "VERIFIED_OFFICIAL"
    cme_cal = build_verified_cme_globex_calendar()
    assert cme_cal.classify_session(datetime(2026, 11, 25, 16, 30, tzinfo=CME_TZ)) == "MAINTENANCE_BREAK"
    assert cme_cal.classify_session(datetime(2026, 11, 26, 13, 0, tzinfo=CME_TZ)) == "CLOSED"  # Thanksgiving early close 12:00

    # Crypto 24/7
    assert audit_calendar("crypto")["verification_status"] == "VERIFIED_OFFICIAL"
    assert CryptoCalendarAdapter().is_trading_day(date(2026, 11, 28)) is True

    # Checksums deterministic
    assert len(VERIFIED_CALENDAR_SPECS[("india", 2026)].checksum) == 64
