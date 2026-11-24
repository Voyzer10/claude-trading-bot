"""Multi-instrument portfolio orchestration for ONE V6 paper book, around the unchanged Modules A-E.

Each instrument runs its own Module E ExecutionStream (the authoritative simulator: entries at the next open,
structural SL, opposing-pool TP, STOP_FIRST exits, fees, slippage). The portfolio decides which Module E entries are
BOOKED into the book's ledger:

  1. one open position per book (across all its instruments)        -> BOOK_POSITION_LIMIT
  2. the book's daily loss latch (2% of start-of-day equity, CK-23)   -> BOOK_DAILY_LOSS
  3. risk: Module E's loss estimate <= 1% of current book equity     -> BOOK_RISK_EXCEEDED
  4. margin: Module E's required margin <= book cash                  -> BOOK_INSUFFICIENT_CASH

An entry that fails a gate is recorded as a rejection; its Module E trade continues as a SHADOW trade inside that
instrument's stream only and never touches book cash. Booked trades use Module E's fills, quantity, fees and P&L
unchanged (no recomputation), so book figures equal Module E figures.

NOT APPROVED design points (kept explicit, see v6_runtime/README.md): Module E sizes on the instrument stream's own
equity (which starts at the book budget); the book only enforces the 1% / margin limits above. Simultaneous entries on
different instruments at the same timestamp are resolved in instrument-id order.

Recovery: every validated input (candle or data event) is appended to journal.jsonl BEFORE it changes any state
(write-ahead). After a restart, `recover()` replays the journal through fresh streams; bookings already in the ledger
are verified against the replayed Module E records (never booked twice); a mismatch stops the book (LedgerCorrupt).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from scanner_v6.data.candle_models import Candle
from scanner_v6.data.market_config import MarketDataConfig
from scanner_v6.entry.candlesticks import CandlestickConfig
from scanner_v6.exit import execution as E
from scanner_v6.exit.execution_config import ExecutionConfig
from scanner_v6.exit.sizing import RISK_FRACTION

from . import identity
from .ledger import BookLedger, D, LedgerCorrupt
from .paths import DataRoot

BOOK_POSITION_LIMIT = "BOOK_POSITION_LIMIT"
BOOK_DAILY_LOSS = "BOOK_DAILY_LOSS"
BOOK_RISK_EXCEEDED = "BOOK_RISK_EXCEEDED"
BOOK_INSUFFICIENT_CASH = "BOOK_INSUFFICIENT_CASH"
BOOK_MTM_UNSCORABLE = "BOOK_MTM_UNSCORABLE"


class PortfolioError(RuntimeError):
    pass


class DuplicateInput(PortfolioError):
    pass


@dataclass(frozen=True)
class InstrumentSpec:
    instrument_id: str
    book_id: str
    timeframe: str
    market: MarketDataConfig
    execution: ExecutionConfig
    candlestick: Optional[CandlestickConfig] = None


def _ser_candle(c: Candle) -> Dict[str, Any]:
    return {"index": c.index, "ts": c.ts.isoformat(), "o": repr(c.open), "h": repr(c.high), "l": repr(c.low),
            "c": repr(c.close), "v": repr(c.volume)}


def _de_candle(d: Dict[str, Any]) -> Candle:
    return Candle(d["index"], datetime.fromisoformat(d["ts"]), float(d["o"]), float(d["h"]), float(d["l"]),
                  float(d["c"]), float(d["v"]))


def _s(v: Any) -> Optional[str]:
    return None if v is None else str(v)


class Portfolio:
    def __init__(self, root: DataRoot, ledger: BookLedger, instruments: List[InstrumentSpec], *, journal: bool = True):
        if not instruments:
            raise PortfolioError("a portfolio needs at least one instrument")
        ids = [i.instrument_id for i in instruments]
        if len(ids) != len(set(ids)):
            raise PortfolioError("duplicate instrument ids: %s" % ids)
        for i in instruments:
            if i.book_id != ledger.book_id:
                raise PortfolioError("instrument %s belongs to book %s, not %s" % (i.instrument_id, i.book_id,
                                                                                    ledger.book_id))
            if i.market.session is None:
                raise PortfolioError("instrument %s has no session calendar" % i.instrument_id)
        self.root, self.ledger, self.journal_on = root, ledger, journal
        self.specs = {i.instrument_id: i for i in sorted(instruments, key=lambda s: s.instrument_id)}
        self.streams = {iid: E.ExecutionStream(iid, s.timeframe, s.market, s.execution, s.candlestick)
                        for iid, s in self.specs.items()}
        self.shadow: set = set()
        self.mtm: Optional[Dict[str, Any]] = None
        self.last_day: Optional[str] = None
        self.replaying = False
        self._signal_keys = {self._sig_key(r) for r in root.read_jsonl(*self._signals_file())}

    # ------------------------------------------------------------ files
    def _journal_file(self) -> tuple:
        return ("journal", "%s.jsonl" % self.ledger.book_id)

    def _signals_file(self) -> tuple:
        return ("signals", "%s.jsonl" % self.ledger.book_id)

    @staticmethod
    def _sig_key(r: Dict[str, Any]) -> tuple:
        return (r.get("instrument"), r.get("setup_id"), r.get("stage"), r.get("index"), r.get("book_decision"))

    # ------------------------------------------------------------ inputs
    def on_candle(self, instrument_id: str, c: Candle) -> List[Dict[str, Any]]:
        st = self._stream(instrument_id)
        st.d.check_candle(c)                    # pure validation (F-D1/F-E1): nothing is journaled or changed if invalid
        if self.journal_on and not self.replaying:
            self.root.append_jsonl({"kind": "candle", "instrument": instrument_id, "candle": _ser_candle(c)},
                                   *self._journal_file())
        if self.replaying:
            # the ledger already holds the FINAL state: during replay nothing is derived from it (no day-start
            # equity, no MTM, no daily-loss latch); MTM is rebuilt once after the replay ends
            self.last_day = self._day(instrument_id, c.ts)
            changed = st.on_candle(c)
            return [o for o in (self._handle(instrument_id, c, r) for r in changed) if o is not None]
        self._day_rollover(instrument_id, c)
        changed = st.on_candle(c)
        out = [self._handle(instrument_id, c, r) for r in changed]
        self._update_mtm(instrument_id, c)
        self._check_daily_loss(instrument_id, c)
        return [o for o in out if o is not None]

    def on_data_interrupted(self, instrument_id: str, ts: datetime) -> List[Dict[str, Any]]:
        return self._data(instrument_id, "DATA_INTERRUPTED", ts)

    def on_data_resumed(self, instrument_id: str, ts: datetime) -> List[Dict[str, Any]]:
        return self._data(instrument_id, "DATA_RESUMED", ts)

    def _data(self, instrument_id: str, state: str, ts: datetime) -> List[Dict[str, Any]]:
        st = self._stream(instrument_id)
        changed = st.mark_data_interrupted(ts) if state == "DATA_INTERRUPTED" else st.mark_data_resumed(ts)
        if self.journal_on and not self.replaying:
            self.root.append_jsonl({"kind": state, "instrument": instrument_id, "ts": ts.isoformat()},
                                   *self._journal_file())
        c = st.candles[-1] if st.candles else None
        return [o for o in (self._handle(instrument_id, c, r) for r in changed) if o is not None]

    def _stream(self, instrument_id: str) -> E.ExecutionStream:
        try:
            return self.streams[instrument_id]
        except KeyError:
            raise PortfolioError("instrument %s is not configured in book %s" % (instrument_id,
                                                                                self.ledger.book_id)) from None

    # ------------------------------------------------------------ recovery
    def recover(self) -> int:
        """Replay the journal into fresh streams (call on a new Portfolio before any live input). Returns the number of
        journal entries replayed. Bookings are verified, never repeated."""
        entries = self.root.read_jsonl(*self._journal_file())
        self.replaying = True
        try:
            for e in entries:
                if e["kind"] == "candle":
                    self.on_candle(e["instrument"], _de_candle(e["candle"]))
                else:
                    self._data(e["instrument"], e["kind"], datetime.fromisoformat(e["ts"]))
        finally:
            self.replaying = False
        ot = self.ledger.open_trade
        if ot is not None:
            rec = self.streams[ot["instrument"]].record(ot["setup_id"]) if ot["instrument"] in self.streams else None
            if rec is None or rec.status != E.ENTERED:
                raise LedgerCorrupt("book %s: open trade %s is not open after replay" % (self.ledger.book_id,
                                                                                         ot["setup_id"]))
            st = self.streams[ot["instrument"]]
            if st.candles:
                self._update_mtm(ot["instrument"], st.candles[-1])
        return len(entries)

    # ------------------------------------------------------------ booking
    def _handle(self, iid: str, c: Optional[Candle], r: E.TradeRecord) -> Optional[Dict[str, Any]]:
        decision, detail = None, None
        if r.status == E.ENTERED and c is not None and r.entry_index == c.index:
            decision, detail = self._entry(iid, r)
        elif r.status in (E.STOPPED_OUT, E.TARGET_HIT):
            decision, detail = self._exit(iid, c, r)
        return self._signal(iid, c, r, decision, detail)

    def _equity_now(self) -> Tuple[str, Optional[Decimal]]:
        if self.ledger.open_trade is None:
            return "OK", self.ledger.cash()
        if self.mtm and self.mtm.get("status") == "OK":
            return "OK", self.ledger.cash() + D(self.mtm["unrealized"]) - D(self.mtm["est_exit_fee"])
        return E.UNSCORABLE, None

    def _entry(self, iid: str, r: E.TradeRecord) -> Tuple[str, Optional[str]]:
        led = self.ledger
        if led.seen(r.setup_id):                                     # replay after a restart: verify, do not re-book
            ot = led.open_trade
            booked = next((t for t in led.trades() if t["setup_id"] == r.setup_id), None)
            if booked is None:
                self.shadow.add(r.setup_id)
                return "REJECTED (journal)", None
            if booked["entry_fill"] != str(r.entry_fill) or booked["quantity"] != str(r.quantity):
                raise LedgerCorrupt("replayed entry %s differs from the ledger" % r.setup_id)
            return "BOOKED (verified)", None if ot else "already closed"
        day = self._day(iid, r.history[-1].ts)
        st, equity = self._equity_now()
        code = None
        if led.open_trade is not None:
            code, why = BOOK_POSITION_LIMIT, "book %s already holds %s" % (led.book_id, led.open_trade["setup_id"])
        elif day in led.state["latched_days"]:
            code, why = BOOK_DAILY_LOSS, "daily loss latch for %s" % day
        elif st != "OK" or equity is None:
            code, why = BOOK_MTM_UNSCORABLE, "book equity is not scorable"
        elif r.loss_estimate is None or r.loss_estimate > RISK_FRACTION * equity:
            code, why = BOOK_RISK_EXCEEDED, "loss estimate %s > 1%% of book equity %s" % (r.loss_estimate, equity)
        elif r.required_margin is None or r.required_margin > led.cash():
            code, why = BOOK_INSUFFICIENT_CASH, "required margin %s > book cash %s" % (r.required_margin, led.cash())
        if code is not None:
            self.shadow.add(r.setup_id)
            led.record_rejection(r.setup_id, iid, code, why)
            return "REJECTED", "%s: %s" % (code, why)
        spec = self.specs[iid]
        M = spec.execution.contract_multiplier
        led.book_entry({
            "setup_id": r.setup_id, "instrument": iid, "market": led.state["market"],
            "timeframe": spec.timeframe, "side": r.side, "entry_index": r.entry_index,
            "entry_ts": r.history[-1].ts.isoformat(), "entry_open": _s(r.entry_open), "entry_fill": _s(r.entry_fill),
            "quantity": _s(r.quantity), "contract_multiplier": _s(M), "sl": _s(r.sl), "tp": _s(r.tp),
            "tp_pool_id": r.tp_pool_id, "entry_fee": _s(r.entry_fee), "loss_estimate": _s(r.loss_estimate),
            "net_rr": _s(r.net_rr), "required_margin": _s(r.required_margin), "risk_budget": _s(r.risk_budget),
            "entry_slippage": _s(abs(r.entry_fill - r.entry_open) * r.quantity * M),
        })
        return "BOOKED", None

    def _exit(self, iid: str, c: Optional[Candle], r: E.TradeRecord) -> Tuple[Optional[str], Optional[str]]:
        led = self.ledger
        if r.setup_id in self.shadow:
            return "SHADOW", "not booked"
        ot = led.open_trade
        if ot is None or ot["setup_id"] != r.setup_id:
            closed = next((t for t in led.state["closed_trades"] if t["setup_id"] == r.setup_id), None)
            if closed is not None:                                    # replay: verify
                if closed["exit_fill"] != str(r.exit_fill) or closed["realized_pnl"] != str(r.realized_pnl):
                    raise LedgerCorrupt("replayed exit %s differs from the ledger" % r.setup_id)
                return "BOOKED (verified)", None
            raise LedgerCorrupt("exit of %s, which the book does not hold" % r.setup_id)
        M = D(ot["contract_multiplier"])
        if r.status == E.TARGET_HIT:
            ref = r.tp
        else:
            ref = D(repr(c.open)) if r.exit_gap and c is not None else r.sl
        led.book_exit(r.setup_id, {
            "status": r.status, "exit_index": r.exit_index, "exit_ts": r.history[-1].ts.isoformat(),
            "exit_fill": _s(r.exit_fill), "exit_gap": r.exit_gap, "exit_fee": _s(r.exit_fee),
            "gross_pnl": _s(r.gross_pnl), "realized_pnl": _s(r.realized_pnl),
            "exit_reference": _s(ref), "exit_slippage": _s(abs(r.exit_fill - ref) * r.quantity * M),
        })
        self.mtm = None
        return "BOOKED", None

    # ------------------------------------------------------------ MTM, days, daily loss
    def _tz(self, iid: str) -> ZoneInfo:
        return ZoneInfo(self.specs[iid].market.session.timezone)

    def _day(self, iid: str, ts: datetime) -> str:
        return ts.astimezone(self._tz(iid)).date().isoformat()

    def _day_rollover(self, iid: str, c: Candle) -> None:
        day = self._day(iid, c.ts)
        if day != self.last_day:
            st, eq = self._equity_now()
            if st == "OK" and eq is not None:
                self.ledger.mark_day_start(day, eq)
            self.last_day = day

    def _update_mtm(self, iid: str, c: Candle) -> None:
        ot = self.ledger.open_trade
        if ot is None or ot["instrument"] != iid:
            return
        st = self.streams[iid]
        try:
            rec = st.record(ot["setup_id"])
        except KeyError:
            raise LedgerCorrupt("book %s holds %s, unknown to the %s stream" % (self.ledger.book_id, ot["setup_id"],
                                                                                iid)) from None
        status, est, why = st.estimate_exit(rec, D(repr(c.close)))
        if status != "OK":
            self.mtm = {"status": E.UNSCORABLE, "reason": why}
        else:
            self.mtm = {"status": "OK", "mark": str(est[0]), "est_exit_fill": str(est[1]), "unrealized": str(est[2]),
                        "est_exit_fee": str(est[3]), "at": c.ts.isoformat()}

    def _check_daily_loss(self, iid: str, c: Candle) -> None:
        day = self._day(iid, c.ts)
        sod = self.ledger.state["day_start_equity"].get(day)
        st, eq = self._equity_now()
        if sod is None or st != "OK" or eq is None:
            return
        if D(sod) - eq >= E.DAILY_LOSS_FRACTION * D(sod):
            self.ledger.latch_day(day, "equity %s <= start-of-day %s - 2%%" % (eq, sod))

    # ------------------------------------------------------------ signals log
    def _signal(self, iid: str, c: Optional[Candle], r: E.TradeRecord, decision: Optional[str],
                detail: Optional[str]) -> Optional[Dict[str, Any]]:
        spec = self.specs[iid]
        last = r.history[-1]
        tz = self._tz(iid)
        sig = identity.stamp({
            "book_id": self.ledger.book_id, "instrument": iid, "market": self.ledger.state["market"],
            "timeframe": spec.timeframe, "setup_id": r.setup_id, "stage": r.status, "index": last.index,
            "ts_utc": last.ts.isoformat(), "ts_local": last.ts.astimezone(tz).isoformat(), "direction": r.side,
            "entry_reference": _s(r.entry_open if r.entry_open is not None else r.confirmation_close),
            "entry_fill": _s(r.entry_fill), "stop_loss": _s(r.sl), "target": _s(r.tp), "quantity": _s(r.quantity),
            "confirmation_index": r.confirmation_index, "result": r.result,
            "rejection_reason": r.reason_code or r.disposition_reason, "blocked_by": list(r.blocked_by),
            "data_quality": r.data_state, "book_decision": decision, "book_detail": detail,
            "shadow": r.setup_id in self.shadow,
        })
        key = self._sig_key(sig)
        if self.replaying or key in self._signal_keys:     # replay re-derives signals already logged: never re-log
            return sig
        self._signal_keys.add(key)
        self.root.append_jsonl(sig, *self._signals_file())
        return sig

    # ------------------------------------------------------------ view
    def summary(self) -> Dict[str, Any]:
        day = self.last_day
        return self.ledger.summary(self.mtm if self.ledger.open_trade else None, day)
