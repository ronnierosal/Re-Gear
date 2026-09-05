import { DialogButton } from "@decky/ui";
import { useSyncExternalStore, useEffect, useReducer } from "react";
import type { createLiveStatusStore } from "./connection-live-status";
import { ReadinessRow } from "./readiness-row";
import { connectionPanelCss } from "./connection-panel-style";
import { regearTheme as theme } from "./regear-theme";

const labels: Record<string, string> = {
  "GPU and driver": "GPU driver",
  "Connection link": "Connection link",
  "TV HDMI detected": "TV HDMI",
  "Audio recovery ready": "Audio recovery",
  "No game running": "No game running",
};

/** Shares the popup monitor; never starts another backend read. */
export function ConnectionQuickStatus({store, visible, onOpen}: {
  store: ReturnType<typeof createLiveStatusStore>; visible: boolean; onOpen(): void;
}) {
  const source = useSyncExternalStore(store.subscribe, store.get);
  const [, tick] = useReducer((value: number) => value + 1, 0);
  useEffect(() => {
    if (!visible) return;
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [visible]);
  const stale = Date.now() >= source.expiresAt;
  return <div aria-label="Live G1 readiness" style={{background:theme.surface, border:`1px solid ${theme.border}`, borderRadius:14, padding:"10px 12px", color:theme.text}}>
    <style>{connectionPanelCss}</style>
    <div style={{fontSize:13, lineHeight:1.4, color:theme.muted, marginBottom:6}} role="status">
      {stale ? "Waiting for a fresh status update" : source.title}
    </div>
    <div>{source.rows.filter(row => labels[row.label]).map(row => {
      const state = stale ? "waiting" : row.state;
      return <ReadinessRow key={row.label} label={labels[row.label]} compact
        state={state === "waiting" && !stale && visible ? "checking" : state}/>;
    })}</div>
    <DialogButton className="rg-dashboard-action" onClick={onOpen}
      style={{width:"100%", minWidth:0, height:"auto", padding:"9px 8px", marginTop:10,
        border:`1px solid ${theme.border}`, borderRadius:9, background:"transparent",
        color:theme.accentSoft, fontSize:13, lineHeight:1.4}}>
      View full progress
    </DialogButton>
  </div>;
}
