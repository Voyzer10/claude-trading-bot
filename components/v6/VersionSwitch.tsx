// The V4 | V6 switch. Plain links between two independent pages: "/" (V4, unchanged) and "/v6" (V6).
export default function VersionSwitch({ current }: { current: "v4" | "v6" }) {
  const item = (key: "v4" | "v6", href: string, label: string) => (
    <a
      href={href}
      aria-current={current === key ? "page" : undefined}
      style={{
        padding: "3px 10px", borderRadius: 6, fontSize: 12, fontWeight: 700, textDecoration: "none",
        color: current === key ? "var(--on-accent, #fff)" : "var(--muted)",
        background: current === key ? "var(--accent)" : "transparent",
      }}
    >
      {label}
    </a>
  );
  return (
    <nav aria-label="Scanner version" style={{ display: "inline-flex", gap: 2, padding: 2, border: "1px solid var(--line)", borderRadius: 8 }}>
      {item("v4", "/", "V4")}
      {item("v6", "/v6", "V6")}
    </nav>
  );
}
