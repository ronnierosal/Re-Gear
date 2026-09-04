import { DialogButton } from "@decky/ui";
import type { DialogButtonProps } from "@decky/ui";
import { DashboardIcon } from "./quick-access-overview";

type DashboardActionProps = Pick<DialogButtonProps, "onClick" | "disabled"> & {
  title: string;
  description: string;
  icon: Parameters<typeof DashboardIcon>[0]["kind"];
  expanded?: boolean;
};

/** One native focus target; no Item label/action columns or detached icon row. */
export function DashboardAction({ title, description, icon, expanded, onClick, disabled }: DashboardActionProps) {
  return (
    <DialogButton onClick={onClick} disabled={disabled} aria-expanded={expanded}
      style={{
        width: "100%",
        minWidth: 0,
        height: "auto",
        minHeight: 62,
        margin: 0,
        padding: "11px 12px",
        boxSizing: "border-box",
        borderRadius: 14,
        textAlign: "left",
        whiteSpace: "normal",
        background: "linear-gradient(135deg, rgba(19,36,58,.96), rgba(9,21,36,.98))",
        border: "1px solid #2c4663",
        boxShadow: "inset 0 1px 0 rgba(255,255,255,.025)",
      }}>
      <span style={{
        display: "grid",
        gridTemplateColumns: "32px minmax(0, 1fr) 16px",
        alignItems: "center",
        gap: 10,
        width: "100%",
        minWidth: 0,
        boxSizing: "border-box",
      }}>
        <span style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 32,
          height: 32,
          borderRadius: 10,
          color: disabled ? "#687b91" : "#35d6ff",
          background: disabled ? "rgba(25,37,51,.62)" : "rgba(9,58,78,.58)",
          border: `1px solid ${disabled ? "#344457" : "#2b7188"}`,
        }}>
          <DashboardIcon kind={icon} />
        </span>
        <span style={{
          display: "block",
          minWidth: 0,
          whiteSpace: "normal",
          wordBreak: "normal",
          overflowWrap: "normal",
          lineHeight: 1.32,
        }}>
          <span style={{ display: "block", fontSize: 13.5, fontWeight: 700, color: disabled ? "#8394a7" : "#f2f7ff" }}>
            {title}
          </span>
          <span style={{ display: "block", fontSize: 11.5, fontWeight: 400, marginTop: 3,
            color: disabled ? "#708093" : "#9fb2ca" }}>{description}</span>
        </span>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
          style={{ opacity: disabled ? .35 : .72, transform: expanded ? "rotate(90deg)" : undefined,
            transition: "transform 120ms ease" }}>
          <path d="m9 5 7 7-7 7" />
        </svg>
      </span>
    </DialogButton>
  );
}
