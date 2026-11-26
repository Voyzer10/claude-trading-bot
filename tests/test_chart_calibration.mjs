import assert from "node:assert/strict";
import test from "node:test";
import { calibratePriceAxis, extractCandlesFromImageData } from "../lib/chartExtractor.ts";

// Helper bitmap glyph renderer (independent 5x7 crisp font) for synthetic chart buffers
const FONT_5X7 = {
  "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
  "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
  "2": ["01110", "10001", "00001", "00110", "01000", "10000", "11111"],
  "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
  "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
  "5": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
  "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
  "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
  "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
  "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
  ".": ["00000", "00000", "00000", "00000", "00000", "11000", "11000"],
  ",": ["00000", "00000", "00000", "00000", "01000", "01000", "10000"],
  "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
};

function makeSyntheticChartRGBA({
  width = 1024,
  height = 460,
  ticks = [],
  candles = [],
  axisSide = "right",
  invertedY = false,
  priceMin,
  priceMax,
  yTop = 60,
  yBot = 360,
  scale = 2,
  darkTheme = true,
}) {
  const buf = new Uint8ClampedArray(width * height * 4);
  const bg = darkTheme ? [13, 17, 23] : [248, 250, 252];
  const fg = darkTheme ? [226, 232, 240] : [15, 23, 42];
  const bull = [34, 197, 94];
  const bear = [239, 68, 68];

  for (let i = 0; i < width * height; i++) {
    buf[i * 4] = bg[0];
    buf[i * 4 + 1] = bg[1];
    buf[i * 4 + 2] = bg[2];
    buf[i * 4 + 3] = 255;
  }

  const setPx = (x, y, rgb) => {
    const ix = Math.round(x);
    const iy = Math.round(y);
    if (ix < 0 || ix >= width || iy < 0 || iy >= height) return;
    const p = (iy * width + ix) * 4;
    buf[p] = rgb[0];
    buf[p + 1] = rgb[1];
    buf[p + 2] = rgb[2];
    buf[p + 3] = 255;
  };

  const priceToY = (price) => {
    const frac = (price - priceMin) / (priceMax - priceMin);
    return invertedY ? yTop + frac * (yBot - yTop) : yBot - frac * (yBot - yTop);
  };

  // Draw axis labels
  for (const label of ticks) {
    const p = Number(label.replace(/,/g, ""));
    const yc = priceToY(p);
    const topY = Math.round(yc - (7 * scale) / 2);
    let cursorX = axisSide === "right" ? Math.floor(width * 0.90) : 6;
    for (const ch of label) {
      const bm = FONT_5X7[ch];
      if (!bm) {
        cursorX += 2 * scale;
        continue;
      }
      const chW = ch === "." || ch === "," ? 2 : 5;
      for (let r = 0; r < 7; r++) {
        const yOff = ch === "," && r >= 5 ? r + 1 : r;
        for (let c = 0; c < 5; c++) {
          if (bm[r][c] === "1") {
            for (let sy = 0; sy < scale; sy++) {
              for (let sx = 0; sx < scale; sx++) {
                setPx(cursorX + c * scale + sx, topY + yOff * scale + sy, fg);
              }
            }
          }
        }
      }
      cursorX += (chW + 1) * scale;
    }
  }

  // Draw candlesticks inside plot region
  const plotLeft = axisSide === "left" ? Math.floor(width * 0.16) : Math.floor(width * 0.06);
  const plotRight = axisSide === "right" ? Math.floor(width * 0.85) : Math.floor(width * 0.92);
  const stepX = Math.floor((plotRight - plotLeft) / Math.max(1, candles.length));
  const bodyHalf = Math.max(2, Math.min(5, Math.floor(stepX * 0.3)));

  candles.forEach((c, idx) => {
    const cx = plotLeft + idx * stepX + Math.floor(stepX / 2);
    const isBull = c.c >= c.o;
    const color = isBull ? bull : bear;
    const yH = Math.round(priceToY(c.h));
    const yL = Math.round(priceToY(c.l));
    const yO = Math.round(priceToY(c.o));
    const yC = Math.round(priceToY(c.c));
    const yHiPx = Math.min(yH, yL);
    const yLoPx = Math.max(yH, yL);
    const bTop = Math.min(yO, yC);
    const bBot = Math.max(yO, yC);

    for (let y = yHiPx; y <= yLoPx; y++) setPx(cx, y, color);
    for (let y = bTop; y <= bBot; y++) {
      for (let x = cx - bodyHalf; x <= cx + bodyHalf; x++) {
        setPx(x, y, color);
      }
    }
  });

  return { buf, width, height, priceToY };
}

test("calibratePriceAxis fits standard linear range and rejects outlier", () => {
  const cal = calibratePriceAxis([
    { y: 51.5, price: 2516, label: "2,516.00" },
    { y: 72.5, price: 2512, label: "2,512.00" },
    { y: 94.5, price: 2508, label: "2,508.00" },
    { y: 115.5, price: 9999, label: "9,999.00" }, // corrupted outlier
    { y: 137.5, price: 2500, label: "2,500.00" },
    { y: 393.5, price: 2452, label: "2,452.00" },
  ]);
  assert.equal(cal.available, true);
  assert.equal(cal.points.length, 5);
  assert.ok(cal.slope < 0);
  assert.ok(Math.abs(cal.slope * 222.5 + cal.intercept - 2484) < 0.3);
});

test("calibratePriceAxis handles inverted Y coordinates and negative spreads", () => {
  const cal = calibratePriceAxis([
    { y: 50, price: -15.0, label: "-15.00" },
    { y: 150, price: -5.0, label: "-5.00" },
    { y: 250, price: 5.0, label: "5.00" },
  ]);
  assert.equal(cal.available, true);
  assert.ok(cal.slope > 0);
  assert.ok(Math.abs(cal.slope - 0.1) < 1e-6);
  assert.ok(Math.abs(cal.intercept - -20.0) < 1e-6);
});

test("calibratePriceAxis refuses fewer than 2 consistent ticks", () => {
  const single = calibratePriceAxis([{ y: 100, price: 2500, label: "2500" }]);
  assert.equal(single.available, false);
  assert.equal(single.slope, null);

  const zeroSpan = calibratePriceAxis([
    { y: 100, price: 2500, label: "2500" },
    { y: 200, price: 2500, label: "2500" },
  ]);
  assert.equal(zeroSpan.available, false);
});

test("extractCandlesFromImageData calibrates 2452-2516 chart and matches source OHLC", () => {
  const source = [
    { o: 2490, h: 2493, l: 2486, c: 2487 },
    { o: 2487, h: 2489, l: 2480, c: 2482 },
    { o: 2482, h: 2484, l: 2475, c: 2477 },
    { o: 2477, h: 2480, l: 2470, c: 2472 },
    { o: 2472, h: 2475, l: 2466, c: 2468 },
    { o: 2468, h: 2472, l: 2463, c: 2471 },
    { o: 2471, h: 2478, l: 2469, c: 2476 },
    { o: 2476, h: 2485, l: 2475, c: 2484 },
    { o: 2484, h: 2494, l: 2483, c: 2492 },
    { o: 2492, h: 2504, l: 2491, c: 2502 },
    { o: 2502, h: 2510, l: 2500, c: 2508 },
  ];
  const { buf, width, height } = makeSyntheticChartRGBA({
    ticks: ["2,516.00", "2,500.00", "2,484.00", "2,468.00", "2,452.00"],
    candles: source,
    priceMin: 2452,
    priceMax: 2516,
  });
  const ext = extractCandlesFromImageData(buf, width, height);
  assert.equal(ext.calibration.available, true);
  assert.equal(ext.calibration.axisSide, "right");
  assert.ok(ext.calibration.points.length >= 4);
  assert.equal(ext.candles.length, source.length);
  for (let i = 0; i < source.length; i++) {
    assert.ok(Math.abs(ext.candles[i].o - source[i].o) <= 0.6, `bar ${i} O: ${ext.candles[i].o} vs ${source[i].o}`);
    assert.ok(Math.abs(ext.candles[i].h - source[i].h) <= 0.6, `bar ${i} H: ${ext.candles[i].h} vs ${source[i].h}`);
    assert.ok(Math.abs(ext.candles[i].l - source[i].l) <= 0.6, `bar ${i} L: ${ext.candles[i].l} vs ${source[i].l}`);
    assert.ok(Math.abs(ext.candles[i].c - source[i].c) <= 0.6, `bar ${i} C: ${ext.candles[i].c} vs ${source[i].c}`);
  }
});

test("extractCandlesFromImageData supports micro decimal range (0.0012-0.0020) and large index range (45000-48000)", () => {
  const microSrc = [
    { o: 0.00130, h: 0.00136, l: 0.00125, c: 0.00134 },
    { o: 0.00134, h: 0.00148, l: 0.00132, c: 0.00146 },
    { o: 0.00146, h: 0.00160, l: 0.00144, c: 0.00158 },
    { o: 0.00158, h: 0.00176, l: 0.00155, c: 0.00174 },
  ];
  const m = makeSyntheticChartRGBA({
    ticks: ["0.0020", "0.0018", "0.0016", "0.0014", "0.0012"],
    candles: microSrc,
    priceMin: 0.0012,
    priceMax: 0.0020,
  });
  const extMicro = extractCandlesFromImageData(m.buf, m.width, m.height);
  assert.equal(extMicro.calibration.available, true);
  assert.equal(extMicro.candles.length, microSrc.length);
  for (let i = 0; i < microSrc.length; i++) {
    assert.ok(Math.abs(extMicro.candles[i].h - microSrc[i].h) <= 0.000015);
    assert.ok(Math.abs(extMicro.candles[i].l - microSrc[i].l) <= 0.000015);
  }

  const bigSrc = [
    { o: 45400, h: 45800, l: 45200, c: 45700 },
    { o: 45700, h: 46500, l: 45600, c: 46400 },
    { o: 46400, h: 47200, l: 46300, c: 47100 },
    { o: 47100, h: 47900, l: 47000, c: 47800 },
  ];
  const b = makeSyntheticChartRGBA({
    ticks: ["48,000", "47,000", "46,000", "45,000"],
    candles: bigSrc,
    priceMin: 45000,
    priceMax: 48000,
  });
  const extBig = extractCandlesFromImageData(b.buf, b.width, b.height);
  assert.equal(extBig.calibration.available, true);
  assert.equal(extBig.candles.length, bigSrc.length);
  for (let i = 0; i < bigSrc.length; i++) {
    assert.ok(Math.abs(extBig.candles[i].h - bigSrc[i].h) <= 30);
    assert.ok(Math.abs(extBig.candles[i].l - bigSrc[i].l) <= 30);
  }
});

test("extractCandlesFromImageData handles inverted Y coordinates and left axis", () => {
  const source = [
    { o: 120.0, h: 121.0, l: 118.0, c: 119.0 },
    { o: 119.0, h: 119.5, l: 114.0, c: 115.0 },
    { o: 115.0, h: 116.0, l: 112.0, c: 113.0 },
    { o: 113.0, h: 118.0, l: 112.5, c: 117.5 },
  ];
  const inv = makeSyntheticChartRGBA({
    ticks: ["110.00", "114.00", "118.00", "122.00"],
    candles: source,
    axisSide: "left",
    invertedY: true,
    priceMin: 110,
    priceMax: 122,
  });
  const extInv = extractCandlesFromImageData(inv.buf, inv.width, inv.height);
  assert.equal(extInv.calibration.available, true);
  assert.equal(extInv.calibration.axisSide, "left");
  assert.ok(extInv.calibration.slope > 0);
  assert.equal(extInv.candles.length, source.length);
  for (let i = 0; i < source.length; i++) {
    assert.ok(extInv.candles[i].l <= extInv.candles[i].h);
    assert.ok(Math.abs(extInv.candles[i].h - source[i].h) <= 0.25);
    assert.ok(Math.abs(extInv.candles[i].l - source[i].l) <= 0.25);
  }
});

test("extractCandlesFromImageData supports light-theme TradingView narrow right axis (54,000-55,800)", () => {
  const w = 1352;
  const h = 535;
  const buf = new Uint8ClampedArray(w * h * 4);
  const fgGray = [120, 123, 134]; // #787b86 TradingView gray axis text
  const divGray = [224, 227, 235];
  for (let i = 0; i < w * h; i++) {
    buf[i * 4] = 255;
    buf[i * 4 + 1] = 255;
    buf[i * 4 + 2] = 255;
    buf[i * 4 + 3] = 255;
  }
  const setPx = (x, y, rgb) => {
    if (x < 0 || x >= w || y < 0 || y >= h) return;
    const p = (Math.round(y) * w + Math.round(x)) * 4;
    buf[p] = rgb[0];
    buf[p + 1] = rgb[1];
    buf[p + 2] = rgb[2];
    buf[p + 3] = 255;
  };
  const divX = 1280; // narrow ~72px right axis (~5.3% width)
  for (let y = 0; y < h; y++) setPx(divX, y, divGray);

  const pMin = 54000;
  const pMax = 55800;
  const yTop = 30;
  const yBot = 420;
  const p2y = (p) => yBot - ((p - pMin) / (pMax - pMin)) * (yBot - yTop);
  const ticks = ["55,800.00", "55,600.00", "55,400.00", "55,200.00", "55,000.00", "54,800.00", "54,600.00", "54,400.00", "54,200.00", "54,000.00"];
  for (const label of ticks) {
    const val = Number(label.replace(/,/g, ""));
    const yc = p2y(val);
    const ty = Math.round(yc - 7);
    let cx = divX + 8;
    for (const ch of label) {
      const bm = FONT_5X7[ch];
      const cw = ch === "." || ch === "," ? 2 : 5;
      for (let r = 0; r < 7; r++) {
        const yr = ch === "," && r >= 5 ? r + 1 : r;
        for (let c = 0; c < 5; c++) {
          if (bm[r][c] === "1") {
            setPx(cx + c, ty + yr * 2, fgGray);
            setPx(cx + c, ty + yr * 2 + 1, fgGray);
          }
        }
      }
      cx += cw + 2;
    }
  }
  // Place candles extending right up to divX - 6 (inside old 0.89*w = 1203 strip!)
  const src = [
    { o: 54600, h: 54750, l: 54500, c: 54700 },
    { o: 54700, h: 54950, l: 54680, c: 54900 },
    { o: 54900, h: 55250, l: 54880, c: 55200 },
    { o: 55200, h: 55520, l: 55150, c: 55480 },
  ];
  src.forEach((c, idx) => {
    const cx = 1210 + idx * 18;
    const col = [38, 166, 154];
    for (let y = Math.round(p2y(c.h)); y <= Math.round(p2y(c.l)); y++) setPx(cx, y, col);
    const bTop = Math.round(p2y(Math.max(c.o, c.c)));
    const bBot = Math.round(p2y(Math.min(c.o, c.c)));
    for (let y = bTop; y <= bBot; y++) for (let x = cx - 3; x <= cx + 3; x++) setPx(x, y, col);
  });

  const ext = extractCandlesFromImageData(buf, w, h);
  assert.equal(ext.calibration.available, true);
  assert.ok(ext.calibration.points.length >= 6);
  assert.equal(ext.candles.length, src.length);
  for (let i = 0; i < src.length; i++) {
    assert.ok(Math.abs(ext.candles[i].h - src[i].h) <= 12, `bar ${i} H: ${ext.candles[i].h} vs ${src[i].h}`);
    assert.ok(Math.abs(ext.candles[i].l - src[i].l) <= 12, `bar ${i} L: ${ext.candles[i].l} vs ${src[i].l}`);
  }
});

test("1752x887 NIFTY-scale chart calibrates 54,000-55,800 with 55,473.65 pill anchor and 111 candles", () => {
  const w = 1752;
  const h = 887;
  const buf = new Uint8ClampedArray(w * h * 4);
  const fgGray = [120, 123, 134];
  const divGray = [224, 227, 235];
  const pillBg = [8, 153, 129];
  const white = [255, 255, 255];
  for (let i = 0; i < w * h; i++) {
    buf[i * 4] = 255;
    buf[i * 4 + 1] = 255;
    buf[i * 4 + 2] = 255;
    buf[i * 4 + 3] = 255;
  }
  const setPx = (x, y, rgb) => {
    if (x < 0 || x >= w || y < 0 || y >= h) return;
    const p = (Math.round(y) * w + Math.round(x)) * 4;
    buf[p] = rgb[0];
    buf[p + 1] = rgb[1];
    buf[p + 2] = rgb[2];
    buf[p + 3] = 255;
  };
  const divX = 1630;
  for (let y = 0; y < h; y++) setPx(divX, y, divGray);

  const pMin = 54000;
  const pMax = 55800;
  const yTop = 45;
  const yBot = 740;
  const p2y = (p) => yBot - ((p - pMin) / (pMax - pMin)) * (yBot - yTop);
  const drawText = (label, startX, yc, rgb, scale = 2) => {
    const ty = Math.round(yc - (7 * scale) / 2);
    let cx = startX;
    for (const ch of label) {
      const bm = FONT_5X7[ch];
      const cw = ch === "." || ch === "," ? 2 : 5;
      for (let r = 0; r < 7; r++) {
        const yr = ch === "," && r >= 5 ? r + 1 : r;
        for (let c = 0; c < 5; c++) {
          if (bm[r][c] === "1") {
            for (let sy = 0; sy < scale; sy++) {
              for (let sx = 0; sx < scale; sx++) {
                setPx(cx + c * scale + sx, ty + yr * scale + sy, rgb);
              }
            }
          }
        }
      }
      cx += (cw + 1) * scale;
    }
  };

  for (let tv = 54000; tv <= 55800; tv += 200) {
    drawText(`${tv.toLocaleString("en-US")}.00`, divX + 8, p2y(tv), fgGray, 2);
  }
  // Draw current-price teal pill badge 55,473.65 at its exact calibrated Y
  const pillY = Math.round(p2y(55473.65));
  for (let y = pillY - 10; y <= pillY + 10; y++) {
    for (let x = divX + 1; x <= w - 3; x++) setPx(x, y, pillBg);
  }
  drawText("55,473.65", divX + 8, pillY, white, 2);

  // Draw 111 candlesticks across 54,400-55,550
  const plotLeft = 50;
  const stepX = 14;
  for (let k = 0; k < 111; k++) {
    const cx = plotLeft + k * stepX;
    const base = 54450 + Math.sin(k * 0.14) * 350 + (k / 111) * 700;
    const o = base;
    const c = base + (k % 2 === 0 ? 45 : -30);
    const hVal = Math.max(o, c) + 35;
    const lVal = Math.min(o, c) - 35;
    const col = c >= o ? [8, 153, 129] : [242, 54, 69];
    for (let y = Math.round(p2y(hVal)); y <= Math.round(p2y(lVal)); y++) setPx(cx, y, col);
    for (let y = Math.round(p2y(Math.max(o, c))); y <= Math.round(p2y(Math.min(o, c))); y++) {
      for (let x = cx - 4; x <= cx + 4; x++) setPx(x, y, col);
    }
  }

  const ext = extractCandlesFromImageData(buf, w, h);
  assert.equal(ext.calibration.available, true);
  assert.ok(ext.calibration.points.length >= 6);
  assert.ok(ext.calibration.anchor && Math.abs(ext.calibration.anchor.price - 55473.65) < 0.01);
  assert.equal(ext.candles.length, 111);
  assert.ok(ext.ohlcRange.minLow >= 54000 && ext.ohlcRange.maxHigh <= 56000, `Got range ${JSON.stringify(ext.ohlcRange)}`);
});

test("calibratePriceAxis rejects 10,000-point discrepancy vs anchor and rejects 3 weak ticks", () => {
  // Exact reproduction of the 64,600..64,900 vs 55,473.65 failure mode
  const badScale = calibratePriceAxis(
    [
      { y: 120, price: 64900, label: "64,900", confidence: 0.52 },
      { y: 170, price: 64750, label: "64,750", confidence: 0.49 },
      { y: 220, price: 64600, label: "64,600", confidence: 0.48 },
    ],
    "right",
    {
      imageHeight: 887,
      anchor: { price: 55473.65, y: 169, label: "55,473.65", source: "axis_pill" },
      requireMultiTicks: true,
    }
  );
  assert.equal(badScale.available, false);
  assert.equal(badScale.slope, null);

  // Even if anchor is absent, 3 weak/narrow ticks on an 887px chart must fail closed
  const weakThree = calibratePriceAxis(
    [
      { y: 120, price: 64900, label: "64,900", confidence: 0.45 },
      { y: 170, price: 64750, label: "64,750", confidence: 0.44 },
      { y: 220, price: 64600, label: "64,600", confidence: 0.45 },
    ],
    "right",
    { imageHeight: 887, requireMultiTicks: true }
  );
  assert.equal(weakThree.available, false);

  // Even with 4 ticks matching internally, contradicting the current-price anchor MUST fail closed (never offset by 10,000!)
  const anchorMismatch = calibratePriceAxis(
    [
      { y: 100, price: 65000, label: "65,000", confidence: 0.90 },
      { y: 250, price: 64600, label: "64,600", confidence: 0.90 },
      { y: 400, price: 64200, label: "64,200", confidence: 0.90 },
      { y: 550, price: 63800, label: "63,800", confidence: 0.90 },
    ],
    "right",
    {
      imageHeight: 887,
      anchor: { price: 55473.65, y: 169, label: "55,473.65", source: "axis_pill" },
      requireMultiTicks: true,
    }
  );
  assert.equal(anchorMismatch.available, false);
  assert.match(anchorMismatch.reason || "", /contradict/i);
});

test("extractCandlesFromImageData refuses calibration when no axis ticks exist", () => {
  const source = [
    { o: 2490, h: 2495, l: 2485, c: 2488 },
    { o: 2488, h: 2492, l: 2480, c: 2482 },
    { o: 2482, h: 2486, l: 2476, c: 2478 },
  ];
  const noAxis = makeSyntheticChartRGBA({
    ticks: [],
    candles: source,
    priceMin: 2452,
    priceMax: 2516,
  });
  const ext = extractCandlesFromImageData(noAxis.buf, noAxis.width, noAxis.height);
  assert.equal(ext.calibration.available, false);
  assert.equal(ext.calibration.slope, null);
  assert.equal(ext.ohlcRange, null);
  assert.equal(ext.candles.length, source.length);
  assert.ok(Number.isNaN(ext.candles[0].o));
  assert.ok(Number.isNaN(ext.priceToY(2500)));
});
