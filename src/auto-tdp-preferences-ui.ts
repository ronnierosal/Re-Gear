import type { AutoTdpPreferencesPayload } from "./backend";

export const preferenceModes = [
  { data: "portable", label: "Portable" },
  { data: "boosted_handheld", label: "Boosted Handheld" },
  { data: "docked_igpu", label: "Docked-iGPU" },
  { data: "docked_egpu", label: "Docked-eGPU" },
];
export function sanitizeAutoTdpPreferences(value: unknown): AutoTdpPreferencesPayload | null {
  if (!value || typeof value !== "object") return null;
  const v = value as AutoTdpPreferencesPayload;
  if (v.schema_version !== 1 || !["loaded", "missing", "saved", "invalid", "save_failed"].some(code => v.code === `auto_tdp_preferences.${code}`) || !Array.isArray(v.preferences) || v.preferences.length > 4) return null;
  const seen = new Set<string>();
  for (const row of v.preferences) {
    if (!row || !preferenceModes.some(mode => mode.data === row.placement) || seen.has(row.placement)
        || typeof row.target_fps !== "number" || !Number.isFinite(row.target_fps) || row.target_fps <= 2 || row.target_fps > 1000
        || !Number.isSafeInteger(row.minimum_watts) || !Number.isSafeInteger(row.maximum_watts)
        || row.minimum_watts <= 0 || row.maximum_watts > 0xffffffff || row.minimum_watts > row.maximum_watts) return null;
    seen.add(row.placement);
  }
  return v;
}
