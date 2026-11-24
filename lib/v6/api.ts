// V6 fetch helpers. V6 talks ONLY to its own namespace (/api/py/v6/*, the separate trader-v6-api process).
export const V6 = "/api/py/v6";

export async function v6Get<T>(path: string): Promise<T> {
  const r = await fetch(`${V6}${path}`, { cache: "no-store" });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body as { detail?: string }).detail || `${r.status} ${r.statusText}`);
  return body as T;
}

export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));
