import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import { tdpControls, tdpMessage, tdpResultMessage } from "./tdp-ui";
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
  const { manual: status, busy } = controller;
  useEffect(() => { setSelected(status?.current_watts ?? null); }, [status]);
  const controls = tdpControls(status);
  const options = status?.minimum_watts != null && status.maximum_watts != null
    ? Array.from({ length: status.maximum_watts - status.minimum_watts + 1 }, (_, index) => ({ data: status.minimum_watts! + index, label: `${status.minimum_watts! + index} W` })) : [];
  if (!visible) return null;
  return <PanelSection title="Handheld power">
    {!initiallyExpanded && <PanelSectionRow><ButtonItem layout="below" onClick={() => setExpanded(value => !value)}>{expanded ? "Hide power controls" : "Show power controls"}</ButtonItem></PanelSectionRow>}
    {expanded && <>
      <PanelSectionRow>{busy ? "Checking power settings…" : tdpMessage(status)}</PanelSectionRow>
      {!busy && tdpResultMessage(status) && <PanelSectionRow>Last request: {tdpResultMessage(status)}</PanelSectionRow>}
      <PanelSectionRow>{status?.current_watts != null ? `Last checked limit: ${status.current_watts} W` : "Last checked limit: unavailable"}</PanelSectionRow>
      <PanelSectionRow><span style={{ fontSize: "12px", opacity: 0.75 }}>This is the configured limit, not measured power use. Enable only after resolving other power controllers.</span></PanelSectionRow>
      <ToggleField label="Use Re-Gear power control" checked={status?.enabled ?? false} disabled={busy || !controls.canToggle} onChange={(enabled) => { void controller.setEnabled(enabled); }} />
      <DropdownItem label="Power limit" rgOptions={options} selectedOption={selected ?? undefined} disabled={busy || !controls.canApply} onChange={(option) => { if (options.some(entry => entry.data === option.data)) setSelected(option.data as number); }} />
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || !controls.canApply || selected === null} onClick={() => { if (selected !== null) void controller.apply(selected); }}>Apply power limit</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || !controls.canRestore} onClick={() => { void controller.restore(); }}>Restore previous power settings</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => { void controller.refresh(); }}>Refresh power settings</ButtonItem></PanelSectionRow>
      {!initiallyExpanded && <PanelSectionRow><ButtonItem layout="below" onClick={() => setAutoExpanded(value => !value)}>{autoExpanded ? "Hide Auto TDP" : "Show Auto TDP"}</ButtonItem></PanelSectionRow>}
      {autoExpanded && <AutoTdpControls controller={controller} />}
    </>}
  </PanelSection>;
}
