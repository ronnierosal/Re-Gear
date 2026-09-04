const manifest = {"name":"Handheld Dock Mode"};
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error('[@decky/api]: Failed to connect to the loader as as the loader API was not initialized. This is likely a bug in Decky Loader.');
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
}
catch {
    api = internalAPIConnection.connect(1, manifest.name);
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version 1. Some features may not work.`);
}
if (api._version != API_VERSION) {
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version ${api._version}. Some features may not work.`);
}
const callable = api.callable;
const toaster = api.toaster;
const useQuickAccessVisible = api.useQuickAccessVisible;
const definePlugin = (fn) => {
    return (...args) => {
        return fn(...args);
    };
};

const getSnapshot = callable("get_snapshot");
const getPeripheralStatus = callable("get_peripheral_status");
const getActionHistory = callable("get_action_history");
const getAutomaticDockStatus = callable("get_automatic_dock_status");
const setAutomaticDockEnabled = callable("set_automatic_dock_enabled");
const getDockedIgpuStatus = callable("get_docked_igpu_status");
const acknowledgeDockedIgpuStatus = callable("acknowledge_docked_igpu_status");
const getDiagnosticLoggingStatus = callable("get_diagnostic_logging_status");
const enableDiagnosticLogging = callable("enable_diagnostic_logging");
const disableDiagnosticLogging = callable("disable_diagnostic_logging");
const previewSupportBundle = callable("preview_support_bundle");
const saveSupportBundle = callable("save_support_bundle");
const previewPresentationPreparation = callable("preview_presentation_preparation");
const approvePresentationPreparation = callable("approve_presentation_preparation");
const preparePresentationIntegration = callable("prepare_presentation_integration");
callable("preview_supervised_tv_switch");
const approveSupervisedTvSwitch = callable("approve_supervised_tv_switch");
const executeSupervisedTvSwitch = callable("execute_supervised_tv_switch");
const approveSupervisedPortableSwitch = callable("approve_supervised_portable_switch");
const executeSupervisedPortableSwitch = callable("execute_supervised_portable_switch");
const acknowledgeSupervisedTvSwitch = callable("acknowledge_supervised_tv_switch");
const getSupervisedTvSwitchStatus = callable("get_supervised_tv_switch_status");
const approveSafeDisconnectShutdown = callable("approve_safe_disconnect_shutdown");
const executeSafeDisconnectShutdown = callable("execute_safe_disconnect_shutdown");
const getTransitionJournalStatus = callable("get_transition_journal_status");
const acknowledgeSleepJournal = callable("acknowledge_sleep_journal");
const getProcessReleaseStatus = callable("get_process_release_status");
const previewProcessRelease = callable("preview_process_release");
const approveProcessRelease = callable("approve_process_release");
const executeProcessRelease = callable("execute_process_release");
const acknowledgeProcessRelease = callable("acknowledge_process_release");

function isSteamSuspendStore(value) {
    if (typeof value !== "object" || value === null) {
        return false;
    }
    const candidate = value;
    return (typeof candidate.BlockSuspendAction === "function"
        && typeof candidate.OnSuspendRequest === "function"
        && typeof candidate.RequestSleep === "function");
}
function createSteamSuspendAdapter(resolveStore, patchBefore) {
    let store;
    try {
        const candidate = resolveStore();
        if (!isSteamSuspendStore(candidate)) {
            return null;
        }
        store = candidate;
    }
    catch {
        return null;
    }
    return {
        acquireBlocker() {
            const nativeRelease = store.BlockSuspendAction.call(store);
            if (typeof nativeRelease !== "function") {
                throw new Error("Steam returned an invalid suspend-blocker lease");
            }
            let released = false;
            return () => {
                if (released) {
                    return;
                }
                released = true;
                nativeRelease();
            };
        },
        observeSuspendRequests(handler) {
            const patch = patchBefore(store, "OnSuspendRequest", () => handler());
            let unpatched = false;
            return () => {
                if (unpatched) {
                    return;
                }
                unpatched = true;
                patch.unpatch();
            };
        },
    };
}

function createDeckySteamSuspendAdapter() {
    return createSteamSuspendAdapter(() => DFL.findModuleExport((candidate) => isSteamSuspendStore(candidate)), (object, property, handler) => DFL.beforePatch(object, property, handler));
}

/**
 * Keep enforcement independent from a particular Decky modal host. A visible
 * fallback is preferable to silently losing the explanation when that host
 * rejects a modal from Steam's transient Power-menu lifecycle.
 */
function deliverBlockedAttempt(warning, delivery) {
    try {
        delivery.showModal();
        return "modal";
    }
    catch {
        try {
            delivery.showFallbackToast(warning);
            return "fallback";
        }
        catch {
            return "unavailable";
        }
    }
}

function humanize(value) {
    return value.replaceAll("_", " ").replaceAll(".", " ");
}
function yesNoUnknown(value) {
    return value === true ? "yes" : value === false ? "no" : "unknown";
}
function overheadMeasurementLabel(measurement) {
    if (!measurement || measurement.schema_version !== 1 || measurement.game_impact !== "unknown") {
        return "unavailable";
    }
    if (measurement.status === "observed"
        && typeof measurement.total_cost_ms === "number"
        && Number.isFinite(measurement.total_cost_ms)
        && measurement.total_cost_ms >= 0) {
        return `${Math.round(measurement.total_cost_ms)}ms observed · game impact unknown`;
    }
    if (measurement.status === "deferred") {
        return "deferred · game impact unknown";
    }
    if (measurement.status === "stale" || measurement.status === "evidence_insufficient") {
        return "evidence incomplete · game impact unknown";
    }
    return "unavailable";
}
function reportedBuildLabel(build) {
    if (!build || build.schema_version !== 1 || !/^[0-9A-Za-z.+-]{1,32}$/.test(build.version)
        || !/^[0-9a-f]{12}$/.test(build.revision) || !build.candidate_match)
        return "unavailable";
    const match = build.candidate_match === "current_candidate" ? "current candidate"
        : build.candidate_match === "different_build" ? "different build" : "comparison unavailable";
    return `v${build.version} · ${build.revision} · ${match}`;
}
function diagnosticOverlayRows(payload, dockedIgpuStatus = null, loggingStatus = null, peripheralStatus = null, actionHistory = null) {
    if (!payload) {
        return [];
    }
    const { snapshot } = payload;
    const renderer = snapshot.gpus.find((gpu) => gpu.selected_for_render === true);
    const externalGpu = snapshot.gpus.find((gpu) => gpu.role === "external");
    const externalDisplay = snapshot.displays.find((display) => display.kind === "external");
    const disconnect = snapshot.disconnect_readiness;
    const profiles = payload.diagnostics.hardware_profiles;
    const capabilities = new Map(profiles.capabilities.map((capability) => [capability.axis, capability]));
    const capability = (axis) => {
        const value = capabilities.get(axis);
        return value ? `${humanize(value.value)} · ${humanize(value.confidence)}` : "unknown";
    };
    const rows = [
        { name: "Observed mode", value: humanize(payload.inference.mode) },
        {
            name: "System health",
            value: humanize(payload.health?.state ?? "unavailable"),
        },
        {
            name: "Health blockers",
            value: payload.health?.blockers.length
                ? payload.health.blockers.map(humanize).join(", ")
                : "none",
        },
        {
            name: "eGPU attach",
            value: payload.attach_readiness
                ? `${humanize(payload.attach_readiness.stage)} · ${humanize(payload.attach_readiness.code)}`
                : "unavailable",
        },
        { name: "Snapshot schema", value: String(snapshot.schema_version) },
        { name: "Reported HDM build", value: reportedBuildLabel(payload.diagnostics.build) },
        {
            name: "Device profile",
            value: profiles.host.status === "exact"
                ? "recognized"
                : humanize(profiles.host.status),
        },
        { name: "Support tier", value: humanize(snapshot.support_tier) },
        {
            name: "Profile evidence",
            value: `host ${humanize(profiles.host.status)} · eGPU ${humanize(profiles.egpu.status)}`,
        },
        { name: "eGPU transport", value: capability("egpu_transport") },
        {
            name: "Display capability",
            value: `output ${capability("external_display_output")} · handoff ${capability("display_handoff")}`,
        },
        {
            name: "Audio capability",
            value: `output ${capability("external_audio_output")} · handoff ${capability("audio_handoff")}`,
        },
        {
            name: "Controller capability",
            value: `promote ${capability("external_controller_promotion")} · suppress ${capability("internal_controller_suppression")}`,
        },
        {
            name: "Sleep and removal",
            value: `${capability("sleep_behavior")} · ${capability("removal_behavior")}`,
        },
        {
            name: "Gamescope",
            value: `${yesNoUnknown(snapshot.gamescope.running)} · ${humanize(snapshot.gamescope.confidence)}`,
        },
        {
            name: "Observed renderer",
            value: renderer ? `${humanize(renderer.role)} · ${humanize(renderer.confidence)}` : "unknown",
        },
        {
            name: "External GPU",
            value: externalGpu
                ? `present ${yesNoUnknown(externalGpu.present)} · ${humanize(externalGpu.confidence)}`
                : "not observed",
        },
        {
            name: "eGPU link",
            value: snapshot.egpu_link.applicable
                ? `${humanize(snapshot.egpu_link.state)} · ${humanize(snapshot.egpu_link.confidence)}`
                : "not applicable",
        },
        {
            name: "eGPU link metrics",
            value: snapshot.egpu_link.applicable
                && typeof snapshot.egpu_link.speed_gtps === "number"
                && typeof snapshot.egpu_link.width_lanes === "number"
                ? `${snapshot.egpu_link.speed_gtps} GT/s · x${snapshot.egpu_link.width_lanes} lanes · current values, not a performance rating`
                : "not reported",
        },
        {
            name: "External display",
            value: externalDisplay
                ? `connected ${yesNoUnknown(externalDisplay.connected)} · active ${yesNoUnknown(externalDisplay.active)} · ${humanize(externalDisplay.confidence)}`
                : "not observed",
        },
        {
            name: "Sleep flow",
            value: snapshot.sleep_guard.required
                ? snapshot.sleep_guard.active ? "guard active" : "guard required but inactive"
                : "guard not required",
        },
        {
            name: "Disconnect scan",
            value: disconnect.applicable
                ? `${disconnect.scan_complete ? "complete" : "incomplete"} · ${disconnect.ready ? "software ready" : "blocked"}`
                : "not applicable",
        },
        {
            name: "Blocker codes",
            value: snapshot.blockers.length
                ? snapshot.blockers.map((blocker) => blocker.code).join(", ")
                : "none",
        },
        {
            name: "Stage timings",
            value: payload.diagnostics.timings_ms
                .map((timing) => `${timing.stage} ${Math.round(timing.duration_ms)}ms`)
                .join(" · ") || "unavailable",
        },
        {
            name: "HDM overhead",
            value: overheadMeasurementLabel(payload.diagnostics.overhead_measurement),
        },
        {
            name: "Verbose logging",
            value: diagnosticLoggingLabel(loggingStatus),
        },
        {
            name: "Peripheral observation",
            value: peripheralStatus
                ? `controller ${peripheralStatus.controller.exact ? "mapped" : "unmapped"} · audio ${peripheralStatus.audio.exact ? "mapped" : "unmapped"}`
                : "unavailable",
        },
        {
            name: "Peripheral evidence",
            value: peripheralStatus
                ? `${humanize(peripheralStatus.controller.code)} · ${humanize(peripheralStatus.audio.code)}`
                : "unavailable",
        },
    ];
    rows.push(...(dockedIgpuStatus
        ? [
            {
                name: "Docked-iGPU watch",
                value: `${humanize(dockedIgpuStatus.stage)} · ${humanize(dockedIgpuStatus.code)}`,
            },
            {
                name: "Promotion inspection",
                value: dockedIgpuStatus.inspection_available
                    ? "available · read-only"
                    : "unavailable",
            },
        ]
        : [
            {
                name: "Docked-iGPU watch",
                value: "unavailable",
            },
        ]));
    disconnect.clients.forEach((client, index) => {
        rows.push({
            name: `Client ${index + 1}`,
            value: `${client.name} · ${humanize(client.kind)} · ${client.resources.map(humanize).join(", ")}`,
        });
    });
    actionHistory?.entries.slice(0, 3).forEach((entry, index) => {
        rows.push({
            name: `Recent action ${index + 1}`,
            value: `${humanize(entry.kind)} · ${humanize(entry.outcome)} · ${humanize(entry.code)}`,
        });
    });
    return rows;
}
function diagnosticLoggingLabel(status) {
    if (!status) {
        return "unavailable";
    }
    if (!status.enabled) {
        return `off · ${humanize(status.code)}`;
    }
    if (status.mode === "until_reboot") {
        return "on · until reboot";
    }
    const remaining = Math.max(0, status.remaining_seconds ?? 0);
    const hours = Math.floor(remaining / 3600);
    const minutes = Math.ceil((remaining % 3600) / 60);
    const countdown = hours > 0
        ? `${hours}h ${minutes}m remaining`
        : `${minutes}m remaining`;
    return `on · ${countdown}`;
}

/** Decorative icons never substitute for the independent, text-labelled facts. */
const ICONS = {
    Mode: { color: "#9baeff", path: "M3 5h18v12H3z M8 21h8 M12 17v4" },
    Health: { color: "#7edbd2", path: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M7 12h3l2-4 2 8 2-4h2" },
    Connection: { color: "#82caff", path: "M8 3v5 M16 3v5 M6 8h12v4a6 6 0 0 1-12 0z M12 18v4" },
    Game: { color: "#c6adff", path: "M6 7h12l3 11h-5l-2-3h-4l-2 3H3z M6 11h5 M8.5 8.5v5 M16 10h.1 M18 12h.1" },
};
function StatusCard({ name, value }) {
    const icon = ICONS[name] ?? ICONS.Mode;
    return (SP_JSX.jsxs("div", { style: {
            display: "flex", alignItems: "center", gap: 12, minWidth: 0,
            padding: "12px", marginBottom: 8, borderRadius: 12,
            border: "1px solid rgba(135, 164, 224, 0.32)",
            background: "linear-gradient(120deg, rgba(62, 82, 128, 0.30), rgba(28, 39, 65, 0.35))",
        }, children: [SP_JSX.jsx("svg", { width: "24", height: "24", viewBox: "0 0 24 24", "aria-hidden": "true", style: { color: icon.color, flexShrink: 0 }, fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", children: SP_JSX.jsx("path", { d: icon.path }) }), SP_JSX.jsxs("div", { style: { minWidth: 0, lineHeight: 1.4 }, children: [SP_JSX.jsx("div", { style: { fontSize: 12, opacity: 0.8 }, children: name }), SP_JSX.jsx("div", { style: { fontSize: 15, fontWeight: 600, overflowWrap: "anywhere" }, children: value })] })] }));
}

const HEALTH_BLOCKER_MESSAGES = {
    "health.placement_degraded": "Current mode needs attention.",
    "health.placement_unknown": "Current mode needs verification.",
    "health.workflow_unknown": "HDM recovery status needs review.",
    "health.session_degraded": "Steam session is not usable.",
    "health.session_unknown": "Steam session status needs verification.",
    "health.display_degraded": "Active display is not usable.",
    "health.display_unknown": "Active display needs verification.",
    "health.egpu_link_degraded": "eGPU link is down.",
    "health.egpu_link_unknown": "eGPU link needs verification.",
    "health.storage_degraded": "eGPU storage needs attention.",
    "health.storage_unknown": "eGPU storage status needs verification.",
    "health.controller_degraded": "Built-in controls are unavailable.",
    "health.controller_unknown": "Built-in controls need verification.",
    "health.audio_degraded": "Current audio output is not usable.",
    "health.audio_unknown": "Current audio output needs verification.",
    "health.no_observations": "HDM health evidence is unavailable.",
    "health.duplicate_component": "HDM health evidence is inconsistent.",
};
function healthStatusLabel(health, loading = false) {
    if (loading) {
        return "Checking…";
    }
    switch (health?.state) {
        case "ready":
            return "Ready";
        case "recovering":
            return "Recovering";
        case "degraded":
            return "Degraded";
        case "attention_required":
            return "Needs attention";
        default:
            return "Unavailable";
    }
}
/**
 * Present only recognized public health blockers. Raw or future codes collapse
 * to one generic message, and no message is shown for a healthy payload.
 */
function healthAttentionMessages(health) {
    if (!health || health.state === "ready" || !Array.isArray(health.blockers)) {
        return [];
    }
    const messages = health.blockers.map((blocker) => HEALTH_BLOCKER_MESSAGES[blocker] ?? "HDM health evidence needs review.");
    return [...new Set(messages)].slice(0, 3);
}

function isEgpuRelevantPlacement(mode) {
    return ["boosted_handheld", "docked_igpu", "docked_egpu", "tv_docked"].includes(mode);
}
function reasonFor(payload) {
    const link = payload.snapshot.egpu_link;
    return link.reason || link.error || "link_unverified";
}
/**
 * Turn read-only link observations into sparse player notifications. A link
 * sample has no removal, recovery, or cable-fault authority; it can only ask
 * the player to review the current observation.
 */
function decideLinkHealthNotification(previous, payload) {
    const link = payload.snapshot.egpu_link;
    if (!link.applicable) {
        return { memory: null, notification: null };
    }
    if (!isEgpuRelevantPlacement(payload.inference.mode)) {
        return { memory: previous, notification: null };
    }
    const current = {
        state: link.state,
        reason: reasonFor(payload),
        instabilityNotified: previous?.instabilityNotified ?? false,
    };
    if (previous === null) {
        return { memory: current, notification: null };
    }
    if (previous.state === current.state && previous.reason === current.reason) {
        return { memory: current, notification: null };
    }
    if (current.state === "up") {
        const wasUnstable = previous.state !== "up" && previous.instabilityNotified === true;
        return {
            memory: { ...current, instabilityNotified: false },
            notification: wasUnstable
                ? {
                    title: "eGPU link observed again",
                    body: "HDM is preserving the current setup. Verify the display and controls before changing it.",
                    critical: false,
                }
                : null,
        };
    }
    if (previous.instabilityNotified === true) {
        return { memory: { ...current, instabilityNotified: true }, notification: null };
    }
    return {
        memory: { ...current, instabilityNotified: true },
        notification: {
            title: current.state === "down" ? "eGPU link is down" : "eGPU link needs verification",
            body: "HDM is preserving the current setup. Avoid disconnecting until the link is stable.",
            critical: false,
        },
    };
}

const STATES = {
    deferred_dock: new Set(["deferred", "eligible", "cancelled", "expired", "invalidated", "rejected"]),
    prepared_docked_idle: new Set(["not_yet_stable", "prepared", "invalidated"]),
    safe_undock: new Set(["ready_for_revalidation", "not_ready", "evidence_insufficient", "invalidated"]),
    unexpected_removal_recovery: new Set(["portable_fallback_verified", "recovery_incomplete", "needs_supervised_diagnosis"]),
    link_instability: new Set(["stable_observed", "instability_observed", "evidence_insufficient"]),
    offline_readiness: new Set(["ready_to_try_offline", "needs_attention", "online_check_needed", "unknown"]),
};
function record(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value)
        ? value
        : null;
}
function state(value, allowed) {
    const candidate = record(value)?.state;
    return typeof candidate === "string" && allowed.has(candidate) ? candidate : null;
}
/**
 * Accept only known public journey states. Raw codes, reason lists, and all
 * unknown fields are intentionally discarded before Quick Access presentation.
 */
function sanitizeJourneyStatus(value) {
    const source = record(value);
    if (!source)
        return undefined;
    const result = {};
    for (const key of [
        "deferred_dock",
        "prepared_docked_idle",
        "safe_undock",
        "unexpected_removal_recovery",
    ]) {
        const valueState = state(source[key], STATES[key]);
        if (valueState)
            result[key] = { state: valueState, code: "" };
    }
    const link = record(source.link_instability);
    if (link?.schema_version === 1
        && typeof link.status === "string"
        && STATES.link_instability.has(link.status)
        && ((typeof link.current_state === "string" && ["up", "down"].includes(link.current_state))
            || (link.current_state === null && link.status === "evidence_insufficient"))) {
        result.link_instability = {
            schema_version: 1,
            status: link.status,
            code: "",
            current_state: link.current_state,
        };
    }
    const offline = record(source.offline_readiness);
    if (offline?.schema_version === 1
        && typeof offline.status === "string"
        && STATES.offline_readiness.has(offline.status)) {
        result.offline_readiness = {
            schema_version: 1,
            status: offline.status,
            reason_codes: [],
        };
    }
    return Object.keys(result).length ? result : undefined;
}

/** Small, controller-first presentation helpers for the Quick Access panel. */
/** Keep secondary evidence and tools behind the single Troubleshoot disclosure. */
function quickAccessSectionVisibility(troubleshootingOpen) {
    return {
        journey: troubleshootingOpen,
        sleepProtection: troubleshootingOpen,
        disconnectReadiness: troubleshootingOpen,
        support: troubleshootingOpen,
        diagnostics: troubleshootingOpen,
        navigation: troubleshootingOpen,
    };
}
/**
 * Keep the first screen to four player-facing facts. Technical evidence stays
 * behind the explicit troubleshooting control.
 */
function atAGlanceRows(state) {
    return [
        ["Mode", state.mode],
        ["Health", state.health],
        ["Connection", state.connection],
        ["Game", state.game],
    ];
}
const JOURNEY_STATES = {
    deferred_dock: {
        deferred: ["Waiting for game to close", "A player request remains evidence only."],
        eligible: ["Fresh idle evidence", "A future transition owner must revalidate."],
        cancelled: ["Cancelled", "No dock request remains."],
        expired: ["Expired", "A new player request is required."],
        invalidated: ["Needs revalidation", "The prior dock evidence changed or became stale."],
        rejected: ["Not available", "A direct request needs a verified running game."],
    },
    prepared_docked_idle: {
        not_yet_stable: ["Stabilizing", "Fresh idle evidence has not matured yet."],
        prepared: ["Prepared evidence", "A future owner must still revalidate."],
        invalidated: ["Needs revalidation", "Prepared evidence changed or became stale."],
    },
    safe_undock: {
        ready_for_revalidation: ["Needs revalidation", "This is not a physical-unplug approval."],
        not_ready: ["Not ready", "Current Safe Undock evidence does not meet the gate."],
        evidence_insufficient: ["Evidence incomplete", "Collect fresh supervised evidence before deciding."],
        invalidated: ["Needs revalidation", "The Safe Undock evidence changed or became stale."],
    },
    unexpected_removal_recovery: {
        portable_fallback_verified: ["Portable fallback observed", "This does not claim hardware recovery or game survival."],
        recovery_incomplete: ["Recovery incomplete", "Handheld fallback evidence is incomplete."],
        needs_supervised_diagnosis: ["Needs supervised diagnosis", "Evidence is unknown, stale, or contradictory."],
    },
    link_instability: {
        stable_observed: ["Stable state observed", "Two observed samples matched; this is not a performance or link-quality rating."],
        instability_observed: ["State change observed", "Review the current link observation; HDM does not diagnose cable quality."],
        evidence_insufficient: ["Evidence incomplete", "Fresh observed link evidence is unavailable."],
    },
    offline_readiness: {
        ready_to_try_offline: ["Ready to try offline", "Current local evidence is encouraging, but offline play is not guaranteed."],
        needs_attention: ["Needs attention", "Resolve local readiness concerns before relying on offline play."],
        online_check_needed: ["Online check needed", "This may need an online check; offline play is not guaranteed."],
        unknown: ["Unknown", "Fresh reviewed offline evidence is unavailable."],
    },
};
function journeyStatusRows(journey) {
    const rows = [
        ["deferred_dock", "Dock request"],
        ["prepared_docked_idle", "Prepared state"],
        ["safe_undock", "Safe Undock evidence"],
        ["unexpected_removal_recovery", "Recovery"],
        ["link_instability", "Link evidence"],
        ["offline_readiness", "Offline readiness"],
    ];
    return rows.map(([key, name]) => {
        const value = journey?.[key];
        const state = value && ("status" in value ? value.status : value.state);
        const presentation = state && JOURNEY_STATES[key][state];
        return presentation
            ? { name, value: presentation[0], detail: presentation[1] }
            : {
                name,
                value: "Not connected",
                detail: "This local classifier is not yet wired into read-only snapshot delivery.",
            };
    });
}
/** Keep the controller-first journey summary quiet until a read-only source wires it. */
function compactJourneyStatusRows(journey) {
    const rows = journeyStatusRows(journey);
    const connected = rows.filter((row) => row.value !== "Not connected");
    return connected.length > 0
        ? connected
        : [{
                name: "Status",
                value: "Not connected",
                detail: "No read-only journey status is connected yet. Open details to review each future status source.",
            }];
}
/** Reveal newly expanded detail without moving controller focus away from its toggle. */
function revealJourneyDetails(anchor) {
    if (!anchor) {
        return false;
    }
    anchor.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return true;
}
/** State reset used before returning controller focus to the compact status. */
function compactStatusPanels() {
    return { showDiagnostics: false, showJourneyDetails: false };
}
/**
 * Steam can otherwise send controller focus to the QAM Back control after a
 * long panel collapses. Focus a native in-panel control after the owning panel
 * has been scrolled back to its first row.
 */
function restoreQuickAccessFocus(findFirstControl) {
    const control = findFirstControl();
    if (!control) {
        return false;
    }
    control.focus({ preventScroll: true });
    return true;
}

const EMPTY_VALUES = {
    dockedIgpuStatus: null,
    diagnosticLoggingStatus: null,
    peripheralStatus: null,
    actionHistory: null,
};
function shouldCollectOptionalDiagnostics(visible, gameState) {
    return visible && gameState === "idle";
}
function optionalCall(source) {
    return Promise.resolve().then(source).catch(() => null);
}
async function collectOptionalDiagnostics(visible, sources) {
    if (!visible) {
        return EMPTY_VALUES;
    }
    const [dockedIgpuStatus, diagnosticLoggingStatus, peripheralStatus, actionHistory] = await Promise.all([
        optionalCall(sources.getDockedIgpuStatus),
        optionalCall(sources.getDiagnosticLoggingStatus),
        optionalCall(sources.getPeripheralStatus),
        optionalCall(sources.getActionHistory),
    ]);
    return {
        dockedIgpuStatus,
        diagnosticLoggingStatus,
        peripheralStatus,
        actionHistory,
    };
}

const DISCOVERY_REFRESH_MS = 1_000;
const SETTLING_REFRESH_MS = 750;
const STABLE_REFRESH_MS = 3_000;
const ACTIVE_GAME_REFRESH_MS = 5_000;
const BACKGROUND_REFRESH_MS = 5_000;
function firstHardwareBlocker(payload) {
    const blocker = payload.snapshot.blockers.find((item) => (item.code === "egpu_identity_unverified"
        || item.code === "drm_inventory_unavailable"
        || item.code === "active_display_unknown"
        || item.code === "render_gpu_unknown"
        || item.code === "gamescope_unverified"
        || item.code === "render_selector_conflict"
        || item.code === "game_state_unknown"));
    return blocker?.message ?? "Waiting for complete hardware evidence.";
}
function exactEgpuState(payload) {
    const profile = payload.diagnostics?.hardware_profiles?.egpu?.status;
    const external = payload.snapshot.gpus.filter((gpu) => (gpu.role === "external" && gpu.present && gpu.confidence === "verified"));
    if (profile === "exact" && external.length === 1) {
        return "exact";
    }
    return profile === "absent" ? "absent" : "unknown";
}
function connectionProgress(payload) {
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
    if (snapshot.egpu_link.applicable !== true
        || snapshot.egpu_link.state !== "up"
        || snapshot.egpu_link.confidence !== "observed") {
        return {
            label: snapshot.egpu_link.applicable && snapshot.egpu_link.state === "down"
                ? "eGPU link needs attention"
                : "eGPU link needs verification",
            detail: "HDM is preserving the current setup. Verify the display and controls before changing it.",
            settling: true,
        };
    }
    const external = snapshot.displays.filter((display) => display.kind === "external" && display.connected === true);
    if (external.length === 0) {
        return {
            label: "eGPU detected",
            detail: "Waiting for a connected TV output.",
            settling: false,
        };
    }
    if (external.length !== 1
        || external[0].edid_ready !== true
        || external[0].active === null
        || external[0].confidence !== "verified") {
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
    if (snapshot.gamescope.running !== true
        || snapshot.gamescope.confidence !== "verified") {
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
function refreshDelayForSnapshot(payload) {
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
    if (progress.settling
        || !snapshot.disconnect_readiness.scan_complete
        || snapshot.sleep_guard.confidence === "unknown"
        || (snapshot.sleep_guard.required && !snapshot.sleep_guard.active)) {
        return SETTLING_REFRESH_MS;
    }
    return progress.label === "TV Docked" ? STABLE_REFRESH_MS : DISCOVERY_REFRESH_MS;
}
/**
 * Keep the always-rendered Decky panel out of the player's way while Quick
 * Access is closed. Backend sleep protection remains independently active, and
 * reopening Quick Access immediately re-enters the ordinary adaptive cadence.
 */
function refreshDelayForVisibility(payload, quickAccessVisible) {
    return quickAccessVisible
        ? refreshDelayForSnapshot(payload)
        : BACKGROUND_REFRESH_MS;
}

function processReleaseOutcomeMessage(outcome) {
    if (!outcome.accepted) {
        return "Process-release approval expired or was rejected. Inspect again.";
    }
    if (outcome.software_blockers_cleared) {
        return "Software blockers cleared. Physical eGPU removal is still not authorized; shut down before disconnecting.";
    }
    if (outcome.force_receipt_token) {
        return "A process still holds the eGPU. Force close requires a separate confirmation and may lose unsaved work.";
    }
    if (outcome.action_required) {
        return "Process release needs attention. Acknowledge the result, inspect again, and do not disconnect the eGPU.";
    }
    return "Software blockers remain. Acknowledge the result and inspect again; do not disconnect the eGPU.";
}
function canOfferForce(outcome) {
    return Boolean(outcome.accepted
        && !outcome.software_blockers_cleared
        && outcome.force_receipt_token
        && outcome.acknowledgement_id);
}

function messageFrom(error) {
    return error instanceof Error && error.message
        ? error.message
        : "Unknown Steam preflight error";
}
function requiresPreflightBlocker(observation) {
    return !(observation.kind === "fresh"
        && observation.guardRequired === false
        && observation.guardConfidence === "verified");
}
function observationFromSnapshotEvidence(evidence, nowMs, staleAfterMs) {
    const observedAtMs = Date.parse(evidence.observedAt);
    const ageMs = nowMs - observedAtMs;
    if (evidence.schemaVersion !== 3
        || !Number.isFinite(observedAtMs)
        || ageMs > staleAfterMs
        || ageMs < -staleAfterMs) {
        return { kind: "stale" };
    }
    return {
        kind: "fresh",
        guardRequired: evidence.guardRequired,
        guardConfidence: evidence.guardConfidence,
        gameState: evidence.gameState,
        gameUsesEgpu: evidence.gameUsesEgpu,
    };
}
function warningForBlockedAttempt(observation) {
    if (observation.kind === "fresh"
        && observation.guardRequired
        && observation.gameUsesEgpu) {
        return {
            kind: "game",
            title: "Sleep blocked — game is using the eGPU",
            body: "Close the game and restore Portable before disconnecting the eGPU. The sleep request was not started.",
            critical: true,
        };
    }
    if (observation.kind === "fresh"
        && observation.guardRequired
        && observation.gameState !== "unknown") {
        return {
            kind: "standard",
            title: "Sleep blocked while an eGPU is attached",
            body: "This eGPU is known to wake the handheld immediately. Restore Portable and shut down before disconnecting it.",
            critical: false,
        };
    }
    return {
        kind: "unknown",
        title: "Sleep blocked — safety state is unknown",
        body: "HDM could not verify that the eGPU is safely absent, so the sleep request was not started.",
        critical: true,
    };
}
class SleepPreflightCoordinator {
    adapter;
    onBlockedAttempt;
    blockerRelease = null;
    observerRelease = null;
    observation = { kind: "loading" };
    started = false;
    stopped = false;
    acquireFailed = false;
    lifecycleError = "";
    blockedAttemptCount = 0;
    constructor(adapter, onBlockedAttempt) {
        this.adapter = adapter;
        this.onBlockedAttempt = onBlockedAttempt;
    }
    start() {
        if (this.started || this.stopped) {
            return this.status();
        }
        this.started = true;
        // The blocker must exist before any asynchronous snapshot request starts.
        this.acquireBlocker();
        if (this.adapter && this.blockerRelease) {
            try {
                this.observerRelease = this.adapter.observeSuspendRequests(() => {
                    if (this.blockerRelease) {
                        this.blockedAttemptCount += 1;
                        this.onBlockedAttempt(warningForBlockedAttempt(this.observation));
                    }
                });
            }
            catch (error) {
                this.lifecycleError = `Sleep is blocked, but the attempted-action warning is unavailable: ${messageFrom(error)}`;
            }
        }
        return this.status();
    }
    reconcile(observation) {
        if (this.stopped) {
            return this.status();
        }
        this.observation = observation;
        if (requiresPreflightBlocker(observation)) {
            this.acquireBlocker();
        }
        else {
            this.releaseBlocker();
        }
        return this.status();
    }
    stop() {
        if (this.stopped) {
            return this.status();
        }
        this.stopped = true;
        const releaseObserver = this.observerRelease;
        this.observerRelease = null;
        if (releaseObserver) {
            try {
                releaseObserver();
            }
            catch (error) {
                this.lifecycleError = `Failed to remove the Steam sleep warning hook: ${messageFrom(error)}`;
            }
        }
        this.releaseBlocker();
        return this.status();
    }
    status() {
        const reason = this.observation.kind === "fresh"
            ? this.observation.guardRequired
                ? "required"
                : "verified_absent"
            : this.observation.kind;
        if (!this.adapter || this.acquireFailed) {
            return {
                state: "unavailable",
                blocking: false,
                attemptWarningAvailable: false,
                blockedAttemptCount: this.blockedAttemptCount,
                reason,
                error: this.lifecycleError || "Steam's native suspend blocker could not be resolved.",
            };
        }
        if (this.blockerRelease) {
            return {
                state: "active",
                blocking: true,
                attemptWarningAvailable: this.observerRelease !== null,
                blockedAttemptCount: this.blockedAttemptCount,
                reason,
                error: this.lifecycleError,
            };
        }
        return {
            state: "inactive",
            blocking: false,
            attemptWarningAvailable: false,
            blockedAttemptCount: this.blockedAttemptCount,
            reason,
            error: this.lifecycleError,
        };
    }
    acquireBlocker() {
        if (!this.started
            || this.stopped
            || !this.adapter
            || this.blockerRelease
            || this.acquireFailed) {
            return;
        }
        try {
            const release = this.adapter.acquireBlocker();
            if (typeof release !== "function") {
                throw new Error("Steam did not return a suspend-blocker release callback");
            }
            this.blockerRelease = release;
        }
        catch (error) {
            // Do not retry in the same plugin lifecycle: a failed call may have
            // incremented Steam's blocker count without returning its release handle.
            this.acquireFailed = true;
            this.lifecycleError = `Steam preflight acquisition failed: ${messageFrom(error)}`;
        }
    }
    releaseBlocker() {
        const release = this.blockerRelease;
        this.blockerRelease = null;
        if (!release) {
            return;
        }
        try {
            release();
        }
        catch (error) {
            this.acquireFailed = true;
            this.lifecycleError = `Steam preflight release failed: ${messageFrom(error)}`;
        }
    }
}

const LABELS = {
    "journal.foreign_workflow": "Another workflow needs attention",
    "automatic_dock.rearmed_after_acknowledgement": "Re-checking attachment",
    "automatic_dock.suppressed_for_safe_disconnect": "Waiting for G1 removal",
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
];
function scrollToTopOfOwningPanel(anchor) {
    // A Decky quick-access plugin is hosted inside Steam's scroll container, not
    // the browser window. Find that container rather than assuming a particular
    // Steam class name (which changes between client builds).
    let candidate = anchor.parentElement;
    while (candidate) {
        const overflowY = window.getComputedStyle(candidate).overflowY;
        if ((overflowY === "auto" || overflowY === "scroll")
            && candidate.scrollHeight > candidate.clientHeight) {
            candidate.scrollTo({ top: 0, behavior: "smooth" });
            return;
        }
        candidate = candidate.parentElement;
    }
    // This remains useful for a future Decky host that does not expose its
    // scrolling element through the DOM hierarchy above the plugin content.
    anchor.scrollIntoView({ block: "start", behavior: "smooth" });
}
function label(value) {
    return LABELS[value] ?? value.replaceAll("_", " ").replaceAll(".", " ");
}
function DiagnosticRow({ name, value }) {
    return (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { display: "flex", justifyContent: "space-between", gap: "12px", width: "100%" }, children: [SP_JSX.jsx("span", { children: name }), SP_JSX.jsx("span", { style: { opacity: 0.72, textAlign: "right" }, children: value })] }) }));
}
function showSupportBundlePreview(preview, onClose) {
    let modal;
    const close = () => {
        modal.Close();
        onClose();
    };
    // Let Decky resolve Steam's visible SP window. This plugin executes in the
    // invisible SharedJSContext, so using its global window hides the dialog.
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: "Redacted support bundle preview", strOKButtonText: "Close preview", bAlertDialog: true, bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: close, children: SP_JSX.jsxs("div", { style: { fontSize: "12px", lineHeight: "17px" }, children: [SP_JSX.jsx("p", { children: "Review this exact redacted JSON before copying or saving it. The save approval expires after five minutes and can be used once." }), SP_JSX.jsx("div", { style: { maxHeight: "55vh", overflow: "hidden" }, children: SP_JSX.jsx(DFL.ScrollPanel, { children: SP_JSX.jsx("pre", { style: { whiteSpace: "pre-wrap" }, children: preview.preview_json }) }) })] }) }), window, { strTitle: "Handheld Dock Mode", bNeverPopOut: true });
    return modal;
}
function showPresentationPreparationConfirmation(onConfirm, onClose) {
    let modal;
    const close = () => {
        modal.Close();
        onClose();
    };
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: "Prepare experimental display validation?", strOKButtonText: "Prepare", strCancelButtonText: "Cancel", bDestructiveWarning: true, bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: () => {
            close();
            onConfirm();
        }, onCancel: close, children: SP_JSX.jsxs("div", { style: { fontSize: "13px", lineHeight: "18px" }, children: [SP_JSX.jsx("p", { children: "Continue only with the eGPU disconnected, no game running, and the handheld screen visible." }), SP_JSX.jsx("p", { children: "This installs HDM's reversible Gamescope startup integration and reloads the user service configuration. It does not restart Gamescope, switch displays, or select a GPU." })] }) }), window, { strTitle: "Handheld Dock Mode", bNeverPopOut: true });
    return modal;
}
function showAutomaticDockConfirmation(onConfirm, onClose) {
    let modal;
    const close = () => {
        modal.Close();
        onClose();
    };
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: "Enable automatic TV docking?", strOKButtonText: "Enable", strCancelButtonText: "Cancel", bDestructiveWarning: true, bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: () => {
            close();
            onConfirm();
        }, onCancel: close, children: SP_JSX.jsxs("div", { style: { fontSize: "13px", lineHeight: "18px" }, children: [SP_JSX.jsx("p", { children: "When HDM verifies this Ally X, the exact GPD G1, one ready TV, a healthy link, and no running game, it will restart Steam Game Mode onto the TV." }), SP_JSX.jsx("p", { children: "The screen will briefly show Steam shutting down. USB4 presence alone never triggers the restart, and physical live removal remains unsupported." })] }) }), window, { strTitle: "Handheld Dock Mode", bNeverPopOut: true });
    return modal;
}
function showSafeDisconnectConfirmation(portable, onConfirm, onClose) {
    let modal;
    const close = () => {
        modal.Close();
        onClose();
    };
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: portable ? "Shut down for G1 disconnect?" : "Return to Ally for G1 disconnect?", strOKButtonText: portable ? "Shut down" : "Return to Ally", strCancelButtonText: "Cancel", bDestructiveWarning: true, bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: () => {
            close();
            onConfirm();
        }, onCancel: close, children: SP_JSX.jsx("div", { style: { fontSize: "13px", lineHeight: "18px" }, children: portable ? (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx("p", { children: "HDM will revalidate idle Portable mode and request a normal system shutdown." }), SP_JSX.jsx("p", { children: "The request cannot prove physical power-off. Keep the G1 connected until the fan stops and every top power LED is off." }), SP_JSX.jsx("p", { children: "If the fan remains on after 60 seconds, keep the G1 connected and hold the Ally power button until the fan stops." })] })) : (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx("p", { children: "HDM will require no running game, then restart Game Mode on the Ally display." }), SP_JSX.jsx("p", { children: "After Portable is verified, acknowledge the result and use this control again to shut down. Do not unplug yet." })] })) }) }), window, { strTitle: "Handheld Dock Mode", bNeverPopOut: true });
    return modal;
}
function showPresentationPreparationBlocked(blockers) {
    // The preparation result appears below its controller-focused button. Steam's
    // Quick Access navigation can leave that row off-screen, so also surface the
    // outcome immediately without requiring touch scrolling. Keep the message
    // categorical: integration ownership belongs in diagnostics, not a player
    // instruction to edit another plugin's files.
    const ownsPresentationPath = blockers.some((blocker) => blocker.includes("path") || blocker.includes("integration"));
    toaster.toast({
        title: "Display validation is not ready",
        body: ownsPresentationPath
            ? "Another display integration is active. HDM will not replace it."
            : `Preparation blocked: ${blockers.map(label).join(", ")}.`,
        critical: true,
        duration: 12000,
    });
}
function showProcessReleaseConfirmation(preview, onConfirm, onClose) {
    let modal;
    const force = preview.phase === "force";
    const close = () => {
        modal.Close();
        onClose();
    };
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: force ? "Force close eGPU processes?" : "Close eGPU processes?", strOKButtonText: force ? "Force close" : "Close gracefully", strCancelButtonText: "Cancel", bDestructiveWarning: true, bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: () => {
            close();
            onConfirm();
        }, onCancel: close, children: SP_JSX.jsxs("div", { style: { fontSize: "13px", lineHeight: "18px" }, children: [SP_JSX.jsx("p", { children: force
                        ? "Force close may lose unsaved work. Only the exact processes that survived the approved graceful attempt are eligible."
                        : "HDM will request a graceful close only for the exact ordinary user processes listed below." }), preview.targets.map((target, index) => (SP_JSX.jsxs("p", { children: [target.name, " \u2014 ", target.resources.map(label).join(", ")] }, `${target.name}-${index}`))), preview.protected_client_count > 0 && (SP_JSX.jsxs("p", { children: [preview.protected_client_count, " protected client(s) will not be closed."] })), SP_JSX.jsx("p", { children: "Clearing software clients does not authorize physical eGPU removal. Shut down before disconnecting the eGPU." })] }) }), window, { strTitle: "Handheld Dock Mode", bNeverPopOut: true });
    return modal;
}
function showDiagnosticLoggingConfirmation(durationLabel, onConfirm, onClose) {
    let modal;
    const close = () => {
        modal.Close();
        onClose();
    };
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: "Enable verbose HDM diagnostics?", strOKButtonText: "Enable", strCancelButtonText: "Cancel", bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: () => {
            close();
            onConfirm();
        }, onCancel: close, children: SP_JSX.jsxs("div", { style: { fontSize: "13px", lineHeight: "18px" }, children: [SP_JSX.jsxs("p", { children: ["HDM will retain additional sanitized, HDM-only events for ", durationLabel, ". Storage remains capped and verbose logging will not survive a reboot."] }), SP_JSX.jsx("p", { children: "Logs stay on this handheld unless you separately preview, save, and share a support bundle." })] }) }), window, { strTitle: "Handheld Dock Mode", bNeverPopOut: true });
    return modal;
}
function MonitorIcon() {
    return (SP_JSX.jsxs("svg", { width: "24", height: "24", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", children: [SP_JSX.jsx("rect", { x: "3", y: "4", width: "18", height: "13", rx: "2" }), SP_JSX.jsx("path", { d: "M8 21h8M12 17v4" })] }));
}
function preflightObservation(payload) {
    const { snapshot } = payload;
    return observationFromSnapshotEvidence({
        schemaVersion: snapshot.schema_version,
        observedAt: snapshot.observed_at,
        guardRequired: snapshot.sleep_guard.required,
        guardConfidence: snapshot.sleep_guard.confidence,
        gameState: snapshot.game_state,
        gameUsesEgpu: snapshot.disconnect_readiness.clients.some((client) => client.kind === "game"),
    }, Date.now(), SNAPSHOT_STALE_AFTER_MS);
}
function Content({ preflight }) {
    const quickAccessVisible = useQuickAccessVisible();
    const statusAnchor = SP_REACT.useRef(null);
    const statusFocusAnchor = SP_REACT.useRef(null);
    const primaryControlAnchor = SP_REACT.useRef(null);
    const journeyDetailsAnchor = SP_REACT.useRef(null);
    const [payload, setPayload] = SP_REACT.useState(null);
    const [peripheralStatus, setPeripheralStatus] = SP_REACT.useState(null);
    const [actionHistory, setActionHistory] = SP_REACT.useState(null);
    const [automaticDockStatus, setAutomaticDockStatus] = SP_REACT.useState(null);
    const [automaticDockBusy, setAutomaticDockBusy] = SP_REACT.useState(false);
    const [automaticDockMessage, setAutomaticDockMessage] = SP_REACT.useState("");
    const [safeDisconnectBusy, setSafeDisconnectBusy] = SP_REACT.useState(false);
    const [safeDisconnectMessage, setSafeDisconnectMessage] = SP_REACT.useState("");
    const [dockedIgpuStatus, setDockedIgpuStatus] = SP_REACT.useState(null);
    const [dockedIgpuMessage, setDockedIgpuMessage] = SP_REACT.useState("");
    const [diagnosticLoggingStatus, setDiagnosticLoggingStatus] = SP_REACT.useState(null);
    const [diagnosticLoggingDuration, setDiagnosticLoggingDuration] = SP_REACT.useState("2_hours");
    const [diagnosticLoggingBusy, setDiagnosticLoggingBusy] = SP_REACT.useState(false);
    const [diagnosticLoggingMessage, setDiagnosticLoggingMessage] = SP_REACT.useState("");
    const [error, setError] = SP_REACT.useState("");
    const [loading, setLoading] = SP_REACT.useState(true);
    const [preflightStatus, setPreflightStatus] = SP_REACT.useState(() => preflight.status());
    const [sleepWarningHidden, setSleepWarningHidden] = SP_REACT.useState(() => (localStorage.getItem(SLEEP_WARNING_KEY) === "1"
        || localStorage.getItem(LEGACY_SLEEP_WARNING_KEY) === "1"));
    const [supportPreview, setSupportPreview] = SP_REACT.useState(null);
    const [supportBusy, setSupportBusy] = SP_REACT.useState(false);
    const [supportMessage, setSupportMessage] = SP_REACT.useState("");
    const [showDiagnostics, setShowDiagnostics] = SP_REACT.useState(false);
    const [showJourneyDetails, setShowJourneyDetails] = SP_REACT.useState(false);
    const [presentationBusy, setPresentationBusy] = SP_REACT.useState(false);
    const [presentationMessage, setPresentationMessage] = SP_REACT.useState("");
    const [tvSwitchBusy, setTvSwitchBusy] = SP_REACT.useState(false);
    const [tvSwitchMessage, setTvSwitchMessage] = SP_REACT.useState("");
    const [tvSwitchAcknowledgementId, setTvSwitchAcknowledgementId] = SP_REACT.useState("");
    const [journalStatus, setJournalStatus] = SP_REACT.useState(null);
    const [journalBusy, setJournalBusy] = SP_REACT.useState(false);
    const [journalMessage, setJournalMessage] = SP_REACT.useState("");
    const [processBusy, setProcessBusy] = SP_REACT.useState(false);
    const [processMessage, setProcessMessage] = SP_REACT.useState("");
    const [processAcknowledgementId, setProcessAcknowledgementId] = SP_REACT.useState("");
    const [forceReceiptToken, setForceReceiptToken] = SP_REACT.useState("");
    const lastSnapshotAt = SP_REACT.useRef(null);
    const refreshInFlight = SP_REACT.useRef(false);
    const warningToastShown = SP_REACT.useRef(false);
    const inactiveToastShown = SP_REACT.useRef(false);
    const linkHealthNotification = SP_REACT.useRef(null);
    const supportModal = SP_REACT.useRef(null);
    const presentationModal = SP_REACT.useRef(null);
    const automaticDockModal = SP_REACT.useRef(null);
    const safeDisconnectModal = SP_REACT.useRef(null);
    const processModal = SP_REACT.useRef(null);
    const diagnosticLoggingModal = SP_REACT.useRef(null);
    const refreshTransitionJournal = SP_REACT.useCallback(async () => {
        try {
            const status = await getTransitionJournalStatus();
            setJournalStatus(status);
            if (status.code === "journal.idle") {
                setJournalMessage("");
            }
            else if (status.owner === "sleep" && status.acknowledgement_required) {
                setJournalMessage("A prior sleep result must be acknowledged before HDM can switch displays.");
            }
            else if (status.code === "journal.recovery_required") {
                setJournalMessage(`An interrupted ${label(status.owner)} workflow requires recovery. HDM will not retry it automatically.`);
            }
            else if (status.owner === "unknown") {
                setJournalMessage("The safety journal owner is unknown. HDM will not clear it or switch displays.");
            }
            else {
                setJournalMessage(`A prior ${label(status.owner)} result still needs attention.`);
            }
        }
        catch {
            setJournalStatus(null);
            setJournalMessage("Shared safety-journal status is unavailable. HDM will not switch displays.");
        }
    }, []);
    SP_REACT.useEffect(() => () => {
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
    SP_REACT.useEffect(() => {
        void refreshTransitionJournal();
    }, [refreshTransitionJournal]);
    SP_REACT.useEffect(() => {
        let disposed = false;
        void getAutomaticDockStatus().then((status) => {
            if (!disposed)
                setAutomaticDockStatus(status);
        }).catch(() => {
            if (!disposed) {
                setAutomaticDockMessage("Automatic docking status is unavailable; no restart will be requested.");
            }
        });
        return () => {
            disposed = true;
        };
    }, []);
    SP_REACT.useEffect(() => {
        let disposed = false;
        void getProcessReleaseStatus().then((status) => {
            if (disposed
                || status.code === "process_release.idle"
                || status.code === "process_release.foreign_journal") {
                return;
            }
            if (status.acknowledgement_required && status.acknowledgement_id) {
                setProcessAcknowledgementId(status.acknowledgement_id);
            }
            setProcessMessage(status.action_required
                ? "A prior process-release attempt needs acknowledgement. Do not disconnect the eGPU."
                : `Previous process-release result: ${label(status.code)}.`);
        }).catch(() => {
            if (!disposed) {
                setProcessMessage("Process-release safety state is unavailable. Do not disconnect the eGPU.");
            }
        });
        return () => {
            disposed = true;
        };
    }, []);
    SP_REACT.useEffect(() => {
        let disposed = false;
        void getSupervisedTvSwitchStatus().then((status) => {
            if (disposed
                || status.code === "transition.idle"
                || status.code === "transition.foreign_journal") {
                return;
            }
            if (status.acknowledgement_required && status.acknowledgement_id) {
                setTvSwitchAcknowledgementId(status.acknowledgement_id);
            }
            setTvSwitchMessage(status.action_required
                ? "A prior display transition needs acknowledgement. HDM did not claim its target is active."
                : `Previous display transition result: ${label(status.code)}.`);
        }).catch(() => {
            if (!disposed) {
                setTvSwitchMessage("Display-transition safety state is unavailable. HDM did not claim success.");
            }
        });
        return () => {
            disposed = true;
        };
    }, []);
    const refresh = SP_REACT.useCallback(async (quiet = false) => {
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
            }
            catch {
                setAutomaticDockMessage("Automatic docking status is unavailable; no restart will be requested.");
            }
            await refreshTransitionJournal();
            const linkDecision = decideLinkHealthNotification(linkHealthNotification.current, nextPayload);
            linkHealthNotification.current = linkDecision.memory;
            if (linkDecision.notification) {
                try {
                    toaster.toast(linkDecision.notification);
                }
                catch {
                    // A transient QAM toast-host failure must not turn a successful
                    // read-only snapshot into an apparent hardware failure.
                }
            }
            const optionalDiagnostics = await collectOptionalDiagnostics(shouldCollectOptionalDiagnostics(quickAccessVisible && showDiagnostics, nextPayload.snapshot.game_state), {
                getDockedIgpuStatus,
                getDiagnosticLoggingStatus,
                getPeripheralStatus,
                getActionHistory,
            });
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
        }
        catch {
            setError("Read-only snapshot unavailable. Check the Decky log for details.");
            setPreflightStatus(preflight.reconcile({ kind: "unavailable" }));
            return null;
        }
        finally {
            refreshInFlight.current = false;
            if (!quiet) {
                setLoading(false);
            }
        }
    }, [preflight, quickAccessVisible, refreshTransitionJournal, showDiagnostics]);
    SP_REACT.useEffect(() => {
        if (quickAccessVisible) {
            return;
        }
        const compact = compactStatusPanels();
        setShowDiagnostics(compact.showDiagnostics);
        setShowJourneyDetails(compact.showJourneyDetails);
        setDockedIgpuStatus(null);
        setDiagnosticLoggingStatus(null);
        setPeripheralStatus(null);
        setActionHistory(null);
    }, [quickAccessVisible]);
    SP_REACT.useEffect(() => {
        let disposed = false;
        let timer = null;
        const poll = async (quiet) => {
            if (lastSnapshotAt.current !== null
                && Date.now() - lastSnapshotAt.current > SNAPSHOT_STALE_AFTER_MS) {
                setPreflightStatus(preflight.reconcile({ kind: "stale" }));
            }
            const nextPayload = await refresh(quiet);
            if (!disposed) {
                timer = window.setTimeout(() => void poll(true), refreshDelayForVisibility(nextPayload, quickAccessVisible));
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
    const closeEligibleClientCount = disconnect?.clients.filter((client) => client.kind === "user" && client.close_eligible).length ?? 0;
    const disconnectStatus = loading
        ? "Reading…"
        : !disconnect?.applicable
            ? "eGPU not connected"
            : !disconnect.scan_complete
                ? "Scan incomplete — blocked"
                : disconnect.ready
                    ? "Ready"
                    : "Blocked";
    const overlayRows = diagnosticOverlayRows(payload, dockedIgpuStatus, diagnosticLoggingStatus, peripheralStatus, actionHistory);
    const optionalDiagnosticsDeferred = showDiagnostics && snapshot?.game_state !== "idle";
    const journeyRows = compactJourneyStatusRows(payload?.journey);
    const journeyDetailRows = journeyStatusRows(payload?.journey);
    const healthAttention = healthAttentionMessages(payload?.health);
    const needsAttention = Boolean(error)
        || (snapshot?.blockers.length ?? 0) > 0
        || healthAttention.length > 0;
    const acknowledgeDockedIgpuWatch = SP_REACT.useCallback(async () => {
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
        }
        catch {
            setDockedIgpuMessage("Watcher acknowledgement is unavailable.");
        }
    }, []);
    const applyDiagnosticLogging = SP_REACT.useCallback(async () => {
        setDiagnosticLoggingBusy(true);
        setDiagnosticLoggingMessage("");
        try {
            const status = await enableDiagnosticLogging(diagnosticLoggingDuration, true);
            setDiagnosticLoggingStatus(status);
            setDiagnosticLoggingMessage(status.enabled
                ? "Verbose diagnostics enabled. They remain local until separately exported."
                : "Verbose diagnostics were not enabled.");
        }
        catch {
            setDiagnosticLoggingMessage("Verbose diagnostics could not be enabled.");
        }
        finally {
            setDiagnosticLoggingBusy(false);
        }
    }, [diagnosticLoggingDuration]);
    const requestDiagnosticLogging = SP_REACT.useCallback(() => {
        const option = DIAGNOSTIC_LOGGING_OPTIONS.find((value) => value.data === diagnosticLoggingDuration);
        diagnosticLoggingModal.current?.Close();
        diagnosticLoggingModal.current = showDiagnosticLoggingConfirmation(option?.label ?? "the selected duration", () => void applyDiagnosticLogging(), () => {
            diagnosticLoggingModal.current = null;
        });
    }, [applyDiagnosticLogging, diagnosticLoggingDuration]);
    const stopDiagnosticLogging = SP_REACT.useCallback(async () => {
        setDiagnosticLoggingBusy(true);
        setDiagnosticLoggingMessage("");
        try {
            const status = await disableDiagnosticLogging();
            setDiagnosticLoggingStatus(status);
            setDiagnosticLoggingMessage("Verbose diagnostics disabled.");
        }
        catch {
            setDiagnosticLoggingMessage("Verbose diagnostics status is unavailable.");
        }
        finally {
            setDiagnosticLoggingBusy(false);
        }
    }, []);
    SP_REACT.useEffect(() => {
        if (!sleepGuard?.required) {
            warningToastShown.current = false;
            inactiveToastShown.current = false;
            return;
        }
        if (sleepGuard.active) {
            inactiveToastShown.current = false;
        }
        else if (!inactiveToastShown.current) {
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
    const hideSleepWarning = SP_REACT.useCallback(() => {
        localStorage.setItem(SLEEP_WARNING_KEY, "1");
        localStorage.removeItem(LEGACY_SLEEP_WARNING_KEY);
        setSleepWarningHidden(true);
    }, []);
    const showSleepWarning = SP_REACT.useCallback(() => {
        localStorage.removeItem(SLEEP_WARNING_KEY);
        localStorage.removeItem(LEGACY_SLEEP_WARNING_KEY);
        warningToastShown.current = false;
        setSleepWarningHidden(false);
    }, []);
    const createSupportPreview = SP_REACT.useCallback(async () => {
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
        }
        catch {
            setSupportMessage("Support bundle preview failed. No file was written.");
        }
        finally {
            setSupportBusy(false);
        }
    }, []);
    const reviewSupportPreview = SP_REACT.useCallback(() => {
        if (!supportPreview) {
            return;
        }
        supportModal.current?.Close();
        supportModal.current = showSupportBundlePreview(supportPreview, () => {
            supportModal.current = null;
        });
    }, [supportPreview]);
    const copySupportPreview = SP_REACT.useCallback(async () => {
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
        }
        catch {
            setSupportMessage("Clipboard copy is unavailable. The preview was not changed.");
        }
        finally {
            setSupportBusy(false);
        }
    }, [supportPreview]);
    const saveApprovedSupportPreview = SP_REACT.useCallback(async () => {
        if (!supportPreview) {
            return;
        }
        setSupportBusy(true);
        try {
            const result = await saveSupportBundle(supportPreview.preview_token);
            setSupportMessage(result.ok
                ? `Saved the reviewed bundle to ${result.relative_path}.`
                : "Support bundle save did not complete.");
            if (result.ok) {
                setSupportPreview(null);
            }
        }
        catch {
            setSupportMessage("Save approval expired or failed. Create and review a new preview.");
            setSupportPreview(null);
        }
        finally {
            setSupportBusy(false);
        }
    }, [supportPreview]);
    const preparePresentation = SP_REACT.useCallback(async () => {
        setPresentationBusy(true);
        setPresentationMessage("");
        try {
            const approval = await approvePresentationPreparation();
            if (!approval.approval_token || approval.blockers.length > 0) {
                if (approval.blockers.length > 0) {
                    showPresentationPreparationBlocked(approval.blockers);
                }
                setPresentationMessage(approval.blockers.length > 0
                    ? `Preparation blocked: ${approval.blockers.map(label).join(", ")}.`
                    : "Preparation approval was not issued. Inspect again.");
                return;
            }
            const outcome = await preparePresentationIntegration(approval.approval_token);
            setPresentationMessage(outcome.prepared
                ? outcome.changed
                    ? "Gamescope validation integration prepared. Gamescope was not restarted."
                    : "Gamescope validation integration was already prepared."
                : outcome.rollback_attempted && !outcome.rollback_succeeded
                    ? "Preparation failed and rollback needs attention. Do not restart Gamescope."
                    : `Preparation did not complete: ${label(outcome.code)}.`);
        }
        catch {
            setPresentationMessage("Preparation failed safely. Gamescope was not intentionally restarted.");
        }
        finally {
            setPresentationBusy(false);
        }
    }, []);
    const inspectPresentationPreparation = SP_REACT.useCallback(async () => {
        setPresentationBusy(true);
        setPresentationMessage("");
        try {
            const preview = await previewPresentationPreparation();
            if (preview.blockers.length > 0) {
                showPresentationPreparationBlocked(preview.blockers);
                setPresentationMessage(`Preparation blocked: ${preview.blockers.map(label).join(", ")}.`);
                return;
            }
            if (preview.ready) {
                setPresentationMessage("Gamescope validation integration is already prepared.");
                return;
            }
            presentationModal.current?.Close();
            presentationModal.current = showPresentationPreparationConfirmation(() => void preparePresentation(), () => {
                presentationModal.current = null;
            });
        }
        catch {
            setPresentationMessage("Preparation inspection is unavailable. No change was made.");
        }
        finally {
            setPresentationBusy(false);
        }
    }, [preparePresentation]);
    const executeTvSwitch = SP_REACT.useCallback(async () => {
        setTvSwitchBusy(true);
        setTvSwitchMessage("");
        try {
            const approval = await approveSupervisedTvSwitch();
            if (!approval.approval_token || approval.blockers.length > 0) {
                setTvSwitchMessage(approval.blockers.length > 0
                    ? `TV switch blocked: ${approval.blockers.map(label).join(", ")}.`
                    : "TV switch approval was not issued. Inspect again.");
                return;
            }
            toaster.toast({
                title: "HDM is switching to the TV",
                body: "Watch the handheld screen while HDM verifies the transition.",
                critical: true,
                duration: 30000,
            });
            const outcome = await executeSupervisedTvSwitch(approval.approval_token);
            setTvSwitchAcknowledgementId(outcome.acknowledgement_required ? outcome.acknowledgement_id : "");
            setTvSwitchMessage(outcome.accepted
                ? `TV switch result: ${label(outcome.code)}.`
                : `TV switch was not accepted: ${label(outcome.code)}.`);
        }
        catch {
            setTvSwitchMessage("TV switch did not complete. HDM did not claim success.");
        }
        finally {
            setTvSwitchBusy(false);
        }
    }, []);
    const changeAutomaticDock = SP_REACT.useCallback(async (enabled) => {
        setAutomaticDockBusy(true);
        setAutomaticDockMessage("");
        try {
            const status = await setAutomaticDockEnabled(enabled, enabled);
            setAutomaticDockStatus(status);
            setAutomaticDockMessage(status.enabled
                ? "Automatic TV docking is enabled. HDM is waiting for complete G1 and TV evidence."
                : status.code === "automatic_dock.disabled"
                    ? "Automatic TV docking is disabled."
                    : `Automatic TV docking was not changed: ${label(status.code)}.`);
        }
        catch {
            setAutomaticDockMessage("Automatic TV docking was not changed.");
        }
        finally {
            setAutomaticDockBusy(false);
        }
    }, []);
    const toggleAutomaticDock = SP_REACT.useCallback(() => {
        if (automaticDockStatus?.enabled) {
            void changeAutomaticDock(false);
            return;
        }
        automaticDockModal.current?.Close();
        automaticDockModal.current = showAutomaticDockConfirmation(() => void changeAutomaticDock(true), () => {
            automaticDockModal.current = null;
        });
    }, [automaticDockStatus?.enabled, changeAutomaticDock]);
    const executeSafeDisconnect = SP_REACT.useCallback(async () => {
        setSafeDisconnectBusy(true);
        setSafeDisconnectMessage("");
        const portable = payload?.inference.mode === "portable";
        try {
            if (portable) {
                const approval = await approveSafeDisconnectShutdown();
                if (!approval.ready || !approval.approval_token || approval.blockers.length > 0) {
                    setSafeDisconnectMessage(approval.blockers.length > 0
                        ? `Shutdown blocked: ${approval.blockers.map(label).join(", ")}.`
                        : "Shutdown approval was not issued. Inspect again.");
                    return;
                }
                toaster.toast({
                    title: "HDM requested an Ally shutdown",
                    body: "Completion is unverified. Keep the G1 connected until the fan and every top power LED are off.",
                    critical: true,
                    duration: 30000,
                });
                const outcome = await executeSafeDisconnectShutdown(approval.approval_token);
                setSafeDisconnectMessage(outcome.accepted
                    ? "Power-off request accepted; completion is unverified. Keep the G1 connected until the fan stops. If it remains on after 60 seconds, hold the Ally power button until the fan stops."
                    : `Shutdown was not requested: ${label(outcome.code)}.`);
                return;
            }
            const approval = await approveSupervisedPortableSwitch();
            if (!approval.approval_token || approval.blockers.length > 0) {
                setSafeDisconnectMessage(approval.blockers.length > 0
                    ? `Return to Ally blocked: ${approval.blockers.map(label).join(", ")}.`
                    : "Portable transition approval was not issued. Inspect again.");
                return;
            }
            toaster.toast({
                title: "HDM is returning to the Ally",
                body: "Do not disconnect the G1. Wait for Portable verification, then shut down.",
                critical: true,
                duration: 30000,
            });
            const outcome = await executeSupervisedPortableSwitch(approval.approval_token);
            setTvSwitchAcknowledgementId(outcome.acknowledgement_required ? outcome.acknowledgement_id : "");
            setSafeDisconnectMessage(outcome.accepted
                ? `Portable transition result: ${label(outcome.code)}.`
                : `Portable transition was not accepted: ${label(outcome.code)}.`);
        }
        catch {
            setSafeDisconnectMessage(portable
                ? "Shutdown was not requested. Keep the G1 connected."
                : "Portable transition did not complete. Keep the G1 connected.");
        }
        finally {
            setSafeDisconnectBusy(false);
        }
    }, [payload?.inference.mode]);
    const requestSafeDisconnect = SP_REACT.useCallback(() => {
        const portable = payload?.inference.mode === "portable";
        safeDisconnectModal.current?.Close();
        safeDisconnectModal.current = showSafeDisconnectConfirmation(portable, () => void executeSafeDisconnect(), () => {
            safeDisconnectModal.current = null;
        });
    }, [executeSafeDisconnect, payload?.inference.mode]);
    const acknowledgeTvSwitch = SP_REACT.useCallback(async () => {
        if (!tvSwitchAcknowledgementId)
            return;
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
        }
        catch {
            setTvSwitchMessage("Display transition acknowledgement is unavailable.");
        }
        finally {
            setTvSwitchBusy(false);
        }
    }, [refreshTransitionJournal, tvSwitchAcknowledgementId]);
    const acknowledgePriorSleep = SP_REACT.useCallback(async () => {
        const acknowledgementId = journalStatus?.owner === "sleep"
            ? journalStatus.acknowledgement_id
            : "";
        if (!acknowledgementId)
            return;
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
        }
        catch {
            setJournalMessage("Sleep-result acknowledgement is unavailable.");
        }
        finally {
            setJournalBusy(false);
        }
    }, [journalStatus]);
    const runProcessRelease = SP_REACT.useCallback(async (phase, receiptToken) => {
        setProcessBusy(true);
        setProcessMessage("");
        try {
            const approval = await approveProcessRelease(phase, receiptToken);
            if (!approval.approval_token || approval.blockers.length > 0) {
                setProcessMessage(approval.blockers.length > 0
                    ? `Process release blocked: ${approval.blockers.map(label).join(", ")}.`
                    : "Process-release approval was not issued. Inspect again.");
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
        }
        catch {
            setProcessMessage("Process release failed closed. Do not disconnect the eGPU.");
            if (phase === "force") {
                setForceReceiptToken("");
            }
        }
        finally {
            setProcessBusy(false);
        }
    }, [refresh]);
    const inspectProcessRelease = SP_REACT.useCallback(async (phase, receiptToken = "") => {
        setProcessBusy(true);
        setProcessMessage("");
        try {
            const preview = await previewProcessRelease(phase, receiptToken);
            if (!preview.ready || preview.blockers.length > 0 || preview.targets.length === 0) {
                setProcessMessage(preview.blockers.length > 0
                    ? `Process release blocked: ${preview.blockers.map(label).join(", ")}.`
                    : "No eligible ordinary user process is holding the eGPU.");
                return;
            }
            processModal.current?.Close();
            processModal.current = showProcessReleaseConfirmation(preview, () => void runProcessRelease(phase, receiptToken), () => {
                processModal.current = null;
            });
        }
        catch {
            setProcessMessage("Process-release inspection is unavailable. No process was signaled.");
        }
        finally {
            setProcessBusy(false);
        }
    }, [runProcessRelease]);
    const acknowledgeProcessResult = SP_REACT.useCallback(async () => {
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
        }
        catch {
            setProcessMessage("Process-release acknowledgement failed.");
        }
        finally {
            setProcessBusy(false);
        }
    }, [processAcknowledgementId, refreshTransitionJournal]);
    const reviewForceClose = SP_REACT.useCallback(async () => {
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
        }
        catch {
            setProcessMessage("Force-close review is unavailable. No process was signaled.");
        }
        finally {
            setProcessBusy(false);
        }
    }, [forceReceiptToken, inspectProcessRelease, processAcknowledgementId]);
    const returnToStatus = SP_REACT.useCallback(() => {
        const compact = compactStatusPanels();
        setShowDiagnostics(compact.showDiagnostics);
        setShowJourneyDetails(compact.showJourneyDetails);
        // Wait for the diagnostics section to collapse, then reset Steam's owning
        // scroll panel and move focus to a native in-panel control. A non-focusable
        // status div leaves controller navigation at Steam's QAM Back control.
        window.setTimeout(() => {
            const anchor = statusAnchor.current;
            if (!anchor)
                return;
            scrollToTopOfOwningPanel(anchor);
            restoreQuickAccessFocus(() => statusFocusAnchor.current ?? primaryControlAnchor.current?.querySelector("button, [role='button'], input, select") ?? null);
        }, 0);
    }, []);
    const toggleTroubleshooting = SP_REACT.useCallback(() => {
        if (!showDiagnostics) {
            void refresh(true);
        }
        setShowDiagnostics((visible) => !visible);
    }, [refresh, showDiagnostics]);
    const toggleJourneyDetails = SP_REACT.useCallback(() => {
        setShowJourneyDetails((visible) => {
            const next = !visible;
            if (next) {
                window.setTimeout(() => revealJourneyDetails(journeyDetailsAnchor.current), 0);
            }
            return next;
        });
    }, []);
    const sectionVisibility = quickAccessSectionVisibility(showDiagnostics);
    return (SP_JSX.jsx(SP_JSX.Fragment, { children: SP_JSX.jsxs("div", { ref: statusAnchor, tabIndex: -1, children: [SP_JSX.jsx(DFL.PanelSection, { title: "At a glance", children: SP_JSX.jsxs(DFL.Focusable, { ref: statusFocusAnchor, "aria-label": "HDM status summary", onGamepadFocus: () => {
                            if (statusAnchor.current)
                                scrollToTopOfOwningPanel(statusAnchor.current);
                        }, children: [atAGlanceRows({
                                mode: loading ? "Reading…" : label(payload?.inference.mode ?? "unknown"),
                                health: healthStatusLabel(payload?.health, loading),
                                connection: progress.label,
                                game: label(snapshot?.game_state ?? "unknown"),
                            }).map(([name, value]) => (SP_JSX.jsx(StatusCard, { name: name, value: value }, name))), SP_JSX.jsx(DFL.PanelSectionRow, { children: progress.detail })] }) }), SP_JSX.jsxs(DFL.PanelSection, { title: "Safety & actions", children: [SP_JSX.jsxs("div", { ref: primaryControlAnchor, children: [SP_JSX.jsx(DFL.ToggleField, { label: "Automatic TV docking", description: automaticDockBusy
                                        ? "Saving…"
                                        : !automaticDockStatus
                                            ? "Status unavailable"
                                            : automaticDockStatus.enabled
                                                ? label(automaticDockStatus.code)
                                                : "Off · Ask before enabling", checked: automaticDockStatus?.enabled === true, disabled: automaticDockBusy || !automaticDockStatus, highlightOnFocus: true, onChange: toggleAutomaticDock }), automaticDockMessage && (SP_JSX.jsx(DFL.PanelSectionRow, { children: automaticDockMessage })), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void executeTvSwitch(), disabled: tvSwitchBusy
                                            || Boolean(tvSwitchAcknowledgementId)
                                            || Boolean(journalStatus && journalStatus.code !== "journal.idle"), children: tvSwitchBusy ? "Switching…" : "Switch to TV now" }) }), tvSwitchMessage && SP_JSX.jsx(DFL.PanelSectionRow, { children: tvSwitchMessage }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: requestSafeDisconnect, disabled: safeDisconnectBusy
                                            || !disconnect?.applicable
                                            || Boolean(tvSwitchAcknowledgementId)
                                            || Boolean(journalStatus && journalStatus.code !== "journal.idle"), children: safeDisconnectBusy
                                            ? "Checking…"
                                            : payload?.inference.mode === "portable"
                                                ? "Request shutdown for G1 disconnect"
                                                : "Prepare G1 disconnect" }) }), safeDisconnectMessage && (SP_JSX.jsx(DFL.PanelSectionRow, { children: safeDisconnectMessage })), journalStatus && journalStatus.code !== "journal.idle" && (SP_JSX.jsx(DiagnosticRow, { name: "Safety journal", value: label(journalStatus.owner) })), journalMessage && SP_JSX.jsx(DFL.PanelSectionRow, { children: journalMessage }), journalStatus?.owner === "sleep"
                                    && journalStatus.acknowledgement_required
                                    && journalStatus.acknowledgement_id && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void acknowledgePriorSleep(), disabled: journalBusy, children: journalBusy ? "Acknowledging…" : "Acknowledge prior sleep result" }) })), tvSwitchAcknowledgementId && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void acknowledgeTvSwitch(), disabled: tvSwitchBusy, children: "Acknowledge prior display transition result" }) })), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { label: "Troubleshoot", description: "Connection checks, safety details, and support", layout: "inline", childrenContainerWidth: "min", onClick: toggleTroubleshooting, children: showDiagnostics ? "Hide" : "Show" }) })] }), needsAttention && (SP_JSX.jsx(DFL.PanelSectionRow, { children: error || healthAttention[0] || `${snapshot?.blockers.length} safety check${snapshot?.blockers.length === 1 ? "" : "s"} needs attention.` })), sectionVisibility.diagnostics && (SP_JSX.jsx(DFL.PanelSectionRow, { children: "Read-only status refreshes while this panel is open." })), sectionVisibility.diagnostics && sleepGuard?.required && sleepWarningHidden && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: showSleepWarning, children: "Show sleep warning again" }) }))] }), sectionVisibility.journey && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsxs(DFL.PanelSection, { title: "Journey status", children: [journeyRows.map((row) => (SP_JSX.jsx(DiagnosticRow, { name: row.name, value: row.value }, row.name))), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: toggleJourneyDetails, children: showJourneyDetails ? "Hide journey details" : "Open journey details" }) })] }), showJourneyDetails && (SP_JSX.jsx("div", { ref: journeyDetailsAnchor, children: SP_JSX.jsxs(DFL.PanelSection, { title: "Journey details", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: "Read-only local policy status. It does not perform dock, undock, recovery, or game actions." }), journeyDetailRows.map((row) => (SP_JSX.jsx(DiagnosticRow, { name: row.name, value: row.detail }, row.name)))] }) }))] })), sectionVisibility.sleepProtection && SP_JSX.jsxs(DFL.PanelSection, { title: "Sleep protection", children: [SP_JSX.jsx(DiagnosticRow, { name: "System inhibitor", value: loading
                                ? "Checking…"
                                : sleepGuard?.required
                                    ? sleepGuard.active
                                        ? "Active"
                                        : "Inactive"
                                    : "Not required" }), SP_JSX.jsx(DiagnosticRow, { name: "Steam preflight", value: preflightStatus.state === "active"
                                ? preflightStatus.attemptWarningAvailable
                                    ? "Active"
                                    : "Blocked; warning unavailable"
                                : preflightStatus.state === "inactive"
                                    ? "Standby — eGPU verified absent"
                                    : "Unavailable" }), SP_JSX.jsx(DiagnosticRow, { name: "Blocked sleep attempts", value: preflightStatus.blockedAttemptCount
                                ? `${preflightStatus.blockedAttemptCount} observed this session`
                                : "None observed this session" }), preflightStatus.error && (SP_JSX.jsx(DFL.PanelSectionRow, { children: preflightStatus.error })), sleepGuard?.required && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [!sleepWarningHidden && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: gameUsesEgpu
                                                ? "A game is using the eGPU. Sleep is blocked to prevent the known immediate-wake behavior and workload risk."
                                                : "The attached eGPU is known to wake this handheld immediately after sleep. Sleep remains blocked until the eGPU is verified absent." }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: hideSleepWarning, children: "Never show this explanation again" }) })] })), sleepWarningHidden && (SP_JSX.jsx(DFL.PanelSectionRow, { children: "The explanation is hidden. Sleep protection remains active." }))] }))] }), sectionVisibility.disconnectReadiness && SP_JSX.jsxs(DFL.PanelSection, { title: "Disconnect readiness", children: [SP_JSX.jsx(DiagnosticRow, { name: "Status", value: disconnectStatus }), disconnect?.applicable && (SP_JSX.jsx(DiagnosticRow, { name: "Resource clients", value: String(disconnect.clients.length) })), (disconnect?.storage_devices ?? 0) > 0 && (SP_JSX.jsx(DiagnosticRow, { name: "eGPU storage", value: disconnect?.storage_in_use ? "In use — blocked" : "Not mounted" })), disconnect?.error && SP_JSX.jsx(DFL.PanelSectionRow, { children: disconnect.error }), closeEligibleClientCount > 0 && !processAcknowledgementId && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void inspectProcessRelease("graceful"), disabled: processBusy, children: processBusy ? "Checking…" : "Close eligible eGPU processes" }) })), forceReceiptToken && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void reviewForceClose(), disabled: processBusy, children: "Review force close" }) })), processAcknowledgementId && !forceReceiptToken && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void acknowledgeProcessResult(), disabled: processBusy, children: "Acknowledge process-release result" }) })), processMessage && SP_JSX.jsx(DFL.PanelSectionRow, { children: processMessage }), SP_JSX.jsx(DFL.PanelSectionRow, { children: "Process closure always requires confirmation. Software readiness never authorizes physical eGPU removal." })] }), needsAttention && (SP_JSX.jsxs(DFL.PanelSection, { title: "Needs attention", children: [error && SP_JSX.jsx(DFL.PanelSectionRow, { children: error }), healthAttention.map((message) => (SP_JSX.jsx(DFL.PanelSectionRow, { children: message }, message))), snapshot?.blockers.map((blocker) => (SP_JSX.jsx(DFL.PanelSectionRow, { children: blocker.message }, blocker.code)))] })), sectionVisibility.support && SP_JSX.jsxs(DFL.PanelSection, { title: "Support bundle", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: "Preview a bounded HDM-only report before copying or saving it. Raw hardware IDs, addresses, usernames, home paths, and command lines are excluded or redacted." }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void createSupportPreview(), disabled: supportBusy, children: supportBusy ? "Working…" : "Preview redacted support bundle" }) }), supportPreview && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DiagnosticRow, { name: "Preview size", value: `${supportPreview.size_bytes} bytes` }), SP_JSX.jsx(DiagnosticRow, { name: "Recent events", value: String(supportPreview.event_count) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: reviewSupportPreview, disabled: supportBusy, children: "Review exact redacted JSON" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void copySupportPreview(), disabled: supportBusy, children: "Copy reviewed JSON" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void saveApprovedSupportPreview(), disabled: supportBusy, children: "Save reviewed bundle to Downloads" }) })] })), supportMessage && SP_JSX.jsx(DFL.PanelSectionRow, { children: supportMessage })] }), sectionVisibility.diagnostics && (SP_JSX.jsxs(DFL.PanelSection, { title: "Troubleshooting details", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: "Read-only technical evidence. Raw hardware identities, connector names, and process IDs are hidden." }), optionalDiagnosticsDeferred && (SP_JSX.jsx(DFL.PanelSectionRow, { children: "Additional troubleshooting checks wait until HDM confirms no game is running." })), overlayRows.map((row) => (SP_JSX.jsx(DiagnosticRow, { name: row.name, value: row.value }, row.name))), dockedIgpuStatus?.acknowledgement_required && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void acknowledgeDockedIgpuWatch(), children: "Acknowledge Docked-iGPU watcher state" }) })), dockedIgpuMessage && (SP_JSX.jsx(DFL.PanelSectionRow, { children: dockedIgpuMessage })), SP_JSX.jsx(DFL.DropdownItem, { label: "Verbose logging duration", description: "Temporary, sanitized, capped, and off by default", rgOptions: DIAGNOSTIC_LOGGING_OPTIONS, selectedOption: diagnosticLoggingDuration, disabled: diagnosticLoggingBusy || diagnosticLoggingStatus?.enabled === true, onChange: (option) => {
                                setDiagnosticLoggingDuration(option.data);
                            } }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: diagnosticLoggingStatus?.enabled
                                    ? () => void stopDiagnosticLogging()
                                    : requestDiagnosticLogging, disabled: diagnosticLoggingBusy, children: diagnosticLoggingStatus?.enabled
                                    ? "Disable verbose diagnostics"
                                    : "Enable verbose diagnostics" }) }), diagnosticLoggingMessage && (SP_JSX.jsx(DFL.PanelSectionRow, { children: diagnosticLoggingMessage })), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void inspectPresentationPreparation(), disabled: presentationBusy, children: presentationBusy ? "Checking…" : "Prepare supervised display validation" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: "Preparation only. This control cannot restart Gamescope or switch displays." }), presentationMessage && SP_JSX.jsx(DFL.PanelSectionRow, { children: presentationMessage })] })), sectionVisibility.navigation && SP_JSX.jsx(DFL.PanelSection, { title: "Navigation", children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: returnToStatus, children: "Back to top" }) }) })] }) }));
}
function showBlockedAttempt(warning, onClose) {
    let modal;
    const close = () => {
        modal.Close();
        onClose();
    };
    // Let Decky resolve Steam's visible SP window after the Power menu closes.
    // SharedJSContext's global window is not a player-visible modal parent.
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: warning.title, strDescription: warning.body, strOKButtonText: "OK", bAlertDialog: true, bDestructiveWarning: warning.critical, bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: close }), window, { strTitle: "Handheld Dock Mode", bNeverPopOut: true });
    return modal;
}
var index = definePlugin(() => {
    let warningModal = null;
    let warningTimer = null;
    const preflight = new SleepPreflightCoordinator(createDeckySteamSuspendAdapter(), (warning) => {
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
        }
        catch {
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
    });
    preflight.start();
    return {
        name: "Handheld Dock Mode",
        titleView: SP_JSX.jsx("div", { className: DFL.staticClasses.Title, children: "Handheld Dock Mode" }),
        content: SP_JSX.jsx(Content, { preflight: preflight }),
        icon: SP_JSX.jsx(MonitorIcon, {}),
        alwaysRender: true,
        onDismount() {
            if (warningTimer !== null) {
                window.clearTimeout(warningTimer);
                warningTimer = null;
            }
            warningModal?.Close();
            warningModal = null;
            preflight.stop();
        },
    };
});

export { index as default };
//# sourceMappingURL=index.js.map
