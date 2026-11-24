"""Scanner v6 as a V4 Scanner version (owner, 25 Nov 2026: "settings m ek option add karo scanner replace karne ka jese
pehle tha"): Settings > Risk limits > Scanner version = v6 makes that paper account's Scanner the V6 SMC scanner.

What comes from V6 (scanner_v6, Modules A-D, unchanged): the strategy sequence CHoCH -> reversal BOS -> liquidity
sweep -> candlestick pattern -> confirmation, replayed over the chart's closed candles in order (no look-ahead: only
candles 0..i). A setup is reported on the candle where V6 CONFIRMS it, with V6's structural stop (beyond the sweep
candle, `v6_sl_buffer_ticks`) and V6's target (the nearest active opposing liquidity pool, `v6_tp_offset_ticks` before
it); a setup with no eligible pool, or whose entry is at or beyond the stop, is not reported (V6 CK-13).

What stays V4 (this is the V4 pipeline, not the V6 paper runtime): the entry (V4's Entry agent at the live price
after the confirmation candle, where V6 Module E would use the next candle's open), sizing, fees, Risk, Broker and the
Trade Manager are the account's V4 agents and settings. V6's own paper runtime (v6_runtime/, the /v6 dashboard) is
separate and is not affected.

Assumptions (documented, never hidden): the price grid is the market's tick (NSE 0.05, US 0.01) or, for crypto, the
finest decimal the chart's own prices use; overnight / weekend gaps are read as consecutive candles (Modules A-D have
no session rule; V6's session rules live in Module E, which V4 does not use).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

TICKS = {"NSE": Decimal("0.05"), "BSE": Decimal("0.05"), "NFO": Decimal("0.05"), "US": Decimal("0.01")}
ROUNDING = "ROUND_HALF_UP"


def _r(x: float) -> float:
    ax = abs(x)
    return round(x, 2) if ax >= 100 else round(x, 4) if ax >= 1 else float("%.6g" % x)


def tick_for(market: Optional[str], rows) -> Decimal:
    """The market's price grid; crypto: the finest decimal step in the chart's last 200 prices (capped at 1e-8)."""
    if market in TICKS:
        return TICKS[market]
    places = 0
    for r in rows[-200:]:
        for x in r[1:5]:
            d = Decimal(repr(float(x))).normalize()
            places = max(places, -d.as_tuple().exponent if d.as_tuple().exponent < 0 else 0)
    return Decimal(1).scaleb(-min(places, 8))


def _timeframe(rows):
    """The chart's bar length: the most common gap between consecutive candles (None if there is none)."""
    from collections import Counter
    tail = rows[-60:]
    gaps = Counter(b[0] - a[0] for a, b in zip(tail, tail[1:]) if b[0] > a[0])
    return gaps.most_common(1)[0][0] if gaps else None


def setups(rows, i: int, market: Optional[str] = None, sl_buffer_ticks: int = 2, tp_offset_ticks: int = 1,
           tick: Optional[Decimal] = None) -> List[Dict]:
    """V6 setups CONFIRMED on candle i (rows: closed candles oldest first, (ts, o, h, l, c[, v]))."""
    from scanner_v6.data.candle_models import Candle
    from scanner_v6.data.market_config import ConfigOrigin, MarketDataConfig
    from scanner_v6.entry.confirmation import CONFIRMED, ConfirmationStream
    from scanner_v6.exit.stop_loss import BUY, structural_sl, to_grid
    from scanner_v6.exit.targets import PoolView, select_target_pool, target_price

    if i != len(rows) - 1 or i < 1:
        return []
    T = tick if tick is not None else tick_for(market, rows)
    tf = _timeframe(rows)
    if tf is None:
        return []
    mkt = MarketDataConfig(origin=ConfigOrigin.INSTRUMENT_CONFIG, instrument_id="chart", timeframe=tf,
                           tick_size=float(T), session=None)
    st = ConfirmationStream("chart", "%ds" % int(tf.total_seconds()), mkt)
    candles = []
    for k, r in enumerate(rows):
        c = Candle(k, r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                   float(r[5]) if len(r) > 5 and r[5] is not None else 0.0)
        st.on_candle(c)
        candles.append(c)
    lq = st.setup_stream.liquidity
    pools = [PoolView(p.id, "BSL" if p.side.value == "above" else "SSL", Decimal(repr(p.price)),
                      p.stamp.confirmed_index, lq.state[p.id]) for p in lq.pools]
    out = []
    for rec in st.setups:
        if rec.status != CONFIRMED or not rec.history or rec.history[-1].index != i:
            continue
        side = rec.setup_side
        sw = candles[rec.sweep_index]
        sl = structural_sl(side, Decimal(repr(sw.low)), Decimal(repr(sw.high)), int(sl_buffer_ticks), T, ROUNDING)
        entry = to_grid(Decimal(repr(candles[i].close)), T, ROUNDING)
        if (side == BUY and entry <= sl) or (side != BUY and entry >= sl):
            continue                                                    # V6 CK-13: entry at or beyond the stop
        pool = select_target_pool(side, entry, pools)
        if pool is None:
            continue                                                    # V6: no eligible opposing liquidity
        tp = target_price(side, pool.price, int(tp_offset_ticks), T, ROUNDING)
        risk = abs(entry - sl)
        if (side == BUY and tp <= entry) or (side != BUY and tp >= entry) or risk == 0:
            continue
        long_ = side == BUY
        hist = {h.status: h for h in rec.history}
        out.append({
            "setup": "v6_smc_long" if long_ else "v6_smc_short", "side": "long" if long_ else "short",
            "price": _r(float(entry)), "stop": _r(float(sl)), "target": _r(float(tp)),
            "target_2r": _r(float(entry + 2 * risk if long_ else entry - 2 * risk)),
            "liquidity": "V6: CHoCH -> BOS -> swept %s %s -> %s, confirmed; target %s pool %s" % (
                "sell-side (SSL)" if long_ else "buy-side (BSL)", _r(sw.low if long_ else sw.high),
                rec.confirmed_pattern_id.split(":")[-1] if rec.confirmed_pattern_id else "pattern", pool.side,
                _r(float(pool.price))),
            "details": {"choch": rec.choch_id, "bos": rec.bos_id, "sweep_at": sw.ts.isoformat(),
                        "pattern": rec.confirmed_pattern_id,
                        "pattern_at": hist["PATTERN_DETECTED"].ts.isoformat() if "PATTERN_DETECTED" in hist else None,
                        "confirmed_at": rows[i][0].isoformat(), "target_pool": pool.pool_id,
                        "tick": str(T), "sl_buffer_ticks": int(sl_buffer_ticks), "tp_offset_ticks": int(tp_offset_ticks),
                        "rr": round(float(abs(tp - entry) / risk), 2), "v6_setup_id": rec.setup_id},
        })
    return out
