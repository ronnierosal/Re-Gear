import { SectionFocus } from "../section-focus";
import type { ReactNode, Ref } from "react";
import type { Route } from "./module-registry";

type Pages = {
  route: Route;
  commandCenter: ReactNode;
  modules: ReactNode;
  egpu: ReactNode;
  autoTdp: ReactNode;
  controller: ReactNode;
  egpuStatus: ReactNode;
  controllerStatus: ReactNode;
  troubleshoot: ReactNode;
  picker?: ReactNode;
};

/** Exactly one destination is mounted. Configuration never trails the grid. */
export function PageLayout(p: Pages): ReactNode {
  switch (p.route.kind) {
    case "command-center": return p.commandCenter;
    case "modules": return p.modules;
    case "picker": return p.picker ?? null;
    case "troubleshoot": return p.troubleshoot;
    case "status": return p.route.id === "egpu" ? p.egpuStatus : p.controllerStatus;
    case "module":
      switch (p.route.id) {
        case "egpu": return p.egpu;
        case "auto-tdp": return p.autoTdp;
        case "controller": return p.controller;
      }
  }
}

export function CommandCenterHeader({ mode, display, game, health, navigation, summaryRef, onSummaryFocus }: {
  mode: string; display: string; game: string; health: string; navigation: ReactNode;
  summaryRef?: Ref<HTMLDivElement>; onSummaryFocus?(): void;
}) {
  return <div style={{ minWidth: 0, marginBottom: 12, color: "#f4f7fb" }}>
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 10 }}>
      <span style={{ fontSize: 15, fontWeight: 700, minWidth: 0 }}>Command Center</span>
      {navigation}
    </div>
    <SectionFocus ref={summaryRef} label="Command Center: current state" onFocused={onSummaryFocus}>
    <div style={{ border: "1px solid #294665", borderRadius: 12, padding: "10px 12px", background: "#0a1727", overflowWrap: "anywhere" }}>
      <div style={{ fontSize: 16, fontWeight: 700 }}>{mode}</div>
      <div style={{ fontSize: 12, lineHeight: "18px", color: "#9eb2ca" }}>{display} · {game}</div>
      {health !== "Ready" && <div style={{ fontSize: 12, lineHeight: "18px", color: "#ffc247" }}>{health}</div>}
    </div>
    </SectionFocus>
  </div>;
}
