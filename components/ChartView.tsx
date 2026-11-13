"use client";

import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type ISeriesApi, type ISeriesPrimitive, type SeriesAttachedParameter, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import type { CanvasRenderingTarget2D } from "fancy-canvas";
import { getJSON } from "@/lib/api";

type ChartPos = {
  key: string; market: string; symbol: string; side?: string; qty?: number; entry: number; stop: number;
  risk_stop?: number; target?: number; entry_time?: string; exit_time?: string; exit?: number; reason?: string;
  setup_name?: string; liquidity?: string; entry_reason?: string; signal_at?: string; trailing?: boolean;
  breakeven?: boolean; locked?: boolean; trail_k?: number; last?: number;
};
type ChartDoc = {
  chart: string; tf: string; open: boolean; box: boolean; note?: string | null;
  candles: [number, number, number, number, number][]; links: { name: string; url: string }[]; pos: ChartPos;
};

const IST = 19800; // the chart's clock: IST, like the rest of the dashboard
const toT = (iso?: string | number | null) =>
  iso === undefined || iso === null ? null : ((typeof iso === "number" ? iso : Math.floor(new Date(iso).getTime() / 1000)) + IST) as UTCTimestamp;

function cssVar(name: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return /^#[0-9a-f]{6}$/i.test(v) ? v : fallback;
}
function rgba(hex: string, a: number) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/** The long / short position box: the reward zone (entry -> target) and the risk zone (entry -> the original stop),
 *  from the entry candle to the exit (or the last candle while open). Drawn under the candles. */
class PositionBox implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<"Candlestick"> | null = null;
  constructor(private spec: { t1: Time; t2: Time; entry: number; target?: number; risk: number; good: string; bad: string }) {}
  attached(p: SeriesAttachedParameter<Time>) {
    this.chart = p.chart as IChartApi;
    this.series = p.series as ISeriesApi<"Candlestick">;
  }
  detached() { this.chart = null; this.series = null; }
  paneViews() {
    return [{
      zOrder: () => "bottom" as const,
      renderer: () => ({
        draw: (target: CanvasRenderingTarget2D) => {
          const { chart, series, spec } = this;
          if (!chart || !series) return;
          const ts = chart.timeScale();
          const x1 = ts.timeToCoordinate(spec.t1), x2 = ts.timeToCoordinate(spec.t2);
          const ye = series.priceToCoordinate(spec.entry), yr = series.priceToCoordinate(spec.risk);
          const yt = spec.target !== undefined ? series.priceToCoordinate(spec.target) : null;
          if (x1 === null || x2 === null || ye === null || yr === null) return;
          target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
            const left = Math.min(x1, x2) * hr, w = Math.max(Math.abs(x2 - x1) * hr, 6 * hr);
            const zone = (ya: number, yb: number, fill: string, edge: string) => {
              const top = Math.min(ya, yb) * vr, h = Math.abs(yb - ya) * vr;
              ctx.fillStyle = fill;
              ctx.fillRect(left, top, w, h);
              ctx.strokeStyle = edge;
              ctx.lineWidth = Math.max(1, hr);
              ctx.strokeRect(left, top, w, h);
            };
            if (yt !== null) zone(ye, yt, rgba(spec.good, 0.18), rgba(spec.good, 0.6));
            zone(ye, yr, rgba(spec.bad, 0.18), rgba(spec.bad, 0.6));
          });
        },
      }),
    }];
  }
}

export default function ChartView({ posKey, entryTime, onClose }: { posKey: string; entryTime?: string; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const dlg = useRef<HTMLDialogElement>(null);
  const [doc, setDoc] = useState<ChartDoc | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    dlg.current?.showModal();
    const q = new URLSearchParams({ key: posKey, ...(entryTime ? { entry_time: entryTime } : {}) });
    getJSON<ChartDoc>(`/api/py/chart/position?${q}`).then(setDoc).catch((e) => setErr(String(e?.message ?? e)));
  }, [posKey, entryTime]);

  useEffect(() => {
    if (!doc || !box.current || !doc.candles.length) return;
    const good = cssVar("--good", "#6fcf97"), bad = cssVar("--bad", "#f0807a");
    const ink = cssVar("--ink", "#f1ebe1"), muted = cssVar("--muted", "#a89e90"), line = cssVar("--line", "#3a332c");
    const accent = cssVar("--accent", "#f0b541");
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: muted, fontFamily: "IBM Plex Mono, ui-monospace, monospace" },
      grid: { vertLines: { color: rgba(line, 0.5) }, horzLines: { color: rgba(line, 0.5) } },
      rightPriceScale: { borderColor: line },
      timeScale: { borderColor: line, timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    const s = chart.addSeries(CandlestickSeries, {
      upColor: good, downColor: bad, borderUpColor: good, borderDownColor: bad, wickUpColor: good, wickDownColor: bad,
    });
    const data = doc.candles.map(([t, o, h, l, c]) => ({ time: toT(t)!, open: o, high: h, low: l, close: c }));
    s.setData(data);
    const p = doc.pos;
    const times = data.map((d) => d.time as number);
    const snap = (t: number | null) => {           // the candle that contains t
      if (t === null) return null;
      let best: number | null = null;
      for (const x of times) if (x <= t) best = x; else break;
      return (best ?? times[0]) as UTCTimestamp;
    };
    const tEntry = snap(toT(p.entry_time));
    const tExit = p.exit_time ? snap(toT(p.exit_time)) : (times[times.length - 1] as UTCTimestamp);
    const risk = p.risk_stop ?? p.stop;
    if (doc.box && tEntry !== null && tExit !== null) {
      s.attachPrimitive(new PositionBox({ t1: tEntry, t2: tExit, entry: p.entry, target: p.trail_k ? undefined : p.target, risk, good, bad }));
      s.createPriceLine({ price: p.entry, color: ink, lineWidth: 1, lineStyle: LineStyle.Solid, title: "entry" });
      if (p.target !== undefined && !p.trail_k) s.createPriceLine({ price: p.target, color: good, lineWidth: 1, lineStyle: LineStyle.Dashed, title: "target" });
      s.createPriceLine({ price: risk, color: bad, lineWidth: 1, lineStyle: LineStyle.Dashed, title: "stop" });
      if (Math.abs(p.stop - risk) > 1e-9) {
        s.createPriceLine({ price: p.stop, color: accent, lineWidth: 2, lineStyle: LineStyle.Solid,
                            title: p.trailing ? "trailing stop" : p.locked ? "locked stop" : "stop now" });
      }
    }
    const short = p.side === "short";
    const marks: SeriesMarker<Time>[] = [];
    const tSig = snap(toT(p.signal_at));
    if (tSig !== null) marks.push({ time: tSig, position: short ? "aboveBar" : "belowBar", color: accent, shape: "circle" });
    if (tEntry !== null) marks.push({ time: tEntry, position: short ? "aboveBar" : "belowBar", color: ink, shape: short ? "arrowDown" : "arrowUp", text: short ? "short" : "buy" });
    if (p.exit_time && tExit !== null) marks.push({ time: tExit, position: short ? "belowBar" : "aboveBar", color: muted, shape: "square", text: `exit ${p.reason ?? ""}`.trim() });
    marks.sort((a, b) => (a.time as number) - (b.time as number));
    createSeriesMarkers(s, marks);
    if (tEntry !== null) {   // open on the trade: a little before the entry to the end
      const before = (box.current?.clientWidth ?? 800) < 600 ? 15 : 60;   // fewer candles before the entry on a phone
      const i = Math.max(0, times.indexOf(tEntry as number) - before);
      chart.timeScale().setVisibleLogicalRange({ from: i, to: times.length + 5 });
    }
    return () => chart.remove();
  }, [doc]);

  const p = doc?.pos;
  const r = p && p.risk_stop !== undefined ? Math.abs(p.entry - p.risk_stop) : null;
  const rr = p && r && p.target !== undefined ? Math.abs(p.target - p.entry) / r : null;
  return (
    <dialog ref={dlg} className="chart-dialog" onClose={onClose} aria-labelledby="chart-title">
      <div className="chart-head">
        <div>
          <h2 id="chart-title" style={{ margin: 0, fontSize: 16 }}>{posKey}{p ? ` · ${p.side ?? "long"}` : ""}</h2>
          {p && (
            <p className="small muted" style={{ margin: "2px 0 0" }}>
              {p.setup_name ?? "trade"} · entry {p.entry} · stop {p.risk_stop ?? p.stop}{p.target !== undefined && !p.trail_k ? ` · target ${p.target}` : ""}
              {rr ? ` · ${rr.toFixed(1)}R` : ""} · {doc?.tf} candles, IST{doc && !doc.open ? " · closed" : ""}
              {p.signal_at ? <> · <span style={{ color: "var(--accent)" }} aria-hidden="true">●</span> signal candle</> : null}
            </p>
          )}
        </div>
        <button className="btn small-btn" onClick={() => dlg.current?.close()} aria-label="Close chart">Close</button>
      </div>
      {err && <div className="notice bad">Chart not loaded: {err}</div>}
      {!doc && !err && <p className="muted small">Loading candles…</p>}
      {doc && !doc.candles.length && <div className="notice bad">No candles came back for {doc.chart}.</div>}
      <div ref={box} className="chart-box" />
      {doc?.note && <p className="small muted" style={{ margin: "6px 0 0" }}>{doc.note}</p>}
      {p?.liquidity && <p className="small muted" style={{ margin: "4px 0 0" }}>Why: {p.liquidity}{p.entry_reason ? ` · ${p.entry_reason}` : ""}</p>}
      {!!doc?.links.length && (
        <div className="actions" style={{ marginTop: 8 }}>
          <span className="small muted">Open the symbol on (no drawings there):</span>
          {doc.links.map((l) => (
            <a key={l.url} className="btn small-btn" href={l.url} target="_blank" rel="noopener noreferrer">{l.name}</a>
          ))}
        </div>
      )}
    </dialog>
  );
}
