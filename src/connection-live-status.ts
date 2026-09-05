import type { SnapshotPayload, AutomaticDockStatusPayload } from "./backend";
export type Light = "ready" | "waiting" | "blocked";
export type LiveStatus = { phase: "checking" | "switching" | "complete"; connected: boolean; expiresAt: number; seconds: number; title: string; rows: {label: string; state: Light}[]; canSwitch: boolean };
export function connectionLiveStatus(payload: SnapshotPayload | null, automatic: AutomaticDockStatusPayload | null, journal: string | undefined, failed = false): LiveStatus {
  const c = payload?.connection_readiness;
  const connected = !!c && c.stage !== "disconnected";
  const snapshotAge = Date.now() - Date.parse(payload?.snapshot.observed_at ?? "");
  const fresh = !failed && Number.isFinite(snapshotAge) && snapshotAge >= -5000 && snapshotAge < 15000
    && typeof c?.checks_age_ms === "number" && c.checks_age_ms >= 0 && c.checks_age_ms < 15000;
  // The backend timeout remains an authorization boundary, not proof of a
  // failed cable/device. Later exact enumeration can start a fresh window.
  const blocked = fresh && ["link_training_failed", "action_required"].includes(c?.stage ?? "");
  const names = {gpu: "GPU and driver", link: "Connection link", hdmi: "TV HDMI detected", audio: "Audio recovery ready", session: "Display switching ready", idle: "No game running"};
  const rows = Object.entries(names).map(([key, label]) => ({label, state: (!fresh ? "waiting" : (key === "idle" ? payload?.snapshot.game_state === "idle" && c?.checks?.idle === true : c?.checks?.[key as keyof typeof names] === true) ? "ready" : blocked || key === "idle" && payload?.snapshot.game_state === "running" ? "blocked" : "waiting") as Light}));
  rows.push({label: "Previous result cleared", state: !fresh || !journal ? "waiting" : journal === "journal.idle" ? "ready" : "blocked"});
  const all = fresh && c?.stage === "ready_idle" && rows.every(row => row.state === "ready");
  const switching = fresh && automatic?.stage === "switching";
  const docked = fresh && automatic?.stage === "docked" && payload?.inference.mode === "docked_egpu";
  const waiting: Record<string, string> = {waiting_for_pci: "Waiting for G1 detection", transport_detected: "G1 connection detected", waiting_for_driver: "Waiting for GPU driver", waiting_for_link: "Waiting for connection link", waiting_for_hdmi: "Waiting for TV HDMI", waiting_for_audio: "Checking audio recovery", waiting_for_session: "Waiting for display integration", game_running: "Close the game to continue", stabilizing: "Checking connection stability", timed_out: "Detection timed out — keep G1 connected", link_training_failed: "Connection link needs attention", action_required: "Connection needs attention"};
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
  return {phase: docked ? "complete" : switching ? "switching" : "checking", connected, expiresAt: fresh ? Date.now() + Math.max(0, 15000 - Math.max(snapshotAge, c?.checks_age_ms ?? 15000)) : 0, seconds: Math.floor((c?.window_age_ms ?? 0) / 1000), rows,
    title: !fresh ? "Waiting for a fresh status update" : switching ? "Switching to TV — checking picture and audio" : docked ? "TV transition reported complete" : all ? automatic?.enabled ? "Ready — waiting for automatic switch" : "Ready to switch to TV" : detail ?? "Checking connection readiness",
    canSwitch: all && automatic?.enabled === false};
}
export function createLiveStatusStore() {
  let value: LiveStatus = {phase:"checking",connected:false,expiresAt:0,seconds:0,title:"Checking connection",rows:[],canSwitch:false};
  const listeners = new Set<() => void>();
  return {get: () => value, set(next: LiveStatus) { value = next; for (const listener of listeners) listener(); }, subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }};
}
