import { ConnectionProgressOverlay } from "./connection-progress-overlay";
import { connectionProgressViewModel } from "./connection-progress-model";
import { useSyncExternalStore, useEffect, useReducer, useRef } from "react";
import { Focusable, ModalRoot, showModal } from "@decky/ui";
import { createLiveStatusStore } from "./connection-live-status";
import { connectionPanelCss } from "./connection-panel-style";
import { LinkRecoveryControl } from "./link-recovery-control";
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
  const hiding = useRef(false);
  const hideAnimation = useRef<Animation | null>(null);
  useEffect(()=>()=>{hideAnimation.current?.cancel();},[]);
  const complete = status.phase === "complete";
  const interacted = () => {lastInteraction.current=Date.now();};
  const toggleDetails = () => {
    interacted();
    const details=panel.current?.querySelector("details");
    if(details) details.open=!details.open;
  };
  const hide = () => {
    if(hiding.current) return;
    hiding.current=true;
    const card=panel.current?.querySelector<HTMLElement>(".rg-popup");
    if(!card?.animate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {close();return;}
    const animation=card.animate([{opacity:1,transform:"translateY(0)"},{opacity:0,transform:"translateY(4px)"}],{duration:140,easing:"ease-in",fill:"forwards"});
    hideAnimation.current=animation;
    animation.onfinish=close;
  };

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
  return <ModalRoot className="rg-popup-host" onCancel={hide} closeModal={close}
    bDisableBackgroundDismiss={true} bHideCloseIcon={true}>
    <style>{connectionPanelCss}</style>
    <Focusable ref={panel} onPointerDownCapture={interacted} onKeyDownCapture={interacted}
      onFocusCapture={interacted} onGamepadFocus={interacted} onGamepadDirection={interacted} onButtonDown={interacted}
      onOptionsButton={toggleDetails} onOptionsActionDescription="Connection details">
    <ConnectionProgressOverlay {...connectionProgressViewModel(status)} onHide={hide} onSwitch={switchAction}
      recoveryAction={<LinkRecoveryControl eligible={!stale && source.connected
        && source.phase === "checking" && source.seconds >= 120
        && source.rows.some(row => row.label === "GPU and driver" && row.state === "waiting")
        && source.rows.some(row => row.label === "No game running" && row.state === "ready")} />} />
    </Focusable>
  </ModalRoot>;
}
export function showConnectionLivePanel(store: Store, switchTv: (() => void) | undefined, onClose: () => void) {
  let modal: ReturnType<typeof showModal>;
  let closed=false;
  const close = () => { if(closed)return;closed=true;modal.Close();onClose(); };
  modal = showModal(<LivePanel store={store} switchTv={switchTv} close={close}/>, window, {strTitle:"Re-Gear",bNeverPopOut:true});
  return modal;
}
