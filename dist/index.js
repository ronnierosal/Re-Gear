// SteamClient.Input.ControllerInputGamepadButton, not browser Gamepad indices.
const VIEW_BUTTON = 9;
const Y_BUTTON = 3;
const SAFE_DISCONNECT_HOLD_MS = 3000;
const CONTEXT_TIMEOUT_MS = 2000;
function safeDisconnectContext(context) {
    const value = context?.snapshot;
    const snapshot = value?.snapshot;
    const observedAt = Date.parse(snapshot?.observed_at ?? "");
    const age = Date.now() - observedAt;
    return value?.delivery_schema_version === 2 && snapshot?.schema_version === 3
        && Number.isFinite(age) && age >= -5e3 && age <= 15000
        && snapshot.game_state === "idle"
        && snapshot.gamescope?.running === true
        && snapshot.support_tier === "certified"
        && snapshot.disconnect_readiness?.applicable === true
        && Array.isArray(snapshot.gpus)
        && snapshot.gpus.some(gpu => gpu.role === "external" && gpu.present === true && gpu.confidence === "verified")
        && (value.inference?.mode === "portable" || value.inference?.mode === "tv_docked")
        && context.journal?.code === "journal.idle";
}
/** Native event listener; only opens the ordinary confirmation, never executes. */
function startControllerSafeDisconnect(deps) {
    const subscriptions = [];
    const controllers = new Map();
    const latched = new Set();
    let active = false;
    let reading = false;
    let epoch = 0;
    let timer;
    let owner;
    const exact = (id) => {
        const buttons = controllers.get(id);
        return buttons?.size === 2 && buttons.has(VIEW_BUTTON) && buttons.has(Y_BUTTON);
    };
    const cancel = () => { epoch++; clearTimeout(timer); timer = undefined; owner = undefined; };
    const reset = () => { cancel(); controllers.clear(); latched.clear(); };
    const stop = () => {
        active = false;
        reset();
        for (const subscription of subscriptions.splice(0)) {
            try {
                subscription.unregister();
            }
            catch { /* Disabled callbacks remain inert. */ }
        }
    };
    const readFresh = async () => {
        if (reading)
            return null;
        reading = true;
        const request = Promise.resolve().then(() => deps.readContext()).then(value => { reading = false; return value; }, () => { reading = false; return null; });
        let timeout;
        try {
            return await Promise.race([
                request,
                new Promise(resolve => { timeout = setTimeout(() => resolve(null), CONTEXT_TIMEOUT_MS); }),
            ]);
        }
        catch {
            return null;
        }
        finally {
            clearTimeout(timeout);
        }
    };
    const valid = (id, token) => active && epoch === token && exact(id) && !deps.isBusy();
    const begin = (id) => {
        cancel();
        owner = id;
        const token = epoch;
        const initial = readFresh();
        timer = setTimeout(() => {
            timer = undefined;
            void (async () => {
                const before = await initial;
                if (!valid(id, token) || !before || !safeDisconnectContext(before))
                    return;
                const after = await readFresh();
                if (!valid(id, token) || !after || !safeDisconnectContext(after))
                    return;
                if (before.snapshot.inference.mode !== after.snapshot.inference.mode)
                    return;
                latched.add(id);
                deps.confirm(after.snapshot.inference.mode === "portable" ? "tv" : "ally");
            })().catch(() => { });
        }, SAFE_DISCONNECT_HOLD_MS);
    };
    const onInput = (id, button, pressed) => {
        if (!active)
            return;
        if (!Number.isInteger(id) || id < 0 || id > 255 || !Number.isInteger(button)
            || button < 0 || button > 255 || typeof pressed !== "boolean") {
            reset();
            return;
        }
        if (!controllers.has(id)) {
            if (!pressed)
                return;
            if (controllers.size >= 8) {
                reset();
                return;
            }
            controllers.set(id, new Set());
        }
        const buttons = controllers.get(id);
        if (pressed === buttons.has(button))
            return; // Ignore repeated down/up delivery.
        if (pressed)
            buttons.add(button);
        else
            buttons.delete(button);
        if (!exact(id) && owner === id)
            cancel();
        if (buttons.size === 0) {
            controllers.delete(id);
            latched.delete(id);
        }
        if (exact(id) && !latched.has(id) && owner === undefined && !deps.isBusy())
            begin(id);
    };
    try {
        const input = deps.input;
        if (typeof input?.RegisterForControllerInputMessages !== "function")
            return { available: false, stop };
        // Steam builds differ: the Ally exposes active-controller notifications,
        // while other builds expose controller-list notifications. Either cancels
        // all pending holds; never substitute per-button/analog state notifications.
        const registerChanges = typeof input.RegisterForControllerListChanges === "function"
            ? input.RegisterForControllerListChanges.bind(input)
            : typeof input.RegisterForActiveControllerChanges === "function"
                ? input.RegisterForActiveControllerChanges.bind(input) : undefined;
        if (!registerChanges)
            return { available: false, stop };
        for (const register of [
            () => registerChanges(reset),
            () => input.RegisterForControllerInputMessages(onInput),
        ]) {
            const subscription = register();
            if (typeof subscription?.unregister !== "function") {
                stop();
                return { available: false, stop };
            }
            subscriptions.push(subscription);
        }
        active = true;
        return { available: true, stop };
    }
    catch {
        stop();
        return { available: false, stop };
    }
}
function steamControllerInput(host) {
    try {
        return host?.SteamClient?.Input;
    }
    catch {
        return undefined;
    }
}

function createDisplayShortcutRuntime(deps) {
    const state = {
        modal: { current: null },
        portableBusy: { current: false }, tvBusy: { current: false },
    };
    let stopped = false;
    let acknowledgement = "";
    const acknowledgementListeners = new Set();
    const busy = () => stopped || state.portableBusy.current || state.tvBusy.current || state.modal.current !== null;
    const execute = async (target) => {
        if (busy())
            return;
        const lock = target === "tv" ? state.tvBusy : state.portableBusy;
        lock.current = true;
        try {
            const approval = await deps.approve(target);
            if (stopped)
                return;
            if (!approval.approval_token || approval.blockers.length) {
                deps.report("Display switch blocked. Open Re-Gear to inspect readiness.");
                return;
            }
            const result = await deps.execute(target, approval.approval_token);
            if (!stopped) {
                acknowledgement = result.acknowledgement_required ? result.acknowledgement_id ?? "" : "";
                for (const notify of acknowledgementListeners)
                    notify(acknowledgement);
            }
            if (!stopped)
                deps.report(result.accepted
                    ? "Display request accepted. Keep the eGPU connected and verify the display."
                    : "Display switch did not complete. Open Re-Gear for details.");
        }
        catch {
            if (!stopped)
                deps.report("Display switch could not be verified. Keep the eGPU connected.");
        }
        finally {
            lock.current = false;
        }
    };
    const request = (target) => {
        if (busy())
            return;
        let confirmed = false;
        state.modal.current = deps.show(target, () => {
            if (confirmed)
                return;
            confirmed = true;
            state.modal.current = null;
            void execute(target);
        }, () => { state.modal.current = null; });
    };
    const listener = startControllerSafeDisconnect({
        input: deps.input, readContext: deps.readContext, isBusy: busy,
        confirm: request,
    });
    return { ...state, request, available: listener.available,
        subscribeAcknowledgement(notify) {
            acknowledgementListeners.add(notify);
            notify(acknowledgement);
            return () => { acknowledgementListeners.delete(notify); };
        },
        clearAcknowledgement() { acknowledgement = ""; },
        stop() {
            stopped = true;
            listener.stop();
            acknowledgementListeners.clear();
            state.modal.current?.Close();
            state.modal.current = null;
        } };
}

const manifest = {"name":"Re-Gear"};
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
const routerHook = api.routerHook;
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
const getTdpStatus = callable("get_tdp_status");
const setTdpEnabled = callable("set_tdp_enabled");
const applyTdpLimit = callable("apply_tdp_limit");
const restoreTdpLimit = callable("restore_tdp_limit");
const getAutoTdpStatus = callable("get_auto_tdp_status");
const startAutoTdp = callable("start_auto_tdp");
const stopAutoTdp = callable("stop_auto_tdp");
const getTdpBenchmarkStatus = callable("get_auto_tdp_benchmark_status");
const runTdpBenchmark = callable("run_auto_tdp_benchmark");
const cancelTdpBenchmark = callable("cancel_auto_tdp_benchmark");
const getAutoTdpPreferences = callable("get_auto_tdp_preferences");
const saveAutoTdpPreference = callable("save_auto_tdp_preference");
/** Read-only. Observes and changes nothing, so it is safe to poll. */
const getEgpuDisconnectStatus = callable("get_egpu_disconnect_status");
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
const executeEgpuDisconnect = callable("execute_egpu_disconnect");
/** Claim the game a disconnect closed, if it may still be reopened.
 *
 * Consuming, and consuming on refusal too, so a relaunch that happens cannot
 * happen twice. Call it after a disconnect returns, and again when the panel
 * loads: freeing the eGPU restarts the Steam session, so the panel that asked
 * for the relaunch is usually not the one that gets to perform it.
 */
callable("take_pending_relaunch");
/** Store the player's answer about closing one game before a disconnect.
 *
 * The backend re-derives what may be stored from a fresh status rather than
 * trusting this call, so an answer filed against the wrong game, or a "do not
 * ask again" for a game the catalog says loses progress, is refused rather
 * than written. Check `ok` before telling a player the box was remembered.
 */
callable("remember_game_close_choice");
/** Return one game to being asked about before a disconnect. */
callable("forget_game_close_choice");

function disconnectProgress(payload, failed = false, now = Date.now()) {
    const s = payload?.snapshot;
    const age = now - Date.parse(s?.observed_at ?? "");
    const fresh = !failed && Number.isFinite(age) && age >= -5e3 && age < 15000;
    const selected = s?.gpus.filter(gpu => gpu.present && gpu.selected_for_render);
    const active = s?.displays.filter(display => display.active);
    const internal = selected?.length === 1 && selected[0].role === "internal" && selected[0].confidence === "verified"
        && active?.length === 1 && active[0].kind === "internal" && active[0].confidence === "verified";
    const d = s?.disconnect_readiness;
    const clientsClear = d?.applicable && d.scan_complete && !d.error && d.clients.length === 0 && d.storage_devices === 0 && !d.storage_in_use;
    return {
        // A clean client scan is not a safe-to-unplug capability. This adapter has
        // no release RPC or final-verification contract; it cannot report success.
        safeToUnplug: false,
        detail: !fresh ? "Waiting for a fresh status update." : d?.clients.length
            ? `${d.clients.length} eGPU client(s) remain. Live release is not available in this build.`
            : "Live GPU release and final disconnect verification are not available in this build.",
        rows: [
            { label: "No game running", state: fresh && s?.game_state === "idle" ? "ready" : fresh && s?.game_state === "running" ? "blocked" : "waiting" },
            { label: "Ally display & render GPU", state: fresh && internal ? "ready" : "waiting" },
            { label: "Ally audio", state: "unavailable" },
            { label: "Remaining eGPU clients", state: fresh && clientsClear ? "ready" : fresh && d?.clients.length ? "blocked" : "waiting" },
            { label: "GPU & link release", state: "unavailable" },
            { label: "Final disconnect verification", state: "unavailable" },
        ],
    };
}

const connectionPanelCss = `
.rg-connection-modal.rg-connection-compact { padding:6px !important; min-width:0 !important; width:min(432px,calc(100vw - 24px)) !important; }
.rg-connection-modal { background: linear-gradient(145deg,#18212c,#10171f) !important; border:1px solid #394653; border-radius:14px; box-sizing:border-box; max-width:calc(100vw - 32px); max-height:calc(100vh - 32px); overflow-y:auto; }
.rg-connection { color:#edf3f8; font-size:16px; line-height:1.4; min-width:0; width:100%; max-width:520px; }
.rg-connection-subtitle { color:#b5c3d2; margin:0 0 18px; }
.rg-connection-list { border:1px solid #394653; border-radius:12px; padding:0 14px; }
.rg-connection-row { display:flex; align-items:center; gap:12px; padding:11px 0; border-bottom:1px solid #303c48; }
.rg-connection-row:last-child { border:0; }
.rg-connection-label { flex:1; min-width:0; overflow-wrap:break-word; }
.rg-connection-state { display:flex; align-items:center; gap:8px; font-size:14px; white-space:nowrap; }
.rg-connection-ready { color:#87da91; }
.rg-connection-waiting { color:#ffd16b; }
.rg-connection-blocked { color:#ffd16b; }
.rg-connection-icon { width:22px; height:22px; display:inline-flex; align-items:center; justify-content:center; flex-shrink:0; }
.rg-connection-ring { width:17px; height:17px; border:2px solid transparent; border-top-color:currentColor; border-right-color:currentColor; border-radius:50%; animation:rg-connection-spin 1.3s linear infinite; }
.rg-connection-check { animation:rg-connection-reveal .2s ease-out; }
.rg-connection-detail { margin:16px 0 8px; color:#b5c3d2; font-size:14px; }
.rg-connection-foot { color:#95a6b7; font-size:13px; margin:8px 0 0; }
.rg-connection-hero { display:flex; justify-content:center; padding:20px 0; color:#87da91; }
.rg-connection-hero .rg-connection-icon, .rg-connection-hero svg { width:76px; height:76px; }
.rg-connection-sweep { overflow:hidden; height:3px; background:#33414f; margin:22px 0; border-radius:3px; }
.rg-connection-sweep::after { content:''; display:block; width:35%; height:100%; background:#66d9f7; animation:rg-connection-sweep 1.8s ease-in-out infinite; }
@keyframes rg-connection-spin { to { transform:rotate(360deg); } }
@keyframes rg-connection-reveal { from { opacity:.3; transform:scale(.8); } to { opacity:1; transform:scale(1); } }
@keyframes rg-connection-sweep { from { transform:translateX(-110%); } to { transform:translateX(390%); } }
@media (prefers-reduced-motion:reduce) { .rg-connection-ring,.rg-connection-check,.rg-connection-sweep::after { animation:none; } }
/* Modal density is independent of the physical display resolution: Steam can
   scale its UI while reporting a large CSS viewport. Keep the base compact. */
.rg-connection-modal .rg-connection { font-size:14px; line-height:1.3; max-width:440px; }
.rg-connection-modal .rg-connection-subtitle { margin:0 0 8px; font-size:13px; }
.rg-connection-modal .rg-connection-list { padding:0 10px; }
.rg-connection-modal .rg-connection-row { padding:4px 0; gap:8px; min-height:20px; }
.rg-connection-modal .rg-connection-icon, .rg-connection-modal .rg-connection-icon svg { width:18px; height:18px; }
.rg-connection-modal .rg-connection-ring { width:14px; height:14px; }
.rg-connection-modal .rg-connection-detail { margin:8px 0 4px; font-size:13px; }
.rg-connection-modal .rg-connection-foot { margin:4px 0 0; font-size:12px; }
.rg-connection-modal .rg-connection-hero { padding:10px 0; }
.rg-connection-modal .rg-connection-hero .rg-connection-icon, .rg-connection-modal .rg-connection-hero svg { width:48px; height:48px; }
.rg-connection-modal .rg-connection-sweep { margin:12px 0; }
@media (max-height:540px) {
  .rg-connection-modal { padding:16px !important; }
  .rg-connection-modal .rg-connection-row { padding:2px 0; }
}
`;

const statusAppearance = {
    ready: { label: "Ready", color: "#87da91", motion: false },
    checking: { label: "Checking", color: "#ffd16b", motion: true },
    waiting: { label: "Waiting", color: "#ffd16b", motion: false },
    pending: { label: "Pending", color: "#95a6b7", motion: false },
    switching: { label: "Switching", color: "#66d9f7", motion: true },
    blocked: { label: "Blocked", color: "#ffd16b", motion: false },
    error: { label: "Error", color: "#ff9c93", motion: false },
    unavailable: { label: "Unavailable", color: "#95a6b7", motion: false },
};

function StatusIcon({ state }) {
    const appearance = statusAppearance[state];
    return SP_JSX.jsx("span", { className: "rg-connection-icon", "aria-hidden": "true", style: { color: appearance.color }, children: state === "ready" ? SP_JSX.jsxs("svg", { className: "rg-connection-check", viewBox: "0 0 24 24", width: "22", height: "22", fill: "none", stroke: "currentColor", strokeWidth: "1.7", children: [SP_JSX.jsx("circle", { cx: "12", cy: "12", r: "10" }), SP_JSX.jsx("path", { d: "m7 12 3 3 7-7" })] })
            : state === "blocked" || state === "error" ? SP_JSX.jsx("svg", { viewBox: "0 0 24 24", width: "22", height: "22", fill: "none", stroke: "currentColor", strokeWidth: "1.7", children: SP_JSX.jsx("path", { d: "M12 3 22 21H2Z M12 9v5 M12 17v1" }) })
                : appearance.motion ? SP_JSX.jsx("span", { className: "rg-connection-ring" }) : SP_JSX.jsx("svg", { viewBox: "0 0 24 24", width: "22", height: "22", fill: "none", stroke: "currentColor", strokeWidth: "1.7", children: SP_JSX.jsx("circle", { cx: "12", cy: "12", r: "9" }) }) });
}
function ReadinessRow({ label, state, compact = false }) {
    return SP_JSX.jsxs("div", { className: "rg-connection-row", style: compact ? { padding: "8px 0", gap: 8, fontSize: 13 } : undefined, children: [SP_JSX.jsx("span", { className: "rg-connection-label", children: label }), SP_JSX.jsxs("span", { className: "rg-connection-state", style: { color: statusAppearance[state].color, fontSize: compact ? 12 : 14 }, children: [SP_JSX.jsx(StatusIcon, { state: state }), statusAppearance[state].label] })] });
}

function DisconnectPanel({ close }) {
    const [payload, setPayload] = SP_REACT.useState(null);
    const [failed, setFailed] = SP_REACT.useState(false);
    const [now, setNow] = SP_REACT.useState(Date.now());
    SP_REACT.useEffect(() => {
        let stopped = false;
        let timer;
        const tick = setInterval(() => setNow(Date.now()), 1000);
        const poll = async () => {
            try {
                const next = await getSnapshot();
                if (!stopped) {
                    setPayload(next);
                    setFailed(false);
                }
            }
            catch {
                if (!stopped)
                    setFailed(true);
            }
            finally {
                if (!stopped)
                    timer = setTimeout(() => void poll(), 2000);
            }
        };
        void poll();
        return () => { stopped = true; clearInterval(tick); if (timer !== undefined)
            clearTimeout(timer); };
    }, []);
    const status = disconnectProgress(payload, failed, now);
    return SP_JSX.jsxs(DFL.ConfirmModal, { className: "rg-connection-modal", strTitle: "Disconnect status", strOKButtonText: "Hide", bAlertDialog: true, bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: close, onCancel: close, children: [SP_JSX.jsx("style", { children: connectionPanelCss }), SP_JSX.jsxs("div", { className: "rg-connection", children: [SP_JSX.jsx("p", { className: "rg-connection-subtitle", children: "Keep the eGPU cable connected" }), SP_JSX.jsx("div", { className: "rg-connection-list", children: status.rows.map(row => SP_JSX.jsx(ReadinessRow, { label: row.label, state: row.state === "ready" ? "ready" : row.state === "blocked" ? "blocked" : row.state === "unavailable" ? "unavailable" : "waiting" }, row.label)) }), SP_JSX.jsx("p", { role: "status", className: "rg-connection-detail", children: status.detail }), SP_JSX.jsx("p", { className: "rg-connection-foot", children: "Status only. This does not release devices. Shut down fully before unplugging." })] })] });
}
function showDisconnectProgress(onClose) {
    let modal;
    const close = () => { modal.Close(); onClose(); };
    modal = DFL.showModal(SP_JSX.jsx(DisconnectPanel, { close: close }), window, { strTitle: "Re-Gear", bNeverPopOut: true });
    return modal;
}

const regearTheme = {
    text: "#edf3f8",
    muted: "#b5c3d2",
    border: "#394653",
    surface: "linear-gradient(145deg, #18212c, #10171f)",
    accentSoft: "#acebfa"};
// Scoped to Re-Gear controls. Native Decky focus handling remains in charge.
const regearControlCss = `
.rg-section-focus {
  min-width: 0;
  border-radius: 14px;
  scroll-margin-top: 48px;
  scroll-margin-bottom: 16px;
}
.rg-section-focus, .rg-section-focus.gpfocus, .rg-section-focus:focus-visible,
.rg-section-focus:focus-within {
  /* Informational navigation stops remain focusable but visually neutral. */
  background: transparent !important;
  outline: none !important;
  box-shadow: none !important;
}
.rg-dashboard-action:focus-visible, .rg-dashboard-action.gpfocus,
.gpfocus > .rg-dashboard-action {
  outline: 2px solid #66d9f7 !important;
  outline-offset: -3px;
  background: #213744 !important;
}
.rg-dashboard-action:disabled { opacity: .7; }
`;

/** Informational controller stop, not an action or an invisible button. */
const SectionFocus = SP_REACT.forwardRef(function SectionFocus({ label, children, onFocused }, ref) {
    // Generic Focusable containers can route to children without becoming a
    // selectable leaf. Field explicitly registers this read-only focus stop.
    return SP_JSX.jsx(DFL.Field, { ref: ref, focusable: true, highlightOnFocus: false, padding: "none", bottomSeparator: "none", childrenLayout: "below", className: "rg-section-focus", onGamepadFocus: (event) => {
            if (event.currentTarget instanceof HTMLElement) {
                event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" });
            }
            onFocused?.();
        }, children: SP_JSX.jsx("div", { role: "group", "aria-label": label, style: { minWidth: 0, width: "100%" }, children: children }) });
});

const labels = {
    "GPU and driver": "GPU driver",
    "Connection link": "Connection link",
    "TV HDMI detected": "TV HDMI",
    "Audio recovery ready": "Audio recovery",
    "No game running": "No game running",
};
/** Shares the popup monitor; never starts another backend read. */
function ConnectionQuickStatus({ store, visible, onOpen }) {
    const source = SP_REACT.useSyncExternalStore(store.subscribe, store.get);
    const [, tick] = SP_REACT.useReducer((value) => value + 1, 0);
    SP_REACT.useEffect(() => {
        if (!visible)
            return;
        const timer = setInterval(tick, 1000);
        return () => clearInterval(timer);
    }, [visible]);
    const stale = Date.now() >= source.expiresAt;
    return SP_JSX.jsxs("div", { "aria-label": "Live eGPU readiness", style: { background: regearTheme.surface, border: `1px solid ${regearTheme.border}`, borderRadius: 14, padding: "10px 12px", color: regearTheme.text }, children: [SP_JSX.jsx("style", { children: connectionPanelCss }), SP_JSX.jsxs(SectionFocus, { label: "eGPU readiness", children: [SP_JSX.jsx("div", { style: { fontSize: 13, fontWeight: 700, overflowWrap: "anywhere", marginBottom: 6 }, children: !stale && source.gpuName ? source.gpuName : "eGPU" }), SP_JSX.jsx("div", { style: { fontSize: 13, lineHeight: 1.4, color: regearTheme.muted, marginBottom: 6 }, role: "status", children: stale ? "Waiting for a fresh status update" : source.title }), SP_JSX.jsx("div", { children: source.rows.filter(row => labels[row.label]).map(row => {
                            const state = stale ? "waiting" : row.state;
                            return SP_JSX.jsx(ReadinessRow, { label: labels[row.label], compact: true, state: state === "waiting" && !stale && visible ? "checking" : state }, row.label);
                        }) })] }), SP_JSX.jsx(DFL.DialogButton, { className: "rg-dashboard-action", onClick: onOpen, style: { width: "100%", minWidth: 0, height: "auto", padding: "9px 8px", marginTop: 10,
                    border: `1px solid ${regearTheme.border}`, borderRadius: 9, background: "transparent",
                    color: regearTheme.accentSoft, fontSize: 13, lineHeight: 1.4 }, children: "View full progress" })] });
}

function detectedGpuName(payload, fresh) {
    if (!fresh)
        return undefined;
    // Do not choose arbitrarily among external or unclassified devices.
    const candidates = payload?.snapshot.gpus?.filter(gpu => gpu.present && gpu.role !== "internal") ?? [];
    if (candidates.length !== 1 || candidates[0].role !== "external" || candidates[0].confidence !== "verified")
        return undefined;
    const raw = candidates[0].model_name;
    if (typeof raw !== "string" || raw.length > 128)
        return undefined;
    const name = raw.trim();
    return name && /^[\x20-\x7e]+$/.test(name) && !/^(unknown|n\/a|none)$/i.test(name) ? name : undefined;
}
function connectionLiveStatus(payload, automatic, journal, failed = false) {
    const c = payload?.connection_readiness;
    const connected = !!c && c.stage !== "disconnected";
    const snapshotAge = Date.now() - Date.parse(payload?.snapshot.observed_at ?? "");
    const fresh = !failed && Number.isFinite(snapshotAge) && snapshotAge >= -5e3 && snapshotAge < 15000
        && typeof c?.checks_age_ms === "number" && c.checks_age_ms >= 0 && c.checks_age_ms < 15000;
    // The backend timeout remains an authorization boundary, not proof of a
    // failed cable/device. Later exact enumeration can start a fresh window.
    const blocked = fresh && ["link_training_failed", "action_required"].includes(c?.stage ?? "");
    const names = { gpu: "GPU and driver", link: "Connection link", hdmi: "TV HDMI detected", audio: "Audio recovery ready", session: "Display switching ready", idle: "No game running" };
    const rows = Object.entries(names).map(([key, label]) => ({ label, state: (!fresh ? "waiting" : (key === "idle" ? payload?.snapshot.game_state === "idle" && c?.checks?.idle === true : c?.checks?.[key] === true) ? "ready" : blocked || key === "idle" && payload?.snapshot.game_state === "running" ? "blocked" : "waiting") }));
    rows.push({ label: "Previous result cleared", state: !fresh || !journal ? "waiting" : journal === "journal.idle" ? "ready" : "blocked" });
    const all = fresh && c?.stage === "ready_idle" && rows.every(row => row.state === "ready");
    const switching = fresh && automatic?.stage === "switching";
    const docked = fresh && automatic?.stage === "docked" && payload?.inference.mode === "docked_egpu";
    const waiting = { waiting_for_pci: "Waiting for eGPU detection", transport_detected: "eGPU connection detected", waiting_for_driver: "Waiting for GPU driver", waiting_for_link: "Waiting for connection link", waiting_for_hdmi: "Waiting for TV HDMI", waiting_for_audio: "Checking audio recovery", waiting_for_session: "Waiting for display integration", game_running: "Close the game to continue", stabilizing: "Checking connection stability", timed_out: "Detection timed out — keep eGPU connected", link_training_failed: "Connection link needs attention", action_required: "Connection needs attention" };
    const age = c?.window_age_ms;
    const waitingStage = ["timed_out", "waiting_for_pci", "transport_detected", "waiting_for_driver", "waiting_for_link", "waiting_for_hdmi", "waiting_for_audio", "waiting_for_session", "stabilizing"].includes(c?.stage ?? "");
    const delayMessage = waitingStage && typeof age === "number" && Number.isFinite(age)
        ? age >= 300000 ? "Connection hasn’t completed—troubleshooting needed"
            : age >= 120000 ? "Taking longer than expected—still checking" : undefined
        : undefined;
    const detail = blocked ? waiting[c?.stage ?? ""]
        : payload?.snapshot.game_state === "running" ? "Close the game to continue"
            : journal && journal !== "journal.idle" ? "Previous result needs acknowledgement"
                : delayMessage ?? (c?.stage === "timed_out" ? "Taking longer than expected—still checking" : waiting[c?.stage ?? ""]);
    return { phase: docked ? "complete" : switching ? "switching" : "checking", connected, expiresAt: fresh ? Date.now() + Math.max(0, 15000 - Math.max(snapshotAge, c?.checks_age_ms ?? 15000)) : 0, seconds: Math.floor((c?.window_age_ms ?? 0) / 1000), rows,
        title: !fresh ? "Waiting for a fresh status update" : switching ? "Switching to TV — checking picture and audio" : docked ? "TV transition reported complete" : all ? automatic?.enabled ? "Ready — waiting for automatic switch" : "Ready to switch to TV" : detail ?? "Checking connection readiness",
        gpuName: connected ? detectedGpuName(payload, fresh) : undefined,
        canSwitch: all && automatic?.enabled === false };
}
function createLiveStatusStore() {
    let value = { phase: "checking", connected: false, expiresAt: 0, seconds: 0, title: "Checking connection", rows: [], canSwitch: false };
    const listeners = new Set();
    return { get: () => value, set(next) { value = next; for (const listener of listeners)
            listener(); }, subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener); }; } };
}

// Owned by the plugin, never by the Quick Access content mount. The first
// successful sample establishes a baseline; an already attached GPU is not
// a new physical connection. Missing/stale reads cannot rearm the popup.
function startConnectionMonitor(deps) {
    const store = createLiveStatusStore();
    const schedule = deps.schedule ?? setTimeout;
    const cancel = deps.cancel ?? clearTimeout;
    let previous;
    let stopped = false;
    let timer;
    let modal = null;
    const close = () => { modal?.Close(); modal = null; };
    const open = (switchTv) => {
        if (!stopped && !modal)
            modal = deps.show(store, switchTv, () => { modal = null; });
    };
    const poll = async () => {
        try {
            const { payload, automatic, journal } = await deps.read();
            if (stopped)
                return;
            const status = connectionLiveStatus(payload, automatic, journal);
            store.set(status);
            const age = Date.now() - Date.parse(payload.snapshot.observed_at);
            if (payload.connection_readiness && Number.isFinite(age) && age >= -5e3 && age < 15000) {
                const attached = status.connected;
                const newConnection = previous === false && attached;
                previous = attached;
                if (!attached)
                    close();
                else if (newConnection && payload.snapshot.game_state === "idle"
                    && payload.inference.mode !== "docked_egpu")
                    open();
            }
        }
        catch {
            if (!stopped)
                store.set({ ...store.get(), expiresAt: 0, canSwitch: false });
        }
        finally {
            // One in-flight read, no overlapping polling or new hardware mutation.
            if (!stopped)
                timer = schedule(() => void poll(), 1000);
        }
    };
    void poll();
    return { store, open, stop() { stopped = true; if (timer !== undefined)
            cancel(timer); close(); } };
}

var brandIcon = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNTYgMjU2IiByb2xlPSJpbWciIGFyaWEtbGFiZWxsZWRieT0idGl0bGUgZGVzYyI+CiAgPHRpdGxlIGlkPSJ0aXRsZSI+UmUtR2VhciBpY29uPC90aXRsZT4KICA8ZGVzYyBpZD0iZGVzYyI+Q3lhbiBzZWdtZW50ZWQgaGV4YWdvbmFsIFJlLUdlYXIgUiBlbWJsZW0gZm9yIERlY2t5IFVJLjwvZGVzYz4KICA8ZyBmaWxsPSJub25lIiBzdHJva2U9IiMzNWQ2ZjUiIHN0cm9rZS13aWR0aD0iMTQiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCI+CiAgICA8cGF0aCBkPSJNNzggMzEgMTIxIDhsNDMgMjMiLz4KICAgIDxwYXRoIGQ9Ik0xODEgNDEgMjIwIDYzdjQ3Ii8+CiAgICA8cGF0aCBkPSJNMjIwIDE0NXY0OGwtNDIgMjQiLz4KICAgIDxwYXRoIGQ9Im0xNjQgMjI1LTQzIDIzLTQzLTIzIi8+CiAgICA8cGF0aCBkPSJNNjEgMjE2IDIwIDE5M3YtNDciLz4KICAgIDxwYXRoIGQ9Ik0yMCAxMTFWNjNsNDItMjMiLz4KICA8L2c+CiAgPHBhdGggZmlsbD0iIzM1ZDZmNSIgZD0iTTc1IDYyaDY5YzI5IDAgNDYgMTQgNDYgMzkgMCAyMC0xMSAzMy0zMSAzOGwzMCA1NWgtMzRsLTI3LTUwaC0yMmwtMTkgNTBINTNsMzgtMTAxaDU1YzggMCAxMi0zIDEyLTEwIDAtNi00LTktMTItOUg4M0w3NSA2MlptNDEgNThoMjljOCAwIDEyLTQgMTItMTBzLTQtOS0xMi05aC0yMmwtNyAxOVoiLz4KPC9zdmc+Cg==";

const C$3 = {
    bg: "#06101c",
    panel: "#0a1727",
    panel2: "#0d1b2d",
    row: "rgba(4,11,20,.34)",
    border: "rgba(129,160,193,.30)",
    borderStrong: "rgba(57,216,255,.62)",
    text: "#f4f7fb",
    muted: "#9fb1c8",
    cyan: "#39d8ff",
    green: "#6fe45d",
    amber: "#ffc43d",
    red: "#ff6578",
};
const stateColor = {
    ready: C$3.green,
    checking: C$3.amber,
    pending: C$3.muted,
    switching: C$3.cyan,
    blocked: C$3.amber,
    error: C$3.red,
};
function StatusGlyph({ state }) {
    if (state === "ready") {
        return SP_JSX.jsx("span", { "aria-hidden": "true", style: {
                width: 14, height: 14, borderRadius: 999, border: `2px solid ${C$3.green}`,
                display: "grid", placeItems: "center", color: C$3.green, fontWeight: 900, fontSize: 13,
                boxShadow: `0 0 12px ${C$3.green}18`, boxSizing: "border-box",
            }, children: "\u2713" });
    }
    if (state === "blocked" || state === "error") {
        return SP_JSX.jsx("span", { "aria-hidden": "true", style: {
                width: 14, height: 14, borderRadius: 999, border: `2px solid ${stateColor[state]}`,
                display: "grid", placeItems: "center", color: stateColor[state], fontWeight: 900, fontSize: 13,
                boxSizing: "border-box",
            }, children: "!" });
    }
    return SP_JSX.jsx("span", { "aria-hidden": "true", className: state === "checking" || state === "switching" ? "regear-progress-spinner" : undefined, style: {
            width: 14, height: 14, borderRadius: 999, border: "2px solid rgba(255,255,255,.16)",
            borderTopColor: stateColor[state], boxSizing: "border-box", flexShrink: 0,
        } });
}
function phaseIndex(phase) {
    return phase === "connecting" ? 0 : phase === "switching" ? 1 : 2;
}
function headline(phase) {
    return phase === "connecting" ? "Getting your TV ready" : phase === "switching" ? "Switching to TV" : "Ready to play";
}
function ConnectionProgressOverlay(props) {
    const activeIndex = phaseIndex(props.phase);
    const elapsed = props.elapsedSeconds != null ? ` · ${props.elapsedSeconds} seconds` : "";
    return SP_JSX.jsxs("div", { style: {
            width: "100%", maxWidth: 420, minWidth: 0, boxSizing: "border-box", padding: 6,
            borderRadius: 22, background: `linear-gradient(180deg, ${C$3.bg} 0%, #071322 100%)`,
            border: `1px solid ${C$3.borderStrong}`, boxShadow: "0 26px 90px rgba(0,0,0,.58)",
            lineHeight: 1.2, color: C$3.text, fontFamily: "Motiva Sans, Inter, system-ui, sans-serif",
        }, children: [SP_JSX.jsx("style", { children: `
      @keyframes regear-spin { to { transform: rotate(360deg); } }
      @keyframes regear-sweep { 0% { opacity:.35; transform:scaleX(.35); transform-origin:left; } 50% { opacity:1; transform:scaleX(.78); transform-origin:left; } 100% { opacity:.35; transform:scaleX(.35); transform-origin:right; } }
      .regear-progress-spinner { animation: regear-spin 1s linear infinite; }
      .regear-progress-sweep { animation: regear-sweep 1.25s ease-in-out infinite; }
      .regear-hide-button:focus { outline: 3px solid rgba(57,216,255,.42); outline-offset: 3px; }
      @media (prefers-reduced-motion: reduce) { .regear-progress-spinner, .regear-progress-sweep { animation: none; } }
    ` }), SP_JSX.jsxs("div", { style: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 3, minWidth: 0 }, children: [SP_JSX.jsx("img", { src: brandIcon, alt: "", "aria-hidden": "true", width: 20, height: 20, style: { objectFit: "contain", flexShrink: 0 } }), SP_JSX.jsx("div", { style: { fontSize: 16, fontWeight: 820, letterSpacing: "-.02em" }, children: "Re-Gear" }), SP_JSX.jsx("div", { style: { color: C$3.muted, fontSize: 13, margin: "0 2px" }, children: "/" }), SP_JSX.jsx("div", { style: { fontSize: 13, fontWeight: 620 }, children: "Connection progress" })] }), SP_JSX.jsx("div", { style: { display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6, marginTop: 4, marginBottom: 4 }, children: ["Connecting", "Switching", "Ready"].map((name, i) => {
                    const active = i === activeIndex;
                    const complete = i < activeIndex;
                    return SP_JSX.jsxs("div", { children: [SP_JSX.jsxs("div", { style: { display: "flex", alignItems: "baseline", gap: 4, color: active ? C$3.text : C$3.muted, marginBottom: 4 }, children: [SP_JSX.jsxs("span", { style: { color: complete || active ? C$3.cyan : C$3.muted, fontWeight: 820, fontSize: 13 }, children: ["0", i + 1] }), SP_JSX.jsx("span", { style: { fontWeight: active ? 780 : 600, fontSize: 13 }, children: name })] }), SP_JSX.jsx("div", { style: { height: 4, borderRadius: 999, background: "rgba(105,130,155,.28)", overflow: "hidden" }, children: (complete || active) && SP_JSX.jsx("div", { className: active && props.phase === "switching" ? "regear-progress-sweep" : undefined, style: { width: "100%", height: "100%", borderRadius: 999, background: C$3.cyan, boxShadow: `0 0 12px ${C$3.cyan}66` } }) })] }, name);
                }) }), SP_JSX.jsxs("div", { style: {
                    border: `1px solid ${C$3.border}`, borderRadius: 18,
                    background: `linear-gradient(180deg, ${C$3.panel} 0%, ${C$3.panel2} 100%)`, padding: "6px",
                }, children: [SP_JSX.jsx("div", { style: { fontSize: 16, fontWeight: 830, letterSpacing: "-.02em", marginBottom: 3 }, children: headline(props.phase) }), SP_JSX.jsxs("div", { style: { color: C$3.muted, fontSize: 13, marginBottom: 6 }, children: [props.deviceLabel, elapsed] }), props.phase === "ready" && SP_JSX.jsx("div", { style: { display: "grid", placeItems: "center", margin: "2px 0 6px" }, children: SP_JSX.jsx("div", { style: { width: 36, height: 36, borderRadius: 999, border: `4px solid ${C$3.green}`, color: C$3.green, display: "grid", placeItems: "center", fontSize: 24, fontWeight: 500, boxShadow: `0 0 28px ${C$3.green}18` }, children: "\u2713" }) }), SP_JSX.jsx("div", { style: { border: `1px solid ${C$3.border}`, borderRadius: 14, overflow: "hidden", background: C$3.row }, children: props.rows.map((row, index) => SP_JSX.jsxs("div", { style: {
                                minHeight: 19, padding: "1px 6px", display: "grid", gridTemplateColumns: row.icon ? "20px minmax(0,1fr) auto" : "minmax(0,1fr) auto",
                                alignItems: "center", gap: 6, borderBottom: index === props.rows.length - 1 ? "none" : `1px solid ${C$3.border}`,
                            }, children: [row.icon && SP_JSX.jsx("div", { style: { color: C$3.text, opacity: .95 }, children: row.icon }), SP_JSX.jsx("div", { style: { fontSize: 13, minWidth: 0, overflowWrap: "anywhere" }, children: row.label }), SP_JSX.jsxs("div", { style: { display: "flex", alignItems: "center", gap: 6, color: stateColor[row.state], fontWeight: 700, fontSize: 13, whiteSpace: "nowrap" }, children: [SP_JSX.jsx(StatusGlyph, { state: row.state }), SP_JSX.jsx("span", { children: row.stateLabel ?? (row.state === "ready" ? "Ready" : row.state === "checking" ? "Checking" : row.state === "switching" ? "Switching" : row.state === "pending" ? "Next" : row.state === "blocked" ? "Blocked" : "Error") })] })] }, row.key)) }), props.detail && SP_JSX.jsx("div", { style: { marginTop: 4, color: C$3.muted, fontSize: 13 }, children: props.detail }), props.keepConnectedMessage && SP_JSX.jsx("div", { style: { marginTop: 6, color: C$3.muted, fontSize: 13 }, children: props.keepConnectedMessage }), SP_JSX.jsxs("div", { style: { display: "flex", gap: 8, marginTop: 6 }, children: [SP_JSX.jsx(DFL.DialogButton, { className: "rg-dashboard-action regear-hide-button", onClick: props.onHide, style: {
                                    margin: 0, padding: "4px 10px", height: 32, lineHeight: "22px", width: "100%", minWidth: 0, minHeight: 32, borderRadius: 12,
                                    border: `2px solid ${C$3.cyan}`, background: "rgba(5,16,28,.74)", color: C$3.text,
                                    fontSize: 17, fontWeight: 720, cursor: "pointer", boxShadow: `inset 0 0 18px ${C$3.cyan}08`,
                                }, children: "Hide" }), props.onSwitch && SP_JSX.jsx(DFL.DialogButton, { className: "rg-dashboard-action", onClick: props.onSwitch, style: { width: "100%", minWidth: 0, margin: 0, padding: "4px 10px", height: 32, minHeight: 32, lineHeight: "22px", fontSize: 14 }, children: "Switch to TV" })] })] })] });
}

/** Presentation adapter for the existing monitor: no snapshot inference or I/O. */
function connectionProgressViewModel(status, now = Date.now()) {
    const fresh = now < status.expiresAt;
    const phase = !fresh ? "connecting"
        : status.phase === "complete" ? "ready" : status.phase === "switching" ? "switching" : "connecting";
    let rows = status.rows.map((row, index) => ({
        key: String(index), label: row.label,
        state: !fresh ? "pending" : row.state === "waiting" ? "checking" : row.state,
    }));
    if (phase === "switching")
        rows = [
            { key: "display", label: "Display activation", state: "switching" },
            { key: "audio", label: "TV audio", state: "pending", stateLabel: "Not verified" },
            { key: "final", label: "Final verification", state: "pending", stateLabel: "Next" },
        ];
    if (phase === "ready")
        rows = [
            { key: "display", label: "TV display", state: "ready" },
            // Audio recovery readiness is not proof of active TV audio output.
            { key: "audio", label: "TV audio", state: "pending", stateLabel: "Check sound" },
        ];
    return { phase, rows, elapsedSeconds: status.seconds,
        deviceLabel: `${fresh && status.gpuName ? status.gpuName : "eGPU"} ${fresh && status.connected ? "connected" : "connection"}`,
        detail: !fresh ? "Waiting for a fresh status update" : phase === "ready"
            ? "TV transition reported complete. Check picture and sound. Closing automatically…" : status.title,
        keepConnectedMessage: "Keep eGPU connected · Hide keeps docking active.",
    };
}

function LivePanel({ store, close, switchTv }) {
    const source = SP_REACT.useSyncExternalStore(store.subscribe, store.get);
    const [, tick] = SP_REACT.useReducer((value) => value + 1, 0);
    SP_REACT.useEffect(() => { const timer = setInterval(tick, 1000); return () => clearInterval(timer); }, []);
    const stale = Date.now() >= source.expiresAt;
    const status = stale ? { phase: "checking", canSwitch: false,
        rows: source.rows.map(row => ({ ...row, state: "waiting" })) } : source;
    const complete = status.phase === "complete";
    SP_REACT.useEffect(() => {
        if (!complete)
            return;
        const timer = setTimeout(() => {
            const latest = store.get();
            if (latest.phase === "complete" && Date.now() < latest.expiresAt)
                close();
        }, 3500);
        return () => clearTimeout(timer);
    }, [complete, store, close]);
    const switchAction = status.canSwitch && switchTv ? () => {
        const latest = store.get();
        if (latest.canSwitch && Date.now() < latest.expiresAt) {
            close();
            switchTv();
        }
    } : undefined;
    return SP_JSX.jsxs(DFL.ModalRoot, { className: "rg-connection-modal rg-connection-compact", onCancel: close, closeModal: close, bDisableBackgroundDismiss: true, bHideCloseIcon: true, children: [SP_JSX.jsx("style", { children: connectionPanelCss }), SP_JSX.jsx(ConnectionProgressOverlay, { ...connectionProgressViewModel(source), onHide: close, onSwitch: switchAction })] });
}
function showConnectionLivePanel(store, switchTv, onClose) {
    let modal;
    const close = () => { modal.Close(); onClose(); };
    modal = DFL.showModal(SP_JSX.jsx(LivePanel, { store: store, switchTv: switchTv, close: close }), window, { strTitle: "Re-Gear", bNeverPopOut: true });
    return modal;
}

/** Player-facing name; keep legacy installation and safety-state identities separate. */
const PRODUCT_NAME = "Re-Gear";

class OfflineTestMemory {
    records = new Map();
    now;
    constructor(now = () => Date.now()) { this.now = now; }
    clear() { this.records.clear(); }
    forget(appId) { this.records.delete(appId); }
    confirm(binding) {
        const at = this.now();
        if (!Number.isFinite(at) || !Number.isSafeInteger(binding.appId) || binding.appId <= 0 ||
            !Number.isSafeInteger(binding.buildId) || binding.buildId <= 0 || !binding.account || !binding.store || !binding.app)
            return false;
        this.records.delete(binding.appId);
        this.records.set(binding.appId, { binding: { ...binding }, at });
        while (this.records.size > 32)
            this.records.delete(this.records.keys().next().value);
        return true;
    }
    has(binding) {
        const record = this.records.get(binding.appId);
        if (!record)
            return false;
        const age = this.now() - record.at;
        const valid = Number.isFinite(age) && age >= 0 && age < 24 * 60 * 60 * 1000 &&
            record.binding.buildId === binding.buildId && record.binding.account === binding.account &&
            record.binding.store === binding.store && record.binding.app === binding.app;
        if (!valid)
            this.forget(binding.appId);
        return valid;
    }
}
const offlineTestMemory = new OfflineTestMemory();

function record$1(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value)
        ? value : {};
}
function boolean(value) {
    return typeof value === "boolean" ? value : null;
}
function integer$1(value) {
    return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}
/** Explicit allowlist: never retain account, game identity, paths, or free text. */
function projectOfflinePreparation(raw) {
    const source = record$1(raw);
    const derived = record$1(source.deckDerivedProperties);
    const build = integer$1(source.nBuildID);
    return {
        buildId: build !== null && build > 0 ? build : null,
        hasLocalContent: boolean(source.bHasAnyLocalContent),
        subscribed: boolean(source.bIsSubscribedTo),
        thirdParty: boolean(source.bIsThirdPartyUpdater),
        displayStatus: integer$1(source.eDisplayStatus),
        cloudStatus: integer$1(source.eCloudStatus),
        cloudAvailable: boolean(source.bCloudAvailable),
        cloudEnabledAccount: boolean(source.bCloudEnabledForAccount),
        cloudEnabledApp: boolean(source.bCloudEnabledForApp),
        internetSingleplayer: boolean(derived.requires_internet_for_singleplayer),
        internetSetup: boolean(derived.requires_internet_for_setup),
    };
}
function assessOfflineConfidence(preparation, installed, tested = false, singleplayer = null) {
    const p = preparation;
    const blockers = [];
    const unknowns = [];
    const ready = [];
    const display = p.displayStatus;
    if (installed === false || p.hasLocalContent === false || display === 9 || display === 10)
        blockers.push("Install the game before offline play.");
    if ([3, 6, 7, 18, 19, 20, 21, 22, 23, 24, 25, 38, 39].includes(display))
        blockers.push("Finish pending downloads or updates.");
    if (p.subscribed === false || display === 26 || display === 27)
        blockers.push("Steam license needs attention online.");
    if (display === 34 || display === 35 || [4, 5, 6, 7, 8, 9, 10].includes(p.cloudStatus))
        blockers.push("Resolve pending or failed cloud-save synchronization.");
    if (p.internetSingleplayer === true)
        blockers.push("Steam reports internet is required for single-player play.");
    if (p.internetSetup === true)
        blockers.push("Steam reports an internet setup requirement; completion is unverified.");
    if (p.thirdParty === true)
        blockers.push("A third-party launcher needs a separate offline check.");
    if (installed !== true)
        unknowns.push("Local installation is not confirmed.");
    if (p.hasLocalContent !== true)
        unknowns.push("Local game content is not confirmed.");
    if (!(typeof p.buildId === "number" && Number.isSafeInteger(p.buildId) && p.buildId > 0))
        unknowns.push("Installed game version is unknown.");
    if (display !== 11)
        unknowns.push("Steam has not reported the game ready to launch.");
    else
        ready.push("Steam reports ready to launch with no pending download reported.");
    if (p.subscribed !== true)
        unknowns.push("Steam subscription is not confirmed.");
    const cloudDisabled = p.cloudAvailable === false || p.cloudEnabledAccount === false || p.cloudEnabledApp === false;
    const cloudSynced = p.cloudStatus === 3 && p.cloudAvailable === true &&
        p.cloudEnabledAccount === true && p.cloudEnabledApp === true;
    if (!cloudDisabled && !cloudSynced)
        unknowns.push("Cloud-save preparation is unknown.");
    else
        ready.push(cloudDisabled ? "Steam Cloud is unavailable or disabled; this does not verify save freshness." : "Steam reports cloud saves synchronized.");
    if (installed === true && p.hasLocalContent === true)
        ready.unshift("Installation and local content are reported present; file integrity is not verified.");
    const canConfirm = blockers.length === 0 && unknowns.length === 0;
    if (blockers.length)
        return { status: "needs_preparation", label: "Needs preparation", reasons: blockers, canConfirm: false };
    if (tested === true && canConfirm)
        return {
            status: "tested_offline", label: "Tested offline", canConfirm,
            reasons: ["You confirmed offline gameplay for this installed version.", ...ready, "A previous test does not guarantee future offline authorization."],
        };
    if (singleplayer !== true)
        unknowns.push("Single-player support is not confirmed by Steam categories.");
    if (p.thirdParty !== false)
        unknowns.push("Third-party launcher requirements are unknown.");
    if (p.internetSingleplayer !== false)
        unknowns.push("Offline single-player compatibility is unverified.");
    if (p.internetSetup !== false)
        unknowns.push("Internet setup requirements are unverified.");
    if (canConfirm && unknowns.length === 0)
        return {
            status: "likely_offline_ready", label: "Likely offline-ready", canConfirm,
            reasons: [...ready, "Steam compatibility metadata reports no internet requirement for single-player or setup.", "Offline license authorization is not guaranteed."],
        };
    return { status: "unverified", label: "Unverified", canConfirm, reasons: [...ready, ...unknowns] };
}

// Adapted from mcarlucci/decky-storage-cleaner, src/utils.ts, revision
// 932e6876dbf94b6feb4b033401139b193f9cc79a. Upstream license: GNU GPL version 3.
// See THIRD_PARTY_NOTICES.md. Changes: injected subscription, cancellation,
// synchronous callback handling, fail-closed cleanup, and exact input checks.
/**
 * One private, explicitly requested game-detail subscription, never a poller.
 * Used by the bounded selected-game check; see the offline source review.
 * Callback receipt time does not prove freshness. Caller must minimize fields
 * and discard on game/session changes; raw details must not enter public RPC.
 */
function requestSteamAppDetails(appId, subscribe, signal) {
    if (!Number.isInteger(appId) || appId <= 0 || appId >= 2 ** 32 || signal?.aborted) {
        return Promise.resolve(null);
    }
    return new Promise((resolve) => {
        let lease;
        let registrationFinished = false;
        let pending = false;
        let settled = false;
        let result = null;
        const drain = () => {
            if (!registrationFinished || !pending || settled)
                return;
            settled = true;
            clearTimeout(timer);
            signal?.removeEventListener("abort", abort);
            try {
                if (lease)
                    lease.unregister();
            }
            catch {
                result = null;
            }
            resolve(result);
        };
        const finish = (value) => {
            if (pending || settled)
                return;
            pending = true;
            result = value ?? null;
            drain();
        };
        const abort = () => {
            // Cancellation during registration overrides an early callback result.
            if (!settled) {
                pending = true;
                result = null;
                drain();
            }
        };
        const timer = setTimeout(() => finish(null), 1000);
        signal?.addEventListener("abort", abort, { once: true });
        try {
            lease = subscribe(appId, finish);
            if (!lease || typeof lease.unregister !== "function") {
                lease = undefined;
                pending = true;
                result = null;
            }
        }
        catch {
            pending = true;
            result = null;
        }
        registrationFinished = true;
        if (signal?.aborted)
            abort();
        drain();
    });
}

// Only fields consumed by the Python projector may cross the private reader seam.
function minimizeOfflineDetails(value) {
    if (!value || typeof value !== "object" || Array.isArray(value))
        return null;
    const source = value;
    const result = {};
    for (const key of ["iInstallFolder", "eDisplayStatus", "eCloudStatus"]) {
        const field = source[key];
        if (typeof field === "number" && Number.isSafeInteger(field))
            result[key] = field;
    }
    for (const key of ["bCloudAvailable", "bCloudEnabledForAccount", "bCloudEnabledForApp", "bIsThirdPartyUpdater"]) {
        if (typeof source[key] === "boolean")
            result[key] = source[key];
    }
    return result;
}
/** Private view lifetime; invalidate on selection, Steam session, or game-state changes.
 * No polling or persistence. Supplies minimized RPC fields and private preparation clues.
 */
class OfflineDetailsSession {
    generation = 0;
    pending;
    invalidate() {
        this.generation++;
        this.pending?.abort();
        this.pending = undefined;
    }
    async request(appId, subscribe, isCurrentAndIdle, now = () => performance.now()) {
        this.invalidate();
        const generation = this.generation;
        const controller = new AbortController();
        this.pending = controller;
        try {
            const started = now();
            if (!Number.isFinite(started) || !isCurrentAndIdle())
                return null;
            const raw = await requestSteamAppDetails(appId, subscribe, controller.signal);
            const received = now();
            if (!Number.isFinite(received) || received < started || received - started > 1000)
                return null;
            let expired = false;
            const valid = () => {
                try {
                    const current = now();
                    const accepted = !expired && generation === this.generation && !controller.signal.aborted &&
                        Number.isFinite(current) && current >= received && current - received < 1000 &&
                        isCurrentAndIdle();
                    if (!accepted)
                        expired = true;
                    return accepted;
                }
                catch {
                    expired = true;
                    return false;
                }
            };
            if (!valid())
                return null;
            const details = minimizeOfflineDetails(raw);
            return details ? { details, preparation: projectOfflinePreparation(raw), isValid: valid } : null;
        }
        catch {
            return null;
        }
        finally {
            if (this.pending === controller)
                this.pending = undefined;
        }
    }
}

/** Public reason copy only. Never render a backend string as player guidance. */
const GUIDANCE = {
    cloud_save_failed: "Steam reports a cloud-save problem. Resolve it in Steam before going offline.",
    steam_authorization_required: "Steam reports a pending or expired license. Connect to Steam and check this game before going offline.",
    cloud_save_conflict: "Resolve the Steam Cloud conflict for this game before going offline.",
    cloud_save_pending: "Wait for this game's Steam Cloud sync to finish before going offline.",
    game_not_installed: "Install this game on this handheld before going offline.",
    missing_local_content: "Finish installing this game's files before going offline.",
    local_storage_unavailable: "Check that this game's storage is available.",
    install_integrity_unconfirmed: "Check this game's installation in Steam before going offline.",
    update_pending: "Finish this game's update in Steam before going offline.",
    download_pending: "Finish this game's download in Steam before going offline.",
    offline_evidence_game_active: "Close the game, then check again.",
    offline_evidence_game_unknown: "Wait until Steam can confirm no game is running, then check again.",
    offline_evidence_context_changed: "Select the game you want to check and try again.",
    offline_evidence_stale: "This check is out of date. Check the selected game again.",
    third_party_launcher: "Open this game while online to check its launcher requirements.",
    drm: "This game's authorization may need an online check before offline play.",
    anti_cheat: "This game's anti-cheat may need an online check before offline play.",
    game_owned_online_requirement: "Check this game's internet requirements before going offline.",
    steam_entitlement_unknown: "Offline authorization could not be confirmed. Test this game in Steam Offline Mode before relying on it.",
    cloud_save_unknown: "Cloud save status could not be confirmed. Check this game's sync status in Steam.",
    install_unknown: "Local installation could not be confirmed. Check this game in Steam.",
    download_state_unknown: "Update status could not be confirmed. Check this game's downloads in Steam.",
    offline_evidence_source_unreviewed: "Offline checks are not available for this source yet.",
    offline_evidence_privacy_unreviewed: "Offline checks are not available for this source yet.",
    offline_evidence_cost_unbenchmarked: "Offline checks are not available for this source yet.",
    offline_evidence_cost_exceeds_budget: "The check could not finish within its performance limit. Check this game in Steam.",
    offline_evidence_unavailable: "This game's status is unavailable. Check it in Steam or try again.",
    local_readiness_confirmed: "Offline play is not guaranteed. Try this game in Steam Offline Mode before relying on it away from Wi-Fi.",
};
function sanitizeOfflineReasonCodes(value) {
    if (!Array.isArray(value) || value.length > 16)
        return [];
    return [...new Set(value.filter((item) => typeof item === "string" && Object.hasOwn(GUIDANCE, item)))];
}
function offlineReadinessDetail(reasons) {
    const allowed = new Set(sanitizeOfflineReasonCodes(reasons));
    // Preserve priority even if a transport changes the order of reason codes.
    const reason = Object.keys(GUIDANCE).find((key) => allowed.has(key));
    return reason === undefined ? undefined : GUIDANCE[reason];
}

/** Badges for the limited Steam-report source. It cannot certify offline launch. */
function offlineReportBadge(value) {
    if (!value || typeof value !== "object" || Array.isArray(value))
        return null;
    const report = value;
    if (report.schema_version !== 1 || !sanitizeOfflineReasonCodes(report.reason_codes).length)
        return null;
    switch (report.status) {
        case "needs_attention": return { asset: "offline-attention", label: "Offline needs attention" };
        case "online_check_needed": return { asset: "offline-verify", label: "Online check needed" };
        case "unknown": {
            const reasons = sanitizeOfflineReasonCodes(report.reason_codes);
            const incomplete = new Set(["install_unknown", "download_state_unknown", "steam_entitlement_unknown", "cloud_save_unknown"]);
            return reasons.length && reasons.every(reason => incomplete.has(reason))
                ? { asset: "offline-verify", label: "Offline readiness unverified" } : null;
        }
        // Ready and Internet required require stronger evidence than this source provides.
        default: return null;
    }
}

/** Account identity stays inside this private, session-only frontend boundary. */
function offlineAccountScope() {
    try {
        const value = window.loginStore?.m_strAccountName;
        return typeof value === "string" && value.length > 0 && value.length <= 128 ? value : null;
    }
    catch {
        return null;
    }
}
function offlineConfidenceForGame(preparation, source, appId, report, confirm = null) {
    const legacy = offlineReportBadge(report);
    if (!legacy) {
        offlineTestMemory.forget(appId);
        return { status: "unverified", label: "Unverified", reasons: ["The check is unavailable or the game context changed."], canConfirm: false };
    }
    const app = source.store.GetAppOverviewByAppID(appId);
    const installed = app?.local_per_client_data?.installed;
    let singleplayer = null;
    try {
        singleplayer = app?.BHasStoreCategory?.(2);
    }
    catch { /* Missing cached category stays unknown. */ }
    const base = assessOfflineConfidence(preparation, installed, false, singleplayer);
    if (["needs_attention", "online_check_needed"].includes(String(report.status)) && base.status !== "needs_preparation") {
        offlineTestMemory.forget(appId);
        return { status: "needs_preparation", label: "Needs preparation", reasons: ["Steam reports a preparation or authorization issue. Resolve it before relying on offline play."], canConfirm: false };
    }
    const account = offlineAccountScope();
    const binding = app && account && preparation.buildId
        ? { appId, buildId: preparation.buildId, account, store: source.store, app } : null;
    if (!base.canConfirm || !binding) {
        offlineTestMemory.forget(appId);
        return { ...base, canConfirm: false };
    }
    if (confirm) {
        if (confirm.appId !== binding.appId || confirm.buildId !== binding.buildId || confirm.account !== binding.account ||
            confirm.store !== binding.store || confirm.app !== binding.app) {
            offlineTestMemory.forget(appId);
            return { status: "unverified", label: "Unverified", reasons: ["The game version or account changed. Check and test the current version again."], canConfirm: false };
        }
        offlineTestMemory.confirm(binding);
    }
    return assessOfflineConfidence(preparation, installed, offlineTestMemory.has(binding), singleplayer);
}
function offlineConfidenceBadge(value) {
    return { asset: value.status === "needs_preparation" ? "offline-attention" :
            value.status === "likely_offline_ready" || value.status === "tested_offline" ? "offline-ready" : "offline-verify", label: value.label };
}

var ready = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMTAgMTEwIj48Y2lyY2xlIGN4PSI1NSIgY3k9IjU1IiByPSI1NCIgZmlsbD0iIzBmMTUxYiIvPjxwYXRoIGZpbGw9IiMyMGJmZjMiIGQ9Ik00NSA3aDIwbDMgMTIgMTAgNiAxMi00IDEwIDE4LTkgOHYxNmw5IDgtMTAgMTgtMTItNC0xMCA2LTMgMTJINDVsLTMtMTItMTAtNi0xMiA0TDEwIDcxbDktOFY0N2wtOS04IDEwLTE4IDEyIDQgMTAtNloiLz48Y2lyY2xlIGN4PSI1NSIgY3k9IjU1IiByPSIyOSIgZmlsbD0iIzBmMTUxYiIvPjxnIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzIwYmZmMyIgc3Ryb2tlLXdpZHRoPSI3IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Im00MyA1NCA4IDggMTctMjAiLz48L2c+PC9zdmc+";

var attention = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMTAgMTEwIj48Y2lyY2xlIGN4PSI1NSIgY3k9IjU1IiByPSI1NCIgZmlsbD0iIzBmMTUxYiIvPjxwYXRoIGZpbGw9IiNmZmQxNWIiIGQ9Ik00NSA3aDIwbDMgMTIgMTAgNiAxMi00IDEwIDE4LTkgOHYxNmw5IDgtMTAgMTgtMTItNC0xMCA2LTMgMTJINDVsLTMtMTItMTAtNi0xMiA0TDEwIDcxbDktOFY0N2wtOS04IDEwLTE4IDEyIDQgMTAtNloiLz48Y2lyY2xlIGN4PSI1NSIgY3k9IjU1IiByPSIyOSIgZmlsbD0iIzBmMTUxYiIvPjxnIGZpbGw9Im5vbmUiIHN0cm9rZT0iI2ZmZDE1YiIgc3Ryb2tlLXdpZHRoPSI3IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik01NSAzN3YyMG0wIDEydjEiLz48L2c+PC9zdmc+";

var verify = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMTAgMTEwIj48Y2lyY2xlIGN4PSI1NSIgY3k9IjU1IiByPSI1NCIgZmlsbD0iIzBmMTUxYiIvPjxwYXRoIGZpbGw9IiM4YWM1ZTUiIGQ9Ik00NSA3aDIwbDMgMTIgMTAgNiAxMi00IDEwIDE4LTkgOHYxNmw5IDgtMTAgMTgtMTItNC0xMCA2LTMgMTJINDVsLTMtMTItMTAtNi0xMiA0TDEwIDcxbDktOFY0N2wtOS04IDEwLTE4IDEyIDQgMTAtNloiLz48Y2lyY2xlIGN4PSI1NSIgY3k9IjU1IiByPSIyOSIgZmlsbD0iIzBmMTUxYiIvPjxnIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzhhYzVlNSIgc3Ryb2tlLXdpZHRoPSI3IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik00NSA0M2MwLTE0IDIzLTE0IDIzIDAgMCA4LTEzIDgtMTMgMTZtMCAxMHYxIi8+PC9nPjwvc3ZnPg==";

const offlineBadgeImages = { "offline-ready": ready, "offline-attention": attention, "offline-verify": verify };

// Native interfaces are checked at use time: Steam updates may remove them.
function offlineNativeSource() {
    const native = window;
    const store = native.appStore;
    const apps = native.SteamClient?.Apps;
    if (!store || typeof store.m_mapApps?.values !== "function" ||
        typeof store.GetAppOverviewByAppID !== "function" ||
        typeof apps?.RegisterForAppDetails !== "function")
        return null;
    return { store, subscribe: apps.RegisterForAppDetails.bind(apps) };
}

/** Compact gear matches the native symbol height, capped at 24 CSS pixels. */
function offlineBadgeLayout(host, clientWidth, clientHeight, icon, group = icon) {
    const values = [host.left, host.top, host.width, host.height, clientWidth, clientHeight, icon.left, icon.top, icon.width, icon.height, group.left, group.top, group.width, group.height];
    if (!values.every(Number.isFinite) || Math.min(host.width, host.height, clientWidth, clientHeight, icon.width, icon.height, group.width, group.height) <= 0)
        return null;
    const sx = host.width / clientWidth, sy = host.height / clientHeight;
    const height = Math.min(24, icon.height / sy);
    if (height < 12)
        return null;
    const width = height, left = 6;
    const bottom = (host.top + host.height - icon.top - icon.height / 2) / sy - height / 2;
    if (bottom < 0 || bottom + height > clientHeight || left + width + 4 > (group.left - host.left) / sx)
        return null;
    return { width, height, left, bottom };
}

// Native DOM seam researched in sebet/decky-nonsteam-badges (BSD-3-Clause),
// cc620181962f601b713c9db2045e98dd82ecdbf2. Independent bounded implementation:
// exact data-id only; no native style changes, per-tile requests, or polling.
const OFFLINE_TILE_SELECTOR = 'div[role="tabpanel"] div[role="gridcell"],.ReactVirtualized__Grid__innerScrollContainer div[role="listitem"]';
const OWN = "data-regear-offline-badge";
function exactTileAppId(value) {
    if (!value || !/^[1-9][0-9]{0,9}$/.test(value))
        return null;
    const id = Number(value);
    return id < 2 ** 32 ? id : null;
}
function exactTileElementAppId(tile) {
    const direct = exactTileAppId(tile.getAttribute("data-id"));
    if (direct !== null)
        return direct;
    const ids = new Set();
    for (const image of Array.from(tile.querySelectorAll("img")).slice(0, 8)) {
        for (const match of (image.getAttribute("src") ?? "").matchAll(/\/(?:apps|assets|customimages)\/(\d+)(?:\/|[p.]|$)/g)) {
            const id = exactTileAppId(match[1]);
            if (id !== null)
                ids.add(id);
        }
    }
    return ids.size === 1 ? [...ids][0] : null;
}
function attachOfflineTileBadge(view, appId, image, label, current, initialTile, expiredBadge, expiryMs = 30000) {
    const owned = new Map();
    let stopped = false;
    let timer;
    let observer;
    const stop = () => {
        stopped = true;
        observer?.disconnect();
        clearTimeout(timer);
        for (const badge of owned.values())
            badge.remove();
        owned.clear();
    };
    const validate = () => {
        try {
            if (!current())
                stop();
        }
        catch {
            stop();
        }
    };
    const reconcile = (tile) => {
        if (initialTile && tile !== initialTile)
            return;
        const existing = owned.get(tile);
        const artwork = Array.from(tile.querySelectorAll("img")).find(img => {
            const src = img.getAttribute("src") ?? "";
            return src.includes(`/${appId}/`) || src.includes(`/${appId}p.`) || src.includes(`/${appId}.`);
        });
        let host = tile;
        if (view.getComputedStyle(host).position === "static" && artwork) {
            host = artwork.parentElement;
            while (host && host !== tile && view.getComputedStyle(host).position === "static")
                host = host.parentElement;
        }
        if (!tile.isConnected || !tile.matches(OFFLINE_TILE_SELECTOR) ||
            exactTileElementAppId(tile) !== appId || !host || view.getComputedStyle(host).position === "static") {
            existing?.remove();
            owned.delete(tile);
            return;
        }
        let css = "position:absolute;bottom:6px;left:6px;width:24px;height:24px;pointer-events:none;z-index:2";
        // Inspect only a few native SVGs on this exact tile. A visible square
        // lower-right icon is Steam's compatibility mark, not the cover artwork.
        const icons = Array.from(tile.querySelectorAll("svg")).slice(0, 16);
        if (icons.length) {
            const bounds = host.getBoundingClientRect();
            const matches = icons.map(element => ({ element, rect: element.getBoundingClientRect() })).filter(({ rect: r }) => r.width > 0 && r.height > 0 && r.width / r.height > 0.9 && r.width / r.height < 1.1 &&
                r.left >= bounds.left + bounds.width * 0.5 && r.top >= bounds.top + bounds.height * 0.7 &&
                r.right <= bounds.right + 1 && r.bottom <= bounds.bottom + 1);
            if (matches.length === 1) {
                const reference = matches[0];
                let nativeGroup = reference.rect;
                let parent = reference.element.parentElement;
                for (let depth = 0; parent && parent !== tile && depth < 3; depth++, parent = parent.parentElement) {
                    if (parent.querySelectorAll("svg").length !== 2)
                        continue;
                    const group = parent.getBoundingClientRect();
                    if (group.width <= bounds.width * 0.65 && group.height <= bounds.height * 0.3)
                        nativeGroup = group;
                    break;
                }
                const layout = offlineBadgeLayout(bounds, host.clientWidth, host.clientHeight, reference.rect, nativeGroup);
                if (layout)
                    css = `position:absolute;bottom:${layout.bottom}px;left:${layout.left}px;width:${layout.width}px;height:${layout.height}px;pointer-events:none;z-index:2`;
            }
        }
        if (existing?.parentElement === host) {
            existing.style.cssText = css;
            return;
        }
        existing?.remove();
        const badge = view.document.createElement("img");
        badge.setAttribute(OWN, "");
        badge.src = image;
        badge.alt = label;
        badge.title = `${label} â€” Steam report at check time`;
        badge.width = 24;
        badge.height = 24;
        badge.style.cssText = css;
        host.appendChild(badge);
        owned.set(tile, badge);
    };
    try {
        validate();
        if (!stopped) {
            const tiles = initialTile ? [initialTile] : Array.from(view.document.querySelectorAll(OFFLINE_TILE_SELECTOR));
            // Fail closed rather than process an unexpectedly large rendered surface.
            if (tiles.length > 256)
                stop();
            else
                for (const tile of Array.from(tiles))
                    reconcile(tile);
        }
        if (!stopped) {
            const Observer = view.MutationObserver;
            observer = new Observer((records) => {
                validate();
                if (stopped)
                    return;
                try {
                    if (initialTile) {
                        reconcile(initialTile);
                        return;
                    }
                    if (records.length > 128) {
                        stop();
                        return;
                    }
                    const candidates = new Set();
                    const collect = (node) => {
                        if (node.nodeType !== 1)
                            return;
                        const element = node;
                        if (element.hasAttribute(OWN))
                            return;
                        const parent = element.closest(OFFLINE_TILE_SELECTOR);
                        if (parent)
                            candidates.add(parent);
                        for (const tile of Array.from(element.querySelectorAll(OFFLINE_TILE_SELECTOR))) {
                            candidates.add(tile);
                            if (candidates.size > 256)
                                throw new Error();
                        }
                    };
                    for (const record of records) {
                        // Own insertion/removal is not a reason to rescan its tile subtree.
                        if (record.type === "childList" && [...Array.from(record.addedNodes), ...Array.from(record.removedNodes)].every(node => node.nodeType === 1 && node.hasAttribute(OWN)))
                            continue;
                        collect(record.target);
                        for (const node of Array.from(record.addedNodes))
                            collect(node);
                    }
                    // An ancestor can change role/class while the tile stays connected.
                    // Revalidate the bounded set we own, not just newly matching selectors.
                    for (const tile of owned.keys())
                        reconcile(tile);
                    for (const tile of candidates)
                        reconcile(tile);
                }
                catch {
                    stop();
                }
            });
            observer.observe(view.document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-id", "role", "class", "src"] });
            timer = setTimeout(() => {
                validate();
                if (stopped)
                    return;
                if (!expiredBadge) {
                    stop();
                    return;
                }
                // Preserve the affordance, but never leave an expired positive claim.
                image = expiredBadge.image;
                label = expiredBadge.label;
                for (const badge of owned.values()) {
                    badge.src = image;
                    badge.alt = label;
                    badge.title = label;
                }
            }, expiryMs);
        }
    }
    catch {
        stop();
    }
    return { stop, validate };
}

const classify = callable("classify_offline_details");
const SETTLE_MS = 450;
const REFRESH_MS = 60000;
const RETRY_MS = 5000;
function libraryWindows() {
    try {
        const host = window;
        const trees = host.DFL?.getGamepadNavigationTrees?.();
        if (!Array.isArray(trees))
            return [];
        return [...new Set(trees.slice(0, 16).map(tree => tree.m_window).filter((view) => !!view))];
    }
    catch {
        return [];
    }
}
/** Start once with the plugin, independently of Quick Access rendering. */
function startOfflineFocusChecks() {
    const session = new OfflineDetailsSession();
    let timer;
    let sequence = 0;
    let selectedTile = null;
    let selectedId = null;
    let shown;
    let selectionContextMatches;
    const cancel = () => { sequence++; clearTimeout(timer); session.invalidate(); shown?.stop(); shown = undefined; };
    const context = (id, app, source) => window.appStore === source.store && source.store.GetAppOverviewByAppID(id) === app && app.display_status !== 4 && Array.isArray(DFL.Router.RunningApps) && DFL.Router.RunningApps.length === 0;
    const focus = (event) => {
        const target = event.target;
        const tile = target?.closest?.(OFFLINE_TILE_SELECTOR);
        const id = tile ? exactTileElementAppId(tile) : null;
        const view = tile?.ownerDocument.defaultView;
        if (event.type !== "focusin" && tile === selectedTile && id === selectedId && selectionContextMatches?.())
            return;
        cancel();
        selectedTile = tile ?? null;
        selectedId = id;
        selectionContextMatches = undefined;
        if (!tile || !view || id === null)
            return;
        const request = sequence;
        const selected = () => request === sequence && tile.isConnected &&
            tile.ownerDocument.activeElement?.closest(OFFLINE_TILE_SELECTOR) === tile && exactTileElementAppId(tile) === id;
        const capture = () => {
            const source = offlineNativeSource();
            const app = source?.store.GetAppOverviewByAppID(id);
            const account = offlineAccountScope();
            const displayStatus = app?.display_status;
            const idle = Array.isArray(DFL.Router.RunningApps) && DFL.Router.RunningApps.length === 0;
            selectionContextMatches = () => offlineAccountScope() === account &&
                window.appStore === source?.store && source?.store.GetAppOverviewByAppID(id) === app &&
                app?.display_status === displayStatus && idle === (Array.isArray(DFL.Router.RunningApps) && DFL.Router.RunningApps.length === 0);
            return { source, app, matches: selectionContextMatches };
        };
        capture();
        let failures = 0;
        // Re-read on settled selection so positive confidence cannot reuse an old build report.
        const check = async () => {
            let delay = REFRESH_MS;
            try {
                if (!selected())
                    return;
                shown?.validate();
                const { source, app, matches } = capture();
                if (!source || !app || !context(id, app, source)) {
                    session.invalidate();
                    return;
                }
                // Bind each attempt to its own observation, not the original focus state.
                // Once invalidated, a late response cannot become valid again.
                let invalid = false;
                const valid = () => { invalid ||= !selected() || !matches() || !context(id, app, source); return !invalid; };
                delay = ++failures <= 2 ? RETRY_MS : REFRESH_MS;
                const report = await session.request(id, source.subscribe, valid);
                if (!report || !report.isValid() || !valid())
                    return;
                const result = await classify(report.details);
                if (!report.isValid() || request !== sequence || !valid())
                    return;
                if (!offlineReportBadge(result))
                    return;
                const badge = offlineConfidenceBadge(offlineConfidenceForGame(report.preparation, source, id, result));
                shown?.stop();
                shown = attachOfflineTileBadge(view, id, offlineBadgeImages[badge.asset], badge.label, valid, tile, { image: offlineBadgeImages["offline-verify"], label: "Check unavailable" }, 65000);
                failures = 0;
                delay = REFRESH_MS;
            }
            catch { /* Failed refresh expires to neutral; never retain a stale positive. */ }
            finally {
                // Keep the existing cadence alive while this exact tile is selected,
                // including gameplay/unknown state. Ineligible ticks make no requests.
                if (selected())
                    timer = setTimeout(check, delay);
            }
        };
        timer = setTimeout(check, SETTLE_MS);
    };
    const views = new Map();
    const refresh = (view) => {
        const active = view.document.activeElement;
        if (active?.closest?.(OFFLINE_TILE_SELECTOR) || selectedTile?.ownerDocument === view.document)
            focus({ target: active });
    };
    const syncViews = () => {
        for (const view of libraryWindows()) {
            if (!views.has(view)) {
                view.document.addEventListener("focusin", focus, true);
                const Observer = view.MutationObserver;
                // Controller tab changes and recycled artwork need not emit focusin.
                // Inspect only the active element; never enumerate library tiles.
                const observer = new Observer(() => refresh(view));
                observer.observe(view.document.body, { subtree: true, childList: true,
                    attributes: true, attributeFilter: ["class", "role", "data-id", "src"] });
                views.set(view, observer);
            }
            refresh(view);
        }
    };
    // Steam may not expose navigation windows when Decky first loads. Route
    // patches provide an event-driven retry without a timer or document scan.
    const routePatch = (route) => { syncViews(); return route; };
    const libraryPatch = routerHook.addPatch("/library", routePatch);
    const homePatch = routerHook.addPatch("/library/home", routePatch);
    const searchPatch = routerHook.addPatch("/search", routePatch);
    syncViews();
    return { stop() {
            cancel();
            offlineTestMemory.clear();
            routerHook.removePatch("/library", libraryPatch);
            routerHook.removePatch("/search", searchPatch);
            routerHook.removePatch("/library/home", homePatch);
            for (const [view, observer] of views) {
                view.document.removeEventListener("focusin", focus, true);
                observer.disconnect();
            }
            views.clear();
        } };
}

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
            value: payload.connection_readiness
                ? `${humanize(payload.connection_readiness.stage)} · ${humanize(payload.connection_readiness.code)}`
                : payload.attach_readiness
                    ? `${humanize(payload.attach_readiness.stage)} · ${humanize(payload.attach_readiness.code)}`
                    : "unavailable",
        },
        { name: "Snapshot schema", value: String(snapshot.schema_version) },
        { name: "Reported Re-Gear build", value: reportedBuildLabel(payload.diagnostics.build) },
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
            name: "Re-Gear overhead",
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

var handheldModeIcon = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI1MTIiIGhlaWdodD0iNTEyIiB2aWV3Qm94PSIwIDAgNTEyIDUxMiIgZmlsbD0ibm9uZSI+CiAgPGc+CiAgICA8cmVjdCB4PSI0OCIgeT0iMTMyIiB3aWR0aD0iNDE2IiBoZWlnaHQ9IjI0OCIgcng9Ijc4IiBmaWxsPSIjMDgxODJBIiBzdHJva2U9IiMzNWQ2ZjUiIHN0cm9rZS13aWR0aD0iMTIiLz4KICAgIDxyZWN0IHg9IjE2NiIgeT0iMTY2IiB3aWR0aD0iMTgwIiBoZWlnaHQ9IjE4MCIgcng9IjE0IiBmaWxsPSIjMDIwQTE0IiBzdHJva2U9IiMwRDJCNTAiIHN0cm9rZS13aWR0aD0iOCIvPgogICAgPHJlY3QgeD0iMTg0IiB5PSIxODQiIHdpZHRoPSIxNDQiIGhlaWdodD0iMTQ0IiByeD0iOCIgZmlsbD0iIzEwMjIzNyIvPgogICAgPGNpcmNsZSBjeD0iMTA0IiBjeT0iMjAwIiByPSIyNCIgZmlsbD0iIzBBMTkzMCIgc3Ryb2tlPSIjMzVkNmY1IiBzdHJva2Utd2lkdGg9IjkiLz4KICAgIDxjaXJjbGUgY3g9IjQwOCIgY3k9IjIwMCIgcj0iMjQiIGZpbGw9IiMwQTE5MzAiIHN0cm9rZT0iIzM1ZDZmNSIgc3Ryb2tlLXdpZHRoPSI5Ii8+CiAgICA8cGF0aCBkPSJNOTUgMjY2aDE4djE4aDE4djE4aC0xOHYxOEg5NXYtMThINzd2LTE4aDE4di0xOFoiIGZpbGw9IiMzNWQ2ZjUiLz4KICAgIDxjaXJjbGUgY3g9IjQwMiIgY3k9IjI3OCIgcj0iOSIgZmlsbD0iIzM1ZDZmNSIvPgogICAgPGNpcmNsZSBjeD0iNDI4IiBjeT0iMjk0IiByPSI5IiBmaWxsPSIjMzVkNmY1Ii8+CiAgICA8Y2lyY2xlIGN4PSIzNzYiIGN5PSIyOTQiIHI9IjkiIGZpbGw9IiMzNWQ2ZjUiLz4KICAgIDxjaXJjbGUgY3g9IjQwMiIgY3k9IjMxMCIgcj0iOSIgZmlsbD0iIzM1ZDZmNSIvPgogICAgPHJlY3QgeD0iOTEiIHk9IjMzNyIgd2lkdGg9IjMwIiBoZWlnaHQ9IjgiIHJ4PSI0IiBmaWxsPSIjMzVkNmY1Ii8+CiAgICA8cmVjdCB4PSIzOTEiIHk9IjMzNyIgd2lkdGg9IjMwIiBoZWlnaHQ9IjgiIHJ4PSI0IiBmaWxsPSIjMzVkNmY1Ii8+CiAgPC9nPgo8L3N2Zz4K";

var tvModeIcon = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI1MTIiIGhlaWdodD0iNTEyIiB2aWV3Qm94PSIwIDAgNTEyIDUxMiIgZmlsbD0ibm9uZSI+CiAgPGc+CiAgICA8cmVjdCB4PSI2NiIgeT0iMTAwIiB3aWR0aD0iMzgwIiBoZWlnaHQ9IjI0OCIgcng9IjI4IiBmaWxsPSIjMDcxNTI2IiBzdHJva2U9IiMzNWQ2ZjUiIHN0cm9rZS13aWR0aD0iMTIiLz4KICAgIDxyZWN0IHg9IjkyIiB5PSIxMjYiIHdpZHRoPSIzMjgiIGhlaWdodD0iMTk2IiByeD0iMTIiIGZpbGw9IiMxMDIyMzciIHN0cm9rZT0iIzBEMkI1MCIgc3Ryb2tlLXdpZHRoPSI4Ii8+CiAgICA8cGF0aCBkPSJNMjM2IDM0OGg0MHY1Mmg3MGMxMiAwIDIyIDEwIDIyIDIySDE0NGMwLTEyIDEwLTIyIDIyLTIyaDcwdi01MloiIGZpbGw9IiMwODE4MkEiIHN0cm9rZT0iIzM1ZDZmNSIgc3Ryb2tlLXdpZHRoPSIxMCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPgogIDwvZz4KPC9zdmc+Cg==";

/** Selection represents observed placement, never a clickable transition target. */
function placementCards(mode, loading = false) {
    return [
        { name: "Portable", detail: "Internal GPU · Handheld screen", active: !loading && mode === "portable" },
        { name: "TV Docked", detail: "External GPU · TV", active: !loading && (mode === "tv_docked" || mode === "docked_egpu") },
    ];
}
/** Bounded snapshot-only facts; opening this disclosure starts no extra requests. */
function hardwareDetailRows(payload) {
    const snapshot = payload?.snapshot;
    const displays = snapshot?.displays.filter((display) => display.active === true);
    const gpus = snapshot?.gpus.filter((gpu) => gpu.selected_for_render === true);
    const displayKnown = displays && displays.length > 0
        && displays.every((display) => display.confidence !== "unknown" && display.kind !== "unknown");
    const gpu = gpus?.length === 1 ? gpus[0] : undefined;
    const link = snapshot?.egpu_link;
    return [
        ["Active display", displayKnown
                ? [...new Set(displays.map((display) => display.kind === "internal" ? "Handheld" : "External"))].join(" + ")
                : "Unknown"],
        ["Render GPU", gpu?.present && gpu.confidence !== "unknown" && gpu.role !== "unknown"
                ? gpu.role === "internal" ? "Internal GPU" : "External GPU"
                : "Unknown"],
        ["eGPU link", link?.applicable && link.confidence !== "unknown"
                ? link.state === "up" ? "Observed up" : link.state === "down" ? "Observed down" : "Unknown"
                : "Unknown"],
    ];
}

const C$2 = {
    cyan: "#39d8ff",
    green: "#5eea8a",
    text: "#f4f7fb",
    muted: "#9eb2ca",
    border: "#294665"};
const paths = {
    handheld: "M5 6h14l3 12h-5l-2-3H9l-2 3H2z M6 10h5 M8.5 7.5v5 M16 9h.1 M18 11h.1",
    monitor: "M3 4h18v13H3z M8 21h8 M12 17v4",
    connection: "M8 3v5 M16 3v5 M6 8h12v4a6 6 0 0 1-12 0z M12 18v4",
    power: "M12 2v10 M6 5a9 9 0 1 0 12 0",
    bolt: "M13 2L4 14h7l-1 8 10-12h-7z",
    tools: "M14 3a6 6 0 0 0-7 7L2 15l7 7 5-5a6 6 0 0 0 7-7l-4 4-5-5z",
};
function DashboardIcon({ kind, size = 24 }) {
    return SP_JSX.jsx("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.7", strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", style: { flexShrink: 0 }, children: SP_JSX.jsx("path", { d: paths[kind] }) });
}
function DashboardSurface({ children, primary = false }) {
    return SP_JSX.jsx("div", { style: {
            borderRadius: 18,
            marginBottom: 12,
            minWidth: 0,
            overflow: "hidden",
            border: `1px solid ${primary ? "#9d7635" : C$2.border}`,
            background: primary
                ? "linear-gradient(115deg, rgba(82,58,16,.72), rgba(12,25,42,.98))"
                : "linear-gradient(120deg, rgba(14,31,52,.98), rgba(7,17,30,.98))",
            color: C$2.text,
            boxShadow: primary ? "inset 0 0 28px rgba(255,185,48,.05)" : "inset 0 0 24px rgba(0,170,255,.025)",
        }, children: children });
}
function CurrentStateCard({ modeLabel, health, game, loading }) {
    return SP_JSX.jsxs("div", { style: {
            padding: "10px 12px",
            marginBottom: 14,
            borderRadius: 14,
            border: `1px solid ${regearTheme.border}`,
            background: regearTheme.surface,
        }, children: [SP_JSX.jsx("div", { style: {
                    color: C$2.cyan,
                    fontSize: 12,
                    fontWeight: 760,
                    letterSpacing: "1.5px",
                    marginBottom: 5,
                }, children: "CURRENT STATE" }), SP_JSX.jsx("div", { style: {
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 10,
                    marginBottom: 12,
                }, children: SP_JSX.jsx("div", { style: { fontSize: 18, fontWeight: 700, lineHeight: 1.4 }, children: modeLabel }) }), [["Health", loading ? "Reading…" : health], ["Game", loading ? "Reading…" : game]].map(([name, value]) => SP_JSX.jsxs("div", { style: { display: "grid", gridTemplateColumns: "64px minmax(0,1fr)", gap: 8,
                    padding: "8px 0", borderTop: `1px solid ${regearTheme.border}`, fontSize: 13, lineHeight: 1.4 }, children: [SP_JSX.jsx("span", { style: { color: regearTheme.muted }, children: name }), SP_JSX.jsx("span", { style: { textAlign: "right", overflowWrap: "anywhere",
                            color: name === "Health" && !loading && health === "Ready" ? C$2.green : regearTheme.text }, children: value })] }, name))] });
}
function ModeCard({ name, detail, active, loading }) {
    const isPortable = name === "Portable";
    return SP_JSX.jsxs("div", { style: {
            minWidth: 0,
            minHeight: 130,
            padding: "18px 12px 14px",
            borderRadius: 20,
            border: `2px solid ${active ? C$2.cyan : "#36516f"}`,
            background: active
                ? "linear-gradient(145deg, rgba(4,53,82,.98), rgba(9,26,45,.98))"
                : "linear-gradient(145deg, rgba(12,28,47,.98), rgba(7,17,30,.98))",
            boxShadow: active ? `0 0 20px ${C$2.cyan}20, inset 0 0 24px ${C$2.cyan}0b` : "none",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
            color: active ? C$2.text : "#d7e3f1",
        }, children: [SP_JSX.jsx("div", { style: { color: active ? C$2.cyan : "#a6bfdc", marginBottom: 10 }, children: SP_JSX.jsx("img", { src: isPortable ? handheldModeIcon : tvModeIcon, width: 56, height: 56, alt: "", "aria-hidden": "true", style: { display: "block", objectFit: "contain" } }) }), SP_JSX.jsx("div", { style: { fontSize: 18, fontWeight: 760, marginBottom: 6 }, children: name }), SP_JSX.jsx("div", { style: { fontSize: 12, lineHeight: "16px", color: C$2.muted, minHeight: 32 }, children: detail }), SP_JSX.jsx("div", { style: { marginTop: 10, color: active ? C$2.cyan : C$2.muted, fontSize: 12, fontWeight: 700 }, children: active ? "ACTIVE" : loading ? "READING…" : "Not active" })] });
}
function QuickAccessOverview({ mode, modeLabel, health, game, loading, summaryRef, onSummaryFocus }) {
    const cards = placementCards(mode, loading);
    return SP_JSX.jsxs("div", { style: { color: C$2.text, minWidth: 0 }, children: [SP_JSX.jsx(SectionFocus, { ref: summaryRef, label: "At a glance: current state", onFocused: onSummaryFocus, children: SP_JSX.jsx(CurrentStateCard, { modeLabel: modeLabel, health: health, game: game, loading: loading }) }), SP_JSX.jsxs(SectionFocus, { label: "Your setup", children: [SP_JSX.jsx("div", { style: {
                            color: C$2.muted,
                            fontSize: 11,
                            fontWeight: 760,
                            letterSpacing: "1.6px",
                            margin: "2px 2px 8px",
                        }, children: "YOUR SETUP" }), SP_JSX.jsx("div", { style: { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }, children: cards.map((card) => SP_JSX.jsx(ModeCard, { ...card, loading: loading }, card.name)) })] })] });
}

/** Re-Gear action card: one controller focus target with mockup-style hierarchy. */
function DashboardAction({ title, description, icon, expanded, onClick, disabled, tone = "normal" }) {
    const primary = tone === "primary";
    const warning = tone === "warning";
    const accent = warning ? "#ffc247" : primary ? "#39d8ff" : "#35d6ff";
    return SP_JSX.jsx(DFL.DialogButton, { onClick: onClick, disabled: disabled, className: "rg-dashboard-action", "aria-expanded": expanded, style: {
            width: "100%", minWidth: 0, height: "auto", minHeight: 68, margin: 0,
            padding: "12px 13px", boxSizing: "border-box", borderRadius: 16,
            textAlign: "left", whiteSpace: "normal",
            background: warning
                ? "linear-gradient(135deg, rgba(65,47,15,.92), rgba(10,22,37,.98))"
                : primary
                    ? "linear-gradient(135deg, rgba(8,56,81,.94), rgba(8,24,41,.98))"
                    : "linear-gradient(135deg, rgba(19,36,58,.96), rgba(9,21,36,.98))",
            border: `1px solid ${disabled ? "#344457" : warning ? "#9d7635" : primary ? "#2c89a6" : "#2c4663"}`,
            boxShadow: disabled ? "none" : `inset 0 1px 0 rgba(255,255,255,.025), 0 0 20px ${accent}0a`,
        }, children: SP_JSX.jsxs("span", { style: { display: "grid", gridTemplateColumns: "38px minmax(0,1fr) 18px", alignItems: "center", gap: 11, width: "100%", minWidth: 0 }, children: [SP_JSX.jsx("span", { style: {
                        display: "flex", alignItems: "center", justifyContent: "center", width: 38, height: 38,
                        borderRadius: 11, color: disabled ? "#687b91" : accent,
                        background: disabled ? "rgba(25,37,51,.62)" : `${accent}14`,
                        border: `1px solid ${disabled ? "#344457" : `${accent}66`}`,
                    }, children: SP_JSX.jsx(DashboardIcon, { kind: icon }) }), SP_JSX.jsxs("span", { style: { display: "block", minWidth: 0, whiteSpace: "normal", wordBreak: "normal", overflowWrap: "normal", lineHeight: 1.3 }, children: [SP_JSX.jsx("span", { style: { display: "block", fontSize: 14, fontWeight: 760, color: disabled ? "#8394a7" : primary || warning ? accent : "#f2f7ff" }, children: title }), SP_JSX.jsx("span", { style: { display: "block", fontSize: 12, marginTop: 3, color: disabled ? "#708093" : "#9fb2ca" }, children: description })] }), SP_JSX.jsx("svg", { width: "18", height: "18", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", style: { opacity: disabled ? .35 : .75, color: warning || primary ? accent : undefined, transform: expanded ? "rotate(90deg)" : undefined, transition: "transform 120ms ease" }, children: SP_JSX.jsx("path", { d: "m9 5 7 7-7 7" }) })] }) });
}

const reasons = {
    "tdp.disabled": "Power control is off.",
    "tdp.ready": "Ready to adjust handheld power.",
    "tdp.conflict": "Another power controller is present. Resolve the overlap before enabling.",
    "tdp.portable_required": "Use Portable mode before adjusting handheld power.",
    "tdp.placement_unverified": "Verify the active display and render GPU before adjusting power.",
    "tdp.egpu_presence_unverified": "The eGPU connection state needs verification.",
    "tdp.egpu_attached": "Power control is paused while an eGPU is attached. Follow the disconnect workflow before returning to handheld power control.",
    "tdp.egpu_power_profile_unavailable": "Power control for Boosted Handheld and Docked-eGPU is not validated yet.",
    "tdp.docked_power_profile_unavailable": "Power control for internal-GPU docked play is not validated yet.",
    "tdp.game_unknown": "Game activity needs verification.",
    "tdp.transition_active": "Wait for the current mode change to finish.",
    "tdp.ownership_unverified": "Power control ownership needs verification.",
    "tdp.enable_required": "Enable power control to make changes.",
    "tdp.readback_verified": "Power settings were verified.",
    "tdp.already_observed": "The requested power setting is already active.",
    "tdp.nothing_to_restore": "There are no saved power settings to restore.",
    "tdp.baseline_not_restorable": "The original power settings cannot yet be restored by this control.",
    "tdp.dispatch_rejected": "The automatic request was stopped before changing power.",
};
for (const code of ["busy", "closing", "writer_busy"])
    reasons[`tdp.${code}`] = "Power control is busy. Refresh in a moment.";
for (const code of ["runtime_unavailable", "conflict_scan_unavailable", "host_unverified", "user_unverified", "boot_unverified", "owner_unavailable", "read_unavailable", "source_ambiguous", "firmware_unverified", "source_disagreement", "owner_changed", "observation_invalid", "observation_failed", "context_changed", "limit_invalid", "request_invalid", "request_out_of_range", "journal_unavailable", "revalidation_failed"])
    reasons[`tdp.${code}`] = "Power settings need verification. Refresh to check again.";
for (const code of ["previous_write_uncertain", "external_change", "write_outcome_unknown", "readback_unverified", "write_unverified"])
    reasons[`tdp.${code}`] = "Power settings need recovery before further changes.";
const known = (code) => typeof code === "string" && Object.hasOwn(reasons, code);
const watts$1 = (value) => typeof value === "number" && Number.isInteger(value) && value > 0 && value <= 0xFFFFFFFF;
const object$1 = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
function sanitizeTdpStatus(value) {
    if (!object$1(value) || value.schema_version !== 1 || typeof value.auto_tdp_available !== "boolean" || !known(value.code))
        return null;
    for (const field of ["enabled", "can_enable", "ready", "restore_available", "recovery_required"])
        if (typeof value[field] !== "boolean")
            return null;
    const fields = [value.current_watts, value.minimum_watts, value.maximum_watts];
    const empty = fields.every((field) => field === null);
    if (!empty && (!fields.every(watts$1) || value.minimum_watts > value.current_watts || value.current_watts > value.maximum_watts))
        return null;
    // Bound option allocation without making a device capability claim.
    if (!empty && value.maximum_watts - value.minimum_watts > 255)
        return null;
    if ((value.ready && (!value.enabled || !value.can_enable || value.code !== "tdp.ready")) || (empty && (value.ready || value.can_enable || value.restore_available)))
        return null;
    const last = value.last_result;
    if (last !== null && (!object$1(last) || !["blocked", "unchanged", "applied", "restored", "recovery_required"].includes(last.state) || !known(last.code) || ![last.requested_watts, last.observed_watts].every((field) => field === null || watts$1(field))))
        return null;
    return value;
}
function tdpControls(status) {
    const usable = status !== null && status.current_watts !== null && !status.recovery_required;
    return {
        canToggle: status?.enabled === true || (usable && status.can_enable),
        canApply: usable && status.enabled && status.ready,
        canRestore: usable && status.restore_available,
    };
}
function tdpMessage(status) {
    if (!status)
        return "Power settings are unavailable. Refresh to try again.";
    if (status.recovery_required)
        return "Power settings need recovery before further changes.";
    return reasons[status.code] ?? "Power settings need verification.";
}
function tdpResultMessage(status) {
    return status?.last_result ? reasons[status.last_result.code] ?? "Power settings need verification." : null;
}
class TdpRequestGate {
    active = false;
    async run(action) {
        if (this.active)
            return undefined;
        this.active = true;
        try {
            return await action();
        }
        finally {
            this.active = false;
        }
    }
}

const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const watts = (value) => typeof value === "number" && Number.isInteger(value) && value > 0 && value <= 0xFFFFFFFF;
const fps = (value) => typeof value === "number" && Number.isFinite(value) && value > 2 && value <= 1000;
const code$1 = (value) => typeof value === "string" && /^(auto_tdp|tdp|telemetry)\.[a-z0-9_]{1,80}$/.test(value);
function sanitizeAutoTdpStatus(value) {
    if (!object(value) || value.schema_version !== 1 || !code$1(value.code))
        return null;
    for (const name of ["can_start", "enabled", "running", "stopping"])
        if (typeof value[name] !== "boolean")
            return null;
    if (value.activity_code !== null && !code$1(value.activity_code))
        return null;
    if ((value.enabled && (!value.running || value.stopping)) || (value.stopping && !value.running)
        || (value.can_start && (value.running || value.code !== "auto_tdp.ready")))
        return null;
    const empty = [value.target_fps, value.minimum_watts, value.maximum_watts].every((item) => item === null);
    if (!empty && (!fps(value.target_fps) || !watts(value.minimum_watts) || !watts(value.maximum_watts)
        || value.minimum_watts > value.maximum_watts))
        return null;
    if (value.enabled && empty)
        return null;
    return value;
}
function validAutoTdpRange(manual, minimum, maximum, target) {
    return !!(manual?.ready && !manual.recovery_required && fps(target) && watts(minimum) && watts(maximum)
        && manual.minimum_watts !== null && manual.maximum_watts !== null && manual.current_watts !== null
        && manual.minimum_watts <= minimum && minimum <= manual.current_watts
        && manual.current_watts <= maximum && maximum <= manual.maximum_watts);
}
function autoTdpMessage(status, manualMessage) {
    if (!status)
        return "Auto TDP status is unavailable. Refresh or stop Auto TDP.";
    if (status.stopping)
        return "Stopping Auto TDP…";
    if (status.enabled && ["auto_tdp.configuration_missing", "auto_tdp.configuration_invalid", "auto_tdp.configuration_context_changed"].includes(status.code)) {
        return "Auto TDP is still on. Stop and revalidate the device configuration before starting again.";
    }
    if (status.enabled && status.code === "auto_tdp.game_or_render_unverified")
        return "Auto TDP is waiting for a running game in Portable mode.";
    if (status.code.startsWith("tdp."))
        return manualMessage;
    const reasons = {
        "auto_tdp.configuration_missing": "Auto TDP needs a device configuration before it can start.",
        "auto_tdp.configuration_invalid": "The Auto TDP device configuration needs correction.",
        "auto_tdp.configuration_context_changed": "The device or power provider changed. Revalidate its Auto TDP configuration.",
        "auto_tdp.game_or_render_unverified": "Run a game in Portable mode before starting Auto TDP.",
        "telemetry.collection_cost_unbenchmarked": "Auto TDP needs a collection benchmark on this device.",
        "telemetry.auto_tdp_cost_exceeds_budget": "Collection exceeds the gameplay budget. Auto TDP cannot start.",
        "telemetry.collection_cost_exceeds_budget": "Collection exceeds the gameplay budget. Auto TDP cannot start.",
        "auto_tdp.request_invalid": "Choose a valid FPS target and power range.",
        "auto_tdp.start_unavailable": "Auto TDP could not start. Refresh and check the power range.",
        "auto_tdp.stopped": "Auto TDP is stopped. The current power limit is retained.",
        "auto_tdp.closing": "Power control is closing.",
        "auto_tdp.runtime_unavailable": "Auto TDP needs a fresh check. Refresh to try again.",
    };
    if (status.code === "auto_tdp.ready")
        return status.enabled ? "Auto TDP is running." : "Ready to start Auto TDP.";
    return Object.hasOwn(reasons, status.code) ? reasons[status.code] : "Auto TDP needs a fresh readiness check.";
}
function autoTdpActivity(status) {
    if (status && ["auto_tdp.worker_unavailable", "auto_tdp.session_unavailable"].includes(status.activity_code ?? ""))
        return "Auto TDP stopped because the session became unavailable. Refresh before restarting.";
    if (!status?.enabled)
        return null;
    switch (status.activity_code) {
        case "auto_tdp.no_performance_gain": return "Holding power: recent increases did not improve the sampled frame rate. A changed workload or fresh start will reassess.";
        case "telemetry.auto_tdp_game_not_running": return "Paused until a running game is verified. Fresh samples are required before power changes resume.";
        case "auto_tdp.render_unverified": return "Paused while the game's render GPU is unverified.";
        case "auto_tdp.ownership_unverified": return "Paused while power-controller ownership is unverified.";
        case "auto_tdp.thermal_unverified": return "Paused until temperature evidence is ready.";
        case "auto_tdp.power_source_unverified": return "Paused until the power source is verified.";
        case "auto_tdp.sample_unavailable": return "Waiting for fresh game performance and sensor evidence.";
        case "auto_tdp.context_settling":
        case "auto_tdp.settling": return "Collecting performance at the current power limit.";
        case "tdp.readback_verified": return "The latest power adjustment was verified.";
        default: return "Status updates when you refresh.";
    }
}
class AutoTdpRequestGate {
    generation = 0;
    active = false;
    get busy() { return this.active; }
    begin(priority = false) {
        if (this.active && !priority)
            return null;
        this.active = true;
        return ++this.generation;
    }
    current(generation) { return generation === this.generation; }
    finish(generation) { if (this.current(generation))
        this.active = false; }
    invalidate() { this.generation++; this.active = false; }
}

const code = (value) => typeof value === "string" && /^(auto_tdp|tdp)\.[a-z_]{1,80}$/.test(value);
const integer = (value, maximum) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= maximum;
function sanitizeTdpBenchmark(value) {
    if (!value || typeof value !== "object")
        return null;
    const v = value;
    if (v.schema_version !== 1 || typeof v.running !== "boolean" || typeof v.cancelling !== "boolean" || (v.cancelling && !v.running) || !code(v.code))
        return null;
    if (v.result !== null) {
        if (!v.result || typeof v.result !== "object")
            return null;
        const r = v.result;
        if (!code(r.code) || !integer(r.attempts, 30) || !integer(r.usable_samples, r.attempts) || !integer(r.consecutive_samples, r.usable_samples)
            || !integer(r.elapsed_ms, Number.MAX_SAFE_INTEGER) || !integer(r.interval_ms, 2000) || r.interval_ms < 1000
            || (r.maximum_collection_and_revalidation_ms !== null && !integer(r.maximum_collection_and_revalidation_ms, Number.MAX_SAFE_INTEGER)))
            return null;
    }
    return v;
}
function tdpBenchmarkMessage(status) {
    if (!status)
        return "Benchmark status unavailable. Refresh to check again.";
    if (status.cancelling)
        return "Cancelling after the current read finishes…";
    if (status.running)
        return "Measuring frame and sensor collection…";
    return {
        "auto_tdp.benchmark_idle": "No benchmark has run in this session.",
        "auto_tdp.benchmark_within_budget": "This run met the collection time budget. Auto TDP has not been enabled.",
        "auto_tdp.benchmark_budget_exceeded": "Collection exceeded the time budget for Auto TDP.",
        "auto_tdp.benchmark_cancelled": "Benchmark cancelled.",
        "auto_tdp.benchmark_stop_auto_first": "Stop Auto TDP before running a benchmark.",
        "auto_tdp.benchmark_context_changed": "The game, power source or device context changed. Run again when stable.",
        "auto_tdp.benchmark_samples_insufficient": "Not enough usable frame samples. Check the running game and try again.",
        "auto_tdp.benchmark_context_unavailable": "Game, sensor or device evidence is unavailable. Check readiness and try again.",
        "auto_tdp.benchmark_time_limit": "The benchmark reached its time limit.",
        "auto_tdp.configuration_missing": "Device configuration is required before measurement.",
        "auto_tdp.configuration_invalid": "Device configuration needs correction before measurement.",
        "auto_tdp.game_or_render_unverified": "A verified game running on the internal GPU is required.",
        "tdp.disabled": "Enable manual power control before measurement.",
        "tdp.busy": "Power control is busy. Refresh and try again after it finishes.",
        "tdp.closing": "Power control is shutting down.",
    }[status.code] ?? "Benchmark unavailable. Check power control readiness and refresh.";
}

function TdpBenchmarkControls({ ready, autoRunning }) {
    const [status, setStatus] = SP_REACT.useState(null);
    const [busy, setBusy] = SP_REACT.useState(false);
    const [runPending, setRunPending] = SP_REACT.useState(false);
    const [cancelling, setCancelling] = SP_REACT.useState(false);
    const mounted = SP_REACT.useRef(true);
    const gate = SP_REACT.useRef(new AutoTdpRequestGate());
    const request = async (kind) => {
        const token = gate.current.begin(kind === "cancel");
        if (token === null)
            return;
        setBusy(true);
        setCancelling(kind === "cancel");
        if (kind === "run")
            setRunPending(true);
        try {
            const result = await (kind === "run" ? runTdpBenchmark() : kind === "cancel" ? cancelTdpBenchmark() : getTdpBenchmarkStatus());
            if (mounted.current && gate.current.current(token))
                setStatus(sanitizeTdpBenchmark(result));
        }
        catch {
            if (mounted.current && gate.current.current(token))
                setStatus(null);
        }
        finally {
            if (mounted.current) {
                if (kind === "run")
                    setRunPending(false);
                if (gate.current.current(token)) {
                    setBusy(false);
                    setCancelling(false);
                }
            }
            gate.current.finish(token);
        }
    };
    SP_REACT.useEffect(() => {
        mounted.current = true;
        void request("read");
        return () => { mounted.current = false; gate.current.invalidate(); };
    }, []);
    const result = status?.result;
    return SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("strong", { children: "Collection benchmark" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: cancelling ? "Requesting cancellation…" : runPending && busy ? "Measuring frame and sensor collection…" : tdpBenchmarkMessage(status) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || runPending || !ready || autoRunning || status?.running === true, onClick: () => void request("run"), children: "Run benchmark" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: cancelling, onClick: () => void request("cancel"), children: "Cancel benchmark" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => void request("read"), children: "Refresh benchmark" }) }), result && SP_JSX.jsxs(DFL.PanelSectionRow, { children: ["Last benchmark: ", result.usable_samples, " usable samples from ", result.attempts, " attempts.", SP_JSX.jsx("br", {}), "Longest collection and recheck: ", result.maximum_collection_and_revalidation_ms === null ? "unavailable" : `${result.maximum_collection_and_revalidation_ms} ms`, ".", SP_JSX.jsx("br", {}), "Sample interval: ", result.interval_ms, " ms. Elapsed: ", (result.elapsed_ms / 1000).toFixed(1), " seconds."] }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("span", { style: { fontSize: "12px", opacity: 0.75 }, children: "Measures collection time while a game runs. Power settings stay unchanged. Closing this panel lets the benchmark finish; use Cancel to stop it. Results require review before Auto TDP can use them." }) })] });
}

const preferenceModes = [
    { data: "portable", label: "Portable" },
    { data: "boosted_handheld", label: "Boosted Handheld" },
    { data: "docked_igpu", label: "Docked-iGPU" },
    { data: "docked_egpu", label: "Docked-eGPU" },
];
function sanitizeAutoTdpPreferences(value) {
    if (!value || typeof value !== "object")
        return null;
    const v = value;
    if (v.schema_version !== 1 || !["loaded", "missing", "saved", "invalid", "save_failed"].some(code => v.code === `auto_tdp_preferences.${code}`) || !Array.isArray(v.preferences) || v.preferences.length > 4)
        return null;
    const seen = new Set();
    for (const row of v.preferences) {
        if (!row || !preferenceModes.some(mode => mode.data === row.placement) || seen.has(row.placement)
            || typeof row.target_fps !== "number" || !Number.isFinite(row.target_fps) || row.target_fps <= 2 || row.target_fps > 1000
            || !Number.isSafeInteger(row.minimum_watts) || !Number.isSafeInteger(row.maximum_watts)
            || row.minimum_watts <= 0 || row.maximum_watts > 0xffffffff || row.minimum_watts > row.maximum_watts)
            return null;
        seen.add(row.placement);
    }
    return v;
}

function AutoTdpPreferencesControls({ target, minimum, maximum, canSave, onLoad }) {
    const [mode, setMode] = SP_REACT.useState("portable");
    const [status, setStatus] = SP_REACT.useState(null);
    const [busy, setBusy] = SP_REACT.useState(false);
    const mounted = SP_REACT.useRef(true);
    const pending = SP_REACT.useRef(false);
    const request = async (save = false) => {
        if (pending.current)
            return;
        pending.current = true;
        setBusy(true);
        try {
            const result = await (save && minimum !== null && maximum !== null ? saveAutoTdpPreference(mode, target, minimum, maximum) : getAutoTdpPreferences());
            if (mounted.current)
                setStatus(sanitizeAutoTdpPreferences(result));
        }
        catch {
            if (mounted.current)
                setStatus(null);
        }
        finally {
            pending.current = false;
            if (mounted.current)
                setBusy(false);
        }
    };
    SP_REACT.useEffect(() => { mounted.current = true; void request(); return () => { mounted.current = false; }; }, []);
    const saved = status?.preferences.find(row => row.placement === mode);
    return SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.DropdownItem, { label: "Save preferences for", rgOptions: preferenceModes, selectedOption: mode, disabled: busy, onChange: option => { if (preferenceModes.some(row => row.data === option.data))
                    setMode(option.data); } }), SP_JSX.jsx(DFL.PanelSectionRow, { children: busy ? "Checking saved preferences…" : !status || ["auto_tdp_preferences.invalid", "auto_tdp_preferences.save_failed"].includes(status.code) ? "Preferences unavailable or save failed. Refresh to check stored values." : status.code === "auto_tdp_preferences.saved" ? "Preferences saved. Auto TDP settings and activation are unchanged." : "Saved preferences do not start Auto TDP." }), SP_JSX.jsx(DFL.PanelSectionRow, { children: saved ? `Saved: ${saved.target_fps} FPS, ${saved.minimum_watts}–${saved.maximum_watts} W.` : "No saved preferences for this mode." }), mode !== "portable" && SP_JSX.jsx(DFL.PanelSectionRow, { children: "This mode's power profile is not validated. Preferences can be saved for future use." }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || !canSave, onClick: () => void request(true), children: "Save current FPS and range" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || !saved || mode !== "portable" || !canSave, onClick: () => { if (saved && mode === "portable")
                        onLoad(saved); }, children: "Load Portable preferences into controls" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => void request(), children: "Refresh saved preferences" }) })] });
}

function AutoTdpControls({ manual, manualBusy, manualMessage, onChanged }) {
    const [status, setStatus] = SP_REACT.useState(null);
    const [target, setTarget] = SP_REACT.useState(60);
    const [minimum, setMinimum] = SP_REACT.useState(null);
    const [maximum, setMaximum] = SP_REACT.useState(null);
    const [busy, setBusy] = SP_REACT.useState(false);
    const [stopping, setStopping] = SP_REACT.useState(false);
    const [benchmarkVisible, setBenchmarkVisible] = SP_REACT.useState(false);
    const [preferencesVisible, setPreferencesVisible] = SP_REACT.useState(false);
    const mounted = SP_REACT.useRef(true);
    const gate = SP_REACT.useRef(new AutoTdpRequestGate());
    const pendingRefresh = SP_REACT.useRef(false);
    const request = async (action, kind = "read") => {
        const generation = gate.current.begin(kind === "stop");
        if (generation === null)
            return;
        setBusy(true);
        setStopping(kind === "stop");
        try {
            const next = sanitizeAutoTdpStatus(await action());
            if (mounted.current && gate.current.current(generation)) {
                setStatus(next);
                if (next?.target_fps != null) {
                    setTarget(next.target_fps);
                    setMinimum(next.minimum_watts);
                    setMaximum(next.maximum_watts);
                }
                if (kind !== "read")
                    onChanged();
            }
        }
        catch {
            if (mounted.current && gate.current.current(generation))
                setStatus(null);
        }
        finally {
            if (mounted.current && gate.current.current(generation)) {
                setBusy(false);
                setStopping(false);
            }
            gate.current.finish(generation);
            if (mounted.current && gate.current.current(generation) && pendingRefresh.current) {
                pendingRefresh.current = false;
                void request(getAutoTdpStatus);
            }
        }
    };
    SP_REACT.useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; gate.current.invalidate(); };
    }, []);
    SP_REACT.useEffect(() => {
        if (manual?.minimum_watts != null && manual.maximum_watts != null) {
            setMinimum((value) => value === null || value < manual.minimum_watts || value > manual.maximum_watts ? manual.minimum_watts : value);
            setMaximum((value) => value === null || value < manual.minimum_watts || value > manual.maximum_watts ? manual.maximum_watts : value);
        }
        if (gate.current.busy)
            pendingRefresh.current = true;
        else
            void request(getAutoTdpStatus);
        // On-demand only: manual state changes and explicit Refresh, never a timer.
    }, [manual]);
    const watts = manual?.minimum_watts != null && manual.maximum_watts != null
        ? Array.from({ length: manual.maximum_watts - manual.minimum_watts + 1 }, (_, index) => ({ data: manual.minimum_watts + index, label: `${manual.minimum_watts + index} W` })) : [];
    const targets = [...new Set([30, 40, 45, 60, 90, 120, target])].sort((a, b) => a - b).map((value) => ({ data: value, label: `${value} FPS` }));
    const valid = validAutoTdpRange(manual, minimum, maximum, target);
    const locked = busy || manualBusy || status?.running === true;
    return SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("strong", { children: "Auto TDP" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: busy ? (stopping ? "Stopping Auto TDP…" : "Checking Auto TDP…") : autoTdpMessage(status, manualMessage) }), !busy && autoTdpActivity(status) && SP_JSX.jsx(DFL.PanelSectionRow, { children: autoTdpActivity(status) }), SP_JSX.jsx(DFL.DropdownItem, { label: "Target frame rate", rgOptions: targets, selectedOption: target, disabled: locked, onChange: (option) => { if (targets.some((entry) => entry.data === option.data))
                    setTarget(option.data); } }), SP_JSX.jsx(DFL.DropdownItem, { label: "Minimum power", rgOptions: watts, selectedOption: minimum ?? undefined, disabled: locked, onChange: (option) => { if (watts.some((entry) => entry.data === option.data))
                    setMinimum(option.data); } }), SP_JSX.jsx(DFL.DropdownItem, { label: "Maximum power", rgOptions: watts, selectedOption: maximum ?? undefined, disabled: locked, onChange: (option) => { if (watts.some((entry) => entry.data === option.data))
                    setMaximum(option.data); } }), !valid && manual?.ready && SP_JSX.jsxs(DFL.PanelSectionRow, { children: ["Choose a range that includes the last checked limit of ", manual.current_watts, " W."] }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: locked || !status?.can_start || !valid, onClick: () => { if (!locked && status?.can_start && valid && minimum !== null && maximum !== null)
                        void request(() => startAutoTdp(target, minimum, maximum), "start"); }, children: "Start Auto TDP" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: stopping, onClick: () => void request(stopAutoTdp, "stop"), children: "Stop Auto TDP" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => void request(getAutoTdpStatus), children: "Refresh Auto TDP" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("span", { style: { fontSize: "12px", opacity: 0.75 }, children: "Stop keeps the current limit. Restore returns to saved settings. Manual Apply or Restore stops Auto TDP. Closing this panel keeps Auto TDP running." }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Show saved mode preferences", checked: preferencesVisible, onChange: setPreferencesVisible }) }), preferencesVisible && SP_JSX.jsx(AutoTdpPreferencesControls, { target: target, minimum: minimum, maximum: maximum, canSave: !locked && valid, onLoad: row => { if (!locked) {
                    setTarget(row.target_fps);
                    setMinimum(row.minimum_watts);
                    setMaximum(row.maximum_watts);
                } } }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Show collection benchmark", checked: benchmarkVisible, onChange: setBenchmarkVisible }) }), benchmarkVisible && SP_JSX.jsx(TdpBenchmarkControls, { ready: manual?.ready === true && !manualBusy && !busy, autoRunning: status?.running === true })] });
}

function TdpControls({ visible }) {
    const [expanded, setExpanded] = SP_REACT.useState(false);
    const [autoExpanded, setAutoExpanded] = SP_REACT.useState(false);
    const [status, setStatus] = SP_REACT.useState(null);
    const [selected, setSelected] = SP_REACT.useState(null);
    const [busy, setBusy] = SP_REACT.useState(false);
    const gate = SP_REACT.useRef(new TdpRequestGate());
    const showing = SP_REACT.useRef(false);
    showing.current = visible && expanded;
    const mounted = SP_REACT.useRef(true);
    const request = (action) => gate.current.run(async () => {
        if (!showing.current)
            return;
        setBusy(true);
        try {
            const next = sanitizeTdpStatus(await action());
            if (mounted.current && showing.current) {
                setStatus(next);
                setSelected(next?.current_watts ?? null);
            }
        }
        catch {
            if (mounted.current) {
                setStatus(null);
                setSelected(null);
            }
        }
        finally {
            if (mounted.current)
                setBusy(false);
        }
    });
    SP_REACT.useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);
    SP_REACT.useEffect(() => {
        if (!visible) {
            setExpanded(false);
            setAutoExpanded(false);
            setStatus(null);
            setSelected(null);
        }
    }, [visible]);
    SP_REACT.useEffect(() => {
        if (visible && expanded)
            void request(getTdpStatus);
        // Visibility/expansion owns the only automatic refresh. No polling timer.
    }, [visible, expanded]);
    const controls = tdpControls(status);
    const options = status?.minimum_watts != null && status.maximum_watts != null
        ? Array.from({ length: status.maximum_watts - status.minimum_watts + 1 }, (_, index) => ({ data: status.minimum_watts + index, label: `${status.minimum_watts + index} W` }))
        : [];
    return SP_JSX.jsxs(DFL.PanelSection, { title: "Handheld power", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => { setStatus(null); setSelected(null); setAutoExpanded(false); setExpanded((value) => !value); }, children: expanded ? "Hide power controls" : "Show power controls" }) }), visible && expanded && SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: busy ? "Checking power settings…" : tdpMessage(status) }), !busy && tdpResultMessage(status) && SP_JSX.jsxs(DFL.PanelSectionRow, { children: ["Last request: ", tdpResultMessage(status)] }), SP_JSX.jsx(DFL.PanelSectionRow, { children: status?.current_watts != null ? `Last checked limit: ${status.current_watts} W` : "Last checked limit: unavailable" }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("span", { style: { fontSize: "12px", opacity: 0.75 }, children: "This is the configured limit, not measured power use. Enable only after resolving other power controllers." }) }), SP_JSX.jsx(DFL.ToggleField, { label: "Use Re-Gear power control", checked: status?.enabled ?? false, disabled: busy || !controls.canToggle, onChange: (enabled) => { if (controls.canToggle)
                            void request(() => setTdpEnabled(enabled)); } }), SP_JSX.jsx(DFL.DropdownItem, { label: "Power limit", rgOptions: options, selectedOption: selected ?? undefined, disabled: busy || !controls.canApply, onChange: (option) => { if (options.some((entry) => entry.data === option.data))
                            setSelected(option.data); } }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || !controls.canApply || selected === null, onClick: () => { if (controls.canApply && selected !== null)
                                void request(() => applyTdpLimit(selected)); }, children: "Apply power limit" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy || !controls.canRestore, onClick: () => { if (controls.canRestore)
                                void request(restoreTdpLimit); }, children: "Restore previous power settings" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", disabled: busy, onClick: () => void request(getTdpStatus), children: "Refresh power settings" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => setAutoExpanded((value) => !value), children: autoExpanded ? "Hide Auto TDP" : "Show Auto TDP" }) }), autoExpanded && SP_JSX.jsx(AutoTdpControls, { manual: status, manualBusy: busy, manualMessage: tdpMessage(status), onChanged: () => { void request(getTdpStatus); } })] })] });
}

const HEALTH_BLOCKER_MESSAGES = {
    "health.placement_degraded": "Current mode needs attention.",
    "health.placement_unknown": "Current mode needs verification.",
    "health.workflow_unknown": "Re-Gear recovery status needs review.",
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
    "health.no_observations": "Re-Gear health evidence is unavailable.",
    "health.duplicate_component": "Re-Gear health evidence is inconsistent.",
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
    const messages = health.blockers.map((blocker) => HEALTH_BLOCKER_MESSAGES[blocker] ?? "Re-Gear health evidence needs review.");
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
                    body: "Re-Gear is preserving the current setup. Verify the display and controls before changing it.",
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
            body: "Re-Gear is preserving the current setup. Avoid disconnecting until the link is stable.",
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
 * Accept only known public journey states. Raw codes, unknown reasons, and all
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
            reason_codes: sanitizeOfflineReasonCodes(offline.reason_codes),
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
        instability_observed: ["State change observed", "Review the current link observation; Re-Gear does not diagnose cable quality."],
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
            ? { name, value: presentation[0], detail: key === "offline_readiness"
                    ? offlineReadinessDetail(journey?.offline_readiness?.reason_codes) ?? presentation[1]
                    : presentation[1] }
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

/** Command Center routing and module registry: pure, no React, no I/O.
 *
 * The approved layout (docs/design/command-center/LAYOUT_APPROVAL.md, baseline
 * df6a36c) replaces the flat panel with a small navigation stack:
 *
 *     Command Center -> Modules -> module
 *     Command Center -> status detail
 *
 * The horizontal five-icon chooser is superseded. Measured evidence puts the
 * information column at 268px, where five 44px targets do not fit and do not
 * scale as modules are added; a labelled list costs one step and does not.
 *
 * Availability is derived from the existing `quickAccessSections` taxonomy
 * rather than recomputed, so a module and its section can never disagree about
 * whether a feature is usable. Unavailable destinations stay listed and stay
 * reachable: selecting one is how a player reads why it cannot be used. That
 * rule is load-bearing -- it is the defect this stack already shipped once.
 *
 * Nothing here asserts backend capability. A route is a place to render, never
 * a claim that an operation is supported.
 */
/** Stable identity for a route, used as the focus-restoration key. */
function routeKey(route) {
    return route.kind === "module" || route.kind === "status" ? `${route.kind}:${route.id}` : route.kind;
}
/** Taxonomy section that owns each module's availability evidence. */
const SECTION_OF = {
    egpu: "egpu", "auto-tdp": "tdp", controller: "controller",
};
const TITLE = {
    egpu: "eGPU", "auto-tdp": "Auto TDP", controller: "Controller",
};
/** Panel order. Stable through refresh: a row must not move under a thumb. */
const MODULE_ORDER = ["egpu", "auto-tdp", "controller"];
/** Build the Modules list from the existing taxonomy.
 *
 * A module whose section is missing reads unavailable rather than being
 * dropped, because a destination that vanishes reads as a bug and unknown
 * state is never a capability claim.
 */
function quickAccessModules(sections) {
    return MODULE_ORDER.map((id) => {
        const section = sections.find((candidate) => candidate.id === SECTION_OF[id]);
        if (!section) {
            return { id, title: TITLE[id], summary: "", available: false,
                reason: "Status not yet observed." };
        }
        return {
            id, title: TITLE[id], summary: section.summary,
            available: section.available, reason: section.available ? null : section.reason,
        };
    });
}
const INITIAL_STACK = [{ kind: "command-center" }];
function currentRoute(stack) {
    return stack[stack.length - 1];
}
/** Open a destination one level deeper.
 *
 * Re-opening the destination already on top is a no-op rather than a second
 * copy, so a repeated press cannot build a stack that needs two Backs to
 * leave. Depth is capped at Command Center plus two levels, matching the
 * approved shape; anything deeper would be a route this design does not have.
 */
function pushRoute(stack, route) {
    if (routeKey(currentRoute(stack)) === routeKey(route))
        return stack;
    const next = stack.length >= 3 ? [stack[0], route] : [...stack, route];
    return next;
}
function backRoute(stack) {
    if (stack.length <= 1)
        return { stack, delegate: true };
    return { stack: stack.slice(0, -1), delegate: false };
}
// ------------------------------------------------- what the route implies
/** True when Back has an internal level to pop.
 *
 * The caller uses this to decide whether to attach a cancel handler at all.
 * Deciding inside a React state updater does not work: an updater may be
 * deferred or replayed, so a value assigned from inside one and read straight
 * afterwards is not a reliable answer, and a handler that is attached but
 * declines to act has already swallowed the press.
 */
function hasInternalLevel(stack) {
    return stack.length > 1;
}
/** Whether the diagnostics surfaces are actually on screen.
 *
 * `showDiagnostics` says the player opened them; it does not say they are
 * visible. On any pushed route the Command Center body is not rendered, so
 * collecting for surfaces nobody can see is work the player did not ask for.
 */
function diagnosticsVisible(stack, showDiagnostics) {
    return showDiagnostics && currentRoute(stack).kind === "command-center";
}
/** A fresh Quick Access entry starts at Command Center.
 *
 * Steam may keep the plugin mounted between openings, so the stack survives a
 * close unless it is reset. Reopening into a pushed route would make the panel
 * resume somewhere the player did not choose this time.
 */
function stackOnPanelOpen() {
    return INITIAL_STACK;
}
/** The Troubleshooting control's open/close rule.
 *
 * This is the surviving owner of the open-edge behaviour that the deleted
 * quick-access-section-state helper used to hold: opening asks for fresh
 * evidence, closing does not, and re-opening an already-open surface must not
 * request again.
 */
function troubleshootingToggle(open) {
    return { next: !open, refresh: !open };
}

/** Command Center navigation shell: rendering only, no policy, no requests.
 *
 * Which destinations exist, whether they are usable and what a blocked one says
 * all come from `module-registry`, so this file cannot disagree with the
 * taxonomy. It renders one route at a time and owns no state.
 *
 * A destination is never hidden because it is unavailable. It renders its
 * reason instead, which is the answer a player actually needs, and it stays
 * focusable so a controller can reach it.
 *
 * Nothing here implies a backend operation is supported. Content for each
 * module arrives in its own slice; this shell only establishes the routes.
 */
const C$1 = {
    cyan: "#39d8ff", text: "#f4f7fb", muted: "#9eb2ca",
    border: "#294665", amber: "#ffc247", dim: "#5d7a99",
};
const SURFACE$1 = "linear-gradient(135deg, rgba(19,36,58,.96), rgba(9,21,36,.98))";
function Chevron() {
    return SP_JSX.jsx("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", style: { flexShrink: 0 }, children: SP_JSX.jsx("path", { d: "M9 6l6 6-6 6" }) });
}
/** One tappable row: icon slot, title, one-line summary or reason, chevron. */
function NavRow({ title, detail, blocked, onClick, focusKey }) {
    return SP_JSX.jsxs(DFL.DialogButton, { "data-regear-focus": focusKey, onClick: onClick, 
        // Blocked rows stay focusable: opening one is how its reason is read.
        style: {
            width: "100%", minHeight: 44, margin: "0 0 6px", padding: "8px 10px",
            display: "flex", alignItems: "center", gap: 8, textAlign: "left",
            background: SURFACE$1, border: `1px solid ${C$1.border}`, borderRadius: 12,
            color: blocked ? C$1.dim : C$1.text,
        }, children: [SP_JSX.jsxs("span", { style: { flex: "1 1 auto", minWidth: 0 }, children: [SP_JSX.jsx("span", { style: { display: "block", fontSize: 14, fontWeight: 700 }, children: title }), SP_JSX.jsx("span", { style: { display: "block", fontSize: 12, lineHeight: "16px",
                            color: blocked ? C$1.amber : C$1.muted, whiteSpace: "normal" }, children: detail })] }), SP_JSX.jsx(Chevron, {})] });
}
function ModulesList({ modules, onOpen }) {
    return SP_JSX.jsx(DFL.Focusable, { style: { color: C$1.text }, "flow-children": "vertical", children: modules.map((entry) => (SP_JSX.jsx(NavRow, { focusKey: `module:${entry.id}`, title: entry.title, 
            // A blocked module shows why, not a summary of controls it cannot reach.
            detail: entry.available ? entry.summary : entry.reason ?? "", blocked: !entry.available, onClick: () => onOpen(entry.id) }, entry.id))) });
}
/** Heading for a pushed level, with the reason when the destination is blocked. */
function RouteHeader({ title, reason }) {
    return SP_JSX.jsxs("div", { style: { margin: "0 2px 10px", color: C$1.text }, children: [SP_JSX.jsx("div", { style: { fontSize: 15, fontWeight: 760, marginBottom: 2 }, children: title }), reason && SP_JSX.jsx("div", { style: { fontSize: 12, lineHeight: "16px", color: C$1.amber }, children: reason })] });
}
/** The Modules entry on Command Center. Labelled, not an icon-only target. */
function ModulesButton({ onOpen }) {
    return SP_JSX.jsx(DFL.DialogButton, { "data-regear-focus": "modules", onClick: onOpen, style: {
            width: "auto", minHeight: 36, margin: 0, padding: "4px 12px",
            alignSelf: "flex-end", borderRadius: 10, fontSize: 13, fontWeight: 700,
            background: SURFACE$1, border: `1px solid ${C$1.border}`, color: C$1.cyan,
        }, children: "Modules" });
}
/** Read-only status entries, deliberately not routed to configuration. */
function StatusLinks({ entries, onOpen }) {
    return SP_JSX.jsx(DFL.Focusable, { style: { color: C$1.text }, "flow-children": "vertical", children: entries.map((entry) => (SP_JSX.jsx(NavRow, { focusKey: `status:${entry.id}`, title: entry.title, detail: entry.detail, blocked: false, onClick: () => onOpen(entry.id) }, entry.id))) });
}
/** Placeholder body for a route whose content has not been migrated yet.
 *
 * Stated plainly rather than left blank: an empty pane reads as a broken
 * screen, and this shell must not imply a control exists where none does. */
function PendingContent({ what }) {
    return SP_JSX.jsxs("div", { style: { margin: "0 2px", fontSize: 12, lineHeight: "16px", color: C$1.muted }, children: [what, " has not moved here yet. It is still reachable on the main panel."] });
}
function ShellBody({ route, modules, children, onOpenModule, onOpenStatus, statusEntries }) {
    if (route.kind === "modules") {
        return SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(RouteHeader, { title: "Modules", reason: null }), SP_JSX.jsx(ModulesList, { modules: modules, onOpen: onOpenModule })] });
    }
    if (route.kind === "module") {
        const entry = modules.find((candidate) => candidate.id === route.id);
        return SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(RouteHeader, { title: entry?.title ?? "Module", reason: entry?.reason ?? null }), SP_JSX.jsx(PendingContent, { what: entry?.title ?? "This module" })] });
    }
    if (route.kind === "status") {
        const entry = statusEntries.find((candidate) => candidate.id === route.id);
        return SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(RouteHeader, { title: entry?.title ?? "Status", reason: null }), SP_JSX.jsx(PendingContent, { what: entry?.title ?? "This status" })] });
    }
    return SP_JSX.jsxs(SP_JSX.Fragment, { children: [children, SP_JSX.jsx(StatusLinks, { entries: statusEntries, onOpen: onOpenStatus })] });
}

/** Turn the backend's disconnect status into what a player is shown.
 *
 * The backend reports facts. This decides what they mean on screen, and it
 * exists so the things a caller must not infer are enforced in one place
 * instead of described in a document nobody rereads.
 *
 * Five of those, because each one has already gone wrong somewhere:
 *
 * 1. **An empty holder list is not a clear device.** `holders` and
 *    `scanComplete` travel separately; an empty list from a scan that could
 *    not finish means the check did not complete, not that nothing is using
 *    the eGPU.
 * 2. **A blocker the disconnect exists to clear is not a blocker to report.**
 *    Removal safety is assessed before any release, and before one it always
 *    declines: the holders are still there and the eGPU is still driving a
 *    display. The backend reports those as `attemptable`, and offering the
 *    action only on `ready` would tell a player their eGPU can never be
 *    disconnected.
 * 3. **A half-detached device is not a failed action.** It is a system that
 *    needs attention, and it outranks every other state.
 * 4. **A running game is not a blocker either.** Closing it is exactly what
 *    the flow does. Reporting it as a dead end would refuse the action at the
 *    only moment a player wants it -- while they are playing on the eGPU.
 * 5. **Nothing here may imply that unplugging is safe.** Re-Gear detaches the
 *    eGPU in software; the cable stays connected. That distinction is the
 *    whole safety position and no string below softens it.
 *
 * The confirmation also states that the Steam session will restart, because
 * today it does -- that is what releases the device -- and a player must be
 * told before rather than surprised after.
 *
 * What it does *not* decide is whether a game may be closed unasked. That is
 * the backend's `close_prompt`, which is read here and never re-derived: a
 * second opinion about someone's unsaved progress is one too many.
 */
/** What each blocking code means to a player.
 *
 * Codes absent here fall through to a reason that quotes the code, so an
 * unmapped state reads as something a bug report can act on rather than as a
 * confident sentence that happens to be wrong.
 */
const BLOCKED_REASON = {
    "removal_safety.clients_active_or_protected": "Something is still using the eGPU.",
    "removal_safety.client_scan_incomplete": "Re-Gear could not check every process, so it cannot confirm the eGPU is free.",
    // Reached only when a status names a running game but carries no prompt to
    // act on it; the ordinary path offers the close instead of reporting this.
    "removal_safety.game_running": "Close the running game first.",
    "removal_safety.evidence_insufficient": "Re-Gear does not have enough information about the eGPU yet.",
    "live_disconnect.egpu_unavailable": "No eGPU is connected.",
    "live_disconnect.session_unavailable": "Re-Gear cannot reach the Steam session.",
    "live_disconnect.status_unavailable": "Re-Gear could not read the eGPU state.",
};
const ATTENTION_REASON = {
    "removal_transaction.partially_detached": "A previous disconnect stopped partway and the eGPU is half detached. Restore it before trying again.",
    "live_disconnect.record_unreadable": "Re-Gear cannot read its record of the last disconnect, which may describe a half-detached eGPU.",
    "removal_transaction.complete": "A previous disconnect finished and its record is still present.",
};
/** The one sentence that must never drift.
 *
 * Software removal is not unplug clearance. Every confirmation says so, and
 * says it after the disruptive part rather than buried ahead of it.
 */
const KEEP_CABLE = "Keep the cable connected: this does not make unplugging safe.";
const SESSION_WARNING = "Your Steam session will restart.";
/** What closing this game will cost, in words a player can act on.
 *
 * Driven by the reviewed catalog. The default is the honest one: for a game
 * nobody has reported on, Re-Gear does not know whether it saves, and says so
 * rather than implying it is fine.
 */
function gameCloseAdvice(game) {
    switch (game.save_capability) {
        case "verified_triggerable_autosave":
        case "verified_save_on_exit":
        case "graceful_exit_verified":
            return "Closing it saves your progress.";
        case "manual_save_recommended":
        case "manual_save_required":
            return "Save your progress first: this game does not save when it closes.";
        case "unsafe_unknown":
            return "Closing it may lose progress. Save your game first.";
        default:
            return "Re-Gear cannot confirm this game saves when it closes. Save it first.";
    }
}
function gameName(game) {
    return game?.title || "the running game";
}
/** The dialog shown before a disconnect closes whatever is running.
 *
 * Returns null when nothing has to be asked: either nothing is running, or
 * the player already gave a standing answer for this game.
 *
 * The body is ordered the way a player needs it -- what is about to happen,
 * what it costs them, then the two things they must not be surprised by. The
 * cable sentence is last in every branch, for the same reason it is last in
 * the tile confirmation: it is the sentence that must survive skim-reading.
 */
function gameCloseDialog(prompt, game) {
    if (prompt === null || prompt.decision !== "confirm") {
        return null;
    }
    const named = game !== null && game.identity_exact;
    if (prompt.code === "game_close.scan_incomplete") {
        // Not "nothing is running": Re-Gear could not look. Saying the first
        // would close a player's game without a word about it.
        return {
            title: "Disconnect the eGPU?",
            body: [
                "Re-Gear could not check whether a game is running, so it cannot tell you what disconnecting will close.",
                "Save anything you have open first.",
                SESSION_WARNING,
                KEEP_CABLE,
            ].join(" "),
            confirmLabel: "Disconnect anyway",
            cancelLabel: "Cancel",
            rememberLabel: null,
            relaunchLabel: null,
            relaunchChecked: false,
            canCloseGame: false,
            progressAtRisk: false,
        };
    }
    if (!named) {
        return {
            title: "Close your game first",
            body: [
                "A game is using the eGPU and has to close before it can be disconnected.",
                "Re-Gear could not identify which game, so it cannot close it for you, cannot tell you whether closing it saves your progress, and cannot reopen it afterwards.",
                "Save and close your game, then try again.",
                SESSION_WARNING,
                KEEP_CABLE,
            ].join(" "),
            // Not "Close and disconnect": without an app id there is nothing to
            // close, and offering a close that cannot happen is a promise broken
            // one second after it is made.
            confirmLabel: "Try disconnect anyway",
            cancelLabel: "Cancel",
            rememberLabel: null,
            relaunchLabel: null,
            relaunchChecked: false,
            canCloseGame: false,
            progressAtRisk: prompt.progress_at_risk,
        };
    }
    const name = gameName(game);
    return {
        title: `Close ${name}?`,
        body: [
            `${name} is using the eGPU and has to close before it can be disconnected.`,
            gameCloseAdvice(game),
            SESSION_WARNING,
            KEEP_CABLE,
        ].join(" "),
        confirmLabel: "Close and disconnect",
        cancelLabel: "Cancel",
        // Absent, not unticked, when the catalog says closing loses progress:
        // that prompt carries something to act on now, which a box ticked last
        // week cannot carry.
        rememberLabel: prompt.remember_offered
            ? `Don't ask again for ${name}`
            : null,
        relaunchLabel: prompt.relaunch_offered
            ? `Reopen ${name} afterwards`
            : null,
        relaunchChecked: prompt.relaunch_requested,
        canCloseGame: true,
        progressAtRisk: prompt.progress_at_risk,
    };
}
function disconnectPresentation(status) {
    if (status === null) {
        return {
            available: false,
            value: "Unknown",
            reason: "Re-Gear has not read the eGPU state yet.",
            actionLabel: null,
            confirmation: null,
            displayApprovalRequired: false,
            attention: false,
            game: null,
            dialog: null,
            closesGame: false,
        };
    }
    if (status.availability === "recovery_required") {
        return {
            available: false,
            value: "Needs attention",
            reason: ATTENTION_REASON[status.code] ??
                `A previous disconnect left the eGPU in an unexpected state (${status.code}).`,
            actionLabel: null,
            confirmation: null,
            displayApprovalRequired: false,
            attention: true,
            game: null,
            dialog: null,
            closesGame: false,
        };
    }
    if (status.availability === "busy") {
        return {
            available: false,
            value: "Working",
            reason: "A disconnect is already running.",
            actionLabel: null,
            confirmation: null,
            displayApprovalRequired: false,
            attention: false,
            game: null,
            dialog: null,
            closesGame: false,
        };
    }
    if (status.availability === "unavailable") {
        return {
            available: false,
            value: "Unavailable",
            reason: BLOCKED_REASON[status.code] ?? "No eGPU is connected.",
            actionLabel: null,
            confirmation: null,
            displayApprovalRequired: false,
            attention: false,
            game: null,
            dialog: null,
            closesGame: false,
        };
    }
    // A running game is the fifth thing that must not be reported as a blocker.
    // Closing it is exactly what the flow does, so declining here would tell a
    // player their eGPU can never be disconnected while they are playing --
    // which is the only time they would want to.
    const gameIsTheBlocker = status.code === "removal_safety.game_running";
    // A backend too old to send the field is not a backend reporting a running
    // game, so a missing prompt reads the same as no prompt rather than as an
    // undefined that leaks into every comparison below.
    const prompt = status.close_prompt ?? null;
    // Either signal is enough. A backend that names a running game in its
    // readiness code but reports no prompt is a backend mid-upgrade, and the
    // safe reading of the disagreement is that a game will close.
    const closesGame = gameIsTheBlocker ||
        (prompt !== null && prompt.decision !== "nothing_to_close");
    if (!status.attemptable && !gameIsTheBlocker) {
        return {
            available: false,
            value: "Not ready",
            reason: BLOCKED_REASON[status.code] ??
                `Re-Gear cannot confirm the eGPU is free (${status.code}).`,
            actionLabel: null,
            confirmation: null,
            displayApprovalRequired: false,
            attention: false,
            game: null,
            dialog: null,
            closesGame: false,
        };
    }
    const display = status.display_release_required;
    const ready = status.availability === "ready" && !closesGame;
    const dialog = gameCloseDialog(prompt, status.game ?? null);
    return {
        available: true,
        value: closesGame ? "Close game" : ready ? "Ready" : "Try disconnect",
        reason: null,
        actionLabel: "Disconnect",
        confirmation: [
            closesGame
                ? `Re-Gear will close ${gameName(status.game)}, then detach the eGPU in software.`
                : ready
                    ? "Re-Gear will detach the eGPU in software."
                    : "Re-Gear will try to free the eGPU and detach it in software.",
            display ? "The external display will turn off." : null,
            SESSION_WARNING,
            KEEP_CABLE,
        ]
            .filter((line) => line !== null)
            .join(" "),
        displayApprovalRequired: display,
        attention: false,
        game: status.game ?? null,
        dialog,
        closesGame,
    };
}

/** Shared performance state for the Command Center tiles and the Auto TDP
 * module: pure, no React, no I/O, no requests.
 *
 * Two consumers now read the same TDP status: the compact tiles on the first
 * screen and the module page behind Modules. Deriving what each shows from the
 * raw payload twice is how they end up disagreeing -- one offering Start while
 * the other says unavailable, from the same bytes. This module is the single
 * derivation, so a disagreement has nowhere to come from.
 *
 * What it deliberately does NOT do:
 *
 * - It never implies enablement and loop start are the same operation. The
 *   approved design is explicit: Stop when active, Start only with an already
 *   valid explicitly configured range and existing permission, otherwise Open
 *   Auto TDP. A single toggle would conflate a power-writer capability with
 *   running a control loop.
 * - It never fabricates a value. Absent watts render as unknown, never as a
 *   plausible default, and never as a number carried over from a stale read.
 * - It never starts anything from guessed defaults.
 *
 * FPS is not modelled here. The approved FPS tile is a proposed new capability,
 * not Auto TDP's target FPS, and no backend provides it; see fpsTile.
 */
function performanceState(input) {
    const { status } = input;
    const busy = input.busy === true;
    if (!status) {
        return {
            active: false, supported: false, configuredWatts: null, configuredIsLimit: false,
            action: "none", reason: "Performance status not yet observed.", busy,
        };
    }
    const supported = status.auto_tdp_available === true;
    const active = status.enabled === true;
    // Stop stays reachable whenever the loop is running, even if permission to
    // start again has since been withdrawn: a player must always be able to stop
    // something that is currently changing their device.
    if (active) {
        return {
            active: true, supported, configuredWatts: status.current_watts,
            configuredIsLimit: true, action: busy ? "none" : "stop",
            reason: busy ? "Working…" : null, busy,
        };
    }
    if (!supported) {
        return {
            active: false, supported: false, configuredWatts: null, configuredIsLimit: false,
            action: "none", reason: "This device has no verified TDP control.", busy,
        };
    }
    if (busy) {
        return { active: false, supported, configuredWatts: status.current_watts,
            configuredIsLimit: true, action: "none", reason: "Working…", busy };
    }
    if (status.recovery_required === true) {
        // Recovery outranks starting: begin a loop over an unrestored limit and the
        // player keeps whatever the interrupted session left behind.
        return { active: false, supported, configuredWatts: status.current_watts,
            configuredIsLimit: true, action: "open", reason: "Needs recovery in Auto TDP.", busy };
    }
    const startable = status.can_enable === true && input.configured === true;
    return {
        active: false, supported, configuredWatts: status.current_watts, configuredIsLimit: true,
        action: startable ? "start" : "open",
        reason: startable ? null
            : status.can_enable !== true ? "Not available in the current state."
                : "Set a power range in Auto TDP first.",
        busy,
    };
}
/** Format watts for a tile. Unknown stays unknown rather than becoming 0 W. */
function wattsValue(watts) {
    return typeof watts === "number" && Number.isFinite(watts)
        ? { text: `${Math.round(watts)} W`, known: true }
        : { text: "Unknown", known: false };
}
/** The FPS tile.
 *
 * FPS limiting is a proposed capability with no backend provider, and it is not
 * Auto TDP's target FPS. The tile keeps a fixed position in the grid and reads
 * unavailable: removing it would make the grid's shape depend on live evidence,
 * which moves a target under a player's thumb, and showing a number would be
 * fabricating one.
 */
function fpsTile() {
    return {
        available: false,
        value: { text: "Unavailable", known: false },
        reason: "No verified frame-rate provider on this device.",
    };
}

/** The Command Center quick-tile grid: pure, no React, no I/O, no requests.
 *
 * Approved layout (LAYOUT_APPROVAL.md, baseline df6a36c): two columns of
 * FPS target, TDP limit, Auto TDP and Display target, plus a fifth Safe
 * Disconnect tile marked In development.
 *
 * The grid's shape is fixed. Every tile keeps its position whatever the live
 * evidence says, and an unusable tile reads unavailable with a reason instead
 * of disappearing. A tile that vanishes moves every tile after it under the
 * player's thumb as a snapshot arrives, and on a controller that is worse than
 * a target that politely declines. This is the same rule the section row
 * already learned the hard way.
 *
 * No tile fabricates a value. Unknown is rendered as unknown, never as a
 * plausible default and never as a number carried from a stale read.
 *
 * Nothing here performs an operation. Tiles describe what a player may do; the
 * caller owns every request, and every guard stays where it already lives.
 */
/** Fixed order and fixed length. Two columns; the fifth tile sits alone on the
 * last row, which stepGrid already resolves from either cell above it. */
const TILE_ORDER = ["fps", "tdp", "auto-tdp", "display", "safe-disconnect"];
const TILE_COLUMNS = 2;
const ACTION_LABEL = {
    stop: "Stop", start: "Start", open: "Open Auto TDP", none: null,
};
function commandCenterTiles(input) {
    const performance = input.performance;
    const fps = fpsTile();
    const tiles = {
        // Proposed capability with no provider. Keeps its slot, states why.
        fps: {
            id: "fps", title: "FPS target", value: fps.value, available: false,
            reason: fps.reason, activation: "none", actionLabel: null, developmental: false,
        },
        // The configured power limit, which is not telemetry of current draw.
        tdp: {
            id: "tdp", title: "TDP limit",
            value: performance.supported ? wattsValue(performance.configuredWatts)
                : { text: "Unavailable", known: false },
            available: performance.supported,
            reason: performance.supported ? null : "This device has no verified TDP control.",
            activation: performance.supported ? "open" : "none",
            actionLabel: performance.supported ? "Open Auto TDP" : null,
            developmental: false,
        },
        // One context-sensitive action, never a toggle: Stop while running, Start
        // only when explicitly configured and permitted, otherwise open the module.
        "auto-tdp": {
            id: "auto-tdp", title: "Auto TDP",
            value: { text: performance.active ? "Running" : performance.supported ? "Off" : "Unavailable",
                known: performance.supported },
            available: performance.action !== "none",
            reason: performance.reason,
            activation: performance.action === "open" ? "open"
                : performance.action === "none" ? "none" : "act",
            actionLabel: ACTION_LABEL[performance.action],
            developmental: false,
        },
        // Reading plus a route. Requesting a display change stays with the surface
        // that already owns its guards; this tile does not run a transition.
        display: {
            id: "display", title: "Display target",
            value: input.displayTarget
                ? { text: input.displayTarget, known: true }
                : { text: "Unknown", known: false },
            available: true, reason: null, activation: "open", actionLabel: "Open eGPU",
            developmental: false,
        },
        // Wired to the owning backend's contract. Every judgement below comes from
        // disconnectPresentation: whether the action may be offered, what it says,
        // whether the display approval is needed, and whether this is a system
        // needing attention rather than a failed press. Re-deriving any of that
        // here is how the tile and the operation start disagreeing.
        //
        // Software removal is not unplug clearance. The confirmation copy lives in
        // egpu-disconnect-tile.ts with the tests that pin it, and is passed through
        // untouched rather than restated here.
        "safe-disconnect": (() => {
            const view = disconnectPresentation(input.disconnectStatus ?? null);
            return {
                id: "safe-disconnect", title: "Safe Disconnect",
                value: { text: view.value, known: view.available },
                available: view.available,
                reason: view.reason,
                activation: view.available ? "act" : "notice",
                actionLabel: view.actionLabel,
                developmental: false,
                confirmation: view.confirmation,
                displayApprovalRequired: view.displayApprovalRequired,
                attention: view.attention,
            };
        })(),
    };
    return TILE_ORDER.map((id) => tiles[id]);
}

/** Command Center first screen: rendering only, no policy, no requests.
 *
 * Which tiles exist, whether they are usable, what they say and what pressing
 * one means all come from command-center.ts. This file cannot disagree with
 * that model, and it performs no operation of its own.
 *
 * Two columns at roughly 268px of information width. Tiles keep a fixed size
 * and a fixed position: an unusable tile is dimmed and still focusable rather
 * than removed, so a target never moves under a player's thumb when a snapshot
 * arrives. Native left/right and up/down traversal is supplied by the
 * Focusable grid; stepGrid models the same movement for tests.
 */
const C = {
    cyan: "#39d8ff", text: "#f4f7fb", muted: "#9eb2ca",
    border: "#294665", amber: "#ffc247", dim: "#5d7a99",
};
const SURFACE = "linear-gradient(135deg, rgba(19,36,58,.96), rgba(9,21,36,.98))";
function Tile({ tile, onActivate }) {
    const usable = tile.available;
    return SP_JSX.jsxs(DFL.DialogButton, { "data-regear-tile": tile.id, onClick: () => onActivate(tile.id), "aria-label": `${tile.title}: ${tile.value.text}`, style: {
            minWidth: 0, width: "auto", minHeight: 62, margin: 0, padding: "8px 10px",
            display: "flex", flexDirection: "column", alignItems: "flex-start",
            justifyContent: "center", gap: 2, textAlign: "left", borderRadius: 12,
            background: SURFACE,
            border: `1px solid ${usable ? C.border : "#22374f"}`,
            color: usable ? C.text : C.dim,
            opacity: usable ? 1 : 0.72,
        }, children: [SP_JSX.jsx("span", { style: { fontSize: 11, letterSpacing: ".02em", color: C.muted,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }, children: tile.title }), SP_JSX.jsx("span", { style: { fontSize: 14, fontWeight: 760,
                    color: tile.developmental ? C.amber : tile.value.known ? C.cyan : C.dim,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }, children: tile.value.text }), tile.actionLabel && (SP_JSX.jsx("span", { style: { fontSize: 11, color: C.muted }, children: tile.actionLabel }))] });
}
function CommandCenterGrid({ tiles, onActivate }) {
    return SP_JSX.jsx(DFL.Focusable, { style: {
            display: "grid",
            gridTemplateColumns: `repeat(${TILE_COLUMNS}, minmax(0, 1fr))`,
            gap: 6, minWidth: 0, marginBottom: 10,
        }, "flow-children": "grid", children: tiles.map((tile) => SP_JSX.jsx(Tile, { tile: tile, onActivate: onActivate }, tile.id)) });
}
/** Reason for the tile a player just selected, shown under the grid rather
 * than inside it so tile heights stay uniform and the grid does not reflow. */
function TileReason({ tile }) {
    if (!tile || !tile.reason)
        return null;
    return SP_JSX.jsx("div", { style: { margin: "0 2px 10px", fontSize: 12, lineHeight: "16px", color: C.amber }, children: tile.reason });
}

/** Quick Access section taxonomy: pure, no React, no I/O, no requests.
 *
 * The panel grew one flat scroll of surfaces, and Auto TDP made it longer. This
 * splits the same controls into named sections so one area renders at a time.
 *
 * A section is never silently dropped. When its feature is unavailable the
 * section still appears with the reason, because a control that vanishes reads
 * as a bug and a missing signal must never be presented as a working one.
 * Unknown evidence fails closed to unavailable, per the repository's rule that
 * unknown state is not a capability claim.
 */
const WAITING = "Waiting for a fresh status update.";
function quickAccessSections(input = {}) {
    const fresh = input.fresh === true;
    // eGPU stays reachable without fresh evidence: it owns the recovery and
    // troubleshooting controls a player needs precisely when readings are stale.
    const egpu = {
        id: "egpu", title: "eGPU", summary: "Connection, display target, safe disconnect",
        available: true, reason: null,
    };
    const controller = {
        id: "controller", title: "Controller", summary: "Shortcuts and button routing",
        available: input.shortcutAvailable === true,
        reason: input.shortcutAvailable === true ? null
            : input.shortcutAvailable === false ? "No verified controller input source. Shortcuts stay unavailable."
                : "Controller input source not yet observed.",
    };
    // Auto TDP requires both a proven writer and current permission to use it.
    const tdpBlocked = input.autoTdpAvailable !== true ? "This device has no verified TDP control."
        : input.tdpCanEnable === false ? "TDP control is not available in the current state."
            : input.tdpCanEnable !== true ? "TDP readiness not yet observed."
                : null;
    const tdp = {
        id: "tdp", title: "Auto TDP", summary: "Power limit and automatic tuning",
        available: tdpBlocked === null, reason: tdpBlocked,
    };
    const display = {
        id: "display", title: "Display & Audio", summary: "Output target and audio handoff",
        available: fresh && input.healthKnown === true,
        reason: fresh ? (input.healthKnown === true ? null : "Display and audio health not yet observed.") : WAITING,
    };
    // System owns diagnostics and support export, which must stay reachable when
    // everything else is unknown; that is when a player needs them most.
    const system = {
        id: "system", title: "System", summary: "Diagnostics, readiness, support",
        available: true, reason: null,
    };
    return [egpu, controller, tdp, display, system];
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
            detail: "Re-Gear is preserving the current setup. Verify the display and controls before changing it.",
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
        detail: "eGPU and TV evidence are ready. Use Switch to TV now, or enable automatic TV docking.",
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
        body: "Re-Gear could not verify that the eGPU is safely absent, so the sleep request was not started.",
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
    "automatic_dock.suppressed_for_safe_disconnect": "Waiting for eGPU removal",
    "connection.disconnected": "Waiting for eGPU",
    "connection.waiting_for_pci": "eGPU detected; starting GPU",
    "connection.waiting_for_driver": "Waiting for eGPU graphics driver",
    "connection.waiting_for_link": "Waiting for eGPU PCIe link",
    "connection.waiting_for_hdmi": "Waiting for eGPU HDMI",
    "connection.waiting_for_audio": "Waiting for eGPU TV audio",
    "connection.waiting_for_session": "Preparing Steam session",
    "connection.game_running": "Waiting for game to close",
    "connection.stabilizing": "Checking eGPU connection stability",
    "connection.late_enumeration_detected": "eGPU GPU appeared; checking connection",
    "connection.ready_idle": "eGPU ready for TV",
    "connection.transport_dropped_before_pci": "eGPU USB4 connection dropped while starting",
    "connection.verified_absence_required": "Power off and disconnect eGPU before retrying",
    "connection.readiness_timed_out": "eGPU did not become ready",
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
    docked_egpu: "TV Docked",
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
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: "Redacted support bundle preview", strOKButtonText: "Close preview", bAlertDialog: true, bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: close, children: SP_JSX.jsxs("div", { style: { fontSize: "12px", lineHeight: "17px" }, children: [SP_JSX.jsx("p", { children: "Review this exact redacted JSON before copying or saving it. The save approval expires after five minutes and can be used once." }), SP_JSX.jsx("div", { style: { maxHeight: "55vh", overflow: "hidden" }, children: SP_JSX.jsx(DFL.ScrollPanel, { children: SP_JSX.jsx("pre", { style: { whiteSpace: "pre-wrap" }, children: preview.preview_json }) }) })] }) }), window, { strTitle: PRODUCT_NAME, bNeverPopOut: true });
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
        }, onCancel: close, children: SP_JSX.jsxs("div", { style: { fontSize: "13px", lineHeight: "18px" }, children: [SP_JSX.jsx("p", { children: "Continue only with the eGPU disconnected, no game running, and the handheld screen visible." }), SP_JSX.jsx("p", { children: "This installs Re-Gear's reversible Gamescope startup integration and reloads the user service configuration. It does not restart Gamescope, switch displays, or select a GPU." })] }) }), window, { strTitle: PRODUCT_NAME, bNeverPopOut: true });
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
        }, onCancel: close, children: SP_JSX.jsxs("div", { style: { fontSize: "13px", lineHeight: "18px" }, children: [SP_JSX.jsx("p", { children: "When Re-Gear verifies this Ally X, the exact supported eGPU profile, one ready TV, a healthy link, and no running game, it will restart Steam Game Mode onto the TV." }), SP_JSX.jsx("p", { children: "The screen will briefly show Steam shutting down. USB4 presence alone never triggers the restart, and physical live removal remains unsupported." })] }) }), window, { strTitle: PRODUCT_NAME, bNeverPopOut: true });
    return modal;
}
function showSafeDisconnectConfirmation(portable, onConfirm, onClose) {
    let modal;
    const close = () => {
        modal.Close();
        onClose();
    };
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: portable ? "Shut down for eGPU disconnect?" : "Return to Ally for eGPU disconnect?", strOKButtonText: portable ? "Shut down" : "Return to Ally", strCancelButtonText: "Cancel", bDestructiveWarning: true, bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: () => {
            close();
            onConfirm();
        }, onCancel: close, children: SP_JSX.jsx("div", { style: { fontSize: "13px", lineHeight: "18px" }, children: portable ? (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx("p", { children: "Re-Gear will revalidate idle Portable mode and request a normal system shutdown." }), SP_JSX.jsx("p", { children: "The request cannot prove physical power-off. Keep the eGPU connected until the fan stops and every top power LED is off." }), SP_JSX.jsx("p", { children: "If the fan remains on after 60 seconds, keep the eGPU connected and hold the Ally power button until the fan stops." })] })) : (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx("p", { children: "Re-Gear will require no running game, then restart Game Mode on the Ally display." }), SP_JSX.jsx("p", { children: "After Portable is verified, acknowledge the result and use this control again to shut down. Do not unplug yet." })] })) }) }), window, { strTitle: PRODUCT_NAME, bNeverPopOut: true });
    return modal;
}
function showControllerDisplayConfirmation(target, onConfirm, onClose) {
    let modal;
    const close = () => { modal.Close(); onClose(); };
    modal = DFL.showModal(SP_JSX.jsxs(DFL.ConfirmModal, { strTitle: target === "tv" ? "Switch to TV?" : "Return to Ally?", strOKButtonText: target === "tv" ? "Switch to TV" : "Return to Ally", strCancelButtonText: "Cancel", bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: () => { close(); onConfirm(); }, onCancel: close, children: [SP_JSX.jsx("p", { children: "Re-Gear will check that no game is running and verify display readiness before restarting Game Mode." }), SP_JSX.jsx("p", { children: "Keep the eGPU connected. This action does not shut down the Ally or make unplugging safe." })] }), window, { strTitle: PRODUCT_NAME, bNeverPopOut: true });
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
            ? "Another display integration is active. Re-Gear will not replace it."
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
                        : "Re-Gear will request a graceful close only for the exact ordinary user processes listed below." }), preview.targets.map((target, index) => (SP_JSX.jsxs("p", { children: [target.name, " \u2014 ", target.resources.map(label).join(", ")] }, `${target.name}-${index}`))), preview.protected_client_count > 0 && (SP_JSX.jsxs("p", { children: [preview.protected_client_count, " protected client(s) will not be closed."] })), SP_JSX.jsx("p", { children: "Clearing software clients does not authorize physical eGPU removal. Shut down before disconnecting the eGPU." })] }) }), window, { strTitle: PRODUCT_NAME, bNeverPopOut: true });
    return modal;
}
function showDiagnosticLoggingConfirmation(durationLabel, onConfirm, onClose) {
    let modal;
    const close = () => {
        modal.Close();
        onClose();
    };
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: "Enable verbose Re-Gear diagnostics?", strOKButtonText: "Enable", strCancelButtonText: "Cancel", bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: () => {
            close();
            onConfirm();
        }, onCancel: close, children: SP_JSX.jsxs("div", { style: { fontSize: "13px", lineHeight: "18px" }, children: [SP_JSX.jsxs("p", { children: ["Re-Gear will retain additional sanitized, Re-Gear-only events for ", durationLabel, ". Storage remains capped and verbose logging will not survive a reboot."] }), SP_JSX.jsx("p", { children: "Logs stay on this handheld unless you separately preview, save, and share a support bundle." })] }) }), window, { strTitle: PRODUCT_NAME, bNeverPopOut: true });
    return modal;
}
function BrandIcon({ size = 24 }) {
    return (SP_JSX.jsx("img", { src: brandIcon, alt: "", "aria-hidden": "true", width: size, height: size, style: { objectFit: "contain", flexShrink: 0 } }));
}
function BrandHeader() {
    return (SP_JSX.jsxs("span", { style: { display: "inline-flex", alignItems: "center", gap: 8, minHeight: 36, whiteSpace: "nowrap" }, children: [SP_JSX.jsx(BrandIcon, { size: 28 }), SP_JSX.jsx("span", { style: { fontSize: 20, fontWeight: 700, lineHeight: 1.2, color: "#ffffff" }, children: PRODUCT_NAME })] }));
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
function Content({ preflight, connection, shortcut }) {
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
    const [showHardwareDetails, setShowHardwareDetails] = SP_REACT.useState(false);
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
    // The approved layout replaces the icon row with a navigation stack. Command
    // Center sits at the bottom and is never popped; Back delegates to Steam's own
    // QAM Back once no internal level is left. See quick-access/module-registry.
    const [navStack, setNavStack] = SP_REACT.useState(INITIAL_STACK);
    // The owning backend's disconnect status. Null means not read yet, which is
    // not the same as "no": the tile renders that distinction itself.
    const [egpuDisconnect, setEgpuDisconnect] = SP_REACT.useState(null);
    const [disconnectBusy, setDisconnectBusy] = SP_REACT.useState(false);
    const [disconnectMessage, setDisconnectMessage] = SP_REACT.useState("");
    /** The tile whose reason is shown under the grid. */
    const [selectedTile, setSelectedTile] = SP_REACT.useState(null);
    const route = currentRoute(navStack);
    const onCommandCenter = route.kind === "command-center";
    // Read by the refresh callback, which must not be rebuilt on every navigation:
    // adding navStack to its dependencies would restart the refresh cycle on a
    // route change.
    const diagnosticsOnScreen = SP_REACT.useRef(true);
    SP_REACT.useEffect(() => {
        diagnosticsOnScreen.current = diagnosticsVisible(navStack, showDiagnostics);
    }, [navStack, showDiagnostics]);
    const [showJourneyDetails, setShowJourneyDetails] = SP_REACT.useState(false);
    const [presentationBusy, setPresentationBusy] = SP_REACT.useState(false);
    const [presentationMessage, setPresentationMessage] = SP_REACT.useState("");
    const [tvSwitchBusy, setTvSwitchBusy] = SP_REACT.useState(false);
    const [tvSwitchMessage, setTvSwitchMessage] = SP_REACT.useState("");
    const [tvSwitchAcknowledgementId, setTvSwitchAcknowledgementId] = SP_REACT.useState("");
    SP_REACT.useEffect(() => shortcut.subscribeAcknowledgement(setTvSwitchAcknowledgementId), [shortcut]);
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
    const disconnectProgressModal = SP_REACT.useRef(null);
    const safeDisconnectModal = shortcut.modal;
    const safeDisconnectExecuting = shortcut.portableBusy;
    const tvSwitchExecuting = shortcut.tvBusy;
    const controllerShortcutAvailable = shortcut.available;
    const requestControllerDisplaySwitch = shortcut.request;
    const processModal = SP_REACT.useRef(null);
    const diagnosticLoggingModal = SP_REACT.useRef(null);
    const refreshTransitionJournal = SP_REACT.useCallback(async () => {
        try {
            const status = await getTransitionJournalStatus();
            setJournalStatus(status);
            if (status.code === "journal.idle") {
                setJournalMessage("");
                // A verified success may be retired by the backend after the initial
                // status/RPC response. Do not keep its acknowledgement blocking actions.
                setTvSwitchAcknowledgementId("");
            }
            else if (status.owner === "sleep" && status.acknowledgement_required) {
                setJournalMessage("A prior sleep result must be acknowledged before Re-Gear can switch displays.");
            }
            else if (status.code === "journal.recovery_required") {
                setJournalMessage(`An interrupted ${label(status.owner)} workflow requires recovery. Re-Gear will not retry it automatically.`);
            }
            else if (status.owner === "unknown") {
                setJournalMessage("The safety journal owner is unknown. Re-Gear will not clear it or switch displays.");
            }
            else {
                setJournalMessage(`A prior ${label(status.owner)} result still needs attention.`);
            }
        }
        catch {
            setJournalStatus(null);
            setJournalMessage("Shared safety-journal status is unavailable. Re-Gear will not switch displays.");
        }
    }, []);
    SP_REACT.useEffect(() => () => {
        disconnectProgressModal.current?.Close();
        disconnectProgressModal.current = null;
        supportModal.current?.Close();
        supportModal.current = null;
        presentationModal.current?.Close();
        presentationModal.current = null;
        automaticDockModal.current?.Close();
        automaticDockModal.current = null;
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
                ? "A prior display transition needs acknowledgement. Re-Gear did not claim its target is active."
                : `Previous display transition result: ${label(status.code)}.`);
        }).catch(() => {
            if (!disposed) {
                setTvSwitchMessage("Display-transition safety state is unavailable. Re-Gear did not claim success.");
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
                setAutomaticDockStatus(null);
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
            const optionalDiagnostics = await collectOptionalDiagnostics(shouldCollectOptionalDiagnostics(
            // `showDiagnostics` says the player opened these surfaces, not that
            // they are on screen: on a pushed route the Command Center body is
            // not rendered, and collecting for surfaces nobody can see is work
            // the player did not ask for.
            quickAccessVisible && diagnosticsOnScreen.current, nextPayload.snapshot.game_state), {
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
        setShowHardwareDetails(false);
        // Steam may keep the plugin mounted between openings, so the route resets
        // with the rest of the compact state; otherwise the panel reopens wherever
        // it was left instead of at Command Center.
        setNavStack(stackOnPanelOpen());
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
        if (tvSwitchExecuting.current || safeDisconnectExecuting.current)
            return;
        tvSwitchExecuting.current = true;
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
                title: "Re-Gear is switching to the TV",
                body: "Watch the handheld screen while Re-Gear verifies the transition.",
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
            setTvSwitchMessage("TV switch did not complete. Re-Gear did not claim success.");
        }
        finally {
            tvSwitchExecuting.current = false;
            setTvSwitchBusy(false);
        }
    }, []);
    const openConnectionProgress = SP_REACT.useCallback(() => {
        connection.open(() => void executeTvSwitch());
    }, [connection, executeTvSwitch]);
    const changeAutomaticDock = SP_REACT.useCallback(async (enabled) => {
        setAutomaticDockBusy(true);
        setAutomaticDockMessage("");
        try {
            const status = await setAutomaticDockEnabled(enabled, enabled);
            setAutomaticDockStatus(status);
            setAutomaticDockMessage(status.enabled
                ? "Automatic TV docking is enabled. Re-Gear is waiting for complete eGPU and TV evidence."
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
    const executeSafeDisconnect = SP_REACT.useCallback(async (portable) => {
        if (safeDisconnectExecuting.current || tvSwitchExecuting.current)
            return;
        safeDisconnectExecuting.current = true;
        setSafeDisconnectBusy(true);
        setSafeDisconnectMessage("");
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
                    title: "Re-Gear requested an Ally shutdown",
                    body: "Completion is unverified. Keep the eGPU connected until the fan and every top power LED are off.",
                    critical: true,
                    duration: 30000,
                });
                const outcome = await executeSafeDisconnectShutdown(approval.approval_token);
                setSafeDisconnectMessage(outcome.accepted
                    ? "Power-off request accepted; completion is unverified. Keep the eGPU connected until the fan stops. If it remains on after 60 seconds, hold the Ally power button until the fan stops."
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
                title: "Re-Gear is returning to the Ally",
                body: "Do not disconnect the eGPU. Wait for Portable verification, then shut down.",
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
                ? "Shutdown was not requested. Keep the eGPU connected."
                : "Portable transition did not complete. Keep the eGPU connected.");
        }
        finally {
            safeDisconnectExecuting.current = false;
            setSafeDisconnectBusy(false);
        }
    }, []);
    const requestSafeDisconnectForMode = SP_REACT.useCallback((portable) => {
        if (safeDisconnectExecuting.current || tvSwitchExecuting.current || safeDisconnectModal.current)
            return;
        safeDisconnectModal.current = showSafeDisconnectConfirmation(portable, () => void executeSafeDisconnect(portable), () => {
            safeDisconnectModal.current = null;
        });
    }, [executeSafeDisconnect]);
    const requestSafeDisconnect = SP_REACT.useCallback(() => {
        requestSafeDisconnectForMode(payload?.inference.mode === "portable");
    }, [requestSafeDisconnectForMode, payload?.inference.mode]);
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
                shortcut.clearAcknowledgement();
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
        setShowHardwareDetails(false);
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
    // The Troubleshoot route is deliberately not wired here. Its content is the
    // six surfaces the existing `showDiagnostics` boolean gates, and moving them
    // behind a route is its own slice; opening an empty Troubleshoot destination
    // would be a screen that claims to hold controls it does not have. The
    // existing Troubleshooting control stays the way in until then.
    /** Read the disconnect status. The backend documents this call as observing
     * and mutating nothing -- no filter armed, no DRM master taken, no display
     * touched -- so it is safe to call whenever the screen showing it is open. */
    const refreshDisconnect = SP_REACT.useCallback(async () => {
        try {
            setEgpuDisconnect(await getEgpuDisconnectStatus());
        }
        catch {
            // A failed read is not evidence about the device. Leaving the previous
            // status would show a stale offer, so it falls back to not-read.
            setEgpuDisconnect(null);
        }
    }, []);
    /** Run the disconnect the player just confirmed.
     *
     * The confirmation text and the display approval both come from the owning
     * backend's presentation; neither is composed here. `release_display` is
     * passed exactly as that presentation reported it and is never defaulted on,
     * because turning the output off is visible to whoever is watching the TV.
     */
    const runDisconnect = SP_REACT.useCallback(async (releaseDisplay) => {
        setDisconnectBusy(true);
        setDisconnectMessage("");
        try {
            const outcome = await executeEgpuDisconnect(releaseDisplay);
            // A software removal is not clearance to unplug, so the result says what
            // happened and nothing about the cable.
            setDisconnectMessage(outcome.ok
                ? "The eGPU has been detached in software. Keep the cable connected."
                : `Disconnect did not complete: ${label(outcome.code)}.`);
        }
        catch {
            setDisconnectMessage("Re-Gear could not complete the disconnect request.");
        }
        finally {
            setDisconnectBusy(false);
            // Re-read rather than assuming what the attempt left behind.
            void refreshDisconnect();
        }
    }, [refreshDisconnect]);
    const openRoute = SP_REACT.useCallback((route) => {
        setNavStack((stack) => pushRoute(stack, route));
    }, []);
    // Pops one internal level. Whether Back is ours to handle at all is decided
    // by `hasInternalLevel` in the render below, not here: a handler that is
    // attached and then declines has already swallowed the press, and a decision
    // computed inside a state updater is not reliable because React may defer or
    // replay it.
    const popRoute = SP_REACT.useCallback(() => {
        setNavStack((stack) => backRoute(stack).stack);
    }, []);
    // The open-edge rule lives in troubleshootingToggle: opening asks for fresh
    // evidence, closing does not, and re-opening does not request again. That is
    // the surviving owner of what the deleted quick-access-section-state helper
    // held, and it is covered by its own tests.
    const toggleTroubleshooting = SP_REACT.useCallback(() => {
        const result = troubleshootingToggle(showDiagnostics);
        if (result.refresh)
            void refresh(true);
        setShowDiagnostics(result.next);
    }, [refresh, showDiagnostics]);
    // Only while the panel is open and the Command Center is the visible route:
    // reading for a screen nobody is looking at is work the player did not ask
    // for, and the tile is the only consumer.
    SP_REACT.useEffect(() => {
        if (!quickAccessVisible || !onCommandCenter)
            return;
        void refreshDisconnect();
    }, [quickAccessVisible, onCommandCenter, refreshDisconnect]);
    const toggleJourneyDetails = SP_REACT.useCallback(() => {
        setShowJourneyDetails((visible) => {
            const next = !visible;
            if (next) {
                window.setTimeout(() => revealJourneyDetails(journeyDetailsAnchor.current), 0);
            }
            return next;
        });
    }, []);
    // Only System is wired to the row in this slice; the other four targets change
    // the selection and nothing else yet. TDP evidence lives inside TdpControls, so
    // its readiness is not observable here and the section reads unavailable --
    // unknown state is not a capability claim.
    const sections = quickAccessSections({
        fresh: !loading && payload != null,
        shortcutAvailable: controllerShortcutAvailable,
        healthKnown: payload?.health != null,
    });
    const modules = quickAccessModules(sections);
    // Auto TDP status is not observable from here yet: it lives inside
    // TdpControls, and lifting it is qa-performance-controls-lift. Until then the
    // performance tiles report not-yet-observed rather than guessing a value.
    const tiles = commandCenterTiles({
        performance: performanceState({ status: null, busy: disconnectBusy }),
        displayTarget: payload ? label(payload.inference.mode) : undefined,
        disconnectStatus: egpuDisconnect,
    });
    const shownTile = tiles.find((tile) => tile.id === selectedTile);
    // Read-only status destinations, kept distinct from the configuration
    // modules: these open detail, never controls.
    const statusEntries = [
        { id: "egpu", title: "eGPU status",
            detail: label(payload?.inference.mode ?? "unknown") },
        { id: "controller", title: "Controller status",
            detail: controllerShortcutAvailable ? "Shortcut input available" : "Status unavailable" },
    ];
    const sectionVisibility = quickAccessSectionVisibility(showDiagnostics);
    return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx("style", { children: regearControlCss }), SP_JSX.jsx(DFL.Focusable
            // B is handled only while an internal level exists. At Command Center
            // no handler is attached at all, so the press reaches Steam's own QAM
            // Back instead of being swallowed by a handler that chose to do
            // nothing. Native confirmation of that propagation stays pending.
            , { ...(hasInternalLevel(navStack) ? { onCancelButton: popRoute } : {}), style: { minWidth: 0 }, children: SP_JSX.jsxs("div", { ref: statusAnchor, tabIndex: -1, children: [!onCommandCenter && (SP_JSX.jsx(DFL.PanelSection, { children: SP_JSX.jsx(ShellBody, { route: route, modules: modules, statusEntries: statusEntries, onOpenModule: (id) => openRoute({ kind: "module", id }), onOpenStatus: (id) => openRoute({ kind: "status", id }), children: null }) })), onCommandCenter && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSection, { title: "At a glance", children: SP_JSX.jsx(QuickAccessOverview, { summaryRef: statusFocusAnchor, onSummaryFocus: () => {
                                            if (statusAnchor.current)
                                                scrollToTopOfOwningPanel(statusAnchor.current);
                                        }, mode: payload?.inference.mode ?? "unknown", modeLabel: loading ? "Reading…" : label(payload?.inference.mode ?? "unknown"), health: healthStatusLabel(payload?.health, loading), game: label(snapshot?.game_state ?? "unknown"), loading: loading }) }), SP_JSX.jsxs(DFL.PanelSection, { children: [SP_JSX.jsx("div", { style: { display: "flex", flexDirection: "column", minWidth: 0 }, children: SP_JSX.jsx(ModulesButton, { onOpen: () => openRoute({ kind: "modules" }) }) }), SP_JSX.jsx(CommandCenterGrid, { tiles: tiles, onActivate: (id) => {
                                                setSelectedTile(id);
                                                const tile = tiles.find((candidate) => candidate.id === id);
                                                if (!tile)
                                                    return;
                                                if (id === "safe-disconnect") {
                                                    // Only an offer the owning backend actually made is actionable.
                                                    // Anything else selects the tile so its reason is read.
                                                    if (tile.activation !== "act" || !tile.confirmation || disconnectBusy)
                                                        return;
                                                    const releaseDisplay = tile.displayApprovalRequired === true;
                                                    showDisconnectConfirmation(tile.confirmation, () => {
                                                        void runDisconnect(releaseDisplay);
                                                    });
                                                    return;
                                                }
                                                if (tile.activation !== "open")
                                                    return;
                                                // Performance tiles route to Auto TDP; the display target routes to
                                                // the eGPU module, which owns the guarded transition.
                                                openRoute(id === "display"
                                                    ? { kind: "module", id: "egpu" }
                                                    : { kind: "module", id: "auto-tdp" });
                                            } }), SP_JSX.jsx(TileReason, { tile: shownTile }), disconnectMessage && (SP_JSX.jsx(DFL.PanelSectionRow, { children: disconnectMessage })), SP_JSX.jsx(ShellBody, { route: route, modules: modules, statusEntries: statusEntries, onOpenModule: (id) => openRoute({ kind: "module", id }), onOpenStatus: (id) => openRoute({ kind: "status", id }), children: null })] }), payload?.connection_readiness && payload.connection_readiness.stage !== "disconnected" &&
                                    SP_JSX.jsx(DFL.PanelSection, { title: "eGPU readiness", children: SP_JSX.jsx(ConnectionQuickStatus, { store: connection.store, visible: quickAccessVisible, onOpen: openConnectionProgress }) }), SP_JSX.jsx(TdpControls, { visible: quickAccessVisible }), SP_JSX.jsxs(DFL.PanelSection, { title: "Docking & actions", children: [SP_JSX.jsxs("div", { ref: primaryControlAnchor, children: [SP_JSX.jsx(DashboardSurface, { children: SP_JSX.jsx("div", { style: { padding: "4px 12px" }, children: SP_JSX.jsx(DFL.ToggleField, { label: "Automatic TV docking", layout: "inline", description: automaticDockBusy
                                                                ? "Saving…"
                                                                : !automaticDockStatus
                                                                    ? "Status unavailable"
                                                                    : automaticDockStatus.enabled
                                                                        ? label(automaticDockStatus.code)
                                                                        : "Off · Ask before enabling", checked: automaticDockStatus?.enabled === true, disabled: automaticDockBusy || !automaticDockStatus, highlightOnFocus: true, onChange: toggleAutomaticDock }) }) }), automaticDockMessage && (SP_JSX.jsx(DFL.PanelSectionRow, { children: automaticDockMessage })), SP_JSX.jsx(DashboardSurface, { primary: true, children: SP_JSX.jsx(DashboardAction, { icon: "bolt", tone: "primary", title: tvSwitchBusy || safeDisconnectBusy
                                                            ? "Switching…"
                                                            : payload?.inference.mode === "docked_egpu"
                                                                ? "Switch to handheld"
                                                                : "Switch to TV", description: controllerShortcutAvailable
                                                            ? "Hold Back/View + Y for 3 seconds to switch."
                                                            : "Checks readiness before switching. Controller shortcut unavailable.", onClick: () => {
                                                            if (payload?.inference.mode === "docked_egpu")
                                                                requestControllerDisplaySwitch("ally");
                                                            else if (payload?.inference.mode === "portable")
                                                                void executeTvSwitch();
                                                        }, disabled: tvSwitchBusy
                                                            || safeDisconnectBusy
                                                            || (payload?.inference.mode !== "portable" && payload?.inference.mode !== "docked_egpu")
                                                            || Boolean(tvSwitchAcknowledgementId)
                                                            || Boolean(journalStatus && journalStatus.code !== "journal.idle") }) }), tvSwitchMessage && SP_JSX.jsx(DFL.PanelSectionRow, { children: tvSwitchMessage }), SP_JSX.jsx(DashboardSurface, { children: SP_JSX.jsx(DashboardAction, { icon: "connection", title: "Disconnect status", description: "Live checks \u00B7 keep eGPU connected", onClick: () => {
                                                            if (!disconnectProgressModal.current)
                                                                disconnectProgressModal.current = showDisconnectProgress(() => { disconnectProgressModal.current = null; });
                                                        } }) }), SP_JSX.jsx(DashboardSurface, { children: SP_JSX.jsx(DashboardAction, { icon: "power", title: safeDisconnectBusy
                                                            ? "Checking…"
                                                            : payload?.inference.mode === "portable"
                                                                ? "Shut down before unplugging"
                                                                : "Prepare to disconnect", description: "Keep the eGPU connected until fully powered off.", onClick: requestSafeDisconnect, disabled: safeDisconnectBusy
                                                            || !disconnect?.applicable
                                                            || Boolean(tvSwitchAcknowledgementId)
                                                            || Boolean(journalStatus && journalStatus.code !== "journal.idle") }) }), safeDisconnectMessage && (SP_JSX.jsx(DFL.PanelSectionRow, { children: safeDisconnectMessage })), journalStatus && journalStatus.code !== "journal.idle" && (SP_JSX.jsx(DiagnosticRow, { name: "Safety journal", value: label(journalStatus.owner) })), journalMessage && SP_JSX.jsx(DFL.PanelSectionRow, { children: journalMessage }), journalStatus?.owner === "sleep"
                                                    && journalStatus.acknowledgement_required
                                                    && journalStatus.acknowledgement_id && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void acknowledgePriorSleep(), disabled: journalBusy, children: journalBusy ? "Acknowledging…" : "Acknowledge prior sleep result" }) })), tvSwitchAcknowledgementId && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void acknowledgeTvSwitch(), disabled: tvSwitchBusy, children: "Acknowledge prior display transition result" }) })), SP_JSX.jsx(DashboardSurface, { children: SP_JSX.jsx(DashboardAction, { title: "Troubleshoot", icon: "tools", description: "Safety checks, details & support", expanded: showDiagnostics, onClick: toggleTroubleshooting }) })] }), needsAttention && (SP_JSX.jsx(DFL.PanelSectionRow, { children: error || healthAttention[0] || `${snapshot?.blockers.length} safety check${snapshot?.blockers.length === 1 ? "" : "s"} needs attention.` })), sectionVisibility.diagnostics && (SP_JSX.jsx(DFL.PanelSectionRow, { children: "Read-only status refreshes while this panel is open." })), sectionVisibility.diagnostics && sleepGuard?.required && sleepWarningHidden && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: showSleepWarning, children: "Show sleep warning again" }) }))] }), sectionVisibility.journey && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsxs(DFL.PanelSection, { title: "Journey status", children: [journeyRows.map((row) => (SP_JSX.jsx(DiagnosticRow, { name: row.name, value: row.value }, row.name))), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: toggleJourneyDetails, children: showJourneyDetails ? "Hide journey details" : "Open journey details" }) })] }), showJourneyDetails && (SP_JSX.jsx("div", { ref: journeyDetailsAnchor, children: SP_JSX.jsxs(DFL.PanelSection, { title: "Journey details", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: "Read-only local policy status. It does not perform dock, undock, recovery, or game actions." }), journeyDetailRows.map((row) => (SP_JSX.jsx(DiagnosticRow, { name: row.name, value: row.detail }, row.name)))] }) }))] })), sectionVisibility.sleepProtection && SP_JSX.jsxs(DFL.PanelSection, { title: "Sleep protection", children: [SP_JSX.jsx(DiagnosticRow, { name: "System inhibitor", value: loading
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
                                                                : "The attached eGPU is known to wake this handheld immediately after sleep. Sleep remains blocked until the eGPU is verified absent." }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: hideSleepWarning, children: "Never show this explanation again" }) })] })), sleepWarningHidden && (SP_JSX.jsx(DFL.PanelSectionRow, { children: "The explanation is hidden. Sleep protection remains active." }))] }))] }), sectionVisibility.disconnectReadiness && SP_JSX.jsxs(DFL.PanelSection, { title: "Disconnect readiness", children: [SP_JSX.jsx(DiagnosticRow, { name: "Status", value: disconnectStatus }), disconnect?.applicable && (SP_JSX.jsx(DiagnosticRow, { name: "Resource clients", value: String(disconnect.clients.length) })), (disconnect?.storage_devices ?? 0) > 0 && (SP_JSX.jsx(DiagnosticRow, { name: "eGPU storage", value: disconnect?.storage_in_use ? "In use — blocked" : "Not mounted" })), disconnect?.error && SP_JSX.jsx(DFL.PanelSectionRow, { children: disconnect.error }), closeEligibleClientCount > 0 && !processAcknowledgementId && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void inspectProcessRelease("graceful"), disabled: processBusy, children: processBusy ? "Checking…" : "Close eligible eGPU processes" }) })), forceReceiptToken && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void reviewForceClose(), disabled: processBusy, children: "Review force close" }) })), processAcknowledgementId && !forceReceiptToken && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void acknowledgeProcessResult(), disabled: processBusy, children: "Acknowledge process-release result" }) })), processMessage && SP_JSX.jsx(DFL.PanelSectionRow, { children: processMessage }), SP_JSX.jsx(DFL.PanelSectionRow, { children: "Process closure always requires confirmation. Software readiness never authorizes physical eGPU removal." })] }), needsAttention && (SP_JSX.jsxs(DFL.PanelSection, { title: "Needs attention", children: [error && SP_JSX.jsx(DFL.PanelSectionRow, { children: error }), healthAttention.map((message) => (SP_JSX.jsx(DFL.PanelSectionRow, { children: message }, message))), snapshot?.blockers.map((blocker) => (SP_JSX.jsx(DFL.PanelSectionRow, { children: blocker.message }, blocker.code)))] })), sectionVisibility.support && SP_JSX.jsxs(DFL.PanelSection, { title: "Support bundle", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: "Preview a bounded Re-Gear-only report before copying or saving it. Raw hardware IDs, addresses, usernames, home paths, and command lines are excluded or redacted." }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void createSupportPreview(), disabled: supportBusy, children: supportBusy ? "Working…" : "Preview redacted support bundle" }) }), supportPreview && (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DiagnosticRow, { name: "Preview size", value: `${supportPreview.size_bytes} bytes` }), SP_JSX.jsx(DiagnosticRow, { name: "Recent events", value: String(supportPreview.event_count) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: reviewSupportPreview, disabled: supportBusy, children: "Review exact redacted JSON" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void copySupportPreview(), disabled: supportBusy, children: "Copy reviewed JSON" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void saveApprovedSupportPreview(), disabled: supportBusy, children: "Save reviewed bundle to Downloads" }) })] })), supportMessage && SP_JSX.jsx(DFL.PanelSectionRow, { children: supportMessage })] }), sectionVisibility.diagnostics && (SP_JSX.jsxs(DFL.PanelSection, { title: "Troubleshooting details", children: [SP_JSX.jsxs(DashboardSurface, { children: [SP_JSX.jsx(DashboardAction, { title: "Dock / eGPU", description: progress.label, icon: "connection", expanded: showHardwareDetails, onClick: () => setShowHardwareDetails((visible) => !visible) }), showHardwareDetails && SP_JSX.jsxs("div", { children: [hardwareDetailRows(payload).map(([name, value]) => SP_JSX.jsx(DiagnosticRow, { name: name, value: value }, name)), SP_JSX.jsx(DFL.PanelSectionRow, { children: progress.detail })] })] }), SP_JSX.jsx(DFL.PanelSectionRow, { children: "Read-only technical evidence. Raw hardware identities, connector names, and process IDs are hidden." }), optionalDiagnosticsDeferred && (SP_JSX.jsx(DFL.PanelSectionRow, { children: "Additional troubleshooting checks wait until Re-Gear confirms no game is running." })), overlayRows.map((row) => (SP_JSX.jsx(DiagnosticRow, { name: row.name, value: row.value }, row.name))), dockedIgpuStatus?.acknowledgement_required && (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void acknowledgeDockedIgpuWatch(), children: "Acknowledge Docked-iGPU watcher state" }) })), dockedIgpuMessage && (SP_JSX.jsx(DFL.PanelSectionRow, { children: dockedIgpuMessage })), SP_JSX.jsx(DFL.DropdownItem, { label: "Verbose logging duration", description: "Temporary, sanitized, capped, and off by default", rgOptions: DIAGNOSTIC_LOGGING_OPTIONS, selectedOption: diagnosticLoggingDuration, disabled: diagnosticLoggingBusy || diagnosticLoggingStatus?.enabled === true, onChange: (option) => {
                                                setDiagnosticLoggingDuration(option.data);
                                            } }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: diagnosticLoggingStatus?.enabled
                                                    ? () => void stopDiagnosticLogging()
                                                    : requestDiagnosticLogging, disabled: diagnosticLoggingBusy, children: diagnosticLoggingStatus?.enabled
                                                    ? "Disable verbose diagnostics"
                                                    : "Enable verbose diagnostics" }) }), diagnosticLoggingMessage && (SP_JSX.jsx(DFL.PanelSectionRow, { children: diagnosticLoggingMessage })), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => void inspectPresentationPreparation(), disabled: presentationBusy, children: presentationBusy ? "Checking…" : "Prepare supervised display validation" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: "Preparation only. This control cannot restart Gamescope or switch displays." }), presentationMessage && SP_JSX.jsx(DFL.PanelSectionRow, { children: presentationMessage })] })), sectionVisibility.navigation && SP_JSX.jsx(DFL.PanelSection, { title: "Navigation", children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: returnToStatus, children: "Back to top" }) }) })] }))] }) })] }));
}
/** Confirm a software disconnect.
 *
 * The body is the owning backend's confirmation string, rendered verbatim. It
 * already states that the Steam session will restart, that the external
 * display turns off when that applies, and that the cable stays connected.
 * Rewriting or supplementing it here would create a second source of truth for
 * the one piece of copy that must not drift.
 */
function showDisconnectConfirmation(confirmation, onConfirm) {
    let modal;
    const close = () => modal.Close();
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: "Disconnect the eGPU?", strOKButtonText: "Disconnect", strCancelButtonText: "Cancel", bDestructiveWarning: true, bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: () => {
            close();
            onConfirm();
        }, onCancel: close, children: SP_JSX.jsx("div", { style: { fontSize: "12px", lineHeight: "17px" }, children: confirmation }) }), window, { strTitle: PRODUCT_NAME, bNeverPopOut: true });
    return modal;
}
function showBlockedAttempt(warning, onClose) {
    let modal;
    const close = () => {
        modal.Close();
        onClose();
    };
    // Let Decky resolve Steam's visible SP window after the Power menu closes.
    // SharedJSContext's global window is not a player-visible modal parent.
    modal = DFL.showModal(SP_JSX.jsx(DFL.ConfirmModal, { strTitle: warning.title, strDescription: warning.body, strOKButtonText: "OK", bAlertDialog: true, bDestructiveWarning: warning.critical, bDisableBackgroundDismiss: true, bHideCloseIcon: true, onOK: close }), window, { strTitle: PRODUCT_NAME, bNeverPopOut: true });
    return modal;
}
var index = definePlugin(() => {
    const shortcut = createDisplayShortcutRuntime({
        input: steamControllerInput(window),
        readContext: async () => {
            const [snapshot, journal] = await Promise.all([getSnapshot(), getTransitionJournalStatus()]);
            return { snapshot, journal };
        },
        show: showControllerDisplayConfirmation,
        approve: target => target === "tv" ? approveSupervisedTvSwitch() : approveSupervisedPortableSwitch(),
        execute: (target, token) => target === "tv" ? executeSupervisedTvSwitch(token) : executeSupervisedPortableSwitch(token),
        report: body => { toaster.toast({ title: PRODUCT_NAME, body, duration: 15000 }); },
    });
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
    const offlineFocusChecks = startOfflineFocusChecks();
    const connection = startConnectionMonitor({
        read: async () => {
            const [payload, automatic, journal] = await Promise.all([
                getSnapshot(), getAutomaticDockStatus(), getTransitionJournalStatus(),
            ]);
            return { payload, automatic, journal: journal.code };
        },
        show: (store, switchTv, closed) => showConnectionLivePanel(store, switchTv, closed),
    });
    return {
        name: PRODUCT_NAME,
        titleView: SP_JSX.jsx("div", { className: DFL.staticClasses.Title, style: { display: "flex", alignItems: "center" }, children: SP_JSX.jsx(BrandHeader, {}) }),
        content: SP_JSX.jsx(Content, { preflight: preflight, connection: connection, shortcut: shortcut }),
        icon: SP_JSX.jsx(BrandIcon, {}),
        alwaysRender: true,
        onDismount() {
            shortcut.stop();
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

export { index as default };
//# sourceMappingURL=index.js.map
