"""V6 historical backtesting (PAPER ONLY research tool; no broker, no order path).

A backtest replays a validated historical OHLCV dataset, one completed candle at a time and in timestamp order,
through EXACTLY the V6 paper pipeline: Modules A-E (CHoCH -> BOS -> liquidity sweep -> candlestick -> confirmation ->
entry, with Module E's sizing, SL / TP, fees and slippage) wrapped by `v6_runtime.portfolio.Portfolio` and its book
gates. Every run has its own SIMULATION ledger (`ledger_kind=BACKTEST`) inside its own run directory
(`<V6 data root>/backtests/<run_id>/`); it never opens a paper book or anything belonging to V4.

    python -m v6_runtime.backtest --help
"""
ENGINE_VERSION = "v6-backtest-1"
