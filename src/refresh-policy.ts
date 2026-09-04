export const DISCOVERY_REFRESH_MS = 1_000;
export const SETTLING_REFRESH_MS = 750;
export const STABLE_REFRESH_MS = 3_000;
export const ACTIVE_GAME_REFRESH_MS = 5_000;
export const BACKGROUND_REFRESH_MS = 5_000;

export interface RefreshPolicyPayload {
  snapshot: {
    support_tier: string;
    game_state: string;
    gpus: Array<{
      role: string;
      present: boolean;
      confidence: string;
    }>;
    displays: Array<{
      kind: string;
      connected: boolean | null;
      active: boolean | null;
      edid_ready: boolean | null;
      confidence: string;
    }>;
    gamescope: {
      running: boolean | null;
      confidence: string;
    };
    disconnect_readiness: {
      scan_complete: boolean;
    };
    sleep_guard: {
      required: boolean;
      active: boolean;
      confidence: string;
    };
    egpu_link: {
      applicable: boolean;
      state: "up" | "down" | "unknown";
      confidence: string;
    };
    blockers: Array<{ code: string; message: string }>;
  };
  inference: {
    mode: string;
  };
  diagnostics?: {
    hardware_profiles?: {
      egpu?: {
        status: "exact" | "absent" | "unknown";
      };
    };
  };
}

export interface ConnectionProgress {
  label: string;
  detail: string;
  settling: boolean;
}

function firstHardwareBlocker(payload: RefreshPolicyPayload): string {
  const blocker = payload.snapshot.blockers.find((item) => (
    item.code === "egpu_identity_unverified"
    || item.code === "drm_inventory_unavailable"
    || item.code === "active_display_unknown"
    || item.code === "render_gpu_unknown"
    || item.code === "gamescope_unverified"
    || item.code === "render_selector_conflict"
    || item.code === "game_state_unknown"
  ));
  return blocker?.message ?? "Waiting for complete hardware evidence.";
}

function exactEgpuState(payload: RefreshPolicyPayload): "exact" | "absent" | "unknown" {
  const profile = payload.diagnostics?.hardware_profiles?.egpu?.status;
  const external = payload.snapshot.gpus.filter((gpu) => (
    gpu.role === "external" && gpu.present && gpu.confidence === "verified"
  ));
  if (profile === "exact" && external.length === 1) {
    return "exact";
  }
  return profile === "absent" ? "absent" : "unknown";
}

export function connectionProgress(
  payload: RefreshPolicyPayload | null,
): ConnectionProgress {
  if (!payload) {
    return { label: "Checking hardware", detail: "Reading current state.", settling: true };
  }

  const { snapshot, inference } = payload;
  const egpu = exactEgpuState(payload);
  if (egpu === "absent") {
    return {
      label: "eGPU not detected",
      detail: "Current read-only evidence has not detected a supported eGPU.",
      settling: false,
    };
  }
  if (egpu !== "exact") {
    return {
      label: "eGPU evidence unavailable",
      detail: "Waiting for current exact eGPU profile evidence.",
      settling: true,
    };
  }
  if (snapshot.support_tier !== "certified") {
    return {
      label: "eGPU verification blocked",
      detail: firstHardwareBlocker(payload),
      settling: true,
    };
  }
  if (
    snapshot.egpu_link.applicable !== true
    || snapshot.egpu_link.state !== "up"
    || snapshot.egpu_link.confidence !== "observed"
  ) {
    return {
      label: snapshot.egpu_link.applicable && snapshot.egpu_link.state === "down"
        ? "eGPU link needs attention"
        : "eGPU link needs verification",
      detail: "Re-Gear is preserving the current setup. Verify the display and controls before changing it.",
      settling: true,
    };
  }

  const external = snapshot.displays.filter(
    (display) => display.kind === "external" && display.connected === true,
  );
  if (external.length === 0) {
    return {
      label: "eGPU detected",
      detail: "Waiting for a connected TV output.",
      settling: false,
    };
  }
  if (
    external.length !== 1
    || external[0].edid_ready !== true
    || external[0].active === null
    || external[0].confidence !== "verified"
  ) {
    return {
      label: "TV initializing",
      detail: "Waiting for one verified connector, EDID, and active-output result.",
      settling: true,
    };
  }
  if (inference.mode === "tv_docked") {
    return {
      label: "TV Docked",
      detail: "The live render GPU and TV output are verified.",
      settling: false,
    };
  }
  if (external[0].active === true) {
    return {
      label: "Dock verification blocked",
      detail: firstHardwareBlocker(payload),
      settling: true,
    };
  }
  if (
    snapshot.gamescope.running !== true
    || snapshot.gamescope.confidence !== "verified"
  ) {
    return {
      label: "Dock verification blocked",
      detail: firstHardwareBlocker(payload),
      settling: true,
    };
  }
  return {
    label: "Ready to dock",
    detail: "G1 and TV evidence are ready. Use Switch to TV now, or enable automatic TV docking.",
    settling: false,
  };
}

export function refreshDelayForSnapshot(
  payload: RefreshPolicyPayload | null,
): number {
  if (!payload) {
    return SETTLING_REFRESH_MS;
  }
  const { snapshot } = payload;
  if (snapshot.game_state === "running") {
    return ACTIVE_GAME_REFRESH_MS;
  }
  if (snapshot.game_state === "unknown") {
    return STABLE_REFRESH_MS;
  }
  const progress = connectionProgress(payload);
  if (
    progress.settling
    || !snapshot.disconnect_readiness.scan_complete
    || snapshot.sleep_guard.confidence === "unknown"
    || (snapshot.sleep_guard.required && !snapshot.sleep_guard.active)
  ) {
    return SETTLING_REFRESH_MS;
  }
  return progress.label === "TV Docked" ? STABLE_REFRESH_MS : DISCOVERY_REFRESH_MS;
}

/**
 * Keep the always-rendered Decky panel out of the player's way while Quick
 * Access is closed. Backend sleep protection remains independently active, and
 * reopening Quick Access immediately re-enters the ordinary adaptive cadence.
 */
export function refreshDelayForVisibility(
  payload: RefreshPolicyPayload | null,
  quickAccessVisible: boolean,
): number {
  return quickAccessVisible
    ? refreshDelayForSnapshot(payload)
    : BACKGROUND_REFRESH_MS;
}
