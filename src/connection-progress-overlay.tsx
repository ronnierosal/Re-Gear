import type { ReactNode } from "react";

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
};

const C = {
  bg: "#07111f",
  panel: "#0b1727",
  panel2: "#0d1c2f",
  border: "rgba(135, 166, 199, 0.30)",
  borderStrong: "rgba(69, 207, 255, 0.55)",
  text: "#f4f7fb",
  muted: "#9fb1c8",
  cyan: "#39d8ff",
  green: "#71e35d",
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
    return (
      <span aria-hidden="true" style={{ width: 24, height: 24, borderRadius: 999, border: `2px solid ${C.green}`, display: "grid", placeItems: "center", color: C.green, fontWeight: 900, fontSize: 15 }}>
        ✓
      </span>
    );
  }

  if (state === "blocked" || state === "error") {
    return (
      <span aria-hidden="true" style={{ width: 24, height: 24, borderRadius: 999, border: `2px solid ${stateColor[state]}`, display: "grid", placeItems: "center", color: stateColor[state], fontWeight: 900, fontSize: 15 }}>
        !
      </span>
    );
  }

  return (
    <span
      aria-hidden="true"
      className={state === "checking" || state === "switching" ? "regear-progress-spinner" : undefined}
      style={{ width: 22, height: 22, borderRadius: 999, border: "3px solid rgba(255,255,255,.18)", borderTopColor: stateColor[state], boxSizing: "border-box", flexShrink: 0 }}
    />
  );
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

  return (
    <div style={{ width: "min(1120px, 92vw)", maxHeight: "84vh", overflow: "hidden", padding: 22, borderRadius: 22, background: `linear-gradient(180deg, ${C.bg} 0%, #081321 100%)`, border: `1px solid ${C.borderStrong}`, boxShadow: "0 24px 80px rgba(0,0,0,.52)", color: C.text, fontFamily: "Motiva Sans, Inter, system-ui, sans-serif" }}>
      <style>{`
        @keyframes regear-spin { to { transform: rotate(360deg); } }
        .regear-progress-spinner { animation: regear-spin 1s linear infinite; }
        @media (prefers-reduced-motion: reduce) { .regear-progress-spinner { animation: none; } }
      `}</style>

      <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 8, minWidth: 0 }}>
        <div style={{ color: C.cyan, fontWeight: 900, fontSize: 30, letterSpacing: "-0.02em" }}>Re-Gear</div>
        <div style={{ color: C.muted, fontSize: 28 }}>/</div>
        <div style={{ fontSize: 28, fontWeight: 700 }}>Connection progress</div>
      </div>
      <div style={{ color: C.muted, fontSize: 17, marginBottom: 18 }}>Live feedback from plug-in to TV</div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16, marginBottom: 18 }}>
        {["Connecting", "Switching", "Ready"].map((name, i) => {
          const active = i === activeIndex;
          const complete = i < activeIndex;
          return (
            <div key={name}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, color: active ? C.text : C.muted, marginBottom: 10 }}>
                <span style={{ color: complete || active ? C.cyan : C.muted, fontWeight: 800, fontSize: 18 }}>0{i + 1}</span>
                <span style={{ fontWeight: active ? 800 : 600, fontSize: 18 }}>{name}</span>
              </div>
              <div style={{ height: 4, borderRadius: 999, background: complete ? C.cyan : active ? `linear-gradient(90deg, ${C.cyan} 0 58%, rgba(105,130,155,.35) 58%)` : "rgba(105,130,155,.30)" }} />
            </div>
          );
        })}
      </div>

      <div style={{ border: `1px solid ${C.border}`, borderRadius: 18, background: `linear-gradient(180deg, ${C.panel} 0%, ${C.panel2} 100%)`, padding: "22px 24px" }}>
        <div style={{ fontSize: 31, fontWeight: 850, letterSpacing: "-0.02em", marginBottom: 4 }}>{headline(props.phase)}</div>
        <div style={{ color: C.muted, fontSize: 18, marginBottom: 18 }}>{props.deviceLabel}{elapsed}</div>

        <div style={{ border: `1px solid ${C.border}`, borderRadius: 14, overflow: "hidden", background: "rgba(4,10,18,.30)" }}>
          {props.rows.map((row, index) => (
            <div key={row.key} style={{ minHeight: 50, padding: "0 16px", display: "grid", gridTemplateColumns: "42px 1fr auto", alignItems: "center", gap: 10, borderBottom: index === props.rows.length - 1 ? "none" : `1px solid ${C.border}` }}>
              <div style={{ color: C.text, opacity: .96 }}>{row.icon ?? ""}</div>
              <div style={{ fontSize: 18, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{row.label}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, color: stateColor[row.state], fontWeight: 700, fontSize: 17, whiteSpace: "nowrap" }}>
                <StatusGlyph state={row.state} />
                <span>{row.stateLabel ?? (row.state === "ready" ? "Ready" : row.state === "checking" ? "Checking" : row.state === "switching" ? "Switching" : row.state === "pending" ? "Next" : row.state === "blocked" ? "Blocked" : "Error")}</span>
              </div>
            </div>
          ))}
        </div>

        {props.detail && <div style={{ marginTop: 14, color: C.muted, fontSize: 17 }}>{props.detail}</div>}
        {props.keepConnectedMessage && <div style={{ marginTop: 6, color: C.muted, fontSize: 16 }}>{props.keepConnectedMessage}</div>}

        <button onClick={props.onHide} style={{ marginTop: 18, width: "100%", minHeight: 54, borderRadius: 12, border: `2px solid ${C.cyan}`, background: "rgba(6,18,30,.66)", color: C.text, fontSize: 20, fontWeight: 750, cursor: "pointer" }}>
          Hide
        </button>
      </div>
    </div>
  );
}

export const connectionProgressMockRows: ConnectionProgressRow[] = [
  { key: "gpu", label: "GPU and driver", state: "checking" },
  { key: "link", label: "Connection link", state: "checking" },
  { key: "hdmi", label: "TV HDMI detected", state: "checking" },
  { key: "audio", label: "Audio recovery ready", state: "checking" },
  { key: "display", label: "Display switching ready", state: "checking" },
  { key: "game", label: "No game running", state: "ready" },
  { key: "previous", label: "Previous result cleared", state: "ready" },
];
