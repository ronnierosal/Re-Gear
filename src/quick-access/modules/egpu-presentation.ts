/** eGPU module presentation: pure, no React, no I/O, no requests.
 *
 * The safety rule this file exists to enforce is in AGENTS.md: physical
 * connection, render GPU, display target, Gamescope session and running-game
 * state are INDEPENDENT. Each reading below is derived from exactly one source
 * and never from another. A link that is up does not mean the eGPU is
 * rendering; a connected external display does not mean it is active; a
 * present GPU does not mean it was selected. Collapsing any of those into one
 * "eGPU: connected" line is the failure this module is built to prevent,
 * because a player acts on it and the device does not agree.
 *
 * Two further rules:
 *
 * - Unknown fails closed. Absent or unverified evidence renders as unknown and
 *   never as a working state, and confidence is carried so the page can say
 *   "observed" rather than implying a verified reading.
 * - Nothing here claims a disconnect is safe. Re-Gear cannot confirm live
 *   removal, so `disconnect` reports what is known and always refuses the
 *   claim, whatever the readings say. That refusal is not conditional.
 *
 * `model_name` is documented in the payload as presentation only, never a
 * readiness or identity input, so it is shown only when a single external GPU
 * is reported and never used in any decision here.
 */

import type { SnapshotPayload } from "../../backend";

export type Evidence = {
  /** Player-facing text. "Unknown" whenever evidence is absent or unusable. */
  text: string;
  /** False when this is an absence of evidence rather than a reading. */
  known: boolean;
  /** True only for a payload that reported `verified` confidence. */
  verified: boolean;
};

const UNKNOWN: Evidence = { text: "Unknown", known: false, verified: false };

function evidence(text: string | null, confidence?: string): Evidence {
  if (text === null) return UNKNOWN;
  return { text, known: true, verified: confidence === "verified" };
}

/** Absent evidence, for a caller with nothing yet to grade. */
export const UNKNOWN_EVIDENCE: Evidence = UNKNOWN;

/** Which panel is being driven, graded by the observation's own confidence.
 *
 * Display target is one of the independent readings this module exists to
 * keep apart, so it is derived from `active` alone and never from
 * attachment. It belongs here rather than at the call site: a second copy of
 * this mapping is a second copy of the safety argument, and the one that
 * drifts is the one nobody is reading.
 *
 * Two panels reported active is mirrored output, which is a third answer
 * rather than "External" -- naming one of two driven panels hides the other
 * exactly when a player is deciding whether the TV is live.
 *
 * The grade is the weakest confidence among the entries the answer rests on,
 * because an answer is only as verified as its least verified input. */
export function displayTargetEvidence(
  displays: SnapshotPayload["snapshot"]["displays"] | null | undefined,
): Evidence {
  const driven = (displays ?? []).filter((display) => display.active === true
    && (display.kind === "external" || display.kind === "internal"));
  if (driven.length === 0) return UNKNOWN;
  const external = driven.some((display) => display.kind === "external");
  const internal = driven.some((display) => display.kind === "internal");
  return {
    text: external && internal ? "External + handheld" : external ? "External" : "Handheld",
    known: true,
    verified: driven.every((display) => display.confidence === "verified"),
  };
}

export type EgpuPresentation = {
  /** Physical link only. Says nothing about rendering or display. */
  connection: Evidence;
  /** Which GPU was selected for render. Independent of the link. */
  renderGpu: Evidence;
  /** External display attachment, independent of whether it is active. */
  displayConnected: Evidence;
  /** Whether that display is actually driving output. */
  displayActive: Evidence;
  /** Gamescope session, independent of everything above. */
  session: Evidence;
  /** Running-game state, independent of everything above. */
  game: Evidence;
  /** Driver-reported name, presentation only. Null unless unambiguous. */
  model: string | null;
  /** Where the connection lifecycle currently is. */
  lifecycle: Evidence;
  /** Always refuses a safe-removal claim. */
  disconnect: { text: string; safeClaim: false; reason: string };
  /** Recovery must stay reachable even when readings are stale. */
  recovery: { reachable: true; note: string | null };
};

const LINK_TEXT: Record<string, string> = { up: "Link up", down: "Link down" };

const LIFECYCLE_TEXT: Record<string, string> = {
  disconnected: "Disconnected",
  transport_detected: "Transport detected",
  waiting_for_pci: "Waiting for PCI",
  waiting_for_driver: "Waiting for driver",
  waiting_for_link: "Waiting for link",
  waiting_for_hdmi: "Waiting for display",
  waiting_for_audio: "Waiting for audio",
  waiting_for_session: "Waiting for session",
  game_running: "Game running",
  stabilizing: "Stabilizing",
  ready_idle: "Ready",
  link_training_failed: "Link training failed",
  timed_out: "Timed out",
  action_required: "Needs attention",
};

function bool(value: boolean | null | undefined, yes: string, no: string): string | null {
  return value === true ? yes : value === false ? no : null;
}

export function egpuPresentation(payload: SnapshotPayload | null | undefined): EgpuPresentation {
  const snapshot = payload?.snapshot;
  const link = snapshot?.egpu_link;
  const gpus = snapshot?.gpus ?? [];
  const displays = snapshot?.displays ?? [];
  const external = gpus.filter((gpu) => gpu.role === "external");
  const externalDisplays = displays.filter((display) => display.kind === "external");

  // Each of the following reads exactly one source. Deliberately no cross-use.
  const connection = link && link.applicable
    ? evidence(LINK_TEXT[link.state] ?? null, link.confidence)
    : UNKNOWN;

  const rendering = external.find((gpu) => gpu.selected_for_render === true);
  const renderGpu = external.length === 0 ? UNKNOWN
    : rendering ? evidence("External GPU", rendering.confidence)
    : external.some((gpu) => gpu.selected_for_render === false)
      ? evidence("Internal GPU", external[0].confidence)
      : UNKNOWN;

  const connectedDisplay = externalDisplays[0];
  const displayConnected = connectedDisplay
    ? evidence(bool(connectedDisplay.connected, "Connected", "Not connected"), connectedDisplay.confidence)
    : UNKNOWN;
  const displayActive = connectedDisplay
    ? evidence(bool(connectedDisplay.active, "Active", "Not active"), connectedDisplay.confidence)
    : UNKNOWN;

  const session = snapshot?.gamescope
    ? evidence(bool(snapshot.gamescope.running, "Running", "Not running"), snapshot.gamescope.confidence)
    : UNKNOWN;

  const game = snapshot?.game_state
    ? evidence(snapshot.game_state === "idle" ? "No game running" : "Game running")
    : UNKNOWN;

  // Presentation only. One unambiguous external GPU, or nothing.
  const model = external.length === 1 && typeof external[0].model_name === "string"
    && external[0].model_name.trim() !== "" ? external[0].model_name : null;

  const stage = payload?.connection_readiness?.stage;
  const lifecycle = stage ? evidence(LIFECYCLE_TEXT[stage] ?? null) : UNKNOWN;

  return {
    connection, renderGpu, displayConnected, displayActive, session, game, model, lifecycle,
    // Unconditional. No combination of readings turns this into a safe claim,
    // because Re-Gear cannot confirm live removal is safe.
    disconnect: {
      text: "Not confirmed",
      safeClaim: false,
      reason: "Re-Gear cannot confirm that disconnecting now is safe. Shut down before unplugging.",
    },
    // Recovery is the control a player needs precisely when readings are stale
    // or missing, so it is never gated on fresh evidence.
    recovery: {
      reachable: true,
      note: connection.known ? null : "Readings are unavailable; recovery is still available.",
    },
  };
}
