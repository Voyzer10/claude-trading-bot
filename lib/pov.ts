"use client";

import { useEffect, useState } from "react";

/** One timeframe's point of view: the direction of the last complete Scanner v4 setup (pov.py; display only). */
export type PovTf = { pov: "bullish" | "bearish" | null; at?: string; setup?: string; why?: string };
export type PovDoc = { written?: number; tfs?: string[]; charts?: Record<string, Record<string, PovTf>> };

let cache: PovDoc | null = null;
let loadedAt = 0;
let inflight: Promise<PovDoc | null> | null = null;
const subs = new Set<(d: PovDoc | null) => void>();

function load(): Promise<PovDoc | null> {
  if (inflight) return inflight;
  inflight = fetch("/api/py/pov", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null)
    .then((d: PovDoc | null) => {
      cache = d;
      loadedAt = Date.now();
      inflight = null;
      subs.forEach((f) => f(d));
      return d;
    });
  return inflight;
}

/** The POV file, shared by every component, refreshed every 5 minutes (it changes hourly). */
export function usePov(): PovDoc | null {
  const [doc, setDoc] = useState<PovDoc | null>(cache);
  useEffect(() => {
    subs.add(setDoc);
    if (!cache || Date.now() - loadedAt > 5 * 60_000) load();
    const id = setInterval(() => { if (Date.now() - loadedAt > 5 * 60_000) load(); }, 60_000);
    return () => { subs.delete(setDoc); clearInterval(id); };
  }, []);
  return doc;
}
