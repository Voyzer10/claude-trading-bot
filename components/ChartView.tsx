"use client";

import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type ISeriesApi, type ISeriesPrimitive, type SeriesAttachedParameter, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import type { CanvasRenderingTarget2D } from "fancy-canvas";
import { getJSON } from "@/lib/api";

type ChartPos = {
  key: string; market: string; symbol: string; side?: string; qty?: number; entry: number | null; stop: number | null;
  risk_stop?: number; target?: number; entry_time?: string; exit_time?: string; exit?: number; reason?: string;
  setup_name?: string; liquidity?: string; entry_reason?: string; signal_at?: string; trailing?: boolean;
  breakeven?: boolean; locked?: boolean; trail_k?: number; last?: number; r?: number; pnl?: number;
  rr?: number | null; planned?: boolean;
};
type Marker = { t: number; kind: string; text: string };
type Verdict = { tone: "good" | "bad" | "flat"; title: string; lines: string[] };
/** What to chart: a paper position (open or closed) or a scanner candidate from the decisions log. */
export type ChartSource = { kind: "position"; key: string; entryTime?: string } | { kind: "decision"; time: string; symbol: string };
type ChartDoc = {
  chart: string; tf: string; open: boolean; box: boolean; note?: string | null;
  candles: [number, number, number, number, number][]; links: { name: string; url: string }[]; pos: ChartPos;
  markers?: Marker[]; verdict?: Verdict;
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

export default function ChartView({ src, onClose }: { src: ChartSource; onClose: () => void }) {
  const title = src.kind === "position" ? src.key : src.symbol;
  const box = useRef<HTMLDivElement>(null);
  const dlg = useRef<HTMLDialogElement>(null);
  const [doc, setDoc] = useState<ChartDoc | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    dlg.current?.showModal();
    const url = src.kind === "position"
      ? `/api/py/chart/position?${new URLSearchParams({ key: src.key, ...(src.entryTime ? { entry_time: src.entryTime } : {}) })}`
      : `/api/py/chart/decision?${new URLSearchParams({ time: src.time, symbol: src.symbol })}`;
    getJSON<ChartDoc>(url).then(setDoc).catch((e) => setErr(String(e?.message ?? e)));
  }, [src]);

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
    const p = doc.pos;
    // keep the whole box (entry, stop, target) on screen, not only the candles
    const levels = [p.entry, p.risk_stop ?? p.stop, p.stop, p.trail_k ? null : p.target].filter((x): x is number => typeof x === "number");
    s.applyOptions({
      autoscaleInfoProvider: (orig: () => { priceRange: { minValue: number; maxValue: number } | null } | null) => {
        const r = orig();
        if (!r || !r.priceRange || !doc.box || !levels.length) return r;
        return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, ...levels), maxValue: Math.max(r.priceRange.maxValue, ...levels) } };
      },
    });
    s.setData(data);
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
    const planned = p.planned ? "planned " : "";
    if (doc.box && tEntry !== null && tExit !== null && p.entry !== null && risk !== null) {
      s.attachPrimitive(new PositionBox({ t1: tEntry, t2: tExit, entry: p.entry, target: p.trail_k ? undefined : (p.target ?? undefined), risk, good, bad }));
      s.createPriceLine({ price: p.entry, color: ink, lineWidth: 1, lineStyle: LineStyle.Solid, title: planned + "entry" });
      if (p.target != null && !p.trail_k) s.createPriceLine({ price: p.target, color: good, lineWidth: 1, lineStyle: LineStyle.Dashed, title: planned + "target" });
      s.createPriceLine({ price: risk, color: bad, lineWidth: 1, lineStyle: LineStyle.Dashed, title: planned + "stop" });
      if (p.stop !== null && Math.abs(p.stop - risk) > 1e-9) {
        s.createPriceLine({ price: p.stop, color: accent, lineWidth: 2, lineStyle: LineStyle.Solid,
                            title: p.trailing ? "trailing stop" : p.locked ? "locked stop" : "stop now" });
      }
      if (p.exit != null) s.createPriceLine({ price: p.exit, color: muted, lineWidth: 1, lineStyle: LineStyle.Dotted, title: "exit" });
    }
    const short = p.side === "short";
    // server markers: BOS, sweep, signal, entry / skip, Trade Manager actions, exit (or what a skipped trade would hit)
    type MStyle = { color: string; shape: "circle" | "square" | "arrowUp" | "arrowDown"; position: "aboveBar" | "belowBar" };
    const style: Record<string, MStyle> = {
      bos: { color: muted, shape: "square", position: short ? "belowBar" : "aboveBar" },
      sweep: { color: accent, shape: short ? "arrowUp" : "arrowDown", position: short ? "aboveBar" : "belowBar" },
      signal: { color: accent, shape: "circle", position: short ? "aboveBar" : "belowBar" },
      entry: { color: ink, shape: short ? "arrowDown" : "arrowUp", position: short ? "aboveBar" : "belowBar" },
      skip: { color: bad, shape: "square", position: short ? "belowBar" : "aboveBar" },   // the other side: no pile-up
      tm: { color: accent, shape: "circle", position: short ? "belowBar" : "aboveBar" },
      win: { color: good, shape: "square", position: short ? "belowBar" : "aboveBar" },
      loss: { color: bad, shape: "square", position: short ? "aboveBar" : "belowBar" },
      exit: { color: muted, shape: "square", position: short ? "belowBar" : "aboveBar" },
      info: { color: muted, shape: "circle", position: "aboveBar" },
    };
    const marks: SeriesMarker<Time>[] = (doc.markers ?? [])
      .map((m) => ({ m, t: snap(toT(m.t)) }))
      .filter((x) => x.t !== null)
      .map(({ m, t }) => ({ time: t as Time, text: m.text, ...(style[m.kind] ?? style.info) }));
    marks.sort((a, b) => (a.time as number) - (b.time as number));
    // labels on neighbouring candles on the same side overlap: join them into the first one ("sweep · doji")
    const lastLabel: Record<string, SeriesMarker<Time> | undefined> = {};
    for (const mk of marks) {
      const prev = lastLabel[mk.position];
      if (prev && mk.text && (mk.time as number) - (prev.time as number) <= 2 * 300) {
        prev.text = `${prev.text} · ${mk.text}`;
        mk.text = "";
      } else if (mk.text) {
        lastLabel[mk.position] = mk;
      }
    }
    createSeriesMarkers(s, marks);
    const firstMark = marks.length ? (marks[0].time as number) : null;
    const startAt = firstMark !== null && tEntry !== null ? Math.min(firstMark, tEntry as number) : (tEntry as number | null);
    if (startAt !== null) {   // open on the setup: a little before its first marker to the end
      const before = (box.current?.clientWidth ?? 800) < 600 ? 10 : 30;   // fewer candles before it on a phone
      const i = Math.max(0, times.indexOf(startAt) - before);
      chart.timeScale().setVisibleLogicalRange({ from: i, to: times.length + 5 });
    }
    return () => chart.remove();
  }, [doc]);

  const p = doc?.pos;
  const r = p && p.entry != null && p.risk_stop != null ? Math.abs(p.entry - p.risk_stop) : null;
  const rr = p && r && p.entry != null && p.target != null ? Math.abs(p.target - p.entry) / r : null;
  const v = doc?.verdict;
  return (
    <dialog ref={dlg} className="chart-dialog" onClose={onClose} aria-labelledby="chart-title">
      <div className="chart-head">
        <div>
          <h2 id="chart-title" style={{ margin: 0, fontSize: 16 }}>{title}{p ? ` · ${p.side ?? "long"}` : ""}</h2>
          {p && (
            <p className="small muted" style={{ margin: "2px 0 0" }}>
              {p.setup_name ?? "trade"}{p.planned ? " · planned" : ""}
              {p.entry != null ? ` · entry ${p.entry}` : ""}{p.risk_stop ?? p.stop ? ` · stop ${p.risk_stop ?? p.stop}` : ""}
              {p.target != null && !p.trail_k ? ` · target ${p.target}` : ""}
              {rr ? ` · ${rr.toFixed(1)}R` : ""} · {doc?.tf} candles, IST
            </p>
          )}
        </div>
        <button className="btn small-btn" onClick={() => dlg.current?.close()} aria-label="Close chart">Close</button>
      </div>
      {err && <div className="notice bad">Chart not loaded: {err}</div>}
      {v && (
        <div className={`chart-verdict tone-${v.tone}`} role="status">
          <b>{v.title}</b>
          <ul>{v.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </div>
      )}
      {!doc && !err && <p className="muted small">Loading candles…</p>}
      {doc && !doc.candles.length && <div className="notice bad">No candles came back for {doc.chart}.</div>}
      <div ref={box} className="chart-box" />
      {doc?.note && <p className="small muted" style={{ margin: "6px 0 0" }}>{doc.note}</p>}
      <p className="small muted chart-legend" style={{ margin: "6px 0 0" }}>
        Markers: ■ BOS · ▼▲ sweep · ● signal / Trade Manager · arrow = entry · red ■ = skipped · exit in green (win) / red (loss)
      </p>
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
