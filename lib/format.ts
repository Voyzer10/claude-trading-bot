// Formatting helpers. All times are shown in India time (IST), the bot's clock.

const IST = "Asia/Kolkata";

export function timeIST(iso: string | null | undefined, withDate = false): string {
  if (!iso) return "—";
  const d = new Date(iso.includes("T") || iso.includes("+") ? iso : iso.replace(" ", "T") + "+05:30");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", {
    timeZone: IST,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    ...(withDate ? { day: "2-digit", month: "short" } : {}),
  });
}

export function ago(seconds: number): string {
  if (seconds < 0) seconds = 0;
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  const m = seconds / 60;
  if (m < 90) return `${Math.round(m)} min ago`;
  const h = m / 60;
  if (h < 48) return `${h.toFixed(1)} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

export function duration(ms: number): string {
  const min = Math.max(0, Math.round(ms / 60000));
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
  return h ? `${h}h ${m}m` : `${m}m`;
}

export function price(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  const a = Math.abs(x);
  const digits = a >= 1000 ? 2 : a >= 1 ? 4 : 6;
  return x.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: a >= 1000 ? 2 : 0 });
}

export function money(x: number | null | undefined, cur = "$"): string {
  if (x === null || x === undefined) return "—";
  const s = Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
  return `${x < 0 ? "−" : ""}${cur}${s}`;
}

export function pct(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return `${x > 0 ? "+" : ""}${x.toFixed(2)}%`;
}

export const currencyOf = (account: string) => (account === "US" || account === "USFNO" || account === "CRYPTO" ? "$" : "₹");
