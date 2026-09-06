import { ButtonItem, PanelSectionRow } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { cancelTdpBenchmark, getTdpBenchmarkStatus, runTdpBenchmark, type TdpBenchmarkStatus } from "./backend";
import { AutoTdpRequestGate } from "./auto-tdp-ui";
import { sanitizeTdpBenchmark, tdpBenchmarkMessage } from "./tdp-benchmark-ui";

export function TdpBenchmarkControls({ ready, autoRunning }: { ready: boolean; autoRunning: boolean }) {
  const [status, setStatus] = useState<TdpBenchmarkStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [runPending, setRunPending] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const mounted = useRef(true);
  const gate = useRef(new AutoTdpRequestGate());
  const request = async (kind: "read" | "run" | "cancel") => {
    const token = gate.current.begin(kind === "cancel");
    if (token === null) return;
    setBusy(true); setCancelling(kind === "cancel");
    if (kind === "run") setRunPending(true);
    try {
      const result = await (kind === "run" ? runTdpBenchmark() : kind === "cancel" ? cancelTdpBenchmark() : getTdpBenchmarkStatus());
      if (mounted.current && gate.current.current(token)) setStatus(sanitizeTdpBenchmark(result));
    } catch {
      if (mounted.current && gate.current.current(token)) setStatus(null);
    } finally {
      if (mounted.current) {
        if (kind === "run") setRunPending(false);
        if (gate.current.current(token)) { setBusy(false); setCancelling(false); }
      }
      gate.current.finish(token);
    }
  };
  useEffect(() => {
    mounted.current = true;
    void request("read");
    return () => { mounted.current = false; gate.current.invalidate(); };
  }, []);
  const result = status?.result;
  return <>
    <PanelSectionRow><strong>Collection benchmark</strong></PanelSectionRow>
    <PanelSectionRow>{cancelling ? "Requesting cancellation…" : runPending && busy ? "Measuring frame and sensor collection…" : tdpBenchmarkMessage(status)}</PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy || runPending || !ready || autoRunning || status?.running === true} onClick={() => void request("run")}>Run benchmark</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={cancelling} onClick={() => void request("cancel")}>Cancel benchmark</ButtonItem></PanelSectionRow>
    <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void request("read")}>Refresh benchmark</ButtonItem></PanelSectionRow>
    {result && <PanelSectionRow>
      Last benchmark: {result.usable_samples} usable samples from {result.attempts} attempts.<br />
      Longest collection and recheck: {result.maximum_collection_and_revalidation_ms === null ? "unavailable" : `${result.maximum_collection_and_revalidation_ms} ms`}.<br />
      Sample interval: {result.interval_ms} ms. Elapsed: {(result.elapsed_ms / 1000).toFixed(1)} seconds.
    </PanelSectionRow>}
    <PanelSectionRow><span style={{ fontSize: "12px", opacity: 0.75 }}>Measures collection time while a game runs. Power settings stay unchanged. Closing this panel lets the benchmark finish; use Cancel to stop it. Results require review before Auto TDP can use them.</span></PanelSectionRow>
  </>;
}
