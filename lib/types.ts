// Shape of the snapshot the bot pushes (dashboard_push.py, version 1).

export type Segment = { start: string; end: string };

export type Runner = {
  mode?: "cloud" | "pc" | "vps";
  status: string | null;
  updated: string | null;
  next_run: string | null;
  markets: string[] | null;
  pid: number | null;
  started_at: string | null;
  errors: string[];
  uptime_24h_hours: number;
  segments: Segment[];
};

export type Coin = {
  symbol: string;
  state: "breakout" | "breakdown" | "oversold" | "quiet" | "no data";
  price: number | null;
  pct_vs_high: number | null;
  pct_vs_low: number | null;
  rsi_15m: number | null;
  vol_ratio: number | null;
  range_high: number | null;
  range_low: number | null;
  daily: string[];
  seen_today: string[];
};

export type Decision = {
  time: string | null;
  symbol: string | null;
  market: string;
  setup: string | null;
  result: string | null;
  why: string | null;
  category: string;
  price: number | null;
  stop: number | null;
  target: number | null;
  stop_pct: number | null;
  vol: number | null;
};

export type Position = {
  key: string;
  market: string;
  symbol: string;
  qty: number;
  entry: number;
  stop: number;
  target: number;
  side?: string;
  entry_time?: string;
  exit?: number;
  exit_time?: string;
  exit_date?: string;
  pnl?: number;
  r?: number;
  reason?: string;
};

export type Snapshot = {
  version: number;
  generated_at: string;
  runner: Runner;
  crypto: {
    universe: string[];
    coins: Coin[];
    scan_as_of: string | null;
    usable: number | null;
    scanned: number | null;
    failed: number | null;
    daily_closes_through: string | null;
  };
  markets: Record<string, Record<string, unknown> & { mode?: string }>;
  rules: Record<string, Record<string, unknown> | null>;
  decisions: Decision[];
  skip_reasons: { since_restart: Record<string, number>; today: Record<string, number>; all: Record<string, number> };
  counts: { decisions_total: number; traded: number; skipped: number; blocked: number; log_only: number };
  ledger: {
    accounts: Record<string, { cash: number; start_capital: number }>;
    open: Position[];
    closed: Position[];
  };
  logs: { t: string; text: string; kind: string }[];
};

export type SnapshotResponse = { received: number | null; now: number; snapshot: Snapshot | null };
