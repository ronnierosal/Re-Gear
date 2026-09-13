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

const popupStyles = `
@keyframes regearPopupPulse{0%,100%{transform:scale(.92);opacity:.58}50%{transform:scale(1.08);opacity:1}}
@media (prefers-reduced-motion: reduce){[data-regear-popup-active]{animation:none!important}}
[data-regear-popup-footer]{display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:8px 12px;border-top:1px solid #294f68;background:#061521;flex-wrap:wrap}
[data-regear-popup-footer]>*{min-width:0;max-width:100%}
@media(max-width:620px){[data-regear-popup-layer]{padding:16px!important}[data-regear-popup]{width:min(520px,calc(100vw - 32px))!important;max-height:min(500px,calc(100vh - 32px))!important}}
@media(max-width:430px){[data-regear-popup-layer]{padding:10px!important}[data-regear-popup]{width:calc(100vw - 20px)!important;max-height:calc(100vh - 20px)!important}[data-regear-popup-footer]{justify-content:stretch;gap:6px}[data-regear-popup-footer]>*{flex:1 1 100%}}
@media(max-height:520px){[data-regear-popup-layer]{padding:10px!important}[data-regear-popup]{max-height:calc(100vh - 20px)!important}[data-regear-popup-body]{padding:9px!important}[data-regear-popup-footer]{padding:6px 9px;gap:6px}}
`;

/** Shared presentation shell for Re-Gear popups. Runtime owners provide state,
 * actions and dismissal; they should not invent a second modal visual system. */
export function ReGearPopup({ title, status, tone = "neutral", elapsed, children, footer }: {
  title: string; status?: string; tone?: DetailTone; elapsed?: string; children: ReactNode; footer?: ReactNode;
}) {
  const color = toneColor[tone];
  return <div data-regear-popup-layer style={{ position: "fixed", inset: 0, display: "grid", placeItems: "center", padding: 24, pointerEvents: "none", zIndex: 1000 }}>
    <style>{popupStyles}</style>
    <section data-regear-popup style={{ width: "min(560px,calc(100vw - 48px))", maxHeight: "min(520px,calc(100vh - 48px))", display: "grid", gridTemplateRows: "auto minmax(0,1fr) auto", overflow: "hidden", border: "1px solid #315c75", borderRadius: 14, background: "linear-gradient(145deg,#102536f7,#061520fa 62%,#04101afa)", boxShadow: "0 18px 55px #0009", color: "#f4f7fb", pointerEvents: "auto" }}>
      <header style={{ display: "grid", gridTemplateColumns: "auto minmax(0,1fr) auto", alignItems: "center", gap: 9, padding: "10px 12px", borderBottom: "1px solid #294f68" }}>
        <span data-regear-popup-active={tone === "active" ? "true" : undefined} style={{ display: "grid", placeItems: "center", width: 30, height: 30, borderRadius: 8, border: `1px solid ${color}66`, color, background: "#0a2232", animation: tone === "active" ? "regearPopupPulse 1.1s ease-in-out infinite" : undefined }}><CommandCenterIcon id={toneIcon[tone]} size={19}/></span>
        <span style={{ minWidth: 0 }}><strong style={{ display: "block", fontSize: 14, lineHeight: 1.2 }}>{title}</strong>{status && <small style={{ display: "block", marginTop: 2, color, fontSize: 10.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{status}</small>}</span>
        {elapsed && <span style={{ color: "#8fb3cc", fontSize: 10, whiteSpace: "nowrap" }}>{elapsed}</span>}
      </header>
      <div data-regear-popup-body style={{ minHeight: 0, overflow: "auto", padding: 12, scrollbarWidth: "thin", scrollbarColor: "#315f78 #061724" }}>{children}</div>
      {footer && <footer data-regear-popup-footer>{footer}</footer>}
    </section>
  </div>;
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
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color, fontSize: 10, fontWeight: 700 }}>
      <span data-regear-popup-active={active ? "true" : undefined} style={{ display: "inline-grid", placeItems: "center", animation: active ? "regearPopupPulse 1.1s ease-in-out infinite" : undefined }}><CommandCenterIcon id={toneIcon[active ? "active" : tone]} size={14}/></span>
      {value}
    </span>
  </div>;
}

export function PopupDetailsToggle({ children }: { children: ReactNode }) {
  return <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid #24475d", color: "#91b7d1", fontSize: 10 }}>{children}</div>;
}
