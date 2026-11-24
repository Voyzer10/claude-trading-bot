"""Pure view functions (no web framework): each returns JSON-ready data read from the V6 data root only."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional

from v6_runtime import identity, status
from v6_runtime.backtest import engine as backtest
from v6_runtime.books import BOOKS
from v6_runtime.ledger import BookLedger, LedgerError
from v6_runtime.paths import DataRoot


def _root() -> DataRoot:
    return DataRoot()


def health() -> Dict[str, Any]:
    r = _root()
    return {"ok": True, "service": "trader-v6-api", "paper_only": True, "data_root_exists": r.exists(),
            "scanner": identity.scanner_identity()["status"]}


def get_status() -> Dict[str, Any]:
    return status.overall(_root())


def get_identity() -> Dict[str, Any]:
    o = status.overall(_root())
    return {**identity.scanner_identity(), "label": o["scanner"]["label"], "reason": o["scanner"]["reason"],
            "runner": o["runner"]["state"], "verified_by": "backend import of scanner_v6"}


def get_books() -> Dict[str, Any]:
    r = _root()
    return {b: status.book_status(r, b) for b in BOOKS}


def _ledger(book_id: str) -> Optional[BookLedger]:
    if book_id not in BOOKS:
        raise KeyError(book_id)
    r = _root()
    if not r.exists() or not BookLedger.exists(r, book_id):
        return None
    return BookLedger.load(r, book_id)


def get_book(book_id: str) -> Dict[str, Any]:
    r = _root()
    st = status.book_status(r, book_id)
    try:
        led = _ledger(book_id)
    except LedgerError as e:
        return dict(st, trades=None, rejections=None, reason=str(e))
    if led is None:
        return dict(st, trades=None, rejections=None)
    return dict(st, trades=led.trades(), rejections=led.state["rejections"])


def get_signals(book_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    if book_id not in BOOKS:
        raise KeyError(book_id)
    r = _root()
    rows = r.read_jsonl("signals", "%s.jsonl" % book_id) if r.exists() else []
    return rows[-max(1, min(int(limit), 2000)):][::-1]


def get_data_health() -> Dict[str, Any]:
    r = _root()
    rs = status.runner_state(r) if r.exists() else {"state": "NOT_ACTIVE", "heartbeat": None,
                                                    "reason": "V6 data root missing"}
    hb = rs.get("heartbeat") or {}
    return {"runner": rs["state"], "reason": rs.get("reason"), "feeds": hb.get("feeds", {}), "at": hb.get("at")}


def get_performance(book_id: str) -> Dict[str, Any]:
    led = _ledger(book_id)
    if led is None:
        return {"book_id": book_id, "state": "NOT_INITIALISED", "instruments": None}
    per: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"trades": 0, "wins": 0, "realized_pnl": Decimal(0),
                                                          "fees": Decimal(0)})
    for t in led.state["closed_trades"]:
        p = per[t["instrument"]]
        p["trades"] += 1
        p["wins"] += 1 if Decimal(t["realized_pnl"]) > 0 else 0
        p["realized_pnl"] += Decimal(t["realized_pnl"])
        p["fees"] += Decimal(t["entry_fee"]) + Decimal(t["exit_fee"])
    return {"book_id": book_id, "state": "LOADED", "instruments": {
        k: {"trades": v["trades"], "wins": v["wins"], "realized_pnl": str(v["realized_pnl"]), "fees": str(v["fees"]),
            "win_rate_pct": str((Decimal(v["wins"]) * 100 / v["trades"]).quantize(Decimal("0.01")))}
        for k, v in sorted(per.items())}}


# ------------------------------------------------------------ backtests (simulation runs, separate from paper books)
def list_backtests() -> Dict[str, Any]:
    r = _root()
    return {"kind": backtest.KIND, "runs": backtest.list_runs(r) if r.exists() else []}


def get_backtest(run_id: str) -> Dict[str, Any]:
    r = _root()
    got = backtest.get_run(r, run_id) if r.exists() else None   # KeyError for a malformed id
    if got is None:
        raise KeyError(run_id)
    res = got["results"] or {}
    return {"kind": backtest.KIND, "run": got["run"], "metrics": res.get("metrics"), "trades": res.get("trades"),
            "rejections": res.get("rejections"), "equity_curve": res.get("equity_curve")}
