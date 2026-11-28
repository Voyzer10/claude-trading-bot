"""Verified, provenance-tracked production exchange calendars for NSE, NYSE, NASDAQ, CME Globex, and Crypto."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, time as dt_time
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


VERIFICATION_STATUSES = frozenset({
    "VERIFIED_OFFICIAL",
    "VERIFIED_OFFICIAL_WITH_UPDATES",
    "PARTIALLY_VERIFIED",
    "UNVERIFIED",
    "SUPERSEDED",
})


@dataclass(frozen=True)
class VerifiedCalendarSpec:
    calendar_id: str
    market: str
    venue: str
    product_group: str
    timezone: str
    year: Optional[int]
    sessions: Dict[str, str]
    holidays: Tuple[str, ...]
    early_closes: Dict[str, str]
    special_sessions: Dict[str, Tuple[str, str]]
    source_url: str
    source_document_reference: str
    source_published_at: str
    retrieved_at: str
    verified_at: str
    calendar_version: str
    verification_status: str
    supersedes_version: Optional[str] = None
    notes: str = ""

    @property
    def checksum(self) -> str:
        payload = asdict(self)
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["checksum"] = self.checksum
        return d


# ------------------------------------------------------------------ NSE INDIA (Authoritative JSON source of truth)
def _load_nse_specs_from_json() -> Dict[Tuple[str, Optional[int]], VerifiedCalendarSpec]:
    from ..india.calendars import load_nse_fo_calendar_data

    doc = load_nse_fo_calendar_data()
    cal_version = str(doc.get("calendar_version") or "1.0.0")
    reg = doc.get("regular_session") or {}
    reg_str = f"{reg.get('open', '09:15')}-{reg.get('close', '15:30')}"
    specs: Dict[Tuple[str, Optional[int]], VerifiedCalendarSpec] = {}
    for yr_key, ydoc in sorted(doc["years"].items()):
        yr = int(yr_key)
        srcs = list(ydoc.get("sources") or [])
        hols = tuple(sorted(str(h["date"]) for h in (ydoc.get("trading_holidays") or [])))
        specials = {
            str(s["date"]): (str(s["open"]), str(s["close"]))
            for s in (ydoc.get("special_sessions") or [])
        }
        refs = " + ".join(f"{s.get('circular_ref')} ({s.get('publication_date')})" for s in srcs if s.get("circular_ref"))
        pub_dates = [str(s.get("publication_date")) for s in srcs if s.get("publication_date")]
        ret_dates = [str(s.get("retrieved_at_utc")) for s in srcs if s.get("retrieved_at_utc")]
        is_ver = str(ydoc.get("verification_status") or "").upper() == "VERIFIED" and bool(srcs) and bool(hols)
        specs[("india", yr)] = VerifiedCalendarSpec(
            calendar_id="XNSE",
            market="IN",
            venue="NSE",
            product_group="NIFTY_BANKNIFTY_FNO",
            timezone=str(doc.get("timezone") or "Asia/Kolkata"),
            year=yr,
            sessions={"regular": reg_str, "pre_open": "09:00-09:08"},
            holidays=hols,
            early_closes={},
            special_sessions=specials,
            source_url=str(srcs[0].get("url")) if srcs else "https://www.nseindia.com/resources/exchange-communication-holidays",
            source_document_reference=refs or "UNPUBLISHED",
            source_published_at=max(pub_dates) if pub_dates else "",
            retrieved_at=max(ret_dates) if ret_dates else "",
            verified_at=max(ret_dates) if (is_ver and ret_dates) else "",
            calendar_version=cal_version,
            verification_status="VERIFIED_OFFICIAL_WITH_UPDATES" if is_ver else "UNVERIFIED",
            supersedes_version=None,
            notes=f"Loaded from authoritative nse_fo_calendar_v1.json (v{cal_version}).",
        )
    return specs


_NSE_JSON_SPECS = _load_nse_specs_from_json()
NSE_2026_HOLIDAYS: Tuple[str, ...] = _NSE_JSON_SPECS[("india", 2026)].holidays

# ------------------------------------------------------------------ NYSE (2026, 2027, 2028)
NYSE_HOLIDAYS: Dict[int, Tuple[str, ...]] = {
    2026: (
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
        "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    ),
    2027: (
        "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
        "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
    ),
    2028: (
        "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19",
        "2028-07-04", "2028-09-04", "2028-11-23", "2028-12-25",
    ),
}

NYSE_EARLY_CLOSES: Dict[int, Dict[str, str]] = {
    2026: {"2026-11-27": "13:00", "2026-12-24": "13:00"},
    2027: {"2027-11-26": "13:00"},
    2028: {"2028-07-03": "13:00", "2028-11-24": "13:00"},
}

# ------------------------------------------------------------------ CME GLOBEX EQUITY INDEX FUTURES (2026, 2027)
CME_EARLY_CLOSES: Dict[int, Dict[str, str]] = {
    2026: {
        "2026-01-19": "12:00", "2026-02-16": "12:00", "2026-05-25": "12:00",
        "2026-06-19": "12:00", "2026-07-03": "12:00", "2026-09-07": "12:00",
        "2026-11-26": "12:00", "2026-11-27": "12:15", "2026-12-24": "12:15",
    },
    2027: {
        "2027-01-18": "12:00", "2027-02-15": "12:00", "2027-05-31": "12:00",
        "2027-06-18": "12:00", "2027-07-05": "12:00", "2027-09-06": "12:00",
        "2027-11-25": "12:00", "2027-11-26": "12:15",
    },
}

VERIFIED_CALENDAR_SPECS: Dict[Tuple[str, Optional[int]], VerifiedCalendarSpec] = {
    **_NSE_JSON_SPECS,
    ("india", 2027): VerifiedCalendarSpec(
        calendar_id="XNSE",
        market="IN",
        venue="NSE",
        product_group="NIFTY_BANKNIFTY_FNO",
        timezone="Asia/Kolkata",
        year=2027,
        sessions={"regular": "09:15-15:30"},
        holidays=(),
        early_closes={},
        special_sessions={},
        source_url="https://www.nseindia.com/resources/exchange-communication-holidays",
        source_document_reference="UNPUBLISHED",
        source_published_at="",
        retrieved_at="2026-11-28T00:00:00Z",
        verified_at="",
        calendar_version="2027.0-unverified",
        verification_status="UNVERIFIED",
        notes="2027 NSE F&O trading holiday circular not yet verified; do not extrapolate 2026 dates.",
    ),
    **{
        ("us_equity", yr): VerifiedCalendarSpec(
            calendar_id="XNYS",
            market="US",
            venue="NYSE",
            product_group="US_EQUITIES_OPTIONS",
            timezone="America/New_York",
            year=yr,
            sessions={"pre_market": "04:00-09:30", "regular": "09:30-16:00", "options_late_close": "16:15", "post_market": "16:00-20:00"},
            holidays=NYSE_HOLIDAYS[yr],
            early_closes=NYSE_EARLY_CLOSES[yr],
            special_sessions={},
            source_url="https://www.nyse.com/trade/hours-calendars",
            source_document_reference=f"NYSE Group Holiday & Early Closing Dates {yr} ({'2024-11-08' if yr in (2026, 2027) else '2025-12-23'})",
            source_published_at="2024-11-08" if yr in (2026, 2027) else "2025-12-23",
            retrieved_at="2026-11-28T00:00:00Z",
            verified_at="2026-11-28T00:00:00Z",
            calendar_version=f"{yr}.1",
            verification_status="VERIFIED_OFFICIAL",
        )
        for yr in (2026, 2027, 2028)
    },
    **{
        ("nasdaq", yr): VerifiedCalendarSpec(
            calendar_id="XNAS",
            market="US",
            venue="NASDAQ",
            product_group="US_EQUITIES_OPTIONS",
            timezone="America/New_York",
            year=yr,
            sessions={"pre_market": "04:00-09:30", "regular": "09:30-16:00", "post_market": "16:00-20:00"},
            holidays=NYSE_HOLIDAYS[yr],
            early_closes=NYSE_EARLY_CLOSES[yr],
            special_sessions={},
            source_url="https://www.nasdaq.com/market-activity/stock-market-holiday-schedule",
            source_document_reference=f"NASDAQ Stock Market Holiday Schedule {yr} (publication date unverified)",
            source_published_at="",
            retrieved_at="2026-11-28T00:00:00Z",
            verified_at="",
            calendar_version=f"{yr}.1",
            verification_status="PARTIALLY_VERIFIED",
            notes="Holiday dates align with US market schedule; independent Nasdaq circular publication date not yet verified.",
        )
        for yr in (2026, 2027)
    },
    **{
        ("us_futures", yr): VerifiedCalendarSpec(
            calendar_id="XCME_GLOBEX",
            market="US",
            venue="CME",
            product_group="ES_MES_NQ_MNQ_YM_MYM_RTY_M2K",
            timezone="America/Chicago",
            year=yr,
            sessions={"globex": "Sun 17:00 - Fri 16:00 CT", "maintenance_break": "16:00-17:00 CT", "rth": "08:30-15:00 CT"},
            holidays=("2026-01-01", "2026-04-03", "2026-12-25") if yr == 2026 else ("2027-01-01", "2027-03-26", "2027-12-24"),
            early_closes=CME_EARLY_CLOSES[yr] if yr == 2026 else {},
            special_sessions={},
            source_url="https://www.cmegroup.com/trading-hours.html",
            source_document_reference=f"CME Globex Equity Index Futures Schedule {yr}",
            source_published_at="2025-12-01" if yr == 2026 else "",
            retrieved_at="2026-11-28T00:00:00Z",
            verified_at="2026-11-28T00:00:00Z" if yr == 2026 else "",
            calendar_version=f"{yr}.1",
            verification_status="VERIFIED_OFFICIAL" if yr == 2026 else "PARTIALLY_VERIFIED",
            notes="CME holiday early-close times are subject to final exchange notices ~2 weeks prior to each holiday.",
        )
        for yr in (2026, 2027)
    },
    ("crypto", None): VerifiedCalendarSpec(
        calendar_id="CRYPTO_24_7",
        market="CRYPTO",
        venue="GLOBAL_24_7",
        product_group="SPOT_AND_PERPETUALS",
        timezone="UTC",
        year=None,
        sessions={"continuous": "00:00-24:00 UTC"},
        holidays=(),
        early_closes={},
        special_sessions={},
        source_url="https://docs.coindcx.com/",
        source_document_reference="24/7 Continuous UTC Crypto Schedule",
        source_published_at="2026-01-01",
        retrieved_at="2026-11-28T00:00:00Z",
        verified_at="2026-11-28T00:00:00Z",
        calendar_version="2026.1",
        verification_status="VERIFIED_OFFICIAL",
        notes="Tracks maintenance, suspension, delisting, and stale feeds rather than weekly exchange closures.",
    ),
}


def build_verified_nse_calendar():
    from ..india.config import NSECalendar
    return NSECalendar.official()


def build_verified_us_equity_calendar(calendar_id: str = "XNYS"):
    from ..us.config import USCalendar
    is_nasdaq = calendar_id.strip().upper() == "XNAS"
    years = (2026, 2027) if is_nasdaq else (2026, 2027, 2028)
    hols = frozenset(date.fromisoformat(d) for y in years for d in NYSE_HOLIDAYS[y])
    ec = {
        date.fromisoformat(d): dt_time.fromisoformat(t)
        for y in years
        for d, t in NYSE_EARLY_CLOSES[y].items()
    }
    # XNAS 2026/2027 are PARTIALLY_VERIFIED (independent Nasdaq circular publication date unverified),
    # so only XNYS marks 2026-2028 in verified_years while XNAS retains deterministic schedule dates.
    ver_years = frozenset() if is_nasdaq else frozenset(years)
    return USCalendar(holidays=hols, early_closes=ec, verified_years=ver_years)


def build_verified_cme_globex_calendar():
    from ..futures.config import CMEGlobexCalendar
    hols = frozenset(
        date.fromisoformat(d)
        for y in (2026, 2027)
        for d in VERIFIED_CALENDAR_SPECS[("us_futures", y)].holidays
    )
    ec = {date.fromisoformat(d): dt_time.fromisoformat(t) for d, t in CME_EARLY_CLOSES[2026].items()}
    return CMEGlobexCalendar(holidays=hols, early_closes=ec, verified_years=frozenset({2026}))
