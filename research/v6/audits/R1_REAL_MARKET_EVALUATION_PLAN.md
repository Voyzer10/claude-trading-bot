# R-1: protected-swing availability on real market data (evaluation plan)

Status: **PLAN ONLY. Not run. No rule was changed.** D2 (P-B) and A5 stay as approved, with no fallback protection.
Prepared 22 Nov 2026 (Phase 2).

## 0. What is known and what is not

- **Known (synthetic only):** in 400 random walks, 59 % of the candles in a BULLISH / BEARISH state had no protected swing
  in force.
  - Causes: NO_ORIGIN_SWING 2 601 + 143, NOT_QUALIFIED 2 106 + 11, no same-direction BOS 666, origin pending 169.
- **Not known:** whether real markets look like this. Random walks have no trend persistence, volatility clustering,
  sessions or gaps.

**The 59 % must not be quoted as a market property.** It only shows that the rule *can* leave large gaps.

## 1. Instruments and timeframes

The instruments are the markets the bot already has data paths for. Read-only data; no broker or execution.

| Market | Instruments (fixed list, chosen in advance) | Source |
|---|---|---|
| Crypto (24/7) | BTC-USD, ETH-USD, SOL-USD, XRP-USD | Coinbase public candles (no key) |
| NSE cash | NIFTY 50 index, BANKNIFTY index, RELIANCE, HDFCBANK, INFY, TCS, SBIN, ICICIBANK | Zerodha historical (existing data access; read-only) |
| US equities | SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMZN, JPM | Alpaca IEX (paper key, data only) |

Timeframes:
- **5m, 15m, 1h, 1D** for all instruments.
- **4h** for crypto only, where sessions do not cut the bars.

Splitting the instruments into groups ahead of the run means no instrument is added or dropped after seeing the results.

## 2. Required historical data

| Timeframe | History per instrument | Approx. candles |
|---|---|---|
| 5m | 6 months | crypto ≈ 52 k; NSE ≈ 9 k (75 / day); US ≈ 9.8 k (78 / day RTH) |
| 15m | 12 months | crypto ≈ 35 k; NSE ≈ 6.2 k; US ≈ 6.5 k |
| 1h | 2 years | crypto ≈ 17.5 k; NSE ≈ 3.5 k; US ≈ 3.5 k |
| 4h (crypto) | 3 years | ≈ 6.6 k |
| 1D | 8 years | crypto ≈ 2.9 k; NSE / US ≈ 2 k |

Data requirements:
- OHLC with UTC timestamps.
- An exchange-session flag for NSE / US. RTH only for US (IEX), noted as a limitation.
- Corporate-action adjusted daily data for equities.
- A gap list (missing bars and session breaks), recorded **as data** and **not repaired**. O7 (gaps / sessions) is
  unresolved, so the detector is run on the bars as given and the gaps are reported as a segment.
- Each file saved with a SHA-256 and its download date, so the run can be repeated.

## 3. Metrics (all per instrument × timeframe, and pooled per market)

Denominator **S** = the candles whose structure state is BULLISH or BEARISH. TRANSITION, UNKNOWN and warm-up candles
are excluded and reported separately.

| ID | Metric |
|---|---|
| M1 | **% of S with no protected swing in force** (the R-1 headline). Plus the % of candles that are UNKNOWN / TRANSITION. |
| M2 | Cause of each unprotected candle: NO_ORIGIN_SWING, NOT_QUALIFIED (A5), no same-direction BOS yet, origin pending confirmation, consumed / stale (`min_bos_index`) |
| M3 | Length of unprotected runs (in candles and in wall-clock time): median, p90, max |
| M4 | **Bullish vs bearish** split of M1–M3, so any asymmetry is visible |
| M5 | Events per 1 000 candles: BOS, CHoCH, REVERSAL_CONFIRMED, WICK_ONLY, EXACT_LEVEL_CLOSE, MIXED_STRUCTURE, EQUAL_SWING_PRICE, O4 / O9 diagnostics |
| M6 | Distance from the close to the protected level, in ATR(14) units, when one is in force |
| M7 | Frequency of the **S-1 pattern**: a later-confirming lower (higher) origin candidate in a leg whose origin is already active. Counted only; not resolved. |
| M8 | Breaks that happened while unprotected: the price closed beyond the last swing low (high) of the opposite kind during an unprotected run. This measures what the gap may miss; it is **not** an alternative rule. |

## 4. Segmentation

- **Session** (bar open in the local exchange time):
  - NSE: open 09:15–10:00, mid, close 14:30–15:30.
  - US: open 09:30–10:30, mid, power hour 15:00–16:00 ET.
  - Crypto: Asia / Europe / US UTC blocks, and weekend vs weekday.
- **Volatility:** ATR(14) / close percentile within each instrument × timeframe, in terciles (low / mid / high), with
  thresholds computed on the data before the segment (no look-ahead in the labels).
- **Trend context:** the sign of the 1D 50-bar slope, used only as a label.
- **Gap segment:** the candles within R = 2 bars of a session break or a missing bar.

## 5. Procedure (research only)

1. Freeze the code version. Record the commit hash and confirm that no rule changed.
2. Download the data (read-only) into `research/v6/data/` with checksums. Never touch `/opt/trader` or production data.
3. Run `analyze_structure` per series. Also run `no_lookahead_violations` on a sample of each timeframe as a sanity check.
4. Compute M1–M8 per segment. Report the counts together with the percentages.
5. Run the same pipeline on random walks with **matched** volatility as a control, labelled "synthetic control", so
   real-market and synthetic results are never pooled.
6. Write `research/v6/audits/R1_RESULTS_<date>.md`. It must contain no rule change and no proposal applied, only the
   numbers and the open questions for the owner.

## 6. Decision use

- The results inform the owner's choices about D2 / A5, S-1, A1 (external structure) and O7.
- They do not authorise any change by themselves.
- If M1 is high on real data, the options go back to the owner as proposals. Any change then needs its own backtest,
  with the out-of-sample numbers reported, per the repo rules.
