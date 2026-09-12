import type { ReactNode } from "react";
import type { DetailTone } from "./detail-ui";

const toneColor: Record<DetailTone, string> = {
  neutral: "#d8ebf7",
  active: "#39d8ff",
  success: "#49e6b1",
  warning: "#ffc247",
  error: "#ff7a7a",
  unavailable: "#9fb4c7",
};

/** Presentation-only building blocks for interactive nested Command Center views.
 * Runtime owners provide actual buttons/inputs/actions through children/props;
 * these components deliberately own no hardware, RPC, or persistence behavior.
 */
export function CommandControlRow({ label, value, detail, tone = "neutral", control }: {
  label: string; value?: string; detail?: string; tone?: DetailTone; control?: ReactNode;
}) {
  return <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: "4px 10px", alignItems: "center", minWidth: 0, padding: "6px 0" }}>
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 11.5, fontWeight: 650, color: "#e5f3fb", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</div>
      {detail && <div style={{ marginTop: 2, fontSize: 9.5, lineHeight: 1.3, color: "#91b7d1" }}>{detail}</div>}
    </div>
    <div style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "flex-end", minWidth: 0 }}>
      {value && <strong style={{ fontSize: 12, color: toneColor[tone], whiteSpace: "nowrap" }}>{value}</strong>}
      {control}
    </div>
  </div>;
}

export function CommandRangePreview({ value, min = 0, max = 100, tone = "active", label }: {
  value: number; min?: number; max?: number; tone?: DetailTone; label?: string;
}) {
  const span = Math.max(1, max - min);
  const percent = Math.max(0, Math.min(100, ((value - min) / span) * 100));
  return <div aria-label={label} style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 6, alignItems: "center", minWidth: 110 }}>
    <div style={{ height: 6, borderRadius: 999, background: "#173347", overflow: "hidden", boxShadow: "inset 0 0 0 1px #2d5268" }}>
      <div style={{ width: `${percent}%`, height: "100%", borderRadius: 999, background: toneColor[tone] }}/>
    </div>
    <span style={{ fontSize: 10, color: toneColor[tone], minWidth: 28, textAlign: "right" }}>{Math.round(value)}</span>
  </div>;
}

export function CommandSegmentedPreview({ options, selected }: { options: readonly string[]; selected: string }) {
  return <div role="group" aria-label="Selection preview" style={{ display: "flex", gap: 4, flexWrap: "wrap", justifyContent: "flex-end" }}>
    {options.map(option => <span key={option} data-selected={option === selected ? "true" : "false"} style={{ padding: "4px 7px", borderRadius: 7, border: `1px solid ${option === selected ? "#39d8ff" : "#315f79"}`, background: option === selected ? "#0c4058" : "#0a2030", color: option === selected ? "#55e0ff" : "#b7d8ed", fontSize: 9.5, fontWeight: option === selected ? 700 : 500 }}>{option}</span>)}
  </div>;
}

export function CommandTogglePreview({ enabled, unavailable = false }: { enabled: boolean; unavailable?: boolean }) {
  const active = enabled && !unavailable;
  return <span aria-label={unavailable ? "Unavailable" : active ? "On" : "Off"} style={{ position: "relative", display: "inline-block", width: 34, height: 18, borderRadius: 999, border: `1px solid ${unavailable ? "#496072" : active ? "#39d8ff" : "#49677a"}`, background: unavailable ? "#1b2b37" : active ? "#0b526d" : "#132b3a", opacity: unavailable ? .65 : 1 }}>
    <span style={{ position: "absolute", top: 2, left: active ? 17 : 2, width: 12, height: 12, borderRadius: "50%", background: unavailable ? "#8095a5" : active ? "#55e0ff" : "#a8bfd0", transition: "left .12s ease" }}/>
  </span>;
}

export function CommandProgressSteps({ steps, activeIndex }: { steps: readonly string[]; activeIndex: number }) {
  return <div style={{ display: "grid", gap: 6 }}>
    {steps.map((step, index) => {
      const done = index < activeIndex;
      const active = index === activeIndex;
      const color = done ? "#49e6b1" : active ? "#39d8ff" : "#7895a8";
      return <div key={step} style={{ display: "grid", gridTemplateColumns: "18px minmax(0,1fr)", alignItems: "center", gap: 7, minWidth: 0 }}>
        <span aria-hidden="true" style={{ width: 14, height: 14, borderRadius: "50%", border: `1px solid ${color}`, background: done ? "#123b31" : active ? "#0d3a4f" : "#112431", boxShadow: active ? "0 0 0 3px #39d8ff16" : "none" }}/>
        <span style={{ fontSize: 10.5, color: active ? "#e5f6ff" : done ? "#c5eadf" : "#91a9b9", fontWeight: active ? 700 : 500 }}>{step}</span>
      </div>;
    })}
  </div>;
}
