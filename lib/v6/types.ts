// Shapes returned by api_v6 (all money values are exact decimal strings, or null when not available).
export type Money = string | null;

export interface Scanner {
  label: string; // "V6 SMC Scanner" | "V6 NOT ACTIVE" | "V6 NOT CONNECTED" (decided by the backend)
  reason: string | null;
  scanner_name: string | null;
  scanner_version: string | null;
  execution_mode: string | null;
  paper_only: boolean | null;
  places_orders: boolean | null;
  package_sha256: string | null;
  pipeline?: string[];
}

export interface Summary {
  book_id: string; label: string; currency: string; market: string;
  starting_budget: string; cash: string; equity: Money; available_balance: string; committed_capital: string;
  realized_pnl: string; unrealized_pnl: Money; estimated_exit_fee: Money; total_pnl: Money; daily_pnl: Money;
  fees_total: string; slippage_total: string; open_positions: number; closed_trades: number;
  win_rate_pct: string | null; max_drawdown_pct: string; current_drawdown_pct: string | null;
  mtm_status: string; mtm_reason: string | null; rejections: number; seq: number; created_at: string;
}

export interface BookStatus {
  book_id: string; label: string; currency: string; starting_budget: string; budget_decision: string;
  state: "NOT_INITIALISED" | "NOT_READY" | "LOADED"; summary: Summary | null; reason: string | null;
}

export interface Readiness { book_id: string; ready: boolean; blockers: string[]; status?: string }

export interface Status {
  scanner: Scanner;
  paper_only: boolean; places_orders: boolean;
  data_root: { path: string; exists: boolean };
  runner: { state: string; reason: string | null; heartbeat: Record<string, unknown> | null };
  readiness: Record<string, Readiness>;
  books: Record<string, BookStatus>;
  calendar: { verified: boolean; note: string | null };
  generated_at: string;
}

export type Trade = Record<string, string | number | boolean | null | Record<string, unknown>>;

export interface BookDetail extends BookStatus { trades: Trade[] | null; rejections: Trade[] | null }

export type Signal = Record<string, string | number | boolean | null | string[]>;

export interface DataHealth {
  runner: string; reason: string | null; at: string | null;
  feeds: Record<string, { symbol: string; state: string; last_bar_start: string | null; last_poll: string | null; counts: Record<string, number> }>;
}

export interface Performance {
  book_id: string; state: string;
  instruments: Record<string, { trades: number; wins: number; realized_pnl: string; fees: string; win_rate_pct: string }> | null;
}

// Backtests: SIMULATION runs on historical data, stored apart from the paper books.
export type BacktestMetrics = Record<string, string | number | null | Record<string, number>>;

export interface BacktestRow {
  run_id: string; status: string; created_at: string | null; updated_at: string | null; symbols: string[] | null;
  range: { start: string | null; end: string | null } | null; book_id: string | null; label: string | null;
  error: string | null; metrics: BacktestMetrics | null;
}

export interface BacktestList { kind: string; runs: BacktestRow[] }

export interface BacktestDetail {
  kind: string;
  run: Record<string, unknown> & { run_id: string; status: string; datasets?: Record<string, unknown>[] };
  metrics: BacktestMetrics | null;
  trades: Trade[] | null;
  rejections: Trade[] | null;
  equity_curve: { ts: string; equity: string | null }[] | null;
}
