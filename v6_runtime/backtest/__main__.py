"""V6 backtest CLI (PAPER-ONLY research; no broker, no orders).

  python -m v6_runtime.backtest validate --config CFG.json --data AAPL=aapl_5m.csv [--start D --end D] [--source S]
  python -m v6_runtime.backtest run      --config CFG.json --data AAPL=aapl_5m.csv [--data MSFT=...] \\
                                         [--start 2026-01-05 --end 2026-03-31] [--source "..."] [--root DIR]
  python -m v6_runtime.backtest list     [--root DIR]
  python -m v6_runtime.backtest show     RUN_ID [--trades] [--equity] [--root DIR]
  python -m v6_runtime.backtest fetch    --symbol AAPL --timeframe 5m --start D --end D --feed iex --out FILE.csv

--root defaults to the V6 data root ($V6_DATA_ROOT or /var/lib/trader-v6); runs are written to <root>/backtests/<id>/.
`fetch` uses the V6 DATA-ONLY Alpaca credential (/etc/trader-v6/alpaca-data.json) and refuses without it.
Exit codes: 0 ok · 2 invalid configuration or data · 3 data source NOT CONNECTED · 4 run failed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from ..paths import DataRoot, PathGuardError
from . import config as bcfg
from .dataset import DatasetError, write_csv
from .engine import BacktestError, BacktestRun, get_run, list_runs, prepare


def _date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError("dates are YYYY-MM-DD, got %r" % s) from None


def _data(items: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for it in items or []:
        if "=" not in it:
            raise BacktestError("--data takes SYMBOL=FILE, got %r" % it)
        sym, path = it.split("=", 1)
        if sym in out:
            raise BacktestError("symbol %s given twice" % sym)
        out[sym] = path
    return out


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=1, default=str))


def fetch_to_csv(client, symbol: str, timeframe: str, start: date, end: date, out: str, feed: str,
                 sessions=None) -> Dict[str, object]:
    """Download bars with an AlpacaBars client (DATA host, GET only) and write a dataset + sidecar. With `sessions`
    ((open, close) UTC pairs, e.g. the NYSE regular sessions) only bars lying fully inside a session are kept; the
    extended-hours bars dropped are counted in the metadata. Nothing is filled in or adjusted."""
    t0 = datetime.combine(start, datetime.min.time(), timezone.utc)
    t1 = datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc)
    bars = client.fetch(symbol, timeframe, t0, t1)
    tf = timedelta(minutes={"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}[timeframe])
    keep = [b for b in bars if sessions is None or any(o <= b.start and b.start + tf <= c for o, c in sessions)]
    rows = [(b.start, b.open, b.high, b.low, b.close, b.volume) for b in keep]
    label = {"iex": "IEX real-time feed (single venue IEX, NOT the consolidated tape)",
             "sip": "SIP feed (consolidated tape)"}[feed]
    meta = {"source": "alpaca market data v2 bars, feed=%s, adjustment=raw: %s" % (feed, label), "symbol": symbol,
            "feed": feed, "timeframe": timeframe, "requested": {"start": start.isoformat(), "end": end.isoformat()},
            "regular_session_only": sessions is not None, "bars_received": len(bars),
            "bars_dropped_outside_session": len(bars) - len(keep),
            "fetched_at": datetime.now(timezone.utc).isoformat()}
    write_csv(out, rows, meta)
    return {"file": out, "rows": len(rows), "dropped_outside_session": len(bars) - len(keep), "source": meta["source"]}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m v6_runtime.backtest", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "run"):
        s = sub.add_parser(name)
        s.add_argument("--config", required=True)
        s.add_argument("--data", action="append", required=True, metavar="SYMBOL=FILE")
        s.add_argument("--start", type=_date)
        s.add_argument("--end", type=_date)
        s.add_argument("--source", help="dataset source label (overrides the .meta.json sidecar)")
        s.add_argument("--root")
    s = sub.add_parser("list")
    s.add_argument("--root")
    s = sub.add_parser("show")
    s.add_argument("run_id")
    s.add_argument("--trades", action="store_true")
    s.add_argument("--equity", action="store_true")
    s.add_argument("--root")
    s = sub.add_parser("fetch")
    s.add_argument("--symbol", required=True)
    s.add_argument("--timeframe", required=True)
    s.add_argument("--start", type=_date, required=True)
    s.add_argument("--end", type=_date, required=True)
    s.add_argument("--feed", required=True, choices=("iex", "sip"))
    s.add_argument("--out", required=True)
    s.add_argument("--credential")
    a = p.parse_args(argv)
    try:
        root = DataRoot(getattr(a, "root", None)) if a.cmd != "fetch" else None
        if a.cmd == "validate":
            cfg = bcfg.load(a.config)
            ds, _ = prepare(cfg, _data(a.data), a.start, a.end, a.source)
            _print({"status": "VALID", "config": bcfg.describe(cfg), "datasets": [d.integrity for d in ds]})
            return 0
        if a.cmd == "run":
            cfg = bcfg.load(a.config)
            run = BacktestRun(root, cfg, _data(a.data), a.start, a.end, a.source)
            res = run.execute()
            _print({"run_id": res["run_id"], "status": res["status"], "results_sha256": res["results_sha256"],
                    "kind": res["kind"], "metrics": res["metrics"], "run_dir": run.run.root})
            return 0
        if a.cmd == "list":
            _print(list_runs(root))
            return 0
        if a.cmd == "show":
            try:
                r = get_run(root, a.run_id)
            except KeyError:
                r = None
            if r is None:
                print("no backtest run %s under %s" % (a.run_id, root.root), file=sys.stderr)
                return 2
            res = r["results"] or {}
            out = {"run": r["run"], "metrics": res.get("metrics")}
            if a.trades:
                out["trades"] = res.get("trades")
                out["rejections"] = res.get("rejections")
            if a.equity:
                out["equity_curve"] = res.get("equity_curve")
            _print(out)
            return 0
        if a.cmd == "fetch":
            from ..data.alpaca import AlpacaBars, CredentialError, DEFAULT_CREDENTIAL_FILE, load_credential
            try:
                cred = load_credential(a.credential or DEFAULT_CREDENTIAL_FILE)
            except CredentialError as e:
                print("NOT CONNECTED: %s" % e, file=sys.stderr)
                return 3
            if cred is None:
                print("NOT CONNECTED: the V6 DATA-ONLY Alpaca credential is not supplied (%s)"
                      % (a.credential or DEFAULT_CREDENTIAL_FILE), file=sys.stderr)
                return 3
            from .. import us_stocks
            sess = us_stocks.trading_sessions(us_stocks.load_calendar(), a.start, a.end)
            _print(fetch_to_csv(AlpacaBars(cred, a.feed), a.symbol, a.timeframe, a.start, a.end, a.out, a.feed, sess))
            return 0
    except (bcfg.BacktestConfigError, DatasetError, BacktestError, PathGuardError) as e:
        print("INVALID: %s" % e, file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - reported with its type; the run is marked FAILED by the engine
        print("FAILED: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 4
    return 2


if __name__ == "__main__":
    sys.exit(main())
