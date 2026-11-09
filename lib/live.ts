"use client";

import { useEffect, useState } from "react";

/** One instrument's latest tick from Zerodha (kite_ticker.py -> /api/py/live/ticks). */
export type Tick = { ltp: number; t?: number; open?: number; high?: number; low?: number; close?: number; volume?: number; oi?: number };
export type LiveTicks = { age_s: number | null; live: boolean; connected: boolean; ticks: Record<string, Tick> };

/** Polls the Indian market ticks every second while the page is visible. Returns null until the first answer,
 *  or when the server has no Zerodha endpoints (cloud mode). */
export function useLiveTicks(enabled = true): LiveTicks | null {
  const [data, setData] = useState<LiveTicks | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let fails = 0;
    async function tick() {
      if (stop) return;
      if (document.visibilityState === "visible") {
        try {
          const r = await fetch("/api/py/live/ticks", { cache: "no-store" });
          if (r.status === 404) return; // no Zerodha endpoints here: stop polling
          if (r.ok) {
            setData((await r.json()) as LiveTicks);
            fails = 0;
          } else fails++;
        } catch {
          fails++;
        }
      }
      // every second; back off to 10 s after repeated failures; slow (5 s) when nothing is streaming
      timer = setTimeout(tick, fails > 3 ? 10000 : 1000);
    }
    tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled]);
  return data;
}

export const INDIA = (m: string) => m === "NSE" || m === "BSE" || m === "NFO";
