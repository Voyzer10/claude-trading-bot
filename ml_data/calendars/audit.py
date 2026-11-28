"""Calendar provenance audit logic and CLI entrypoint (`python -m ml_data.calendars audit`)."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time as dt_time, timezone
from typing import Any, Dict, List, Optional, Sequence

from .verified_schedules import VERIFIED_CALENDAR_SPECS, VerifiedCalendarSpec


def _parse_iso_dt(val: str, *, end_of_day: bool = False) -> datetime:
    s = val.strip()
    if "T" not in s and " " not in s:
        d = date.fromisoformat(s)
        t = dt_time(23, 59, 59) if end_of_day else dt_time(0, 0, 0)
        return datetime.combine(d, t, tzinfo=timezone.utc)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _validate_spec_contents(spec: VerifiedCalendarSpec, *, now_utc: Optional[datetime] = None) -> List[str]:
    errors: List[str] = []
    ref_now = now_utc or datetime.now(timezone.utc)
    if spec.calendar_id == "XNAS" and "nyse.com" in spec.source_url.lower():
        errors.append(f"exchange/source mismatch: XNAS points to {spec.source_url}")
    if spec.calendar_id == "XNYS" and "nasdaq.com" in spec.source_url.lower():
        errors.append(f"exchange/source mismatch: XNYS points to {spec.source_url}")
    if spec.verification_status in ("VERIFIED_OFFICIAL", "VERIFIED_OFFICIAL_WITH_UPDATES"):
        if not spec.source_document_reference or spec.source_document_reference == "UNPUBLISHED":
            errors.append("missing source_document_reference")
        if not spec.source_published_at:
            errors.append("missing source_published_at")
        if not spec.retrieved_at:
            errors.append("missing retrieved_at")
        if not spec.verified_at:
            errors.append("missing verified_at")
    try:
        pub_dt = _parse_iso_dt(spec.source_published_at) if spec.source_published_at else None
        ret_dt = _parse_iso_dt(spec.retrieved_at) if spec.retrieved_at else None
        ver_dt = _parse_iso_dt(spec.verified_at) if spec.verified_at else None
        if pub_dt is not None and pub_dt > ref_now:
            errors.append(f"future source_published_at: {spec.source_published_at}")
        if pub_dt is not None and ret_dt is not None and pub_dt > ret_dt:
            errors.append(f"retrieved_at {spec.retrieved_at} precedes source_published_at {spec.source_published_at}")
        if ret_dt is not None and ver_dt is not None and ret_dt > ver_dt:
            errors.append(f"verified_at {spec.verified_at} precedes retrieved_at {spec.retrieved_at}")
    except ValueError as e:
        errors.append(f"invalid provenance timestamp: {e}")
    reg = spec.sessions.get("regular")
    if reg and "-" in reg:
        try:
            o_s, c_s = reg.split("-", 1)
            if dt_time.fromisoformat(c_s) <= dt_time.fromisoformat(o_s):
                errors.append(f"regular session close <= open: {reg}")
        except ValueError as e:
            errors.append(f"invalid regular session {reg!r}: {e}")
    hol_set = set()
    for d_s in spec.holidays:
        try:
            d = date.fromisoformat(d_s)
            hol_set.add(d_s)
            if spec.year is not None and d.year != spec.year:
                errors.append(f"holiday {d_s} outside year {spec.year}")
        except ValueError as e:
            errors.append(f"invalid holiday date {d_s!r}: {e}")
    for d_s, times in spec.special_sessions.items():
        try:
            d = date.fromisoformat(d_s)
            if spec.year is not None and d.year != spec.year:
                errors.append(f"special_session {d_s} outside year {spec.year}")
            if d_s in hol_set:
                errors.append(f"date {d_s} in both holidays and special_sessions")
            if dt_time.fromisoformat(times[1]) <= dt_time.fromisoformat(times[0]):
                errors.append(f"special_session {d_s} close <= open: {times}")
        except (ValueError, IndexError, TypeError) as e:
            errors.append(f"invalid special_session {d_s!r}: {e}")
    for d_s, t_s in spec.early_closes.items():
        try:
            d = date.fromisoformat(d_s)
            if spec.year is not None and d.year != spec.year:
                errors.append(f"early_close {d_s} outside year {spec.year}")
            dt_time.fromisoformat(t_s)
        except ValueError as e:
            errors.append(f"invalid early_close {d_s!r}: {e}")
    if spec.market == "IN" and spec.year is not None and spec.verification_status in ("VERIFIED_OFFICIAL", "VERIFIED_OFFICIAL_WITH_UPDATES"):
        from ..india.config import NSECalendar
        rt = NSECalendar.official(years=[spec.year])
        rt_hols = tuple(sorted(d.isoformat() for d in rt.holidays if d.year == spec.year))
        if rt_hols != tuple(sorted(spec.holidays)):
            errors.append("NSE runtime holidays differ from verified schedule")
        rt_spec = {d.isoformat(): (v[0].strftime("%H:%M"), v[1].strftime("%H:%M")) for d, v in rt.special_sessions.items() if d.year == spec.year}
        if rt_spec != dict(spec.special_sessions):
            errors.append("NSE runtime special_sessions differ from verified schedule")
        if rt.calendar_version != spec.calendar_version:
            errors.append(f"NSE runtime calendar_version {rt.calendar_version!r} != {spec.calendar_version!r}")
    return errors


def audit_calendar(market: str, year: Optional[int] = None) -> Dict[str, Any]:
    m = market.strip().lower()
    if m == "crypto":
        spec = VERIFIED_CALENDAR_SPECS[("crypto", None)]
        content_errors = _validate_spec_contents(spec)
        return {
            "market": "crypto",
            "calendar_id": spec.calendar_id,
            "calendar_version": spec.calendar_version,
            "verification_status": "UNVERIFIED" if content_errors else spec.verification_status,
            "verified_years": ["24/7_UTC"] if not content_errors else [],
            "unverified_years": [],
            "source_document": spec.source_document_reference,
            "checksum": spec.checksum,
            "content_valid": not content_errors,
            "content_errors": content_errors,
        }

    matching = {yr: sp for (mk, yr), sp in VERIFIED_CALENDAR_SPECS.items() if mk == m and yr is not None}
    verified_years: List[int] = []
    unverified_years: List[int] = []
    errors_by_year: Dict[int, List[str]] = {}
    for yr, sp in sorted(matching.items()):
        errs = _validate_spec_contents(sp)
        if errs:
            errors_by_year[yr] = errs
        if not errs and sp.verification_status in ("VERIFIED_OFFICIAL", "VERIFIED_OFFICIAL_WITH_UPDATES"):
            verified_years.append(yr)
        else:
            unverified_years.append(yr)
    if year is not None and year not in matching:
        unverified_years = sorted(set(unverified_years + [year]))

    target_spec = matching.get(year) if year is not None else (matching.get(verified_years[0]) if verified_years else None)
    target_errs = errors_by_year.get(target_spec.year, []) if (target_spec and target_spec.year is not None) else []
    status = target_spec.verification_status if target_spec else "UNVERIFIED"
    if target_errs:
        status = "UNVERIFIED"
    return {
        "market": m,
        "requested_year": year,
        "calendar_id": target_spec.calendar_id if target_spec else "UNKNOWN",
        "calendar_version": target_spec.calendar_version if target_spec else "UNVERIFIED",
        "verification_status": status,
        "verified_years": verified_years,
        "unverified_years": unverified_years,
        "source_document": target_spec.source_document_reference if target_spec else "UNPUBLISHED",
        "source_url": target_spec.source_url if target_spec else "",
        "supersedes_version": target_spec.supersedes_version if target_spec else None,
        "checksum": target_spec.checksum if target_spec else None,
        "content_valid": not target_errs and not errors_by_year,
        "content_errors": target_errs,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Audit verified cross-market exchange calendars.")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="Audit a market calendar.")
    a.add_argument("--market", required=True, choices=["india", "us_equity", "nasdaq", "us_futures", "crypto"])
    a.add_argument("--year", type=int, default=None)
    args = p.parse_args(argv)
    rep = audit_calendar(args.market, args.year)
    print(json.dumps(rep, indent=2, sort_keys=True))
    return 0 if rep.get("content_valid", True) else 1
