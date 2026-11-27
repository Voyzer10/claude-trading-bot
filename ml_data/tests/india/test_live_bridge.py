"""Tests for KiteLiveBridge WebSocket tick mapping, subscriptions, reconnects, and limits."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ml_data.india import (
    ContractDiscovery,
    InstrumentMasterDownloader,
    KiteClientWrapper,
    KiteInputError,
    KiteLiveBridge,
)
from ml_data.instruments import InstrumentRegistry
from ml_data.tests.india.fixtures import (
    FakeKiteSDK,
    build_equity_full_packet,
    build_index_binary_packet,
    build_index_quote_packet,
)


class _FakeWS:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)


def test_live_bridge_subscriptions_binary_ticks_reconnect_and_staleness(tmp_path):
    sdk = FakeKiteSDK()
    client = KiteClientWrapper(kite_client=sdk)
    dl = InstrumentMasterDownloader(client=client, root_dir=str(tmp_path / "master"))
    d0 = date(2026, 11, 27)
    nse = dl.download_snapshot("NSE", snap_date=d0)
    nfo = dl.download_snapshot("NFO", snap_date=d0)
    reg = InstrumentRegistry(str(tmp_path / "reg.sqlite3"))
    rep = ContractDiscovery().discover_from_snapshots(nse_snapshot=nse, nfo_snapshot=nfo, registry=reg)

    now_s = [1764215100.0]
    bridge = KiteLiveBridge(registry=reg, stale_after_seconds=10.0, clock=lambda: now_s[0])
    ws = _FakeWS()

    nifty_idx = rep.indices[0]
    toks = bridge.subscribe([nifty_idx.instrument_id], ws=ws)
    assert toks == [256265]
    assert len(ws.sent) == 2

    pkt = build_index_binary_packet(256265, 24512.35, 1764215100)
    ticks = bridge.on_binary_message(pkt)
    assert len(ticks) == 1
    assert ticks[0].instrument_id == nifty_idx.instrument_id
    assert ticks[0].ltp == Decimal("24512.35")
    assert bridge.stale_instruments() == []

    # Advance clock past staleness window
    now_s[0] += 20.0
    assert bridge.stale_instruments() == [nifty_idx.instrument_id]

    # Reconnect re-subscribes active tokens
    re_toks = bridge.on_reconnect(ws=ws)
    assert re_toks == [256265]
    assert bridge.reconnect_count == 1

    # Unsubscribe clears token and tick
    rem = bridge.unsubscribe([nifty_idx.instrument_id], ws=ws)
    assert rem == [256265]
    assert bridge.latest_tick(nifty_idx.instrument_id) is None

    with pytest.raises(KiteInputError):
        KiteLiveBridge(registry=reg, max_instruments=3001)

    # 28-byte index quote packet has net_change and no exchange timestamp
    bridge.subscribe([nifty_idx.instrument_id], ws=ws)
    q_pkt = build_index_quote_packet(256265, 24520.0, net_change=15.5)
    q_ticks = bridge.on_binary_message(q_pkt)
    assert len(q_ticks) == 1
    assert q_ticks[0].exchange_ts_utc is None
    assert q_ticks[0].net_change == Decimal("15.5")
    assert q_ticks[0].depth_buy is None

    # 184-byte equity/derivative full packet with 5-level market depth
    nifty_ce = next(o for o in rep.options if o.canonical_symbol == "NIFTY26D0324500CE")
    bridge.subscribe([nifty_ce.instrument_id], ws=ws)
    full_pkt = build_equity_full_packet(100003, 182.5)
    f_ticks = bridge.on_binary_message(full_pkt)
    assert len(f_ticks) == 1
    ft = f_ticks[0]
    assert ft.ltp == Decimal("182.5")
    assert ft.last_traded_quantity == 75
    assert ft.average_traded_price == Decimal("181.25")
    assert ft.volume == 125000
    assert ft.buy_quantity == 45000
    assert ft.sell_quantity == 38000
    assert ft.oi == 980000
    assert ft.oi_day_high == 1020000
    assert ft.oi_day_low == 850000
    assert ft.last_traded_timestamp_utc is not None
    assert ft.exchange_ts_utc is not None
    assert len(ft.depth_buy) == 5 and len(ft.depth_sell) == 5
    assert ft.depth_buy[0].price == Decimal("182.45")
    assert ft.depth_sell[0].price == Decimal("182.55")

    # Enforce MAX_CONNECTIONS_PER_API_KEY = 3
    conns = [KiteLiveBridge(registry=reg, api_key="test_api_key_limit") for _ in range(3)]
    with pytest.raises(KiteInputError):
        KiteLiveBridge(registry=reg, api_key="test_api_key_limit")
    conns[0].close()
    c4 = KiteLiveBridge(registry=reg, api_key="test_api_key_limit")
    for c in conns[1:] + [c4]:
        c.close()
    reg.close()
