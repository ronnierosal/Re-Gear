import { ButtonItem, DropdownItem, PanelSectionRow } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { getAutoTdpPreferences, saveAutoTdpPreference, type AutoTdpPreferencesPayload, type AutoTdpSavedPreference } from "./backend";
import { preferenceModes, sanitizeAutoTdpPreferences } from "./auto-tdp-preferences-ui";

export function AutoTdpPreferencesControls({ target, minimum, maximum, canSave, onLoad }: {
  target: number; minimum: number | null; maximum: number | null; canSave: boolean;
  onLoad: (preference: AutoTdpSavedPreference) => void;
}) {
  const [mode, setMode] = useState("portable");
  const [status, setStatus] = useState<AutoTdpPreferencesPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  const pending = useRef(false);
  const request = async (save = false) => {
    if (pending.current) return;
    pending.current = true; setBusy(true);
    try {
      const result = await (save && minimum !== null && maximum !== null ? saveAutoTdpPreference(mode, target, minimum, maximum) : getAutoTdpPreferences());
      if (mounted.current) setStatus(sanitizeAutoTdpPreferences(result));
    } catch { if (mounted.current) setStatus(null); }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  };
  useEffect(() => { mounted.current = true; void request(); return () => { mounted.current = false; }; }, []);
  const saved = status?.preferences.find(row => row.placement === mode);
  return <>
    <DropdownItem label="Save preferences for" rgOptions={preferenceModes} selectedOption={mode} disabled={busy} onChange={option => { if (preferenceModes.some(row => row.data === option.data)) setMode(option.data as string); }} />
    <PanelSectionRow>{busy ? "Checking saved preferences…" : !status || ["auto_tdp_preferences.invalid", "auto_tdp_preferences.save_failed"].includes(status.code) ? "Preferences unavailable or save failed. Refresh to check stored values." : status.code === "auto_tdp_preferences.saved" ? "Preferences saved. Auto TDP settings and activation are unchanged." : "Saved preferences do not start Auto TDP."}</PanelSectionRow>
    <PanelSectionRow>{saved ? `Saved: ${saved.target_fps} FPS, ${saved.minimum_watts}–${saved.maximum_watts} W.` : "No saved preferences for this mode."}</PanelSectionRow>
    {mode !== "portable" && <PanelSectionRow>This mode's power profile is not validated. Preferences can be saved for future use.</PanelSectionRow>}
    <PanelSectionRow><ButtonItem layout="below" disabled={busy || !canSave} onClick={() => void request(true)}>Save current FPS and range</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy || !saved || mode !== "portable" || !canSave} onClick={() => { if (saved && mode === "portable") onLoad(saved); }}>Load Portable preferences into controls</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void request()}>Refresh saved preferences</ButtonItem></PanelSectionRow>
  </>;
}
