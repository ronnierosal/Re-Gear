import type { SnapshotPayload } from "./backend";

/** Selection represents observed placement, never a clickable transition target. */
export function placementCards(mode: string, loading = false) {
  return [
    { name: "Portable", detail: "Internal GPU · Handheld screen", active: !loading && mode === "portable" },
    { name: "TV Docked", detail: "External GPU · TV", active: !loading && mode === "tv_docked" },
  ];
}

/** Bounded snapshot-only facts; opening this disclosure starts no extra requests. */
export function hardwareDetailRows(payload: SnapshotPayload | null): Array<[string, string]> {
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
