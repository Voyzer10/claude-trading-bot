// Small fetch helpers for the operations API (/api/py/ops/*). Errors carry the server's "detail" message.

export async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(path, { cache: "no-store" });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body as { detail?: string }).detail || `${r.status} ${r.statusText}`);
  return body as T;
}

export async function postJSON<T>(path: string, data: unknown = {}): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body as { detail?: string }).detail || `${r.status} ${r.statusText}`);
  return body as T;
}

export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

export const OPS = "/api/py/ops";
