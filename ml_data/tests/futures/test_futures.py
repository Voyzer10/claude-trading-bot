"""Tests for US Futures (Databento / CME Globex) provider evaluation, definitions, discovery, historical, continuous, and preflight."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from ml_data.adapters.databento import DatabentoFuturesAdapter
from ml_data.futures import (
    CMEGlobexCalendar,
    CME_TZ,
    ContinuousContractBuilder,
    DatabentoCredential,
    DatabentoHistoricalClient,
    DatabentoHistoricalFutures,
    DatabentoHTTPResponse,
    FuturesBlockedEndpointError,
    FuturesContractDiscovery,
    FuturesCoveragePreflight,
    FuturesInputError,
    PROVIDER_EVALUATIONS,
    inspect_databento_credentials,
)
from ml_data.instruments import AssetClass, InstrumentRegistry, InstrumentStatus, Market, Segment

TEST_DB_CRED = DatabentoCredential(api_key="db-test-secret-0001")

SAMPLE_DEFS = [
    {
        "dataset": "GLBX.MDP3", "publisher_id": 1, "venue": "GLBX", "exchange": "CME",
        "raw_symbol": "ESZ6", "instrument_id": 42001, "asset": "ES",
        "expiration": "2026-12-18", "min_price_increment": "0.25", "unit_of_measure_qty": "50",
        "currency": "USD", "settlement_type": "CASH", "ts_event": "2026-01-02T00:00:00Z",
    },
    {
        "dataset": "GLBX.MDP3", "publisher_id": 1, "venue": "GLBX", "exchange": "CME",
        "raw_symbol": "ESH7", "instrument_id": 42002, "asset": "ES",
        "expiration": "2027-03-19", "min_price_increment": "0.25", "unit_of_measure_qty": "50",
        "currency": "USD", "settlement_type": "CASH", "ts_event": "2026-01-02T00:00:00Z",
    },
    {
        "dataset": "GLBX.MDP3", "publisher_id": 1, "venue": "GLBX", "exchange": "CME",
        "raw_symbol": "MESZ6", "instrument_id": 42003, "asset": "MES",
        "expiration": "2026-12-18", "min_price_increment": "0.25", "unit_of_measure_qty": "5",
        "currency": "USD", "settlement_type": "CASH", "ts_event": "2026-01-02T00:00:00Z",
    },
    {
        "dataset": "GLBX.MDP3", "publisher_id": 1, "venue": "GLBX", "exchange": "CME",
        "raw_symbol": "CLZ6", "instrument_id": 42099, "asset": "CL",  # commodity: excluded from initial scope
        "expiration": "2026-11-20", "min_price_increment": "0.01", "unit_of_measure_qty": "1000",
        "currency": "USD", "settlement_type": "PHYSICAL",
    },
]


def test_databento_security_evaluation_and_preflight(monkeypatch):
    assert PROVIDER_EVALUATIONS["databento"].selected_as_initial is True
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    assert inspect_databento_credentials()["DATABENTO_API_KEY"] == "ABSENT"

    # Unapproved host and non-GET blocked
    with pytest.raises(FuturesBlockedEndpointError):
        DatabentoHistoricalClient(credential=TEST_DB_CRED, base_url="https://evil.example.com")
    c_no_tr = DatabentoHistoricalClient(credential=TEST_DB_CRED)
    with pytest.raises(FuturesBlockedEndpointError):
        c_no_tr.request("/v0/timeseries.get_range")  # billable live timeseries blocked by default

    # Mocked non-billable preflight
    def _tr(method, url, headers, params, timeout):
        if url.endswith("list_datasets"):
            return DatabentoHTTPResponse(200, ["GLBX.MDP3"], {})
        if url.endswith("list_schemas"):
            return DatabentoHTTPResponse(200, ["definition", "ohlcv-1m", "trades", "statistics"], {})
        return DatabentoHTTPResponse(200, {"start": "2017-05-21", "end": "2026-11-27"}, {})

    pre = FuturesCoveragePreflight(client=DatabentoHistoricalClient(credential=TEST_DB_CRED, transport=_tr))
    res = pre.run_preflight()
    assert res["status"] == "VERIFIED" and res["dataset_available"] is True


def test_futures_discovery_historical_globex_and_continuous(tmp_path):
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))
    disc = FuturesContractDiscovery(
        raw_root=str(tmp_path / "raw"),
        manifest_root=str(tmp_path / "man"),
    )
    rep = disc.discover_from_definitions(SAMPLE_DEFS, registry=reg, as_of_date=date(2026, 11, 28))
    assert len(rep.contracts) == 3  # CLZ6 skipped
    assert len(rep.skipped) == 1
    esz6 = next(c for c in rep.contracts if c.canonical_symbol == "ESZ6")
    assert esz6.market == Market.US and esz6.segment == Segment.US_FUTURES
    assert esz6.contract_multiplier == Decimal("50") and esz6.tick_size == Decimal("0.25")
    assert esz6.instrument_status == InstrumentStatus.ACTIVE

    # Historical OHLCV + Globex RTH / Maintenance break classification
    def _hist_tr(method, url, headers, params, timeout):
        return DatabentoHTTPResponse(200, [
            {"ts_event": "2026-11-25T15:00:00Z", "raw_symbol": "ESZ6", "instrument_id": 42001, "open": "6000.00", "high": "6005.00", "low": "5999.50", "close": "6004.00", "volume": 1200, "open_interest": 250000},
            {"ts_event": "2026-11-25T22:15:00Z", "raw_symbol": "ESZ6", "instrument_id": 42001, "open": "6004.00", "high": "6004.00", "low": "6004.00", "close": "6004.00", "volume": 0, "open_interest": 250000},  # 16:15 CT maintenance break
            {"ts_event": "2026-11-26T15:00:00Z", "raw_symbol": "ESH7", "instrument_id": 42002, "open": "6050.00", "high": "6052.00", "low": "6049.00", "close": "6051.00", "volume": 900, "open_interest": 180000},
        ], {})

    cal = CMEGlobexCalendar(verified_years=frozenset({2026}))
    hist = DatabentoHistoricalFutures(
        client=DatabentoHistoricalClient(credential=TEST_DB_CRED, transport=_hist_tr),
        registry=reg,
        calendar=cal,
    )
    res_es = hist.fetch_ohlcv(["ESZ6"], start=datetime(2026, 11, 25, 0, 0, tzinfo=CME_TZ), end=datetime(2026, 11, 25, 23, 59, tzinfo=CME_TZ))
    assert res_es.bars[0].session == "RTH"
    assert res_es.bars[1].session == "MAINTENANCE_BREAK"

    res_h7 = hist.fetch_ohlcv(["ESH7"], start=datetime(2026, 11, 26, 0, 0, tzinfo=CME_TZ), end=datetime(2026, 11, 26, 23, 59, tzinfo=CME_TZ))
    cont = ContinuousContractBuilder().build(
        product_root="ES",
        bars_by_contract={"ESZ6": res_es.bars, "ESH7": res_h7.bars},
        roll_schedule=[(date(2026, 11, 25), "ESZ6"), (date(2026, 11, 26), "ESH7")],
        roll_rule="calendar",
        adjustment_policy="panama_back_adjusted",
    )
    assert len(cont) == 3
    # Raw prices preserved; ESZ6 back-adjusted by +47.00 (6051 - 6004)
    assert cont[0].raw_close == Decimal("6004.00")
    assert cont[0].adjusted_close == Decimal("6051.00")
    assert cont[0].actual_instrument_id == esz6.instrument_id

    # OI roll without OI raises
    with pytest.raises(FuturesInputError):
        ContinuousContractBuilder().build(
            product_root="ES",
            bars_by_contract={"ESZ6": []},
            roll_schedule=[(date(2026, 11, 25), "ESZ6")],
            roll_rule="open_interest",
        )

    adapter = DatabentoFuturesAdapter(definitions=SAMPLE_DEFS)
    assert len(adapter.fetch_futures("ES")) == 2
    reg.close()
