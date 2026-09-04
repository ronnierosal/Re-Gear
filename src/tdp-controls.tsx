import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { applyTdpLimit, getTdpStatus, restoreTdpLimit, setTdpEnabled, type TdpStatusPayload } from "./backend";
import { sanitizeTdpStatus, tdpControls, tdpMessage, tdpResultMessage, TdpRequestGate } from "./tdp-ui";
import { AutoTdpControls } from "./auto-tdp-controls";

export function TdpControls({ visible }: { visible: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const [autoExpanded, setAutoExpanded] = useState(false);
  const [status, setStatus] = useState<TdpStatusPayload | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const gate = useRef(new TdpRequestGate());
  const showing = useRef(false);
  showing.current = visible && expanded;
  const mounted = useRef(true);

  const request = (action: () => Promise<unknown>) => gate.current.run(async () => {
    if (!showing.current) return;
    setBusy(true);
    try {
      const next = sanitizeTdpStatus(await action());
      if (mounted.current && showing.current) {
        setStatus(next);
        setSelected(next?.current_watts ?? null);
      }
    } catch {
      if (mounted.current) { setStatus(null); setSelected(null); }
    } finally {
      if (mounted.current) setBusy(false);
    }
  });

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    if (!visible) { setExpanded(false); setAutoExpanded(false); setStatus(null); setSelected(null); }
  }, [visible]);
  useEffect(() => {
    if (visible && expanded) void request(getTdpStatus);
    // Visibility/expansion owns the only automatic refresh. No polling timer.
  }, [visible, expanded]);

  const controls = tdpControls(status);
  const options = status?.minimum_watts != null && status.maximum_watts != null
    ? Array.from({ length: status.maximum_watts - status.minimum_watts + 1 }, (_, index) => ({ data: status.minimum_watts! + index, label: `${status.minimum_watts! + index} W` }))
    : [];

  return <PanelSection title="Handheld power">
    <PanelSectionRow>
      <ButtonItem layout="below" disabled={busy} onClick={() => { setStatus(null); setSelected(null); setAutoExpanded(false); setExpanded((value) => !value); }}>
        {expanded ? "Hide power controls" : "Show power controls"}
      </ButtonItem>
    </PanelSectionRow>
    {visible && expanded && <>
      <PanelSectionRow>{busy ? "Checking power settings…" : tdpMessage(status)}</PanelSectionRow>
      {!busy && tdpResultMessage(status) && <PanelSectionRow>Last request: {tdpResultMessage(status)}</PanelSectionRow>}
      <PanelSectionRow>{status?.current_watts != null ? `Last checked limit: ${status.current_watts} W` : "Last checked limit: unavailable"}</PanelSectionRow>
      <PanelSectionRow><span style={{ fontSize: "12px", opacity: 0.75 }}>This is the configured limit, not measured power use. Enable only after resolving other power controllers.</span></PanelSectionRow>
      <ToggleField label="Use Re-Gear power control" checked={status?.enabled ?? false} disabled={busy || !controls.canToggle} onChange={(enabled) => { if (controls.canToggle) void request(() => setTdpEnabled(enabled)); }} />
      <DropdownItem label="Power limit" rgOptions={options} selectedOption={selected ?? undefined} disabled={busy || !controls.canApply} onChange={(option) => { if (options.some((entry) => entry.data === option.data)) setSelected(option.data as number); }} />
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || !controls.canApply || selected === null} onClick={() => { if (controls.canApply && selected !== null) void request(() => applyTdpLimit(selected)); }}>Apply power limit</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || !controls.canRestore} onClick={() => { if (controls.canRestore) void request(restoreTdpLimit); }}>Restore previous power settings</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void request(getTdpStatus)}>Refresh power settings</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" onClick={() => setAutoExpanded((value) => !value)}>{autoExpanded ? "Hide Auto TDP" : "Show Auto TDP"}</ButtonItem></PanelSectionRow>
      {autoExpanded && <AutoTdpControls manual={status} manualBusy={busy} manualMessage={tdpMessage(status)} onChanged={() => { void request(getTdpStatus); }} />}
    </>}
  </PanelSection>;
}
