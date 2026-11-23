# AGENT_2 notes

## Method
- Visual inspection only. Order: EXTREME (X-01..04), HARD, MEDIUM, EASY. Each chart was read right-to-left first for the major swings, then candle by candle.
- I estimated each candle's high, low and close by eye from the full PNG. Where two levels were within about 1-2 px of each other (equal highs or lows, closes right at a level) I looked at enlarged nearest-neighbour crops (scratch/z_*.png). Code was used only to crop and enlarge, to turn axis-tick calibration into pixel coordinates (read visually per chart: x of index 0, px per candle, two y ticks), and to draw the marks and write the JSON/CSV. No code read OHLC values from pixel colours.
- I checked every swing, sweep and break by hand against the README rules: a swing needs 2 strictly lower or higher neighbours on each side, a pool is known 2 bars after the swing, a sweep needs a wick beyond the level with the close at or inside it, and a BOS breaks the most recent known swing on a close, with each swing broken once.
- CHoCH: trend comes from the BOS sequence. The protected level is the extreme swing of the leg that produced the last with-trend BOS: the lowest swing low between the broken swing high and the BOS candle in an uptrend, the reverse in a downtrend. The CHoCH is the first close beyond that level. A break of a more recent swing against the trend that does not clear the protected level is marked as BOS with the note "internal". When the CHoCH candle also breaks the most recent swing at a different level, both are marked.

## Difficulties and uncertainty
- Price precision is about ±0.02-0.04, or roughly 1-2 px. Many highs and lows that look equal were decided on single-pixel differences; these carry confidence of 0.3-0.5 with a note. Exactly equal extremes (by zoom) were not counted as swings, e.g. H-01 49/50 highs and 22/24 lows, H-02 49/50 lows, M-02 44/45 lows, M-04 44/45 highs.
- Close-at-level cases that cannot be settled visually: E-03 candle 28 against SH21 (I marked BOS at 29, with 28 as a possible alternative), E-01 candle 28 against SL21 (I marked BOS at 28 at 0.35), X-01 102, X-04 47/102, X-02 69, and H-03 56 against 99.40 (judged not a break).
- The CHoCH vs internal-BOS classification depends on the protected-level interpretation. A simpler "first break against the last BOS direction" rule would move several CHoCH marks to the earlier internal BOS candle, for example H-02 74 instead of 87, H-03 56 instead of 67, M-01 62 instead of 63 and M-03 51 instead of 63.
- Sweeps: I marked a pool swept again only when it is clearly a separate event. For marginal wicks (≤0.03 beyond the level) confidence is ≤0.35.
- TAKEN_* events are partial; I marked mostly the ones tied to BOS/CHoCH and to clear closes through pools.
- H-01 and H-02 have 111 candles with narrower spacing (≈14.9 px), so index reading there is slightly less reliable than on the EASY charts (≈21 px).
