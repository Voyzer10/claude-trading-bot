export type ExtractedCandle = {
  index: number;
  x: number;
  yHigh: number;
  yLow: number;
  yOpen: number;
  yClose: number;
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  bullish: boolean;
};

export type ExtractedChart = {
  width: number;
  height: number;
  plotTop: number;
  plotBottom: number;
  darkTheme: boolean;
  candles: ExtractedCandle[];
  priceToY: (price: number) => number;
  indexToX: (index: number) => number;
};

export type ChartAnalysis = {
  scanner_version: string;
  strategy_name: string;
  strategy_summary: string;
  candle_count: number;
  summary: { bias: string; setups_found: number; best_rr: number };
  swings: { index: number; price: number; kind: string }[];
  lines: { kind: string; label: string; start: number; end: number; price: number; side?: string }[];
  zones: { kind: string; label: string; start: number; end: number; high: number; low: number; side?: string }[];
  markers: { index: number; price: number; kind: string; label: string; side?: string }[];
  trades: { side: string; status: string; entry_index: number; entry: number; sl: number; tp: number; rr: number; label: string }[];
  checklist: { step: string; passed: boolean; detail: string }[];
};

const PRICE_BASE = 100;
const PRICE_SPAN = 1000;

export function extractCandlesFromImage(img: HTMLImageElement): ExtractedChart {
  const w = img.naturalWidth || img.width;
  const h = img.naturalHeight || img.height;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("Canvas 2D context unavailable");
  ctx.drawImage(img, 0, 0, w, h);

  const imgData = ctx.getImageData(0, 0, w, h).data;
  const xStart = Math.floor(w * 0.03);
  const xEnd = Math.floor(w * 0.88);
  const yStart = Math.floor(h * 0.08);
  const yEnd = Math.floor(h * 0.87);

  // Sample background luminance
  let bgLumSum = 0;
  let bgSamples = 0;
  for (let y = yStart; y < yEnd; y += Math.max(1, Math.floor((yEnd - yStart) / 20))) {
    for (let x = xStart; x < xEnd; x += Math.max(1, Math.floor((xEnd - xStart) / 20))) {
      const i = (y * w + x) * 4;
      bgLumSum += 0.299 * imgData[i] + 0.587 * imgData[i + 1] + 0.114 * imgData[i + 2];
      bgSamples++;
    }
  }
  const bgLum = bgSamples ? bgLumSum / bgSamples : 30;
  const darkTheme = bgLum < 128;

  type ColInfo = { x: number; bullCount: number; bearCount: number; top: number; bot: number; isBull: boolean };
  const cols: ColInfo[] = [];

  for (let x = xStart; x < xEnd; x++) {
    let bullCount = 0;
    let bearCount = 0;
    let top = h;
    let bot = 0;
    for (let y = yStart; y < yEnd; y++) {
      const i = (y * w + x) * 4;
      const r = imgData[i];
      const g = imgData[i + 1];
      const b = imgData[i + 2];
      const isBull = g > r + 14 && g > b + 6 && g > 50;
      const isBear = r > g + 14 && r > b + 6 && r > 50;
      if (isBull) {
        bullCount++;
        if (y < top) top = y;
        if (y > bot) bot = y;
      } else if (isBear) {
        bearCount++;
        if (y < top) top = y;
        if (y > bot) bot = y;
      }
    }
    if (bullCount + bearCount >= 1) {
      cols.push({ x, bullCount, bearCount, top, bot, isBull: bullCount >= bearCount });
    }
  }

  // Group strictly adjacent columns of the SAME polarity (bull vs bear)
  const rawGroups: ColInfo[][] = [];
  for (const col of cols) {
    const last = rawGroups[rawGroups.length - 1];
    if (last && col.x - last[last.length - 1].x === 1 && last[0].isBull === col.isBull) {
      last.push(col);
    } else {
      rawGroups.push([col]);
    }
  }

  // Estimate typical candle width from small runs, then split wide same-color runs
  const smallWidths = rawGroups.map((g) => g.length).filter((len) => len >= 1 && len <= 10).sort((a, b) => a - b);
  const medianW = smallWidths.length ? smallWidths[Math.floor(smallWidths.length / 2)] : 3;
  const pitch = Math.max(2, medianW);

  const groups: ColInfo[][] = [];
  for (const grp of rawGroups) {
    if (grp.length > Math.max(48, w * 0.08)) continue; // skip wide UI elements
    if (grp.length > Math.max(6, pitch * 1.7)) {
      const parts = Math.max(2, Math.round(grp.length / pitch));
      const step = grp.length / parts;
      for (let p = 0; p < parts; p++) {
        const slice = grp.slice(Math.floor(p * step), Math.floor((p + 1) * step));
        if (slice.length) groups.push(slice);
      }
    } else {
      groups.push(grp);
    }
  }

  const rawCandles: Omit<ExtractedCandle, "index" | "t" | "o" | "h" | "l" | "c">[] = [];
  for (const grp of groups) {
    let bull = 0;
    let bear = 0;
    let bodyTop = h;
    let bodyBot = 0;
    for (const c of grp) {
      bull += c.bullCount;
      bear += c.bearCount;
      if (c.top < bodyTop) bodyTop = c.top;
      if (c.bot > bodyBot) bodyBot = c.bot;
    }
    const cx = Math.round((grp[0].x + grp[grp.length - 1].x) / 2);
    const bullish = bull >= bear;

    // Scan wicks above and below body along center x (+/- 1px)
    let yHigh = bodyTop;
    let yLow = bodyBot;
    const wickHit = (x: number, y: number) => {
      if (x < 0 || x >= w || y < yStart || y >= yEnd) return false;
      const i = (y * w + x) * 4;
      const lum = 0.299 * imgData[i] + 0.587 * imgData[i + 1] + 0.114 * imgData[i + 2];
      return Math.abs(lum - bgLum) > 18;
    };

    for (let y = bodyTop - 1; y >= yStart; y--) {
      if (wickHit(cx, y) || wickHit(cx - 1, y) || wickHit(cx + 1, y)) {
        yHigh = y;
      } else if (yHigh - y > 4) {
        break;
      }
    }
    for (let y = bodyBot + 1; y < yEnd; y++) {
      if (wickHit(cx, y) || wickHit(cx - 1, y) || wickHit(cx + 1, y)) {
        yLow = y;
      } else if (y - yLow > 4) {
        break;
      }
    }

    if (yLow - yHigh < 3) continue;
    const yOpen = bullish ? bodyBot : bodyTop;
    const yClose = bullish ? bodyTop : bodyBot;
    rawCandles.push({ x: cx, yHigh, yLow, yOpen, yClose, bullish });
  }

  // Filter out outliers if plot area had stray colored UI elements
  const plotTop = rawCandles.length ? Math.min(...rawCandles.map((c) => c.yHigh)) : yStart;
  const plotBottom = rawCandles.length ? Math.max(...rawCandles.map((c) => c.yLow)) : yEnd;
  const spanY = Math.max(10, plotBottom - plotTop);

  const yToPrice = (y: number) => PRICE_BASE + ((plotBottom - y) / spanY) * PRICE_SPAN;
  const priceToY = (price: number) => plotBottom - ((price - PRICE_BASE) / PRICE_SPAN) * spanY;

  const baseTs = Math.floor(Date.now() / 1000) - rawCandles.length * 300;
  const candles: ExtractedCandle[] = rawCandles.map((c, idx) => ({
    ...c,
    index: idx,
    t: baseTs + idx * 300,
    o: Number(yToPrice(c.yOpen).toFixed(2)),
    h: Number(yToPrice(c.yHigh).toFixed(2)),
    l: Number(yToPrice(c.yLow).toFixed(2)),
    c: Number(yToPrice(c.yClose).toFixed(2)),
  }));

  const indexToX = (index: number) => {
    if (!candles.length) return w / 2;
    const clamped = Math.max(0, Math.min(candles.length - 1, Math.round(index)));
    return candles[clamped].x;
  };

  // Suppress unused variable warning for darkTheme (available for future threshold tuning)
  void darkTheme;

  return { width: w, height: h, plotTop, plotBottom, darkTheme, candles, priceToY, indexToX };
}

type Rect = { x: number; y: number; w: number; h: number };

function drawLabel(
  ctx: CanvasRenderingContext2D,
  text: string,
  cx: number,
  cy: number,
  color: string,
  halo: string,
  placed: Rect[] = [],
  fontSize = 13
) {
  ctx.font = `800 ${fontSize}px system-ui, -apple-system, Segoe UI, sans-serif`;
  const tw = ctx.measureText(text).width;
  const bh = fontSize + 4;
  const bx = Math.max(6, Math.min(ctx.canvas.width - tw - 6, cx - tw / 2));
  let by = Math.max(bh + 2, Math.min(ctx.canvas.height - 6, cy));

  for (let attempt = 0; attempt < 6; attempt++) {
    const hit = placed.some(
      (r) => bx < r.x + r.w + 4 && bx + tw + 4 > r.x && by - bh < r.y && by > r.y - r.h
    );
    if (!hit) break;
    by += attempt % 2 === 0 ? -18 : 22;
  }
  placed.push({ x: bx, y: by, w: tw, h: bh });

  ctx.save();
  ctx.lineWidth = 4;
  ctx.strokeStyle = halo;
  ctx.lineJoin = "round";
  ctx.strokeText(text, bx, by);
  ctx.fillStyle = color;
  ctx.fillText(text, bx, by);
  ctx.restore();
}

function drawArrow(
  ctx: CanvasRenderingContext2D,
  x: number,
  tipY: number,
  pointDown: boolean,
  color: string,
  len = 24
) {
  const startY = pointDown ? tipY - len : tipY + len;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(x, startY);
  ctx.lineTo(x, tipY + (pointDown ? -4 : 4));
  ctx.stroke();

  const head = 7;
  ctx.beginPath();
  ctx.moveTo(x, tipY);
  ctx.lineTo(x - head, tipY + (pointDown ? -head * 1.3 : head * 1.3));
  ctx.lineTo(x + head, tipY + (pointDown ? -head * 1.3 : head * 1.3));
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

export function renderAnnotatedChart(
  img: HTMLImageElement,
  extracted: ExtractedChart,
  analysis: ChartAnalysis
): string {
  const { width: w, height: h, darkTheme, priceToY, indexToX } = extracted;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context unavailable");

  ctx.drawImage(img, 0, 0, w, h);
  const placed: Rect[] = [];
  const ink = darkTheme ? "#f8fafc" : "#0f172a";
  const halo = darkTheme ? "rgba(9, 9, 11, 0.85)" : "rgba(255, 255, 255, 0.9)";

  // 1. Zones (FVG, OB)
  for (const z of analysis.zones || []) {
    const x1 = indexToX(z.start);
    const x2 = Math.max(x1 + 24, indexToX(z.end));
    const y1 = priceToY(z.high);
    const y2 = priceToY(z.low);
    const isBuy = z.side === "BUY";
    ctx.fillStyle = isBuy ? "rgba(34, 197, 94, 0.16)" : "rgba(239, 68, 68, 0.16)";
    ctx.strokeStyle = isBuy ? "#16a34a" : "#dc2626";
    ctx.lineWidth = 1.5;
    ctx.fillRect(x1, y1, x2 - x1, Math.max(4, y2 - y1));
    ctx.strokeRect(x1, y1, x2 - x1, Math.max(4, y2 - y1));
    drawLabel(ctx, z.label, (x1 + x2) / 2, y1 - 6, isBuy ? "#15803d" : "#b91c1c", halo, placed, 11);
  }

  // 2. Trade Position Boxes (TradingView-style Long / Short box: Entry, SL, TP)
  for (const tr of analysis.trades || []) {
    const xStart = indexToX(tr.entry_index);
    const boxEndIdx = Math.min(extracted.candles.length - 1, tr.entry_index + 18);
    const xEnd = Math.min(w - 20, Math.max(xStart + 100, indexToX(boxEndIdx)));
    const yEntry = priceToY(tr.entry);
    const ySl = priceToY(tr.sl);
    const yTp = priceToY(tr.tp);

    ctx.fillStyle = "rgba(34, 197, 94, 0.20)";
    ctx.fillRect(xStart, Math.min(yEntry, yTp), xEnd - xStart, Math.abs(yTp - yEntry));
    ctx.fillStyle = "rgba(239, 68, 68, 0.20)";
    ctx.fillRect(xStart, Math.min(yEntry, ySl), xEnd - xStart, Math.abs(ySl - yEntry));

    const drawLevel = (y: number, color: string, label: string) => {
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(xStart, y);
      ctx.lineTo(xEnd, y);
      ctx.stroke();
      ctx.restore();
      drawLabel(ctx, label, xEnd + 34, y + 4, color, halo, placed, 11);
    };

    const sideLabel = tr.side === "BUY" ? "LONG" : "SHORT";
    drawLevel(yTp, "#16a34a", `TP (${tr.rr}R)`);
    drawLevel(yEntry, "#ca8a04", `ENTRY ${sideLabel}`);
    drawLevel(ySl, "#dc2626", "SL");
  }

  // 3. Structure & Liquidity Dotted Lines (BOS, CHOCH, SWEPT)
  for (const ln of analysis.lines || []) {
    const x1 = indexToX(ln.start);
    const x2 = Math.max(x1 + 30, indexToX(ln.end));
    const y = priceToY(ln.price);
    const lineColor =
      ln.kind === "CHoCH" ? (darkTheme ? "#fbbf24" : "#0f172a") :
      ln.kind === "BOS" ? (darkTheme ? "#38bdf8" : "#0f172a") :
      "#9333ea";

    ctx.save();
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 3;
    ctx.setLineDash([2, 7]);
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(x1, y);
    ctx.lineTo(x2, y);
    ctx.stroke();
    ctx.restore();

    const midX = (x1 + x2) / 2;
    const above = ln.side === "BUY";
    drawLabel(ctx, ln.label.toUpperCase(), midX, above ? y - 10 : y + 18, lineColor, halo, placed, 14);
  }

  // 4. Key Swing High / Swing Low Arrows
  for (const sw of analysis.swings || []) {
    const x = indexToX(sw.index);
    const y = priceToY(sw.price);
    const isHigh = sw.kind === "SH";
    drawArrow(ctx, x, isHigh ? y - 4 : y + 4, isHigh, ink, 22);
    drawLabel(ctx, isHigh ? "SWING HIGH" : "SWING LOW", x + 36, isHigh ? y - 18 : y + 26, ink, halo, placed, 11);
  }

  // 5. Setup Markers (LIQ SWEEP, CANDLESTICK PATTERN, CONFIRM)
  for (const mk of analysis.markers || []) {
    const x = indexToX(mk.index);
    const y = priceToY(mk.price);
    const isBuy = mk.side === "BUY";
    const color =
      mk.kind === "SWEEP" ? "#9333ea" :
      mk.kind === "CONFIRM" || mk.kind === "ENTRY" ? "#16a34a" : "#d97706";

    drawArrow(ctx, x, isBuy ? y + 4 : y - 4, !isBuy, color, 20);
    drawLabel(ctx, mk.label.toUpperCase(), x, isBuy ? y + 36 : y - 28, color, halo, placed, 11);
  }

  // 6. Clean top-left summary text
  const banner = `${analysis.strategy_name} · ${analysis.candle_count} candles · Bias: ${analysis.summary.bias} · ${analysis.summary.setups_found} setup(s)`;
  drawLabel(ctx, banner, 190, 20, ink, halo, placed, 11);

  return canvas.toDataURL("image/png");
}
