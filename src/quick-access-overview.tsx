import type { ReactNode } from "react";
import { placementCards } from "./quick-access-dashboard";

const colors = { cyan: "#26c9ff", text: "#edf4ff", muted: "#b6c9e3" };
const paths = {
  handheld: "M5 6h14l3 12h-5l-2-3H9l-2 3H2z M6 10h5 M8.5 7.5v5 M16 9h.1 M18 11h.1",
  monitor: "M3 4h18v13H3z M8 21h8 M12 17v4",
  connection: "M8 3v5 M16 3v5 M6 8h12v4a6 6 0 0 1-12 0z M12 18v4",
  power: "M12 2v10 M6 5a9 9 0 1 0 12 0",
  bolt: "M13 2L4 14h7l-1 8 10-12h-7z",
  tools: "M14 3a6 6 0 0 0-7 7L2 15l7 7 5-5a6 6 0 0 0 7-7l-4 4-5-5z",
};

export function DashboardIcon({ kind }: { kind: keyof typeof paths }) {
  return <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    style={{ flexShrink: 0 }}><path d={paths[kind]} /></svg>;
}

export function DashboardSurface({ children, primary = false }: { children: ReactNode; primary?: boolean }) {
  return <div style={{ borderRadius: 16, marginBottom: 12, minWidth: 0,
    border: `1px solid ${primary ? "#ad8040" : "#304a6b"}`,
    background: primary ? "linear-gradient(110deg, #302411, #111e30)" : "linear-gradient(120deg, #122139, #0a1423)",
    color: colors.text }}>{children}</div>;
}

export function QuickAccessOverview({ mode, modeLabel, health, game, loading }: {
  mode: string; modeLabel: string; health: string; game: string; loading: boolean;
}) {
  return <div style={{ display: "grid", gap: 10, color: colors.text, minWidth: 0 }}>
    <div style={{ padding: "10px 12px", border: "1px solid #304a6b", borderRadius: 14, background: "#0b1728" }}>
      <div style={{ fontSize: 16, fontWeight: 650 }}>{modeLabel}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", fontSize: 12, color: colors.muted }}>
        <span>Health: {health}</span><span>Game: {game}</span>
      </div>
    </div>
    {placementCards(mode, loading).map((card) => <div key={card.name}
      style={{ display: "flex", gap: 12, alignItems: "center", minWidth: 0, padding: "12px",
        borderRadius: 15, border: `1px solid ${card.active ? colors.cyan : "#30405b"}`,
        background: card.active ? "linear-gradient(115deg, #073351, #10203a)" : "#0b1525",
        boxShadow: card.active ? "inset 0 0 18px #00aaff15" : "none" }}>
      <span style={{ color: card.active ? colors.cyan : "#91afd5", display: "flex" }}>
        <DashboardIcon kind={card.name === "Portable" ? "handheld" : "monitor"} />
      </span>
      <div style={{ minWidth: 0, overflowWrap: "anywhere" }}>
        <div style={{ fontSize: 14, fontWeight: 650 }}>{card.name}</div>
        <div style={{ fontSize: 12, color: colors.muted }}>{card.detail}</div>
        <div style={{ fontSize: 11, color: card.active ? colors.cyan : colors.muted, marginTop: 4 }}>
          {card.active ? "✓ Current mode" : loading ? "Reading…" : "Not verified current · Status only"}
        </div>
      </div>
    </div>)}
  </div>;
}
