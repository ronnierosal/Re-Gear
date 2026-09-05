import type { LiveStatus } from "./connection-live-status";
import type { ConnectionProgressPhase, ConnectionProgressRow } from "./connection-progress-overlay";

/** Presentation adapter for the existing monitor: no snapshot inference or I/O. */
export function connectionProgressViewModel(status: LiveStatus, now = Date.now()) {
  const fresh = now < status.expiresAt;
  const phase: ConnectionProgressPhase = !fresh ? "connecting"
    : status.phase === "complete" ? "ready" : status.phase === "switching" ? "switching" : "connecting";
  let rows: ConnectionProgressRow[] = status.rows.map((row, index) => ({
    key: String(index), label: row.label,
    state: !fresh ? "pending" : row.state === "waiting" ? "checking" : row.state,
  }));
  if (phase === "switching") rows = [
    {key:"display",label:"Display activation",state:"switching"},
    {key:"audio",label:"TV audio",state:"pending",stateLabel:"Not verified"},
    {key:"final",label:"Final verification",state:"pending",stateLabel:"Next"},
  ];
  if (phase === "ready") rows = [
    {key:"display",label:"TV display",state:"ready"},
    // Audio recovery readiness is not proof of active TV audio output.
    {key:"audio",label:"TV audio",state:"pending",stateLabel:"Check sound"},
  ];
  return {phase, rows, elapsedSeconds:status.seconds,
    deviceLabel:status.connected ? "GPD G1 connected" : "GPD G1 connection",
    detail:!fresh ? "Waiting for a fresh status update" : phase === "ready"
      ? "TV transition reported complete. Check picture and sound. Closing automatically…" : status.title,
    keepConnectedMessage:"Keep G1 connected · Hide keeps docking active.",
  };
}
