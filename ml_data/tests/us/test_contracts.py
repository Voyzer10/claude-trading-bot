"""Tests for AlpacaOptionsContractDiscovery, deliverables, adjusted options, index options, and AlpacaUSAdapter."""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest

from ml_data.adapters.alpaca import AlpacaUSAdapter
from ml_data.instruments import InstrumentRegistry, OptionRight, SettlementType
from ml_data.us import (
    AlpacaAssetsDiscovery,
    AlpacaDataClient,
    AlpacaHTTPResponse,
    AlpacaIndexDiscovery,
    AlpacaInputError,
    AlpacaOptionsContractDiscovery,
)
from ml_data.tests.us.fixtures import FakeAlpacaTransport, TEST_CRED


def test_options_contract_discovery_pagination_deliverables_and_adapter(tmp_path):
    tr = FakeAlpacaTransport()
    client = AlpacaDataClient(credential=TEST_CRED, transport=tr)
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))

    assets = AlpacaAssetsDiscovery(client=client, raw_root=str(tmp_path / "raw"), manifest_root=str(tmp_path / "man"))
    assets.discover(snapshot=assets.download_snapshot(snap_date=date(2026, 11, 27)), registry=reg)
    AlpacaIndexDiscovery(client=client, raw_root=str(tmp_path / "raw_i"), manifest_root=str(tmp_path / "man")).discover_indices(registry=reg)

    opt_disc = AlpacaOptionsContractDiscovery(
        client=client,
        raw_root=str(tmp_path / "raw_opt"),
        manifest_root=str(tmp_path / "man"),
    )
    rep = opt_disc.discover_and_map(
        registry=reg,
        status="active",
        expiration_date_gte=date(2026, 12, 1),
        expiration_date_lte=date(2026, 12, 31),
    )
    assert rep.pages_fetched == 2
    assert rep.pagination_complete is True
    assert rep.snapshot_path is not None and os.path.isfile(rep.snapshot_path)
    assert len(rep.contracts) == 4

    # Standard AAPL (multiplier=100, size=100) vs adjusted AAPL1 (multiplier=100, size=50)
    std = next(c for c in rep.contracts if c.canonical_symbol == "AAPL261218C00200000")
    adj = next(c for c in rep.contracts if c.canonical_symbol == "AAPL1261218C00200000")
    assert std.instrument_id != adj.instrument_id
    assert std.contract_multiplier == Decimal("100")
    assert adj.contract_multiplier == Decimal("100")
    assert std.deliverable_shares == Decimal("100")
    assert adj.deliverable_shares == Decimal("50")
    assert adj.deliverable_type == "ADJUSTED"
    assert std.last_trade_date is None
    assert all(m.provider_feed is None for m in rep.mappings)

    # European cash-settled SPX index option
    spx_opt = next(c for c in rep.contracts if c.canonical_symbol == "SPX261218C06000000")
    assert spx_opt.exercise_style == "EUROPEAN"
    assert spx_opt.settlement_type == SettlementType.CASH
    assert spx_opt.option_right == OptionRight.CALL

    # Provider-independent Adapter interface (dry_run=False persists snapshot)
    adapter = AlpacaUSAdapter(client=client, assets_discovery=assets, options_discovery=opt_disc, dry_run=False)
    assert len(adapter.fetch_equities()) == 5
    assert len(adapter.fetch_indices()) == 1
    assert len(adapter.fetch_options("AAPL")) == 2
    assert adapter.fetch_futures("ES") == []
    reg.close()


def test_option_contract_multiplier_deliverable_and_validation_errors(tmp_path):
    base_c = {
        "id": "c1",
        "symbol": "AAPL261218C00200000",
        "status": "active",
        "expiration_date": "2026-12-18",
        "underlying_symbol": "AAPL",
        "type": "call",
        "style": "american",
        "strike_price": "200",
        "multiplier": "100",
        "size": "100",
        "deliverables": [{"type": "equity", "symbol": "AAPL", "amount": "100"}],
    }

    def _run_with_contract(contract_dict):
        def _tr(method, url, headers, params, timeout):
            if url.endswith("/v2/assets"):
                return AlpacaHTTPResponse(200, [{"id": "a1", "symbol": "AAPL", "exchange": "NASDAQ", "status": "active", "tradable": True}], {})
            return AlpacaHTTPResponse(200, {"option_contracts": [contract_dict], "next_page_token": None}, {})

        c = AlpacaDataClient(credential=TEST_CRED, transport=_tr)
        reg = InstrumentRegistry(":memory:")
        disc = AlpacaAssetsDiscovery(client=c, raw_root=str(tmp_path / "r"), manifest_root=str(tmp_path / "m"))
        disc.discover(snapshot=disc.download_snapshot(dry_run=True), registry=reg, dry_run=False)
        rep = AlpacaOptionsContractDiscovery(client=c).discover_and_map(registry=reg, dry_run=True)
        reg.close()
        return rep

    # Mixed cash + equity deliverables
    mixed = {
        **base_c,
        "symbol": "AAPL2261218C00200000",
        "size": "50",
        "deliverables": [{"type": "equity", "symbol": "AAPL", "amount": "50"}, {"type": "cash", "symbol": "USD", "amount": "15"}],
    }
    rep_m = _run_with_contract(mixed)
    assert rep_m.contracts[0].deliverable_type == "MIXED"
    assert rep_m.contracts[0].contract_multiplier == Decimal("100")

    # Missing multiplier, invalid size, invalid option type, invalid exercise style
    for bad in (
        {k: v for k, v in base_c.items() if k != "multiplier"},
        {**base_c, "size": "-5"},
        {**base_c, "type": "unknown"},
        {**base_c, "style": "bermudan"},
    ):
        with pytest.raises(AlpacaInputError):
            _run_with_contract(bad)
