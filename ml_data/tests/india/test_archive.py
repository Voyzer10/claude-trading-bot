"""Tests for OptionContractArchive: selection policy, dry-run, final session, and expired retention."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from ml_data.india import (
    CalendarError,
    ContractDiscovery,
    ContractSelectionPolicy,
    InstrumentMasterDownloader,
    KiteAdapterError,
    KiteClientWrapper,
    KiteHistoricalDataClient,
    KiteInputError,
    NSECalendar,
    OptionContractArchive,
)
from ml_data.india.archive import (
    ARCHIVE_STATUS_COMPLETE,
    ARCHIVE_STATUS_PARTIAL,
    ARCHIVE_STATUS_UNAVAILABLE,
    ARCHIVE_STATUS_UNKNOWN,
)
from ml_data.india.config import IST_TZ
from ml_data.instruments import Instrument, InstrumentRegistry, InstrumentStatus
from ml_data.tests.india.fixtures import FakeKiteSDK


def _full_session_5m_candles(day_str: str, open_t: str = "09:15", count: int = 75):
    from datetime import timedelta

    h, m = map(int, open_t.split(":"))
    start = datetime(int(day_str[:4]), int(day_str[5:7]), int(day_str[8:10]), h, m, tzinfo=IST_TZ)
    rows = []
    for i in range(count):
        ts = start + timedelta(minutes=5 * i)
        rows.append([ts.isoformat(), 120.0 + i * 0.1, 121.0 + i * 0.1, 119.5 + i * 0.1, 120.5 + i * 0.1, 1000, 50000])
    return rows


def test_option_archive_policy_dry_run_dedup_and_expired_retention(tmp_path):
    # NIFTY26D0324500CE (token 100003, expiry 2026-12-03)
    exp_candles = [
        ["2026-12-03T09:15:00+0530", 120.0, 125.0, 118.0, 122.0, 5000, 100000],
        ["2026-12-03T15:29:00+0530", 150.0, 152.0, 149.0, 151.0, 8000, 90000],
    ]
    sdk = FakeKiteSDK(candles_by_token={(100003, "minute"): exp_candles})
    client = KiteClientWrapper(kite_client=sdk, sleeper=lambda _: None)
    dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / "master"))
    d0 = date(2026, 11, 27)
    nse = dl.download_snapshot("NSE", snap_date=d0)
    nfo = dl.download_snapshot("NFO", snap_date=d0)

    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))
    rep = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse, nfo_snapshot=nfo, registry=reg)
    hist = KiteHistoricalDataClient(client=client, registry=reg)
    arch = OptionContractArchive(
        archive_db_path=str(tmp_path / "archive.sqlite3"),
        registry=reg,
        historical_client=hist,
    )

    # Without policy: dry_run_report flags policy_required, select_contracts refuses
    dr_none = arch.dry_run_report()
    assert dr_none["eligible_active_options"] == 4 and dr_none["policy_required"] is True
    with pytest.raises(KiteInputError):
        arch.select_contracts(None)
    with pytest.raises(KiteInputError):
        arch.select_contracts(ContractSelectionPolicy())

    # Bounded policy selects NIFTY 24500 options expiring 2026-12-03
    pol = ContractSelectionPolicy(
        underlyings=("NIFTY",),
        min_strike=Decimal("24000"),
        max_strike=Decimal("25000"),
        include_expiries=[date(2026, 12, 3)],
    )
    dr = arch.dry_run_report(pol)
    assert dr["selected_count"] == 2

    nifty_ce = [c for c in arch.select_contracts(pol) if c.canonical_symbol == "NIFTY26D0324500CE"]
    f_dt = datetime(2026, 12, 3, 9, 15, tzinfo=IST_TZ)
    t_dt = datetime(2026, 12, 3, 15, 30, tzinfo=IST_TZ)
    res = arch.archive_contracts(nifty_ce, interval="minute", from_datetime=f_dt, to_datetime=t_dt)
    assert res[0]["candles_fetched"] == 2
    # Two boundary candles with unverified calendar cannot be claimed complete
    assert res[0]["final_session_archived"] is False
    assert res[0]["coverage_status"] == ARCHIVE_STATUS_UNKNOWN

    # Re-archiving avoids duplicates and preserves candles even when UNKNOWN/PARTIAL
    res2 = arch.archive_contracts(nifty_ce, interval="minute", from_datetime=f_dt, to_datetime=t_dt)
    assert res2[0]["total_archived"] == 2

    # Mark contract EXPIRED in registry: both registry record & archived candles remain intact
    exp_inst = Instrument.from_dict({
        **nifty_ce[0].to_dict(),
        "is_active": False,
        "instrument_status": InstrumentStatus.EXPIRED.value,
    })
    reg.upsert(exp_inst)
    assert len(reg.list_expired()) == 1
    assert arch.get_archived_status(exp_inst.instrument_id, "minute")["coverage_status"] == ARCHIVE_STATUS_UNKNOWN

    arch.close()
    reg.close()


def test_archive_completeness_states_and_calendar_validation(tmp_path):
    full_5m = _full_session_5m_candles("2026-12-03", "09:15", 75)
    missing_open = full_5m[1:]
    missing_close = full_5m[:-1]
    with_gap = full_5m[:20] + full_5m[22:]

    cal = NSECalendar(verified_years=frozenset({2026}))
    f_dt = datetime(2026, 12, 3, 9, 15, tzinfo=IST_TZ)
    t_dt = datetime(2026, 12, 3, 15, 30, tzinfo=IST_TZ)

    for label, rows, expected_status, expected_complete in [
        ("complete", full_5m, ARCHIVE_STATUS_COMPLETE, True),
        ("missing_open", missing_open, ARCHIVE_STATUS_PARTIAL, False),
        ("missing_close", missing_close, ARCHIVE_STATUS_PARTIAL, False),
        ("gap", with_gap, ARCHIVE_STATUS_PARTIAL, False),
        ("no_trade_empty", [], ARCHIVE_STATUS_UNKNOWN, False),
    ]:
        sdk = FakeKiteSDK(candles_by_token={(100003, "5minute"): rows})
        client = KiteClientWrapper(kite_client=sdk, sleeper=lambda _: None)
        dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / label / "master"))
        nse = dl.download_snapshot("NSE", snap_date=date(2026, 11, 27))
        nfo = dl.download_snapshot("NFO", snap_date=date(2026, 11, 27))
        reg = InstrumentRegistry(str(tmp_path / label / "reg.sqlite3"))
        rep = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse, nfo_snapshot=nfo, registry=reg)
        hist = KiteHistoricalDataClient(client=client, registry=reg, calendar=cal)
        arch = OptionContractArchive(archive_db_path=str(tmp_path / label / "arch.sqlite3"), registry=reg, historical_client=hist, calendar=cal)
        nifty_ce = [o for o in rep.options if o.canonical_symbol == "NIFTY26D0324500CE"]
        out = arch.archive_contracts(nifty_ce, interval="5minute", from_datetime=f_dt, to_datetime=t_dt)
        assert out[0]["coverage_status"] == expected_status, label
        assert out[0]["final_session_archived"] is expected_complete, label
        arch.close()
        reg.close()

    # Provider error -> UNAVAILABLE
    def _boom(*_a):
        raise KiteAdapterError("upstream unavailable")

    sdk_err = FakeKiteSDK(candles_by_token={(100003, "5minute"): _boom})
    c_err = KiteClientWrapper(kite_client=sdk_err, max_retries=0, sleeper=lambda _: None)
    dl_err = InstrumentMasterDownloader(client=c_err, root_dir=str(tmp_path / "err" / "master"))
    nse = dl_err.download_snapshot("NSE", snap_date=date(2026, 11, 27))
    nfo = dl_err.download_snapshot("NFO", snap_date=date(2026, 11, 27))
    reg_err = InstrumentRegistry(str(tmp_path / "err" / "reg.sqlite3"))
    rep_err = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse, nfo_snapshot=nfo, registry=reg_err)
    hist_err = KiteHistoricalDataClient(client=c_err, registry=reg_err, calendar=cal)
    arch_err = OptionContractArchive(archive_db_path=str(tmp_path / "err" / "arch.sqlite3"), registry=reg_err, historical_client=hist_err, calendar=cal)
    nifty_ce = [o for o in rep_err.options if o.canonical_symbol == "NIFTY26D0324500CE"]
    out_err = arch_err.archive_contracts(nifty_ce, interval="5minute", from_datetime=f_dt, to_datetime=t_dt)
    assert out_err[0]["coverage_status"] == ARCHIVE_STATUS_UNAVAILABLE
    arch_err.close()
    reg_err.close()


def test_archive_strict_scope_and_all_supported_intervals(tmp_path):
    from datetime import timedelta
    from ml_data.instruments import AssetClass, ContractType, Market, OptionRight, Segment

    # 1. Policy rejects non-NIFTY/BANKNIFTY underlyings
    with pytest.raises(KiteInputError):
        ContractSelectionPolicy(underlyings=("FINNIFTY",), allow_unbounded=True)

    sdk = FakeKiteSDK()
    client = KiteClientWrapper(kite_client=sdk, sleeper=lambda _: None)
    dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / "scope" / "master"))
    nse = dl.download_snapshot("NSE", snap_date=date(2026, 11, 27))
    nfo = dl.download_snapshot("NFO", snap_date=date(2026, 11, 27))
    reg = InstrumentRegistry(str(tmp_path / "scope" / "reg.sqlite3"))
    rep = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse, nfo_snapshot=nfo, registry=reg)
    cal = NSECalendar(verified_years=frozenset({2026}))
    hist = KiteHistoricalDataClient(client=client, registry=reg, calendar=cal)
    arch = OptionContractArchive(
        archive_db_path=str(tmp_path / "scope" / "arch.sqlite3"),
        registry=reg,
        historical_client=hist,
        calendar=cal,
    )

    f_dt = datetime(2026, 12, 3, 9, 15, tzinfo=IST_TZ)
    t_dt = datetime(2026, 12, 3, 15, 30, tzinfo=IST_TZ)

    # 2. Expired contract rejected by select_contracts when as_of_date > expiry_date
    pol = ContractSelectionPolicy(underlyings=("NIFTY",), include_expiries=[date(2026, 12, 3)])
    assert arch.select_contracts(pol, as_of_date=date(2026, 12, 4)) == []

    # 3. Mismatched underlying_instrument_id rejected in archive_contracts
    nifty_ce = next(o for o in rep.options if o.canonical_symbol == "NIFTY26D0324500CE")
    bank_idx = next(i for i in rep.indices if i.canonical_symbol == "BANKNIFTY")
    mismatched = Instrument.from_dict({**nifty_ce.to_dict(), "instrument_id": "", "underlying_instrument_id": bank_idx.instrument_id})
    with pytest.raises(KiteInputError):
        arch.archive_contracts([mismatched], interval="5minute", from_datetime=f_dt, to_datetime=t_dt)

    # 4. Out-of-scope FINNIFTY option rejected in archive_contracts
    finnifty_opt = Instrument.from_dict({
        **nifty_ce.to_dict(),
        "instrument_id": "",
        "canonical_symbol": "FINNIFTY26DEC23500CE",
        "trading_symbol": "FINNIFTY26DEC23500CE",
    })
    with pytest.raises(KiteInputError):
        arch.archive_contracts([finnifty_opt], interval="5minute", from_datetime=f_dt, to_datetime=t_dt)
    arch.close()
    reg.close()

    # 5. All 7 intervals including truncated final buckets (10m=38, 30m=13, 60m=7)
    expected_counts = {
        "minute": 375,
        "3minute": 125,
        "5minute": 75,
        "10minute": 38,
        "15minute": 25,
        "30minute": 13,
        "60minute": 7,
    }
    for iv, mins in [("minute", 1), ("3minute", 3), ("5minute", 5), ("10minute", 10), ("15minute", 15), ("30minute", 30), ("60minute", 60)]:
        cnt = expected_counts[iv]
        rows = []
        for k in range(cnt):
            ts = f_dt + timedelta(minutes=mins * k)
            rows.append([ts.isoformat(), 120.0, 121.0, 119.5, 120.5, 1000, 50000])
        sdk_iv = FakeKiteSDK(candles_by_token={(100003, iv): rows})
        c_iv = KiteClientWrapper(kite_client=sdk_iv, sleeper=lambda _: None)
        dl_iv = InstrumentMasterDownloader(client=c_iv, root_dir=str(tmp_path / f"iv_{iv}" / "master"))
        nse_i = dl_iv.download_snapshot("NSE", snap_date=date(2026, 11, 27))
        nfo_i = dl_iv.download_snapshot("NFO", snap_date=date(2026, 11, 27))
        reg_i = InstrumentRegistry(str(tmp_path / f"iv_{iv}" / "reg.sqlite3"))
        rep_i = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse_i, nfo_snapshot=nfo_i, registry=reg_i)
        hist_i = KiteHistoricalDataClient(client=c_iv, registry=reg_i, calendar=cal)
        arch_i = OptionContractArchive(archive_db_path=str(tmp_path / f"iv_{iv}" / "arch.sqlite3"), registry=reg_i, historical_client=hist_i, calendar=cal)
        opt_i = [o for o in rep_i.options if o.canonical_symbol == "NIFTY26D0324500CE"]
        res_i = arch_i.archive_contracts(opt_i, interval=iv, from_datetime=f_dt, to_datetime=t_dt)
        assert res_i[0]["coverage_status"] == ARCHIVE_STATUS_COMPLETE, iv
        assert res_i[0]["final_session_archived"] is True, iv
        assert res_i[0]["missing_count"] == 0, iv
        arch_i.close()
        reg_i.close()
