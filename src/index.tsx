import { connectionLiveStatus } from "./connection-live-status";
import { startConnectionMonitor } from "./connection-monitor";
import { showConnectionLivePanel } from "./connection-live-panel";
import { PRODUCT_NAME } from "./branding";
import { startControllerSafeDisconnect, steamControllerInput } from "./controller-safe-disconnect";
import { startOfflineFocusChecks } from "./offline-focus-checks";
import brandIcon from "../docs/images/re-gear-decky-white-transparent.png";
import { definePlugin, toaster, useQuickAccessVisible } from "@decky/api";
import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Focusable,
  ToggleField,
  PanelSection,
  PanelSectionRow,
  ScrollPanel,
  showModal,
  staticClasses,
} from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  acknowledgeDockedIgpuStatus,
  acknowledgeSleepJournal,
  getSnapshot,
  getPeripheralStatus,
  getActionHistory,
  getAutomaticDockStatus,
  setAutomaticDockEnabled,
  acknowledgeProcessRelease,
  approveProcessRelease,
  approvePresentationPreparation,
  approveSafeDisconnectShutdown,
  approveSupervisedPortableSwitch,
  approveSupervisedTvSwitch,
  acknowledgeSupervisedTvSwitch,
  executeSupervisedTvSwitch,
  getSupervisedTvSwitchStatus,
  getTransitionJournalStatus,
  executeProcessRelease,
  executeSafeDisconnectShutdown,
  executeSupervisedPortableSwitch,
  getProcessReleaseStatus,
  getDockedIgpuStatus,
  getDiagnosticLoggingStatus,
  enableDiagnosticLogging,
  disableDiagnosticLogging,
  preparePresentationIntegration,
  previewPresentationPreparation,
  previewProcessRelease,
  previewSupportBundle,
  saveSupportBundle,
  type SnapshotPayload,
  type DockedIgpuStatusPayload,
  type DiagnosticLoggingDuration,
  type DiagnosticLoggingStatusPayload,
  type PeripheralStatusPayload,
  type ActionHistoryPayload,
  type AutomaticDockStatusPayload,
  type ProcessReleasePhase,
  type ProcessReleasePreviewPayload,
  type SupportBundlePreviewPayload,
  type TransitionJournalStatusPayload,
} from "./backend";
import { createDeckySteamSuspendAdapter } from "./decky-steam-suspend";
import { deliverBlockedAttempt } from "./blocked-attempt-delivery";
import { diagnosticOverlayRows } from "./diagnostics-overlay";
import { DashboardSurface, QuickAccessOverview } from "./quick-access-overview";
import { DashboardAction } from "./dashboard-action";
import { hardwareDetailRows } from "./quick-access-dashboard";
import { healthAttentionMessages, healthStatusLabel } from "./health-ui";
import { decideLinkHealthNotification } from "./link-health-notification";
import { sanitizeJourneyStatus } from "./journey-status-delivery";
import {
  compactJourneyStatusRows,
  compactStatusPanels,
  quickAccessSectionVisibility,
  revealJourneyDetails,
  journeyStatusRows,
  restoreQuickAccessFocus,
} from "./quick-access-ui";
import {
  collectOptionalDiagnostics,
  shouldCollectOptionalDiagnostics,
} from "./optional-diagnostics-refresh";
import { connectionProgress, refreshDelayForVisibility } from "./refresh-policy";
import { canOfferForce, processReleaseOutcomeMessage } from "./process-release-ui";
import {
  SleepPreflightCoordinator,
  observationFromSnapshotEvidence,
  type BlockedAttemptWarning,
  type PreflightObservation,
} from "./sleep-preflight";


const LABELS: Record<string, string> = {
  "journal.foreign_workflow": "Another workflow needs attention",
  "automatic_dock.rearmed_after_acknowledgement": "Re-checking attachment",
  "automatic_dock.suppressed_for_safe_disconnect": "Waiting for G1 removal",
  "connection.disconnected": "Waiting for G1",
  "connection.waiting_for_pci": "G1 detected; starting GPU",
  "connection.waiting_for_driver": "Waiting for G1 graphics driver",
  "connection.waiting_for_link": "Waiting for G1 PCIe link",
  "connection.waiting_for_hdmi": "Waiting for G1 HDMI",
  "connection.waiting_for_audio": "Waiting for G1 TV audio",
  "connection.waiting_for_session": "Preparing Steam session",
  "connection.game_running": "Waiting for game to close",
  "connection.stabilizing": "Checking G1 connection stability",
  "connection.late_enumeration_detected": "G1 GPU appeared; checking connection",
  "connection.ready_idle": "G1 ready for TV",
  "connection.transport_dropped_before_pci": "G1 USB4 connection dropped while starting",
  "connection.verified_absence_required": "Power off and disconnect G1 before retrying",
  "connection.readiness_timed_out": "G1 did not become ready",
  "connection.game_state_unknown": "Game state could not be verified",
  boosted_handheld: "Boosted Handheld",
  certified: "Certified",
  degraded: "Degraded",
  experimental: "Experimental",
  game: "Game",
  idle: "No game running",
  portable: "Portable",
  running: "Game running",
  protected: "Protected",
  system: "System",
  tv_docked: "TV Docked",
  unknown: "Unknown",
  unsupported: "Unsupported",
  user: "User",
};

const SLEEP_WARNING_KEY = "hdm.hideAttachedEgpuSleepWarning";
const LEGACY_SLEEP_WARNING_KEY = "hdm.hideAttachedG1SleepWarning";
const SNAPSHOT_STALE_AFTER_MS = 10_000;
const BLOCKED_ATTEMPT_MODAL_DELAY_MS = 750;
const DIAGNOSTIC_LOGGING_OPTIONS = [
  { data: "30_minutes", label: "30 minutes" },
  { data: "1_hour", label: "1 hour" },
  { data: "2_hours", label: "2 hours" },
  { data: "until_reboot", label: "Until reboot" },
] satisfies Array<{ data: DiagnosticLoggingDuration; label: string }>;

function scrollToTopOfOwningPanel(anchor: HTMLElement): void {
  // A Decky quick-access plugin is hosted inside Steam's scroll container, not
  // the browser window. Find that container rather than assuming a particular
  // Steam class name (which changes between client builds).
  let candidate = anchor.parentElement;
  while (candidate) {
    const overflowY = window.getComputedStyle(candidate).overflowY;
    if (
      (overflowY === "auto" || overflowY === "scroll")
      && candidate.scrollHeight > candidate.clientHeight
    ) {
      candidate.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    candidate = candidate.parentElement;
  }

  // This remains useful for a future Decky host that does not expose its
  // scrolling element through the DOM hierarchy above the plugin content.
  anchor.scrollIntoView({ block: "start", behavior: "smooth" });
}

function label(value: string): string {
  return LABELS[value] ?? value.replaceAll("_", " ").replaceAll(".", " ");
}

function DiagnosticRow({ name, value }: { name: string; value: string }) {
  return (
    <PanelSectionRow>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", width: "100%" }}>
        <span>{name}</span>
        <span style={{ opacity: 0.72, textAlign: "right" }}>{value}</span>
      </div>
    </PanelSectionRow>
  );
}

function showSupportBundlePreview(
  preview: SupportBundlePreviewPayload,
  onClose: () => void,
): ReturnType<typeof showModal> {
  let modal: ReturnType<typeof showModal>;
  const close = () => {
    modal.Close();
    onClose();
  };
  // Let Decky resolve Steam's visible SP window. This plugin executes in the
  // invisible SharedJSContext, so using its global window hides the dialog.
  modal = showModal(
    <ConfirmModal
      strTitle="Redacted support bundle preview"
      strOKButtonText="Close preview"
      bAlertDialog={true}
      bDisableBackgroundDismiss={true}
      bHideCloseIcon={true}
      onOK={close}
    >
      <div style={{ fontSize: "12px", lineHeight: "17px" }}>
        <p>
          Review this exact redacted JSON before copying or saving it. The save approval expires
          after five minutes and can be used once.
        </p>
        <div style={{ maxHeight: "55vh", overflow: "hidden" }}>
          <ScrollPanel>
            <pre style={{ whiteSpace: "pre-wrap" }}>{preview.preview_json}</pre>
          </ScrollPanel>
        </div>
      </div>
    </ConfirmModal>,
    window,
    { strTitle: PRODUCT_NAME, bNeverPopOut: true },
  );
  return modal;
}

function showPresentationPreparationConfirmation(
  onConfirm: () => void,
  onClose: () => void,
): ReturnType<typeof showModal> {
  let modal: ReturnType<typeof showModal>;
  const close = () => {
    modal.Close();
    onClose();
  };
  modal = showModal(
    <ConfirmModal
      strTitle="Prepare experimental display validation?"
      strOKButtonText="Prepare"
      strCancelButtonText="Cancel"
      bDestructiveWarning={true}
      bDisableBackgroundDismiss={true}
      bHideCloseIcon={true}
      onOK={() => {
        close();
        onConfirm();
      }}
      onCancel={close}
    >
      <div style={{ fontSize: "13px", lineHeight: "18px" }}>
        <p>
          Continue only with the eGPU disconnected, no game running, and the handheld screen visible.
        </p>
        <p>
          This installs Re-Gear&apos;s reversible Gamescope startup integration and reloads the user
          service configuration. It does not restart Gamescope, switch displays, or select a GPU.
        </p>
      </div>
    </ConfirmModal>,
    window,
    { strTitle: PRODUCT_NAME, bNeverPopOut: true },
  );
  return modal;
}

function showAutomaticDockConfirmation(
  onConfirm: () => void,
  onClose: () => void,
): ReturnType<typeof showModal> {
  let modal: ReturnType<typeof showModal>;
  const close = () => {
    modal.Close();
    onClose();
  };
  modal = showModal(
    <ConfirmModal
      strTitle="Enable automatic TV docking?"
      strOKButtonText="Enable"
      strCancelButtonText="Cancel"
      bDestructiveWarning={true}
      bDisableBackgroundDismiss={true}
      bHideCloseIcon={true}
      onOK={() => {
        close();
        onConfirm();
      }}
      onCancel={close}
    >
      <div style={{ fontSize: "13px", lineHeight: "18px" }}>
        <p>
          When Re-Gear verifies this Ally X, the exact GPD G1, one ready TV, a healthy link,
          and no running game, it will restart Steam Game Mode onto the TV.
        </p>
        <p>
          The screen will briefly show Steam shutting down. USB4 presence alone never triggers
          the restart, and physical live removal remains unsupported.
        </p>
      </div>
    </ConfirmModal>,
    window,
    { strTitle: PRODUCT_NAME, bNeverPopOut: true },
  );
  return modal;
}

function showSafeDisconnectConfirmation(
  portable: boolean,
  onConfirm: () => void,
  onClose: () => void,
): ReturnType<typeof showModal> {
  let modal: ReturnType<typeof showModal>;
  const close = () => {
    modal.Close();
    onClose();
  };
  modal = showModal(
    <ConfirmModal
      strTitle={portable ? "Shut down for G1 disconnect?" : "Return to Ally for G1 disconnect?"}
      strOKButtonText={portable ? "Shut down" : "Return to Ally"}
      strCancelButtonText="Cancel"
      bDestructiveWarning={true}
      bDisableBackgroundDismiss={true}
      bHideCloseIcon={true}
      onOK={() => {
        close();
        onConfirm();
      }}
      onCancel={close}
    >
      <div style={{ fontSize: "13px", lineHeight: "18px" }}>
        {portable ? (
          <>
            <p>Re-Gear will revalidate idle Portable mode and request a normal system shutdown.</p>
            <p>The request cannot prove physical power-off. Keep the G1 connected until the fan stops and every top power LED is off.</p>
            <p>If the fan remains on after 60 seconds, keep the G1 connected and hold the Ally power button until the fan stops.</p>
          </>
        ) : (
          <>
            <p>Re-Gear will require no running game, then restart Game Mode on the Ally display.</p>
            <p>After Portable is verified, acknowledge the result and use this control again to shut down. Do not unplug yet.</p>
          </>
        )}
      </div>
    </ConfirmModal>,
    window,
    { strTitle: PRODUCT_NAME, bNeverPopOut: true },
  );
  return modal;
}

function showControllerDisplayConfirmation(
  target: "tv" | "ally", onConfirm: () => void, onClose: () => void,
): ReturnType<typeof showModal> {
  let modal: ReturnType<typeof showModal>;
  const close = () => { modal.Close(); onClose(); };
  modal = showModal(
    <ConfirmModal
      strTitle={target === "tv" ? "Switch to TV?" : "Return to Ally?"}
      strOKButtonText={target === "tv" ? "Switch to TV" : "Return to Ally"}
      strCancelButtonText="Cancel"
      bDisableBackgroundDismiss={true}
      bHideCloseIcon={true}
      onOK={() => { close(); onConfirm(); }}
      onCancel={close}
    >
      <p>Re-Gear will check that no game is running and verify display readiness before restarting Game Mode.</p>
      <p>Keep the G1 connected. This action does not shut down the Ally or make unplugging safe.</p>
    </ConfirmModal>,
    window,
    { strTitle: PRODUCT_NAME, bNeverPopOut: true },
  );
  return modal;
}

function showPresentationPreparationBlocked(blockers: string[]): void {
  // The preparation result appears below its controller-focused button. Steam's
  // Quick Access navigation can leave that row off-screen, so also surface the
  // outcome immediately without requiring touch scrolling. Keep the message
  // categorical: integration ownership belongs in diagnostics, not a player
  // instruction to edit another plugin's files.
  const ownsPresentationPath = blockers.some((blocker) =>
    blocker.includes("path") || blocker.includes("integration"),
  );
  toaster.toast({
    title: "Display validation is not ready",
    body: ownsPresentationPath
      ? "Another display integration is active. Re-Gear will not replace it."
      : `Preparation blocked: ${blockers.map(label).join(", ")}.`,
    critical: true,
    duration: 12000,
  });
}

function showProcessReleaseConfirmation(
  preview: ProcessReleasePreviewPayload,
  onConfirm: () => void,
  onClose: () => void,
): ReturnType<typeof showModal> {
  let modal: ReturnType<typeof showModal>;
  const force = preview.phase === "force";
  const close = () => {
    modal.Close();
    onClose();
  };
  modal = showModal(
    <ConfirmModal
      strTitle={force ? "Force close eGPU processes?" : "Close eGPU processes?"}
      strOKButtonText={force ? "Force close" : "Close gracefully"}
      strCancelButtonText="Cancel"
      bDestructiveWarning={true}
      bDisableBackgroundDismiss={true}
      bHideCloseIcon={true}
      onOK={() => {
        close();
        onConfirm();
      }}
      onCancel={close}
    >
      <div style={{ fontSize: "13px", lineHeight: "18px" }}>
        <p>
          {force
            ? "Force close may lose unsaved work. Only the exact processes that survived the approved graceful attempt are eligible."
            : "Re-Gear will request a graceful close only for the exact ordinary user processes listed below."}
        </p>
        {preview.targets.map((target, index) => (
          <p key={`${target.name}-${index}`}>
            {target.name} — {target.resources.map(label).join(", ")}
          </p>
        ))}
        {preview.protected_client_count > 0 && (
          <p>{preview.protected_client_count} protected client(s) will not be closed.</p>
        )}
        <p>
          Clearing software clients does not authorize physical eGPU removal. Shut down before
          disconnecting the eGPU.
        </p>
      </div>
    </ConfirmModal>,
    window,
    { strTitle: PRODUCT_NAME, bNeverPopOut: true },
  );
  return modal;
}

function showDiagnosticLoggingConfirmation(
  durationLabel: string,
  onConfirm: () => void,
  onClose: () => void,
): ReturnType<typeof showModal> {
  let modal: ReturnType<typeof showModal>;
  const close = () => {
    modal.Close();
    onClose();
  };
  modal = showModal(
    <ConfirmModal
      strTitle="Enable verbose Re-Gear diagnostics?"
      strOKButtonText="Enable"
      strCancelButtonText="Cancel"
      bDisableBackgroundDismiss={true}
      bHideCloseIcon={true}
      onOK={() => {
        close();
        onConfirm();
      }}
      onCancel={close}
    >
      <div style={{ fontSize: "13px", lineHeight: "18px" }}>
        <p>
          Re-Gear will retain additional sanitized, Re-Gear-only events for {durationLabel}.
          Storage remains capped and verbose logging will not survive a reboot.
        </p>
        <p>
          Logs stay on this handheld unless you separately preview, save, and share a
          support bundle.
        </p>
      </div>
    </ConfirmModal>,
    window,
    { strTitle: PRODUCT_NAME, bNeverPopOut: true },
  );
  return modal;
}

function BrandIcon({ size = 24 }: { size?: number }) {
  return (
    <img src={brandIcon} alt="" aria-hidden="true" width={size} height={size}
      style={{ objectFit: "contain", flexShrink: 0 }} />
  );
}

function preflightObservation(payload: SnapshotPayload): PreflightObservation {
  const { snapshot } = payload;
  return observationFromSnapshotEvidence({
    schemaVersion: snapshot.schema_version,
    observedAt: snapshot.observed_at,
    guardRequired: snapshot.sleep_guard.required,
    guardConfidence: snapshot.sleep_guard.confidence,
    gameState: snapshot.game_state,
    gameUsesEgpu: snapshot.disconnect_readiness.clients.some(
      (client) => client.kind === "game",
    ),
  }, Date.now(), SNAPSHOT_STALE_AFTER_MS);
}

function Content({ preflight, connection }: { preflight: SleepPreflightCoordinator; connection: ReturnType<typeof startConnectionMonitor> }) {
  const quickAccessVisible = useQuickAccessVisible();
  const statusAnchor = useRef<HTMLDivElement | null>(null);
  const statusFocusAnchor = useRef<HTMLDivElement | null>(null);
  const primaryControlAnchor = useRef<HTMLDivElement | null>(null);
  const journeyDetailsAnchor = useRef<HTMLDivElement | null>(null);
  const [payload, setPayload] = useState<SnapshotPayload | null>(null);
  const [peripheralStatus, setPeripheralStatus] = useState<PeripheralStatusPayload | null>(null);
  const [actionHistory, setActionHistory] = useState<ActionHistoryPayload | null>(null);
  const [automaticDockStatus, setAutomaticDockStatus] = useState<AutomaticDockStatusPayload | null>(null);
  const [automaticDockBusy, setAutomaticDockBusy] = useState(false);
  const [automaticDockMessage, setAutomaticDockMessage] = useState("");
  const [showHardwareDetails, setShowHardwareDetails] = useState(false);
  const [safeDisconnectBusy, setSafeDisconnectBusy] = useState(false);
  const [safeDisconnectMessage, setSafeDisconnectMessage] = useState("");
  const [dockedIgpuStatus, setDockedIgpuStatus] = useState<DockedIgpuStatusPayload | null>(null);
  const [dockedIgpuMessage, setDockedIgpuMessage] = useState("");
  const [diagnosticLoggingStatus, setDiagnosticLoggingStatus] = useState<DiagnosticLoggingStatusPayload | null>(null);
  const [diagnosticLoggingDuration, setDiagnosticLoggingDuration] = useState<DiagnosticLoggingDuration>("2_hours");
  const [diagnosticLoggingBusy, setDiagnosticLoggingBusy] = useState(false);
  const [diagnosticLoggingMessage, setDiagnosticLoggingMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [preflightStatus, setPreflightStatus] = useState(() => preflight.status());
  const [sleepWarningHidden, setSleepWarningHidden] = useState(
    () => (
      localStorage.getItem(SLEEP_WARNING_KEY) === "1"
      || localStorage.getItem(LEGACY_SLEEP_WARNING_KEY) === "1"
    ),
  );
  const [supportPreview, setSupportPreview] = useState<SupportBundlePreviewPayload | null>(null);
  const [supportBusy, setSupportBusy] = useState(false);
  const [supportMessage, setSupportMessage] = useState("");
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [showJourneyDetails, setShowJourneyDetails] = useState(false);
  const [presentationBusy, setPresentationBusy] = useState(false);
  const [presentationMessage, setPresentationMessage] = useState("");
  const [tvSwitchBusy, setTvSwitchBusy] = useState(false);
  const [tvSwitchMessage, setTvSwitchMessage] = useState("");
  const [tvSwitchAcknowledgementId, setTvSwitchAcknowledgementId] = useState("");
  const [journalStatus, setJournalStatus] = useState<TransitionJournalStatusPayload | null>(null);
  const [journalBusy, setJournalBusy] = useState(false);
  const [journalMessage, setJournalMessage] = useState("");
  const [processBusy, setProcessBusy] = useState(false);
  const [processMessage, setProcessMessage] = useState("");
  const [processAcknowledgementId, setProcessAcknowledgementId] = useState("");
  const [forceReceiptToken, setForceReceiptToken] = useState("");
  const lastSnapshotAt = useRef<number | null>(null);
  const refreshInFlight = useRef(false);
  const warningToastShown = useRef(false);
  const inactiveToastShown = useRef(false);
  const linkHealthNotification = useRef<ReturnType<typeof decideLinkHealthNotification>["memory"]>(null);
  const supportModal = useRef<ReturnType<typeof showModal> | null>(null);
  const presentationModal = useRef<ReturnType<typeof showModal> | null>(null);
  const automaticDockModal = useRef<ReturnType<typeof showModal> | null>(null);
  const safeDisconnectModal = useRef<ReturnType<typeof showModal> | null>(null);
  const safeDisconnectExecuting = useRef(false);
  const tvSwitchExecuting = useRef(false);
  const [controllerShortcutAvailable, setControllerShortcutAvailable] = useState(false);
  const processModal = useRef<ReturnType<typeof showModal> | null>(null);
  const diagnosticLoggingModal = useRef<ReturnType<typeof showModal> | null>(null);

  const refreshTransitionJournal = useCallback(async () => {
    try {
      const status = await getTransitionJournalStatus();
      setJournalStatus(status);
      if (status.code === "journal.idle") {
        setJournalMessage("");
        // A verified success may be retired by the backend after the initial
        // status/RPC response. Do not keep its acknowledgement blocking actions.
        setTvSwitchAcknowledgementId("");
      } else if (status.owner === "sleep" && status.acknowledgement_required) {
        setJournalMessage(
          "A prior sleep result must be acknowledged before Re-Gear can switch displays.",
        );
      } else if (status.code === "journal.recovery_required") {
        setJournalMessage(
          `An interrupted ${label(status.owner)} workflow requires recovery. Re-Gear will not retry it automatically.`,
        );
      } else if (status.owner === "unknown") {
        setJournalMessage(
          "The safety journal owner is unknown. Re-Gear will not clear it or switch displays.",
        );
      } else {
        setJournalMessage(`A prior ${label(status.owner)} result still needs attention.`);
      }
    } catch {
      setJournalStatus(null);
      setJournalMessage("Shared safety-journal status is unavailable. Re-Gear will not switch displays.");
    }
  }, []);

  useEffect(() => () => {
    supportModal.current?.Close();
    supportModal.current = null;
    presentationModal.current?.Close();
    presentationModal.current = null;
    automaticDockModal.current?.Close();
    automaticDockModal.current = null;
    safeDisconnectModal.current?.Close();
    safeDisconnectModal.current = null;
    processModal.current?.Close();
    processModal.current = null;
    diagnosticLoggingModal.current?.Close();
    diagnosticLoggingModal.current = null;
  }, []);

  useEffect(() => {
    void refreshTransitionJournal();
  }, [refreshTransitionJournal]);

  useEffect(() => {
    let disposed = false;
    void getAutomaticDockStatus().then((status) => {
      if (!disposed) setAutomaticDockStatus(status);
    }).catch(() => {
      if (!disposed) {
        setAutomaticDockMessage("Automatic docking status is unavailable; no restart will be requested.");
      }
    });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    void getProcessReleaseStatus().then((status) => {
      if (
        disposed
        || status.code === "process_release.idle"
        || status.code === "process_release.foreign_journal"
      ) {
        return;
      }
      if (status.acknowledgement_required && status.acknowledgement_id) {
        setProcessAcknowledgementId(status.acknowledgement_id);
      }
      setProcessMessage(
        status.action_required
          ? "A prior process-release attempt needs acknowledgement. Do not disconnect the eGPU."
          : `Previous process-release result: ${label(status.code)}.`,
      );
    }).catch(() => {
      if (!disposed) {
        setProcessMessage("Process-release safety state is unavailable. Do not disconnect the eGPU.");
      }
    });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    void getSupervisedTvSwitchStatus().then((status) => {
      if (
        disposed
        || status.code === "transition.idle"
        || status.code === "transition.foreign_journal"
      ) {
        return;
      }
      if (status.acknowledgement_required && status.acknowledgement_id) {
        setTvSwitchAcknowledgementId(status.acknowledgement_id);
      }
      setTvSwitchMessage(
        status.action_required
          ? "A prior display transition needs acknowledgement. Re-Gear did not claim its target is active."
          : `Previous display transition result: ${label(status.code)}.`,
      );
    }).catch(() => {
      if (!disposed) {
        setTvSwitchMessage("Display-transition safety state is unavailable. Re-Gear did not claim success.");
      }
    });
    return () => {
      disposed = true;
    };
  }, []);

  const refresh = useCallback(async (quiet = false): Promise<SnapshotPayload | null> => {
    if (refreshInFlight.current) {
      return null;
    }
    refreshInFlight.current = true;
    if (!quiet) {
      setLoading(true);
      setError("");
    }
    try {
      const nextPayload = await getSnapshot();
      try {
        setAutomaticDockStatus(await getAutomaticDockStatus());
      } catch {
        setAutomaticDockStatus(null);
        setAutomaticDockMessage(
          "Automatic docking status is unavailable; no restart will be requested.",
        );
      }
      await refreshTransitionJournal();
      const linkDecision = decideLinkHealthNotification(
        linkHealthNotification.current,
        nextPayload,
      );
      linkHealthNotification.current = linkDecision.memory;
      if (linkDecision.notification) {
        try {
          toaster.toast(linkDecision.notification);
        } catch {
          // A transient QAM toast-host failure must not turn a successful
          // read-only snapshot into an apparent hardware failure.
        }
      }
      const optionalDiagnostics = await collectOptionalDiagnostics(
        shouldCollectOptionalDiagnostics(
          quickAccessVisible && showDiagnostics,
          nextPayload.snapshot.game_state,
        ),
        {
          getDockedIgpuStatus,
          getDiagnosticLoggingStatus,
          getPeripheralStatus,
          getActionHistory,
        },
      );
      const presentationPayload = {
        ...nextPayload,
        journey: sanitizeJourneyStatus(nextPayload.journey),
      };
      setPayload(presentationPayload);
      setDockedIgpuStatus(optionalDiagnostics.dockedIgpuStatus);
      setDiagnosticLoggingStatus(optionalDiagnostics.diagnosticLoggingStatus);
      setPeripheralStatus(optionalDiagnostics.peripheralStatus);
      setActionHistory(optionalDiagnostics.actionHistory);
      setError("");
      lastSnapshotAt.current = Date.now();
      setPreflightStatus(preflight.reconcile(preflightObservation(nextPayload)));
      return presentationPayload;
    } catch {
      setError("Read-only snapshot unavailable. Check the Decky log for details.");
      setPreflightStatus(preflight.reconcile({ kind: "unavailable" }));
      return null;
    } finally {
      refreshInFlight.current = false;
      if (!quiet) {
        setLoading(false);
      }
    }
  }, [preflight, quickAccessVisible, refreshTransitionJournal, showDiagnostics]);

  useEffect(() => {
    if (quickAccessVisible) {
      return;
    }
    const compact = compactStatusPanels();
    setShowDiagnostics(compact.showDiagnostics);
    setShowJourneyDetails(compact.showJourneyDetails);
    setShowHardwareDetails(false);
    setDockedIgpuStatus(null);
    setDiagnosticLoggingStatus(null);
    setPeripheralStatus(null);
    setActionHistory(null);
  }, [quickAccessVisible]);

  useEffect(() => {
    let disposed = false;
    let timer: number | null = null;
    const poll = async (quiet: boolean) => {
      if (
        lastSnapshotAt.current !== null
        && Date.now() - lastSnapshotAt.current > SNAPSHOT_STALE_AFTER_MS
      ) {
        setPreflightStatus(preflight.reconcile({ kind: "stale" }));
      }
      const nextPayload = await refresh(quiet);
      if (!disposed) {
        timer = window.setTimeout(
          () => void poll(true),
          refreshDelayForVisibility(nextPayload, quickAccessVisible),
        );
      }
    };
    void poll(false);
    return () => {
      disposed = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [preflight, quickAccessVisible, refresh]);

  const snapshot = payload?.snapshot;
  const disconnect = snapshot?.disconnect_readiness;
  const sleepGuard = snapshot?.sleep_guard;
  const progress = connectionProgress(payload);
  const gameUsesEgpu = disconnect?.clients.some((client) => client.kind === "game") ?? false;
  const closeEligibleClientCount = disconnect?.clients.filter(
    (client) => client.kind === "user" && client.close_eligible,
  ).length ?? 0;
  const disconnectStatus = loading
    ? "Reading…"
    : !disconnect?.applicable
      ? "eGPU not connected"
      : !disconnect.scan_complete
        ? "Scan incomplete — blocked"
        : disconnect.ready
          ? "Ready"
          : "Blocked";
  const overlayRows = diagnosticOverlayRows(
    payload,
    dockedIgpuStatus,
    diagnosticLoggingStatus,
    peripheralStatus,
    actionHistory,
  );
  const optionalDiagnosticsDeferred = showDiagnostics && snapshot?.game_state !== "idle";
  const journeyRows = compactJourneyStatusRows(payload?.journey);
  const journeyDetailRows = journeyStatusRows(payload?.journey);
  const healthAttention = healthAttentionMessages(payload?.health);
  const needsAttention = Boolean(error)
    || (snapshot?.blockers.length ?? 0) > 0
    || healthAttention.length > 0;

  const acknowledgeDockedIgpuWatch = useCallback(async () => {
    setDockedIgpuMessage("");
    try {
      const result = await acknowledgeDockedIgpuStatus();
      if (!result.acknowledged) {
        setDockedIgpuMessage("The watcher state could not be acknowledged.");
        return;
      }
      const status = await getDockedIgpuStatus();
      setDockedIgpuStatus(status);
      setDockedIgpuMessage("Watcher state acknowledged. Observation will resume.");
    } catch {
      setDockedIgpuMessage("Watcher acknowledgement is unavailable.");
    }
  }, []);

  const applyDiagnosticLogging = useCallback(async () => {
    setDiagnosticLoggingBusy(true);
    setDiagnosticLoggingMessage("");
    try {
      const status = await enableDiagnosticLogging(
        diagnosticLoggingDuration,
        true,
      );
      setDiagnosticLoggingStatus(status);
      setDiagnosticLoggingMessage(
        status.enabled
          ? "Verbose diagnostics enabled. They remain local until separately exported."
          : "Verbose diagnostics were not enabled.",
      );
    } catch {
      setDiagnosticLoggingMessage("Verbose diagnostics could not be enabled.");
    } finally {
      setDiagnosticLoggingBusy(false);
    }
  }, [diagnosticLoggingDuration]);

  const requestDiagnosticLogging = useCallback(() => {
    const option = DIAGNOSTIC_LOGGING_OPTIONS.find(
      (value) => value.data === diagnosticLoggingDuration,
    );
    diagnosticLoggingModal.current?.Close();
    diagnosticLoggingModal.current = showDiagnosticLoggingConfirmation(
      option?.label ?? "the selected duration",
      () => void applyDiagnosticLogging(),
      () => {
        diagnosticLoggingModal.current = null;
      },
    );
  }, [applyDiagnosticLogging, diagnosticLoggingDuration]);

  const stopDiagnosticLogging = useCallback(async () => {
    setDiagnosticLoggingBusy(true);
    setDiagnosticLoggingMessage("");
    try {
      const status = await disableDiagnosticLogging();
      setDiagnosticLoggingStatus(status);
      setDiagnosticLoggingMessage("Verbose diagnostics disabled.");
    } catch {
      setDiagnosticLoggingMessage("Verbose diagnostics status is unavailable.");
    } finally {
      setDiagnosticLoggingBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!sleepGuard?.required) {
      warningToastShown.current = false;
      inactiveToastShown.current = false;
      return;
    }
    if (sleepGuard.active) {
      inactiveToastShown.current = false;
    } else if (!inactiveToastShown.current) {
      toaster.toast({
        title: "eGPU sleep protection is inactive",
        body: sleepGuard.error || "Do not put the handheld to sleep while an eGPU is attached.",
        critical: true,
        duration: 10000,
      });
      inactiveToastShown.current = true;
    }
    if (!sleepWarningHidden && !warningToastShown.current) {
      toaster.toast({
        title: gameUsesEgpu ? "Sleep blocked while game uses eGPU" : "Sleep blocked while eGPU is attached",
        body: "This hardware is known to wake immediately after sleep. Restore Portable and disconnect only after shutdown.",
        duration: 10000,
      });
      warningToastShown.current = true;
    }
  }, [gameUsesEgpu, sleepGuard, sleepWarningHidden]);

  const hideSleepWarning = useCallback(() => {
    localStorage.setItem(SLEEP_WARNING_KEY, "1");
    localStorage.removeItem(LEGACY_SLEEP_WARNING_KEY);
    setSleepWarningHidden(true);
  }, []);

  const showSleepWarning = useCallback(() => {
    localStorage.removeItem(SLEEP_WARNING_KEY);
    localStorage.removeItem(LEGACY_SLEEP_WARNING_KEY);
    warningToastShown.current = false;
    setSleepWarningHidden(false);
  }, []);

  const createSupportPreview = useCallback(async () => {
    setSupportBusy(true);
    setSupportMessage("");
    try {
      const preview = await previewSupportBundle();
      setSupportPreview(preview);
      setSupportMessage("Redacted preview ready. Review it before copying or saving.");
      supportModal.current?.Close();
      supportModal.current = showSupportBundlePreview(preview, () => {
        supportModal.current = null;
      });
    } catch {
      setSupportMessage("Support bundle preview failed. No file was written.");
    } finally {
      setSupportBusy(false);
    }
  }, []);

  const reviewSupportPreview = useCallback(() => {
    if (!supportPreview) {
      return;
    }
    supportModal.current?.Close();
    supportModal.current = showSupportBundlePreview(supportPreview, () => {
      supportModal.current = null;
    });
  }, [supportPreview]);

  const copySupportPreview = useCallback(async () => {
    if (!supportPreview) {
      return;
    }
    setSupportBusy(true);
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("clipboard unavailable");
      }
      await navigator.clipboard.writeText(supportPreview.preview_json);
      setSupportMessage("Redacted support bundle copied to the clipboard.");
    } catch {
      setSupportMessage("Clipboard copy is unavailable. The preview was not changed.");
    } finally {
      setSupportBusy(false);
    }
  }, [supportPreview]);

  const saveApprovedSupportPreview = useCallback(async () => {
    if (!supportPreview) {
      return;
    }
    setSupportBusy(true);
    try {
      const result = await saveSupportBundle(supportPreview.preview_token);
      setSupportMessage(
        result.ok
          ? `Saved the reviewed bundle to ${result.relative_path}.`
          : "Support bundle save did not complete.",
      );
      if (result.ok) {
        setSupportPreview(null);
      }
    } catch {
      setSupportMessage("Save approval expired or failed. Create and review a new preview.");
      setSupportPreview(null);
    } finally {
      setSupportBusy(false);
    }
  }, [supportPreview]);

  const preparePresentation = useCallback(async () => {
    setPresentationBusy(true);
    setPresentationMessage("");
    try {
      const approval = await approvePresentationPreparation();
      if (!approval.approval_token || approval.blockers.length > 0) {
        if (approval.blockers.length > 0) {
          showPresentationPreparationBlocked(approval.blockers);
        }
        setPresentationMessage(
          approval.blockers.length > 0
            ? `Preparation blocked: ${approval.blockers.map(label).join(", ")}.`
            : "Preparation approval was not issued. Inspect again.",
        );
        return;
      }
      const outcome = await preparePresentationIntegration(approval.approval_token);
      setPresentationMessage(
        outcome.prepared
          ? outcome.changed
            ? "Gamescope validation integration prepared. Gamescope was not restarted."
            : "Gamescope validation integration was already prepared."
          : outcome.rollback_attempted && !outcome.rollback_succeeded
            ? "Preparation failed and rollback needs attention. Do not restart Gamescope."
            : `Preparation did not complete: ${label(outcome.code)}.`,
      );
    } catch {
      setPresentationMessage("Preparation failed safely. Gamescope was not intentionally restarted.");
    } finally {
      setPresentationBusy(false);
    }
  }, []);

  const inspectPresentationPreparation = useCallback(async () => {
    setPresentationBusy(true);
    setPresentationMessage("");
    try {
      const preview = await previewPresentationPreparation();
      if (preview.blockers.length > 0) {
        showPresentationPreparationBlocked(preview.blockers);
        setPresentationMessage(
          `Preparation blocked: ${preview.blockers.map(label).join(", ")}.`,
        );
        return;
      }
      if (preview.ready) {
        setPresentationMessage("Gamescope validation integration is already prepared.");
        return;
      }
      presentationModal.current?.Close();
      presentationModal.current = showPresentationPreparationConfirmation(
        () => void preparePresentation(),
        () => {
          presentationModal.current = null;
        },
      );
    } catch {
      setPresentationMessage("Preparation inspection is unavailable. No change was made.");
    } finally {
      setPresentationBusy(false);
    }
  }, [preparePresentation]);

  const executeTvSwitch = useCallback(async () => {
    if (tvSwitchExecuting.current || safeDisconnectExecuting.current) return;
    tvSwitchExecuting.current = true;
    setTvSwitchBusy(true);
    setTvSwitchMessage("");
    try {
      const approval = await approveSupervisedTvSwitch();
      if (!approval.approval_token || approval.blockers.length > 0) {
        setTvSwitchMessage(
          approval.blockers.length > 0
            ? `TV switch blocked: ${approval.blockers.map(label).join(", ")}.`
            : "TV switch approval was not issued. Inspect again.",
        );
        return;
      }
      toaster.toast({
        title: "Re-Gear is switching to the TV",
        body: "Watch the handheld screen while Re-Gear verifies the transition.",
        critical: true,
        duration: 30000,
      });
      const outcome = await executeSupervisedTvSwitch(approval.approval_token);
      setTvSwitchAcknowledgementId(
        outcome.acknowledgement_required ? outcome.acknowledgement_id : "",
      );
      setTvSwitchMessage(
        outcome.accepted
          ? `TV switch result: ${label(outcome.code)}.`
          : `TV switch was not accepted: ${label(outcome.code)}.`,
      );
    } catch {
      setTvSwitchMessage("TV switch did not complete. Re-Gear did not claim success.");
    } finally {
      tvSwitchExecuting.current = false;
      setTvSwitchBusy(false);
    }
  }, []);

  const openConnectionProgress = useCallback(() => {
    connection.open(() => void executeTvSwitch());
  }, [connection, executeTvSwitch]);

  const changeAutomaticDock = useCallback(async (enabled: boolean) => {
    setAutomaticDockBusy(true);
    setAutomaticDockMessage("");
    try {
      const status = await setAutomaticDockEnabled(enabled, enabled);
      setAutomaticDockStatus(status);
      setAutomaticDockMessage(
        status.enabled
          ? "Automatic TV docking is enabled. Re-Gear is waiting for complete G1 and TV evidence."
          : status.code === "automatic_dock.disabled"
            ? "Automatic TV docking is disabled."
            : `Automatic TV docking was not changed: ${label(status.code)}.`,
      );
    } catch {
      setAutomaticDockMessage("Automatic TV docking was not changed.");
    } finally {
      setAutomaticDockBusy(false);
    }
  }, []);

  const toggleAutomaticDock = useCallback(() => {
    if (automaticDockStatus?.enabled) {
      void changeAutomaticDock(false);
      return;
    }
    automaticDockModal.current?.Close();
    automaticDockModal.current = showAutomaticDockConfirmation(
      () => void changeAutomaticDock(true),
      () => {
        automaticDockModal.current = null;
      },
    );
  }, [automaticDockStatus?.enabled, changeAutomaticDock]);

  const executeSafeDisconnect = useCallback(async (portable: boolean) => {
    if (safeDisconnectExecuting.current || tvSwitchExecuting.current) return;
    safeDisconnectExecuting.current = true;
    setSafeDisconnectBusy(true);
    setSafeDisconnectMessage("");
    try {
      if (portable) {
        const approval = await approveSafeDisconnectShutdown();
        if (!approval.ready || !approval.approval_token || approval.blockers.length > 0) {
          setSafeDisconnectMessage(
            approval.blockers.length > 0
              ? `Shutdown blocked: ${approval.blockers.map(label).join(", ")}.`
              : "Shutdown approval was not issued. Inspect again.",
          );
          return;
        }
        toaster.toast({
          title: "Re-Gear requested an Ally shutdown",
          body: "Completion is unverified. Keep the G1 connected until the fan and every top power LED are off.",
          critical: true,
          duration: 30000,
        });
        const outcome = await executeSafeDisconnectShutdown(approval.approval_token);
        setSafeDisconnectMessage(
          outcome.accepted
            ? "Power-off request accepted; completion is unverified. Keep the G1 connected until the fan stops. If it remains on after 60 seconds, hold the Ally power button until the fan stops."
            : `Shutdown was not requested: ${label(outcome.code)}.`,
        );
        return;
      }

      const approval = await approveSupervisedPortableSwitch();
      if (!approval.approval_token || approval.blockers.length > 0) {
        setSafeDisconnectMessage(
          approval.blockers.length > 0
            ? `Return to Ally blocked: ${approval.blockers.map(label).join(", ")}.`
            : "Portable transition approval was not issued. Inspect again.",
        );
        return;
      }
      toaster.toast({
        title: "Re-Gear is returning to the Ally",
        body: "Do not disconnect the G1. Wait for Portable verification, then shut down.",
        critical: true,
        duration: 30000,
      });
      const outcome = await executeSupervisedPortableSwitch(approval.approval_token);
      setTvSwitchAcknowledgementId(
        outcome.acknowledgement_required ? outcome.acknowledgement_id : "",
      );
      setSafeDisconnectMessage(
        outcome.accepted
          ? `Portable transition result: ${label(outcome.code)}.`
          : `Portable transition was not accepted: ${label(outcome.code)}.`,
      );
    } catch {
      setSafeDisconnectMessage(
        portable
          ? "Shutdown was not requested. Keep the G1 connected."
          : "Portable transition did not complete. Keep the G1 connected.",
      );
    } finally {
      safeDisconnectExecuting.current = false;
      setSafeDisconnectBusy(false);
    }
  }, []);

  const requestSafeDisconnectForMode = useCallback((portable: boolean) => {
    if (safeDisconnectExecuting.current || tvSwitchExecuting.current || safeDisconnectModal.current) return;
    safeDisconnectModal.current = showSafeDisconnectConfirmation(
      portable,
      () => void executeSafeDisconnect(portable),
      () => {
        safeDisconnectModal.current = null;
      },
    );
  }, [executeSafeDisconnect]);

  const requestSafeDisconnect = useCallback(() => {
    requestSafeDisconnectForMode(payload?.inference.mode === "portable");
  }, [requestSafeDisconnectForMode, payload?.inference.mode]);

  const requestControllerDisplaySwitch = useCallback((target: "tv" | "ally") => {
    if (safeDisconnectExecuting.current || tvSwitchExecuting.current || safeDisconnectModal.current) return;
    safeDisconnectModal.current = showControllerDisplayConfirmation(
      target,
      () => { if (target === "tv") void executeTvSwitch(); else void executeSafeDisconnect(false); },
      () => { safeDisconnectModal.current = null; },
    );
  }, [executeTvSwitch, executeSafeDisconnect]);

  useEffect(() => {
    const shortcut = startControllerSafeDisconnect({
      input: steamControllerInput(window),
      readContext: async () => {
        const [snapshot, journal] = await Promise.all([getSnapshot(), getTransitionJournalStatus()]);
        return { snapshot, journal };
      },
      isBusy: () => safeDisconnectExecuting.current || tvSwitchExecuting.current || safeDisconnectModal.current !== null,
      confirm: requestControllerDisplaySwitch,
    });
    setControllerShortcutAvailable(shortcut.available);
    return () => shortcut.stop();
  }, [requestControllerDisplaySwitch]);

  const acknowledgeTvSwitch = useCallback(async () => {
    if (!tvSwitchAcknowledgementId) return;
    setTvSwitchBusy(true);
    try {
      const result = await acknowledgeSupervisedTvSwitch(tvSwitchAcknowledgementId);
      setTvSwitchMessage(result.acknowledged
        ? "Display transition result acknowledged."
        : "Display transition result could not be acknowledged.");
      if (result.acknowledged) {
        setTvSwitchAcknowledgementId("");
        await refreshTransitionJournal();
      }
    } catch {
      setTvSwitchMessage("Display transition acknowledgement is unavailable.");
    } finally {
      setTvSwitchBusy(false);
    }
  }, [refreshTransitionJournal, tvSwitchAcknowledgementId]);

  const acknowledgePriorSleep = useCallback(async () => {
    const acknowledgementId = journalStatus?.owner === "sleep"
      ? journalStatus.acknowledgement_id
      : "";
    if (!acknowledgementId) return;
    setJournalBusy(true);
    try {
      const result = await acknowledgeSleepJournal(acknowledgementId);
      setJournalMessage(result.acknowledged
        ? "Prior sleep result acknowledged. Automatic docking is re-checking this attachment."
        : "The exact sleep result could not be acknowledged.");
      if (result.acknowledged) {
        setJournalStatus({
          schema_version: 1,
          code: "journal.idle",
          owner: "none",
          acknowledgement_required: false,
          action_required: false,
          acknowledgement_id: "",
          durable: true,
        });
      }
    } catch {
      setJournalMessage("Sleep-result acknowledgement is unavailable.");
    } finally {
      setJournalBusy(false);
    }
  }, [journalStatus]);

  const runProcessRelease = useCallback(async (
    phase: ProcessReleasePhase,
    receiptToken: string,
  ) => {
    setProcessBusy(true);
    setProcessMessage("");
    try {
      const approval = await approveProcessRelease(phase, receiptToken);
      if (!approval.approval_token || approval.blockers.length > 0) {
        setProcessMessage(
          approval.blockers.length > 0
            ? `Process release blocked: ${approval.blockers.map(label).join(", ")}.`
            : "Process-release approval was not issued. Inspect again.",
        );
        if (phase === "force") {
          setForceReceiptToken("");
        }
        return;
      }
      const outcome = await executeProcessRelease(approval.approval_token);
      setProcessMessage(processReleaseOutcomeMessage(outcome));
      setProcessAcknowledgementId(outcome.acknowledgement_id);
      setForceReceiptToken(canOfferForce(outcome) ? outcome.force_receipt_token : "");
      await refresh(true);
    } catch {
      setProcessMessage("Process release failed closed. Do not disconnect the eGPU.");
      if (phase === "force") {
        setForceReceiptToken("");
      }
    } finally {
      setProcessBusy(false);
    }
  }, [refresh]);

  const inspectProcessRelease = useCallback(async (
    phase: ProcessReleasePhase,
    receiptToken = "",
  ) => {
    setProcessBusy(true);
    setProcessMessage("");
    try {
      const preview = await previewProcessRelease(phase, receiptToken);
      if (!preview.ready || preview.blockers.length > 0 || preview.targets.length === 0) {
        setProcessMessage(
          preview.blockers.length > 0
            ? `Process release blocked: ${preview.blockers.map(label).join(", ")}.`
            : "No eligible ordinary user process is holding the eGPU.",
        );
        return;
      }
      processModal.current?.Close();
      processModal.current = showProcessReleaseConfirmation(
        preview,
        () => void runProcessRelease(phase, receiptToken),
        () => {
          processModal.current = null;
        },
      );
    } catch {
      setProcessMessage("Process-release inspection is unavailable. No process was signaled.");
    } finally {
      setProcessBusy(false);
    }
  }, [runProcessRelease]);

  const acknowledgeProcessResult = useCallback(async () => {
    if (!processAcknowledgementId) {
      return;
    }
    setProcessBusy(true);
    try {
      const result = await acknowledgeProcessRelease(processAcknowledgementId);
      if (!result.acknowledged) {
        setProcessMessage("The exact process-release result could not be acknowledged.");
        return;
      }
      setProcessAcknowledgementId("");
      setForceReceiptToken("");
      setProcessMessage("Process-release result acknowledged. Inspect again if blockers remain.");
      await refreshTransitionJournal();
    } catch {
      setProcessMessage("Process-release acknowledgement failed.");
    } finally {
      setProcessBusy(false);
    }
  }, [processAcknowledgementId, refreshTransitionJournal]);

  const reviewForceClose = useCallback(async () => {
    if (!forceReceiptToken) {
      return;
    }
    setProcessBusy(true);
    try {
      if (processAcknowledgementId) {
        const result = await acknowledgeProcessRelease(processAcknowledgementId);
        if (!result.acknowledged) {
          setProcessMessage("Acknowledge the graceful result before force-close review.");
          return;
        }
        setProcessAcknowledgementId("");
      }
      await inspectProcessRelease("force", forceReceiptToken);
    } catch {
      setProcessMessage("Force-close review is unavailable. No process was signaled.");
    } finally {
      setProcessBusy(false);
    }
  }, [forceReceiptToken, inspectProcessRelease, processAcknowledgementId]);

  const returnToStatus = useCallback(() => {
    const compact = compactStatusPanels();
    setShowDiagnostics(compact.showDiagnostics);
    setShowJourneyDetails(compact.showJourneyDetails);
    setShowHardwareDetails(false);
    // Wait for the diagnostics section to collapse, then reset Steam's owning
    // scroll panel and move focus to a native in-panel control. A non-focusable
    // status div leaves controller navigation at Steam's QAM Back control.
    window.setTimeout(() => {
      const anchor = statusAnchor.current;
      if (!anchor) return;
      scrollToTopOfOwningPanel(anchor);
      restoreQuickAccessFocus(() =>
        statusFocusAnchor.current ?? primaryControlAnchor.current?.querySelector<HTMLElement>(
          "button, [role='button'], input, select",
        ) ?? null,
      );
    }, 0);
  }, []);

  const toggleTroubleshooting = useCallback(() => {
    if (!showDiagnostics) {
      void refresh(true);
    }
    setShowDiagnostics((visible) => !visible);
  }, [refresh, showDiagnostics]);

  const toggleJourneyDetails = useCallback(() => {
    setShowJourneyDetails((visible) => {
      const next = !visible;
      if (next) {
        window.setTimeout(() => revealJourneyDetails(journeyDetailsAnchor.current), 0);
      }
      return next;
    });
  }, []);

  const sectionVisibility = quickAccessSectionVisibility(showDiagnostics);

  return (
    <>
      <div ref={statusAnchor} tabIndex={-1}>
      <PanelSection title="At a glance">
        <Focusable
          ref={statusFocusAnchor}
          aria-label="Re-Gear status summary"
          onGamepadFocus={() => {
            if (statusAnchor.current) scrollToTopOfOwningPanel(statusAnchor.current);
          }}
        >
        <QuickAccessOverview
          mode={payload?.inference.mode ?? "unknown"}
          modeLabel={loading ? "Reading…" : label(payload?.inference.mode ?? "unknown")}
          health={healthStatusLabel(payload?.health, loading)}
          game={label(snapshot?.game_state ?? "unknown")}
          loading={loading}
        />
        </Focusable>
        <DashboardSurface>
          <DashboardAction
            title="Dock / eGPU"
            description={progress.label}
            icon="connection"
            expanded={showHardwareDetails}
            onClick={() => setShowHardwareDetails((visible) => !visible)}
          />
          {showHardwareDetails && <div>
            {hardwareDetailRows(payload).map(([name, value]) => <DiagnosticRow key={name} name={name} value={value} />)}
            <PanelSectionRow>{progress.detail}</PanelSectionRow>
          </div>}
        </DashboardSurface>
      </PanelSection>

      {payload?.connection_readiness && payload.connection_readiness.stage !== "disconnected" &&
        <PanelSection title="G1 connection">
          <ButtonItem layout="below" onClick={openConnectionProgress}>
            {connectionLiveStatus(payload, automaticDockStatus, journalStatus?.code, !!error).title} — View progress
          </ButtonItem>
        </PanelSection>}
      <PanelSection title="Safety & actions">
        <div ref={primaryControlAnchor}>
          <DashboardSurface primary>
            <DashboardAction
              icon="bolt"
              title={tvSwitchBusy ? "Switching…" : "Switch to TV now"}
              description="Checks readiness before switching"
              onClick={() => void executeTvSwitch()}
              disabled={
                tvSwitchBusy
                || Boolean(tvSwitchAcknowledgementId)
                || Boolean(journalStatus && journalStatus.code !== "journal.idle")
              }
            />
          </DashboardSurface>
          {tvSwitchMessage && <PanelSectionRow>{tvSwitchMessage}</PanelSectionRow>}
          <DashboardSurface>
          <div style={{ padding: "4px 12px" }}>
          <ToggleField
            label="Automatic TV docking"
            layout="inline"
            description={automaticDockBusy
              ? "Saving…"
              : !automaticDockStatus
                ? "Status unavailable"
                : automaticDockStatus.enabled
                  ? label(automaticDockStatus.code)
                  : "Off · Ask before enabling"}
            checked={automaticDockStatus?.enabled === true}
            disabled={automaticDockBusy || !automaticDockStatus}
            highlightOnFocus={true}
            onChange={toggleAutomaticDock}
          />
          </div>
          </DashboardSurface>
          {automaticDockMessage && (
            <PanelSectionRow>{automaticDockMessage}</PanelSectionRow>
          )}
          <DashboardSurface>
            <DashboardAction
              icon="power"
              title={safeDisconnectBusy
                ? "Checking…"
                : payload?.inference.mode === "portable"
                  ? "Shut down to disconnect"
                  : "Prepare to disconnect"}
              description={controllerShortcutAvailable
                ? "Back/View + Y (3 seconds): switch between Ally and TV. Keep the G1 connected."
                : "Keep the eGPU connected until fully powered off. Controller shortcut unavailable."}
              onClick={requestSafeDisconnect}
              disabled={
                safeDisconnectBusy
                || !disconnect?.applicable
                || Boolean(tvSwitchAcknowledgementId)
                || Boolean(journalStatus && journalStatus.code !== "journal.idle")
              }
            />
          </DashboardSurface>
          {safeDisconnectMessage && (
            <PanelSectionRow>{safeDisconnectMessage}</PanelSectionRow>
          )}
          {journalStatus && journalStatus.code !== "journal.idle" && (
            <DiagnosticRow name="Safety journal" value={label(journalStatus.owner)} />
          )}
          {journalMessage && <PanelSectionRow>{journalMessage}</PanelSectionRow>}
          {journalStatus?.owner === "sleep"
            && journalStatus.acknowledgement_required
            && journalStatus.acknowledgement_id && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={() => void acknowledgePriorSleep()}
                disabled={journalBusy}
              >
                {journalBusy ? "Acknowledging…" : "Acknowledge prior sleep result"}
              </ButtonItem>
            </PanelSectionRow>
          )}
          {tvSwitchAcknowledgementId && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => void acknowledgeTvSwitch()} disabled={tvSwitchBusy}>
                Acknowledge prior display transition result
              </ButtonItem>
            </PanelSectionRow>
          )}
          <DashboardSurface>
            <DashboardAction
              title="Troubleshoot"
              icon="tools"
              description="Safety checks, details & support"
              expanded={showDiagnostics}
              onClick={toggleTroubleshooting}
            />
          </DashboardSurface>
        </div>
        {needsAttention && (
          <PanelSectionRow>
            {error || healthAttention[0] || `${snapshot?.blockers.length} safety check${snapshot?.blockers.length === 1 ? "" : "s"} needs attention.`}
          </PanelSectionRow>
        )}
        {sectionVisibility.diagnostics && (
          <PanelSectionRow>Read-only status refreshes while this panel is open.</PanelSectionRow>
        )}
        {sectionVisibility.diagnostics && sleepGuard?.required && sleepWarningHidden && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={showSleepWarning}>
              Show sleep warning again
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      {sectionVisibility.journey && (
        <>
          <PanelSection title="Journey status">
            {journeyRows.map((row) => (
              <DiagnosticRow key={row.name} name={row.name} value={row.value} />
            ))}
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={toggleJourneyDetails}>
                {showJourneyDetails ? "Hide journey details" : "Open journey details"}
              </ButtonItem>
            </PanelSectionRow>
          </PanelSection>

          {showJourneyDetails && (
            <div ref={journeyDetailsAnchor}>
              <PanelSection title="Journey details">
                <PanelSectionRow>
                  Read-only local policy status. It does not perform dock, undock, recovery, or game actions.
                </PanelSectionRow>
                {journeyDetailRows.map((row) => (
                  <DiagnosticRow key={row.name} name={row.name} value={row.detail} />
                ))}
              </PanelSection>
            </div>
          )}
        </>
      )}

      {sectionVisibility.sleepProtection && <PanelSection title="Sleep protection">
        <DiagnosticRow
          name="System inhibitor"
          value={loading
            ? "Checking…"
            : sleepGuard?.required
              ? sleepGuard.active
                ? "Active"
                : "Inactive"
              : "Not required"}
        />
        <DiagnosticRow
          name="Steam preflight"
          value={preflightStatus.state === "active"
            ? preflightStatus.attemptWarningAvailable
              ? "Active"
              : "Blocked; warning unavailable"
            : preflightStatus.state === "inactive"
              ? "Standby — eGPU verified absent"
              : "Unavailable"}
        />
        <DiagnosticRow
          name="Blocked sleep attempts"
          value={preflightStatus.blockedAttemptCount
            ? `${preflightStatus.blockedAttemptCount} observed this session`
            : "None observed this session"}
        />
        {preflightStatus.error && (
          <PanelSectionRow>{preflightStatus.error}</PanelSectionRow>
        )}
        {sleepGuard?.required && (
          <>
            {!sleepWarningHidden && (
              <>
                <PanelSectionRow>
                  {gameUsesEgpu
                    ? "A game is using the eGPU. Sleep is blocked to prevent the known immediate-wake behavior and workload risk."
                    : "The attached eGPU is known to wake this handheld immediately after sleep. Sleep remains blocked until the eGPU is verified absent."}
                </PanelSectionRow>
                <PanelSectionRow>
                  <ButtonItem layout="below" onClick={hideSleepWarning}>
                    Never show this explanation again
                  </ButtonItem>
                </PanelSectionRow>
              </>
            )}
            {sleepWarningHidden && (
              <PanelSectionRow>
                The explanation is hidden. Sleep protection remains active.
              </PanelSectionRow>
            )}
          </>
        )}
      </PanelSection>}

      {sectionVisibility.disconnectReadiness && <PanelSection title="Disconnect readiness">
        <DiagnosticRow name="Status" value={disconnectStatus} />
        {disconnect?.applicable && (
          <DiagnosticRow
            name="Resource clients"
            value={String(disconnect.clients.length)}
          />
        )}
        {(disconnect?.storage_devices ?? 0) > 0 && (
          <DiagnosticRow
            name="eGPU storage"
            value={disconnect?.storage_in_use ? "In use — blocked" : "Not mounted"}
          />
        )}
        {disconnect?.error && <PanelSectionRow>{disconnect.error}</PanelSectionRow>}
        {closeEligibleClientCount > 0 && !processAcknowledgementId && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => void inspectProcessRelease("graceful")}
              disabled={processBusy}
            >
              {processBusy ? "Checking…" : "Close eligible eGPU processes"}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {forceReceiptToken && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => void reviewForceClose()}
              disabled={processBusy}
            >
              Review force close
            </ButtonItem>
          </PanelSectionRow>
        )}
        {processAcknowledgementId && !forceReceiptToken && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => void acknowledgeProcessResult()}
              disabled={processBusy}
            >
              Acknowledge process-release result
            </ButtonItem>
          </PanelSectionRow>
        )}
        {processMessage && <PanelSectionRow>{processMessage}</PanelSectionRow>}
        <PanelSectionRow>
          Process closure always requires confirmation. Software readiness never authorizes
          physical eGPU removal.
        </PanelSectionRow>
      </PanelSection>}

      {needsAttention && (
        <PanelSection title="Needs attention">
          {error && <PanelSectionRow>{error}</PanelSectionRow>}
          {healthAttention.map((message) => (
            <PanelSectionRow key={message}>{message}</PanelSectionRow>
          ))}
          {snapshot?.blockers.map((blocker) => (
            <PanelSectionRow key={blocker.code}>{blocker.message}</PanelSectionRow>
          ))}
        </PanelSection>
      )}

      {sectionVisibility.support && <PanelSection title="Support bundle">
        <PanelSectionRow>
          Preview a bounded Re-Gear-only report before copying or saving it. Raw hardware IDs,
          addresses, usernames, home paths, and command lines are excluded or redacted.
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void createSupportPreview()} disabled={supportBusy}>
            {supportBusy ? "Working…" : "Preview redacted support bundle"}
          </ButtonItem>
        </PanelSectionRow>
        {supportPreview && (
          <>
            <DiagnosticRow name="Preview size" value={`${supportPreview.size_bytes} bytes`} />
            <DiagnosticRow name="Recent events" value={String(supportPreview.event_count)} />
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={reviewSupportPreview} disabled={supportBusy}>
                Review exact redacted JSON
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => void copySupportPreview()} disabled={supportBusy}>
                Copy reviewed JSON
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={() => void saveApprovedSupportPreview()}
                disabled={supportBusy}
              >
                Save reviewed bundle to Downloads
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
        {supportMessage && <PanelSectionRow>{supportMessage}</PanelSectionRow>}
      </PanelSection>}

      {sectionVisibility.diagnostics && (
        <PanelSection title="Troubleshooting details">
          <PanelSectionRow>
            Read-only technical evidence. Raw hardware identities, connector names, and process IDs are hidden.
          </PanelSectionRow>
          {optionalDiagnosticsDeferred && (
            <PanelSectionRow>
              Additional troubleshooting checks wait until Re-Gear confirms no game is running.
            </PanelSectionRow>
          )}
          {overlayRows.map((row) => (
            <DiagnosticRow key={row.name} name={row.name} value={row.value} />
          ))}
          {dockedIgpuStatus?.acknowledgement_required && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={() => void acknowledgeDockedIgpuWatch()}
              >
                Acknowledge Docked-iGPU watcher state
              </ButtonItem>
            </PanelSectionRow>
          )}
          {dockedIgpuMessage && (
            <PanelSectionRow>{dockedIgpuMessage}</PanelSectionRow>
          )}
          <DropdownItem
            label="Verbose logging duration"
            description="Temporary, sanitized, capped, and off by default"
            rgOptions={DIAGNOSTIC_LOGGING_OPTIONS}
            selectedOption={diagnosticLoggingDuration}
            disabled={diagnosticLoggingBusy || diagnosticLoggingStatus?.enabled === true}
            onChange={(option) => {
              setDiagnosticLoggingDuration(option.data as DiagnosticLoggingDuration);
            }}
          />
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={diagnosticLoggingStatus?.enabled
                ? () => void stopDiagnosticLogging()
                : requestDiagnosticLogging}
              disabled={diagnosticLoggingBusy}
            >
              {diagnosticLoggingStatus?.enabled
                ? "Disable verbose diagnostics"
                : "Enable verbose diagnostics"}
            </ButtonItem>
          </PanelSectionRow>
          {diagnosticLoggingMessage && (
            <PanelSectionRow>{diagnosticLoggingMessage}</PanelSectionRow>
          )}
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => void inspectPresentationPreparation()}
              disabled={presentationBusy}
            >
              {presentationBusy ? "Checking…" : "Prepare supervised display validation"}
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            Preparation only. This control cannot restart Gamescope or switch displays.
          </PanelSectionRow>
          {presentationMessage && <PanelSectionRow>{presentationMessage}</PanelSectionRow>}
        </PanelSection>
      )}

      {sectionVisibility.navigation && <PanelSection title="Navigation">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={returnToStatus}>
            Back to top
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>}
      </div>
    </>
  );
}

function showBlockedAttempt(
  warning: BlockedAttemptWarning,
  onClose: () => void,
): ReturnType<typeof showModal> {
  let modal: ReturnType<typeof showModal>;
  const close = () => {
    modal.Close();
    onClose();
  };
  // Let Decky resolve Steam's visible SP window after the Power menu closes.
  // SharedJSContext's global window is not a player-visible modal parent.
  modal = showModal(
    <ConfirmModal
      strTitle={warning.title}
      strDescription={warning.body}
      strOKButtonText="OK"
      bAlertDialog={true}
      bDestructiveWarning={warning.critical}
      bDisableBackgroundDismiss={true}
      bHideCloseIcon={true}
      onOK={close}
    />,
    window,
    { strTitle: PRODUCT_NAME, bNeverPopOut: true },
  );
  return modal;
}

export default definePlugin(() => {
  let warningModal: ReturnType<typeof showModal> | null = null;
  let warningTimer: number | null = null;
  const preflight = new SleepPreflightCoordinator(
    createDeckySteamSuspendAdapter(),
    (warning) => {
      let toastDelivered = false;
      try {
        // Steam may silently discard a modal during the transient Power-menu
        // lifecycle. Show a durable native toast first, then still offer the
        // controller-confirmable modal after that menu has closed.
        toaster.toast({
          title: warning.title,
          body: warning.body,
          critical: true,
          duration: 30000,
        });
        toastDelivered = true;
      } catch {
        // The modal/fallback path below remains independently available.
      }
      if (warningTimer !== null) {
        window.clearTimeout(warningTimer);
      }
      warningModal?.Close();
      warningModal = null;
      // Steam closes the Power menu after dispatching OnSuspendRequest. Defer the
      // acknowledgement dialog so it is not discarded with that transient menu.
      warningTimer = window.setTimeout(() => {
        warningTimer = null;
        deliverBlockedAttempt(warning, {
          showModal: () => {
            warningModal = showBlockedAttempt(warning, () => {
              warningModal = null;
            });
          },
          showFallbackToast: (fallback) => {
            if (!toastDelivered) {
              toaster.toast({
                title: fallback.title,
                body: fallback.body,
                critical: true,
                duration: 30000,
              });
            }
          },
        });
      }, BLOCKED_ATTEMPT_MODAL_DELAY_MS);
    },
  );
  preflight.start();
  const offlineFocusChecks = startOfflineFocusChecks();
  const connection = startConnectionMonitor({
    read: async () => {
      const [payload, automatic, journal] = await Promise.all([
        getSnapshot(), getAutomaticDockStatus(), getTransitionJournalStatus(),
      ]);
      return {payload, automatic, journal: journal.code};
    },
    show: (store, switchTv, closed) => showConnectionLivePanel(store, switchTv, closed),
  });

  return {
    name: PRODUCT_NAME,
    titleView: <div className={staticClasses.Title} style={{ display: "flex", alignItems: "center", gap: 8 }}><BrandIcon size={36} />{PRODUCT_NAME}</div>,
    content: <Content preflight={preflight} connection={connection} />,
    icon: <BrandIcon />,
    alwaysRender: true,
    onDismount() {
      if (warningTimer !== null) {
        window.clearTimeout(warningTimer);
        warningTimer = null;
      }
      warningModal?.Close();
      warningModal = null;
      connection.stop();
      offlineFocusChecks.stop();
      preflight.stop();
    },
  };
});
