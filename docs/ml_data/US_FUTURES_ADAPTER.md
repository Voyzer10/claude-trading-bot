# US Equity-Index Futures Adapter (`ml_data/futures`)

## 1. Provider Evaluation & Selection
- **Evaluated Providers (verified 2026-11-28)**: Databento (`GLBX.MDP3`), CME DataMine, dxFeed (`ml_data/futures/provider_evaluation.py`).
- **Selected Provider**: **Databento (`GLBX.MDP3`)** for CME Globex coverage of `ES`, `MES`, `NQ`, `MNQ`, `YM`, `MYM`, `RTY`, `M2K`, full instrument definitions, `ohlcv-1m`/`1s`/`trades`/`mbp-1`/`statistics` (OI), and usage-based research pricing.
- **Safety**: `DatabentoHistoricalClient` enforces `https://hist.databento.com`, `GET` only, and blocks live `/v0/timeseries.get_range` unless `allow_billable_timeseries=True`.

## 2. Continuous vs Dated Contracts
- Dated contracts map to `Market.US`, `Segment.US_FUTURES`, `AssetClass.FUTURE`, `ContractType.DATED_FUTURE`, Identity v3.
- `ContinuousContractBuilder` constructs derived research series (`calendar`, `volume`, `open_interest` roll rules; `raw_unadjusted`, `panama_back_adjusted`, `ratio_back_adjusted`) while preserving original `actual_instrument_id`, `actual_symbol`, and raw prices. Never use a continuous series as an execution instrument.

## 3. CME Globex Calendar & Licensing
- `CMEGlobexCalendar` (`America/Chicago`) models Sunday 17:00 CT open, 16:00–17:00 CT daily maintenance break, Friday 16:00 CT close, RTH/ETH, and holidays.
- Live Databento entitlement & CME non-display licensing remain `BLOCKED_BY_AUTH` / `UNVERIFIED` until `DATABENTO_API_KEY` is configured.
