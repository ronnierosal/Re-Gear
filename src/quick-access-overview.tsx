import type { ReactNode } from "react";
import brandIcon from "./assets/regear-plugin-icon.png";
import { placementCards } from "./quick-access-dashboard";

const C = {
  cyan: "#39d8ff",
  cyanSoft: "#0aa8e8",
  green: "#5eea8a",
  amber: "#ffc247",
  text: "#f4f7fb",
  muted: "#9eb2ca",
  border: "#294665",
  bg: "#06101d",
  panel: "#0a1727",
  panel2: "#0d1c2f",
};

const paths = {
  handheld: "M5 6h14l3 12h-5l-2-3H9l-2 3H2z M6 10h5 M8.5 7.5v5 M16 9h.1 M18 11h.1",
  monitor: "M3 4h18v13H3z M8 21h8 M12 17v4",
  connection: "M8 3v5 M16 3v5 M6 8h12v4a6 6 0 0 1-12 0z M12 18v4",
  power: "M12 2v10 M6 5a9 9 0 1 0 12 0",
  bolt: "M13 2L4 14h7l-1 8 10-12h-7z",
  tools: "M14 3a6 6 0 0 0-7 7L2 15l7 7 5-5a6 6 0 0 0 7-7l-4 4-5-5z",
};

export function DashboardIcon({ kind, size = 24 }: { kind: keyof typeof paths; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    style={{ flexShrink: 0 }}><path d={paths[kind]} /></svg>;
}

export function DashboardSurface({ children, primary = false }: { children: ReactNode; primary?: boolean }) {
  return <div style={{
    borderRadius: 18,
    marginBottom: 12,
    minWidth: 0,
    overflow: "hidden",
    border: `1px solid ${primary ? "#9d7635" : C.border}`,
    background: primary
      ? "linear-gradient(115deg, rgba(82,58,16,.72), rgba(12,25,42,.98))"
      : "linear-gradient(120deg, rgba(14,31,52,.98), rgba(7,17,30,.98))",
    color: C.text,
    boxShadow: primary ? "inset 0 0 28px rgba(255,185,48,.05)" : "inset 0 0 24px rgba(0,170,255,.025)",
  }}>{children}</div>;
}

function BrandHeader() {
  return <div style={{
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "4px 2px 12px",
    color: C.text,
  }}>
    <img src={brandIcon} alt="" aria-hidden="true" width={34} height={34}
      style={{ objectFit: "contain", flexShrink: 0 }} />
    <div style={{ fontSize: 22, fontWeight: 760, letterSpacing: ".2px" }}>Re-Gear</div>
  </div>;
}

function StatusPill({ label, tone }: { label: string; tone: "ready" | "info" }) {
  const color = tone === "ready" ? C.green : C.cyan;
  return <div style={{
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    minHeight: 28,
    padding: "0 10px",
    borderRadius: 999,
    border: `1px solid ${color}66`,
    color,
    background: `${color}0d`,
    fontSize: 12,
    fontWeight: 650,
    whiteSpace: "nowrap",
  }}>
    <span style={{ width: 8, height: 8, borderRadius: 999, border: `2px solid ${color}`, boxSizing: "border-box" }} />
    {label}
  </div>;
}

function CurrentStateCard({ modeLabel, health, game, loading }: {
  modeLabel: string; health: string; game: string; loading: boolean;
}) {
  return <div style={{
    padding: "14px 15px",
    marginBottom: 14,
    borderRadius: 18,
    border: `1px solid ${C.border}`,
    background: "linear-gradient(135deg, rgba(14,30,49,.98), rgba(7,16,28,.98))",
  }}>
    <div style={{
      color: C.cyan,
      fontSize: 12,
      fontWeight: 760,
      letterSpacing: "1.5px",
      marginBottom: 5,
    }}>CURRENT STATE</div>
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      gap: 10,
      marginBottom: 12,
    }}>
      <div style={{ fontSize: 26, fontWeight: 760, lineHeight: 1 }}>{modeLabel}</div>
      <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: 999, background: C.cyan, boxShadow: `0 0 14px ${C.cyan}` }} />
    </div>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      <StatusPill label={`Health ${loading ? "Reading…" : health}`} tone="ready" />
      <StatusPill label={`Game ${loading ? "Reading…" : game}`} tone="info" />
    </div>
  </div>;
}

function ModeCard({ name, detail, active, loading }: {
  name: string; detail: string; active: boolean; loading: boolean;
}) {
  const isPortable = name === "Portable";
  return <div style={{
    minWidth: 0,
    minHeight: 156,
    padding: "18px 12px 14px",
    borderRadius: 20,
    border: `2px solid ${active ? C.cyan : "#36516f"}`,
    background: active
      ? "linear-gradient(145deg, rgba(4,53,82,.98), rgba(9,26,45,.98))"
      : "linear-gradient(145deg, rgba(12,28,47,.98), rgba(7,17,30,.98))",
    boxShadow: active ? `0 0 20px ${C.cyan}20, inset 0 0 24px ${C.cyan}0b` : "none",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    textAlign: "center",
    color: active ? C.text : "#d7e3f1",
  }}>
    <div style={{ color: active ? C.cyan : "#a6bfdc", marginBottom: 10 }}>
      <DashboardIcon kind={isPortable ? "handheld" : "monitor"} size={38} />
    </div>
    <div style={{ fontSize: 18, fontWeight: 760, marginBottom: 6 }}>{name}</div>
    <div style={{ fontSize: 12, lineHeight: "16px", color: C.muted, minHeight: 32 }}>{detail}</div>
    <div style={{ marginTop: 10, color: active ? C.cyan : C.muted, fontSize: 12, fontWeight: 700 }}>
      {active ? "ACTIVE" : loading ? "READING…" : "Not active"}
    </div>
  </div>;
}

export function QuickAccessOverview({ mode, modeLabel, health, game, loading }: {
  mode: string; modeLabel: string; health: string; game: string; loading: boolean;
}) {
  const cards = placementCards(mode, loading);
  return <div style={{ color: C.text, minWidth: 0 }}>
    <BrandHeader />
    <CurrentStateCard modeLabel={modeLabel} health={health} game={game} loading={loading} />
    <div style={{
      color: C.muted,
      fontSize: 11,
      fontWeight: 760,
      letterSpacing: "1.6px",
      margin: "2px 2px 8px",
    }}>YOUR SETUP</div>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
      {cards.map((card) => <ModeCard key={card.name} {...card} loading={loading} />)}
    </div>
  </div>;
}
