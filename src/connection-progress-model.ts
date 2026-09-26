import type { LiveStatus } from "./connection-live-status";
import type { ConnectionProgressPhase, ConnectionProgressRow } from "./connection-progress-overlay";

export const MILESTONE_LABELS = ["Detect eGPU", "Load GPU driver", "Verify connection", "Find TV", "Prepare and switch display"] as const;
export type MilestoneState = "done" | "active" | "pending" | "attention" | "stale";
export type Milestone = {label: string; state: MilestoneState};
export type MilestoneModel = {
  /** 0-based position of the current milestone; -1 when the stage is unknown. */
  activeStep: number;
  /** Milestones observed complete, kept when stale so assistive text matches "Last observed". */
  observedDone: number;
  /** Accessible progress text; stale history is never described as current. */
  progressText: string;
  steps: Milestone[];
  headline: string;
  currentDetail: string;
  complete: boolean;
  stale: boolean;
  attention: boolean;
  /** Presentation-only attention threshold, not a measured performance claim. */
  slowNotice?: string;
};

// The observed workflow position, as the backend reports it. Milestones are
// presentation of that position, not proof of display output, audio, unplug
// safety or GPU identity. Stages absent here never advance anything.
const STAGE_STEP: Record<string, number> = {
  waiting_for_pci: 0,
  transport_detected: 1,
  waiting_for_driver: 1,
  waiting_for_link: 2,
  waiting_for_hdmi: 3,
  ready_display_pending: 3,
  waiting_for_audio: 4,
  waiting_for_session: 4,
  stabilizing: 4,
  ready_idle: 4,
  // Emitted only after driver, link, HDMI, audio and session readiness pass;
  // the game is the last prerequisite before display preparation.
  game_running: 4,
};
// Stages that report a problem at a known position: the reason stays the
// backend's, and the milestone shows attention instead of progress.
const ATTENTION_STEP: Record<string, number> = {link_training_failed: 2};
const ATTENTION_STAGES = new Set(["link_training_failed", "action_required", "game_running"]);
export const SLOW_NOTICE_SECONDS = 30;


const compactDetail: Record<string, string> = {
  "Waiting for eGPU detection": "Detecting eGPU",
  "Waiting for GPU driver": "Loading GPU driver",
  "Waiting for connection link": "Checking eGPU link",
  "Waiting for TV HDMI": "Looking for TV",
  "Checking audio recovery": "Checking audio",
  "Waiting for display integration": "Preparing display",
  "Checking connection stability": "Checking connection",
};

/** Pure mapping from observed stages to milestones: no I/O, timers or inference. */
export function connectionMilestones(status: LiveStatus & {displayPending?: boolean}, now = Date.now()): MilestoneModel {
  const fresh = now < status.expiresAt;
  const complete = fresh && status.phase === "complete";
  const switching = fresh && status.phase === "switching";
  const stage = status.stage ?? "";
  // Any current blocked prerequisite (game running, retained journal, a
  // blocked check) is attention; the copy stays the backend-derived title.
  const prerequisiteBlocked = status.rows.some(row => row.state === "blocked");
  const attention = fresh && !complete && (ATTENTION_STAGES.has(stage) || prerequisiteBlocked);
  const activeStep = complete ? MILESTONE_LABELS.length
    : status.phase === "switching" ? 4
    : stage in ATTENTION_STEP ? ATTENTION_STEP[stage]
    : stage in STAGE_STEP ? STAGE_STEP[stage] : -1;
  const steps: Milestone[] = MILESTONE_LABELS.map((label, index) => {
    const state: MilestoneState = activeStep < 0 ? "pending"
      : index < activeStep ? "done"
      : index === activeStep ? (attention ? "attention" : "active")
      : "pending";
    // Stale evidence is history: nothing stays green or animated as current.
    return {label, state: fresh ? state : state === "pending" ? "pending" : "stale"};
  });
  const reason = compactDetail[status.title] ?? status.title;
  const known = activeStep >= 0 && activeStep < MILESTONE_LABELS.length;
  const headline = !fresh ? "Waiting for a fresh update"
    : complete ? "Connected to TV"
    : attention ? "Action required"
    : switching ? "Switching to TV" : "Connecting eGPU";
  const currentDetail = !fresh
    ? known ? `Last observed: ${MILESTONE_LABELS[activeStep]}` : "No recent status"
    : complete ? "Check picture and sound on the TV"
    : known ? `Step ${activeStep + 1} of ${MILESTONE_LABELS.length} · ${reason}`
    : reason || "Checking connection";
  const slowNotice = fresh && !complete && !attention && !status.displayPending
    && Number.isFinite(status.seconds) && status.seconds >= SLOW_NOTICE_SECONDS
    ? "Slower than usual · Keep the eGPU connected" : undefined;
  const observedDone = activeStep < 0 ? 0 : Math.min(activeStep, MILESTONE_LABELS.length);
  const progressText = !fresh
    ? known ? `Status stale. Last observed at step ${activeStep + 1} of ${MILESTONE_LABELS.length}: ${MILESTONE_LABELS[activeStep]}`
      : "Status stale. No milestone observed"
    : currentDetail;
  return {activeStep, observedDone, progressText, steps, headline, currentDetail, complete, stale: !fresh, attention, slowNotice};
}

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
  return {phase, rows, delayNotice, milestones: connectionMilestones(status, now),
    activationNotice: !fresh ? "TV status is unavailable. Waiting for a fresh update."
      : status.phase !== "complete" ? "TV activation is not yet confirmed. This popup will close after the TV switch is confirmed." : undefined,
    elapsedSeconds:status.seconds,
    deviceLabel:!fresh ? "eGPU status unavailable"
      : status.connected ? `${status.gpuName ?? "eGPU"} detected` : "Waiting for eGPU",
    detail:!fresh ? "Refreshing status" : phase === "ready"
      ? "TV switch complete. Check picture and sound. Closing automatically…" : compactDetail[status.title] ?? status.title,
    keepConnectedMessage:"Keep eGPU connected · Hide keeps docking active.",
  };
}
