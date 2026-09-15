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

/** Only confirmed clicks mutate. Reopening the menu recovers backend progress. */
export function WholeDockControl({ readCurrentSnapshot, intent = "disconnect", startRequest }: { readCurrentSnapshot: () => any; intent?: DockIntent; startRequest?:()=>boolean }) {
  const source = useRef(readCurrentSnapshot);
  source.current = readCurrentSnapshot;
  const currentIntent = useRef(intent);
  currentIntent.current = intent;
  const read = async () => ({ status: await readTrial("whole_dock_trial"), snapshot: source.current() });
  const [reading, setReading] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const mounted = useRef(true);
  const pending = useRef(false);
  const uncertain = useRef(!!pendingRequest());
  const epoch = useRef(0);
  const modal = useRef<ReturnType<typeof showModal> | null>(null);
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
        if (record && (abandoned || dockRequestSettled(next.status, record.request, record.intent))) {
          window.localStorage.removeItem(pendingKey);
          uncertain.current = false;
          if (abandoned && mounted.current) {
            setNotice("Re-Gear could not confirm how the previous request ended, so it stopped waiting. Check the status below before trying again. Keep the cable connected.");
          }
        }
        setReading(next);
        if(startRequest?.()) confirm(true,next);
      } catch { if (!disposed && started === epoch.current) { setReading(null); startRequest?.(); } }
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
        uncertain.current = true;
        setNotice(action === "whole_dock_shutdown" ? "Shutdown request sent. Keep the cable connected; Gaming Mode may restart before shutdown." : "Request sent. Keep the cable connected; Gaming Mode may restart.");
        const result = await execute(true, "", "disconnect", action, true, attachment, request);
        epoch.current++;
        if (mounted.current) { setReading({ ...fresh, status: result }); setNotice(""); }
        if (dockRequestSettled(result, request, intent)) {
          window.localStorage.removeItem(pendingKey); uncertain.current = false;
        }
      } catch {
        if (mounted.current) setNotice("The reply was interrupted. Waiting for backend progress; no retry was sent.");
      } finally { pending.current = false; if (mounted.current) setBusy(false); }
    };
    if(direct && intent==="disconnect_only") { void run(); return; }
    modal.current = showModal(<EgpuConfirmModal strTitle={action === "whole_dock_shutdown" ? "Disconnect the dock and shut down?" : "Disconnect the dock in software?"}
      strDescription={action === "whole_dock_shutdown" ? "Re-Gear will disconnect the dock in software, verify the result, then request shutdown. The TV will turn off and Gaming Mode may restart first. Save your work and keep the cable connected. Shutdown is not yet hardware-verified; this is not permission to unplug." : "The TV will turn off and Gaming Mode may restart. Keep the dock cable connected for this trial. This is not permission to unplug."}
      strOKButtonText={action === "whole_dock_shutdown" ? "Disconnect and shut down" : "Disconnect"} strCancelButtonText="Cancel"
      className="rg-whole-dock-confirm" bDestructiveWarning onOK={() => { void run(); }} onCancel={cancel} onEscKeypress={cancel}>
      <style>{`.rg-whole-dock-confirm{z-index:2147483647!important;position:fixed!important;left:50%!important;top:50%!important;right:auto!important;bottom:auto!important;margin:0!important;transform:translate(-50%,-50%)!important}`}</style>
    </EgpuConfirmModal>, undefined, { fnOnClose: cancel, bNeverPopOut: true });
  };
  return <div style={{fontSize:13,lineHeight:"18px"}}>
    <p style={{margin:"0 0 8px"}} role="status">{notice || (uncertain.current ? "Waiting to verify the previous request. Keep the cable connected." : view.message)}</p>
    {!startRequest && <DialogButton style={{width:"100%",minWidth:0,padding:"8px",border:"1px solid #39d8ff",borderRadius:8,background:"#112434",color:"#f4f7fb"}} disabled={!view.action || busy || uncertain.current} onClick={()=>confirm()}>{busy ? "Working…" : uncertain.current ? "Checking previous request" : view.label}</DialogButton>}
    <p style={{margin:"8px 0 0"}}>Keep the cable connected. Physical unplug is not yet verified.</p>
  </div>;
}
