import type { LiveStatus } from "./connection-live-status";
import type { ConnectionProgressPhase, ConnectionProgressRow } from "./connection-progress-overlay";

const compactDetail: Record<string, string> = {
  "Waiting for eGPU detection": "Detecting eGPU",
  "Waiting for GPU driver": "Loading GPU driver",
  "Waiting for connection link": "Checking eGPU link",
  "Waiting for TV HDMI": "Looking for TV",
  "Checking audio recovery": "Checking audio",
  "Waiting for display integration": "Preparing display",
  "Checking connection stability": "Checking connection",
};

/** Presentation adapter for the existing monitor: no snapshot inference or I/O. */
export function connectionProgressViewModel(status: LiveStatus & {displayPending?: boolean}, now = Date.now()) {
  const fresh = now < status.expiresAt;
  const phase: ConnectionProgressPhase = !fresh ? "connecting"
    : status.phase === "complete" ? "ready" : status.phase === "switching" ? "switching" : "connecting";
  let rows: ConnectionProgressRow[] = status.rows.map((row, index) => ({
    key: String(index), label: row.label,
    state: !fresh || row.state === "waiting" ? "pending" : row.state,
    stateLabel: !fresh ? "Unavailable" : row.state === "waiting" ? "Waiting"
      : row.state === "ready" ? "Confirmed" : "Attention",
  }));
  if (phase === "switching") rows = [...rows,
    {key:"display",label:"Display activation",state:"switching"},
    {key:"audio",label:"TV audio",state:"pending",stateLabel:"Not verified"},
  ];
  if (phase === "ready") rows = [...rows,
    {key:"display",label:"TV display",state:"ready"},
    // Audio recovery readiness is not proof of active TV audio output.
    {key:"audio",label:"TV audio",state:"pending",stateLabel:"Check sound"},
  ];
  const delayNotice = fresh && !status.displayPending && !rows.some(row=>row.state === "blocked" || row.state === "error") && status.phase !== "complete" && Number.isFinite(status.seconds) && status.seconds >= 60
    ? status.seconds < 180
      ? "Taking longer than expected. Connection may take up to three minutes; completion is not guaranteed."
      : "Still waiting after three minutes. Check the connection and display status below. Keep the eGPU connected."
    : undefined;
  return {phase, rows, delayNotice,
    activationNotice: !fresh ? "TV status is unavailable. Waiting for a fresh update."
      : status.phase !== "complete" ? "TV activation is not yet confirmed. This popup will close after the TV switch is confirmed." : undefined,
    elapsedSeconds:status.seconds,
    deviceLabel:fresh && status.connected ? `${status.gpuName ?? "eGPU"} detected` : "Waiting for eGPU",
    detail:!fresh ? "Refreshing status" : phase === "ready"
      ? "TV switch complete. Check picture and sound. Closing automatically…" : compactDetail[status.title] ?? status.title,
    keepConnectedMessage:"Keep eGPU connected · Hide keeps docking active.",
  };
}
