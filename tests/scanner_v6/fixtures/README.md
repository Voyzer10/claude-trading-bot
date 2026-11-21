# V6 test fixtures

- `synthetic_5m.json`: 120 seeded random-walk 5-minute candles in the repo's chart-JSON shape (`t,o,h,l,c,v`,
  epoch seconds). Candle 50 has `None` prices on purpose (loaders skip it), so the series has 119 candles.
  No market data, no trading meaning: it only exercises loading, ordering, indices and the no-look-ahead harness.
