export type DockAction = "whole_dock_disconnect" | "whole_dock_reconnect";
export function dockControl(status: any, snapshot: any, now = Date.now()): { action: DockAction | null; label: string; message: string } {
  const unavailable = { action: null, label: "Safely disconnect", message: "Disconnect status unavailable. Refresh before continuing." };
  if (status?.schema_version !== 1 || status.safe_to_unplug !== false || typeof status.busy !== "boolean") return unavailable;
  if (status.busy) return { action: null, label: "Working…", message: "Keep the cable connected. Re-Gear is checking the dock." };
  const observed = typeof snapshot?.observed_at === "string" ? Date.parse(snapshot.observed_at) : NaN;
  if (!Number.isFinite(observed) || observed > now || now - observed > 10000) return unavailable;
  if (status.code === "dock_teardown.software_down" && status.software_down === true) {
    return { action: snapshot?.game_state === "idle" ? "whole_dock_reconnect" : null,
      label: "Reconnect eGPU", message: "Software disconnect verified. Keep the cable connected for this trial." };
  }
  const fresh = status.code === "dock_teardown.no_trial";
  const restored = status.code === "dock_reconnect.software_reconnected" && status.software_reconnected === true && status.ok === true;
  if (!fresh && !restored) return { action: null, label: "Needs attention", message: "The last attempt is unresolved. Keep the cable connected; do not repeat the operation." };
  if (snapshot?.game_state !== "idle") return { action: null, label: "Safely disconnect", message: "Close your game and wait for an idle reading before disconnecting." };
  if (snapshot?.egpu_link?.state !== "up") return { action: null, label: "Safely disconnect", message: "Waiting for the eGPU to be detected." };
  if (typeof status.attachment_token !== "string" || !/^[a-f0-9]{64}:[a-f0-9]{64}$/.test(status.attachment_token)) return unavailable;
  return { action: "whole_dock_disconnect", label: "Safely disconnect", message: restored
    ? "Software reconnect verified. Check picture, audio and controls."
    : "Return to the handheld and disconnect the dock in software." };
}
