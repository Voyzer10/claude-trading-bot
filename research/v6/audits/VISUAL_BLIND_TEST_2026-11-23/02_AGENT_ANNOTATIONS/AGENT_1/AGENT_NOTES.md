# AGENT_1 notes (visual inspection only)

## Method
- Used only the 16 PNGs and README in my input folder. I didn't open any other folder, data file or code.
- For each chart I read the x-axis span (number of candles) and two y-axis tick positions by eye from an enlarged
  axis strip that had a pixel ruler on it. Pixel position = linear fit between the two ticks. The x mapping uses the
  plot edges, with xlim = (-1, N).
- I read every candle's high, low and close by eye from enlarged crops of about 23-28 candles each. Each crop had the
  original y-axis pasted on the left and a candle index label on every bar.
- When levels were close (inside about 0.1), I built side-by-side crops. These place the chosen candles' columns over
  the same pixel rows, enlarged 8x with a 5-px row ruler, so I could see which wick or close reaches further. About
  1 px is 0.01-0.014 in price.
- I applied the README definitions by hand. Code was used only for cropping and enlarging, for price/pixel conversion
  and for drawing the marks. No pixel-colour or column scanning was used.

## Interpretation choices (consistent across charts)
- Swing = strictly higher high (lower low) than the 2 bars on each side. Equal extremes, judged equal at pixel level,
  make no swing. Several charts seem to contain these traps on purpose: E-02/M-02 lows 44/45, M-04 highs 44/45, H-01
  lows 22/24 and highs 49/50, H-02 highs 22/24 and lows 49/50, X-01 lows 28/30, X-04 highs 28/30. I marked no swing
  at any of these.
- A single huge-range candle can be both a swing high and a swing low (X-01 44/77, X-02 70, X-03 70, X-04 44/77).
- BOS = close strictly beyond the most recent known swing that hasn't been broken yet (known 2 bars after it forms).
  A close beyond an older, non-most-recent swing is recorded only as TAKEN.
- CHoCH = close beyond the protected level: the swing low that started the last bullish leg, or the swing high that
  started the last bearish leg. If a newer swing formed after the leg's high (low) without starting a new leg, I
  broke that newer swing as a BOS first and put the CHoCH on the later break of the protected level (M-01 86/89,
  M-03 86/89). Some engines would put the CHoCH on the first counter-trend break instead. I noted these
  alternatives in the per-event notes.
- Sweep = wick strictly beyond a known pool with the close at or inside it. A close equal to the level (within 1 px)
  counts as a sweep, but I gave those low confidence and noted the alternative. One candle can sweep several pools.
  I listed each pool separately and used the swept pool's level as the price.
- TAKEN events are included (the first close strictly beyond each pool).

## Difficulties / low-confidence items
- Many near-equal extremes and closes are within 0-1 px (about 0.01). These are marked with confidence 0.35-0.55
  and an "alt:" note: E-01 28/29, 61/62; E-03 28/29; H-03 79; H-04 79; M-04 100; X-04 102, among others.
- On EXTREME charts the very long wicks make one candle sweep many pools at once, so the sweep counts are high there.
- I made no attempt to mark sweeps of pools that were already taken (closed through).
- The y calibration comes from tick labels read by eye. Absolute prices may be off by about 0.01-0.02, but relative
  ordering came from the same-row comparisons.
