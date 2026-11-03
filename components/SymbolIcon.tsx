"use client";

import { useState } from "react";
import { CRYPTO_ICONS } from "@/lib/cryptoIcons";

/** A small round icon for a coin or stock: the coin's logo (bundled), a stock logo (logo service, US and NSE),
 *  or the ticker's first letters on a colour made from the ticker when there is no logo. */
export default function SymbolIcon({ id, market, symbol, size = 18 }: { id?: string | null; market?: string; symbol?: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  let m = (market ?? "").toUpperCase();
  let s = (symbol ?? "").toUpperCase();
  if (id && id.includes(":")) [m, s] = id.toUpperCase().split(":", 2);
  else if (id) s = id.toUpperCase();
  const base = s.replace(/-USD$/, "").replace(/\.(NS|BO)$/, "");
  const src = !failed ? logoUrl(m, base) : null;
  const style = { width: size, height: size, flex: "none" } as const;
  if (src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img className="sym-icon" src={src} alt="" width={size} height={size} loading="lazy" style={style}
           onError={() => setFailed(true)} />
    );
  }
  return (
    <span className="sym-icon sym-mono" aria-hidden="true"
          style={{ ...style, fontSize: Math.round(size * 0.42), background: `hsl(${hue(base)} 55% 42%)` }}>
      {monogram(base)}
    </span>
  );
}

function logoUrl(market: string, sym: string): string | null {
  if (!sym) return null;
  if (market === "CRYPTO" || (!market && CRYPTO_ICONS.has(sym.toLowerCase()))) {
    return CRYPTO_ICONS.has(sym.toLowerCase()) ? `/icons/crypto/${sym.toLowerCase()}.svg` : null;
  }
  if (market === "US") return `https://financialmodelingprep.com/image-stock/${encodeURIComponent(sym)}.png`;
  if (market === "NSE" || market === "BSE") return `https://financialmodelingprep.com/image-stock/${encodeURIComponent(sym)}.NS.png`;
  return null; // F&O contracts and anything else: the monogram
}

function monogram(sym: string) {
  const clean = sym.replace(/[^A-Z0-9]/g, "");
  return (clean.match(/^(NIFTY|BANKNIFTY)/)?.[0] === "BANKNIFTY" ? "BN" : clean.slice(0, clean.startsWith("NIFTY") ? 1 : 2)) || "?";
}

function hue(s: string) {
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}
