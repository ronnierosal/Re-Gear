import type { ReactNode } from "react";
import { CommandCenterIcon, type CommandCenterIconId } from "../command-center-icons";
import type { DetailTone } from "./detail-ui";

const toneIcon: Record<DetailTone, CommandCenterIconId> = {
  neutral: "status-unknown",
  active: "status-unknown",
  success: "status-ok",
  warning: "status-warning",
  error: "status-error",
  unavailable: "status-unknown",
};
const toneColor: Record<DetailTone, string> = {
  neutral: "#d8ebf7",
  active: "#39d8ff",
  success: "#49e6b1",
  warning: "#ffc247",
  error: "#ff7a7a",
  unavailable: "#9fb4c7",
};

/** Shared presentation shell for Re-Gear popups. Runtime owners provide state,
 * actions and dismissal; they should not invent a second modal visual system. */
export function ReGearPopup({ title, status, tone = "neutral", elapsed, children, footer }: {
  title: string; status?: string; tone?: DetailTone; elapsed?: string; children: ReactNode; footer?: ReactNode;
}) {
  const color = toneColor[tone];
  return <section data-regear-popup style={{ width: "min(620px,calc(100vw - 48px))", maxHeight: "min(560px,calc(100vh - 48px))", display: "grid", gridTemplateRows: "auto minmax(0,1fr) auto", overflow: "hidden", border: "1px solid #315c75", borderRadius: 14, background: "linear-gradient(145deg,#102536f7,#061520fa 62%,#04101afa)", boxShadow: "0 18px 55px #0009", color: "#f4f7fb" }}>
    <header style={{ display: "grid", gridTemplateColumns: "auto minmax(0,1fr) auto", alignItems: "center", gap: 9, padding: "10px 12px", borderBottom: "1px solid #294f68" }}>
      <span style={{ display: "grid", placeItems: "center", width: 30, height: 30, borderRadius: 8, border: `1px solid ${color}66`, color, background: "#0a2232" }}><CommandCenterIcon id={toneIcon[tone]} size={19}/></span>
      <span style={{ minWidth: 0 }}><strong style={{ display: "block", fontSize: 14, lineHeight: 1.2 }}>{title}</strong>{status && <small style={{ display: "block", marginTop: 2, color, fontSize: 10.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{status}</small>}</span>
      {elapsed && <span style={{ color: "#8fb3cc", fontSize: 10, whiteSpace: "nowrap" }}>{elapsed}</span>}
    </header>
    <div data-regear-popup-body style={{ minHeight: 0, overflow: "auto", padding: 12, scrollbarWidth: "thin", scrollbarColor: "#315f78 #061724" }}>{children}</div>
    {footer && <footer style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8, padding: "8px 12px", borderTop: "1px solid #294f68", background: "#061521" }}>{footer}</footer>}
  </section>;
}

export function PopupStatusList({ children }: { children: ReactNode }) {
  return <div style={{ display: "grid", gap: 4 }}>{children}</div>;
}

export function PopupStatusRow({ label, value, tone = "neutral", active = false }: {
  label: string; value: string; tone?: DetailTone; active?: boolean;
}) {
  const color = toneColor[tone];
  return <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", alignItems: "center", gap: 10, minHeight: 30, padding: "5px 7px", borderRadius: 8, background: active ? "#0c3145" : "transparent" }}>
    <span style={{ fontSize: 10.5, color: active ? "#e9f7ff" : "#c8deeb", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{label}</span>
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color, fontSize: 10, fontWeight: 700 }}><CommandCenterIcon id={toneIcon[tone]} size={14}/>{value}</span>
  </div>;
}

export function PopupDetailsToggle({ children }: { children: ReactNode }) {
  return <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid #24475d", color: "#91b7d1", fontSize: 10 }}>{children}</div>;
}
