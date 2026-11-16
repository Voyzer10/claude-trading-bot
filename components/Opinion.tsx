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

const MAX_IMAGES = 6;
const MAX_SIDE = 1600;

/** A picked / pasted / dropped image as a base64 data URL: big or odd ones redrawn as a JPEG of at most MAX_SIDE px. */
async function toDataURL(file: File): Promise<string> {
  const read = (b: Blob) => new Promise<string>((ok, bad) => {
    const fr = new FileReader(); fr.onload = () => ok(String(fr.result)); fr.onerror = () => bad(fr.error); fr.readAsDataURL(b);
  });
  const small = file.size <= 1.5 * 1024 * 1024 && ["image/png", "image/jpeg", "image/webp"].includes(file.type);
  let bmp: ImageBitmap | null = null;
  try { bmp = await createImageBitmap(file); } catch { if (small) return read(file); throw new Error("not an image this browser can read"); }
  if (small && Math.max(bmp.width, bmp.height) <= MAX_SIDE) { bmp.close(); return read(file); }
  const k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
  const cv = document.createElement("canvas");
  cv.width = Math.round(bmp.width * k); cv.height = Math.round(bmp.height * k);
  cv.getContext("2d")!.drawImage(bmp, 0, 0, cv.width, cv.height);
  bmp.close();
  const blob = await new Promise<Blob | null>((ok) => cv.toBlob(ok, "image/jpeg", 0.85));
  if (!blob) throw new Error("could not shrink the image");
  return read(blob);
}

/** Screenshots with the opinion: pick (camera / gallery on a phone), paste (Ctrl+V) or drop. */
function ImagePicker({ names, setNames, setErr }: { names: string[]; setNames: (f: (x: string[]) => string[]) => void; setErr: (e: string | null) => void }) {
  const [busy, setBusy] = useState(0);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const add = async (files: File[]) => {
    const imgs = files.filter((f) => f.type.startsWith("image/"));
    if (!imgs.length) return;
    const room = MAX_IMAGES - names.length;
    if (room <= 0) { setErr(`At most ${MAX_IMAGES} images per opinion.`); return; }
    setErr(null);
    for (const f of imgs.slice(0, room)) {
      setBusy((n) => n + 1);
      try {
        const r = await postJSON<{ name: string }>("/api/py/opinion/image", { data: await toDataURL(f) });
        setNames((x) => (x.includes(r.name) || x.length >= MAX_IMAGES ? x : [...x, r.name]));
      } catch (e) {
        setErr(`Image not added: ${String((e as Error)?.message ?? e)}`);
      } finally { setBusy((n) => n - 1); }
    }
  };
  useEffect(() => {      // paste anywhere in the dialog
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.files ?? []);
      if (files.some((f) => f.type.startsWith("image/"))) { e.preventDefault(); add(files); }
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  });
  return (
    <fieldset className="op-q">
      <legend>Screenshots (optional, up to {MAX_IMAGES})</legend>
      <div className={`op-drop${over ? " over" : ""}`}
           onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
           onDrop={(e) => { e.preventDefault(); setOver(false); add(Array.from(e.dataTransfer.files)); }}>
        {names.map((n) => (
          <figure key={n} className="op-thumb">
            <a href={`/api/py/opinion/image/${n}`} target="_blank" rel="noreferrer">
              <img src={`/api/py/opinion/image/${n}`} alt="attached screenshot" loading="lazy" />
            </a>
            <button type="button" className="op-thumb-x" aria-label="Remove this image" onClick={() => setNames((x) => x.filter((y) => y !== n))}>×</button>
          </figure>
        ))}
        {names.length < MAX_IMAGES && (
          <button type="button" className="op-add" onClick={() => input.current?.click()} disabled={busy > 0}>
            {busy > 0 ? "Uploading…" : "+ Add image"}
          </button>
        )}
        <input ref={input} type="file" accept="image/*" multiple hidden
               onChange={(e) => { add(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
      </div>
      <p className="small muted" style={{ margin: "6px 0 0" }}>Pick a file (camera or gallery on a phone), paste a screenshot with Ctrl+V, or drop it here.</p>
    </fieldset>
  );
}

function OpinionDialog({ src, kind, title, onClose }: { src: ChartSource; kind: Kind; title: string; onClose: () => void }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const [qs, setQs] = useState<Question[] | null>(null);
  const [a, setA] = useState<Answers>({});
  const [saved, setSaved] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [images, setImages] = useState<string[]>([]);

  useEffect(() => {
    dlg.current?.showModal();
    getJSON<{ questions: Question[] }>("/api/py/opinion/questions").then((d) => setQs(d.questions)).catch((e) => setErr(String(e?.message ?? e)));
    getJSON<{ answers: Answers; saved_at: string; version: number; images?: string[] } | null>(`/api/py/opinion?ref_id=${encodeURIComponent(refId(src))}`)
      .then((d) => { if (d) { setA(d.answers ?? {}); setImages(d.images ?? []); setSaved(`last saved ${d.saved_at.slice(0, 16).replace("T", " ")} (version ${d.version})`); } })
      .catch(() => {});
  }, [src]);

  const shown = (q: Question) => !q.show_if || Object.entries(q.show_if).every(([k, vs]) => vs.includes(String(a[k] ?? "")));
  const text = (q: Question) => (typeof q.text === "string" ? q.text : q.text[kind] ?? Object.values(q.text)[0]);
  const set = (id: string, v: string | number | string[]) => setA((x) => ({ ...x, [id]: v }));

  async function save() {
    setBusy(true); setErr(null);
    try {
      const answers = Object.fromEntries(Object.entries(a).filter(([k]) => { const q = qs?.find((x) => x.id === k); return q && shown(q); }));
      const r = await postJSON<{ version: number }>("/api/py/opinion", { ref: refOf(src), answers, images });
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
          <ImagePicker names={images} setNames={setImages} setErr={setErr} />
          <div className="actions">
            <button type="submit" className="btn primary" disabled={busy || !a.verdict}>{busy ? "Saving…" : "Save opinion"}</button>
            <span className="small muted">* required. Change it any time: the latest answers count.</span>
          </div>
        </form>
      )}
    </dialog>
  );
}
