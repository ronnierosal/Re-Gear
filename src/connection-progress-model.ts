import type { LiveStatus } from "./connection-live-status";
import type { ConnectionProgressPhase, ConnectionProgressRow } from "./connection-progress-overlay";

/** Presentation adapter for the existing monitor: no snapshot inference or I/O. */
export function connectionProgressViewModel(status: LiveStatus, now = Date.now()) {
  const fresh = now < status.expiresAt;
  const phase: ConnectionProgressPhase = !fresh ? "connecting"
    : status.phase === "complete" ? "ready" : status.phase === "switching" ? "switching" : "connecting";
  let rows: ConnectionProgressRow[] = status.rows.map((row, index) => ({
    key: String(index), label: row.label,
    state: !fresh || row.state === "waiting" ? "pending" : row.state,
    stateLabel: !fresh ? "Status unavailable" : row.state === "waiting" ? "Waiting for confirmation"
      : row.state === "ready" ? "Confirmed" : "Needs attention",
  }));
  if (phase === "switching") rows = [
    {key:"display",label:"Display activation",state:"switching"},
    {key:"audio",label:"TV audio",state:"pending",stateLabel:"Not verified"},
  ];
  if (phase === "ready") rows = [
    {key:"display",label:"TV display",state:"ready"},
    // Audio recovery readiness is not proof of active TV audio output.
    {key:"audio",label:"TV audio",state:"pending",stateLabel:"Check sound"},
  ];
  const delayNotice = fresh && status.phase !== "complete" && Number.isFinite(status.seconds) && status.seconds >= 60
    ? status.seconds < 180
      ? "Taking longer than expected. Still waiting for connection or display confirmation. Allow up to three minutes, then check the status below; completion is not guaranteed."
      : "Still waiting after three minutes. Check the connection and display status below. Keep the eGPU connected."
    : undefined;
  return {phase, rows, delayNotice,
    activationNotice: !fresh ? "TV status is unavailable. Waiting for a fresh update."
      : status.phase !== "complete" ? "TV activation is not yet confirmed. This popup will close after the TV switch is confirmed." : undefined,
    elapsedSeconds:status.seconds,
    deviceLabel:`${fresh && status.gpuName ? status.gpuName : "eGPU"} ${fresh && status.connected ? "connected" : "connection"}`,
    detail:!fresh ? "Waiting for a fresh status update" : phase === "ready"
      ? "TV transition reported complete. Check picture and sound. Closing automatically…" : status.title,
    keepConnectedMessage:"Keep eGPU connected · Hide keeps docking active.",
  };
}
