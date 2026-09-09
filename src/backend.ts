import { callable } from "@decky/api";

export interface BlockerPayload {
  code: string;
  message: string;
}

export interface GpuPayload {
  /** Optional driver-reported presentation; never a readiness/identity input. */
  model_name?: string;
  role: "internal" | "external" | "unknown";
  present: boolean;
  selected_for_render: boolean | null;
  confidence: "unknown" | "observed" | "verified";
}

export interface DisplayPayload {
  kind: "internal" | "external" | "unknown";
  connected: boolean | null;
  active: boolean | null;
  edid_ready: boolean | null;
  confidence: "unknown" | "observed" | "verified";
}

export interface EgpuClientPayload {
  name: string;
  kind: "game" | "user" | "protected" | "system" | "unknown";
  resources: Array<
    | "drm_card"
    | "drm_render"
    | "drm_control"
    | "audio_pcm"
    | "audio_control"
    | "audio_hardware"
  >;
  close_eligible: boolean;
  reason: string;
}

export interface DisconnectReadinessPayload {
  applicable: boolean;
  scan_complete: boolean;
  ready: boolean;
  clients: EgpuClientPayload[];
  storage_devices: number;
  storage_in_use: boolean;
  error: string;
}

export interface SleepGuardPayload {
  required: boolean;
  active: boolean;
  confidence: "unknown" | "observed" | "verified";
  reason: string;
  error: string;
}

export interface EgpuLinkPayload {
  applicable: boolean;
  state: "up" | "down" | "unknown";
  confidence: "unknown" | "observed" | "verified";
  reason: string;
  error: string;
  speed_gtps?: number | null;
  width_lanes?: number | null;
}

export type ProfileResolutionStatus = "exact" | "absent" | "unknown";

export type HardwareCapabilityAxis =
  | "egpu_support"
  | "egpu_transport"
  | "external_display_output"
  | "display_handoff"
  | "external_audio_output"
  | "audio_handoff"
  | "internal_controller_suppression"
  | "external_controller_promotion"
  | "external_controller_disconnect"
  | "external_controller_power_off"
  | "power_button_interception"
  | "sleep_behavior"
  | "removal_behavior";

export interface HardwareCapabilityDiagnostic {
  axis: HardwareCapabilityAxis;
  value: string;
  confidence: "unknown" | "observed" | "verified";
  basis:
    | "exact_host_profile"
    | "exact_egpu_profile"
    | "composed_exact_profiles"
    | "incomplete_profile_set";
}

export interface HardwareProfileDiagnostics {
  schema_version: number;
  host: {
    status: ProfileResolutionStatus;
    profile_id: string;
  };
  egpu: {
    status: ProfileResolutionStatus;
    profile_id: string;
  };
  capabilities: HardwareCapabilityDiagnostic[];
}

export interface SnapshotPayload {
  delivery_schema_version: number;
  snapshot: {
    schema_version: number;
    observed_at: string;
    host_profile: string;
    support_tier: string;
    game_state: string;
    gpus: GpuPayload[];
    displays: DisplayPayload[];
    gamescope: {
      running: boolean | null;
      confidence: string;
    };
    disconnect_readiness: DisconnectReadinessPayload;
    sleep_guard: SleepGuardPayload;
    egpu_link: EgpuLinkPayload;
    blockers: BlockerPayload[];
  };
  inference: {
    mode: string;
    reasons: string[];
  };
  health?: {
    state: "ready" | "recovering" | "degraded" | "attention_required";
    components: Array<{
      component: string;
      state: "ready" | "recovering" | "degraded" | "unknown";
      reason: string;
    }>;
    blockers: string[];
  };
  attach_readiness?: {
    schema_version: number;
    stage: "idle" | "settling" | "waiting_for_external_display" | "waiting_for_link_health" | "ready_idle" | "game_running" | "action_required";
    code: string;
    poll_after_ms: number;
  };
  connection_readiness?: {
    schema_version: number;
    stage: "disconnected" | "transport_detected" | "waiting_for_pci" | "waiting_for_driver" | "waiting_for_link" | "waiting_for_hdmi" | "waiting_for_audio" | "waiting_for_session" | "game_running" | "stabilizing" | "ready_idle" | "link_training_failed" | "timed_out" | "action_required";
    code: string;
    poll_after_ms: number;
    window_age_ms: number;
    checks?: Record<"gpu" | "link" | "hdmi" | "audio" | "session" | "idle", boolean> | null;
    checks_age_ms?: number;
  };
  /** Optional future read-only delivery for local journey classifiers. */
  journey?: {
    deferred_dock?: { state: string; code: string };
    prepared_docked_idle?: { state: string; code: string };
    safe_undock?: { state: string; code: string };
    unexpected_removal_recovery?: { state: string; code: string };
    link_instability?: {
      schema_version: number;
      status: "stable_observed" | "instability_observed" | "evidence_insufficient";
      code: string;
      current_state: "up" | "down" | null;
    };
    offline_readiness?: {
      schema_version: number;
      status: "ready_to_try_offline" | "needs_attention" | "online_check_needed" | "unknown";
      reason_codes: string[];
    };
  };
  diagnostics: {
    schema_version: number;
    timings_ms: Array<{
      stage: string;
      duration_ms: number;
    }>;
    overhead_measurement?: {
      schema_version: 1;
      status: "observed" | "deferred" | "evidence_insufficient" | "stale";
      code: string;
      game_impact: "unknown";
      total_cost_ms?: number;
    };
    hardware_profiles: HardwareProfileDiagnostics;
    build?: {
      schema_version: 1;
      version: string;
      revision: string;
      candidate_match?: "current_candidate" | "different_build" | "unavailable";
    };
  };
}

/** How far a live eGPU disconnect could get right now.
 *
 * `ready` means removal safety says so as things stand. `attemptable` means it
 * does not, but the blocker is one the disconnect exists to clear -- holders it
 * is allowed to restart, or an external display it will turn off. Removal
 * safety is assessed before any release and before one it always declines, so
 * a caller that offered the action only on `ready` would tell a player their
 * eGPU can never be disconnected.
 *
 * `attemptable` is not a promise. The attempt can still refuse, with a reason
 * and nothing removed.
 */
export type DisconnectAvailability =
  | "unavailable"
  | "recovery_required"
  | "busy"
  | "blocked"
  | "attemptable"
  | "ready";

export interface DisconnectOutcomePayload {
  schema_version: number;
  stage: string;
  code: string;
  ok: boolean;
  released: boolean;
  /** True when the player's Steam session was restarted to free the device. */
  session_disturbed: boolean;
  removed: string[];
  restored: string[];
  display_released: number[];
  display_release_code: string;
  filter_disarmed: boolean;
  /** The device was left somewhere it has never been. Needs attention, and is
   * not the same as the action having failed. */
  device_disturbed: boolean;
}

/** What the reviewed catalog knows about closing a game.
 *
 * `untested` is the common case and the only honest answer for a game nobody
 * has reported on yet. It must be shown as "Re-Gear does not know", never
 * rounded to reassurance.
 */
export type GameSaveCapability =
  | "untested"
  | "verified_triggerable_autosave"
  | "verified_save_on_exit"
  | "graceful_exit_verified"
  | "manual_save_recommended"
  | "manual_save_required"
  | "unsafe_unknown";

export interface DisconnectGamePayload {
  app_id: string;
  /** From the catalog when it holds this game, otherwise empty. Resolve a
   * display name yourself rather than showing an empty string. */
  title: string;
  save_capability: GameSaveCapability;
  egpu_handoff: string;
  /** False when the catalog has nothing on this game. */
  save_known: boolean;
  /** False when something is rendering that could not be named. Still a game
   * with a save to lose, but nothing that can be matched to a remembered
   * answer or reopened afterwards. */
  identity_exact: boolean;
}

/** What to do before closing whatever is running.
 *
 * `nothing_to_close` is the only value that clears the way without asking, and
 * it is reported only over a scan that finished. A scan that failed reports
 * `confirm` with code `game_close.scan_incomplete`, because not finding a game
 * is evidence only when the looking finished.
 */
export type CloseDecision = "nothing_to_close" | "confirm" | "remembered";

export interface ClosePromptPayload {
  schema_version: number;
  decision: CloseDecision;
  /** Stable reason code. Render through a mapping, never raw. */
  code: string;
  /** The action that is about to end the game. */
  intent: "disconnect" | "sleep";
  /** True when no further player interaction is needed. */
  may_proceed: boolean;
  /** True when the reviewed catalog says closing this game loses progress. */
  progress_at_risk: boolean;
  /** False when the catalog has nothing on this game either way. */
  save_known: boolean;
  /** Whether to offer "do not ask again for this game". Never true for a game
   * with reviewed evidence of losing progress. */
  remember_offered: boolean;
  /** Whether to offer reopening the game afterwards. */
  relaunch_offered: boolean;
  /** Whether the player has already asked for that reopen. */
  relaunch_requested: boolean;
}

export interface DisconnectStatusPayload {
  schema_version: number;
  availability: DisconnectAvailability;
  /** Stable reason code. Render through a mapping, never raw. */
  code: string;
  ready: boolean;
  /** Whether the action may be offered. True for `ready` and `attemptable`. */
  attemptable: boolean;
  busy: boolean;
  /** Units holding the eGPU. Meaningless without `scan_complete`: an empty
   * list from an unfinished scan is not a free device. */
  holders: string[];
  scan_complete: boolean;
  external_display_committed: boolean | null;
  /** The disconnect would turn the external display off. A separate approval
   * from the disconnect itself, because it is visible to whoever is watching. */
  display_release_required: boolean;
  /** The game holding the eGPU, when one is. Null means no game is running
   * *or* its identity could not be established; the `code` says which, and
   * null must not be read as "there is nothing to close". */
  game: DisconnectGamePayload | null;
  /** What to ask before closing that game, and whether the player already
   * answered. This is the field to branch on: `decision` alone says whether to
   * act, ask, or stop. Null only when there is no eGPU at all. */
  close_prompt: ClosePromptPayload | null;
  last: DisconnectOutcomePayload | null;
}

export const getSnapshot = callable<[], SnapshotPayload>("get_snapshot");

export interface PeripheralStatusPayload {
  schema_version: number;
  controller: { complete: boolean; exact: boolean; builtin_available: boolean | null; external_connected: boolean | null; code: string };
  audio: { complete: boolean; exact: boolean; external_available: boolean | null; portable_available: boolean | null; code: string };
}

export const getPeripheralStatus = callable<[], PeripheralStatusPayload>("get_peripheral_status");

export interface ActionHistoryEntryPayload {
  occurred_at: string;
  kind: "topology" | "transition" | "recovery" | "sleep" | "process_release" | "peripheral" | "presentation";
  outcome: "started" | "succeeded" | "recovered" | "blocked" | "failed" | "attention_required";
  code: string;
}

export interface ActionHistoryPayload {
  schema_version: number;
  entries: ActionHistoryEntryPayload[];
}

export const getActionHistory = callable<[], ActionHistoryPayload>("get_action_history");

export interface AutomaticDockStatusPayload {
  schema_version: 1;
  enabled: boolean;
  stage: "disabled" | "observing" | "settling" | "waiting" | "switching" | "docked" | "action_required";
  code: string;
}

export const getAutomaticDockStatus = callable<[], AutomaticDockStatusPayload>(
  "get_automatic_dock_status",
);
export const setAutomaticDockEnabled = callable<
  [boolean, boolean],
  AutomaticDockStatusPayload
>("set_automatic_dock_enabled");

export type DockedIgpuLifecycleStage =
  | "idle"
  | "watching"
  | "promotion_ready"
  | "action_required"
  | "closed";

export interface DockedIgpuStatusPayload {
  schema_version: number;
  stage: DockedIgpuLifecycleStage;
  code: string;
  poll_after_ms: number;
  inspection_available: boolean;
  acknowledgement_required: boolean;
}

export interface DockedIgpuAcknowledgementPayload {
  schema_version: number;
  acknowledged: boolean;
}

export const getDockedIgpuStatus = callable<[], DockedIgpuStatusPayload>(
  "get_docked_igpu_status",
);
export const acknowledgeDockedIgpuStatus = callable<
  [],
  DockedIgpuAcknowledgementPayload
>("acknowledge_docked_igpu_status");

export type DiagnosticLoggingDuration =
  | "30_minutes"
  | "1_hour"
  | "2_hours"
  | "until_reboot";

export interface DiagnosticLoggingStatusPayload {
  schema_version: number;
  enabled: boolean;
  mode: "off" | "ttl" | "until_reboot";
  duration: DiagnosticLoggingDuration | "";
  remaining_seconds: number | null;
  code: string;
}

export const getDiagnosticLoggingStatus = callable<
  [],
  DiagnosticLoggingStatusPayload
>("get_diagnostic_logging_status");
export const enableDiagnosticLogging = callable<
  [DiagnosticLoggingDuration, boolean],
  DiagnosticLoggingStatusPayload
>("enable_diagnostic_logging");
export const disableDiagnosticLogging = callable<
  [],
  DiagnosticLoggingStatusPayload
>("disable_diagnostic_logging");

export interface SupportBundlePreviewPayload {
  schema_version: number;
  preview_token: string;
  preview_json: string;
  size_bytes: number;
  event_count: number;
  manifest: {
    redacted: boolean;
    bounded: boolean;
    contents: string[];
  };
}

export interface SupportBundleSavePayload {
  ok: boolean;
  relative_path: string;
  size_bytes: number;
}

export const previewSupportBundle = callable<[], SupportBundlePreviewPayload>(
  "preview_support_bundle",
);
export const saveSupportBundle = callable<[string], SupportBundleSavePayload>(
  "save_support_bundle",
);

export interface PresentationPreparationPreviewPayload {
  schema_version: number;
  ready: boolean;
  blockers: string[];
  confirmation_required: boolean;
}

export interface PresentationPreparationApprovalPayload {
  schema_version: number;
  approval_token: string;
  ready: boolean;
  blockers: string[];
}

export interface PresentationPreparationOutcomePayload {
  schema_version: number;
  prepared: boolean;
  changed: boolean;
  code: string;
  rollback_attempted: boolean;
  rollback_succeeded: boolean;
}

export const previewPresentationPreparation = callable<
  [],
  PresentationPreparationPreviewPayload
>("preview_presentation_preparation");
export const approvePresentationPreparation = callable<
  [],
  PresentationPreparationApprovalPayload
>("approve_presentation_preparation");
export const preparePresentationIntegration = callable<
  [string],
  PresentationPreparationOutcomePayload
>("prepare_presentation_integration");

export interface SupervisedTvSwitchPreviewPayload {
  schema_version: number;
  ready: boolean;
  blockers: string[];
  confirmation_required: boolean;
}

export interface SupervisedTvSwitchApprovalPayload {
  schema_version: number;
  approval_token: string;
  blockers: string[];
}

export interface SupervisedTvSwitchOutcomePayload {
  schema_version: number;
  accepted: boolean;
  code: string;
  acknowledgement_id: string;
  acknowledgement_required: boolean;
}

export interface SupervisedTvSwitchAcknowledgementPayload {
  schema_version: number;
  acknowledged: boolean;
}

export interface SupervisedTvSwitchStatusPayload {
  schema_version: number;
  code: string;
  acknowledgement_required: boolean;
  action_required: boolean;
  acknowledgement_id: string;
  durable: boolean;
  target: "portable" | "docked_egpu" | "unknown";
}

export const previewSupervisedTvSwitch = callable<
  [],
  SupervisedTvSwitchPreviewPayload
>("preview_supervised_tv_switch");
export const approveSupervisedTvSwitch = callable<
  [],
  SupervisedTvSwitchApprovalPayload
>("approve_supervised_tv_switch");
export const executeSupervisedTvSwitch = callable<
  [string],
  SupervisedTvSwitchOutcomePayload
>("execute_supervised_tv_switch");
export const approveSupervisedPortableSwitch = callable<
  [],
  SupervisedTvSwitchApprovalPayload
>("approve_supervised_portable_switch");
export const executeSupervisedPortableSwitch = callable<
  [string],
  SupervisedTvSwitchOutcomePayload
>("execute_supervised_portable_switch");
export const acknowledgeSupervisedTvSwitch = callable<
  [string],
  SupervisedTvSwitchAcknowledgementPayload
>("acknowledge_supervised_tv_switch");
export const getSupervisedTvSwitchStatus = callable<
  [],
  SupervisedTvSwitchStatusPayload
>("get_supervised_tv_switch_status");

export interface SafeDisconnectShutdownApprovalPayload {
  schema_version: number;
  ready: boolean;
  approval_token: string;
  blockers: string[];
}

export interface SafeDisconnectShutdownOutcomePayload {
  schema_version: number;
  accepted: boolean;
  code: string;
}

export const approveSafeDisconnectShutdown = callable<
  [],
  SafeDisconnectShutdownApprovalPayload
>("approve_safe_disconnect_shutdown");
export const executeSafeDisconnectShutdown = callable<
  [string],
  SafeDisconnectShutdownOutcomePayload
>("execute_safe_disconnect_shutdown");

export type TransitionJournalOwner =
  | "none"
  | "presentation"
  | "process_release"
  | "sleep"
  | "unknown";

export interface TransitionJournalStatusPayload {
  schema_version: number;
  code: string;
  owner: TransitionJournalOwner;
  acknowledgement_required: boolean;
  action_required: boolean;
  acknowledgement_id: string;
  durable: boolean;
}

export interface SleepJournalAcknowledgementPayload {
  schema_version: number;
  acknowledged: boolean;
}

export const getTransitionJournalStatus = callable<
  [],
  TransitionJournalStatusPayload
>("get_transition_journal_status");
export const acknowledgeSleepJournal = callable<
  [string],
  SleepJournalAcknowledgementPayload
>("acknowledge_sleep_journal");

export type ProcessReleasePhase = "graceful" | "force";

export interface ProcessReleaseTargetPayload {
  name: string;
  resources: string[];
}

export interface ProcessReleasePreviewPayload {
  schema_version: number;
  phase: ProcessReleasePhase | "";
  ready: boolean;
  approval_token: string;
  expires_in_seconds: number;
  targets: ProcessReleaseTargetPayload[];
  protected_client_count: number;
  blockers: string[];
  confirmation_required: boolean;
}

export interface ProcessReleaseExecutionPayload {
  schema_version: number;
  accepted: boolean;
  code: string;
  acknowledgement_id: string;
  status: string;
  software_blockers_cleared: boolean;
  hardware_removal_authorized: false;
  remaining_client_count: number | null;
  force_receipt_token: string;
  action_required: boolean;
}

export interface ProcessReleaseStatusPayload {
  schema_version: number;
  code: string;
  acknowledgement_required: boolean;
  action_required: boolean;
  acknowledgement_id: string;
  durable: boolean;
}

export interface ProcessReleaseAcknowledgementPayload {
  schema_version: number;
  acknowledged: boolean;
}

export const getProcessReleaseStatus = callable<[], ProcessReleaseStatusPayload>(
  "get_process_release_status",
);
export const previewProcessRelease = callable<
  [ProcessReleasePhase, string],
  ProcessReleasePreviewPayload
>("preview_process_release");
export const approveProcessRelease = callable<
  [ProcessReleasePhase, string],
  ProcessReleasePreviewPayload
>("approve_process_release");
export const executeProcessRelease = callable<
  [string],
  ProcessReleaseExecutionPayload
>("execute_process_release");
export const acknowledgeProcessRelease = callable<
  [string],
  ProcessReleaseAcknowledgementPayload
>("acknowledge_process_release");

export interface TdpStatusPayload {
  schema_version: 1;
  enabled: boolean;
  can_enable: boolean;
  ready: boolean;
  code: string;
  current_watts: number | null;
  minimum_watts: number | null;
  maximum_watts: number | null;
  restore_available: boolean;
  recovery_required: boolean;
  auto_tdp_available: boolean;
  last_result: null | {
    state: string;
    code: string;
    requested_watts: number | null;
    observed_watts: number | null;
  };
}

export const getTdpStatus = callable<[], TdpStatusPayload>("get_tdp_status");
export const setTdpEnabled = callable<[boolean], TdpStatusPayload>("set_tdp_enabled");
export const applyTdpLimit = callable<[number], TdpStatusPayload>("apply_tdp_limit");
export const restoreTdpLimit = callable<[], TdpStatusPayload>("restore_tdp_limit");

export interface AutoTdpStatusPayload {
  schema_version: 1;
  can_start: boolean;
  enabled: boolean;
  running: boolean;
  stopping: boolean;
  code: string;
  activity_code: string | null;
  target_fps: number | null;
  minimum_watts: number | null;
  maximum_watts: number | null;
}

export const getAutoTdpStatus = callable<[], AutoTdpStatusPayload>("get_auto_tdp_status");
export const startAutoTdp = callable<[number, number, number], AutoTdpStatusPayload>("start_auto_tdp");
export const stopAutoTdp = callable<[], AutoTdpStatusPayload>("stop_auto_tdp");

export interface TdpBenchmarkResult {
  code: string;
  attempts: number;
  usable_samples: number;
  consecutive_samples: number;
  maximum_collection_and_revalidation_ms: number | null;
  elapsed_ms: number;
  interval_ms: number;
}
export interface TdpBenchmarkStatus {
  schema_version: 1;
  running: boolean;
  cancelling: boolean;
  code: string;
  result: TdpBenchmarkResult | null;
}
export const getTdpBenchmarkStatus = callable<[], TdpBenchmarkStatus>("get_auto_tdp_benchmark_status");
export const runTdpBenchmark = callable<[], TdpBenchmarkStatus>("run_auto_tdp_benchmark");
export const cancelTdpBenchmark = callable<[], TdpBenchmarkStatus>("cancel_auto_tdp_benchmark");

export interface AutoTdpSavedPreference {
  placement: string;
  target_fps: number;
  minimum_watts: number;
  maximum_watts: number;
}
export interface AutoTdpPreferencesPayload {
  schema_version: 1;
  code: string;
  preferences: AutoTdpSavedPreference[];
}
export const getAutoTdpPreferences = callable<[], AutoTdpPreferencesPayload>("get_auto_tdp_preferences");
export const saveAutoTdpPreference = callable<[string, number, number, number], AutoTdpPreferencesPayload>("save_auto_tdp_preference");


/** Read-only. Observes and changes nothing, so it is safe to poll. */
export const getEgpuDisconnectStatus = callable<[], DisconnectStatusPayload>(
  "get_egpu_disconnect_status",
);

/** Detach the eGPU in software. NOT clearance to unplug anything.
 *
 * Serialized by the backend: a second call while one runs returns immediately
 * with `live_disconnect.busy` and does nothing.
 *
 * `releaseDisplay` is a separate approval from the disconnect. Pass true only
 * when the player has agreed to the external display turning off.
 *
 * `relaunchAppId` records a wish to reopen one game afterwards, written down
 * by the backend because this panel is about to be destroyed: freeing the
 * device restarts the Steam session. Pass "" for no relaunch. Claim it with
 * `takePendingRelaunch` rather than remembering it here.
 */
export const executeEgpuDisconnect = callable<
  [releaseDisplay: boolean, relaunchAppId?: string],
  DisconnectOutcomePayload
>("execute_egpu_disconnect");

export interface PendingRelaunchPayload {
  /** The game to reopen, or "" when there is none to reopen. */
  steam_app_id: string;
  /** Why. `relaunch.approved`, `relaunch.nothing_recorded`, or a refusal. */
  code: string;
}

/** Claim the game a disconnect closed, if it may still be reopened.
 *
 * Consuming, and consuming on refusal too, so a relaunch that happens cannot
 * happen twice. Call it after a disconnect returns, and again when the panel
 * loads: freeing the eGPU restarts the Steam session, so the panel that asked
 * for the relaunch is usually not the one that gets to perform it.
 */
export const takePendingRelaunch = callable<[], PendingRelaunchPayload>(
  "take_pending_relaunch",
);

export interface GameClosePreferenceResult {
  ok: boolean;
  /** Stable reason code; `game_close.progress_at_risk` when the backend
   * refused to store a skip for a game known to lose progress. */
  code: string;
}

/** Store the player's answer about closing one game before a disconnect.
 *
 * The backend re-derives what may be stored from a fresh status rather than
 * trusting this call, so an answer filed against the wrong game, or a "do not
 * ask again" for a game the catalog says loses progress, is refused rather
 * than written. Check `ok` before telling a player the box was remembered.
 */
export const rememberGameCloseChoice = callable<
  [steamAppId: string, skipConfirmation: boolean, relaunchAfter: boolean],
  GameClosePreferenceResult
>("remember_game_close_choice");

/** Return one game to being asked about before a disconnect. */
export const forgetGameCloseChoice = callable<
  [steamAppId: string],
  GameClosePreferenceResult
>("forget_game_close_choice");
