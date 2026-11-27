"""Tests for AlpacaUSLiveBridge: stock JSON, updated bar reconciliation, option MessagePack, and limits."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from ml_data.instruments import InstrumentRegistry
from ml_data.us import (
    AlpacaAssetsDiscovery,
    AlpacaDataClient,
    AlpacaInputError,
    AlpacaOptionsContractDiscovery,
    AlpacaUSLiveBridge,
    UTC_TZ,
)
from ml_data.tests.us.fixtures import FakeAlpacaTransport, TEST_CRED, build_option_msgpack


def test_live_bridge_stock_updated_bar_and_option_msgpack(tmp_path):
    tr = FakeAlpacaTransport()
    client = AlpacaDataClient(credential=TEST_CRED, transport=tr)
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))
    assets = AlpacaAssetsDiscovery(client=client, raw_root=str(tmp_path / "raw"), manifest_root=str(tmp_path / "man"))
    assets.discover(snapshot=assets.download_snapshot(snap_date=date(2026, 11, 27)), registry=reg)
    AlpacaOptionsContractDiscovery(client=client).discover_and_map(registry=reg, underlying_symbols=["AAPL"])

    bridge = AlpacaUSLiveBridge(registry=reg, stock_feed="iex", option_feed="indicative", max_stock_symbols=2)
    assert bridge.stock_ws_url == "wss://stream.data.alpaca.markets/v2/iex"
    assert bridge.option_ws_url == "wss://stream.data.alpaca.markets/v1beta1/indicative"

    bridge.subscribe_stocks(["AAPL"])
    # Stock minute bar followed by updated bar ('u') at same timestamp
    evs1 = bridge.on_stock_message(json.dumps([
        {"T": "b", "S": "AAPL", "t": "2026-11-25T14:30:00Z", "o": 200.0, "h": 201.0, "l": 199.5, "c": 200.5, "v": 1000},
        {"T": "u", "S": "AAPL", "t": "2026-11-25T14:30:00Z", "o": 200.0, "h": 201.5, "l": 199.5, "c": 201.2, "v": 1250},
    ]))
    assert len(evs1) == 2
    assert evs1[1].event_type == "updated_bar"
    assert evs1[1].revision_count == 1
    reconciled = bridge.get_reconciled_bar(evs1[0].instrument_id, datetime(2026, 11, 25, 14, 30, tzinfo=UTC_TZ))
    assert reconciled.close == Decimal("201.2")
    assert reconciled.volume == 1250

    # Option MessagePack decoding & wildcard refusal
    with pytest.raises(AlpacaInputError):
        bridge.subscribe_options(["*"])

    occ = "AAPL261218C00200000"
    bridge.subscribe_options([occ])
    pkt = build_option_msgpack([
        {"T": "q", "S": occ, "t": "2026-11-25T14:30:01Z", "bp": 12.3, "bs": 25, "ap": 12.5, "as": 30},
        {"T": "t", "S": occ, "t": "2026-11-25T14:30:02Z", "p": 12.4, "s": 5},
    ])
    opt_evs = bridge.on_option_message(pkt)
    assert len(opt_evs) == 2
    assert opt_evs[0].bid_price == Decimal("12.3")
    assert opt_evs[0].data_source == "alpaca_ws_options"
    assert opt_evs[1].price == Decimal("12.4")

    # Stock limit enforced
    bridge.subscribe_stocks(["MSFT"])
    with pytest.raises(AlpacaInputError):
        bridge.subscribe_stocks(["SPY"])
    reg.close()
