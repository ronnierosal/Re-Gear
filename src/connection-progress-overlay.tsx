import type { ReactNode } from "react";
import { DialogButton } from "@decky/ui";
import brandIcon from "./assets/regear-icon.svg";

export type ConnectionProgressState = "ready" | "checking" | "pending" | "switching" | "blocked" | "error";
export type ConnectionProgressPhase = "connecting" | "switching" | "ready";

export type ConnectionProgressRow = {
  key: string;
  label: string;
  state: ConnectionProgressState;
  stateLabel?: string;
  icon?: ReactNode;
};

export type ConnectionProgressOverlayProps = {
  phase: ConnectionProgressPhase;
  deviceLabel: string;
  elapsedSeconds?: number;
  rows: ConnectionProgressRow[];
  detail?: string;
  keepConnectedMessage?: string;
  onHide: () => void;
  onSwitch?: () => void;
};

const C = {
  bg: "#06101c",
  panel: "#0a1727",
  panel2: "#0d1b2d",
  row: "rgba(4,11,20,.34)",
  border: "rgba(129,160,193,.30)",
  borderStrong: "rgba(57,216,255,.62)",
  text: "#f4f7fb",
  muted: "#9fb1c8",
  cyan: "#39d8ff",
  green: "#6fe45d",
  amber: "#ffc43d",
  red: "#ff6578",
};

const stateColor: Record<ConnectionProgressState, string> = {
  ready: C.green,
  checking: C.amber,
  pending: C.muted,
  switching: C.cyan,
  blocked: C.amber,
  error: C.red,
};

function StatusGlyph({ state }: { state: ConnectionProgressState }) {
  if (state === "ready") {
    return <span aria-hidden="true" style={{
      width: 23, height: 23, borderRadius: 999, border: `2px solid ${C.green}`,
      display: "grid", placeItems: "center", color: C.green, fontWeight: 900, fontSize: 14,
      boxShadow: `0 0 12px ${C.green}18`, boxSizing: "border-box",
    }}>✓</span>;
  }
  if (state === "blocked" || state === "error") {
    return <span aria-hidden="true" style={{
      width: 23, height: 23, borderRadius: 999, border: `2px solid ${stateColor[state]}`,
      display: "grid", placeItems: "center", color: stateColor[state], fontWeight: 900, fontSize: 14,
      boxSizing: "border-box",
    }}>!</span>;
  }
  return <span aria-hidden="true"
    className={state === "checking" || state === "switching" ? "regear-progress-spinner" : undefined}
    style={{
      width: 22, height: 22, borderRadius: 999, border: "3px solid rgba(255,255,255,.16)",
      borderTopColor: stateColor[state], boxSizing: "border-box", flexShrink: 0,
    }} />;
}

function phaseIndex(phase: ConnectionProgressPhase): number {
  return phase === "connecting" ? 0 : phase === "switching" ? 1 : 2;
}

function headline(phase: ConnectionProgressPhase): string {
  return phase === "connecting" ? "Getting your TV ready" : phase === "switching" ? "Switching to TV" : "Ready to play";
}

export function ConnectionProgressOverlay(props: ConnectionProgressOverlayProps) {
  const activeIndex = phaseIndex(props.phase);
  const elapsed = props.elapsedSeconds != null ? ` · ${props.elapsedSeconds} seconds` : "";

  return <div style={{
    width: "100%", maxWidth: 620, minWidth: 0, boxSizing: "border-box", padding: 14,
    borderRadius: 22, background: `linear-gradient(180deg, ${C.bg} 0%, #071322 100%)`,
    border: `1px solid ${C.borderStrong}`, boxShadow: "0 26px 90px rgba(0,0,0,.58)",
    color: C.text, fontFamily: "Motiva Sans, Inter, system-ui, sans-serif",
  }}>
    <style>{`
      @keyframes regear-spin { to { transform: rotate(360deg); } }
      @keyframes regear-sweep { 0% { opacity:.35; transform:scaleX(.35); transform-origin:left; } 50% { opacity:1; transform:scaleX(.78); transform-origin:left; } 100% { opacity:.35; transform:scaleX(.35); transform-origin:right; } }
      .regear-progress-spinner { animation: regear-spin 1s linear infinite; }
      .regear-progress-sweep { animation: regear-sweep 1.25s ease-in-out infinite; }
      .regear-hide-button:focus { outline: 3px solid rgba(57,216,255,.42); outline-offset: 3px; }
      @media (prefers-reduced-motion: reduce) { .regear-progress-spinner, .regear-progress-sweep { animation: none; } }
    `}</style>

    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 3, minWidth: 0 }}>
      <img src={brandIcon} alt="" aria-hidden="true" width={28} height={28} style={{ objectFit: "contain", flexShrink: 0 }} />
      <div style={{ fontSize: 20, fontWeight: 820, letterSpacing: "-.02em" }}>Re-Gear</div>
      <div style={{ color: C.muted, fontSize: 14, margin: "0 2px" }}>/</div>
      <div style={{ fontSize: 14, fontWeight: 620 }}>Connection progress</div>
    </div>
    <div style={{ color: C.muted, fontSize: 13, margin: "0 0 10px 42px" }}>Live feedback from plug-in to TV</div>

    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 18, marginBottom: 10 }}>
      {["Connecting", "Switching", "Ready"].map((name, i) => {
        const active = i === activeIndex;
        const complete = i < activeIndex;
        return <div key={name}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, color: active ? C.text : C.muted, marginBottom: 10 }}>
            <span style={{ color: complete || active ? C.cyan : C.muted, fontWeight: 820, fontSize: 14 }}>0{i + 1}</span>
            <span style={{ fontWeight: active ? 780 : 600, fontSize: 14 }}>{name}</span>
          </div>
          <div style={{ height: 4, borderRadius: 999, background: "rgba(105,130,155,.28)", overflow: "hidden" }}>
            {(complete || active) && <div className={active && props.phase === "switching" ? "regear-progress-sweep" : undefined}
              style={{ width: "100%", height: "100%", borderRadius: 999, background: C.cyan, boxShadow: `0 0 12px ${C.cyan}66` }} />}
          </div>
        </div>;
      })}
    </div>

    <div style={{
      border: `1px solid ${C.border}`, borderRadius: 18,
      background: `linear-gradient(180deg, ${C.panel} 0%, ${C.panel2} 100%)`, padding: "12px",
    }}>
      <div style={{ fontSize: 20, fontWeight: 830, letterSpacing: "-.02em", marginBottom: 4 }}>{headline(props.phase)}</div>
      <div style={{ color: C.muted, fontSize: 14, marginBottom: 8 }}>{props.deviceLabel}{elapsed}</div>

      {props.phase === "ready" && <div style={{ display: "grid", placeItems: "center", margin: "2px 0 18px" }}>
        <div style={{ width: 88, height: 88, borderRadius: 999, border: `4px solid ${C.green}`, color: C.green, display: "grid", placeItems: "center", fontSize: 52, fontWeight: 500, boxShadow: `0 0 28px ${C.green}18` }}>✓</div>
      </div>}

      <div style={{ border: `1px solid ${C.border}`, borderRadius: 14, overflow: "hidden", background: C.row }}>
        {props.rows.map((row, index) => <div key={row.key} style={{
          minHeight: 27, padding: "4px 8px", display: "grid", gridTemplateColumns: row.icon ? "24px minmax(0,1fr) auto" : "minmax(0,1fr) auto",
          alignItems: "center", gap: 10, borderBottom: index === props.rows.length - 1 ? "none" : `1px solid ${C.border}`,
        }}>
          {row.icon && <div style={{ color: C.text, opacity: .95 }}>{row.icon}</div>}
          <div style={{ fontSize: 14, minWidth: 0, overflowWrap: "anywhere" }}>{row.label}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, color: stateColor[row.state], fontWeight: 700, fontSize: 13, whiteSpace: "nowrap" }}>
            <StatusGlyph state={row.state} />
            <span>{row.stateLabel ?? (row.state === "ready" ? "Ready" : row.state === "checking" ? "Checking" : row.state === "switching" ? "Switching" : row.state === "pending" ? "Next" : row.state === "blocked" ? "Blocked" : "Error")}</span>
          </div>
        </div>)}
      </div>

      {props.detail && <div style={{ marginTop: 15, color: C.muted, fontSize: 13 }}>{props.detail}</div>}
      {props.keepConnectedMessage && <div style={{ marginTop: 6, color: C.muted, fontSize: 14 }}>{props.keepConnectedMessage}</div>}

      <DialogButton className="rg-dashboard-action regear-hide-button" onClick={props.onHide} style={{
        marginTop: 10, width: "100%", minHeight: 36, borderRadius: 12,
        border: `2px solid ${C.cyan}`, background: "rgba(5,16,28,.74)", color: C.text,
        fontSize: 20, fontWeight: 720, cursor: "pointer", boxShadow: `inset 0 0 18px ${C.cyan}08`,
      }}>Hide</DialogButton>
      {props.onSwitch && <DialogButton className="rg-dashboard-action" onClick={props.onSwitch} style={{width:"100%", marginTop:8}}>Switch to TV</DialogButton>}
    </div>
  </div>;
}

