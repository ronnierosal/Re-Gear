import { ButtonItem, DropdownItem, PanelSectionRow, ToggleField } from "@decky/ui";
import { TdpBenchmarkControls } from "./tdp-benchmark-controls";
import { AutoTdpPreferencesControls } from "./auto-tdp-preferences-controls";
import { useEffect, useState } from "react";
import type { PerformanceHandle } from "./quick-access/use-performance";
import { autoTdpActivity, autoTdpMessage, validAutoTdpRange } from "./auto-tdp-ui";
import { tdpMessage } from "./tdp-ui";

export function AutoTdpControls({ controller }: { controller: PerformanceHandle }) {
  const [target, setTarget] = useState(60);
  const [minimum, setMinimum] = useState<number | null>(null);
  const [maximum, setMaximum] = useState<number | null>(null);
  const [benchmarkVisible, setBenchmarkVisible] = useState(false);
  const [preferencesVisible, setPreferencesVisible] = useState(false);
  const { manual, auto: status, busy, stopping } = controller;
  const manualBusy = busy;
  const manualMessage = tdpMessage(manual);
  useEffect(() => {
    if (status?.target_fps != null) {
      setTarget(status.target_fps); setMinimum(status.minimum_watts); setMaximum(status.maximum_watts);
    }
  }, [status]);
  const watts = manual?.minimum_watts != null && manual.maximum_watts != null
    ? Array.from({ length: manual.maximum_watts - manual.minimum_watts + 1 }, (_, index) => ({ data: manual.minimum_watts! + index, label: `${manual.minimum_watts! + index} W` })) : [];
  const targets = [...new Set([30, 40, 45, 60, 90, 120, target])].sort((a, b) => a - b).map((value) => ({ data: value, label: `${value} FPS` }));
  const valid = validAutoTdpRange(manual, minimum, maximum, target);
  const locked = busy || manualBusy || status?.running === true;
  return <>
    <PanelSectionRow><strong>Auto TDP</strong></PanelSectionRow>
    <PanelSectionRow>{busy ? (stopping ? "Stopping Auto TDP…" : "Checking Auto TDP…") : autoTdpMessage(status, manualMessage)}</PanelSectionRow>
    {!busy && autoTdpActivity(status) && <PanelSectionRow>{autoTdpActivity(status)}</PanelSectionRow>}
    <DropdownItem label="Target frame rate" rgOptions={targets} selectedOption={target} disabled={locked} onChange={(option) => { if (targets.some((entry) => entry.data === option.data)) setTarget(option.data as number); }} />
    <DropdownItem label="Minimum power" rgOptions={watts} selectedOption={minimum ?? undefined} disabled={locked} onChange={(option) => { if (watts.some((entry) => entry.data === option.data)) setMinimum(option.data as number); }} />
    <DropdownItem label="Maximum power" rgOptions={watts} selectedOption={maximum ?? undefined} disabled={locked} onChange={(option) => { if (watts.some((entry) => entry.data === option.data)) setMaximum(option.data as number); }} />
    {!valid && manual?.ready && <PanelSectionRow>Choose a range that includes the last checked limit of {manual.current_watts} W.</PanelSectionRow>}
    <PanelSectionRow><ButtonItem layout="below" disabled={locked || !status?.can_start || !valid} onClick={() => { if (!locked && status?.can_start && valid && minimum !== null && maximum !== null) void controller.start(target, minimum, maximum); }}>Start Auto TDP</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={stopping || status?.stopping === true} onClick={() => void controller.stop()}>Stop Auto TDP</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void controller.refresh()}>Refresh Auto TDP</ButtonItem></PanelSectionRow>
    <PanelSectionRow><span style={{ fontSize: "12px", opacity: 0.75 }}>Stop keeps the current limit. Restore returns to saved settings. Manual Apply or Restore stops Auto TDP. Closing this panel keeps Auto TDP running.</span></PanelSectionRow>
    <PanelSectionRow><ToggleField label="Show saved mode preferences" checked={preferencesVisible} onChange={setPreferencesVisible} /></PanelSectionRow>
    {preferencesVisible && <AutoTdpPreferencesControls target={target} minimum={minimum} maximum={maximum} canSave={!locked && valid} onLoad={row => { if (!locked) { setTarget(row.target_fps); setMinimum(row.minimum_watts); setMaximum(row.maximum_watts); } }} />}
    <PanelSectionRow><ToggleField label="Show collection benchmark" checked={benchmarkVisible} onChange={setBenchmarkVisible} /></PanelSectionRow>
    {benchmarkVisible && <TdpBenchmarkControls ready={manual?.ready === true && !manualBusy && !busy} autoRunning={status?.running === true} />}
  </>;
}
