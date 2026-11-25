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

export type AxisTickPoint = {
  y: number;
  price: number;
  label: string;
  confidence?: number;
};

export type PriceAnchor = {
  price: number;
  y: number | null;
  label: string;
  source: "axis_pill" | "header_ohlc";
};

export type PriceCalibration = {
  available: boolean;
  points: AxisTickPoint[];
  anchor?: PriceAnchor | null;
  slope: number | null;
  intercept: number | null;
  axisSide: "right" | "left" | "none";
  maxResidualPx?: number;
  reason?: string;
};

export type ExtractedChart = {
  width: number;
  height: number;
  plotTop: number;
  plotBottom: number;
  darkTheme: boolean;
  candles: ExtractedCandle[];
  calibration: PriceCalibration;
  ohlcRange: { minLow: number; maxHigh: number } | null;
  priceToY: (price: number) => number;
  yToPrice: (y: number) => number;
  indexToX: (index: number) => number;
};

export type KeyCandleRow = {
  num: number;
  index: number;
  open: number;
  high: number;
  low: number;
  close: number;
  note: string;
  highlight: string;
};

export type ChartAnalysis = {
  scanner_version: string;
  strategy_name: string;
  strategy_summary: string;
  candle_count: number;
  summary: { bias: string; setups_found: number; best_rr: number };
  swings: { index: number; price: number; kind: string }[];
  lines: { kind: string; label: string; sublabel?: string; start: number; end: number; price: number; side?: string }[];
  zones: { kind: string; label: string; sublabel?: string; start: number; end: number; high: number; low: number; side?: string }[];
  markers: {
    index: number;
    price: number;
    kind: string;
    label: string;
    sublabel?: string;
    side?: string;
    pool_level?: number;
    start?: number;
    end?: number;
  }[];
  trades: {
    side: string;
    status: string;
    entry_index: number;
    confirm_index?: number;
    sweep_index?: number;
    entry: number;
    sl: number;
    tp: number;
    rr: number;
    risk_pts?: number;
    reward_pts?: number;
    entry_mode?: string;
    tp_pool_index?: number;
    tp_label?: string;
    outcome?: string;
    exit_index?: number;
    exit_price?: number;
    realized_r?: number;
    pattern_name?: string | null;
    label: string;
  }[];
  checklist: { step: string; passed: boolean; detail: string }[];
  calibration_available?: boolean;
  calibration_reason?: string;
  validation?: {
    side: string;
    structure_passed: boolean;
    choch_passed: boolean;
    bos_passed: boolean;
    liquidity_passed: boolean;
    pattern_passed: boolean;
    confirmation_passed: boolean;
    confirmation_count: number;
    target_pool_passed: boolean;
    execution_passed: boolean;
    setup_valid: boolean;
    rejection_reasons: string[];
  };
  v6_flow?: {
    flow_text: string;
    modules: { key: string; label: string; passed: boolean }[];
  };
  key_candles?: KeyCandleRow[];
  logic_summary?: { step: number; title: string; detail: string }[];
  concepts?: { name: string; detail: string; passed: boolean }[];
};

// Canonical 7x9 multi-variant digit templates for axis tick OCR (works across dark/light themes & headless Node buffers)
const RAW_DIGIT_TEMPLATES: Record<string, string[]> = {
  "0": ["  ###  ", " #   # ", "#     #", "#     #", "#     #", "#     #", "#     #", " #   # ", "  ###  "],
  "0b": [" ##### ", "#     #", "#     #", "#     #", "#     #", "#     #", "#     #", "#     #", " ##### "],
  "0c": ["  ###  ", " #   # ", "#    ##", "#   # #", "#  #  #", "# #   #", "##    #", " #   # ", "  ###  "],
  "1": ["   ##  ", "  ###  ", " ## #  ", "    #  ", "    #  ", "    #  ", "    #  ", "    #  ", "  #####"],
  "1b": ["   #   ", "  ##   ", " # #   ", "   #   ", "   #   ", "   #   ", "   #   ", "   #   ", "   #   "],
  "1c": ["   #   ", "  ##   ", " # #   ", "   #   ", "   #   ", "   #   ", "   #   ", "   #   ", " ##### "],
  "2": [" ##### ", "#     #", "      #", "      #", "    ## ", "  ##   ", " #     ", "#      ", "#######"],
  "2b": ["  ###  ", " #   # ", "     # ", "    #  ", "   #   ", "  #    ", " #     ", "#      ", "#######"],
  "3": [" ##### ", "#     #", "      #", "      #", "  #### ", "      #", "      #", "#     #", " ##### "],
  "4": ["    ## ", "   ### ", "  # ## ", " #  ## ", "#   ## ", "#######", "    ## ", "    ## ", "    ## "],
  "4b": ["    #  ", "   ##  ", "  # #  ", " #  #  ", "#   #  ", "###### ", "    #  ", "    #  ", "    #  "],
  "4c": ["    #  ", "   ##  ", "  # #  ", " #  #  ", " #  #  ", "#   #  ", "#######", "    #  ", "    #  "],
  "5": ["#######", "#      ", "#      ", "###### ", "      #", "      #", "      #", "#     #", " ##### "],
  "5b": [" ######", " #     ", " #     ", " ##### ", "      #", "      #", "      #", " #    #", "  #### "],
  "6": ["  #### ", " #     ", "#      ", "# #### ", "##    #", "#     #", "#     #", " #   # ", "  ###  "],
  "6b": ["   ### ", "  #    ", " #     ", "#####  ", "##   # ", "#     #", "#     #", " #   # ", "  ###  "],
  "7": ["#######", "      #", "     # ", "    #  ", "   #   ", "   #   ", "  #    ", "  #    ", "  #    "],
  "8": [" ##### ", "#     #", "#     #", " ##### ", "#     #", "#     #", "#     #", "#     #", " ##### "],
  "8b": ["  ###  ", " #   # ", " #   # ", "  ###  ", " #   # ", "#     #", "#     #", " #   # ", "  ###  "],
  "9": ["  ###  ", " #   # ", "#     #", "#    ##", " #### #", "      #", "     # ", "    #  ", " ####  "],
  "9b": ["  ###  ", " #   # ", "#     #", "#     #", " ##### ", "     # ", "    #  ", "   #   ", " ####  "],
};

function zeroMeanNorm(vec: Float64Array): Float64Array {
  let mean = 0;
  for (let i = 0; i < vec.length; i++) mean += vec[i];
  mean /= vec.length;
  const out = new Float64Array(vec.length);
  let norm = 0;
  for (let i = 0; i < vec.length; i++) {
    out[i] = vec[i] - mean;
    norm += out[i] * out[i];
  }
  norm = Math.sqrt(norm) || 1;
  for (let i = 0; i < vec.length; i++) out[i] /= norm;
  return out;
}

const COMPILED_DIGIT_TEMPLATES = Object.entries(RAW_DIGIT_TEMPLATES).map(([k, rows]) => {
  const vec = new Float64Array(63);
  for (let r = 0; r < 9; r++) {
    for (let c = 0; c < 7; c++) {
      vec[r * 7 + c] = rows[r][c] === "#" ? 1 : 0;
    }
  }
  return { digit: k[0], vec: zeroMeanNorm(vec) };
});

function parseAxisNumber(raw: string): number | null {
  if (!raw) return null;
  // Require proper decimal/grouping syntax without double dots or stray signs
  if (!/^-?\d+(,\d{3})*(\.\d+)?$/.test(raw) && !/^-?\d+(\.\d+)?$/.test(raw)) return null;
  const num = Number(raw.replace(/,/g, ""));
  return Number.isFinite(num) ? num : null;
}

function readNumericBandFromFg(
  fgAt: (x: number, y: number) => number,
  x0: number,
  x1: number,
  digitTop: number,
  digitBot: number,
  scanTop: number,
  scanBot: number,
  skipCol?: Uint8Array
): { text: string; minScore: number; minX: number; maxX: number } | null {
  const bh = digitBot - digitTop + 1;
  if (bh < 5 || bh > 28) return null;

  const colMax = new Float64Array(Math.max(1, x1 - x0));
  let bandMaxFg = 0;
  for (let x = x0; x < x1; x++) {
    if (skipCol && skipCol[x - x0]) continue;
    let m = 0;
    for (let y = scanTop; y <= scanBot; y++) m = Math.max(m, fgAt(x, y));
    colMax[x - x0] = m;
    if (m > bandMaxFg) bandMaxFg = m;
  }
  if (bandMaxFg < 24) return null;

  const segThresh = Math.max(22, bandMaxFg * 0.30);
  const pixThresh = Math.max(14, bandMaxFg * 0.20);

  const splitBoxIfWide = (cx0: number, cx1: number): [number, number][] => {
    const gw = cx1 - cx0 + 1;
    if (gw <= bh * 1.15) return [[cx0, cx1]];
    let bestX = -1;
    let minSum = Infinity;
    const lo = cx0 + Math.floor(gw * 0.25);
    const hi = cx1 - Math.floor(gw * 0.25);
    for (let x = lo; x <= hi; x++) {
      let s = 0;
      for (let y = scanTop; y <= scanBot; y++) s += fgAt(x, y);
      if (s < minSum) {
        minSum = s;
        bestX = x;
      }
    }
    if (bestX > cx0 && bestX < cx1) {
      return [...splitBoxIfWide(cx0, bestX - 1), ...splitBoxIfWide(bestX + 1, cx1)];
    }
    return [[cx0, cx1]];
  };

  const boxes: { cx0: number; cx1: number; cy0: number; cy1: number }[] = [];
  let cx0 = -1;
  for (let i = 0; i <= colMax.length; i++) {
    const on = i < colMax.length && colMax[i] > segThresh;
    if (on && cx0 < 0) cx0 = x0 + i;
    else if (!on && cx0 >= 0) {
      const cx1 = x0 + i - 1;
      for (const [sx0, sx1] of splitBoxIfWide(cx0, cx1)) {
        let cy0 = scanBot;
        let cy1 = scanTop;
        for (let y = scanTop; y <= scanBot; y++) {
          for (let x = sx0; x <= sx1; x++) {
            if (fgAt(x, y) > pixThresh) {
              if (y < cy0) cy0 = y;
              if (y > cy1) cy1 = y;
            }
          }
        }
        if (cy1 >= cy0) boxes.push({ cx0: sx0, cx1: sx1, cy0, cy1 });
      }
      cx0 = -1;
    }
  }
  if (!boxes.length || boxes[0].cx0 <= x0) return null;

  let text = "";
  let minScore = 1.0;
  for (const g of boxes) {
    const gw = g.cx1 - g.cx0 + 1;
    const gh = g.cy1 - g.cy0 + 1;
    if (gh <= Math.max(4, Math.round(bh * 0.55)) && g.cy0 >= digitTop + bh * 0.46) {
      text += g.cy1 > digitBot ? "," : ".";
      continue;
    }
    if (gh <= bh * 0.35 && gw >= gh * 1.3 && g.cy0 >= digitTop + bh * 0.25 && g.cy1 <= digitTop + bh * 0.75) {
      text += "-";
      continue;
    }
    if (gw > bh * 1.4) return null;

    const rawVec = new Float64Array(63);
    let maxVal = 1;
    for (let r = 0; r < 9; r++) {
      for (let c = 0; c < 7; c++) {
        const sx = g.cx0 + (c + 0.5) * (gw / 7) - 0.5;
        const sy = g.cy0 + (r + 0.5) * (gh / 9) - 0.5;
        const lx0 = Math.max(g.cx0, Math.min(g.cx1, Math.floor(sx)));
        const lx1 = Math.min(g.cx1, lx0 + 1);
        const ly0 = Math.max(g.cy0, Math.min(g.cy1, Math.floor(sy)));
        const ly1 = Math.min(g.cy1, ly0 + 1);
        const fx = Math.max(0, Math.min(1, sx - lx0));
        const fy = Math.max(0, Math.min(1, sy - ly0));
        const val =
          (fgAt(lx0, ly0) * (1 - fx) + fgAt(lx1, ly0) * fx) * (1 - fy) +
          (fgAt(lx0, ly1) * (1 - fx) + fgAt(lx1, ly1) * fx) * fy;
        rawVec[r * 7 + c] = val;
        if (val > maxVal) maxVal = val;
      }
    }
    for (let i = 0; i < 63; i++) rawVec[i] /= maxVal;
    const avgRegion = (r0: number, r1: number, c0: number, c1: number) => {
      let s = 0;
      let cnt = 0;
      for (let rr = r0; rr <= r1; rr++) {
        for (let cc = c0; cc <= c1; cc++) {
          s += rawVec[rr * 7 + cc];
          cnt++;
        }
      }
      return cnt ? s / cnt : 0;
    };
    const tl = avgRegion(1, 3, 0, 1);
    const tr = avgRegion(1, 3, 5, 6);
    const bl = avgRegion(5, 7, 0, 1);
    const br = avgRegion(5, 7, 5, 6);
    const mid = avgRegion(3, 5, 2, 4);
    const topRightBar = avgRegion(0, 1, 5, 6);
    const edgesMid = (rawVec[4 * 7 + 0] + rawVec[4 * 7 + 6]) / 2;

    const vec = zeroMeanNorm(rawVec);
    let bestD = "?";
    let bestS = -1;
    for (const t of COMPILED_DIGIT_TEMPLATES) {
      let dot = 0;
      for (let i = 0; i < 63; i++) dot += vec[i] * t.vec[i];
      let bonus = 0;
      if (t.digit === "0") bonus = (mid < 0.22 ? 0.12 : edgesMid > 0.45 ? 0.04 : -0.18) + (tl > 0.25 && tr > 0.25 && bl > 0.25 && br > 0.25 ? 0.08 : -0.08);
      else if (t.digit === "8") bonus = (mid > 0.30 && edgesMid < 0.45 ? 0.10 : mid < 0.22 ? -0.18 : 0) + (tl > 0.22 && bl > 0.22 ? 0.08 : -0.20);
      else if (t.digit === "3") bonus = (tl < 0.25 && bl < 0.25 ? 0.10 : -0.18) + (tr > 0.25 && br > 0.25 ? 0.06 : -0.10);
      else if (t.digit === "5") bonus = (tl > 0.22 && tr < 0.25 && br > 0.22 && topRightBar > 0.30 ? 0.14 : (tr > 0.35 ? -0.10 : 0));
      else if (t.digit === "6") bonus = (tl > 0.22 && tr < 0.25 && bl > 0.25 && br > 0.22 && topRightBar < 0.35 ? 0.14 : -0.06);
      else if (t.digit === "9") bonus = (tl > 0.25 && tr > 0.25 && bl < 0.25 && br > 0.25 ? 0.12 : -0.10);
      const score = dot + bonus;
      if (score > bestS) {
        bestS = score;
        bestD = t.digit;
      }
    }
    if (bestS < minScore) minScore = bestS;
    text += bestD;
  }

  return { text, minScore, minX: boxes[0].cx0, maxX: boxes[boxes.length - 1].cx1 };
}

function extractAxisPillAnchor(
  imgData: Uint8ClampedArray | Uint8Array,
  w: number,
  h: number,
  x0: number,
  x1: number,
  bgLum: number
): PriceAnchor | null {
  const yMin = Math.floor(h * 0.04);
  const yMax = Math.floor(h * 0.88);
  const stripW = Math.max(1, x1 - x0);
  // Find rows with dense filled background differing from strip bgLum (colored pill box on axis)
  const pillRow = new Uint8Array(h);
  for (let y = yMin; y < yMax; y++) {
    let diff = 0;
    for (let x = x0; x < x1; x++) {
      const i = (y * w + x) * 4;
      const lum = 0.299 * imgData[i] + 0.587 * imgData[i + 1] + 0.114 * imgData[i + 2];
      const sat = Math.max(imgData[i], imgData[i + 1], imgData[i + 2]) - Math.min(imgData[i], imgData[i + 1], imgData[i + 2]);
      if (Math.abs(lum - bgLum) > 28 && (sat > 20 || Math.abs(lum - bgLum) > 55)) diff++;
    }
    if (diff >= Math.max(20, stripW * 0.40)) pillRow[y] = 1;
  }

  let pTop = -1;
  let bestAnchor: PriceAnchor | null = null;
  for (let y = yMin; y <= yMax; y++) {
    const on = y < yMax && pillRow[y] === 1;
    if (on && pTop < 0) pTop = y;
    else if (!on && pTop >= 0) {
      const pBot = y - 1;
      const ph = pBot - pTop + 1;
      if (ph >= 10 && ph <= 34) {
        // Sample pill interior border color from top+1 row to use as pill background
        const midY = pTop + 1;
        let sr = 0;
        let sg = 0;
        let sb = 0;
        let sc = 0;
        let pillX0 = x1;
        let pillX1 = x0;
        for (let x = x0; x < x1; x++) {
          const i = (midY * w + x) * 4;
          const lum = 0.299 * imgData[i] + 0.587 * imgData[i + 1] + 0.114 * imgData[i + 2];
          if (Math.abs(lum - bgLum) > 25) {
            sr += imgData[i];
            sg += imgData[i + 1];
            sb += imgData[i + 2];
            sc++;
            if (x < pillX0) pillX0 = x;
            if (x > pillX1) pillX1 = x;
          }
        }
        if (sc >= 12 && pillX1 - pillX0 >= 20) {
          const pr = sr / sc;
          const pg = sg / sc;
          const pb = sb / sc;
          const ix0 = pillX0 + 1;
          const ix1 = pillX1;
          const pillFg = (px: number, py: number) => {
            if (px < ix0 || px >= ix1 || py < pTop || py > pBot) return 0;
            const i = (py * w + px) * 4;
            const dist = Math.hypot(imgData[i] - pr, imgData[i + 1] - pg, imgData[i + 2] - pb);
            return Math.max(0, dist - 28);
          };
          // Find tight text rows inside pill
          let dTop = pBot;
          let dBot = pTop;
          for (let ry = pTop; ry <= pBot; ry++) {
            let fgCnt = 0;
            for (let rx = ix0; rx < ix1; rx++) if (pillFg(rx, ry) > 28) fgCnt++;
            if (fgCnt >= 3) {
              if (ry < dTop) dTop = ry;
              if (ry > dBot) dBot = ry;
            }
          }
          if (dBot - dTop + 1 >= 5) {
            const read = readNumericBandFromFg(pillFg, ix0, ix1, dTop, dBot, dTop, Math.min(pBot, dBot + 1));
            if (read && read.minScore >= 0.36) {
              const price = parseAxisNumber(read.text);
              if (price !== null) {
                bestAnchor = { price, y: (dTop + dBot) / 2, label: read.text, source: "axis_pill" };
              }
            }
          }
        }
      }
      pTop = -1;
    }
  }
  return bestAnchor;
}

function scanAxisStrip(
  imgData: Uint8ClampedArray | Uint8Array,
  w: number,
  h: number,
  x0: number,
  x1: number
): { points: AxisTickPoint[]; anchor: PriceAnchor | null; textMinX: number; textMaxX: number } {
  const yMin = Math.floor(h * 0.03);
  const yMax = Math.floor(h * 0.88);
  const lums: number[] = [];
  for (let y = yMin; y < yMax; y += 3) {
    for (let x = x0; x < x1; x += 3) {
      const i = (y * w + x) * 4;
      lums.push(0.299 * imgData[i] + 0.587 * imgData[i + 1] + 0.114 * imgData[i + 2]);
    }
  }
  if (!lums.length) return { points: [], anchor: null, textMinX: x1, textMaxX: x0 };
  lums.sort((a, b) => a - b);
  const bgLum = lums[Math.floor(lums.length / 2)];

  const fgAt = (x: number, y: number) => {
    if (x < x0 || x >= x1 || y < 0 || y >= h) return 0;
    const i = (y * w + x) * 4;
    const lum = 0.299 * imgData[i] + 0.587 * imgData[i + 1] + 0.114 * imgData[i + 2];
    return Math.max(0, Math.abs(lum - bgLum) - 14);
  };

  const rowSpan = Math.max(1, yMax - yMin);
  const skipCol = new Uint8Array(x1 - x0);
  for (let x = x0; x < x1; x++) {
    let activeRows = 0;
    for (let y = yMin; y < yMax; y += 2) {
      if (fgAt(x, y) > 10) activeRows++;
    }
    if (activeRows > (rowSpan / 2) * 0.52) skipCol[x - x0] = 1;
  }

  const rowFg = new Int32Array(h);
  for (let y = yMin; y < yMax; y++) {
    let cnt = 0;
    for (let x = x0; x < x1; x++) {
      if (!skipCol[x - x0] && fgAt(x, y) > 22) cnt++;
    }
    rowFg[y] = cnt;
  }

  type Band = { digitTop: number; digitBot: number; scanTop: number; scanBot: number };
  const bands: Band[] = [];
  let bTop = -1;
  for (let y = yMin; y <= yMax; y++) {
    const hit = y < yMax && rowFg[y] >= 3;
    if (hit && bTop < 0) bTop = y;
    else if (!hit && bTop >= 0) {
      const bBot = y - 1;
      const bh = bBot - bTop + 1;
      if (bh >= 5 && bh <= 26) {
        let extBot = bBot;
        const maxExt = Math.min(yMax - 1, bBot + Math.max(1, Math.round(bh * 0.22)));
        while (extBot < maxExt && rowFg[extBot + 1] >= 1) extBot++;
        bands.push({ digitTop: bTop, digitBot: bBot, scanTop: bTop, scanBot: extBot });
      }
      bTop = -1;
    }
  }

  const points: AxisTickPoint[] = [];
  let textMinX = x1;
  let textMaxX = x0;

  for (const b of bands) {
    const read = readNumericBandFromFg(fgAt, x0, x1, b.digitTop, b.digitBot, b.scanTop, b.scanBot, skipCol);
    if (!read || read.minScore < 0.38) continue;
    const price = parseAxisNumber(read.text);
    if (price === null) continue;
    points.push({ y: (b.digitTop + b.digitBot) / 2, price, label: read.text, confidence: Number(read.minScore.toFixed(3)) });
    if (read.minX < textMinX) textMinX = read.minX;
    if (read.maxX > textMaxX) textMaxX = read.maxX;
  }

  const anchor = extractAxisPillAnchor(imgData, w, h, x0, x1, bgLum);
  return { points, anchor, textMinX, textMaxX };
}

export function calibratePriceAxis(
  candidates: AxisTickPoint[],
  axisSide: "right" | "left" | "none" = "right",
  opts: { imageHeight?: number; anchor?: PriceAnchor | null; requireMultiTicks?: boolean } = {}
): PriceCalibration {
  const anchor = opts.anchor ?? null;
  if (candidates.length < 2) {
    return {
      available: false,
      points: candidates,
      anchor,
      slope: null,
      intercept: null,
      axisSide,
      reason: `Need at least 2 reliable price-axis tick labels, found ${candidates.length}.`,
    };
  }

  let bestInliers: AxisTickPoint[] = [];
  let bestMse = Infinity;

  for (let i = 0; i < candidates.length; i++) {
    for (let j = i + 1; j < candidates.length; j++) {
      const dy = candidates[j].y - candidates[i].y;
      const dp = candidates[j].price - candidates[i].price;
      if (Math.abs(dy) < 6 || Math.abs(dp) <= 1e-12) continue;
      const s = dp / dy;
      const b = candidates[i].price - s * candidates[i].y;

      const inliers: AxisTickPoint[] = [];
      let sqErr = 0;
      for (const pt of candidates) {
        const predY = (pt.price - b) / s;
        const errPx = Math.abs(predY - pt.y);
        if (errPx <= 2.5) {
          inliers.push(pt);
          sqErr += errPx * errPx;
        }
      }
      const mse = inliers.length ? sqErr / inliers.length : Infinity;
      if (inliers.length > bestInliers.length || (inliers.length === bestInliers.length && mse < bestMse)) {
        bestInliers = inliers;
        bestMse = mse;
      }
    }
  }

  const minRequired = candidates.length >= 4 ? Math.max(3, Math.ceil(candidates.length * 0.5)) : 2;
  if (bestInliers.length < minRequired) {
    return {
      available: false,
      points: bestInliers,
      anchor,
      slope: null,
      intercept: null,
      axisSide,
      reason: `Axis tick labels did not form a consistent linear price scale (${bestInliers.length}/${candidates.length} consistent).`,
    };
  }

  // Requirement 5: Require multiple consistent axis ticks, not just <= 3 weak or narrow OCR matches
  if (opts.requireMultiTicks) {
    const minY = Math.min(...bestInliers.map((p) => p.y));
    const maxY = Math.max(...bestInliers.map((p) => p.y));
    const ySpan = maxY - minY;
    const minConf = Math.min(...bestInliers.map((p) => p.confidence ?? 1.0));
    const hRef = opts.imageHeight ?? 500;
    if (bestInliers.length < 4) {
      if (bestInliers.length < 3 || ySpan < hRef * 0.30 || minConf < 0.55) {
        return {
          available: false,
          points: bestInliers,
          anchor,
          slope: null,
          intercept: null,
          axisSide,
          reason: `Insufficient reliable multi-tick axis calibration (${bestInliers.length} tick(s), span=${Math.round(ySpan)}px, minConf=${minConf.toFixed(2)}).`,
        };
      }
    }
  }

  // Ordinary least squares refinement on inlier points: price = slope * y + intercept
  let sumY = 0;
  let sumP = 0;
  for (const pt of bestInliers) {
    sumY += pt.y;
    sumP += pt.price;
  }
  const meanY = sumY / bestInliers.length;
  const meanP = sumP / bestInliers.length;
  let num = 0;
  let den = 0;
  for (const pt of bestInliers) {
    const dy = pt.y - meanY;
    num += dy * (pt.price - meanP);
    den += dy * dy;
  }
  if (den <= 1e-9 || Math.abs(num) <= 1e-12) {
    return {
      available: false,
      points: bestInliers,
      anchor,
      slope: null,
      intercept: null,
      axisSide,
      reason: "Extracted price-axis ticks had zero variance in pixel Y or price.",
    };
  }
  const slope = num / den;
  const intercept = meanP - slope * meanY;

  let maxResidualPx = 0;
  for (const pt of bestInliers) {
    const predY = (pt.price - intercept) / slope;
    maxResidualPx = Math.max(maxResidualPx, Math.abs(predY - pt.y));
  }
  if (maxResidualPx > 2.5) {
    return {
      available: false,
      points: bestInliers,
      anchor,
      slope: null,
      intercept: null,
      axisSide,
      maxResidualPx,
      reason: `Linear axis calibration residual too large (${maxResidualPx.toFixed(2)}px).`,
    };
  }

  // Requirements 1, 2, 3, 4: Cross-validate axis fit against independent price anchor
  if (anchor !== null) {
    const sortedPrices = bestInliers.map((p) => p.price).sort((a, b) => a - b);
    const calMin = sortedPrices[0];
    const calMax = sortedPrices[sortedPrices.length - 1];
    const calSpan = Math.max(1e-9, calMax - calMin);
    if (anchor.y !== null) {
      const predAtAnchor = slope * anchor.y + intercept;
      const predY = (anchor.price - intercept) / slope;
      const pxErr = Math.abs(predY - anchor.y);
      const relDiff = Math.abs(predAtAnchor - anchor.price) / Math.max(1e-9, Math.abs(anchor.price));
      const maxPxTol = Math.max(10, (opts.imageHeight ?? 500) * 0.04);
      if (pxErr > maxPxTol || relDiff > 0.03) {
        return {
          available: false,
          points: bestInliers,
          anchor,
          slope: null,
          intercept: null,
          axisSide,
          maxResidualPx: Number(maxResidualPx.toFixed(3)),
          reason: `Axis ticks (${calMin}..${calMax}) contradict reference anchor ${anchor.price} (expected ~${predAtAnchor.toFixed(2)}, ${ (relDiff * 100).toFixed(1) }% mismatch).`,
        };
      }
    } else {
      const margin = Math.max(calSpan * 0.25, Math.abs(anchor.price) * 0.05);
      if (anchor.price < calMin - margin || anchor.price > calMax + margin) {
        return {
          available: false,
          points: bestInliers,
          anchor,
          slope: null,
          intercept: null,
          axisSide,
          maxResidualPx: Number(maxResidualPx.toFixed(3)),
          reason: `Axis ticks (${calMin}..${calMax}) contradict header Close anchor ${anchor.price}.`,
        };
      }
    }
  }

  const sortedInliers = [...bestInliers].sort((a, b) => a.y - b.y);
  return {
    available: true,
    points: sortedInliers,
    anchor,
    slope,
    intercept,
    axisSide,
    maxResidualPx: Number(maxResidualPx.toFixed(3)),
  };
}

function detectVerticalDivider(
  imgData: Uint8ClampedArray | Uint8Array,
  w: number,
  h: number,
  xFrom: number,
  xTo: number
): number | null {
  const y0 = Math.floor(h * 0.08);
  const y1 = Math.floor(h * 0.80);
  let bestX: number | null = null;
  let bestScore = 0;
  for (let x = Math.max(0, xFrom); x <= Math.min(w - 1, xTo); x++) {
    // Compare against adjacent column to detect crisp 1px axis border regardless of theme
    const nx = Math.min(w - 1, x + 2);
    let diffRows = 0;
    let total = 0;
    for (let y = y0; y < y1; y += 3) {
      total++;
      const i = (y * w + x) * 4;
      const j = (y * w + nx) * 4;
      const l1 = 0.299 * imgData[i] + 0.587 * imgData[i + 1] + 0.114 * imgData[i + 2];
      const l2 = 0.299 * imgData[j] + 0.587 * imgData[j + 1] + 0.114 * imgData[j + 2];
      if (Math.abs(l1 - l2) >= 12) diffRows++;
    }
    const frac = total ? diffRows / total : 0;
    if (frac >= 0.60 && frac > bestScore) {
      bestScore = frac;
      bestX = x;
    }
  }
  return bestX;
}

export function extractCandlesFromImageData(
  imgData: Uint8ClampedArray | Uint8Array,
  w: number,
  h: number
): ExtractedChart {
  const divRight = detectVerticalDivider(imgData, w, h, Math.floor(w * 0.85), Math.floor(w * 0.97));
  const rightStarts = Array.from(
    new Set(
      [
        divRight !== null ? divRight + 2 : -1,
        Math.floor(w * 0.89),
        Math.floor(w * 0.92),
        Math.floor(w * 0.94),
        Math.floor(w * 0.86),
      ].filter((v) => v > 0 && v < w - 12)
    )
  );

  let calibration: PriceCalibration = {
    available: false,
    points: [],
    slope: null,
    intercept: null,
    axisSide: "right",
    reason: "Need at least 2 reliable price-axis tick labels, found 0.",
  };
  let candleXStart = Math.floor(w * 0.02);
  let candleXEnd = divRight !== null ? divRight - 2 : Math.floor(w * 0.90);

  for (const rs of rightStarts) {
    const scan = scanAxisStrip(imgData, w, h, rs, w - 2);
    const cal = calibratePriceAxis(scan.points, "right", {
      imageHeight: h,
      anchor: scan.anchor,
      requireMultiTicks: true,
    });
    if (cal.available) {
      if (!calibration.available || cal.points.length > calibration.points.length) {
        calibration = cal;
        candleXEnd = Math.min(Math.floor(w * 0.96), (divRight !== null ? Math.min(divRight - 2, scan.textMinX - 3) : scan.textMinX - 3));
      }
      if (cal.points.length >= 4) break;
    } else if (!calibration.available && (scan.points.length > calibration.points.length || (cal.anchor && !calibration.anchor))) {
      calibration = cal;
    }
  }

  if (!calibration.available && !(calibration.anchor && calibration.points.length >= 2)) {
    const leftEnds = [Math.floor(w * 0.08), Math.floor(w * 0.11), Math.floor(w * 0.14)];
    for (const le of leftEnds) {
      const leftScan = scanAxisStrip(imgData, w, h, 2, le);
      const leftCal = calibratePriceAxis(leftScan.points, "left", {
        imageHeight: h,
        anchor: leftScan.anchor,
        requireMultiTicks: true,
      });
      if (leftCal.available) {
        calibration = leftCal;
        candleXStart = Math.max(candleXStart, leftScan.textMaxX + 3);
        candleXEnd = Math.floor(w * 0.96);
        break;
      }
    }
  }

  const xStart = Math.max(0, candleXStart);
  const xEnd = Math.max(xStart + 10, candleXEnd);
  const yStart = Math.floor(h * 0.11);
  const rawYEnd = Math.floor(h * 0.87);

  // Sample background luminance across plot area
  let bgLumSum = 0;
  let bgSamples = 0;
  for (let y = yStart; y < rawYEnd; y += Math.max(1, Math.floor((rawYEnd - yStart) / 20))) {
    for (let x = xStart; x < xEnd; x += Math.max(1, Math.floor((xEnd - xStart) / 20))) {
      const i = (y * w + x) * 4;
      bgLumSum += 0.299 * imgData[i] + 0.587 * imgData[i + 1] + 0.114 * imgData[i + 2];
      bgSamples++;
    }
  }
  const bgLum = bgSamples ? bgLumSum / bgSamples : 30;
  const darkTheme = bgLum < 128;

  // Detect bottom volume histogram pane: volume bars sit near 86%-94% height above the time axis,
  // separated from the candlestick plot by a sparse horizontal whitespace band around 73%-84%.
  let yEnd = rawYEnd;
  const volScanTop = Math.floor(h * 0.72);
  const volCheckTop = Math.floor(h * 0.86);
  const volCheckBot = Math.floor(h * 0.94);
  let bottomAnchoredCols = 0;
  let sampledCols = 0;
  for (let x = xStart; x < xEnd; x += 2) {
    sampledCols++;
    for (let y = volCheckTop; y < volCheckBot; y += 2) {
      const i = (y * w + x) * 4;
      const r = imgData[i];
      const g = imgData[i + 1];
      const b = imgData[i + 2];
      if ((g > r + 12 && g > 40) || (r > g + 12 && r > 40)) {
        bottomAnchoredCols++;
        break;
      }
    }
  }
  if (sampledCols > 0 && bottomAnchoredCols >= Math.floor(sampledCols * 0.20)) {
    let bestRow = Math.floor(h * 0.80);
    let minCnt = Infinity;
    for (let y = volScanTop; y <= Math.floor(h * 0.84); y++) {
      let cnt = 0;
      for (let x = xStart; x < xEnd; x += 3) {
        const i = (y * w + x) * 4;
        const r = imgData[i];
        const g = imgData[i + 1];
        const b = imgData[i + 2];
        if ((g > r + 14 && g > b + 6 && g > 45) || (r > g + 14 && r > b + 6 && r > 45)) cnt++;
      }
      if (cnt < minCnt) {
        minCnt = cnt;
        bestRow = y;
      }
    }
    yEnd = Math.min(rawYEnd, bestRow);
  }

  type ColInfo = { x: number; cnt: number; top: number; bot: number; isBull: boolean };
  const cols: ColInfo[] = [];

  for (let x = xStart; x < xEnd; x++) {
    type Run = { top: number; bot: number; cnt: number; isBull: boolean };
    const runs: Run[] = [];
    let cur: Run | null = null;

    for (let y = yStart; y < yEnd; y++) {
      const i = (y * w + x) * 4;
      const r = imgData[i];
      const g = imgData[i + 1];
      const b = imgData[i + 2];
      const isBull = g > r + 16 && g > b + 8 && g > 52;
      const isBear = r > g + 16 && r > b + 8 && r > 52;
      if (isBull || isBear) {
        if (cur && y - cur.bot <= 2 && cur.isBull === isBull) {
          cur.bot = y;
          cur.cnt++;
        } else {
          if (cur) runs.push(cur);
          cur = { top: y, bot: y, cnt: 1, isBull };
        }
      }
    }
    if (cur) runs.push(cur);
    if (!runs.length) continue;

    // Pick ONLY the single dominant vertical colored cluster in this column
    // (ignores 1px horizontal dashed price/level lines and disconnected stray labels)
    let best = runs[0];
    for (let k = 1; k < runs.length; k++) {
      if (runs[k].cnt > best.cnt) best = runs[k];
    }
    if (best.cnt >= 2) {
      cols.push({ x, cnt: best.cnt, top: best.top, bot: best.bot, isBull: best.isBull });
    }
  }

  // Group strictly adjacent columns ONLY if polarity matches AND their vertical body spans overlap
  const rawGroups: ColInfo[][] = [];
  for (const col of cols) {
    const last = rawGroups[rawGroups.length - 1];
    if (last) {
      const prev = last[last.length - 1];
      const overlap = Math.min(prev.bot, col.bot) - Math.max(prev.top, col.top);
      if (col.x - prev.x <= 1 && prev.isBull === col.isBull && overlap >= -2) {
        last.push(col);
        continue;
      }
    }
    rawGroups.push([col]);
  }

  // Estimate real candlestick body width from multi-pixel groups (ignoring 1px edge fringes)
  const bodyWidths = rawGroups
    .map((g) => g.length)
    .filter((len) => len >= 2 && len <= 24)
    .sort((a, b) => a - b);
  const medianW = bodyWidths.length ? bodyWidths[Math.floor(bodyWidths.length / 2)] : 4;
  const minW = Math.max(2, Math.floor(medianW * 0.45));
  const pitch = Math.max(3, medianW);

  const groups: ColInfo[][] = [];
  for (const grp of rawGroups) {
    if (grp.length > Math.max(48, w * 0.08)) continue; // skip wide UI / horizontal bars
    if (grp.length < minW) continue;                    // skip 1px anti-aliased noise slivers
    if (grp.length > Math.max(10, pitch * 2.1)) {
      const parts = Math.max(2, Math.round(grp.length / pitch));
      const step = grp.length / parts;
      for (let p = 0; p < parts; p++) {
        const slice = grp.slice(Math.floor(p * step), Math.floor((p + 1) * step));
        if (slice.length >= minW) groups.push(slice);
      }
    } else {
      groups.push(grp);
    }
  }

  const wickHit = (x: number, y: number) => {
    if (x < 0 || x >= w || y < yStart || y >= yEnd) return false;
    const i = (y * w + x) * 4;
    const lum = 0.299 * imgData[i] + 0.587 * imgData[i + 1] + 0.114 * imgData[i + 2];
    return Math.abs(lum - bgLum) > 20;
  };

  const rawCandles: Omit<ExtractedCandle, "index" | "t" | "o" | "h" | "l" | "c">[] = [];
  for (const grp of groups) {
    const sortedTops = grp.map((c) => c.top).sort((a, b) => a - b);
    const sortedBots = grp.map((c) => c.bot).sort((a, b) => a - b);
    // Use median top/bot for body bounds when group spans >= 3px so 1px center wicks do not swallow O/C
    const bodyTop = grp.length >= 3 ? sortedTops[Math.floor(sortedTops.length / 2)] : sortedTops[0];
    const bodyBot = grp.length >= 3 ? sortedBots[Math.floor(sortedBots.length / 2)] : sortedBots[sortedBots.length - 1];
    const cx = Math.round((grp[0].x + grp[grp.length - 1].x) / 2);
    const bullish = grp[0].isBull;

    let yHigh = Math.min(bodyTop, sortedTops[0]);
    let yLow = Math.max(bodyBot, sortedBots[sortedBots.length - 1]);
    for (let y = yHigh - 1; y >= yStart; y--) {
      if (wickHit(cx, y) || wickHit(cx - 1, y) || wickHit(cx + 1, y)) {
        yHigh = y;
      } else if (yHigh - y > 3) {
        break;
      }
    }
    for (let y = yLow + 1; y < yEnd; y++) {
      if (wickHit(cx, y) || wickHit(cx - 1, y) || wickHit(cx + 1, y)) {
        yLow = y;
      } else if (y - yLow > 3) {
        break;
      }
    }

    if (yLow - yHigh < 3) continue;
    const yOpen = bullish ? bodyBot : bodyTop;
    const yClose = bullish ? bodyTop : bodyBot;
    rawCandles.push({ x: cx, yHigh, yLow, yOpen, yClose, bullish });
  }

  const plotTop = rawCandles.length ? Math.min(...rawCandles.map((c) => c.yHigh)) : yStart;
  const plotBottom = rawCandles.length ? Math.max(...rawCandles.map((c) => c.yLow)) : yEnd;

  const roundCalibratedPrice = (val: number): number => {
    const absSpan = Math.abs((calibration.slope ?? 0) * Math.max(10, plotBottom - plotTop));
    if (absSpan > 0 && absSpan < 0.1) return Number(val.toFixed(6));
    if (absSpan > 0 && absSpan < 5) return Number(val.toFixed(4));
    return Number(val.toFixed(2));
  };

  const yToPrice = (y: number) => {
    if (!calibration.available || calibration.slope === null || calibration.intercept === null) return Number.NaN;
    return calibration.slope * y + calibration.intercept;
  };
  const priceToY = (price: number) => {
    if (!calibration.available || calibration.slope === null || calibration.intercept === null || calibration.slope === 0) {
      return Number.NaN;
    }
    return (price - calibration.intercept) / calibration.slope;
  };

  const baseTs = Math.floor(Date.now() / 1000) - rawCandles.length * 300;
  const candles: ExtractedCandle[] = rawCandles.map((c, idx) => {
    if (!calibration.available) {
      return {
        ...c,
        index: idx,
        t: baseTs + idx * 300,
        o: Number.NaN,
        h: Number.NaN,
        l: Number.NaN,
        c: Number.NaN,
      };
    }
    const pHighRaw = yToPrice(c.yHigh);
    const pLowRaw = yToPrice(c.yLow);
    const pBodyA = yToPrice(c.yOpen);
    const pBodyB = yToPrice(c.yClose);
    const pHigh = Math.max(pHighRaw, pLowRaw);
    const pLow = Math.min(pHighRaw, pLowRaw);
    const pOpen = c.bullish ? Math.min(pBodyA, pBodyB) : Math.max(pBodyA, pBodyB);
    const pClose = c.bullish ? Math.max(pBodyA, pBodyB) : Math.min(pBodyA, pBodyB);
    return {
      ...c,
      index: idx,
      t: baseTs + idx * 300,
      o: roundCalibratedPrice(pOpen),
      h: roundCalibratedPrice(pHigh),
      l: roundCalibratedPrice(pLow),
      c: roundCalibratedPrice(pClose),
    };
  });

  const ohlcRange =
    calibration.available && candles.length
      ? {
          minLow: Math.min(...candles.map((c) => c.l)),
          maxHigh: Math.max(...candles.map((c) => c.h)),
        }
      : null;

  const indexToX = (index: number) => {
    if (!candles.length) return w / 2;
    const clamped = Math.max(0, Math.min(candles.length - 1, Math.round(index)));
    return candles[clamped].x;
  };

  void darkTheme;
  return {
    width: w,
    height: h,
    plotTop,
    plotBottom,
    darkTheme,
    candles,
    calibration,
    ohlcRange,
    priceToY,
    yToPrice,
    indexToX,
  };
}

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
  return extractCandlesFromImageData(imgData, w, h);
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

function drawRoundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number
) {
  const rad = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rad, y);
  ctx.lineTo(x + w - rad, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rad);
  ctx.lineTo(x + w, y + h - rad);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rad, y + h);
  ctx.lineTo(x + rad, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rad);
  ctx.lineTo(x, y + rad);
  ctx.quadraticCurveTo(x, y, x + rad, y);
  ctx.closePath();
}

function drawPointerArrow(
  ctx: CanvasRenderingContext2D,
  fromX: number,
  fromY: number,
  toX: number,
  toY: number,
  color: string
) {
  const dx = toX - fromX;
  const dy = toY - fromY;
  const dist = Math.hypot(dx, dy);
  if (dist < 6) return;
  const ux = dx / dist;
  const uy = dy / dist;
  const endX = toX - ux * 4;
  const endY = toY - uy * 4;

  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  ctx.moveTo(fromX, fromY);
  ctx.lineTo(endX, endY);
  ctx.stroke();

  const head = 6.5;
  const angle = Math.atan2(dy, dx);
  ctx.beginPath();
  ctx.moveTo(toX, toY);
  ctx.lineTo(toX - head * Math.cos(angle - Math.PI / 6), toY - head * Math.sin(angle - Math.PI / 6));
  ctx.lineTo(toX - head * Math.cos(angle + Math.PI / 6), toY - head * Math.sin(angle + Math.PI / 6));
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function findNonOverlappingBox(
  bx: number,
  by: number,
  bw: number,
  bh: number,
  canvasW: number,
  canvasH: number,
  placed: Rect[],
  preferUp = true
): { x: number; y: number } {
  const pad = 6;
  const x = Math.max(8, Math.min(canvasW - bw - 8, bx));
  let y = Math.max(36, Math.min(canvasH - bh - 8, by));
  const step = bh + 6;
  for (let i = 0; i < 8; i++) {
    const hit = placed.some(
      (r) => x < r.x + r.w + pad && x + bw + pad > r.x && y < r.y + r.h + pad && y + bh + pad > r.y
    );
    if (!hit) break;
    const dir = i % 2 === 0 ? (preferUp ? -1 : 1) : (preferUp ? 1 : -1);
    const mag = Math.floor(i / 2) + 1;
    const nextY = y + dir * mag * step * 0.45;
    if (nextY >= 34 && nextY + bh <= canvasH - 8) {
      y = nextY;
    } else {
      y = Math.max(34, Math.min(canvasH - bh - 8, y - dir * step * 0.5));
    }
  }
  return { x, y };
}

function drawCalloutPill(
  ctx: CanvasRenderingContext2D,
  title: string,
  subtitle: string | undefined,
  anchorX: number,
  anchorY: number,
  borderColor: string,
  titleColor: string,
  darkTheme: boolean,
  placed: Rect[],
  pointerTo?: { x: number; y: number },
  preferUp = true
) {
  const titleFont = "700 12px system-ui, -apple-system, Segoe UI, sans-serif";
  const subFont = "600 10.5px system-ui, -apple-system, Segoe UI, sans-serif";

  ctx.save();
  ctx.font = titleFont;
  const tw = ctx.measureText(title).width;
  ctx.font = subFont;
  const subText = subtitle ? (subtitle.startsWith("(") ? subtitle : `(${subtitle})`) : "";
  const sw = subText ? ctx.measureText(subText).width : 0;

  const bw = Math.max(tw, sw) + 18;
  const bh = subText ? 36 : 22;
  const pos = findNonOverlappingBox(
    anchorX - bw / 2,
    anchorY - bh / 2,
    bw,
    bh,
    ctx.canvas.width,
    ctx.canvas.height,
    placed,
    preferUp
  );
  placed.push({ x: pos.x, y: pos.y, w: bw, h: bh });

  if (pointerTo) {
    const cx = pos.x + bw / 2;
    const cy = pos.y + bh / 2;
    const fromY = pointerTo.y > cy ? pos.y + bh : pointerTo.y < cy ? pos.y : cy;
    const fromX = Math.max(pos.x + 8, Math.min(pos.x + bw - 8, pointerTo.x * 0.35 + cx * 0.65));
    drawPointerArrow(ctx, fromX, fromY, pointerTo.x, pointerTo.y, borderColor);
  }

  ctx.fillStyle = darkTheme ? "rgba(13, 18, 28, 0.90)" : "rgba(255, 255, 255, 0.94)";
  ctx.strokeStyle = borderColor;
  ctx.lineWidth = 1.5;
  drawRoundRect(ctx, pos.x, pos.y, bw, bh, 7);
  ctx.fill();
  ctx.stroke();

  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = titleFont;
  ctx.fillStyle = titleColor;
  ctx.fillText(title, pos.x + bw / 2, pos.y + (subText ? 12 : bh / 2));

  if (subText) {
    ctx.font = subFont;
    ctx.fillStyle = darkTheme ? "#e2e8f0" : "#334155";
    ctx.fillText(subText, pos.x + bw / 2, pos.y + 26);
  }
  ctx.restore();
}

function drawBadge(
  ctx: CanvasRenderingContext2D,
  text: string,
  cx: number,
  cy: number,
  borderColor: string,
  bgColor: string,
  textColor: string
) {
  ctx.save();
  const sz = 16;
  const x = cx - sz / 2;
  const y = cy - sz / 2;
  ctx.fillStyle = bgColor;
  ctx.strokeStyle = borderColor;
  ctx.lineWidth = 1.5;
  drawRoundRect(ctx, x, y, sz, sz, 4);
  ctx.fill();
  ctx.stroke();
  ctx.font = "800 10.5px system-ui, -apple-system, Segoe UI, sans-serif";
  ctx.fillStyle = textColor;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, cx, cy + 0.5);
  ctx.restore();
}

function fmtPrice(v: number): string {
  const av = Math.abs(v);
  if (av >= 100) return v.toFixed(2);
  if (av >= 1) return v.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  return v.toPrecision(5);
}

export function renderAnnotatedChart(
  img: HTMLImageElement,
  extracted: ExtractedChart,
  analysis: ChartAnalysis
): string {
  const { width: w, height: h, darkTheme, priceToY, indexToX, candles } = extracted;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context unavailable");

  ctx.drawImage(img, 0, 0, w, h);
  if (!extracted.calibration.available) {
    ctx.save();
    ctx.fillStyle = "rgba(185, 28, 28, 0.92)";
    drawRoundRect(ctx, 16, 12, Math.min(w - 32, 520), 28, 6);
    ctx.fill();
    ctx.font = "700 12px system-ui, -apple-system, Segoe UI, sans-serif";
    ctx.fillStyle = "#ffffff";
    ctx.textBaseline = "middle";
    ctx.fillText("PRICE CALIBRATION UNAVAILABLE — TRADE LEVELS REFUSED", 28, 26);
    ctx.restore();
    return canvas.toDataURL("image/png");
  }
  const placed: Rect[] = [];
  const ink = darkTheme ? "#f8fafc" : "#0f172a";
  const halo = darkTheme ? "rgba(9, 9, 11, 0.88)" : "rgba(255, 255, 255, 0.92)";
  const candleSpan = candles.length > 1 ? Math.abs(candles[1].x - candles[0].x) : 12;
  const halfBody = Math.max(4, candleSpan * 0.45);

  // Reserve top bar + optional side cards so callout pills avoid overlapping them
  placed.push({ x: 6, y: 4, w: w - 12, h: 30 });
  const showOverlayCards = Boolean(analysis.v6_flow) && w >= 720 && h >= 380;
  if (showOverlayCards) {
    placed.push({ x: 14, y: 42, w: Math.min(248, w * 0.28), h: 128 });
    if (analysis.trades && analysis.trades.length > 0) {
      placed.push({ x: w - Math.min(220, w * 0.25) - 18, y: 112, w: Math.min(220, w * 0.25), h: 175 });
    }
  }

  // 1. Zones (PATTERN highlighted dashed purple box, or FVG / OB boxes)
  for (const z of analysis.zones || []) {
    const x1 = indexToX(z.start) - halfBody;
    const x2 = Math.max(x1 + halfBody * 2 + 4, indexToX(z.end) + halfBody);
    const y1 = priceToY(z.high) - 4;
    const y2 = priceToY(z.low) + 4;
    const isBuy = z.side === "BUY";

    if (z.kind === "PATTERN") {
      ctx.save();
      ctx.fillStyle = "rgba(168, 85, 247, 0.12)";
      ctx.strokeStyle = "#a855f7";
      ctx.lineWidth = 1.6;
      ctx.setLineDash([5, 4]);
      drawRoundRect(ctx, x1, y1, x2 - x1, Math.max(12, y2 - y1), 4);
      ctx.fill();
      ctx.stroke();
      ctx.restore();

      const cx = (x1 + x2) / 2;
      drawCalloutPill(
        ctx,
        z.label,
        z.sublabel || "Pattern",
        cx,
        isBuy ? y2 + 34 : y1 - 34,
        "#a855f7",
        "#d8b4fe",
        darkTheme,
        placed,
        { x: cx, y: isBuy ? y2 : y1 },
        !isBuy
      );
    } else {
      ctx.save();
      ctx.fillStyle = isBuy ? "rgba(34, 197, 94, 0.16)" : "rgba(239, 68, 68, 0.16)";
      ctx.strokeStyle = isBuy ? "#16a34a" : "#dc2626";
      ctx.lineWidth = 1.5;
      ctx.fillRect(x1, y1, x2 - x1, Math.max(6, y2 - y1));
      ctx.strokeRect(x1, y1, x2 - x1, Math.max(6, y2 - y1));
      ctx.restore();
      drawLabel(ctx, z.label, (x1 + x2) / 2, y1 - 6, isBuy ? "#22c55e" : "#ef4444", halo, placed, 11);
    }
  }

  // 2. Trade Position Boxes (V6 Entry C+1, Structural SL, Opposing Liquidity Pool TP + Outcome Arrow)
  for (const tr of analysis.trades || []) {
    const xStart = indexToX(tr.entry_index);
    const defaultEnd = Math.min(candles.length - 1, tr.entry_index + 18);
    const endIdx = typeof tr.exit_index === "number" ? Math.max(tr.entry_index + 2, tr.exit_index) : defaultEnd;
    const xEnd = Math.min(w - 24, Math.max(xStart + 92, indexToX(endIdx)));
    const yEntry = priceToY(tr.entry);
    const ySl = priceToY(tr.sl);
    const yTp = priceToY(tr.tp);
    const isBuy = tr.side === "BUY";

    // Reward (green) & Risk (red) zones
    ctx.fillStyle = "rgba(34, 197, 94, 0.16)";
    ctx.fillRect(xStart, Math.min(yEntry, yTp), xEnd - xStart, Math.abs(yTp - yEntry));
    ctx.fillStyle = "rgba(239, 68, 68, 0.16)";
    ctx.fillRect(xStart, Math.min(yEntry, ySl), xEnd - xStart, Math.abs(ySl - yEntry));

    // TP Liquidity Pool line extending across from origin pool
    const tpLineStart =
      typeof tr.tp_pool_index === "number" && tr.tp_pool_index >= 0
        ? Math.min(xStart - 20, indexToX(tr.tp_pool_index))
        : Math.max(16, xStart - 120);
    ctx.save();
    ctx.strokeStyle = "#ef4444";
    ctx.lineWidth = 1.4;
    ctx.setLineDash([6, 5]);
    ctx.beginPath();
    ctx.moveTo(Math.max(12, tpLineStart), yTp);
    ctx.lineTo(w - 14, yTp);
    ctx.stroke();
    ctx.restore();

    if (tr.tp_label) {
      drawLabel(
        ctx,
        tr.tp_label,
        Math.max(120, xStart - 30),
        isBuy ? yTp - 10 : yTp + 16,
        "#fca5a5",
        halo,
        placed,
        10
      );
    }

    // Entry solid line & SL dashed red line across box
    ctx.save();
    ctx.strokeStyle = isBuy ? "#22c55e" : "#f87171";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(xStart, yEntry);
    ctx.lineTo(xEnd, yEntry);
    ctx.stroke();

    ctx.strokeStyle = "#ef4444";
    ctx.lineWidth = 1.8;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(xStart, ySl);
    ctx.lineTo(xEnd, ySl);
    ctx.stroke();
    ctx.restore();

    // Entry circle highlight
    ctx.save();
    ctx.fillStyle = isBuy ? "#22c55e" : "#ef4444";
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.arc(xStart, yEntry, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    // Diagonal arrow inside position box + Target Hit / Stop Hit ring
    if (tr.outcome === "TARGET HIT" || tr.outcome === "STOPPED OUT") {
      const hitTp = tr.outcome === "TARGET HIT";
      const hitY = hitTp ? yTp : ySl;
      const ringColor = hitTp ? "#22c55e" : "#ef4444";
      ctx.save();
      ctx.strokeStyle = ringColor;
      ctx.fillStyle = hitTp ? "rgba(34, 197, 94, 0.24)" : "rgba(239, 68, 68, 0.24)";
      ctx.lineWidth = 2.2;
      ctx.beginPath();
      ctx.arc(xEnd, hitY, 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.restore();
      if (hitTp) {
        drawPointerArrow(
          ctx,
          xStart + (xEnd - xStart) * 0.22,
          yEntry + (yTp - yEntry) * 0.22,
          xEnd - 12,
          yTp + (isBuy ? 14 : -14),
          "#22c55e"
        );
      }
    }

    // Callout pills for TP, ENTRY, SL
    drawCalloutPill(
      ctx,
      "TP (Liquidity Pool)",
      fmtPrice(tr.tp),
      (xStart + xEnd) / 2,
      isBuy ? yTp - 30 : yTp + 30,
      "#22c55e",
      "#4ade80",
      darkTheme,
      placed,
      { x: xEnd, y: yTp },
      isBuy
    );
    drawCalloutPill(
      ctx,
      `ENTRY (${tr.entry_mode === "Confirm Close" ? "Confirm" : "C+1"})`,
      fmtPrice(tr.entry),
      xStart + 58,
      isBuy ? yEntry - 26 : yEntry + 26,
      isBuy ? "#22c55e" : "#f59e0b",
      isBuy ? "#4ade80" : "#fbbf24",
      darkTheme,
      placed,
      { x: xStart, y: yEntry },
      isBuy
    );
    drawCalloutPill(
      ctx,
      "SL (Structural)",
      fmtPrice(tr.sl),
      xStart + 62,
      isBuy ? ySl + 26 : ySl - 26,
      "#ef4444",
      "#f87171",
      darkTheme,
      placed,
      { x: xStart, y: ySl },
      !isBuy
    );
  }

  // 3. Structure & Liquidity Dashed Lines (CHoCH, BOS, SWEEP)
  for (const ln of analysis.lines || []) {
    const x1 = indexToX(ln.start);
    const x2 = Math.max(x1 + 26, indexToX(ln.end));
    const y = priceToY(ln.price);
    const isBuy = ln.side === "BUY";
    const lineColor =
      ln.kind === "CHoCH"
        ? "#f59e0b"
        : ln.kind === "BOS"
          ? (isBuy ? "#22c55e" : "#ef4444")
          : "#a855f7";

    ctx.save();
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = ln.kind === "SWEEP" ? 2.2 : 2.5;
    ctx.setLineDash([6, 5]);
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(x1, y);
    ctx.lineTo(x2, y);
    ctx.stroke();
    ctx.restore();

    if (ln.kind === "CHoCH" || ln.kind === "BOS") {
      const midX = (x1 + x2) / 2;
      drawCalloutPill(
        ctx,
        ln.label,
        ln.sublabel,
        midX - 24,
        isBuy ? y - 56 : y + 56,
        lineColor,
        lineColor,
        darkTheme,
        placed,
        { x: (x1 + x2 * 2) / 3, y },
        isBuy
      );
    } else if (ln.kind !== "SWEEP") {
      const midX = (x1 + x2) / 2;
      drawLabel(ctx, ln.label.toUpperCase(), midX, isBuy ? y - 10 : y + 18, lineColor, halo, placed, 12);
    }
  }

  // 4. Compact Structural Swing Tags (LL, LH, HL, HH / SH, SL)
  for (const sw of analysis.swings || []) {
    const x = indexToX(sw.index);
    const y = priceToY(sw.price);
    const isHigh = sw.kind === "HH" || sw.kind === "LH" || sw.kind === "SH";
    drawLabel(ctx, sw.kind, x, isHigh ? y - 10 : y + 18, ink, halo, placed, 11);
  }

  // 5. Setup Markers (Liquidity Sweep ring + pill, 1/2/3 confirm badges, Confirm box + pill)
  for (const mk of analysis.markers || []) {
    const x = indexToX(mk.index);
    const y = priceToY(mk.price);
    const isBuy = mk.side === "BUY";

    if (mk.kind === "CONFIRM_STEP") {
      drawBadge(ctx, mk.label, x, isBuy ? y + 14 : y - 14, "#3b82f6", "rgba(15, 23, 42, 0.92)", "#93c5fd");
      continue;
    }

    if (mk.kind === "SWEEP") {
      ctx.save();
      ctx.strokeStyle = "#38bdf8";
      ctx.fillStyle = "rgba(168, 85, 247, 0.22)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.restore();

      drawCalloutPill(
        ctx,
        mk.label || "Liquidity Sweep",
        mk.sublabel || (isBuy ? "Took Out Lows" : "Took Out Highs"),
        x - 62,
        isBuy ? y + 36 : y - 36,
        "#e2e8f0",
        "#f8fafc",
        darkTheme,
        placed,
        { x, y },
        !isBuy
      );
      continue;
    }

    if (mk.kind === "CONFIRM") {
      const cBar = candles[mk.index];
      const yTop = cBar ? priceToY(cBar.h) - 6 : y - 24;
      const yBot = cBar ? priceToY(cBar.l) + 6 : y + 24;
      ctx.save();
      ctx.strokeStyle = "#3b82f6";
      ctx.fillStyle = "rgba(59, 130, 246, 0.14)";
      ctx.lineWidth = 1.6;
      drawRoundRect(ctx, x - halfBody - 2, yTop, halfBody * 2 + 4, Math.max(18, yBot - yTop), 4);
      ctx.fill();
      ctx.stroke();
      ctx.restore();

      drawCalloutPill(
        ctx,
        mk.label || "3-Candle Confirm",
        mk.sublabel || "Closes Beyond BOS",
        x + 48,
        isBuy ? yBot + 42 : yTop - 42,
        "#3b82f6",
        "#60a5fa",
        darkTheme,
        placed,
        { x, y: isBuy ? yBot : yTop },
        !isBuy
      );
      continue;
    }

    if (mk.kind === "PATTERN" && (analysis.zones || []).some((z) => z.kind === "PATTERN")) {
      // Pattern box already renders its own callout pill cleanly
      continue;
    }

    const color = mk.kind === "ENTRY" ? "#22c55e" : "#f59e0b";
    drawCalloutPill(
      ctx,
      mk.label,
      mk.sublabel,
      x,
      isBuy ? y + 32 : y - 32,
      color,
      color,
      darkTheme,
      placed,
      { x, y },
      !isBuy
    );
  }

  // 6. Top V6 Pipeline Header & Floating Cards (when V6 metadata is available)
  const primaryTr = analysis.trades && analysis.trades[0];
  if (analysis.v6_flow) {
    ctx.save();
    const sideBadgeText = primaryTr
      ? `V6 SETUP — ${primaryTr.side === "BUY" ? "LONG" : "SHORT"}`
      : `V6 SCANNER — ${analysis.summary.bias}`;
    const badgeColor =
      primaryTr?.side === "BUY" ? "#059669" : primaryTr?.side === "SELL" ? "#dc2626" : "#2563eb";
    ctx.font = "800 11px system-ui, -apple-system, Segoe UI, sans-serif";
    const sbw = ctx.measureText(sideBadgeText).width + 18;
    const sbx = 16;
    ctx.fillStyle = badgeColor;
    drawRoundRect(ctx, sbx, 8, sbw, 22, 5);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    ctx.fillText(sideBadgeText, sbx + sbw / 2, 19);

    if (w >= 620) {
      const flowText = `Flow: ${analysis.v6_flow.flow_text}`;
      ctx.font = "600 10.5px system-ui, -apple-system, Segoe UI, sans-serif";
      const ftw = Math.min(w - sbx - sbw - 30, ctx.measureText(flowText).width + 18);
      const fx = sbx + sbw + 10;
      ctx.fillStyle = darkTheme ? "rgba(15, 23, 42, 0.85)" : "rgba(241, 245, 249, 0.92)";
      ctx.strokeStyle = "rgba(99, 102, 241, 0.65)";
      ctx.lineWidth = 1;
      drawRoundRect(ctx, fx, 8, ftw, 22, 5);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = darkTheme ? "#e2e8f0" : "#1e293b";
      ctx.textAlign = "left";
      ctx.fillText(flowText, fx + 9, 19, ftw - 18);
    }
    ctx.restore();

    if (showOverlayCards) {
      // Top-left: V6 Module Flow Card
      ctx.save();
      const cw = Math.min(248, w * 0.28);
      const ch = 26 + analysis.v6_flow.modules.length * 19 + 8;
      ctx.fillStyle = "rgba(12, 17, 27, 0.86)";
      ctx.strokeStyle = "rgba(148, 163, 184, 0.35)";
      ctx.lineWidth = 1;
      drawRoundRect(ctx, 14, 42, cw, ch, 8);
      ctx.fill();
      ctx.stroke();

      ctx.font = "700 11.5px system-ui, -apple-system, Segoe UI, sans-serif";
      ctx.fillStyle = "#f8fafc";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText("V6 Module Flow (This Trade)", 24, 56);

      ctx.font = "600 10.5px system-ui, -apple-system, Segoe UI, sans-serif";
      analysis.v6_flow.modules.forEach((m, idx) => {
        const ry = 76 + idx * 19;
        ctx.fillStyle = "#e2e8f0";
        ctx.fillText(`${m.key}. ${m.label}`, 24, ry, cw - 34);
        ctx.fillStyle = m.passed ? "#4ade80" : "#94a3b8";
        ctx.textAlign = "right";
        ctx.fillText(m.passed ? "✓" : "○", 14 + cw - 10, ry);
        ctx.textAlign = "left";
      });
      ctx.restore();

      // Right-side: Trade Result (V6 Rules) Card
      if (primaryTr) {
        ctx.save();
        const rw = Math.min(212, w * 0.24);
        const rh = 172;
        const rx = w - rw - 16;
        const ry = 104;
        ctx.fillStyle = "rgba(12, 17, 27, 0.88)";
        ctx.strokeStyle = "rgba(148, 163, 184, 0.38)";
        ctx.lineWidth = 1;
        drawRoundRect(ctx, rx, ry, rw, rh, 8);
        ctx.fill();
        ctx.stroke();

        ctx.font = "700 11.5px system-ui, -apple-system, Segoe UI, sans-serif";
        ctx.fillStyle = "#f8fafc";
        ctx.textBaseline = "middle";
        ctx.textAlign = "left";
        ctx.fillText("Trade Result (V6 Rules)", rx + 12, ry + 16);

        const resR = primaryTr.realized_r ?? primaryTr.rr;
        const resSign = resR >= 0 ? "+" : "";
        const kvRows: [string, string, string][] = [
          ["Side:", primaryTr.side === "BUY" ? "LONG" : "SHORT", primaryTr.side === "BUY" ? "#4ade80" : "#f87171"],
          ["Entry:", fmtPrice(primaryTr.entry), "#f8fafc"],
          ["Stop Loss:", fmtPrice(primaryTr.sl), "#f8fafc"],
          ["Target:", fmtPrice(primaryTr.tp), "#f8fafc"],
          ["Risk (R):", fmtPrice(primaryTr.risk_pts ?? Math.abs(primaryTr.entry - primaryTr.sl)), "#f8fafc"],
          ["Reward:", fmtPrice(primaryTr.reward_pts ?? Math.abs(primaryTr.tp - primaryTr.entry)), "#f8fafc"],
          ["R:R:", `${primaryTr.rr}`, "#f8fafc"],
          ["Result:", `${resSign}${resR}R`, resR >= 0 ? "#4ade80" : "#f87171"],
        ];
        kvRows.forEach(([k, v, vc], i) => {
          const ly = ry + 36 + i * 17;
          ctx.font = i === kvRows.length - 1 ? "700 11px system-ui, sans-serif" : "500 10.5px system-ui, sans-serif";
          ctx.fillStyle = "#94a3b8";
          ctx.textAlign = "left";
          ctx.fillText(k, rx + 12, ly);
          ctx.fillStyle = vc;
          ctx.textAlign = "right";
          ctx.fillText(v, rx + rw - 12, ly);
        });
        ctx.restore();
      }
    }
  } else {
    const banner = `${analysis.strategy_name} · ${analysis.candle_count} candles · Bias: ${analysis.summary.bias} · ${analysis.summary.setups_found} setup(s)`;
    drawLabel(ctx, banner, Math.min(w / 2, 220), 19, ink, halo, placed, 11);
  }

  return canvas.toDataURL("image/png");
}
