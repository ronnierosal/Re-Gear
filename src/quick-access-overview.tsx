import { regearTheme as theme } from "./regear-theme";
import type { ReactNode } from "react";
import { placementCards } from "./quick-access-dashboard";
import handheldModeIcon from "./assets/mode-handheld.svg";
import tvModeIcon from "./assets/mode-tv.svg";

const colors = {
  cyan: theme.accent,
  cyanSoft: theme.accentSoft,
  orange: "#f2a23b",
  text: theme.text,
  muted: theme.muted,
  border: theme.border,
  surface: "#0a1422",
};

const paths = {
  handheld: "M5 6h14l3 12h-5l-2-3H9l-2 3H2z M6 10h5 M8.5 7.5v5 M16 9h.1 M18 11h.1",
  monitor: "M3 4h18v13H3z M8 21h8 M12 17v4",
  connection: "M8 3v5 M16 3v5 M6 8h12v4a6 6 0 0 1-12 0z M12 18v4",
  power: "M12 2v10 M6 5a9 9 0 1 0 12 0",
  bolt: "M13 2L4 14h7l-1 8 10-12h-7z",
  tools: "M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z",
};

export function DashboardIcon({ kind, size = 24 }: { kind: keyof typeof paths; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    style={{ flexShrink: 0 }}><path d={paths[kind]} /></svg>;
}

export function DashboardSurface({ children, primary = false }: { children: ReactNode; primary?: boolean }) {
  return <div style={{
    borderRadius: 16,
    marginTop: 10,
    marginBottom: 12,
    minWidth: 0,
    overflow: "hidden",
    border: `1px solid ${primary ? colors.cyan : colors.border}`,
    background: primary
      ? theme.activeSurface
      : theme.surface,
    boxShadow: primary
      ? "inset 0 1px 0 rgba(255,255,255,.04), 0 8px 22px rgba(0,0,0,.18)"
      : "inset 0 1px 0 rgba(255,255,255,.025)",
    color: colors.text,
  }}>{children}</div>;
}

function StatusPill({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return <span style={{
    display: "inline-flex",
    alignItems: "center",
    gap: 5,
    minWidth: 0,
    padding: "4px 7px",
    borderRadius: 999,
    border: `1px solid ${accent ? "#2e7892" : "#31465f"}`,
    background: accent ? "rgba(19, 79, 100, .34)" : "rgba(7, 17, 29, .55)",
    color: accent ? colors.cyanSoft : colors.muted,
    fontSize: 11,
    lineHeight: 1.2,
    whiteSpace: "nowrap",
  }}>
    <span style={{ opacity: .72 }}>{label}</span>
    <span style={{ color: colors.text, fontWeight: 650 }}>{value}</span>
  </span>;
}

export function QuickAccessOverview({ mode, modeLabel, health, game, loading }: {
  mode: string; modeLabel: string; health: string; game: string; loading: boolean;
}) {
  const cards = placementCards(mode, loading);
  return <div style={{ display: "grid", gap: 10, color: colors.text, minWidth: 0 }}>
    <div style={{
      padding: "11px 12px 10px",
      border: `1px solid ${colors.border}`,
      borderRadius: 15,
      background: theme.surface,
      boxShadow: "inset 0 1px 0 rgba(255,255,255,.025)",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 11, letterSpacing: ".11em", textTransform: "uppercase", color: colors.cyanSoft,
            fontWeight: 700, marginBottom: 3 }}>Current state</div>
          <div style={{ fontSize: 17, lineHeight: 1.15, fontWeight: 700, overflowWrap: "normal" }}>{modeLabel}</div>
        </div>
        <span style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
          background: loading ? "#6d8098" : colors.cyan,
          boxShadow: "none" }} />
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 9 }}>
        <StatusPill label="Health" value={health} accent={!loading && health.toLowerCase().includes("ready")} />
        <StatusPill label="Game" value={game} />
      </div>
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
      {cards.map((card) => <div key={card.name}
        style={{
          position: "relative",
          minWidth: 0,
          minHeight: 105,
          padding: "11px 10px 10px",
          borderRadius: 15,
          border: `1px solid ${card.active ? colors.cyan : "#2b4058"}`,
          background: card.active
            ? theme.activeSurface
            : theme.surface,
          boxShadow: card.active
            ? "inset 0 1px 0 rgba(255,255,255,.04)"
            : "inset 0 1px 0 rgba(255,255,255,.02)",
          overflow: "hidden",
        }}>
        {card.active && <span style={{ position: "absolute", top: 0, left: 10, right: 10, height: 2,
          borderRadius: "0 0 4px 4px", background: colors.cyan,
          boxShadow: "none" }} />}
        <div style={{display:"flex", flexDirection:"column", alignItems:"center", gap:10, textAlign:"center", padding:"5px 0"}}>
          <span style={{color:card.active ? colors.cyanSoft : colors.muted, display:"flex", alignItems:"center", justifyContent:"center", height:42}}>
            <img
              src={card.name === "Portable" ? handheldModeIcon : tvModeIcon}
              alt=""
              aria-hidden="true"
              width={48}
              height={48}
              style={{ display: "block", objectFit: "contain" }}
            />
          </span>
          <div style={{fontSize:15, fontWeight:650}}>{card.name}</div>
          <div style={{fontSize:11, letterSpacing:".06em", color:card.active ? colors.cyan : colors.muted, minHeight:15}}>
            {card.active ? "ACTIVE" : loading ? "Reading…" : "Not active"}
          </div>
        </div>
      </div>)}
    </div>
  </div>;
}
