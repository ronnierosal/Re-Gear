import { callable } from "@decky/api";
import { DialogButton, showModal } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { EgpuConfirmModal } from "./egpu-confirm-modal";
import { dockIntentControl, dockRequestAbandoned, dockRequestSettled, formatPendingRecord, parsePendingRecord,
  type DockAction, type DockIntent } from "./whole-dock-control-model";

const readTrial = callable<[string], any>("get_egpu_disconnect_status");
const execute = callable<[boolean, string, string, DockAction, boolean, string, string], any>("execute_egpu_disconnect");
const pendingKey = "regear.whole-dock.pending-request";
/** Identifies this panel for the life of its script, which is exactly the
 * lifetime that matters: freeing the dock restarts Gaming Mode and a new
 * panel loads with a new one, which is how a record left by the panel that
 * did not survive is told apart from one this panel is still waiting on. */
const panelId = (() => { try { return crypto.randomUUID().replaceAll("-", ""); } catch { return "panel"; } })();
const pendingRecord = () => { try { return window.localStorage.getItem(pendingKey); } catch { return "storage-unavailable"; } };
const pendingRequest = () => parsePendingRecord(pendingRecord())?.request;

export type DirectStartRequest = (() => boolean) & {
  state(): "available" | "consumed" | "submitted";
  markSubmitted(): void;
};
export type DockSettlement = { intent: DockIntent; request: string };
const directStartState = (startRequest: boolean | (() => boolean) | DirectStartRequest | undefined) =>
  typeof startRequest === "function" && "state" in startRequest ? startRequest.state() : null;

/** Only confirmed clicks mutate. Reopening the menu recovers backend progress. */
export function WholeDockControl({ readCurrentSnapshot, intent = "disconnect_only", startRequest, statusOnly = false, onSettled }: { readCurrentSnapshot: () => any; intent?: DockIntent; startRequest?: boolean | (()=>boolean) | DirectStartRequest; statusOnly?: boolean; onSettled?: (settlement: DockSettlement) => void }) {
  const source = useRef(readCurrentSnapshot);
  source.current = readCurrentSnapshot;
  const currentIntent = useRef(intent);
  currentIntent.current = intent;
  const read = async () => ({ status: await readTrial("whole_dock_trial"), snapshot: source.current() });
  const [reading, setReading] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [initialNotStarted, setInitialNotStarted] = useState(directStartState(startRequest) === "consumed");
  const mounted = useRef(true);
  const pending = useRef(false);
  const uncertain = useRef(!!pendingRequest());
  const epoch = useRef(0);
  const modal = useRef<ReturnType<typeof showModal> | null>(null);
  const startConsumed = useRef(false);
  const consumeStartRequest = () => {
    if (!startRequest || startConsumed.current) return false;
    if (typeof startRequest === "function" && !startRequest()) return false;
    startConsumed.current = true;
    return true;
  };
  useEffect(() => {
    mounted.current = true;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      const started = epoch.current;
      try {
        const next = await read();
        if (disposed) return;
        if (started !== epoch.current) { timer = setTimeout(refresh, 2000); return; }
        const record = parsePendingRecord(pendingRecord());
        // Retiring a record whose answer never arrived is not the same as the
        // request having succeeded, so the player is told which happened
        // rather than left to infer it from the control becoming usable.
        const abandoned = dockRequestAbandoned(next.status, record, panelId);
        const settled = !!record && dockRequestSettled(next.status, record.request, record.intent);
        if (record && (abandoned || settled)) {
          // A correlated terminal result must survive a Gamescope/Decky
          // replacement until the replacement panel has actually presented
          // it. The native wrapper acknowledges it only when the player
          // dismisses that status surface. Standalone controls retain the
          // historical immediate retirement behavior.
          // The callback transfers receipt acknowledgement to the native
          // status popup. It also covers an abandoned/unconfirmed answer: the
          // popup must survive long enough to tell the player that result.
          if (onSettled) onSettled({ intent: record.intent, request: record.request });
          else window.localStorage.removeItem(pendingKey);
          uncertain.current = false;
          if (abandoned && mounted.current) {
            setNotice("Re-Gear could not confirm how the previous request ended, so it stopped waiting. Check the status below before trying again. Keep the cable connected.");
          }
        }
        setReading(next);
        if(consumeStartRequest()) {
          const initial = dockIntentControl(next.status,next.snapshot,intent);
          if (!initial.action && !uncertain.current && !pendingRequest()) {
            setInitialNotStarted(true);
          } else confirm(true,next);
        }
      } catch { if (!disposed && started === epoch.current) {
        setReading(null);
        if (consumeStartRequest() && !uncertain.current && !pendingRequest()) {
          setInitialNotStarted(true);
        }
      } }
      if (!disposed) timer = setTimeout(refresh, 2000);
    };
    void refresh();
    return () => { disposed = true; mounted.current = false; epoch.current++; clearTimeout(timer); modal.current?.Close(); modal.current = null; };
  }, []);
  const view = dockIntentControl(reading?.status, reading?.snapshot, intent);
  const confirm = (direct=false, candidate=reading) => {
    const action = dockIntentControl(candidate?.status,candidate?.snapshot,intent).action;
    const attachment = candidate?.status?.attachment_token ?? "";
    if (!action || pending.current || uncertain.current || pendingRequest()) return;
    pending.current = true; setBusy(true);
    let decided = false;
    const cancel = () => { if (decided) return; decided = true; pending.current = false; modal.current?.Close(); modal.current = null; if (mounted.current) setBusy(false); };
    const run = async () => {
      if (decided) return;
      decided = true;
      epoch.current++;
      modal.current?.Close(); modal.current = null;
      try {
        if (currentIntent.current !== intent) { if (mounted.current) setNotice("Action changed. Review the current choice."); return; }
        const fresh = await read();
        if (!mounted.current) return;
        if (pendingRequest()) { uncertain.current = true; setNotice("Waiting to verify the previous request. Keep the cable connected."); return; }
        if (currentIntent.current !== intent || dockIntentControl(fresh.status, fresh.snapshot, intent).action !== action
            || fresh.status?.attachment_token !== attachment) {
          setReading(fresh); setNotice("Status changed. Review the current reading."); return;
        }
        const request = crypto.randomUUID().replaceAll("-", "");
        window.localStorage.setItem(pendingKey, formatPendingRecord(intent, panelId, request));
        if (typeof startRequest === "function" && "markSubmitted" in startRequest) startRequest.markSubmitted();
        uncertain.current = true;
        setNotice(action === "whole_dock_shutdown" ? "Shutdown request sent. Keep the cable connected; Gaming Mode may restart before shutdown."
          : action === "whole_dock_sleep" ? "Disconnect started. Keep the cable connected until Re-Gear asks you to unplug it."
          : "Request sent. Keep the cable connected; Gaming Mode may restart.");
        const result = await execute(true, "", "disconnect", action, true, attachment, request);
        epoch.current++;
        if (mounted.current) { setReading({ ...fresh, status: result }); setNotice(""); }
        if (dockRequestSettled(result, request, intent)) {
          if (onSettled) onSettled({ intent, request });
          else window.localStorage.removeItem(pendingKey);
          uncertain.current = false;
        }
      } catch {
        if (mounted.current) {
          if (directStartState(startRequest) === "consumed" && !pendingRequest()) setInitialNotStarted(true);
          else setNotice("The reply was interrupted. Waiting for backend progress; no retry was sent.");
        }
      } finally { pending.current = false; if (mounted.current) setBusy(false); }
    };
    // One press. `direct` is set only when a named tile activated this mount:
    // native.tsx passes a one-shot startRequest when the player presses
    // "Safe Disconnect" or "Disconnect + Shutdown", so
    // the press that opened this modal IS the explicit choice of this exact
    // action, and a second dialog asks the same question twice. The route
    // selector inside the Safe Disconnect detail passes no startRequest, so a
    // route chosen from a dropdown still confirms before anything happens.
    if(direct) { void run(); return; }
    modal.current = showModal(<EgpuConfirmModal strTitle={action === "whole_dock_shutdown" ? "Disconnect the dock and shut down?" : action === "whole_dock_sleep" ? "Disconnect, unplug, and sleep?" : "Disconnect the dock in software?"}
      strDescription={action === "whole_dock_shutdown" ? "Re-Gear will disconnect the dock in software, verify the result, then request shutdown. The TV will turn off and Gaming Mode may restart first. Save your work and keep the cable connected. Shutdown is not yet hardware-verified; this is not permission to unplug."
        : action === "whole_dock_sleep" ? "Re-Gear will return to the handheld and disconnect the eGPU in software. Keep the cable connected until the urgent unplug prompt appears. Sleep starts only after physical absence is verified."
        : "The TV will turn off and Gaming Mode may restart. Keep the dock cable connected for this trial. This is not permission to unplug."}
      strOKButtonText={action === "whole_dock_shutdown" ? "Disconnect and shut down" : action === "whole_dock_sleep" ? "Disconnect and sleep" : "Disconnect"} strCancelButtonText="Cancel"
      className="rg-whole-dock-confirm" bDestructiveWarning onOK={() => { void run(); }} onCancel={cancel} onEscKeypress={cancel}>
      <style>{`.rg-whole-dock-confirm{z-index:2147483647!important;position:fixed!important;left:50%!important;top:50%!important;right:auto!important;bottom:auto!important;margin:0!important;transform:translate(-50%,-50%)!important}`}</style>
    </EgpuConfirmModal>, undefined, { fnOnClose: cancel, bNeverPopOut: true });
  };
  const terminalRecord = parsePendingRecord(pendingRecord());
  const terminalObservedAt = Date.parse(reading?.snapshot?.observed_at ?? "");
  const terminalNow = Date.now();
  const terminalSnapshotFresh = reading?.snapshot?.schema_version === 3
    && Number.isFinite(terminalObservedAt)
    && terminalObservedAt <= terminalNow
    && terminalNow - terminalObservedAt < 10_000;
  const disconnectComplete = intent === "disconnect_only"
    && terminalRecord?.intent === "disconnect_only"
    && reading?.status?.request_id === terminalRecord.request
    && terminalSnapshotFresh
    && reading?.status?.schema_version === 1
    && reading.status.code === "dock_teardown.software_down"
    && reading.status.busy === false && reading.status.ok === true
    && reading.status.software_down === true && reading.status.safe_to_unplug === false;
  return <div style={{fontSize:13,lineHeight:"18px"}}>
    <p style={{margin:"0 0 8px"}} role="status">{(initialNotStarted && !uncertain.current && !pendingRequest()) ? `Safe Disconnect did not start. No request was sent by this attempt. ${view.message}` : notice || (uncertain.current ? "Waiting to verify the previous request. Keep the cable connected." : disconnectComplete ? "Software disconnect complete. USB4 deauthorization was verified." : view.message)}</p>
    {startRequest && initialNotStarted && !pending.current && !uncertain.current && !pendingRequest() && <DialogButton {...{type:"button" as const}} style={{width:"100%",minWidth:0,padding:"8px",border:"1px solid #39d8ff",borderRadius:8,background:"#112434",color:"#f4f7fb"}} disabled={!view.action || busy} onClick={(event)=>{
      event?.preventDefault(); event?.stopPropagation();
      if (!mounted.current || !view.action || pending.current || uncertain.current || pendingRequest()) return;
      setInitialNotStarted(false);
      confirm(true,reading);
    }}>{intent === "sleep" ? "Disconnect + Sleep" : intent === "shutdown" ? "Safe Disconnect + Shutdown" : "Safe Disconnect"}</DialogButton>}
    {!startRequest && !statusOnly && <DialogButton style={{width:"100%",minWidth:0,padding:"8px",border:"1px solid #39d8ff",borderRadius:8,background:"#112434",color:"#f4f7fb"}} disabled={!view.action || busy || uncertain.current} onClick={()=>confirm()}>{busy ? "Working…" : uncertain.current ? "Checking previous request" : view.label}</DialogButton>}
    <p style={{margin:"8px 0 0"}}>{disconnectComplete
      ? "Unplug the eGPU now. Do not leave the powered dock attached in this state."
      : intent === "sleep" && reading?.status?.code === "dock_power.unplug_required"
      ? "Unplug only after this prompt appears. Sleep waits for verified physical absence."
      : "Keep the cable connected. Physical unplug is not yet verified."}</p>
  </div>;
}
