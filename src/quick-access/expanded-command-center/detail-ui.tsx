import type { CSSProperties, ReactNode } from "react";
import { CommandCenterIcon, type CommandCenterIconId } from "../command-center-icons";

/**
 * Shared presentation-only primitives for nested Command Center surfaces.
 *
 * Runtime owners may compose these with live state/actions, but must not fork
 * their own visual system. This file intentionally imports no backend, RPC,
 * Decky action API, or hardware code.
 */

export type DetailTone = "neutral" | "active" | "success" | "warning" | "error" | "unavailable";

const toneColor: Record<DetailTone, string> = {
  neutral: "#d8ebf7",
  active: "#39d8ff",
  success: "#49e6b1",
  warning: "#ffc247",
  error: "#ff7a7a",
  unavailable: "#9fb4c7",
};

const surface: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
  minWidth: 0,
};

const section: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 7,
  minWidth: 0,
  padding: 10,
  border: "1px solid #315f79",
  borderRadius: 10,
  background: "linear-gradient(150deg,#102b3d,#0a2030 58%,#071827)",
};

export function CommandDetailSurface({ children }: { children: ReactNode }) {
  return <div style={surface}>{children}</div>;
}

export function CommandSection({ title, hint, children }: { title?: string; hint?: string; children: ReactNode }) {
  return <section style={section}>
    {title && <div style={{ fontSize: 12, fontWeight: 700, color: "#f4f7fb" }}>{title}</div>}
    {hint && <div style={{ fontSize: 10.5, lineHeight: 1.35, color: "#9ec0d7" }}>{hint}</div>}
    {children}
  </section>;
}

export function CommandStatusRow({
  label,
  value,
  tone = "neutral",
  icon,
  detail,
}: {
  label: string;
  value: string;
  tone?: DetailTone;
  icon?: CommandCenterIconId;
  detail?: string;
}) {
  return <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", alignItems: "center", gap: "3px 10px", minWidth: 0, padding: "4px 0" }}>
    <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, fontSize: 11.5, color: "#dbeef9" }}>
      {icon && <CommandCenterIcon id={icon} size={17}/>}<span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
    </span>
    <strong style={{ fontSize: 11.5, color: toneColor[tone], whiteSpace: "nowrap" }}>{value}</strong>
    {detail && <small style={{ gridColumn: "1 / -1", fontSize: 9.5, lineHeight: 1.3, color: "#91b7d1" }}>{detail}</small>}
  </div>;
}

export function CommandNotice({
  tone = "neutral",
  title,
  children,
}: {
  tone?: DetailTone;
  title: string;
  children?: ReactNode;
}) {
  const color = toneColor[tone];
  return <div style={{ padding: "8px 10px", border: `1px solid ${color}55`, borderRadius: 9, background: "#071b2a", color: "#dbeef9" }}>
    <div style={{ fontSize: 11.5, fontWeight: 700, color }}>{title}</div>
    {children && <div style={{ marginTop: 3, fontSize: 10, lineHeight: 1.35, color: "#9ec0d7" }}>{children}</div>}
  </div>;
}

export function CommandActionRow({ children }: { children: ReactNode }) {
  return <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>{children}</div>;
}

export function CommandValue({ label, value, tone = "neutral" }: { label: string; value: string; tone?: DetailTone }) {
  return <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
    <span style={{ fontSize: 9.5, color: "#91b7d1" }}>{label}</span>
    <strong style={{ fontSize: 16, lineHeight: 1.2, color: toneColor[tone], overflow: "hidden", textOverflow: "ellipsis" }}>{value}</strong>
  </div>;
}
