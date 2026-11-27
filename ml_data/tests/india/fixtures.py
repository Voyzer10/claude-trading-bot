"""Synthetic mocked Kite Connect NSE/NFO CSV dumps and binary tick builders."""
from __future__ import annotations

import struct

NSE_CSV = """instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange
256265,1001,NIFTY 50,NIFTY 50,24500.0,,0,0.05,1,EQ,INDICES,NSE
260105,1017,NIFTY BANK,NIFTY BANK,52400.0,,0,0.05,1,EQ,INDICES,NSE
738561,2885,RELIANCE,RELIANCE INDUSTRIES,1300.0,,0,0.05,1,EQ,NSE,NSE
"""

NFO_CSV = """instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange
100001,390,NIFTY26DECFUT,NIFTY,24600.0,2026-12-31,0,0.05,75,FUT,NFO-FUT,NFO
100002,391,BANKNIFTY26DECFUT,BANKNIFTY,52600.0,2026-12-31,0,0.05,30,FUT,NFO-FUT,NFO
100003,392,NIFTY26D0324500CE,NIFTY,180.5,2026-12-03,24500,0.05,75,CE,NFO-OPT,NFO
100004,393,NIFTY26D0324500PE,NIFTY,165.0,2026-12-03,24500,0.05,75,PE,NFO-OPT,NFO
100005,394,BANKNIFTY26DEC52500CE,BANKNIFTY,410.0,2026-12-31,52500,0.05,30,CE,NFO-OPT,NFO
100006,395,BANKNIFTY26DEC52500PE,BANKNIFTY,390.0,2026-12-31,52500,0.05,30,PE,NFO-OPT,NFO
100007,396,FINNIFTY26DECFUT,FINNIFTY,23500.0,2026-12-31,0,0.05,65,FUT,NFO-FUT,NFO
100008,397,NIFTYIT26DECFUT,NIFTYIT,41000.0,2026-12-31,0,0.05,25,FUT,NFO-FUT,NFO
100009,398,RELIANCE26DEC1400CE,RELIANCE,25.0,2026-12-31,1400,0.05,500,CE,NFO-OPT,NFO
"""


class FakeKiteSDK:
    """In-memory fake Kite client for offline unit tests."""

    def __init__(self, nse_csv: str = NSE_CSV, nfo_csv: str = NFO_CSV, candles_by_token=None):
        self.nse_csv = nse_csv
        self.nfo_csv = nfo_csv
        self.candles_by_token = candles_by_token or {}
        self.calls = []

    def instruments_csv(self, exchange: str) -> str:
        self.calls.append(("instruments_csv", exchange))
        if exchange == "NSE":
            return self.nse_csv
        if exchange == "NFO":
            return self.nfo_csv
        raise ValueError(f"Unknown exchange {exchange}")

    def historical_data(self, token: int, f_ist: str, t_ist: str, interval: str, continuous: bool = False, oi: bool = False):
        self.calls.append(("historical_data", token, f_ist, t_ist, interval, oi))
        res = self.candles_by_token.get((token, interval), [])
        if callable(res):
            return res(token, f_ist, t_ist, interval, oi)
        return res


def build_index_quote_packet(token: int, ltp: float, net_change: float = 12.5) -> bytes:
    """Build a genuine 28-byte Kite index quote binary packet (no exchange timestamp)."""
    pkt = struct.pack(">H", 1)
    body = struct.pack(
        ">Iiiiiii",
        token,
        int(round(ltp * 100)),
        int(round((ltp + 10) * 100)),
        int(round((ltp - 10) * 100)),
        int(round(ltp * 100)),
        int(round((ltp - net_change) * 100)),
        int(round(net_change * 100)),
    )
    assert len(body) == 28
    return pkt + struct.pack(">H", len(body)) + body


def build_index_binary_packet(token: int, ltp: float, ts_unix: int, net_change: float = 12.5) -> bytes:
    """Build a genuine 32-byte Kite index full binary packet with net_change and exchange timestamp."""
    pkt = struct.pack(">H", 1)
    body = struct.pack(
        ">IiiiiiiI",
        token,
        int(round(ltp * 100)),
        int(round((ltp + 10) * 100)),
        int(round((ltp - 10) * 100)),
        int(round(ltp * 100)),
        int(round((ltp - net_change) * 100)),
        int(round(net_change * 100)),
        ts_unix,
    )
    assert len(body) == 32
    return pkt + struct.pack(">H", len(body)) + body


def build_equity_full_packet(
    token: int,
    ltp: float,
    *,
    ltq: int = 75,
    avg_price: float = 181.25,
    volume: int = 125000,
    buy_qty: int = 45000,
    sell_qty: int = 38000,
    open_p: float = 179.0,
    high_p: float = 185.0,
    low_p: float = 178.5,
    close_p: float = 180.0,
    ltt_unix: int = 1764215098,
    oi: int = 980000,
    oi_day_high: int = 1020000,
    oi_day_low: int = 850000,
    exchange_ts_unix: int = 1764215100,
) -> bytes:
    """Build a genuine 184-byte Kite equity/derivative full binary packet with 5-level depth."""
    header = struct.pack(
        ">IiiiIIIiiiiIIII",
        token,
        int(round(ltp * 100)),
        ltq,
        int(round(avg_price * 100)),
        volume,
        buy_qty,
        sell_qty,
        int(round(open_p * 100)),
        int(round(high_p * 100)),
        int(round(low_p * 100)),
        int(round(close_p * 100)),
        ltt_unix,
        oi,
        oi_day_high,
        oi_day_low,
    ) + struct.pack(">I", exchange_ts_unix)
    depth_bytes = b""
    for i in range(5):
        depth_bytes += struct.pack(">IiHxx", 75 * (i + 1), int(round((ltp - 0.05 * (i + 1)) * 100)), i + 1)
    for i in range(5):
        depth_bytes += struct.pack(">IiHxx", 150 * (i + 1), int(round((ltp + 0.05 * (i + 1)) * 100)), i + 2)
    body = header + depth_bytes
    assert len(body) == 184
    return struct.pack(">H", 1) + struct.pack(">H", len(body)) + body
