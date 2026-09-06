import type { AutomaticDockStatusPayload } from "./backend";
import type {
  ConnectionProgress,
} from "./refresh-policy";
import type {
  ConnectionProgressPhase,
  ConnectionProgressRow,
} from "./connection-progress-overlay";

export type ConnectionProgressModalModel = {
  phase: ConnectionProgressPhase;
  deviceLabel: string;
  rows: ConnectionProgressRow[];
  detail: string;
  keepConnectedMessage: string;
};

function tvState(progress: ConnectionProgress): ConnectionProgressRow {
  if (progress.label === "TV Docked") {
    return { key: "tv", label: "TV HDMI detected", state: "ready" };
  }
  if (progress.label === "Ready to dock") {
    return { key: "tv", label: "TV HDMI detected", state: "ready" };
  }
  if (progress.label === "eGPU detected") {
    return {
      key: "tv",
      label: "TV HDMI detected",
      state: "pending",
      stateLabel: "Waiting for TV",
    };
  }
  return { key: "tv", label: "TV HDMI detected", state: "checking" };
}

export function connectionProgressModalModel(
  progress: ConnectionProgress,
  automatic: AutomaticDockStatusPayload | null,
): ConnectionProgressModalModel {
  const stage = automatic?.stage ?? "observing";
  const docked = progress.label === "TV Docked" || stage === "docked";
  const switching = stage === "switching";
  const gpuReady = ![
    "Checking hardware",
    "eGPU not detected",
    "eGPU evidence unavailable",
    "eGPU verification blocked",
    "eGPU link needs attention",
    "eGPU link needs verification",
  ].includes(progress.label);

  return {
    phase: docked ? "ready" : switching ? "switching" : "connecting",
    deviceLabel: "G1 and TV connection",
    rows: [
      {
        key: "gpu",
        label: "G1 GPU and driver",
        state: gpuReady ? "ready" : "checking",
        stateLabel: gpuReady ? "Connected" : "Checking",
      },
      tvState(progress),
      {
        key: "automatic",
        label: "Automatic TV connection",
        state: docked ? "ready" : switching ? "switching" : stage === "action_required" ? "blocked" : "pending",
        stateLabel: docked ? "TV active" : switching ? "Switching" : stage === "action_required" ? "Needs attention" : "Waiting",
      },
    ],
    detail: progress.detail,
    keepConnectedMessage: docked
      ? "TV output is verified."
      : "This window can be hidden. Re-Gear keeps observing in the background and will retry when the saved TV appears.",
  };
}
