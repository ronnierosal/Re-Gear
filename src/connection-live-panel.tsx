import { useSyncExternalStore, useEffect, useReducer } from "react";
import { ConfirmModal, showModal } from "@decky/ui";
import { createLiveStatusStore, type Light } from "./connection-live-status";
import { connectionPanelCss } from "./connection-panel-style";
type Store = ReturnType<typeof createLiveStatusStore>;

function Check() {
  return <svg className="rg-connection-check" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="m7 12 3 3 7-7"/></svg>;
}
export function ConnectionIndicator({state, stale}: {state: Light; stale: boolean}) {
  return <span className="rg-connection-icon" aria-hidden="true">{state === "ready" ? <Check/> : state === "blocked" ? "!" : stale ? "○" : <span className="rg-connection-ring"/>}</span>;
}
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
  return <ConfirmModal className="rg-connection-modal" strTitle={title}
    strOKButtonText={status.canSwitch && switchTv ? "Switch to TV" : "Hide"}
    strCancelButtonText="Hide" bAlertDialog={!status.canSwitch || !switchTv}
    bDisableBackgroundDismiss={true} bHideCloseIcon={true}
    onOK={() => { const latest = store.get(); const ready = latest.canSwitch && Date.now() < latest.expiresAt; close(); if (ready) switchTv?.(); }} onCancel={close}>
    <style>{connectionPanelCss}</style>
    <div className="rg-connection">
      <p className="rg-connection-subtitle">{complete ? "Re-Gear reports the TV transition completed." : switching ? "Checking the display and TV audio" : `GPD G1 connection · ${status.seconds} seconds`}</p>
      {complete ? <div className="rg-connection-hero"><Check/></div> : switching ? <div className="rg-connection-sweep" aria-hidden="true"/> :
        <div className="rg-connection-list">{status.rows.map(row => <div key={row.label} className="rg-connection-row">
          <span className="rg-connection-label">{row.label}</span>
          <span className={`rg-connection-state rg-connection-${row.state}`}><ConnectionIndicator state={row.state} stale={stale}/>{row.state === "ready" ? "Ready" : row.state === "blocked" ? "Needs attention" : stale ? "Waiting" : "Checking"}</span>
        </div>)}</div>}
      <p className="rg-connection-detail" role="status">{complete ? "Check the TV picture and sound. Closing automatically…" : status.title}</p>
      <p className="rg-connection-foot">Keep G1 connected. Hiding this window does not cancel docking.</p>
    </div>
  </ConfirmModal>;
}
export function showConnectionLivePanel(store: Store, switchTv: (() => void) | undefined, onClose: () => void) {
  let modal: ReturnType<typeof showModal>;
  const close = () => { modal.Close(); onClose(); };
  modal = showModal(<LivePanel store={store} switchTv={switchTv} close={close}/>, window, {strTitle:"Re-Gear",bNeverPopOut:true});
  return modal;
}
