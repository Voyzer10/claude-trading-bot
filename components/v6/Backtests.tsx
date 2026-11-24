"use client";

// Backtesting section: SIMULATION runs on historical data (each with its own simulation ledger). Read-only; runs are
// started from the CLI (python -m v6_runtime.backtest run ...). Nothing here touches a paper book.
import { Fragment, useEffect, useState } from "react";
import { errText, v6Get } from "@/lib/v6/api";
import type { BacktestDetail, BacktestList, BacktestMetrics } from "@/lib/v6/types";

const KEYS: [string, string][] = [
  ["starting_equity", "Starting equity"], ["ending_equity", "Ending equity"], ["gross_pnl", "Gross P&L"],
  ["net_pnl", "Net P&L"], ["return_pct", "Return %"], ["total_trades", "Trades"], ["winning_trades", "Wins"],
  ["losing_trades", "Losses"], ["win_rate_pct", "Win rate %"], ["average_win", "Average win"],
  ["average_loss", "Average loss"], ["profit_factor", "Profit factor"], ["max_drawdown", "Max drawdown"],
  ["max_drawdown_pct", "Max drawdown %"], ["average_planned_net_rr", "Avg planned net R:R"],
  ["average_realized_r", "Avg realized R"], ["fees_total", "Fees"], ["slippage_total", "Slippage (incl. spread)"],
  ["open_trades_at_end", "Open at end"],
];
const TRADE_COLS = ["setup_id", "instrument", "side", "entry_ts", "entry_fill", "sl", "tp", "quantity", "exit_ts",
  "exit_fill", "status", "gross_pnl", "entry_fee", "exit_fee", "realized_pnl", "realized_r"];

function val(v: unknown) {
  if (v === null || v === undefined) return "—";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

function Curve({ pts }: { pts: { ts: string; equity: string | null }[] }) {
  const ys = pts.map((p) => (p.equity === null ? null : Number(p.equity)));
  const ok = ys.filter((y): y is number => y !== null);
  if (ok.length < 2) return <p className="muted small">Not enough scorable equity points to draw a curve.</p>;
  const lo = Math.min(...ok), hi = Math.max(...ok), W = 640, H = 160, pad = 4;
  const x = (i: number) => pad + (i * (W - 2 * pad)) / (pts.length - 1);
  const y = (v: number) => (hi === lo ? H / 2 : pad + ((hi - v) * (H - 2 * pad)) / (hi - lo));
  let d = "";
  ys.forEach((v, i) => { if (v !== null) d += `${d && ys[i - 1] !== null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; });
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Equity curve"
        style={{ maxWidth: W, border: "1px solid var(--line)", borderRadius: 8 }}>
        <path d={d} fill="none" stroke="var(--accent)" strokeWidth={2} />
      </svg>
      <figcaption className="muted small">Equity {lo.toFixed(2)} – {hi.toFixed(2)} · {pts[0].ts} → {pts[pts.length - 1].ts}</figcaption>
    </figure>
  );
}

function Metrics({ m }: { m: BacktestMetrics }) {
  return (
    <div className="grid-2 small">
      {KEYS.map(([k, label]) => (
        <Fragment key={k}>
          <div>{label}</div>
          <div className="mono">{val(m[k])}{k === "profit_factor" && m.profit_factor_note ? ` (${m.profit_factor_note})` : ""}</div>
        </Fragment>
      ))}
    </div>
  );
}

export default function Backtests() {
  const [list, setList] = useState<BacktestList | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<BacktestDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { v6Get<BacktestList>("/backtests").then(setList).catch((e) => setErr(errText(e))); }, []);
  useEffect(() => {
    if (!sel) return;
    setDetail(null);
    v6Get<BacktestDetail>(`/backtests/${sel}`).then(setDetail).catch((e) => setErr(errText(e)));
  }, [sel]);

  return (
    <section className="panel">
      <div className="notice small" role="note">
        BACKTEST: simulation on historical data with its own simulation ledger. Not paper trading, not live results.
        Configuration values used by a run are research assumptions unless marked approved.
      </div>
      {err && <div className="notice bad">V6 API: {err}</div>}
      {list && list.runs.length === 0 && (
        <p className="muted">No backtest runs yet. Run one from the VPS: <span className="mono">python -m v6_runtime.backtest run --config … --data SYMBOL=FILE --start … --end …</span></p>
      )}
      {list && list.runs.length > 0 && (
        <div className="tablewrap">
          <table>
            <thead><tr><th>Run</th><th>Status</th><th>Symbols</th><th>Range</th><th>Trades</th><th>Net P&amp;L</th><th>Return %</th><th>Max DD %</th></tr></thead>
            <tbody>
              {list.runs.map((r) => (
                <tr key={r.run_id} aria-selected={sel === r.run_id}>
                  <td><button className="chip mono" onClick={() => setSel(r.run_id)}>{r.run_id}</button></td>
                  <td>{r.status}{r.error ? ` · ${r.error}` : ""}</td>
                  <td>{(r.symbols ?? []).join(", ")}</td>
                  <td className="mono small">{r.range?.start ?? "—"} → {r.range?.end ?? "—"}</td>
                  <td>{val(r.metrics?.total_trades)}</td>
                  <td className="mono">{val(r.metrics?.net_pnl)}</td>
                  <td className="mono">{val(r.metrics?.return_pct)}</td>
                  <td className="mono">{val(r.metrics?.max_drawdown_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {detail && (
        <div>
          <h3 className="mono">{detail.run.run_id} · {detail.run.status}</h3>
          {detail.metrics ? <Metrics m={detail.metrics} /> : <p className="muted">No results (run not complete).</p>}
          {detail.equity_curve && <Curve pts={detail.equity_curve} />}
          <h4>Trades</h4>
          {detail.trades && detail.trades.length ? (
            <div className="tablewrap"><table>
              <thead><tr>{TRADE_COLS.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{detail.trades.map((t, i) => (
                <tr key={i}>{TRADE_COLS.map((c) => <td key={c} className="mono small">{val(t[c])}</td>)}</tr>))}
              </tbody>
            </table></div>
          ) : <p className="muted small">No trades.</p>}
          <h4>Datasets</h4>
          <pre className="mono small" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(detail.run.datasets ?? [], null, 1)}</pre>
        </div>
      )}
    </section>
  );
}
