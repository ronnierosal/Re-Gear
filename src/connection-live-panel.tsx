import { ReadinessRow, StatusIcon } from "./readiness-row";
import { useSyncExternalStore, useEffect, useReducer } from "react";
import { ConfirmModal, showModal } from "@decky/ui";
import { createLiveStatusStore } from "./connection-live-status";
import { connectionPanelCss } from "./connection-panel-style";
type Store = ReturnType<typeof createLiveStatusStore>;

function LivePanel({store, close, switchTv}: {store: Store; close(): void; switchTv?: () => void}) {
  const source = useSyncExternalStore(store.subscribe, store.get);
  const [, tick] = useReducer((value: number) => value + 1, 0);
  useEffect(() => { const timer = setInterval(tick, 1000); return () => clearInterval(timer); }, []);
  const stale = Date.now() >= source.expiresAt;
  const status = stale ? {...source, phase:"checking" as const, canSwitch:false,
    title:"Waiting for a fresh status update", rows:source.rows.map(row => ({...row, state:"waiting" as const}))} : source;
  const complete = status.phase === "complete";
  const switching = status.phase === "switching";
  useEffect(() => {
    if (!complete) return;
    const timer = setTimeout(() => {
      const latest = store.get();
      if (latest.phase === "complete" && Date.now() < latest.expiresAt) close();
    }, 3500);
    return () => clearTimeout(timer);
  }, [complete, store, close]);
  const title = complete ? "TV connection complete" : switching ? "Switching to TV" : "Getting your TV ready";
  return <ConfirmModal className="rg-connection-modal" strTitle={<span style={{fontSize:20,lineHeight:1.2}}>{title}</span>}
    strOKButtonText={status.canSwitch && switchTv ? "Switch to TV" : "Hide"}
    strCancelButtonText="Hide" bAlertDialog={!status.canSwitch || !switchTv}
    bDisableBackgroundDismiss={true} bHideCloseIcon={true}
    onOK={() => { const latest = store.get(); const ready = latest.canSwitch && Date.now() < latest.expiresAt; close(); if (ready) switchTv?.(); }} onCancel={close}>
    <style>{connectionPanelCss}</style>
    <div className="rg-connection">
      <p className="rg-connection-subtitle">{complete ? "Re-Gear reports the TV transition completed." : switching ? "Checking the display and TV audio" : `GPD G1 connection · ${status.seconds} seconds`}</p>
      {complete ? <div className="rg-connection-hero"><StatusIcon state="ready"/></div> : switching ? <div className="rg-connection-sweep" aria-hidden="true"/> :
        <div className="rg-connection-list">{status.rows.map(row => <ReadinessRow key={row.label} label={row.label}
          state={row.state === "waiting" && !stale ? "checking" : row.state}/>)}</div>}
      <p className="rg-connection-detail" role="status">{complete ? "Check the TV picture and sound. Closing automatically…" : status.title}</p>
      <p className="rg-connection-foot">Keep G1 connected · Hide keeps docking active.</p>
    </div>
  </ConfirmModal>;
}
export function showConnectionLivePanel(store: Store, switchTv: (() => void) | undefined, onClose: () => void) {
  let modal: ReturnType<typeof showModal>;
  const close = () => { modal.Close(); onClose(); };
  modal = showModal(<LivePanel store={store} switchTv={switchTv} close={close}/>, window, {strTitle:"Re-Gear",bNeverPopOut:true});
  return modal;
}
