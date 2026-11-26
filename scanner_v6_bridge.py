"""Scanner v6 as a V4 Scanner version (owner, 25 Nov 2026) with incremental per-symbol state, deterministic replay,
and Agent 4 target/SL revalidation helpers.

Modules A-D (scanner_v6, unchanged) run sequentially:
    StructureStream -> LiquidityStream -> CandlestickStream -> ConfirmationStream

What comes from V6: CHoCH -> reversal BOS -> liquidity sweep -> candlestick pattern -> 3-candle confirmation,
structural stop (`v6_sl_buffer_ticks` beyond sweep candle) and opposing liquidity pool target (`v6_tp_offset_ticks`
before the pool). No arbitrary 2R fallback: if no eligible pool exists or entry is at/beyond stop/target, reject.
"""
from __future__ import annotations

import json
import os
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

TICKS = {"NSE": Decimal("0.05"), "BSE": Decimal("0.05"), "NFO": Decimal("0.05"), "US": Decimal("0.01")}
ROUNDING = "ROUND_HALF_UP"
DEFAULT_CHECKPOINT_DIR = os.path.join("trader", "live", "v6_checkpoints")


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
    tail = rows[-60:]
    gaps = Counter(b[0] - a[0] for a, b in zip(tail, tail[1:]) if b[0] > a[0])
    return gaps.most_common(1)[0][0] if gaps else None


def _to_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _serialize_pools(lq) -> List[Dict[str, Any]]:
    return [
        {
            "pool_id": p.id,
            "side": "BSL" if p.side.value == "above" else "SSL",
            "price": str(Decimal(repr(p.price))),
            "formed_index": p.stamp.confirmed_index,
            "status": lq.state[p.id],
        }
        for p in lq.pools
    ]


def revalidate_v6_levels(
    pools_snapshot: List[Dict[str, Any]],
    side_str: str,
    entry_px: float,
    sweep_low: float,
    sweep_high: float,
    tick: Decimal,
    sl_buffer_ticks: int = 2,
    tp_offset_ticks: int = 1,
    min_rr: float = 1.0,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Agent 4 authoritative V6 Exit validation against the actual executable `entry_px`.

    Returns `(levels_dict, None)` on success or `(None, rejection_reason)` on failure.
    Never fabricates a 2R fallback when no valid opposing liquidity pool exists.
    """
    from scanner_v6.exit.stop_loss import BUY, SELL, structural_sl, to_grid
    from scanner_v6.exit.targets import PoolView, select_target_pool, target_price

    v6_side = BUY if side_str == "long" else SELL
    entry_d = to_grid(Decimal(repr(float(entry_px))), tick, ROUNDING)
    sl_d = structural_sl(v6_side, Decimal(repr(float(sweep_low))), Decimal(repr(float(sweep_high))),
                         int(sl_buffer_ticks), tick, ROUNDING)

    if (v6_side == BUY and entry_d <= sl_d) or (v6_side == SELL and entry_d >= sl_d):
        return None, "V6 exit rejected: executable entry %s is at or beyond structural SL %s" % (
            _r(float(entry_d)), _r(float(sl_d)))

    pools = [
        PoolView(p["pool_id"], p["side"], Decimal(str(p["price"])), int(p["formed_index"]), p["status"])
        for p in (pools_snapshot or [])
    ]
    pool = select_target_pool(v6_side, entry_d, pools)
    if pool is None:
        return None, "V6 exit rejected: no active opposing liquidity pool beyond executable entry %s" % _r(float(entry_d))

    tp_d = target_price(v6_side, pool.price, int(tp_offset_ticks), tick, ROUNDING)
    if (v6_side == BUY and tp_d <= entry_d) or (v6_side == SELL and tp_d >= entry_d):
        return None, "V6 exit rejected: target %s is on the wrong side of executable entry %s" % (
            _r(float(tp_d)), _r(float(entry_d)))

    risk = abs(entry_d - sl_d)
    reward = abs(tp_d - entry_d)
    rr = float(reward / risk) if risk > 0 else 0.0
    if rr + 1e-9 < float(min_rr):
        return None, "V6 exit rejected: R:R %.2f is below minimum %.2f after live entry %s" % (
            rr, float(min_rr), _r(float(entry_d)))

    return {
        "entry": _r(float(entry_d)),
        "stop": _r(float(sl_d)),
        "target": _r(float(tp_d)),
        "target_pool": pool.pool_id,
        "target_pool_price": _r(float(pool.price)),
        "target_pool_side": pool.side,
        "rr": round(rr, 2),
    }, None


def _build_setup_record(rec, candles, rows, i: int, T: Decimal, sl_buffer_ticks: int, tp_offset_ticks: int,
                        lq, raw_counts: Dict[str, int]) -> Optional[Dict[str, Any]]:
    from scanner_v6.exit.stop_loss import BUY, structural_sl, to_grid
    from scanner_v6.exit.targets import PoolView, select_target_pool, target_price

    side = rec.setup_side
    sw = candles[rec.sweep_index]
    sl = structural_sl(side, Decimal(repr(sw.low)), Decimal(repr(sw.high)), int(sl_buffer_ticks), T, ROUNDING)
    entry = to_grid(Decimal(repr(candles[i].close)), T, ROUNDING)
    if (side == BUY and entry <= sl) or (side != BUY and entry >= sl):
        return None
    pools = [PoolView(p.id, "BSL" if p.side.value == "above" else "SSL", Decimal(repr(p.price)),
                      p.stamp.confirmed_index, lq.state[p.id]) for p in lq.pools]
    pool = select_target_pool(side, entry, pools)
    if pool is None:
        return None
    tp = target_price(side, pool.price, int(tp_offset_ticks), T, ROUNDING)
    risk = abs(entry - sl)
    if (side == BUY and tp <= entry) or (side != BUY and tp >= entry) or risk == 0:
        return None
    long_ = side == BUY
    hist = {h.status: h for h in rec.history}
    return {
        "setup": "v6_smc_long" if long_ else "v6_smc_short",
        "side": "long" if long_ else "short",
        "price": _r(float(entry)),
        "stop": _r(float(sl)),
        "target": _r(float(tp)),
        "liquidity": "V6: CHoCH -> BOS -> swept %s %s -> %s, confirmed; target %s pool %s" % (
            "sell-side (SSL)" if long_ else "buy-side (BSL)", _r(sw.low if long_ else sw.high),
            rec.confirmed_pattern_id.split(":")[-1] if rec.confirmed_pattern_id else "pattern", pool.side,
            _r(float(pool.price))),
        "details": {
            "choch": rec.choch_id,
            "bos": rec.bos_id,
            "sweep_at": sw.ts.isoformat(),
            "sweep_low": _r(sw.low),
            "sweep_high": _r(sw.high),
            "pattern": rec.confirmed_pattern_id,
            "pattern_at": hist["PATTERN_DETECTED"].ts.isoformat() if "PATTERN_DETECTED" in hist else None,
            "confirmed_at": _to_utc(rows[i][0]).isoformat(),
            "target_pool": pool.pool_id,
            "target_pool_price": _r(float(pool.price)),
            "pools_snapshot": _serialize_pools(lq),
            "tick": str(T),
            "sl_buffer_ticks": int(sl_buffer_ticks),
            "tp_offset_ticks": int(tp_offset_ticks),
            "rr": round(float(abs(tp - entry) / risk), 2),
            "v6_setup_id": rec.setup_id,
            "raw_counts": dict(raw_counts),
            "qualified_sweeps": raw_counts.get("setup_sweeps", 0),
        },
    }


@dataclass
class V6SymbolState:
    """Isolated incremental V6 scanner state for one (market, symbol, timeframe)."""
    symbol: str
    market: Optional[str]
    tf_sec: int
    tick: Decimal
    stream: Any
    candles: List[Any] = field(default_factory=list)
    rows: List[tuple] = field(default_factory=list)
    last_ts: Optional[datetime] = None
    last_seq: int = -1
    raw_sweeps: int = 0
    raw_patterns: int = 0
    _seen_confirmed: set = field(default_factory=set)

    @classmethod
    def create(cls, symbol: str, market: Optional[str], tf_sec: int, tick: Decimal) -> "V6SymbolState":
        from scanner_v6.data.market_config import ConfigOrigin, MarketDataConfig
        from scanner_v6.entry.confirmation import ConfirmationStream
        from scanner_v6.liquidity.sweep import LiquidityEvent

        mkt = MarketDataConfig(origin=ConfigOrigin.INSTRUMENT_CONFIG, instrument_id=symbol,
                               timeframe=timedelta(seconds=tf_sec), tick_size=float(tick), session=None)
        st = ConfirmationStream(symbol, "%ds" % tf_sec, mkt)
        state = cls(symbol=symbol, market=market, tf_sec=tf_sec, tick=tick, stream=st)

        orig_ss = st.setup_stream.on_candle
        orig_ps = st.patterns_stream.on_candle

        def _wrap_ss(c):
            sev, lev, cands = orig_ss(c)
            for ev in lev:
                if isinstance(ev, LiquidityEvent) and ev.event_type == "SWEEP":
                    state.raw_sweeps += 1
            return sev, lev, cands

        def _wrap_ps(c):
            pats = orig_ps(c)
            state.raw_patterns += len(pats)
            return pats

        st.setup_stream.on_candle = _wrap_ss
        st.patterns_stream.on_candle = _wrap_ps
        return state

    def process_new_rows(self, rows: List[tuple], sl_buffer_ticks: int = 2,
                         tp_offset_ticks: int = 1) -> List[Dict[str, Any]]:
        """Process only newly completed candles (`ts > self.last_ts`) in strict chronological order."""
        from scanner_v6.data.candle_models import Candle
        from scanner_v6.entry.confirmation import CONFIRMED

        out: List[Dict[str, Any]] = []
        for r in rows:
            ts = _to_utc(r[0])
            if self.last_ts is not None and ts <= self.last_ts:
                continue  # duplicate or out-of-order candle safely ignored
            idx = self.last_seq + 1
            c = Candle(idx, r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                       float(r[5]) if len(r) > 5 and r[5] is not None else 0.0)
            self.stream.on_candle(c)
            self.candles.append(c)
            self.rows.append(r)
            self.last_ts = ts
            self.last_seq = idx

        # Only report setups confirmed on the latest completed candle
        if self.last_seq < 1:
            return out
        latest_i = self.last_seq
        raw_counts = {
            "raw_sweeps": self.raw_sweeps,
            "raw_patterns": self.raw_patterns,
            "setup_sweeps": len(self.stream.setups),
        }
        lq = self.stream.setup_stream.liquidity
        for rec in self.stream.setups:
            if rec.status != CONFIRMED or not rec.history or rec.history[-1].index != latest_i:
                continue
            if rec.key in self._seen_confirmed:
                continue
            self._seen_confirmed.add(rec.key)
            built = _build_setup_record(rec, self.candles, self.rows, latest_i, self.tick,
                                        sl_buffer_ticks, tp_offset_ticks, lq, raw_counts)
            if built:
                out.append(built)
        return out


class IncrementalV6Scanner:
    """Process-level incremental V6 scanner with per-symbol state and deterministic checkpoint recovery."""

    def __init__(self, checkpoint_dir: Optional[str] = DEFAULT_CHECKPOINT_DIR):
        self.states: Dict[Tuple[str, str, int], V6SymbolState] = {}
        self.checkpoint_dir = checkpoint_dir
        self._lock = threading.Lock()

    def _ckpt_path(self, market: Optional[str], symbol: str, tf_sec: int) -> Optional[str]:
        if not self.checkpoint_dir:
            return None
        safe = ("%s_%s_%ds.json" % (market or "MKT", symbol, tf_sec)).replace(":", "_").replace("/", "_")
        return os.path.join(self.checkpoint_dir, safe)

    def _save_checkpoint(self, state: V6SymbolState) -> None:
        path = self._ckpt_path(state.market, state.symbol, state.tf_sec)
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "symbol": state.symbol,
            "market": state.market,
            "tf_sec": state.tf_sec,
            "tick": str(state.tick),
            "last_ts": state.last_ts.isoformat() if state.last_ts else None,
            "last_seq": state.last_seq,
            "rows": [
                [r[0].isoformat(), float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                 float(r[5]) if len(r) > 5 and r[5] is not None else 0.0]
                for r in state.rows[-500:]
            ],
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)

    def _restore_checkpoint(self, market: Optional[str], symbol: str, tf_sec: int,
                            tick: Decimal) -> Optional[V6SymbolState]:
        path = self._ckpt_path(market, symbol, tf_sec)
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            if int(doc.get("tf_sec", 0)) != tf_sec or doc.get("tick") != str(tick):
                return None
            saved_rows = [
                (datetime.fromisoformat(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
                for r in (doc.get("rows") or [])
            ]
            if not saved_rows:
                return None
            st = V6SymbolState.create(symbol, market, tf_sec, tick)
            st.process_new_rows(saved_rows)
            return st
        except Exception:
            return None

    def scan(self, rows: List[tuple], symbol: str, market: Optional[str] = None,
             sl_buffer_ticks: int = 2, tp_offset_ticks: int = 1,
             tick: Optional[Decimal] = None) -> List[Dict[str, Any]]:
        if len(rows) < 2:
            return []
        T = tick if tick is not None else tick_for(market, rows)
        tf = _timeframe(rows)
        if tf is None:
            return []
        tf_sec = int(tf.total_seconds())
        key = (market or "", symbol, tf_sec)
        with self._lock:
            state = self.states.get(key)
            if state is None or state.tick != T:
                state = self._restore_checkpoint(market, symbol, tf_sec, T)
                if state is None:
                    state = V6SymbolState.create(symbol, market, tf_sec, T)
                self.states[key] = state
            # Reset deterministically if incoming window is older than checkpoint OR has an unbridged rolling gap
            first_ts, last_in_ts = _to_utc(rows[0][0]), _to_utc(rows[-1][0])
            if state.last_ts is not None and (
                last_in_ts < state.last_ts or first_ts > state.last_ts + timedelta(seconds=tf_sec * 2)
            ):
                state = V6SymbolState.create(symbol, market, tf_sec, T)
                self.states[key] = state
            prev_seq = state.last_seq
            out = state.process_new_rows(rows, sl_buffer_ticks=sl_buffer_ticks, tp_offset_ticks=tp_offset_ticks)
            if state.last_seq != prev_seq:
                self._save_checkpoint(state)
            return out


_DEFAULT_SCANNER = IncrementalV6Scanner()


def setups(rows, i: int, market: Optional[str] = None, sl_buffer_ticks: int = 2, tp_offset_ticks: int = 1,
           tick: Optional[Decimal] = None, symbol: Optional[str] = None) -> List[Dict]:
    """V6 setups CONFIRMED on candle i (rows: closed candles oldest first, (ts, o, h, l, c[, v])).

    When `symbol` is provided, uses `IncrementalV6Scanner` for O(new_candles) incremental processing;
    otherwise runs a clean deterministic replay over `rows[:i+1]`.
    """
    if i != len(rows) - 1 or i < 1:
        return []
    if symbol:
        return _DEFAULT_SCANNER.scan(rows, symbol, market=market, sl_buffer_ticks=sl_buffer_ticks,
                                     tp_offset_ticks=tp_offset_ticks, tick=tick)
    T = tick if tick is not None else tick_for(market, rows)
    tf = _timeframe(rows)
    if tf is None:
        return []
    state = V6SymbolState.create("chart", market, int(tf.total_seconds()), T)
    return state.process_new_rows(rows, sl_buffer_ticks=sl_buffer_ticks, tp_offset_ticks=tp_offset_ticks)
