"""Tests for AlpacaHistoricalStocks and AlpacaHistoricalOptions pagination, adjustments, and checkpoints."""
from __future__ import annotations

from datetime import date, datetime, time as dt_time
from decimal import Decimal

import pytest

from ml_data.instruments import InstrumentRegistry
from ml_data.us import (
    AlpacaAssetsDiscovery,
    AlpacaDataClient,
    AlpacaHistoricalOptions,
    AlpacaHistoricalStocks,
    AlpacaInputError,
    NY_TZ,
    USCalendar,
)
from ml_data.tests.us.fixtures import FakeAlpacaTransport, TEST_CRED


def test_historical_stocks_pagination_adjustments_sessions_and_checkpoints(tmp_path):
    tr = FakeAlpacaTransport()
    client = AlpacaDataClient(credential=TEST_CRED, transport=tr)
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))
    assets = AlpacaAssetsDiscovery(client=client, raw_root=str(tmp_path / "raw"), manifest_root=str(tmp_path / "man"))
    assets.discover(snapshot=assets.download_snapshot(snap_date=date(2026, 11, 27)), registry=reg)

    cal = USCalendar(verified_years=frozenset({2026}))
    hist = AlpacaHistoricalStocks(
        client=client,
        registry=reg,
        calendar=cal,
        checkpoint_dir=str(tmp_path / "ckpts"),
    )
    start = datetime(2026, 11, 25, 9, 30, tzinfo=NY_TZ)
    end = datetime(2026, 11, 25, 16, 0, tzinfo=NY_TZ)

    res_raw = hist.fetch_bars(["AAPL", "MSFT"], timeframe="5Min", start=start, end=end, feed="iex", adjustment="raw")
    assert res_raw.pages_fetched == 2
    assert len(res_raw.bars_by_symbol["AAPL"]) == 1
    assert len(res_raw.bars_by_symbol["MSFT"]) == 1
    assert res_raw.bars_by_symbol["AAPL"][0].session == "REGULAR"
    assert res_raw.bars_by_symbol["AAPL"][0].open == Decimal("200.0")
    assert res_raw.bars_by_symbol["AAPL"][0].adjustment == "raw"

    # Second call with same adjustment hits checkpoint without calling transport
    calls_before = len(tr.calls)
    res_raw_2 = hist.fetch_bars(["AAPL", "MSFT"], timeframe="5Min", start=start, end=end, feed="iex", adjustment="raw")
    assert len(tr.calls) == calls_before
    assert len(res_raw_2.bars_by_symbol["AAPL"]) == 1

    # Different adjustment ('split') MUST NOT reuse 'raw' checkpoint
    res_split = hist.fetch_bars(["AAPL", "MSFT"], timeframe="5Min", start=start, end=end, feed="iex", adjustment="split")
    assert len(tr.calls) > calls_before
    assert res_split.bars_by_symbol["AAPL"][0].adjustment == "split"
    reg.close()


def test_historical_options_bars_trades_quotes_snapshots_and_limits(tmp_path):
    tr = FakeAlpacaTransport()
    client = AlpacaDataClient(credential=TEST_CRED, transport=tr)
    opt_hist = AlpacaHistoricalOptions(client=client)

    s = datetime(2026, 11, 25, 9, 30, tzinfo=NY_TZ)
    e = datetime(2026, 11, 25, 10, 0, tzinfo=NY_TZ)
    sym = "AAPL261218C00200000"

    bars, _ = opt_hist.fetch_bars([sym], timeframe="5Min", start=s, end=e, feed="indicative")
    trades, _ = opt_hist.fetch_trades([sym], start=s, end=e, feed="indicative")
    quotes, _ = opt_hist.fetch_quotes([sym], start=s, end=e, feed="indicative")
    snaps = opt_hist.fetch_snapshots([sym], feed="indicative")

    assert bars[sym][0].close == Decimal("12.4")
    assert trades[sym][0].price == Decimal("12.4")
    assert quotes[sym][0].bid_price == Decimal("12.3")
    assert snaps[sym].greeks["delta"] == 0.55

    # Max 100 option symbols enforced
    with pytest.raises(AlpacaInputError):
        opt_hist.fetch_bars([f"OPT{i}" for i in range(101)], start=s, end=e)

    # Pre-Feb 2024 option history completely before 2024-02-01 rejected
    with pytest.raises(AlpacaInputError):
        opt_hist.fetch_bars([sym], start=datetime(2024, 1, 1, 9, 30, tzinfo=NY_TZ), end=datetime(2024, 1, 2, 16, 0, tzinfo=NY_TZ))

    # Partial pre-Feb 2024 span reports unavailable_pre_feb_2024=True
    bars_partial, _ = opt_hist.fetch_bars(
        [sym],
        timeframe="5Min",
        start=datetime(2024, 1, 15, 9, 30, tzinfo=NY_TZ),
        end=datetime(2026, 11, 25, 10, 0, tzinfo=NY_TZ),
        feed="indicative",
    )
    assert opt_hist.last_fetch_stats["unavailable_pre_feb_2024"] is True
    assert len(bars_partial[sym]) == 1


def test_historical_option_validation_dedup_oor_and_malformed():
    from ml_data.us import AlpacaAdapterError, AlpacaHTTPResponse

    sym = "AAPL261218C00200000"
    s = datetime(2026, 11, 25, 9, 30, tzinfo=NY_TZ)
    e = datetime(2026, 11, 25, 10, 0, tzinfo=NY_TZ)

    def _tr_dup_oor(method, url, headers, params, timeout):
        if url.endswith("/v1beta1/options/bars"):
            return AlpacaHTTPResponse(200, {
                "bars": {
                    sym: [
                        {"t": "2026-11-25T14:35:00Z", "o": 12.0, "h": 12.5, "l": 11.8, "c": 12.4, "v": 10},
                        {"t": "2026-11-25T14:30:00Z", "o": 11.5, "h": 12.0, "l": 11.4, "c": 11.9, "v": 20},
                        {"t": "2026-11-25T14:30:00Z", "o": 11.5, "h": 12.0, "l": 11.4, "c": 11.9, "v": 20},  # dup
                        {"t": "2026-11-25T16:00:00Z", "o": 12.0, "h": 12.5, "l": 11.8, "c": 12.4, "v": 10},  # oor
                    ]
                }
            }, {})
        return AlpacaHTTPResponse(200, {}, {})

    oh = AlpacaHistoricalOptions(client=AlpacaDataClient(credential=TEST_CRED, transport=_tr_dup_oor))
    bars, _ = oh.fetch_bars([sym], timeframe="5Min", start=s, end=e)
    assert len(bars[sym]) == 2
    assert bars[sym][0].ts_utc < bars[sym][1].ts_utc  # sorted chronologically
    assert oh.last_fetch_stats["duplicates_dropped"] == 1
    assert oh.last_fetch_stats["out_of_range_dropped"] == 1

    # Malformed OHLC rejected
    def _tr_bad_ohlc(method, url, headers, params, timeout):
        return AlpacaHTTPResponse(200, {
            "bars": {sym: [{"t": "2026-11-25T14:30:00Z", "o": 12.0, "h": 11.0, "l": 11.5, "c": 12.0, "v": 10}]}
        }, {})

    oh_bad = AlpacaHistoricalOptions(client=AlpacaDataClient(credential=TEST_CRED, transport=_tr_bad_ohlc))
    with pytest.raises(AlpacaAdapterError):
        oh_bad.fetch_bars([sym], timeframe="5Min", start=s, end=e)
