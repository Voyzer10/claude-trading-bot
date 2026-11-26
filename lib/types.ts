// Shape of the snapshot the bot pushes (dashboard_push.py, version 1).

export type Segment = { start: string; end: string };

export type Runner = {
  mode?: "cloud" | "pc" | "vps";
  status: string | null;
  updated: string | null;
  next_run: string | null;
  markets: string[] | null;
  scanners?: Record<string, string>;
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
  profile?: CoinProfile | null;
};

/** How a coin behaved over the last 30 days (coin_profile.py). Display only, not a trading filter. */
export type CoinProfile = {
  symbol: string;
  style: string;
  why?: string;
  notes: string[];
  candles?: number;
  trend?: { label: string; vr_4h: number | null; z_4h: number | null; vr_16h: number | null; z_16h: number | null };
  breakouts?: { follow_pct: number | null; n: number };
  levels?: { hold_pct: number | null; n: number };
  volume?: { continue_pct: number | null; n: number };
  btc_corr?: number | null;
  atr_pct_15m?: number | null;
};

export type Decision = {
  time: string | null;
  symbol: string | null;
  market: string;
  setup: string | null;
  setup_name?: string | null;
  scanner?: string | null;
  liquidity?: string | null;
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
  last?: number;
  open_pnl?: number;
  trail_k?: number | null;
  trailing?: boolean;
  breakeven?: boolean;
  risk_stop?: number;
  note?: string;
  /** when the last price was quoted (paper.py check_once); old = the data feed is stale */
  quote_time?: string;
  /** Trade Manager (7 Nov 2026): furthest the trade went for / against it, in R; profit locked */
  mfe_r?: number;
  mae_r?: number;
  locked?: boolean;
  /** a Scanner v4 trade managed by the PDF's exits only (stop / target / flat-by) */
  pdf_only?: boolean;
  /** cash the trade ties up: futures margin, or the intraday margin of a leveraged stock trade (paper.py) */
  margin?: number;
  /** intraday leverage used (owner, 14 Nov 2026: 5x INDIA, 4x US by default) */
  leverage?: number;
  /** the v4 chart an option position came from (e.g. NSE:BANKNIFTY) */
  v4_chart?: string;
  /** the Trade Manager's last actions on this trade (paper.py tm_event), oldest first */
  tm_log?: { t: string; text: string }[];
  /** why it was taken (paper.py cmd_buy, from 5 Nov 2026): setup, scanner version or "rules", liquidity, reason */
  setup?: string;
  setup_name?: string;
  scanner?: string;
  liquidity?: string;
  entry_reason?: string;
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
    profiles_as_of?: string | null;
    profiles_days?: number | null;
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
