import { ButtonItem, DropdownItem, PanelSectionRow, ToggleField } from "@decky/ui";
import { TdpBenchmarkControls } from "./tdp-benchmark-controls";
import { useEffect, useRef, useState } from "react";
import { getAutoTdpStatus, startAutoTdp, stopAutoTdp, type AutoTdpStatusPayload, type TdpStatusPayload } from "./backend";
import { autoTdpActivity, autoTdpMessage, AutoTdpRequestGate, sanitizeAutoTdpStatus, validAutoTdpRange } from "./auto-tdp-ui";

export function AutoTdpControls({ manual, manualBusy, manualMessage, onChanged }: {
  manual: TdpStatusPayload | null; manualBusy: boolean; manualMessage: string; onChanged: () => void;
}) {
  const [status, setStatus] = useState<AutoTdpStatusPayload | null>(null);
  const [target, setTarget] = useState(60);
  const [minimum, setMinimum] = useState<number | null>(null);
  const [maximum, setMaximum] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [benchmarkVisible, setBenchmarkVisible] = useState(false);
  const mounted = useRef(true);
  const gate = useRef(new AutoTdpRequestGate());
  const pendingRefresh = useRef(false);
  const request = async (action: () => Promise<unknown>, kind: "read" | "start" | "stop" = "read") => {
    const generation = gate.current.begin(kind === "stop");
    if (generation === null) return;
    setBusy(true); setStopping(kind === "stop");
    try {
      const next = sanitizeAutoTdpStatus(await action());
      if (mounted.current && gate.current.current(generation)) {
        setStatus(next);
        if (next?.target_fps != null) {
          setTarget(next.target_fps); setMinimum(next.minimum_watts); setMaximum(next.maximum_watts);
        }
        if (kind !== "read") onChanged();
      }
    } catch {
      if (mounted.current && gate.current.current(generation)) setStatus(null);
    } finally {
      if (mounted.current && gate.current.current(generation)) { setBusy(false); setStopping(false); }
      gate.current.finish(generation);
      if (mounted.current && gate.current.current(generation) && pendingRefresh.current) {
        pendingRefresh.current = false;
        void request(getAutoTdpStatus);
      }
    }
  };
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; gate.current.invalidate(); };
  }, []);
  useEffect(() => {
    if (manual?.minimum_watts != null && manual.maximum_watts != null) {
      setMinimum((value) => value === null || value < manual.minimum_watts! || value > manual.maximum_watts! ? manual.minimum_watts : value);
      setMaximum((value) => value === null || value < manual.minimum_watts! || value > manual.maximum_watts! ? manual.maximum_watts : value);
    }
    if (gate.current.busy) pendingRefresh.current = true;
    else void request(getAutoTdpStatus);
    // On-demand only: manual state changes and explicit Refresh, never a timer.
  }, [manual]);
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
    <PanelSectionRow><ButtonItem layout="below" disabled={locked || !status?.can_start || !valid} onClick={() => { if (!locked && status?.can_start && valid && minimum !== null && maximum !== null) void request(() => startAutoTdp(target, minimum, maximum), "start"); }}>Start Auto TDP</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={stopping} onClick={() => void request(stopAutoTdp, "stop")}>Stop Auto TDP</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void request(getAutoTdpStatus)}>Refresh Auto TDP</ButtonItem></PanelSectionRow>
    <PanelSectionRow><span style={{ fontSize: "12px", opacity: 0.75 }}>Stop keeps the current limit. Restore returns to saved settings. Manual Apply or Restore stops Auto TDP. Closing this panel keeps Auto TDP running.</span></PanelSectionRow>
    <PanelSectionRow><ToggleField label="Show collection benchmark" checked={benchmarkVisible} onChange={setBenchmarkVisible} /></PanelSectionRow>
    {benchmarkVisible && <TdpBenchmarkControls ready={manual?.ready === true && !manualBusy && !busy} autoRunning={status?.running === true} />}
  </>;
}
