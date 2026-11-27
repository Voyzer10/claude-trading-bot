"""Offline tests for the versioned, official-circular-backed NSE F&O calendar."""
from __future__ import annotations

from datetime import date, time as dt_time

import pytest

from ml_data.india import CalendarError, NSECalendar, build_nse_fo_calendar, load_nse_fo_calendar_data
from ml_data.india.config import IST_TZ


def test_official_nse_fo_calendar_provenance_and_years():
    raw = load_nse_fo_calendar_data()
    assert raw["segment"] == "NFO"
    assert raw["timezone"] == "Asia/Kolkata"
    assert set(raw["years"].keys()) == {"2025", "2026"}

    for yr_str, ydoc in raw["years"].items():
        assert ydoc["verification_status"] == "VERIFIED"
        assert len(ydoc["sources"]) >= 3
        for src in ydoc["sources"]:
            assert src["circular_ref"].startswith("NSE/FAOP/")
            assert src["url"].startswith("https://nsearchives.nseindia.com/content/circulars/")
            assert src["publication_date"]
            assert src["retrieved_at_utc"]

    cal = NSECalendar.official()
    assert cal.verified_years == frozenset({2025, 2026})
    assert cal.is_year_verified(2025) and cal.is_year_verified(2026)
    assert not cal.is_year_verified(2024)
    assert not cal.is_year_verified(2027)


def test_normal_days_weekends_official_holidays_and_amendments():
    cal = build_nse_fo_calendar()

    # Normal trading day -> 09:15–15:30 IST
    assert cal.day_status(date(2026, 11, 27), require_verified=True) == "TRADING_DAY"
    b = cal.session_bounds(date(2026, 11, 27), require_verified=True)
    assert b is not None
    assert (b[0].hour, b[0].minute) == (9, 15) and (b[1].hour, b[1].minute) == (15, 30)
    assert b[0].tzinfo == IST_TZ

    # Ordinary Saturday/Sunday closed
    assert cal.day_status(date(2026, 11, 28), require_verified=True) == "WEEKEND"
    assert cal.session_bounds(date(2026, 11, 28), require_verified=True) is None
    assert cal.day_status(date(2025, 11, 23), require_verified=True) == "WEEKEND"

    # Official annual holidays (2025 FAOP65588, 2026 FAOP71777) & amendment (2026-01-15 FAOP72262)
    for h_day in (
        date(2025, 2, 26),   # Mahashivratri
        date(2025, 10, 22),  # Diwali-Balipratipada
        date(2026, 1, 15),   # Maharashtra Municipal Election amendment (NSE/FAOP/72262)
        date(2026, 1, 26),   # Republic Day
        date(2026, 11, 24),  # Prakash Gurpurb
        date(2026, 12, 25),  # Christmas
    ):
        assert cal.day_status(h_day, require_verified=True) == "HOLIDAY"
        assert cal.is_trading_day(h_day, require_verified=True) is False
        assert cal.session_bounds(h_day, require_verified=True) is None


def test_special_weekend_budget_and_muhurat_sessions_override_weekend_and_holiday():
    cal = NSECalendar.official()

    # Saturday Feb 01, 2025 Budget special session (NSE/FAOP/65730): 09:15-15:30 IST overrides weekend
    b_2025 = cal.session_bounds(date(2025, 2, 1), require_verified=True)
    assert cal.day_status(date(2025, 2, 1), require_verified=True) == "WEEKEND_SPECIAL"
    assert b_2025 is not None and (b_2025[0].hour, b_2025[0].minute) == (9, 15) and (b_2025[1].hour, b_2025[1].minute) == (15, 30)

    # Tuesday Oct 21, 2025 Diwali Muhurat (NSE/FAOP/70320): 13:45-14:45 IST replaces normal 09:15-15:30
    m_2025 = cal.session_bounds(date(2025, 10, 21), require_verified=True)
    assert cal.day_status(date(2025, 10, 21), require_verified=True) == "MUHURAT"
    assert m_2025 is not None and (m_2025[0].hour, m_2025[0].minute) == (13, 45) and (m_2025[1].hour, m_2025[1].minute) == (14, 45)
    assert not cal.is_in_session(b_2025[0].replace(month=10, day=21, hour=10, minute=0), require_verified=True)

    # Sunday Feb 01, 2026 Budget special session (NSE/FAOP/72352): 09:15-15:30 IST overrides weekend
    b_2026 = cal.session_bounds(date(2026, 2, 1), require_verified=True)
    assert cal.day_status(date(2026, 2, 1), require_verified=True) == "WEEKEND_SPECIAL"
    assert b_2026 is not None and (b_2026[0].hour, b_2026[0].minute) == (9, 15) and (b_2026[1].hour, b_2026[1].minute) == (15, 30)

    # Sunday Nov 08, 2026 Diwali Muhurat (NSE/FAOP/76940): 14:20-15:40 IST overrides weekend
    m_2026 = cal.session_bounds(date(2026, 11, 8), require_verified=True)
    assert cal.day_status(date(2026, 11, 8), require_verified=True) == "MUHURAT"
    assert m_2026 is not None and (m_2026[0].hour, m_2026[0].minute) == (14, 20) and (m_2026[1].hour, m_2026[1].minute) == (15, 40)


def test_early_close_unverified_year_and_unnotified_special_session_timings():
    early_day = date(2026, 7, 1)
    pending_day = date(2027, 10, 29)
    cal = NSECalendar(
        verified_years=frozenset({2026, 2027}),
        special_sessions={early_day: (dt_time(9, 15), dt_time(13, 0))},
        pending_special_sessions={pending_day: "Muhurat timings to be notified subsequently"},
    )

    # Early close
    assert cal.day_status(early_day, require_verified=True) == "EARLY_CLOSE"
    ec = cal.session_bounds(early_day, require_verified=True)
    assert ec is not None and (ec[0].hour, ec[0].minute) == (9, 15) and (ec[1].hour, ec[1].minute) == (13, 0)
    assert not cal.is_in_session(ec[0].replace(hour=13, minute=0), require_verified=True)

    # Unverified year must NEVER be treated as verified normal year
    off_cal = NSECalendar.official()
    assert off_cal.day_status(date(2024, 6, 3)) == "UNVERIFIED_YEAR"
    assert off_cal.day_status(date(2027, 6, 3)) == "UNVERIFIED_YEAR"
    with pytest.raises(CalendarError):
        off_cal.is_trading_day(date(2027, 6, 3), require_verified=True)
    with pytest.raises(CalendarError):
        off_cal.session_bounds(date(2024, 6, 3), require_verified=True)

    # Pending special session with unnotified timings must NOT invent 09:15-15:30
    assert cal.day_status(pending_day) == "SPECIAL_SESSION_TIMINGS_UNAVAILABLE"
    assert cal.session_bounds(pending_day, require_verified=False) is None
    with pytest.raises(CalendarError):
        cal.session_bounds(pending_day, require_verified=True)
