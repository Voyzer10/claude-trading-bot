"use client";

import { usePov } from "@/lib/pov";

const LABEL: Record<string, string> = { "1h": "1h", "4h": "4h", "1D": "D", "1W": "W", "1M": "M" };

/** The bigger picture of one chart: 1h / 4h / D / W / M, green = the last complete v4 setup there was a BUY, red = a
 *  SELL, grey = none yet. Display only (owner, 12 Nov 2026): it never blocks or opens a trade. */
export default function PovChips({ id }: { id: string }) {
  const doc = usePov();
  const c = doc?.charts?.[id];
  if (!c) return null;
  const tfs = doc?.tfs ?? ["1h", "4h", "1D", "1W", "1M"];
  const words = tfs.map((tf) => `${tf} ${c[tf]?.pov ?? "none"}`).join(", ");
  return (
    <span className="pov" role="img" aria-label={`Bigger picture: ${words}`} title={`Last complete v4 setup per timeframe: ${words}`}>
      {tfs.map((tf) => {
        const p = c[tf]?.pov;
        return <i key={tf} className={p === "bullish" ? "bull" : p === "bearish" ? "bear" : ""}>{LABEL[tf] ?? tf}</i>;
      })}
    </span>
  );
}
