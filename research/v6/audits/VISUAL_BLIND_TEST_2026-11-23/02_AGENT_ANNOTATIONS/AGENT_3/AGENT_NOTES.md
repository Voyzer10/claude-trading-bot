# AGENT_3 notes

## Method (image analysis, all code in `output/code/`)

1. `calib.py`: finds the black axes frame, then the 1 px tick marks on the left and bottom spines. Each tick
   label is cropped, upscaled and read with the tesseract CLI. Because ticks are evenly spaced, the label step and
   offset come from a consensus vote, so a misread label is dropped. Two charts each had one misread label
   (E-01: "296.5" for 96.5; X-03: one label). Price and pixel row are then fitted linearly. x is fitted from
   the major-tick labels (0, 5, 10, ...), and candle i is centred at px[0]*i + px[1].
2. `extract.py`: for each candle index, the wick column is the darkest column within ±1 px of the fitted centre.
   High and low are the first and last rows with luma < 170 in that column. The body comes from columns ±2/±3 px
   off the wick, classified by colour (green fill, red fill, or the dark green/red edge for 1-2 px dojis). For a
   green body, open is the bottom and close the top; for red, the reverse. A body of ≤1 px is treated as a doji.
3. `detect.py`: applies the README definitions to the **integer pixel rows**, not to float prices, so
   "strictly higher/lower" means at least 1 px apart.
   - Swing: strictly beyond the 2 candles on each side. Pool = every swing.
   - Sweep / taken: a pool becomes active at swing index + 3. The first later candle whose wick goes strictly beyond
     it is a SWEEP if its close is at or inside the level, otherwise TAKEN. The pool is consumed at that first
     sweep or take, so I mark only one sweep per pool.
   - BOS: a close strictly beyond the most recent known swing (known = index + 2 < break candle). Each swing breaks
     once. BOS is evaluated independently of sweeps, so the same pool can have a SWEEP and later a BOS.
   - CHoCH: a trend state machine. The trend is first set when the last two known swing highs and lows are HH+HL
     (up) or LH+LL (down). Protected level in an uptrend = the known swing low that started the leg of the latest
     bullish break, i.e. the most recent swing low before that BOS or CHoCH candle. Before any break it is the swing
     low before the highest swing high; a downtrend mirrors this. The first close beyond the protected level is a
     CHoCH (emitted instead of a BOS, not as well), and it flips the trend. If the protected level was already broken
     before the trend was set, the state resets and is derived again from structure.
4. Confidence is driven by the pixel margin of the deciding comparison: ≥4 px gives the base value, and 1 px drops
   it by 0.4. Base values: pools 0.9, BOS 0.85, sweeps 0.8, taken 0.7, CHoCH 0.55. CHoCH is lower because
   the "protected level" rule can be read in several ways.
5. Marked copies are drawn with PIL on a copy of each PNG; the originals are untouched. BOS = blue line from the
   swing to the break, CHoCH = purple, BSL pool = orange tick, SSL pool = teal tick, sweep = magenta circle on
   the wick plus a dotted line to the pool, taken = grey "T".

## Calibration accuracy

- Tick-label fit residual: ≤ 0.008 price (≤ 0.8 px) on all 16 charts. x-tick fit residual ≤ 0.6 px.
- Price per pixel: 0.0098 to 0.0140 depending on the chart, so one pixel is about 0.01 to 0.014.
- Candles appear pixel-snapped (crisp body edges, almost no antialiasing), so I did no sub-pixel estimation.
  I expect each OHLC value to be within about ±1 px, i.e. **±0.01 to 0.015 price**. Reported prices have 2 decimals
  but the last digit is only good to ±1 to 2.
- Self-consistency check: the charts come in exact mirror pairs (E-01/E-03, E-02/E-04, M-01/M-03, M-02/M-04,
  H-01/H-02, H-03/H-04, X-01/X-04, X-02/X-03; price p maps to 200 - p). My extracted highs and the mirrored lows
  sum to 200.0000 with zero spread, and the event sets mirror exactly. This shows the extraction is deterministic
  and symmetric. It does not prove absolute accuracy.
- Visual spot checks (E-01, E-02, H-01, X-01 marked images): pools sit on the wick tips and the candle count matches
  the x axis on every chart (78 to 111 candles).

## Difficulties and uncertainties

- **Near-ties.** The README's strict ">" cannot be resolved below about 0.01. I found 14 places where a would-be
  swing equals a neighbour's extreme in the same pixel row, e.g. H-01 highs at 49/50 and M-02 lows at 44/45,
  which look like deliberate equal highs/lows. I treated these as equal, so no swing. If the true values differ by
  less than 1 px, I miss a pool there.
- **Close exactly at a level.** Several sweeps and BOS cases depend on a close within 0-1 px of the level (for example
  E-01 candle 28's sweep of the candle-21 pool, and E-02 candle 52 at the candle-40 low). These have confidence
  0.3 to 0.5. 40 events have confidence ≤ 0.5.
- **CHoCH definition.** This is the most uncertain part. Different but reasonable readings of "the swing that started
  the last leg", and of when a trend counts as established, move CHoCHs by many candles or turn them into BOS.
  Example: H-01 candle 74 breaking the candle-64 lower high is a BOS for me, and my CHoCH comes at candle 87 on
  the candle-40 high. A looser reading would call 74 a CHoCH.
- **One sweep per pool.** If the reference allows repeated sweeps of the same pool, I under-report sweeps.
- **TAKEN events.** These are marked only when the first touch of an active pool is a close beyond it. Pools consumed
  by an earlier sweep get no TAKEN.
- Totals: 600 events (280 pools, 86 BOS, 30 CHoCH, 130 sweeps, 74 taken). Every chart has at least one of each
  required type. H-01 and H-02 have only one CHoCH each.
