import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useEffect, useState } from "react";
import type { TdpStatusPayload } from "../backend";
import { tdpControls, tdpMessage } from "../tdp-ui";
import type { DisplayActionView } from "../display-action";

/** Only device-reported options; the shared request owner rechecks at Apply. */
export function TdpPicker({ status, busy, onApply, onConfigure }: {
  status: TdpStatusPayload | null; busy: boolean;
  onApply(watts: number): void; onConfigure(): void;
}) {
  const [selected, setSelected] = useState<number | null>(status?.current_watts ?? null);
  useEffect(() => setSelected(status?.current_watts ?? null), [status]);
  const options = status?.minimum_watts != null && status.maximum_watts != null
    ? Array.from({ length: status.maximum_watts - status.minimum_watts + 1 }, (_, index) => ({
      data: status.minimum_watts! + index, label: `${status.minimum_watts! + index} W`,
    })) : [];
  const canApply = !busy && tdpControls(status).canApply && options.some(o => o.data === selected);
  return <PanelSection title="TDP limit">
    <PanelSectionRow>{busy ? "Checking power settings…" : tdpMessage(status)}</PanelSectionRow>
    <PanelSectionRow>Configured limit: {status?.current_watts == null ? "Unknown" : `${status.current_watts} W`}</PanelSectionRow>
    <DropdownItem label="Power limit" rgOptions={options} selectedOption={selected ?? undefined}
      disabled={busy || !tdpControls(status).canApply}
      onChange={option => { if (options.some(o => o.data === option.data)) setSelected(option.data as number); }} />
    <PanelSectionRow><ButtonItem layout="below" disabled={!canApply}
      onClick={() => { if (canApply && selected !== null) onApply(selected); }}>Apply limit</ButtonItem></PanelSectionRow>
    <PanelSectionRow><span style={{ fontSize: 12 }}>This is a power limit, not measured use. Applying it stops Auto TDP.</span></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" onClick={onConfigure}>Power configuration</ButtonItem></PanelSectionRow>
  </PanelSection>;
}

export function DisplayPicker({ current, action, onSwitch, onConfigure }: {
  current: string; action: DisplayActionView; onSwitch(): void; onConfigure(): void;
}) {
  return <PanelSection title="Display target">
    <PanelSectionRow>Current: {current}</PanelSectionRow>
    <PanelSectionRow>{action.description}</PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={action.disabled}
      onClick={() => { if (!action.disabled) onSwitch(); }}>{action.title}</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" onClick={onConfigure}>Docking configuration</ButtonItem></PanelSectionRow>
  </PanelSection>;
}
