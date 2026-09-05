import { useSyncExternalStore, useEffect, useReducer } from "react";
import { ConfirmModal, showModal } from "@decky/ui";
import { createLiveStatusStore } from "./connection-live-status";
type Store = ReturnType<typeof createLiveStatusStore>;
function LivePanel({store, close, switchTv}: {store: Store; close(): void; switchTv?: () => void}) {
  const source = useSyncExternalStore(store.subscribe, store.get);
  const [, tick] = useReducer((value: number) => value + 1, 0);
  useEffect(() => { const timer = setInterval(tick, 1000); return () => clearInterval(timer); }, []);
  const status = Date.now() < source.expiresAt ? source : {...source, canSwitch:false,
    title:"Waiting for a fresh status update", rows:source.rows.map(row => ({...row, state:"waiting" as const}))};
  return <ConfirmModal strTitle="G1 connection progress" strOKButtonText={status.canSwitch && switchTv ? "Switch to TV" : "Hide"} strCancelButtonText="Hide" bAlertDialog={!status.canSwitch || !switchTv} bDisableBackgroundDismiss={true} bHideCloseIcon={true}
    onOK={() => { const latest = store.get(); const ready = latest.canSwitch && Date.now() < latest.expiresAt; close(); if (ready) switchTv?.(); }} onCancel={close}>
    <div aria-live="polite" style={{fontSize:14,lineHeight:"20px"}}><p>{status.title}</p><p>Connection check: {status.seconds} seconds</p>
      {status.rows.map(row => <div key={row.label} style={{display:"flex",justifyContent:"space-between",gap:12,padding:"5px 0"}}>
        <span>{row.label}</span><strong style={{color: row.state === "ready" ? "#78df9c" : row.state === "blocked" ? "#ff8d8d" : "#ffd574"}}>{row.state === "ready" ? "✓ Ready" : row.state === "blocked" ? "! Needs attention" : "… Waiting"}</strong>
      </div>)}<p>Keep the G1 connected. You can hide this window and check progress in Re-Gear.</p>
    </div>
  </ConfirmModal>;
}
export function showConnectionLivePanel(store: Store, switchTv: (() => void) | undefined, onClose: () => void) {
  let modal: ReturnType<typeof showModal>;
  const close = () => { modal.Close(); onClose(); };
  modal = showModal(<LivePanel store={store} switchTv={switchTv} close={close}/>, window, {strTitle:"Re-Gear",bNeverPopOut:true});
  return modal;
}
