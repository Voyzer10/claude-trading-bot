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


def test_opra_separated_from_exchange_identity_and_stable_across_feeds(tmp_path):
    from datetime import datetime
    from ml_data.instruments import AssetClass, Market, build_instrument_id
    from ml_data.us import (
        AlpacaHistoricalOptions,
        AlpacaUSLiveBridge,
        CANONICAL_US_OPTIONS_EXCHANGE,
        NY_TZ,
        UTC_TZ,
    )
    from ml_data.tests.us.fixtures import OPTION_CONTRACTS_PAGE1, build_option_msgpack

    tr = FakeAlpacaTransport(block_opra=False)
    client = AlpacaDataClient(credential=TEST_CRED, transport=tr)
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))

    assets = AlpacaAssetsDiscovery(client=client, raw_root=str(tmp_path / "raw_a"), manifest_root=str(tmp_path / "man"))
    assets.discover(snapshot=assets.download_snapshot(snap_date=date(2026, 11, 27)), registry=reg)
    AlpacaIndexDiscovery(client=client, raw_root=str(tmp_path / "raw_i"), manifest_root=str(tmp_path / "man")).discover_indices(registry=reg)

    opt_disc = AlpacaOptionsContractDiscovery(
        client=client,
        raw_root=str(tmp_path / "raw_opt"),
        manifest_root=str(tmp_path / "man"),
    )
    rep = opt_disc.discover_and_map(
        registry=reg,
        expiration_date_gte=date(2026, 12, 1),
        expiration_date_lte=date(2026, 12, 31),
        snap_date=date(2026, 11, 27),
    )

    # OPRA is never assigned as exchange or exchange_mic; canonical US_OPTIONS namespace is used instead.
    for inst, mp in zip(rep.contracts, rep.mappings):
        assert inst.exchange == CANONICAL_US_OPTIONS_EXCHANGE
        assert inst.exchange_mic is None
        assert inst.exchange_mic != "OPRA"
        assert inst.provider_feed == "opra"
        assert inst.metadata["provider_feed"] == "opra"
        assert inst.metadata["reporting_processor"] == "OPRA"
        assert inst.metadata["multi_listed"] is True
        assert mp.provider_exchange == "OPRA"
        assert mp.provider_feed is None

    # Underlying equity, standard option, and adjusted option remain distinct in Identity v3.
    aapl = next(i for i in reg.list_by_asset_class(AssetClass.EQUITY) if i.canonical_symbol == "AAPL")
    std_opt = next(c for c in rep.contracts if c.canonical_symbol == "AAPL261218C00200000")
    adj_opt = next(c for c in rep.contracts if c.canonical_symbol == "AAPL1261218C00200000")
    assert len({aapl.instrument_id, std_opt.instrument_id, adj_opt.instrument_id}) == 3

    # Even if raw payload explicitly sends exchange='OPRA', exchange_mic='OPRA', OPRA is stripped from exchange_mic
    # and the canonical identity remains identical across feed representations.
    raw_with_opra = [{**OPTION_CONTRACTS_PAGE1[0], "exchange": "OPRA", "exchange_mic": "OPRA"}]

    def _tr_opra_tagged(method, url, headers, params, timeout):
        return AlpacaHTTPResponse(200, {"option_contracts": raw_with_opra, "next_page_token": None}, {})

    opt_disc2 = AlpacaOptionsContractDiscovery(
        client=AlpacaDataClient(credential=TEST_CRED, transport=_tr_opra_tagged),
        raw_root=str(tmp_path / "raw_opt2"),
        manifest_root=str(tmp_path / "man2"),
    )
    rep2 = opt_disc2.discover_and_map(
        registry=reg,
        underlying_symbols=["AAPL"],
        expiration_date_gte=date(2026, 12, 1),
        expiration_date_lte=date(2026, 12, 31),
    )
    assert rep2.contracts[0].exchange == CANONICAL_US_OPTIONS_EXCHANGE
    assert rep2.contracts[0].exchange_mic is None
    assert rep2.contracts[0].instrument_id == std_opt.instrument_id
    assert rep2.contracts[0].instrument_id == build_instrument_id(
        market=Market.US,
        asset_class=AssetClass.OPTION,
        exchange=CANONICAL_US_OPTIONS_EXCHANGE,
        canonical_symbol="AAPL261218C00200000",
        underlying_instrument_id=aapl.instrument_id,
        expiry_date=date(2026, 12, 18),
        strike_price=Decimal("200"),
        option_right=OptionRight.CALL,
        deliverable_shares=Decimal("100"),
        deliverable_type="STANDARD",
    )

    # Market-data records preserve active feed ('indicative' / 'opra') while resolving canonical identity.
    opt_hist = AlpacaHistoricalOptions(client=client, registry=reg)
    s_dt = datetime(2026, 11, 25, 9, 30, tzinfo=NY_TZ)
    e_dt = datetime(2026, 11, 25, 10, 0, tzinfo=NY_TZ)
    occ = std_opt.canonical_symbol
    for feed_name in ("indicative", "opra"):
        bars, _ = opt_hist.fetch_bars([occ], start=s_dt, end=e_dt, feed=feed_name)
        trades, _ = opt_hist.fetch_trades([occ], start=s_dt, end=e_dt, feed=feed_name)
        quotes, _ = opt_hist.fetch_quotes([occ], start=s_dt, end=e_dt, feed=feed_name)
        snaps = opt_hist.fetch_snapshots([occ], feed=feed_name)
        assert bars[occ][0].feed == feed_name and bars[occ][0].instrument_id == std_opt.instrument_id
        assert trades[occ][0].feed == feed_name and trades[occ][0].instrument_id == std_opt.instrument_id
        assert quotes[occ][0].feed == feed_name and quotes[occ][0].instrument_id == std_opt.instrument_id
        assert snaps[occ].feed == feed_name and snaps[occ].instrument_id == std_opt.instrument_id

        bridge = AlpacaUSLiveBridge(registry=reg, option_feed=feed_name)
        bridge.subscribe_options([occ])
        evs = bridge.on_option_message(
            build_option_msgpack([{"T": "t", "S": occ, "t": "2026-11-25T14:30:02Z", "p": 12.4, "s": 5}])
        )
        assert evs[0].feed == feed_name
        assert evs[0].instrument_id == std_opt.instrument_id
    reg.close()


def test_contracts_immutable_snapshot_provenance_revisions_and_recovery(monkeypatch, tmp_path):
    import gzip
    import hashlib
    import json
    from ml_data.us import AlpacaAdapterError
    from ml_data.tests.us.fixtures import OPTION_CONTRACTS_PAGE1, OPTION_CONTRACTS_PAGE2

    state = {"rows": list(OPTION_CONTRACTS_PAGE1), "next_tok": "p2"}

    def _tr(method, url, headers, params, timeout):
        p = params or {}
        if p.get("page_token") == "p2":
            return AlpacaHTTPResponse(200, {"option_contracts": OPTION_CONTRACTS_PAGE2, "next_page_token": None}, {})
        return AlpacaHTTPResponse(200, {"option_contracts": state["rows"], "next_page_token": state["next_tok"]}, {})

    client = AlpacaDataClient(credential=TEST_CRED, transport=_tr)
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))
    d0 = date(2026, 11, 27)
    exp_gte = date(2026, 12, 1)
    exp_lte = date(2026, 12, 31)

    opt_disc = AlpacaOptionsContractDiscovery(
        client=client,
        raw_root=str(tmp_path / "raw_opt"),
        manifest_root=str(tmp_path / "man_opt"),
    )

    # 1. Initial snapshot: SHA/file/manifest consistency + separate retrieved_at_utc & filters
    s1 = opt_disc.download_snapshot(
        snap_date=d0,
        expiration_date_gte=exp_gte,
        expiration_date_lte=exp_lte,
    )
    assert s1.revision == 1
    assert s1.pages_fetched == 2
    assert s1.pagination_complete is True
    assert os.path.isfile(s1.raw_gz_path) and os.path.isfile(s1.manifest_path)
    with gzip.open(s1.raw_gz_path, "rt", encoding="utf-8") as fh:
        assert hashlib.sha256(fh.read().encode("utf-8")).hexdigest() == s1.sha256
    with open(s1.manifest_path, encoding="utf-8") as fh:
        m1 = json.load(fh)
    assert m1["sha256"] == s1.sha256
    assert m1["snapshot_file"] == os.path.basename(s1.raw_gz_path)
    assert m1["snapshot_date"] == d0.isoformat()
    assert m1["retrieved_at_utc"] == s1.retrieved_at_utc.isoformat()
    assert m1["pages_fetched"] == 2
    assert m1["pagination_complete"] is True
    assert m1["filters"]["expiration_date_gte"] == exp_gte.isoformat()

    # 2. Repeated identical retrieval (with and without force_refresh) is idempotent
    s1_cached = opt_disc.download_snapshot(snap_date=d0, expiration_date_gte=exp_gte, expiration_date_lte=exp_lte)
    s1_forced_same = opt_disc.download_snapshot(
        snap_date=d0, expiration_date_gte=exp_gte, expiration_date_lte=exp_lte, force_refresh=True
    )
    assert s1_cached.sha256 == s1.sha256 and s1_cached.raw_gz_path == s1.raw_gz_path
    assert s1_forced_same.sha256 == s1.sha256 and s1_forced_same.manifest_path == s1.manifest_path
    assert len(opt_disc.list_snapshots(d0, filters=s1.filters)) == 1

    # 3. Same-day changed retrieval / force_refresh creates new immutable revision & preserves old one
    state["rows"] = [dict(OPTION_CONTRACTS_PAGE1[0], close_price="14.25")]
    rep2 = opt_disc.discover_and_map(
        registry=reg,
        snap_date=d0,
        expiration_date_gte=exp_gte,
        expiration_date_lte=exp_lte,
    )
    assert rep2.snapshot_sha256 != s1.sha256
    assert rep2.snapshot_path != s1.raw_gz_path
    assert rep2.snapshot_revision == 2
    revs = opt_disc.list_snapshots(d0, filters=s1.filters)
    assert len(revs) == 2
    assert revs[0].sha256 == s1.sha256 and os.path.isfile(s1.raw_gz_path) and os.path.isfile(s1.manifest_path)
    assert revs[1].sha256 == rep2.snapshot_sha256 and os.path.isfile(rep2.snapshot_path)

    # Manifest of rev2 strictly matches rev2 gz file
    with gzip.open(rep2.snapshot_path, "rt", encoding="utf-8") as fh:
        assert hashlib.sha256(fh.read().encode("utf-8")).hexdigest() == rep2.snapshot_sha256
    with open(rep2.manifest_path, encoding="utf-8") as fh:
        m2 = json.load(fh)
    assert m2["sha256"] == rep2.snapshot_sha256
    assert m2["snapshot_file"] == os.path.basename(rep2.snapshot_path)

    # 4. Interrupted write recovery: failed manifest write rolls back orphaned gz & leaves no corrupt manifest
    d1 = date(2026, 11, 28)
    monkeypatch.setattr(opt_disc, "_atomic_write_json", lambda *_a, **_kw: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        opt_disc.download_snapshot(snap_date=d1, expiration_date_gte=exp_gte, expiration_date_lte=exp_lte)
    assert opt_disc.load_snapshot(d1, filters=s1.filters) is None
    raw_d1 = tmp_path / "raw_opt" / f"date={d1.isoformat()}"
    man_d1 = tmp_path / "man_opt" / f"date={d1.isoformat()}"
    assert not any(raw_d1.glob("*.json.gz")) if raw_d1.exists() else True
    assert not any(man_d1.glob("*.json")) if man_d1.exists() else True

    # Retry succeeds cleanly after interruption
    monkeypatch.undo()
    s_d1 = opt_disc.download_snapshot(snap_date=d1, expiration_date_gte=exp_gte, expiration_date_lte=exp_lte)
    assert opt_disc.load_snapshot(d1, filters=s1.filters).sha256 == s_d1.sha256

    # 5. Existing legacy non-content-addressed contracts snapshot remains readable and never overwritten
    d_leg = date(2026, 11, 26)
    f_hash = hashlib.sha256(json.dumps(s1.filters, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    leg_sdir = tmp_path / "raw_opt" / f"date={d_leg.isoformat()}"
    leg_mdir = tmp_path / "man_opt" / f"date={d_leg.isoformat()}"
    leg_sdir.mkdir(parents=True, exist_ok=True)
    leg_mdir.mkdir(parents=True, exist_ok=True)
    leg_text = json.dumps(OPTION_CONTRACTS_PAGE1, sort_keys=True)
    leg_sha = hashlib.sha256(leg_text.encode("utf-8")).hexdigest()
    leg_gz = leg_sdir / f"contracts_{f_hash}.json.gz"
    leg_man = leg_mdir / f"contracts_{f_hash}_manifest.json"
    with gzip.open(leg_gz, "wt", encoding="utf-8") as fh:
        fh.write(leg_text)
    leg_man.write_text(json.dumps({
        "snapshot_date": d_leg.isoformat(),
        "retrieved_at_utc": "2026-11-26T15:00:00+00:00",
        "filters": s1.filters,
        "sha256": leg_sha,
        "count": len(OPTION_CONTRACTS_PAGE1),
        "pages_fetched": 1,
        "pagination_complete": False,
    }), encoding="utf-8")
    loaded_leg = opt_disc.load_snapshot(d_leg, filters=s1.filters)
    assert loaded_leg is not None and loaded_leg.sha256 == leg_sha and loaded_leg.pagination_complete is False

    # Checksum tamper fails closed
    with gzip.open(s_d1.raw_gz_path, "wt", encoding="utf-8") as fh:
        fh.write("[]")
    with pytest.raises(AlpacaAdapterError):
        opt_disc.load_snapshot(d1, filters=s1.filters)
    reg.close()
