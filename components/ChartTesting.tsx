"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { errText, postJSON } from "@/lib/api";
import {
  extractCandlesFromImage,
  renderAnnotatedChart,
  type ChartAnalysis,
  type ExtractedChart,
} from "@/lib/chartExtractor";

type ScannerVersion = "v6" | "v5" | "v4" | "v3" | "v2" | "rules";

const SCANNERS: { id: ScannerVersion; name: string; desc: string }[] = [
  { id: "v6", name: "V6 SMC Scanner", desc: "CHoCH -> Reversal BOS -> Liquidity Sweep -> Candlestick Pattern -> 3-Candle Confirmation -> Structural SL & Opposing Liquidity TP" },
  { id: "v5", name: "Scanner v5 (0.146 Level)", desc: "Confirmed swing leg (L -> H) retracing to 0.146 level without closing beyond it, stop beyond extreme, target leg / 2R" },
  { id: "v4", name: "Scanner v4 (11 Nov Workflow)", desc: "BOS -> Sweep of BOS origin -> Buying/Selling signal candle -> Trigger close -> Entry, plus secondary OB/FVG retest" },
  { id: "v3", name: "Scanner v3 (Sweep Reversal)", desc: "BOS -> Close beyond swept swing -> Doji/Hammer signal -> Trigger close + FVG/OB retest" },
  { id: "v2", name: "Scanner v2 (A-B-C-D)", desc: "BOS (A) -> Red close below swing (B) -> Doji (C) -> Close above doji high (D)" },
  { id: "rules", name: "Core Rules (Breakout / ORB)", desc: "Opening / consolidation range high & low with breakout / breakdown close signals" },
];

export default function ChartTesting() {
  const [version, setVersion] = useState<ScannerVersion>("v6");
  const [direction, setDirection] = useState<"both" | "long" | "short">("both");
  const [minRr, setMinRr] = useState(1.0);
  const [slBufferTicks, setSlBufferTicks] = useState(2);
  const [tpOffsetTicks, setTpOffsetTicks] = useState(1);
  const [cLevel, setCLevel] = useState(0.146);

  const [origUrl, setOrigUrl] = useState<string | null>(null);
  const [annotatedUrl, setAnnotatedUrl] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"annotated" | "original">("annotated");
  const [extracted, setExtracted] = useState<ExtractedChart | null>(null);
  const [analysis, setAnalysis] = useState<ChartAnalysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const imgRef = useRef<HTMLImageElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const loadImageFile = useCallback((file: File) => {
    if (!file.type.startsWith("image/")) {
      setErr("Please upload a PNG, JPG, or WebP chart image.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || "");
      setOrigUrl(dataUrl);
      setAnnotatedUrl(null);
      setAnalysis(null);
      setExtracted(null);
      setErr(null);

      const im = new Image();
      im.onload = () => {
        imgRef.current = im;
      };
      im.src = dataUrl;
    };
    reader.readAsDataURL(file);
  }, []);

  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const it of items) {
        if (it.type.startsWith("image/")) {
          const f = it.getAsFile();
          if (f) {
            loadImageFile(f);
            break;
          }
        }
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [loadImageFile]);

  const runAnalysis = async () => {
    const im = imgRef.current;
    if (!im) {
      setErr("Upload or paste a chart image first.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const ext = extractCandlesFromImage(im);
      setExtracted(ext);
      if (ext.candles.length < 8) {
        throw new Error(`Only detected ${ext.candles.length} candle(s) in the image. Use a clearer candlestick chart screenshot.`);
      }
      const res = await postJSON<ChartAnalysis>("/api/py/chart-test/analyze", {
        scanner_version: version,
        candle_count: ext.candles.length,
        calibration: ext.calibration,
        candles: ext.calibration.available ? ext.candles.map((c) => [c.t, c.o, c.h, c.l, c.c, 1000]) : [],
        options: {
          direction,
          min_rr: minRr,
          sl_buffer_ticks: slBufferTicks,
          tp_offset_ticks: tpOffsetTicks,
          c_level: cLevel,
        },
      });
      setAnalysis(res);
      if (!ext.calibration.available) {
        setErr(`Price calibration unavailable: ${ext.calibration.reason || "Could not extract >= 2 reliable axis ticks."} Trade levels refused.`);
      }
      const outUrl = renderAnnotatedChart(im, ext, res);
      setAnnotatedUrl(outUrl);
      setViewMode("annotated");
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  };

  const activeMeta = SCANNERS.find((s) => s.id === version) ?? SCANNERS[0];

  return (
    <section className="panel" aria-labelledby="chart-test-h">
      <div className="panel-head">
        <div>
          <h2 id="chart-test-h">Chart testing</h2>
          <p className="muted small">Upload any candlestick chart image, select a scanner strategy, and mark all detected structure, liquidity, zones, and trade levels directly on the image.</p>
        </div>
      </div>

      {/* Scanner & strategy selection */}
      <div className="grid-2" style={{ marginBottom: 14 }}>
        <div>
          <label className="small muted" htmlFor="ct-scanner">Scanner strategy</label>
          <select
            id="ct-scanner"
            value={version}
            onChange={(e) => setVersion(e.target.value as ScannerVersion)}
            style={{ width: "100%", marginTop: 4 }}
          >
            {SCANNERS.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <p className="small muted" style={{ marginTop: 6 }}>{activeMeta.desc}</p>
        </div>

        <div className="grid-2" style={{ gap: 8 }}>
          <div>
            <label className="small muted" htmlFor="ct-dir">Direction</label>
            <select id="ct-dir" value={direction} onChange={(e) => setDirection(e.target.value as "both" | "long" | "short")} style={{ width: "100%", marginTop: 4 }}>
              <option value="both">Both (Long &amp; Short)</option>
              <option value="long">Long only</option>
              <option value="short">Short only</option>
            </select>
          </div>
          <div>
            <label className="small muted" htmlFor="ct-rr">Min R:R</label>
            <input id="ct-rr" type="number" step="0.1" min="0" value={minRr} onChange={(e) => setMinRr(Number(e.target.value) || 0)} style={{ width: "100%", marginTop: 4 }} />
          </div>
          {version === "v6" && (
            <>
              <div>
                <label className="small muted" htmlFor="ct-slbuf">V6 SL buffer ticks</label>
                <input id="ct-slbuf" type="number" min="0" value={slBufferTicks} onChange={(e) => setSlBufferTicks(Number(e.target.value) || 0)} style={{ width: "100%", marginTop: 4 }} />
              </div>
              <div>
                <label className="small muted" htmlFor="ct-tpoff">V6 TP offset ticks</label>
                <input id="ct-tpoff" type="number" min="0" value={tpOffsetTicks} onChange={(e) => setTpOffsetTicks(Number(e.target.value) || 0)} style={{ width: "100%", marginTop: 4 }} />
              </div>
            </>
          )}
          {version === "v5" && (
            <div>
              <label className="small muted" htmlFor="ct-clevel">0.146 level</label>
              <input id="ct-clevel" type="number" step="0.001" min="0.05" max="0.5" value={cLevel} onChange={(e) => setCLevel(Number(e.target.value) || 0.146)} style={{ width: "100%", marginTop: 4 }} />
            </div>
          )}
        </div>
      </div>

      {/* Upload / dropzone */}
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const f = e.dataTransfer.files?.[0];
          if (f) loadImageFile(f);
        }}
        style={{
          border: "1px dashed var(--border, #3f3f46)",
          borderRadius: 10,
          padding: 16,
          textAlign: "center",
          marginBottom: 14,
        }}
      >
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) loadImageFile(f);
          }}
        />
        <div style={{ display: "flex", gap: 10, justifyContent: "center", alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn" type="button" onClick={() => fileRef.current?.click()}>
            {origUrl ? "Change chart image" : "Upload chart image"}
          </button>
          <span className="muted small">or drag &amp; drop / paste (Ctrl+V) a TradingView, Kite, or CoinDCX screenshot</span>
          {origUrl && (
            <button className="btn primary" type="button" disabled={busy} onClick={runAnalysis}>
              {busy ? "Analyzing…" : `Analyze & Mark with ${activeMeta.name}`}
            </button>
          )}
        </div>
      </div>

      {err && <div className="notice bad" style={{ marginBottom: 12 }}>{err}</div>}

      {/* Output Image Viewer */}
      {(annotatedUrl || origUrl) && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 8 }}>
            <div className="seg" role="tablist" aria-label="Image view">
              {annotatedUrl && (
                <button role="tab" aria-selected={viewMode === "annotated"} onClick={() => setViewMode("annotated")}>
                  Marked output
                </button>
              )}
              <button role="tab" aria-selected={viewMode === "original" || !annotatedUrl} onClick={() => setViewMode("original")}>
                Original image
              </button>
            </div>
            {annotatedUrl && (
              <a
                className="btn"
                href={annotatedUrl}
                download={`chart-test-${version}.png`}
              >
                Download marked image
              </a>
            )}
          </div>
          <img
            src={viewMode === "annotated" && annotatedUrl ? annotatedUrl : (origUrl ?? "")}
            alt="Chart test output"
            style={{ width: "100%", height: "auto", borderRadius: 8, border: "1px solid var(--border, #27272a)" }}
          />
          {extracted && (
            <div className="muted small" style={{ marginTop: 6, display: "grid", gap: 4 }}>
              <div>
                Extracted {extracted.candles.length} candlesticks from uploaded image ({extracted.width}×{extracted.height}px).
                {extracted.calibration.available && extracted.ohlcRange && (
                  <>
                    {" "}· Axis ({extracted.calibration.axisSide}): {extracted.calibration.points.length} tick(s)
                    {" "}({extracted.calibration.points[0]?.label} … {extracted.calibration.points[extracted.calibration.points.length - 1]?.label})
                    {extracted.calibration.anchor && ` · Anchor (${extracted.calibration.anchor.source}): ${extracted.calibration.anchor.label}`}
                    {" "}· OHLC range: {extracted.ohlcRange.minLow} – {extracted.ohlcRange.maxHigh}
                  </>
                )}
              </div>
              {!extracted.calibration.available && (
                <div style={{ color: "#f87171", fontWeight: 600 }}>
                  Price calibration unavailable: {extracted.calibration.reason || "Insufficient axis labels."} Trade levels refused.
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* V6 3-Panel Breakdown (Key Candles OHLC, Structure & Logic Summary, V6 Concepts) */}
      {analysis && (analysis.key_candles || analysis.logic_summary || analysis.concepts) && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 12,
            marginBottom: 14,
          }}
        >
          {/* Panel 1: Key Candles - OHLC */}
          <div className="panel" style={{ margin: 0, overflowX: "auto" }}>
            <div className="panel-head">
              <h3>Key Candles — OHLC</h3>
            </div>
            {analysis.key_candles && analysis.key_candles.length > 0 ? (
              <table className="small" style={{ width: "100%", borderCollapse: "collapse", fontVariantNumeric: "tabular-nums" }}>
                <thead>
                  <tr className="muted" style={{ borderBottom: "1px solid var(--line, #27272a)", textAlign: "left" }}>
                    <th style={{ padding: "5px 4px" }}>#</th>
                    <th style={{ padding: "5px 4px" }}>Bar</th>
                    <th style={{ padding: "5px 4px" }}>Open</th>
                    <th style={{ padding: "5px 4px" }}>High</th>
                    <th style={{ padding: "5px 4px" }}>Low</th>
                    <th style={{ padding: "5px 4px" }}>Close</th>
                    <th style={{ padding: "5px 4px" }}>Note</th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.key_candles.map((kc) => {
                    const rowBg =
                      kc.highlight === "entry" || kc.highlight === "good"
                        ? "rgba(34, 197, 94, 0.14)"
                        : kc.highlight === "bad"
                          ? "rgba(239, 68, 68, 0.10)"
                          : "transparent";
                    const noteColor =
                      kc.highlight === "entry" || kc.highlight === "good"
                        ? "#4ade80"
                        : kc.highlight === "bad"
                          ? "#f87171"
                          : kc.highlight === "warn"
                            ? "#c084fc"
                            : "#93c5fd";
                    return (
                      <tr key={kc.num} style={{ background: rowBg, borderBottom: "1px solid var(--line, #1f2937)" }}>
                        <td style={{ padding: "5px 4px" }}>{kc.num}</td>
                        <td style={{ padding: "5px 4px" }}>#{kc.index + 1}</td>
                        <td style={{ padding: "5px 4px" }}>{kc.open}</td>
                        <td style={{ padding: "5px 4px" }}>{kc.high}</td>
                        <td style={{ padding: "5px 4px" }}>{kc.low}</td>
                        <td style={{ padding: "5px 4px" }}>{kc.close}</td>
                        <td style={{ padding: "5px 4px", color: noteColor, fontWeight: 600 }}>{kc.note}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p className="muted small">No key setup candles flagged yet on this chart.</p>
            )}
          </div>

          {/* Panel 2: Structure & Logic Summary */}
          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-head">
              <h3>Structure &amp; Logic Summary</h3>
            </div>
            <ol className="small" style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 6 }}>
              {(analysis.logic_summary || []).map((item) => (
                <li key={item.step} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                  <span
                    style={{
                      minWidth: 18,
                      height: 18,
                      borderRadius: 999,
                      background: "#d97706",
                      color: "#09090b",
                      fontSize: 11,
                      fontWeight: 800,
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      marginTop: 1,
                    }}
                  >
                    {item.step}
                  </span>
                  <div>
                    <b>{item.title}:</b> <span className="muted">{item.detail}</span>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          {/* Panel 3: V6 Concepts on Chart */}
          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-head">
              <h3>V6 Concepts on Chart</h3>
            </div>
            <ul className="small" style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 7 }}>
              {(analysis.concepts || []).map((cp) => (
                <li key={cp.name} style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                  <div>
                    <span style={{ color: cp.passed ? "#4ade80" : "#64748b", marginRight: 6, fontWeight: 700 }}>
                      {cp.passed ? "✓" : "○"}
                    </span>
                    <b>{cp.name}</b> — <span className="muted">{cp.detail}</span>
                  </div>
                  <span className={`chip ${cp.passed ? "good" : "warn"}`}>{cp.passed ? "✓" : "—"}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Strategy Breakdown & Checklist */}
      {analysis && (
        <div className="grid-2">
          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-head"><h3>Strategy checklist ({analysis.strategy_name})</h3></div>
            <ul className="small" style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 8 }}>
              {analysis.checklist.map((c) => (
                <li key={c.step} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                  <span className={`chip ${c.passed ? "good" : "warn"}`}>{c.passed ? "PASS" : "NONE"}</span>
                  <div>
                    <div><b>{c.step}</b></div>
                    <div className="muted">{c.detail}</div>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-head"><h3>Detected setups &amp; markings</h3></div>
            {analysis.trades.length && analysis.validation?.setup_valid !== false ? (
              <ul className="small" style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 8 }}>
                {analysis.trades.map((t, i) => (
                  <li key={i} className="notice ok" style={{ margin: 0 }}>
                    <b>{t.label}</b> · Status: {t.outcome || t.status} · Entry #{t.entry_index + 1} ({t.entry_mode || "Close"}) · R:R {t.rr}
                    {typeof t.realized_r === "number" ? ` · Result: ${t.realized_r >= 0 ? "+" : ""}${t.realized_r}R` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="muted small" style={{ display: "grid", gap: 6 }}>
                <p style={{ margin: 0 }}>
                  No complete trade entry confirmed on this chart for {analysis.strategy_name} (detected structure/levels are still marked on the image).
                </p>
                {analysis.validation && analysis.validation.rejection_reasons.length > 0 && (
                  <div className="notice warn" style={{ margin: 0 }}>
                    <b>Rejected:</b> {analysis.validation.rejection_reasons.join(" · ")}
                  </div>
                )}
              </div>
            )}
            <div className="muted small" style={{ marginTop: 10 }}>
              Lines: {analysis.lines.length} · Zones (Pattern/FVG/OB): {analysis.zones.length} · Markers: {analysis.markers.length}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
