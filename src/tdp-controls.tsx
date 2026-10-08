import { ReadableBlock } from "./quick-access/readable-block";
import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import { tdpControls, tdpMessage, tdpResultMessage, manualPresetOptions, type ManualPresetIntent } from "./tdp-ui";
import { AutoTdpControls } from "./auto-tdp-controls";
import { usePerformance, type PerformanceHandle } from "./quick-access/use-performance";

export function TdpControls({ visible, controller, expanded = false }: { visible: boolean; controller?: PerformanceHandle; expanded?: boolean }) {
  return controller ? <SharedTdpControls visible={visible} controller={controller} initiallyExpanded={expanded} />
    : <StandaloneTdpControls visible={visible} />;
}
function StandaloneTdpControls({ visible }: { visible: boolean }) {
  const controller = usePerformance(visible);
  return <SharedTdpControls visible={visible} controller={controller} />;
}
function SharedTdpControls({ visible, controller, initiallyExpanded = false }: { visible: boolean; controller: PerformanceHandle; initiallyExpanded?: boolean }) {
  const [expanded, setExpanded] = useState(initiallyExpanded);
  const [autoExpanded, setAutoExpanded] = useState(initiallyExpanded);
  const [selected, setSelected] = useState<number | null>(null);
  const [preset, setPreset] = useState<ManualPresetIntent | null>(null);
  const { manual: status, auto, busy } = controller;
  useEffect(() => { setSelected(status?.current_watts ?? null); setPreset(null); }, [status, visible]);
  const controls = tdpControls(status);
  const manualLocked = auto?.running === true || auto?.stopping === true || controller.stopping;
  const presets = manualPresetOptions(status);
  const canMutate = () => visible && !controller.busy && !controller.stopping
    && controller.auto?.running !== true && controller.auto?.stopping !== true;
  const presetValid = preset === null || (preset.status === status
    && presets.some(option => option.id === preset.id && option.watts === selected && option.admitted));
  const options = status?.minimum_watts != null && status.maximum_watts != null
    ? Array.from({ length: status.maximum_watts - status.minimum_watts + 1 }, (_, index) => ({ data: status.minimum_watts! + index, label: `${status.minimum_watts! + index} W` })) : [];
  if (!visible) return null;
  return <PanelSection title="Handheld power">
    {!initiallyExpanded && <PanelSectionRow><ButtonItem layout="below" onClick={() => setExpanded(value => !value)}>{expanded ? "Hide power controls" : "Show power controls"}</ButtonItem></PanelSectionRow>}
    {expanded && <>
      <ReadableBlock label="Power status"><PanelSectionRow>{busy ? "Checking power settings…" : tdpMessage(status)}</PanelSectionRow>
      {!busy && tdpResultMessage(status) && <PanelSectionRow>Last request: {tdpResultMessage(status)}</PanelSectionRow>}
      <PanelSectionRow>{status?.current_watts != null ? `Last checked limit: ${status.current_watts} W` : "Last checked limit: unavailable"}</PanelSectionRow></ReadableBlock>
      <ReadableBlock label="Power status and guidance"><PanelSectionRow><span style={{ fontSize: "12px", opacity: 0.75 }}>This is the configured limit, not measured power use. Enable only after resolving other power controllers.</span></PanelSectionRow></ReadableBlock>
      {manualLocked && <ReadableBlock label="Power status and guidance"><PanelSectionRow><span style={{ fontSize: "12px", opacity: 0.75 }}>Stop Auto TDP to adjust manually.</span></PanelSectionRow></ReadableBlock>}
      <ToggleField label="Use Re-Gear power control" checked={status?.enabled ?? false} disabled={busy || manualLocked || !controls.canToggle} onChange={(enabled) => { if (canMutate() && tdpControls(controller.manual).canToggle && (!enabled || controller.manual?.can_enable)) void controller.setEnabled(enabled); }} />
      <ReadableBlock label="Power presets"><PanelSectionRow><span style={{ fontSize: "12px", opacity: 0.75 }}>Choose a preset, then Apply. These are configured limits, not measured power use.</span></PanelSectionRow></ReadableBlock>
      {presets.map(option => <PanelSectionRow key={option.id}><ButtonItem layout="below"
        disabled={busy || manualLocked || !option.admitted}
        onClick={() => {
          if (canMutate() && status === controller.manual
            && manualPresetOptions(controller.manual).some(current => current.id === option.id && current.admitted)) {
            setSelected(option.watts); setPreset({ id: option.id, status: status! });
          }
        }}>{`${option.label} · ${option.watts} W${preset?.status === status && preset.id === option.id ? " (selected)" : ""}`}</ButtonItem></PanelSectionRow>)}
      <DropdownItem label="Power limit" rgOptions={options} selectedOption={selected ?? undefined} disabled={busy || manualLocked || !controls.canApply} onChange={(option) => { if (canMutate() && tdpControls(controller.manual).canApply && options.some(entry => entry.data === option.data)) { setSelected(option.data as number); setPreset(null); } }} />
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || manualLocked || !controls.canApply || selected === null || !presetValid} onClick={() => { if (canMutate() && selected !== null && tdpControls(controller.manual).canApply
        && options.some(option => option.data === selected)
        && (preset === null || (preset.status === controller.manual
          && manualPresetOptions(controller.manual).some(option => option.id === preset.id && option.watts === selected && option.admitted)))) {
        void controller.apply(selected, preset ?? undefined);
      } }}>Apply power limit</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || manualLocked || !controls.canRestore} onClick={() => { if (canMutate() && tdpControls(controller.manual).canRestore) void controller.restore(); }}>Restore previous power settings</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => { void controller.refresh(); }}>Refresh power settings</ButtonItem></PanelSectionRow>
      {!initiallyExpanded && <PanelSectionRow><ButtonItem layout="below" onClick={() => setAutoExpanded(value => !value)}>{autoExpanded ? "Hide Auto TDP" : "Show Auto TDP"}</ButtonItem></PanelSectionRow>}
      {autoExpanded && <AutoTdpControls controller={controller} />}
    </>}
  </PanelSection>;
}
