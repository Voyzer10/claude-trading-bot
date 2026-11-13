"use client";

import { useEffect, useRef, useState } from "react";
import { getJSON, postJSON } from "@/lib/api";
import type { ChartSource } from "@/components/ChartView";

type Kind = "open" | "closed" | "skipped" | "traded";
type Question = {
  id: string; type: "choice" | "multi" | "scale" | "number" | "text"; required?: boolean; long?: boolean;
  text: string | Record<string, string>; options?: [string, string][]; min?: number; max?: number; placeholder?: string;
  show_if?: Record<string, string[]>;
};
type Answers = Record<string, string | number | string[]>;

const refOf = (src: ChartSource) =>
  src.kind === "position" ? { kind: "position", key: src.key, entry_time: src.entryTime } : { kind: "decision", time: src.time, symbol: src.symbol };
export const refId = (src: ChartSource) =>
  src.kind === "position" ? `pos|${src.key}|${src.entryTime ?? ""}` : `dec|${src.symbol}|${src.time}`;

// which trades / candidates already have an opinion (one fetch, shared by every button)
let index: Record<string, string> | null = null;
let loading: Promise<void> | null = null;
const subs = new Set<() => void>();
function loadIndex(force = false) {
  if (loading && !force) return loading;
  loading = getJSON<Record<string, string>>("/api/py/opinion/index")
    .then((d) => { index = d ?? {}; })
    .catch(() => { index = index ?? {}; })
    .then(() => subs.forEach((f) => f()));
  return loading;
}
function useAnswered(id: string) {
  const [, tick] = useState(0);
  useEffect(() => {
    const f = () => tick((n) => n + 1);
    subs.add(f);
    if (!index) loadIndex();
    return () => { subs.delete(f); };
  }, []);
  return !!index?.[id];
}

/** "Your opinion" next to "View on chart": a fixed set of questions about one trade or candidate (owner, 13 Nov 2026). */
export function OpinionButton({ src, kind, title }: { src: ChartSource; kind: Kind; title: string }) {
  const [open, setOpen] = useState(false);
  const answered = useAnswered(refId(src));
  return (
    <>
      <button className={`btn small-btn chart-btn${answered ? " answered" : ""}`} onClick={() => setOpen(true)}
              aria-label={`Your opinion on ${title}${answered ? " (answered, edit)" : ""}`}>
        {answered ? "Your opinion ✓" : "Your opinion"}
      </button>
      {open && <OpinionDialog src={src} kind={kind} title={title} onClose={() => setOpen(false)} />}
    </>
  );
}

function OpinionDialog({ src, kind, title, onClose }: { src: ChartSource; kind: Kind; title: string; onClose: () => void }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const [qs, setQs] = useState<Question[] | null>(null);
  const [a, setA] = useState<Answers>({});
  const [saved, setSaved] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    dlg.current?.showModal();
    getJSON<{ questions: Question[] }>("/api/py/opinion/questions").then((d) => setQs(d.questions)).catch((e) => setErr(String(e?.message ?? e)));
    getJSON<{ answers: Answers; saved_at: string; version: number } | null>(`/api/py/opinion?ref_id=${encodeURIComponent(refId(src))}`)
      .then((d) => { if (d) { setA(d.answers ?? {}); setSaved(`last saved ${d.saved_at.slice(0, 16).replace("T", " ")} (version ${d.version})`); } })
      .catch(() => {});
  }, [src]);

  const shown = (q: Question) => !q.show_if || Object.entries(q.show_if).every(([k, vs]) => vs.includes(String(a[k] ?? "")));
  const text = (q: Question) => (typeof q.text === "string" ? q.text : q.text[kind] ?? Object.values(q.text)[0]);
  const set = (id: string, v: string | number | string[]) => setA((x) => ({ ...x, [id]: v }));

  async function save() {
    setBusy(true); setErr(null);
    try {
      const answers = Object.fromEntries(Object.entries(a).filter(([k]) => { const q = qs?.find((x) => x.id === k); return q && shown(q); }));
      const r = await postJSON<{ version: number }>("/api/py/opinion", { ref: refOf(src), answers });
      await loadIndex(true);
      setSaved(`saved (version ${r.version})`);
      dlg.current?.close();
    } catch (e) {
      setErr(`Not saved: ${String((e as Error)?.message ?? e)}`);
    } finally { setBusy(false); }
  }

  return (
    <dialog ref={dlg} className="chart-dialog opinion-dialog" onClose={onClose} aria-labelledby="op-title">
      <div className="chart-head">
        <div>
          <h2 id="op-title" style={{ margin: 0, fontSize: 16 }}>Your opinion · {title}</h2>
          <p className="small muted" style={{ margin: "2px 0 0" }}>
            Saved with a snapshot of this {kind === "skipped" ? "candidate" : "trade"}; it goes into Download all (opinions.csv) for the rule review.
            {saved ? ` · ${saved}` : ""}
          </p>
        </div>
        <button className="btn small-btn" onClick={() => dlg.current?.close()} aria-label="Close">Close</button>
      </div>
      {err && <div className="notice bad" role="alert">{err}</div>}
      {!qs && !err && <p className="muted small">Loading questions…</p>}
      {qs && (
        <form className="opinion-form" onSubmit={(e) => { e.preventDefault(); save(); }}>
          {qs.filter(shown).map((q) => (
            <fieldset key={q.id} className="op-q">
              <legend>{text(q)}{q.required ? " *" : ""}</legend>
              {q.type === "choice" && (
                <div className="op-opts" role="radiogroup" aria-label={text(q)}>
                  {q.options!.map(([v, l]) => (
                    <label key={v} className={`op-opt${a[q.id] === v ? " on" : ""}`}>
                      <input type="radio" name={q.id} value={v} checked={a[q.id] === v} onChange={() => set(q.id, v)} />{l}
                    </label>
                  ))}
                </div>
              )}
              {q.type === "multi" && (
                <div className="op-opts multi">
                  {q.options!.map(([v, l]) => {
                    const cur = (a[q.id] as string[] | undefined) ?? [];
                    const on = cur.includes(v);
                    return (
                      <label key={v} className={`op-opt${on ? " on" : ""}`}>
                        <input type="checkbox" checked={on} onChange={() => set(q.id, on ? cur.filter((x) => x !== v) : [...cur, v])} />{l}
                      </label>
                    );
                  })}
                </div>
              )}
              {q.type === "scale" && (
                <div className="op-opts" role="radiogroup" aria-label={text(q)}>
                  {Array.from({ length: (q.max ?? 5) - (q.min ?? 1) + 1 }, (_, i) => (q.min ?? 1) + i).map((n) => (
                    <label key={n} className={`op-opt num${a[q.id] === n ? " on" : ""}`}>
                      <input type="radio" name={q.id} checked={a[q.id] === n} onChange={() => set(q.id, n)} />{n}
                    </label>
                  ))}
                </div>
              )}
              {q.type === "number" && (
                <input type="number" inputMode="decimal" step="any" value={String(a[q.id] ?? "")} aria-label={text(q)}
                       onChange={(e) => set(q.id, e.target.value)} />
              )}
              {q.type === "text" && (q.long ? (
                <textarea rows={3} maxLength={q.max} value={String(a[q.id] ?? "")} aria-label={text(q)}
                          onChange={(e) => set(q.id, e.target.value)} />
              ) : (
                <input type="text" maxLength={q.max} placeholder={q.placeholder} value={String(a[q.id] ?? "")} aria-label={text(q)}
                       onChange={(e) => set(q.id, e.target.value)} />
              ))}
            </fieldset>
          ))}
          <div className="actions">
            <button type="submit" className="btn primary" disabled={busy || !a.verdict}>{busy ? "Saving…" : "Save opinion"}</button>
            <span className="small muted">* required. Change it any time: the latest answers count.</span>
          </div>
        </form>
      )}
    </dialog>
  );
}
