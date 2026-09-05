import type { AutomaticDockStatusPayload, SnapshotPayload } from "./backend";
import type { ConnectionProgressPhase, ConnectionProgressRow } from "./connection-progress-overlay";

export type ConnectionProgressViewModel = {
  phase: ConnectionProgressPhase;
  deviceLabel: string;
  rows: ConnectionProgressRow[];
  detail: string;
  keepConnectedMessage: string;
};

function rowState(value: boolean | null | undefined, pendingLabel = "Checking"): Pick<ConnectionProgressRow, "state" | "stateLabel"> {
  if (value === true) return { state: "ready", stateLabel: "Ready" };
  if (value === false) return { state: "checking", stateLabel: pendingLabel };
  return { state: "checking", stateLabel: pendingLabel };
}

export function connectionProgressViewModel(
  payload: SnapshotPayload | null,
  automaticDock: AutomaticDockStatusPayload | null,
): ConnectionProgressViewModel {
  const snapshot = payload?.snapshot;
  const externalGpu = snapshot?.gpus.find((gpu) => gpu.role === "external" && gpu.present);
  const externalDisplay = snapshot?.displays.find((display) => display.kind === "external" && display.connected === true);
  const gameIdle = snapshot?.game_state === "idle";
  const previousResultClear = !snapshot?.blockers.some((blocker) => (
    blocker.code.includes("journal") || blocker.code.includes("transition")
  ));

  const phase: ConnectionProgressPhase = payload?.inference.mode === "tv_docked"
    || automaticDock?.stage === "docked"
      ? "ready"
      : automaticDock?.stage === "switching"
        ? "switching"
        : "connecting";

  const gpuReady = Boolean(
    externalGpu?.present
    && externalGpu.confidence !== "unknown"
    && snapshot?.support_tier === "certified",
  );
  const linkReady = Boolean(
    snapshot?.egpu_link.applicable
    && snapshot.egpu_link.state === "up"
    && snapshot.egpu_link.confidence !== "unknown",
  );
  const hdmiReady = Boolean(
    externalDisplay?.connected
    && externalDisplay.edid_ready
    && externalDisplay.confidence !== "unknown",
  );
  const audioReady = Boolean(payload?.health?.components.some((item) => (
    item.component.toLowerCase().includes("audio") && item.state === "ready"
  )));
  const displayReady = payload?.inference.mode === "tv_docked"
    || Boolean(externalDisplay?.active && externalDisplay.confidence === "verified");

  const rows: ConnectionProgressRow[] = [
    { key: "gpu", label: "GPU and driver", ...rowState(gpuReady) },
    { key: "link", label: "Connection link", ...rowState(linkReady) },
    { key: "hdmi", label: "TV HDMI detected", ...rowState(hdmiReady) },
    { key: "audio", label: "Audio recovery ready", ...rowState(audioReady) },
    {
      key: "display",
      label: "Display switching ready",
      ...(phase === "switching" && !displayReady
        ? { state: "switching" as const, stateLabel: "Switching" }
        : rowState(displayReady)),
    },
    { key: "game", label: gameIdle ? "No game running" : "Game state", ...rowState(gameIdle, "Checking") },
    { key: "previous", label: "Previous result cleared", ...rowState(previousResultClear, "Checking") },
  ];

  if (phase === "ready") {
    return {
      phase,
      deviceLabel: "GPD G1 connected",
      rows: [
        { key: "display", label: "TV display", state: "ready", stateLabel: "Ready" },
        { key: "audio", label: "TV audio", ...rowState(audioReady) },
      ],
      detail: "Picture and TV output are verified.",
      keepConnectedMessage: "Ready to play.",
    };
  }

  if (phase === "switching") {
    return {
      phase,
      deviceLabel: "Readiness checks complete",
      rows: [
        { key: "display", label: "Display activation", state: displayReady ? "ready" : "switching", stateLabel: displayReady ? "Ready" : "Switching" },
        { key: "audio", label: "TV audio", ...rowState(audioReady, "Next") },
        { key: "final", label: "Final verification", state: displayReady && audioReady ? "ready" : "pending", stateLabel: displayReady && audioReady ? "Ready" : "Next" },
      ],
      detail: "Re-Gear is switching the active display path.",
      keepConnectedMessage: "Keep G1 connected · Hide keeps docking active.",
    };
  }

  const detail = !externalGpu
    ? "Waiting for G1 detection."
    : !linkReady
      ? "Waiting for the eGPU connection link."
      : !hdmiReady
        ? "Waiting for the TV HDMI connection."
        : "Finishing readiness checks.";

  return {
    phase,
    deviceLabel: externalGpu ? "GPD G1 connected" : "GPD G1 connection",
    rows,
    detail,
    keepConnectedMessage: "Keep G1 connected · Hide keeps docking active.",
  };
}
