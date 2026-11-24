"""Persistent, versioned ledger for one V6 paper book.

Cash model (identical to Module E's own account, so booked figures equal Module E's figures):
  entry:  cash -= entry_fee
  exit:   cash += gross - exit_fee;   realized (net) = gross - entry_fee - exit_fee
Invariants (checked on every load and every write):
  cash          = starting_budget + sum(realized of closed) - (entry_fee of the open trade, if any)
  realized_pnl  = sum(realized of closed)
  fees_total    = sum(entry_fee + exit_fee of closed) + entry_fee of the open trade
Equity at a mark (OQ-13, same estimate as Module E): cash + unrealized - estimated exit fee of the open trade.

Every write is atomic (temp + fsync + rename) and increments `seq`. A setup id is booked at most once (duplicate
execution protection). A book is never reset or overwritten: `create` refuses when the book already exists.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from . import identity
from .books import BookSpec, spec as book_spec
from .paths import DataRoot

SCHEMA_VERSION = 1
PAPER, BACKTEST = "PAPER", "BACKTEST"     # a BACKTEST ledger lives only inside a backtest run directory


class LedgerError(RuntimeError):
    pass


class BookExists(LedgerError):
    pass


class BookMissing(LedgerError):
    pass


class DuplicateExecution(LedgerError):
    pass


class LedgerCorrupt(LedgerError):
    pass


def D(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool) or v is None:
        raise LedgerCorrupt("not a money value: %r" % (v,))
    return Decimal(str(v))


def _s(v: Optional[Decimal]) -> Optional[str]:
    return None if v is None else str(v)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BookLedger:
    def __init__(self, root: DataRoot, book_id: str, state: Dict[str, Any]):
        self.root, self.book_id, self.state = root, book_id, state

    # ------------------------------------------------------------ files
    @staticmethod
    def _file(book_id: str) -> tuple:
        return ("books", "%s.json" % book_id)

    @staticmethod
    def _events(book_id: str) -> tuple:
        return ("books", "%s.events.jsonl" % book_id)

    @classmethod
    def exists(cls, root: DataRoot, book_id: str) -> bool:
        import os
        return os.path.exists(root.path(*cls._file(book_id)))

    # ------------------------------------------------------------ lifecycle
    @classmethod
    def create(cls, root: DataRoot, book_id: str, *, owner_authorised: bool, created_by: str,
               ledger_kind: str = PAPER, starting_budget: Optional[Decimal] = None) -> "BookLedger":
        """A fresh book: starting budget from the owner-approved spec, zero P&L, no positions, no history.
        Refuses unless explicitly authorised, and never overwrites an existing book.

        `ledger_kind=BACKTEST` creates an independent SIMULATION ledger (used only inside a backtest run directory);
        only a BACKTEST ledger may use a `starting_budget` other than the owner-approved book budget."""
        if owner_authorised is not True:
            raise LedgerError("creating a V6 book needs explicit owner authorisation")
        if ledger_kind not in (PAPER, BACKTEST):
            raise LedgerError("unknown ledger kind %r" % (ledger_kind,))
        sp: BookSpec = book_spec(book_id)
        if starting_budget is not None and ledger_kind != BACKTEST:
            raise LedgerError("a paper book always starts at the owner-approved budget %s" % sp.starting_budget)
        budget = sp.starting_budget if starting_budget is None else D(starting_budget)
        if budget <= 0:
            raise LedgerError("starting budget must be positive")
        if cls.exists(root, book_id):
            raise BookExists("V6 book %s already exists; it is never reset automatically" % book_id)
        st = {
            "schema_version": SCHEMA_VERSION, "seq": 0, "book_id": sp.book_id, "label": sp.label,
            "ledger_kind": ledger_kind,
            "market": sp.market, "currency": sp.currency, "starting_budget": str(budget),
            "budget_decision": sp.decision if ledger_kind == PAPER else "backtest simulation (not a paper account)",
            "created_at": _now(), "created_by": created_by,
            "cash": str(budget), "realized_pnl": "0", "fees_total": "0", "slippage_total": "0",
            "open_trade": None, "closed_trades": [], "booked_setup_ids": [], "rejections": [],
            "hwm_equity": str(budget), "max_drawdown_pct": "0", "day_start_equity": {},
            "latched_days": {}, "identity": identity.stamp(),
        }
        led = cls(root, book_id, st)
        led._write("CREATED", {"starting_budget": str(budget), "ledger_kind": ledger_kind})
        return led

    @classmethod
    def load(cls, root: DataRoot, book_id: str, expect_kind: str = PAPER) -> "BookLedger":
        book_spec(book_id)
        st = root.read_json(*cls._file(book_id))
        if st is None:
            raise BookMissing("V6 book %s does not exist (not initialised)" % book_id)
        if st.get("ledger_kind", PAPER) != expect_kind:
            raise LedgerCorrupt("book file %s is a %s ledger, expected %s" % (book_id, st.get("ledger_kind", PAPER),
                                                                           expect_kind))
        if st.get("schema_version") != SCHEMA_VERSION:
            raise LedgerCorrupt("book %s: schema_version %r, expected %d" % (book_id, st.get("schema_version"),
                                                                           SCHEMA_VERSION))
        if st.get("book_id") != book_id:
            raise LedgerCorrupt("book file %s holds book %r" % (book_id, st.get("book_id")))
        led = cls(root, book_id, st)
        led.reconcile()
        return led

    # ------------------------------------------------------------ invariants
    def reconcile(self) -> Dict[str, str]:
        st = self.state
        start = D(st["starting_budget"])
        closed = st["closed_trades"]
        realized = sum((D(t["realized_pnl"]) for t in closed), Decimal(0))
        fees = sum((D(t["entry_fee"]) + D(t["exit_fee"]) for t in closed), Decimal(0))
        open_fee = D(st["open_trade"]["entry_fee"]) if st["open_trade"] else Decimal(0)
        exp_cash = start + realized - open_fee
        checks = {"cash": (D(st["cash"]), exp_cash), "realized_pnl": (D(st["realized_pnl"]), realized),
                  "fees_total": (D(st["fees_total"]), fees + open_fee)}
        bad = {k: (str(a), str(b)) for k, (a, b) in checks.items() if a != b}
        if bad:
            raise LedgerCorrupt("book %s does not reconcile: %s" % (self.book_id, bad))
        ids = st["booked_setup_ids"]
        if len(ids) != len(set(ids)):
            raise LedgerCorrupt("book %s: a setup id is booked twice" % self.book_id)
        for t in closed:
            if t["setup_id"] not in ids:
                raise LedgerCorrupt("book %s: closed trade %s is not in booked_setup_ids" % (self.book_id, t["setup_id"]))
        return {"cash": str(exp_cash), "realized_pnl": str(realized), "fees_total": str(fees + open_fee)}

    def _write(self, event: str, detail: Dict[str, Any]) -> None:
        self.reconcile()
        self.state["seq"] += 1
        self.root.write_json_atomic(self.state, *self._file(self.book_id))
        self.root.append_jsonl(dict(identity.stamp(), book_id=self.book_id, seq=self.state["seq"], event=event,
                                    at=_now(), detail=detail), *self._events(self.book_id))

    # ------------------------------------------------------------ queries
    @property
    def open_trade(self) -> Optional[Dict[str, Any]]:
        return self.state["open_trade"]

    def seen(self, setup_id: str) -> bool:
        return setup_id in self.state["booked_setup_ids"] or any(r["setup_id"] == setup_id
                                                                 for r in self.state["rejections"])

    def cash(self) -> Decimal:
        return D(self.state["cash"])

    # ------------------------------------------------------------ bookings
    def book_entry(self, trade: Dict[str, Any]) -> None:
        sid = trade["setup_id"]
        if sid in self.state["booked_setup_ids"]:
            raise DuplicateExecution("setup %s is already booked in %s" % (sid, self.book_id))
        if self.state["open_trade"] is not None:
            raise LedgerError("book %s already has an open trade (%s)" % (self.book_id,
                                                                          self.state["open_trade"]["setup_id"]))
        fee = D(trade["entry_fee"])
        t = dict(trade, identity=identity.stamp(), status="ENTERED")
        self.state["open_trade"] = t
        self.state["booked_setup_ids"].append(sid)
        self.state["cash"] = str(self.cash() - fee)
        self.state["fees_total"] = str(D(self.state["fees_total"]) + fee)
        self.state["slippage_total"] = str(D(self.state["slippage_total"]) + D(trade.get("entry_slippage", "0")))
        self._write("ENTRY", {"setup_id": sid, "instrument": trade["instrument"], "entry_fill": trade["entry_fill"],
                              "quantity": trade["quantity"], "entry_fee": trade["entry_fee"]})

    def book_exit(self, setup_id: str, exit_fields: Dict[str, Any]) -> Dict[str, Any]:
        ot = self.state["open_trade"]
        if ot is None or ot["setup_id"] != setup_id:
            raise LedgerError("book %s has no open trade %s" % (self.book_id, setup_id))
        gross, xfee = D(exit_fields["gross_pnl"]), D(exit_fields["exit_fee"])
        realized = gross - D(ot["entry_fee"]) - xfee
        if D(exit_fields["realized_pnl"]) != realized:
            raise LedgerCorrupt("exit of %s: Module E realized %s != gross - fees %s" % (setup_id,
                                                                                       exit_fields["realized_pnl"], realized))
        closed = dict(ot)
        closed.update(exit_fields)
        closed["realized_pnl"] = str(realized)
        self.state["open_trade"] = None
        self.state["closed_trades"].append(closed)
        self.state["cash"] = str(self.cash() + gross - xfee)
        self.state["realized_pnl"] = str(D(self.state["realized_pnl"]) + realized)
        self.state["fees_total"] = str(D(self.state["fees_total"]) + xfee)
        self.state["slippage_total"] = str(D(self.state["slippage_total"]) + D(exit_fields.get("exit_slippage", "0")))
        eq = self.cash()
        self._update_drawdown(eq)
        self._write("EXIT", {"setup_id": setup_id, "status": exit_fields["status"], "exit_fill": exit_fields["exit_fill"],
                             "realized_pnl": str(realized)})
        return closed

    def record_rejection(self, setup_id: str, instrument: str, code: str, detail: str) -> None:
        if self.seen(setup_id):
            raise DuplicateExecution("setup %s already has a booking decision in %s" % (setup_id, self.book_id))
        self.state["rejections"].append({"setup_id": setup_id, "instrument": instrument, "code": code,
                                         "detail": detail, "at": _now()})
        self._write("REJECTED", {"setup_id": setup_id, "code": code})

    def mark_day_start(self, day: str, equity: Decimal) -> None:
        if day in self.state["day_start_equity"]:
            return
        self.state["day_start_equity"][day] = str(equity)
        self._write("DAY_START", {"day": day, "equity": str(equity)})

    def latch_day(self, day: str, reason: str) -> None:
        if day in self.state["latched_days"]:
            return
        self.state["latched_days"][day] = reason
        self._write("DAILY_LOSS_LATCH", {"day": day, "reason": reason})

    def _update_drawdown(self, equity: Decimal) -> None:
        hwm = max(D(self.state["hwm_equity"]), equity)
        self.state["hwm_equity"] = str(hwm)
        dd = (hwm - equity) / hwm * 100 if hwm > 0 else Decimal(0)
        if dd > D(self.state["max_drawdown_pct"]):
            self.state["max_drawdown_pct"] = str(dd.quantize(Decimal("0.0001")))

    # ------------------------------------------------------------ view
    def summary(self, mtm: Optional[Dict[str, Any]] = None, day: Optional[str] = None) -> Dict[str, Any]:
        """Dashboard figures. `mtm` = {"status": "OK", "unrealized": .., "est_exit_fee": .., "mark": ..} for the open
        trade, or {"status": "UNSCORABLE", "reason": ..}. Without a valid mark an open book has no equity figure:
        it is reported as UNSCORABLE, never as a made-up number."""
        st = self.state
        start, cash = D(st["starting_budget"]), self.cash()
        ot = st["open_trade"]
        closed = st["closed_trades"]
        wins = sum(1 for t in closed if D(t["realized_pnl"]) > 0)
        out: Dict[str, Any] = {
            "book_id": self.book_id, "label": st["label"], "currency": st["currency"], "market": st["market"],
            "starting_budget": str(start), "cash": str(cash), "realized_pnl": st["realized_pnl"],
            "fees_total": st["fees_total"], "slippage_total": st["slippage_total"],
            "open_positions": 1 if ot else 0, "closed_trades": len(closed),
            "win_rate_pct": None if not closed else str((Decimal(wins) * 100 / len(closed)).quantize(Decimal("0.01"))),
            "max_drawdown_pct": st["max_drawdown_pct"], "rejections": len(st["rejections"]), "seq": st["seq"],
            "created_at": st["created_at"], "identity": identity.stamp(),
        }
        committed = D(ot["required_margin"]) if ot and ot.get("required_margin") is not None else Decimal(0)
        out["committed_capital"] = str(committed)
        out["available_balance"] = str(cash - committed)
        if ot is None:
            equity, unreal, est_fee, status = cash, Decimal(0), Decimal(0), "OK"
        elif mtm and mtm.get("status") == "OK":
            unreal, est_fee, status = D(mtm["unrealized"]), D(mtm["est_exit_fee"]), "OK"
            equity = cash + unreal - est_fee
        else:
            equity = unreal = est_fee = None
            status = "UNSCORABLE"
        out.update({"mtm_status": status, "mtm_reason": None if status == "OK" else (mtm or {}).get("reason", "no mark"),
                    "unrealized_pnl": _s(unreal), "estimated_exit_fee": _s(est_fee), "equity": _s(equity),
                    "total_pnl": _s(None if equity is None else equity - start)})
        if day is not None and equity is not None and day in st["day_start_equity"]:
            out["daily_pnl"] = str(equity - D(st["day_start_equity"][day]))
        else:
            out["daily_pnl"] = None
        out["current_drawdown_pct"] = None if equity is None else str(
            ((max(D(st["hwm_equity"]), equity) - equity) / max(D(st["hwm_equity"]), equity) * 100).quantize(Decimal("0.0001")))
        return out

    def trades(self) -> List[Dict[str, Any]]:
        return list(self.state["closed_trades"]) + ([self.state["open_trade"]] if self.state["open_trade"] else [])
