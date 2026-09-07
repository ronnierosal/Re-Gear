import { DialogButton } from "@decky/ui";
import type { DialogButtonProps } from "@decky/ui";
import { DashboardIcon } from "./quick-access-overview";

type DashboardActionProps = Pick<DialogButtonProps, "onClick" | "disabled"> & {
  title: string;
  description: string;
  icon: Parameters<typeof DashboardIcon>[0]["kind"];
  expanded?: boolean;
  tone?: "normal" | "primary" | "warning";
};

/** Re-Gear action card: one controller focus target with mockup-style hierarchy. */
export function DashboardAction({ title, description, icon, expanded, onClick, disabled, tone = "normal" }: DashboardActionProps) {
  const primary = tone === "primary";
  const warning = tone === "warning";
  const accent = warning ? "#ffc247" : primary ? "#39d8ff" : "#35d6ff";
  return <DialogButton onClick={onClick} disabled={disabled} className="rg-dashboard-action" aria-expanded={expanded}
    style={{
      width: "100%", minWidth: 0, height: "auto", minHeight: 68, margin: 0,
      padding: "12px 13px", boxSizing: "border-box", borderRadius: 16,
      textAlign: "left", whiteSpace: "normal",
      background: warning
        ? "linear-gradient(135deg, rgba(65,47,15,.92), rgba(10,22,37,.98))"
        : primary
          ? "linear-gradient(135deg, rgba(8,56,81,.94), rgba(8,24,41,.98))"
          : "linear-gradient(135deg, rgba(19,36,58,.96), rgba(9,21,36,.98))",
      border: `1px solid ${disabled ? "#344457" : warning ? "#9d7635" : primary ? "#2c89a6" : "#2c4663"}`,
      boxShadow: disabled ? "none" : `inset 0 1px 0 rgba(255,255,255,.025), 0 0 20px ${accent}0a`,
    }}>
    <span style={{ display: "grid", gridTemplateColumns: "38px minmax(0,1fr) 18px", alignItems: "center", gap: 11, width: "100%", minWidth: 0 }}>
      <span style={{
        display: "flex", alignItems: "center", justifyContent: "center", width: 38, height: 38,
        borderRadius: 11, color: disabled ? "#687b91" : accent,
        background: disabled ? "rgba(25,37,51,.62)" : `${accent}14`,
        border: `1px solid ${disabled ? "#344457" : `${accent}66`}`,
      }}><DashboardIcon kind={icon} /></span>
      <span style={{ display: "block", minWidth: 0, whiteSpace: "normal", wordBreak: "normal", overflowWrap: "normal", lineHeight: 1.3 }}>
        <span style={{ display: "block", fontSize: 14, fontWeight: 760, color: disabled ? "#8394a7" : primary || warning ? accent : "#f2f7ff" }}>{title}</span>
        <span style={{ display: "block", fontSize: 12, marginTop: 3, color: disabled ? "#708093" : "#9fb2ca" }}>{description}</span>
      </span>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
        style={{ opacity: disabled ? .35 : .75, color: warning || primary ? accent : undefined, transform: expanded ? "rotate(90deg)" : undefined, transition: "transform 120ms ease" }}>
        <path d="m9 5 7 7-7 7" />
      </svg>
    </span>
  </DialogButton>;
}
