import type { SnapshotPayload } from "./backend";
export function disconnectProgress(payload: SnapshotPayload | null, failed = false, now = Date.now()) {
  const s = payload?.snapshot;
  const age = now - Date.parse(s?.observed_at ?? "");
  const fresh = !failed && Number.isFinite(age) && age >= -5000 && age < 15000;
  const selected = s?.gpus.filter(gpu => gpu.present && gpu.selected_for_render);
  const active = s?.displays.filter(display => display.active);
  const internal = selected?.length === 1 && selected[0].role === "internal" && selected[0].confidence === "verified"
    && active?.length === 1 && active[0].kind === "internal" && active[0].confidence === "verified";
  const d = s?.disconnect_readiness;
  const clientsClear = d?.applicable && d.scan_complete && !d.error && d.clients.length === 0 && d.storage_devices === 0 && !d.storage_in_use;
  return {
    // A clean client scan is not a safe-to-unplug capability. This adapter has
    // no release RPC or final-verification contract; it cannot report success.
    safeToUnplug: false as const,
    detail: !fresh ? "Waiting for a fresh status update." : d?.clients.length
      ? `${d.clients.length} eGPU client(s) remain. Live release is not available in this build.`
      : "Live GPU release and final disconnect verification are not available in this build.",
    rows: [
      {label:"No game running", state:fresh && s?.game_state === "idle" ? "ready" : fresh && s?.game_state === "running" ? "blocked" : "waiting"},
      {label:"Ally display & render GPU", state:fresh && internal ? "ready" : "waiting"},
      {label:"Ally audio", state:"unavailable"},
      {label:"Remaining eGPU clients", state:fresh && clientsClear ? "ready" : fresh && d?.clients.length ? "blocked" : "waiting"},
      {label:"GPU & link release", state:"unavailable"},
      {label:"Final disconnect verification", state:"unavailable"},
    ],
  };
}
