import { ConnectionProgressOverlay } from "./connection-progress-overlay";
import { connectionProgressViewModel } from "./connection-progress-model";
import { useSyncExternalStore, useEffect, useReducer, useRef } from "react";
import { Focusable, ModalRoot, showModal } from "@decky/ui";
import { createLiveStatusStore } from "./connection-live-status";
import { connectionPanelCss } from "./connection-panel-style";
type Store = ReturnType<typeof createLiveStatusStore>;

export function LivePanel({store, close, switchTv}: {store: Store; close(): void; switchTv?: () => void}) {
  const source = useSyncExternalStore(store.subscribe, store.get);
  const [, tick] = useReducer((value: number) => value + 1, 0);
  useEffect(() => { const timer = setInterval(tick, 1000); return () => clearInterval(timer); }, []);
  const stale = Date.now() >= source.expiresAt;
  const status = stale ? {...source, phase:"checking" as const, canSwitch:false,
    title:"Waiting for a fresh status update", rows:source.rows.map(row => ({...row, state:"waiting" as const}))} : source;
  const lastInteraction = useRef(0);
  const panel = useRef<HTMLDivElement>(null);
  const complete = status.phase === "complete";
  const interacted = () => {lastInteraction.current=Date.now();};

  useEffect(() => {
    if (!complete) return;
    let timer: ReturnType<typeof setTimeout>;
    const finish = () => {
      const latest = store.get();
      if (latest.phase !== "complete" || Date.now() >= latest.expiresAt) return;
      if (Date.now() - lastInteraction.current < 3500 || panel.current?.querySelector("details[open]")) {
        timer = setTimeout(finish, 500); return;
      }
      close();
    };
    timer = setTimeout(finish, 3500);
    return () => clearTimeout(timer);
  }, [complete, store, close]);
  const switchAction = status.canSwitch && switchTv ? () => {
    const latest = store.get();
    if (latest.canSwitch && Date.now() < latest.expiresAt) { close(); switchTv(); }
  } : undefined;
  return <ModalRoot className="rg-popup-host" onCancel={close} closeModal={close}
    bDisableBackgroundDismiss={true} bHideCloseIcon={true}>
    <style>{connectionPanelCss}</style>
    <Focusable ref={panel} onPointerDownCapture={interacted} onKeyDownCapture={interacted}
      onFocusCapture={interacted} onGamepadFocus={interacted} onGamepadDirection={interacted} onButtonDown={interacted}>
    <ConnectionProgressOverlay {...connectionProgressViewModel(status)} onHide={close} onSwitch={switchAction} />
    </Focusable>
  </ModalRoot>;
}
export function showConnectionLivePanel(store: Store, switchTv: (() => void) | undefined, onClose: () => void) {
  let modal: ReturnType<typeof showModal>;
  const close = () => { modal.Close(); onClose(); };
  modal = showModal(<LivePanel store={store} switchTv={switchTv} close={close}/>, window, {strTitle:"Re-Gear",bNeverPopOut:true});
  return modal;
}
