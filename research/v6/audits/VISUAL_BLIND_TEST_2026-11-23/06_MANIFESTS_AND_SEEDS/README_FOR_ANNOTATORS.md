# V6 visual blind annotation task

You receive 16 unmarked synthetic candlestick charts (PNG), 4 per difficulty folder: EASY, MEDIUM, HARD, EXTREME.
Each chart is 1800 x 900 px. The x axis is the zero-based candle index (major tick every 5 candles, a faint vertical
grid line on every candle). The y axis is price. Green body = close >= open, red body = close < open.
There are no labels, answers or hints on the images. Do not assume every chart contains every event type.

## What to mark (definitions used by this test)

- **Swing high / swing low:** a candle whose high (low) is strictly higher (lower) than the highs (lows) of the 2 candles
  on each side. Equal neighbouring extremes do not make a swing. A swing is only *known* 2 candles after it forms.
- **Liquidity pool:** every swing high is a BSL pool at its high; every swing low is an SSL pool at its low. Mark the pool
  at the swing candle index and the swing price.
- **Sweep:** a candle whose wick goes strictly beyond an existing pool (above a BSL pool / below an SSL pool) but whose
  close is back at or inside the level. `SWEEP_BSL` = wick above highs, `SWEEP_SSL` = wick below lows. A pool can only be
  swept by a candle after the pool is known (2 candles after the swing).
- **Taken:** a candle that closes strictly beyond a pool level (optional to mark: `TAKEN_BSL` / `TAKEN_SSL`).
- **BOS (break of structure):** a candle that closes strictly beyond the most recent known swing high (bullish BOS) or
  swing low (bearish BOS). Each swing can be broken only once. Mark the break candle and the broken level.
- **CHoCH (change of character):** once a trend is established (higher highs + higher lows, or lower highs + lower lows),
  the first close strictly beyond the protected level against that trend (the swing low that started the last bullish
  leg in an uptrend / the swing high that started the last bearish leg in a downtrend). Mark the break candle and the
  level. A wick alone is not a CHoCH.

## Output (per chart)

Write into YOUR output folder only:

1. `<chart_id>_marked.png`: a COPY of the chart with your marks drawn on it. Never modify the original PNG.
   Suggested style: BOS = blue line at the broken level ending at the break candle + text "BOS↑"/"BOS↓";
   CHoCH = purple line + "CHoCH↑"/"CHoCH↓"; BSL pools = short orange line at the high; SSL pools = short teal line at the
   low; sweeps = a circle/arrow on the wick + "SW-BSL"/"SW-SSL".
2. `<chart_id>.json`:

```json
{"chart_id": "E-01", "agent": "AGENT_n", "method": "short description of how you worked",
 "events": [
   {"type": "BOS", "direction": "bullish", "candle_index": 23, "price": 104.1, "confidence": 0.8, "note": ""},
   {"type": "CHOCH", "direction": "bearish", "candle_index": 60, "price": 104.2, "confidence": 0.6, "note": ""},
   {"type": "POOL_BSL", "candle_index": 20, "price": 104.0, "confidence": 0.9, "note": ""},
   {"type": "POOL_SSL", "candle_index": 25, "price": 102.4, "confidence": 0.9, "note": ""},
   {"type": "SWEEP_BSL", "candle_index": 30, "price": 104.0, "confidence": 0.7, "note": "price = swept pool level"},
   {"type": "TAKEN_SSL", "candle_index": 40, "price": 102.4, "confidence": 0.5, "note": "optional"}
 ]}
```

Allowed types: `BOS`, `CHOCH`, `POOL_BSL`, `POOL_SSL`, `SWEEP_BSL`, `SWEEP_SSL`, `TAKEN_BSL`, `TAKEN_SSL`.
`direction` is required for BOS and CHOCH (`bullish` or `bearish`). `price` is your best visual estimate (2 decimals).
3. After all charts: `annotations_all.csv` with columns
   `chart_id,type,direction,candle_index,price,confidence,note`, and `AGENT_NOTES.md` (method, difficulties, anything
   you were unsure about).
