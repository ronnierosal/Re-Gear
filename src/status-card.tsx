import { regearTheme as theme } from "./regear-theme";
/** Decorative icons never substitute for the independent, text-labelled facts. */
const ICONS: Record<string, { color: string; path: string }> = {
  Mode: { color: "#9baeff", path: "M3 5h18v12H3z M8 21h8 M12 17v4" },
  Health: { color: "#7edbd2", path: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M7 12h3l2-4 2 8 2-4h2" },
  Connection: { color: "#82caff", path: "M8 3v5 M16 3v5 M6 8h12v4a6 6 0 0 1-12 0z M12 18v4" },
  Game: { color: "#c6adff", path: "M6 7h12l3 11h-5l-2-3h-4l-2 3H3z M6 11h5 M8.5 8.5v5 M16 10h.1 M18 12h.1" },
};

export function StatusCard({ name, value }: { name: string; value: string }) {
  const icon = ICONS[name] ?? ICONS.Mode;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12, minWidth: 0,
      padding: "12px", marginBottom: 8, borderRadius: 12,
      border: `1px solid ${theme.border}`,
      background: theme.surface,
    }}>
      <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"
        style={{ color: icon.color, flexShrink: 0 }} fill="none" stroke="currentColor"
        strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d={icon.path} />
      </svg>
      <div style={{ minWidth: 0, lineHeight: 1.4 }}>
        <div style={{ fontSize: 12, opacity: 0.8 }}>{name}</div>
        <div style={{ fontSize: 15, fontWeight: 600, overflowWrap: "anywhere" }}>{value}</div>
      </div>
    </div>
  );
}
