"""Backtest runner: validated datasets -> the V6 paper pipeline -> an isolated simulation ledger -> metrics.

Determinism: the run id is a hash of the engine version, the configuration, every dataset's SHA-256 and symbol, and
the date range. The same inputs always give the same run id and the same results (results.json holds no wall-clock
time; `results_sha256` lets two runs be compared byte for byte).

No look-ahead: the whole timeline is built up front only to VALIDATE it; the pipeline receives one step at a time
(a candle, or a data event for a gap) and nothing it is given depends on a later step.

Restart: every step is journaled before it is applied (write-ahead, `Portfolio`). Re-running an interrupted run
replays its journal (verifying every booking, never booking twice) and continues with the next step.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from scanner_v6.exit import execution as E

from .. import identity
from ..ledger import BACKTEST, BookLedger
from ..paths import DataRoot
from ..portfolio import InstrumentSpec, Portfolio
from . import ENGINE_VERSION, metrics
from .config import BacktestConfig, describe
from .dataset import Dataset, load_dataset

KIND = "BACKTEST (simulation on historical data; not paper trading, not live)"
CREATED, RUNNING, COMPLETE, FAILED = "CREATED", "RUNNING", "COMPLETE", "FAILED"


class BacktestError(RuntimeError):
    pass


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def run_id_for(cfg: BacktestConfig, datasets: List[Dataset], start: Optional[date], end: Optional[date]) -> str:
    key = {"engine": ENGINE_VERSION, "config": cfg.digest(), "data": sorted((d.symbol, d.sha256) for d in datasets),
           "start": start.isoformat() if start else None, "end": end.isoformat() if end else None}
    return "bt-" + hashlib.sha256(_canon(key)).hexdigest()[:16]


def backtests_root(root: DataRoot) -> DataRoot:
    return DataRoot(root.path("backtests"))


def prepare(cfg: BacktestConfig, data: Dict[str, str], start: Optional[date], end: Optional[date],
            source: Optional[str] = None) -> Tuple[List[Dataset], Any]:
    if not data:
        raise BacktestError("at least one SYMBOL=FILE dataset is required")
    for sym in data:
        if not (sym and sym.replace(".", "").replace("-", "").isalnum() and sym == sym.upper()):
            raise BacktestError("symbol %r must be upper-case letters/digits ('.' and '-' allowed)" % sym)
    if cfg.session_spec.get("calendar") == "NYSE" and not (start and end):
        raise BacktestError("the NYSE calendar needs --start and --end (it covers explicit years only)")
    session = cfg.session(start, end) if (start and end) else cfg.session(date.today(), date.today())
    datasets = [load_dataset(path, sym, cfg.tf, session, start, end, source, cfg.gap_policy)
                for sym, path in sorted(data.items())]
    return datasets, session


def _timeline(datasets: List[Dataset]) -> List[Tuple[datetime, int, str, str, Any]]:
    """(ts, order, symbol, kind, payload): a gap's DATA_INTERRUPTED (at the close of the last bar before it) and
    DATA_RESUMED (at the open of the next bar) precede that bar; ties across symbols resolve by symbol."""
    steps = []
    for ds in datasets:
        gaps = {b: a for a, b in ds.gaps}
        for c in ds.candles():
            if c.ts in gaps:
                steps.append((gaps[c.ts], 0, ds.symbol, "DATA_INTERRUPTED", gaps[c.ts]))
                steps.append((c.ts, 1, ds.symbol, "DATA_RESUMED", c.ts))
            steps.append((c.ts, 2, ds.symbol, "candle", c))
    steps.sort(key=lambda s: (s[0], s[1], s[2]))
    return steps


class BacktestRun:
    def __init__(self, root: DataRoot, cfg: BacktestConfig, data: Dict[str, str], start: Optional[date] = None,
                 end: Optional[date] = None, source: Optional[str] = None):
        self.cfg, self.start, self.end = cfg, start, end
        self.datasets, self.session = prepare(cfg, data, start, end, source)
        self.run_id = run_id_for(cfg, self.datasets, start, end)
        self.home = backtests_root(root)
        self.run = DataRoot(self.home.path(self.run_id))
        self.specs = [InstrumentSpec(ds.symbol, cfg.book_id, cfg.timeframe, cfg.market_config(ds.symbol, self.session),
                                     cfg.execution_config(self.session), data_source=ds.source)
                      for ds in self.datasets]
        for s in self.specs:
            miss = s.execution.missing(s.market)
            if miss:
                raise BacktestError("Module E configuration incomplete for %s: %s" % (s.instrument_id, ", ".join(miss)))

    # ------------------------------------------------------------ metadata
    def meta(self, status: str, **extra: Any) -> Dict[str, Any]:
        old = self.run.read_json("run.json") or {}
        m = {"run_id": self.run_id, "kind": KIND, "status": status, "engine_version": ENGINE_VERSION,
             "created_at": old.get("created_at") or datetime.now(timezone.utc).isoformat(),
             "updated_at": datetime.now(timezone.utc).isoformat(), "identity": identity.stamp(),
             "scanner_sha256": identity.scanner_identity().get("package_sha256"),
             "range": {"start": self.start.isoformat() if self.start else None,
                       "end": self.end.isoformat() if self.end else None},
             "symbols": [d.symbol for d in self.datasets], "config": describe(self.cfg),
             "datasets": [d.integrity for d in self.datasets], "book_id": self.cfg.book_id,
             "paper_only": True, "places_orders": False}
        for k in ("results_sha256", "error", "steps_total", "steps_done"):
            if k in old:
                m[k] = old[k]
        m.update(extra)
        self.run.write_json_atomic(m, "run.json")
        return m

    # ------------------------------------------------------------ execution
    def execute(self, max_steps: Optional[int] = None,
                on_step: Optional[Callable[[int, Portfolio], None]] = None) -> Dict[str, Any]:
        """Run (or resume, or return the finished result of) this backtest. `max_steps` stops early and leaves the run
        RUNNING, exactly like an interrupted process (used to test restart)."""
        existing = self.run.read_json("run.json") if self.run.exists() else None
        if existing and existing.get("status") == COMPLETE:
            return self.load_results()
        timeline = _timeline(self.datasets)
        if not existing:
            os.makedirs(self.run.root, exist_ok=True)
            self.meta(CREATED, steps_total=len(timeline), steps_done=0)
            BookLedger.create(self.run, self.cfg.book_id, owner_authorised=True, created_by="backtest " + self.run_id,
                              ledger_kind=BACKTEST, starting_budget=self.cfg.starting_equity)
        ledger = BookLedger.load(self.run, self.cfg.book_id, expect_kind=BACKTEST)
        pf = Portfolio(self.run, ledger, self.specs)
        done = pf.recover()                                   # 0 for a fresh run
        curve = self.run.read_jsonl("equity.jsonl")
        n_candles = sum(1 for s in timeline[:done] if s[3] == "candle")
        if len(curve) > n_candles:
            raise BacktestError("equity curve has more points than journaled candles: run %s is corrupt" % self.run_id)
        if len(curve) == n_candles - 1:                       # interrupted between journal append and curve append
            self._point(pf, ledger, timeline[done - 1], done - 1)
        self.meta(RUNNING, steps_total=len(timeline), steps_done=done)
        try:
            for i in range(done, len(timeline)):
                if max_steps is not None and i - done >= max_steps:
                    self.meta(RUNNING, steps_done=i)
                    return {"run_id": self.run_id, "status": RUNNING, "steps_done": i, "steps_total": len(timeline)}
                ts, _, sym, kind, payload = timeline[i]
                if kind == "candle":
                    pf.on_candle(sym, payload)
                    self._point(pf, ledger, timeline[i], i)
                elif kind == "DATA_INTERRUPTED":
                    pf.on_data_interrupted(sym, payload)
                else:
                    pf.on_data_resumed(sym, payload)
                if on_step is not None:
                    on_step(i, pf)
        except Exception as e:
            self.meta(FAILED, error="%s: %s" % (type(e).__name__, e))
            raise
        return self._finish(pf, ledger, len(timeline))

    def _point(self, pf: Portfolio, ledger: BookLedger, step: Tuple, i: int) -> None:
        s = ledger.summary(pf.mtm if ledger.open_trade else None)
        self.run.append_jsonl({"step": i, "ts": step[0].isoformat(), "symbol": step[2], "equity": s["equity"],
                               "cash": s["cash"], "status": s["mtm_status"], "open": s["open_positions"]},
                              "equity.jsonl")

    def _finish(self, pf: Portfolio, ledger: BookLedger, steps: int) -> Dict[str, Any]:
        curve = self.run.read_jsonl("equity.jsonl")
        summary = ledger.summary(pf.mtm if ledger.open_trade else None)
        trades = []
        for t in ledger.trades():
            rec = pf.streams[t["instrument"]].record(t["setup_id"])
            trades.append(dict({k: v for k, v in t.items() if k != "identity"},
                               stage_path=[[h.status, h.index, h.ts.isoformat()] for h in rec.history],
                               realized_r=None if t["status"] == E.ENTERED or not t.get("loss_estimate") else
                               str((metrics._d(t["realized_pnl"]) / metrics._d(t["loss_estimate"])).quantize(metrics.Q4))))
        shadow = sorted(pf.shadow)
        results = {
            "run_id": self.run_id, "kind": KIND, "engine_version": ENGINE_VERSION,
            "metrics": metrics.compute(ledger.state, summary, curve, trades, self.cfg.half_spread_ticks,
                                       self.cfg.tick_size),
            "trades": trades,
            "rejections": ledger.state["rejections"],
            "shadow_setups": shadow,
            "equity_curve": metrics.sample([{"ts": p["ts"], "equity": p["equity"]} for p in curve]),
            "datasets": [{"symbol": d.symbol, "sha256": d.sha256, "source": d.source, "rows": len(d.rows),
                          "gaps": len(d.gaps)} for d in self.datasets],
            "config_sha256": self.cfg.digest(),
        }
        results = json.loads(json.dumps(results, default=str))
        for t in results["rejections"]:
            t.pop("at", None)                                   # wall clock: excluded from the reproducible result
        digest = hashlib.sha256(_canon(results)).hexdigest()
        self.run.write_json_atomic(results, "results.json")
        self.meta(COMPLETE, steps_done=steps, results_sha256=digest, error=None)
        return dict(results, status=COMPLETE, results_sha256=digest)

    def load_results(self) -> Dict[str, Any]:
        r = self.run.read_json("results.json")
        m = self.run.read_json("run.json") or {}
        if r is None:
            raise BacktestError("run %s is marked COMPLETE but has no results.json" % self.run_id)
        if hashlib.sha256(_canon(r)).hexdigest() != m.get("results_sha256"):
            raise BacktestError("run %s: results.json does not match its recorded SHA-256" % self.run_id)
        return dict(r, status=COMPLETE, results_sha256=m["results_sha256"])


# ------------------------------------------------------------ read side (CLI and API)
def list_runs(root: DataRoot) -> List[Dict[str, Any]]:
    home = backtests_root(root)
    if not home.exists():
        return []
    out = []
    for name in sorted(os.listdir(home.root)):
        m = home.read_json(name, "run.json")
        if not m:
            continue
        r = home.read_json(name, "results.json") if m.get("status") == COMPLETE else None
        out.append({"run_id": m["run_id"], "status": m["status"], "created_at": m.get("created_at"),
                    "updated_at": m.get("updated_at"), "symbols": m.get("symbols"), "range": m.get("range"),
                    "book_id": m.get("book_id"), "label": (m.get("config") or {}).get("label"),
                    "error": m.get("error"), "metrics": (r or {}).get("metrics")})
    out.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return out


def get_run(root: DataRoot, run_id: str) -> Optional[Dict[str, Any]]:
    if not (run_id.startswith("bt-") and len(run_id) == 19 and all(ch in "0123456789abcdef" for ch in run_id[3:])):
        raise KeyError(run_id)
    home = backtests_root(root)
    m = home.read_json(run_id, "run.json") if home.exists() else None
    if m is None:
        return None
    return {"run": m, "results": home.read_json(run_id, "results.json")}
