"""Tests for AlpacaCoveragePreflight equity/option coverage accuracy, pagination, and entitlements."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ml_data.instruments import InstrumentRegistry
from ml_data.us import (
    AlpacaAssetsDiscovery,
    AlpacaCoveragePreflight,
    AlpacaDataClient,
    AlpacaHTTPResponse,
    AlpacaHistoricalOptions,
    AlpacaHistoricalStocks,
    AlpacaOptionsContractDiscovery,
    AlpacaRateLimiter,
    NY_TZ,
    USCalendar,
)
from ml_data.tests.us.fixtures import FakeAlpacaTransport, TEST_CRED


def test_coverage_preflight_entitlements_and_empty_vs_verified(tmp_path):
    tr = FakeAlpacaTransport(block_sip=True, block_opra=True)
    client = AlpacaDataClient(credential=TEST_CRED, transport=tr)
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))

    assets = AlpacaAssetsDiscovery(client=client, raw_root=str(tmp_path / "raw"), manifest_root=str(tmp_path / "man"))
    assets.discover(snapshot=assets.download_snapshot(snap_date=date(2026, 11, 27)), registry=reg)
    AlpacaOptionsContractDiscovery(client=client, raw_root=str(tmp_path / "raw_o"), manifest_root=str(tmp_path / "man")).discover_and_map(
        registry=reg, underlying_symbols=["AAPL"]
    )

    cal = USCalendar(verified_years=frozenset({2026}))
    stocks = AlpacaHistoricalStocks(client=client, registry=reg, calendar=cal)
    opts = AlpacaHistoricalOptions(client=client, registry=reg)
    pre = AlpacaCoveragePreflight(stocks_client=stocks, options_client=opts, registry=reg, calendar=cal)

    s = datetime(2026, 11, 25, 9, 30, tzinfo=NY_TZ)
    e = datetime(2026, 11, 25, 16, 0, tzinfo=NY_TZ)

    # 1 candle in a full-day range MUST be PARTIAL_DATA, not VERIFIED_WITH_DATA
    rep_iex = pre.check_equities(["AAPL", "SPY", "UNKNOWN_SYM"], start=s, end=e, feed="iex", timeframes=("5Min",))
    assert rep_iex[0]["status"] == "PARTIAL_DATA"
    assert rep_iex[0]["range_covered"] is False
    assert rep_iex[0]["missing_count"] > 0
    assert rep_iex[1]["status"] == "EMPTY_RESPONSE"
    assert rep_iex[2]["status"] == "UNSUPPORTED"

    # SIP blocked on Basic plan
    rep_sip = pre.check_equities(["AAPL"], start=s, end=e, feed="sip", timeframes=("5Min",))
    assert rep_sip[0]["status"] == "BLOCKED_BY_SUBSCRIPTION"

    # Options indicative sparse coverage -> UNKNOWN (never VERIFIED_WITH_DATA); OPRA -> BLOCKED_BY_SUBSCRIPTION
    occ = "AAPL261218C00200000"
    rep_ind = pre.check_options([occ], start=s, end=e, feed="indicative")
    assert rep_ind[0]["status"] == "UNKNOWN"
    assert rep_ind[0]["range_covered"] is False
    rep_opra = pre.check_options([occ], start=s, end=e, feed="opra")
    assert rep_opra[0]["status"] == "BLOCKED_BY_SUBSCRIPTION"
    reg.close()


def test_equity_and_option_coverage_boundaries_holidays_and_pagination(tmp_path):
    # Full 15-minute window 09:30-09:45 -> 3 bars: 09:30, 09:35, 09:40
    s = datetime(2026, 11, 25, 9, 30, tzinfo=NY_TZ)
    e = datetime(2026, 11, 25, 9, 45, tzinfo=NY_TZ)
    full_bars = [
        {"t": (s + timedelta(minutes=5 * i)).isoformat(), "o": 200.0, "h": 201.0, "l": 199.5, "c": 200.5, "v": 100}
        for i in range(3)
    ]

    def _tr(method, url, headers, params, timeout):
        if url.endswith("/v2/assets"):
            return AlpacaHTTPResponse(200, [
                {"id": "a1", "symbol": "AAPL", "exchange": "NASDAQ", "status": "active", "tradable": True},
                {"id": "a2", "symbol": "MSFT", "exchange": "NASDAQ", "status": "active", "tradable": True},
                {"id": "a3", "symbol": "NVDA", "exchange": "NASDAQ", "status": "active", "tradable": True},
                {"id": "a4", "symbol": "QQQ", "exchange": "NASDAQ", "status": "active", "tradable": True},
            ], {})
        sym = str((params or {}).get("symbols", ""))
        if sym == "AAPL":
            return AlpacaHTTPResponse(200, {"bars": {"AAPL": full_bars}, "next_page_token": None}, {})
        if sym == "MSFT":
            return AlpacaHTTPResponse(200, {"bars": {"MSFT": full_bars[1:]}, "next_page_token": None}, {})  # missing open
        if sym == "NVDA":
            return AlpacaHTTPResponse(200, {"bars": {"NVDA": full_bars[:-1]}, "next_page_token": None}, {})  # missing close
        if sym == "QQQ":
            return AlpacaHTTPResponse(200, {"bars": {"QQQ": [full_bars[0], full_bars[2]]}, "next_page_token": None}, {})  # internal gap
        return AlpacaHTTPResponse(200, {}, {})

    client = AlpacaDataClient(credential=TEST_CRED, transport=_tr, rate_limiter=AlpacaRateLimiter(requests_per_minute=6000, sleeper=lambda _: None))
    reg = InstrumentRegistry(":memory:")
    disc = AlpacaAssetsDiscovery(client=client, raw_root=str(tmp_path / "r"), manifest_root=str(tmp_path / "m"))
    disc.discover(snapshot=disc.download_snapshot(dry_run=True), registry=reg, dry_run=False)

    cal = USCalendar(holidays=frozenset({date(2026, 11, 26)}), verified_years=frozenset({2026}))
    pre = AlpacaCoveragePreflight(
        stocks_client=AlpacaHistoricalStocks(client=client, registry=reg, calendar=cal),
        options_client=AlpacaHistoricalOptions(client=client, registry=reg),
        registry=reg,
        calendar=cal,
    )
    rep = pre.check_equities(["AAPL", "MSFT", "NVDA", "QQQ"], start=s, end=e, feed="iex", timeframes=("5Min",))
    assert rep[0]["status"] == "VERIFIED_WITH_DATA" and rep[0]["range_covered"] is True
    assert rep[1]["status"] == "PARTIAL_DATA" and rep[1]["missing_count"] == 1
    assert rep[2]["status"] == "PARTIAL_DATA" and rep[2]["missing_count"] == 1
    assert rep[3]["status"] == "PARTIAL_DATA" and rep[3]["missing_count"] == 1

    # Unverified calendar year -> UNVERIFIED_CALENDAR
    pre_unv = AlpacaCoveragePreflight(
        stocks_client=AlpacaHistoricalStocks(client=client, registry=reg, calendar=USCalendar()),
        options_client=AlpacaHistoricalOptions(client=client, registry=reg),
        registry=reg,
        calendar=USCalendar(),
    )
    assert pre_unv.check_equities(["AAPL"], start=s, end=e, feed="iex", timeframes=("5Min",))[0]["status"] == "UNVERIFIED_CALENDAR"
    reg.close()
